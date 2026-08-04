from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from backtrajectory import (
    Detection,
    OpenMeteoProvider,
    TrajectoryPoint,
    LaunchEstimate,
    Zone,
)

EARTH_RADIUS_M = 6_371_000.0


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _destination(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    distance = math.hypot(east_m, north_m)
    if distance < 1e-12:
        return lat, lon
    bearing = math.atan2(east_m, north_m)
    angular = distance / EARTH_RADIUS_M
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
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
    """Interpolate provider states over the surrounding rectangular cells.

    The existing provider interpolates time and height but selects the nearest
    horizontal cell. Here we perform the missing horizontal interpolation by
    evaluating the provider at the four surrounding grid nodes.
    """
    cells = provider.cells
    if not cells:
        raise RuntimeError("Метеоданные не загружены.")

    nodes = [(float(c["latitude"]), float(c["longitude"])) for c in cells]
    lats = sorted({x[0] for x in nodes})
    lons = sorted({x[1] for x in nodes})

    def bracket(values: list[float], value: float) -> tuple[float, float, float]:
        if value <= values[0]:
            return values[0], values[0], 0.0
        if value >= values[-1]:
            return values[-1], values[-1], 0.0
        hi = next(i for i, v in enumerate(values) if v >= value)
        lo = hi - 1
        a, b = values[lo], values[hi]
        return a, b, (value - a) / (b - a) if b != a else 0.0

    lat0, lat1, fy = bracket(lats, lat)
    lon0, lon1, fx = bracket(lons, lon)

    def state_at(a: float, b: float):
        return provider.state(a, b, altitude, when)

    s00 = state_at(lat0, lon0)
    s01 = state_at(lat0, lon1)
    s10 = state_at(lat1, lon0)
    s11 = state_at(lat1, lon1)

    def blend(a, b, c, d):
        return (
            a * (1 - fx) * (1 - fy)
            + b * fx * (1 - fy)
            + c * (1 - fx) * fy
            + d * fx * fy
        )

    u = blend(s00.u_mps, s01.u_mps, s10.u_mps, s11.u_mps)
    v = blend(s00.v_mps, s01.v_mps, s10.v_mps, s11.v_mps)
    temp = blend(s00.temperature_k, s01.temperature_k, s10.temperature_k, s11.temperature_k)
    pressure = blend(s00.pressure_pa, s01.pressure_pa, s10.pressure_pa, s11.pressure_pa)
    geopotential = blend(s00.geopotential_m2s2, s01.geopotential_m2s2, s10.geopotential_m2s2, s11.geopotential_m2s2)
    return u, v, temp, pressure, geopotential


class BackTrajectorySolver:
    """Backward integration using the same RK4/geodesic kinematics as forward.py.

    The only mathematical reversal is the sign of dt. This makes a forward
    trajectory and a backward trajectory reversible for the same wind field.
    """

    def __init__(self, weather: OpenMeteoProvider, balloon: Any, step_seconds: float = 300.0, max_duration_hours: float = 48.0):
        self.weather = weather
        self.balloon = balloon
        self.step_seconds = float(step_seconds)
        self.max_duration_hours = float(max_duration_hours)

    def _derivative(self, lat, lon, altitude, when, wind_du=(0.0, 0.0)):
        u, v, *_ = _bilinear_state(self.weather, lat, lon, altitude, when)
        return u + wind_du[0], v + wind_du[1], self.balloon.ascent_rate_mps

    def solve(self, detection: Detection, duration_hours: float | None = None) -> list[dict]:
        duration = min(float(duration_hours or self.max_duration_hours), self.max_duration_hours)
        dt = -abs(self.step_seconds)
        remaining = duration * 3600.0
        lat, lon = detection.lat, detection.lon
        altitude = detection.altitude_m
        when = _utc(detection.time)
        points: list[dict] = []

        def append_point():
            u, v, *_ = _bilinear_state(self.weather, lat, lon, altitude, when)
            speed, direction = _uv_to_wind(u, v)
            points.append({
                "time": when.isoformat(),
                "lat": lat,
                "lon": lon,
                "altitude_m": max(0.0, altitude),
                "u_mps": u,
                "v_mps": v,
                "wind_speed_mps": speed,
                "wind_direction": direction,
            })

        append_point()
        while remaining > 1e-9 and altitude > 0.0:
            h = min(abs(dt), remaining)
            step = -h
            k1u, k1v, k1z = self._derivative(lat, lon, altitude, when)
            a2 = max(0.0, altitude + k1z * step / 2.0)
            lat2, lon2 = _destination(lat, lon, k1u * step / 2.0, k1v * step / 2.0)
            t2 = when + timedelta(seconds=step / 2.0)
            k2u, k2v, k2z = self._derivative(lat2, lon2, a2, t2)
            a3 = max(0.0, altitude + k2z * step / 2.0)
            lat3, lon3 = _destination(lat, lon, k2u * step / 2.0, k2v * step / 2.0)
            k3u, k3v, k3z = self._derivative(lat3, lon3, a3, t2)
            a4 = max(0.0, altitude + k3z * step)
            lat4, lon4 = _destination(lat, lon, k3u * step, k3v * step)
            t4 = when + timedelta(seconds=step)
            k4u, k4v, k4z = self._derivative(lat4, lon4, a4, t4)

            east = step / 6.0 * (k1u + 2*k2u + 2*k3u + k4u)
            north = step / 6.0 * (k1v + 2*k2v + 2*k3v + k4v)
            vertical = step / 6.0 * (k1z + 2*k2z + 2*k3z + k4z)
            lat, lon = _destination(lat, lon, east, north)
            altitude = max(0.0, altitude + vertical)
            when += timedelta(seconds=step)
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
        trajectories: list[list[dict]] = []
        launch_points: list[tuple[float, float, float]] = []
        valid = 0

        for _ in range(self.members):
            t = _utc(detection.time) + timedelta(seconds=rng.gauss(0.0, self.detection_time_sigma_s))
            z = max(0.0, detection.altitude_m + rng.gauss(0.0, self.altitude_sigma_m))
            ascent = max(0.2, rng.gauss(self.solver.balloon.ascent_rate_mps, self.solver.balloon.ascent_rate_sigma_mps))
            member_solver = BackTrajectorySolver(
                weather=self.solver.weather,
                balloon=BalloonModel(ascent_rate_mps=ascent, ascent_rate_sigma_mps=0.0),
                step_seconds=self.solver.step_seconds,
                max_duration_hours=self.solver.max_duration_hours,
            )
            # Wind uncertainty is applied as a smooth member-level vector bias.
            # It is deliberately fixed through the trajectory, avoiding white-noise jitter.
            wind_du = rng.gauss(0.0, self.wind_sigma_mps)
            wind_dv = rng.gauss(0.0, self.wind_sigma_mps)
            original = member_solver._derivative
            member_solver._derivative = lambda lat, lon, altitude, when, _du=wind_du, _dv=wind_dv: original(lat, lon, altitude, when, (_du, _dv))
            try:
                points = member_solver.solve(Detection(detection.lat, detection.lon, z, t), self.solver.max_duration_hours)
            except (RuntimeError, ValueError, IndexError, KeyError):
                continue
            if points:
                valid += 1
                trajectories.append(points)
                p = points[-1]
                launch_points.append((p["lat"], p["lon"], p["altitude_m"]))

        if not launch_points:
            raise RuntimeError("Не удалось построить ни одной обратной траектории.")

        arr = np.asarray([[p[0], p[1]] for p in launch_points], dtype=float)
        center_lat = float(np.mean(arr[:, 0]))
        center_lon = float(np.mean(arr[:, 1]))
        distances = np.asarray([
            _destination_distance_m(center_lat, center_lon, p[0], p[1]) for p in launch_points
        ])
        zones = [
            {"probability": 0.50, "radius_m": float(np.quantile(distances, 0.50)), "center_lat": center_lat, "center_lon": center_lon},
            {"probability": 0.80, "radius_m": float(np.quantile(distances, 0.80)), "center_lat": center_lat, "center_lon": center_lon},
            {"probability": 0.95, "radius_m": float(np.quantile(distances, 0.95)), "center_lat": center_lat, "center_lon": center_lon},
        ]
        best = launch_points[int(np.argmin(distances))]
        launch_time = trajectories[int(np.argmin(distances))][-1]["time"]
        estimate = {"lat": best[0], "lon": best[1], "time": launch_time, "altitude_m": best[2]}
        return EnsembleResult(
            detection={"lat": detection.lat, "lon": detection.lon, "altitude_m": detection.altitude_m, "time": _utc(detection.time).isoformat()},
            launch_estimate=estimate,
            zones=zones,
            ensemble_size=self.members,
            valid_members=valid,
            trajectories=trajectories,
        )


def _destination_distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*EARTH_RADIUS_M*math.asin(math.sqrt(max(0.0, min(1.0, a))))
