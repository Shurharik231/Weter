from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from backtrajectory import Detection, OpenMeteoProvider

EARTH_RADIUS_M = 6_371_000.0
DEFAULT_MAX_ALTITUDE_M = 10_000.0


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _destination(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    distance = math.hypot(east_m, north_m)
    if distance < 1e-12:
        return lat, lon
    bearing = math.atan2(east_m, north_m)
    angular = distance / EARTH_RADIUS_M
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(angular) + math.cos(lat1) * math.sin(angular) * math.cos(bearing))
    lon2 = lon1 + math.atan2(math.sin(bearing) * math.sin(angular) * math.cos(lat1), math.cos(angular) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), (math.degrees(lon2) + 540.0) % 360.0 - 180.0


def _wind_to_uv(speed: float, direction_from: float) -> tuple[float, float]:
    towards = math.radians((direction_from + 180.0) % 360.0)
    return math.sin(towards) * speed, math.cos(towards) * speed


def _uv_to_wind(u: float, v: float) -> tuple[float, float]:
    speed = math.hypot(u, v)
    if speed < 1e-9:
        return 0.0, 0.0
    towards = (math.degrees(math.atan2(u, v)) + 360.0) % 360.0
    return speed, (towards + 180.0) % 360.0


def _bilinear_state(provider: OpenMeteoProvider, lat: float, lon: float, altitude: float, when: datetime):
    cells = provider.cells
    if not cells:
        raise RuntimeError("Метеоданные не загружены.")
    lats = sorted({float(c["latitude"]) for c in cells})
    lons = sorted({float(c["longitude"]) for c in cells})

    def bracket(values: list[float], value: float):
        if value <= values[0]: return values[0], values[0], 0.0
        if value >= values[-1]: return values[-1], values[-1], 0.0
        hi = next(i for i, v in enumerate(values) if v >= value)
        lo = hi - 1
        a, b = values[lo], values[hi]
        return a, b, (value - a) / (b - a) if b != a else 0.0

    lat0, lat1, fy = bracket(lats, lat)
    lon0, lon1, fx = bracket(lons, lon)
    lookup = {(round(float(c["latitude"]), 6), round(float(c["longitude"]), 6)): c for c in cells}

    def state_at(a, b):
        cell = lookup.get((round(a, 6), round(b, 6)))
        if cell is None:
            return provider.state(a, b, altitude, when)
        # OpenMeteoProvider.state() performs time + height interpolation at this exact grid node.
        return provider.state(float(cell["latitude"]), float(cell["longitude"]), altitude, when)

    s00, s01, s10, s11 = state_at(lat0, lon0), state_at(lat0, lon1), state_at(lat1, lon0), state_at(lat1, lon1)

    def blend(a, b, c, d):
        return a * (1-fx) * (1-fy) + b * fx * (1-fy) + c * (1-fx) * fy + d * fx * fy

    return (
        blend(s00.u_mps, s01.u_mps, s10.u_mps, s11.u_mps),
        blend(s00.v_mps, s01.v_mps, s10.v_mps, s11.v_mps),
        blend(s00.temperature_k, s01.temperature_k, s10.temperature_k, s11.temperature_k),
        blend(s00.pressure_pa, s01.pressure_pa, s10.pressure_pa, s11.pressure_pa),
        blend(s00.geopotential_m2s2, s01.geopotential_m2s2, s10.geopotential_m2s2, s11.geopotential_m2s2),
    )


class BackTrajectorySolver:
    """Reverse of the same kinematic model used by trajectory.py.

    RK4 stages, geodesic displacement, vector wind conversion, time/height
    interpolation and ascent law are kept equivalent. Negative dt is the only
    integration-direction change. The ascent plateau is handled explicitly so
    a trajectory that reached max altitude stays there while reversed until its
    launch transition, then descends to the starting altitude.
    """

    def __init__(self, weather: OpenMeteoProvider, balloon: Any, step_seconds: float = 300.0, max_duration_hours: float = 48.0):
        self.weather = weather
        self.balloon = balloon
        self.step_seconds = float(step_seconds)
        self.max_duration_hours = float(max_duration_hours)

    def _wind(self, lat, lon, altitude, when, wind_du=(0.0, 0.0)):
        u, v, *_ = _bilinear_state(self.weather, lat, lon, altitude, when)
        return u + wind_du[0], v + wind_du[1]

    def solve(self, detection: Detection, duration_hours: float | None = None, start_altitude: float = 0.0) -> list[dict]:
        duration = min(float(duration_hours or self.max_duration_hours), self.max_duration_hours)
        step_abs = abs(self.step_seconds)
        remaining = duration * 3600.0
        back_elapsed = 0.0
        lat, lon = detection.lat, detection.lon
        altitude = max(0.0, detection.altitude_m)
        when = _utc(detection.time)
        ascent = max(0.01, float(self.balloon.ascent_rate_mps))
        max_altitude = max(DEFAULT_MAX_ALTITUDE_M, altitude)
        # If detection is at/near the configured/default ceiling, assume the
        # balloon reached that ceiling and then drifted there. Otherwise it was
        # still ascending at detection and reverse integration descends directly.
        on_plateau = altitude >= 0.95 * max_altitude
        ascent_time = max(0.0, (max_altitude - start_altitude) / ascent) if on_plateau else 0.0
        plateau_duration = max(0.0, duration * 3600.0 - ascent_time) if on_plateau else 0.0
        points: list[dict] = []

        def append_point():
            u, v = self._wind(lat, lon, altitude, when)
            speed, direction = _uv_to_wind(u, v)
            points.append({
                "time": when.isoformat(), "lat": lat, "lon": lon,
                "altitude_m": max(0.0, altitude), "u_mps": u, "v_mps": v,
                "wind_speed_mps": speed, "wind_direction": direction,
            })

        def vertical_rate(elapsed: float) -> float:
            if altitude <= start_altitude + 1e-6:
                return 0.0
            if on_plateau and elapsed < plateau_duration:
                return 0.0
            return ascent

        append_point()
        while remaining > 1e-9 and altitude > start_altitude + 1e-6:
            h = min(step_abs, remaining)
            dt = -h
            k1u, k1v = self._wind(lat, lon, altitude, when)
            k1z = vertical_rate(back_elapsed)
            a2 = max(start_altitude, altitude + k1z * dt / 2)
            lat2, lon2 = _destination(lat, lon, k1u * dt / 2, k1v * dt / 2)
            t2 = when + timedelta(seconds=dt/2)
            k2u, k2v = self._wind(lat2, lon2, a2, t2)
            k2z = ascent if (not on_plateau or back_elapsed + h/2 >= plateau_duration) else 0.0
            a3 = max(start_altitude, altitude + k2z * dt / 2)
            lat3, lon3 = _destination(lat, lon, k2u * dt / 2, k2v * dt / 2)
            k3u, k3v = self._wind(lat3, lon3, a3, t2)
            k3z = ascent if (not on_plateau or back_elapsed + h/2 >= plateau_duration) else 0.0
            a4 = max(start_altitude, altitude + k3z * dt)
            lat4, lon4 = _destination(lat, lon, k3u * dt, k3v * dt)
            t4 = when + timedelta(seconds=dt)
            k4u, k4v = self._wind(lat4, lon4, a4, t4)
            k4z = ascent if (not on_plateau or back_elapsed + h >= plateau_duration) else 0.0

            east = dt / 6 * (k1u + 2*k2u + 2*k3u + k4u)
            north = dt / 6 * (k1v + 2*k2v + 2*k3v + k4v)
            vertical = dt / 6 * (k1z + 2*k2z + 2*k3z + k4z)
            lat, lon = _destination(lat, lon, east, north)
            altitude = max(start_altitude, altitude + vertical)
            when += timedelta(seconds=dt)
            back_elapsed += h
            remaining -= h
            append_point()

        return points


@dataclass
class BalloonModel:
    ascent_rate_mps: float = 5.0
    ascent_rate_sigma_mps: float = 0.7


@dataclass
class EnsembleResult:
    detection: dict
    launch_estimate: dict
    zones: list[dict]
    ensemble_size: int
    valid_members: int
    trajectories: list[list[dict]]


class EnsembleEstimator:
    def __init__(self, solver: BackTrajectorySolver, members: int = 150, wind_sigma_mps: float = 1.5, detection_time_sigma_s: float = 60.0, altitude_sigma_m: float = 50.0, seed: int = 42):
        self.solver = solver
        self.members = int(members)
        self.wind_sigma_mps = float(wind_sigma_mps)
        self.detection_time_sigma_s = float(detection_time_sigma_s)
        self.altitude_sigma_m = float(altitude_sigma_m)
        self.seed = seed

    def run(self, detection: Detection) -> EnsembleResult:
        rng = random.Random(self.seed)
        trajectories, launch_points = [], []
        valid = 0
        for _ in range(self.members):
            t = _utc(detection.time) + timedelta(seconds=rng.gauss(0.0, self.detection_time_sigma_s))
            z = max(0.0, detection.altitude_m + rng.gauss(0.0, self.altitude_sigma_m))
            ascent = max(0.2, rng.gauss(self.solver.balloon.ascent_rate_mps, self.solver.balloon.ascent_rate_sigma_mps))
            member_solver = BackTrajectorySolver(self.solver.weather, BalloonModel(ascent, 0.0), self.solver.step_seconds, self.solver.max_duration_hours)
            du, dv = rng.gauss(0.0, self.wind_sigma_mps), rng.gauss(0.0, self.wind_sigma_mps)
            original_wind = member_solver._wind
            member_solver._wind = lambda lat, lon, alt, tm, _du=du, _dv=dv: original_wind(lat, lon, alt, tm, (_du, _dv))
            try:
                points = member_solver.solve(Detection(detection.lat, detection.lon, z, t), self.solver.max_duration_hours)
            except (RuntimeError, ValueError, IndexError, KeyError):
                continue
            if points:
                valid += 1
                trajectories.append(points)
                launch_points.append((points[-1]["lat"], points[-1]["lon"], points[-1]["altitude_m"], points[-1]["time"]))

        if not launch_points:
            raise RuntimeError("Не удалось построить ни одной обратной траектории.")
        arr = np.asarray([[p[0], p[1]] for p in launch_points], dtype=float)
        center_lat, center_lon = float(np.mean(arr[:,0])), float(np.mean(arr[:,1]))
        distances = np.asarray([_distance_m(center_lat, center_lon, p[0], p[1]) for p in launch_points])
        zones = [{"probability": p, "radius_m": float(np.quantile(distances, p)), "center_lat": center_lat, "center_lon": center_lon} for p in (0.50, 0.80, 0.95)]
        best_index = int(np.argmin(distances)); best = launch_points[best_index]
        return EnsembleResult(
            detection={"lat": detection.lat, "lon": detection.lon, "altitude_m": detection.altitude_m, "time": _utc(detection.time).isoformat()},
            launch_estimate={"lat": best[0], "lon": best[1], "time": best[3], "altitude_m": best[2]},
            zones=zones, ensemble_size=self.members, valid_members=valid, trajectories=trajectories,
        )


def _distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(max(0.0, min(1.0, a))))
