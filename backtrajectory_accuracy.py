from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime, timezone
from typing import Any

import numpy as np

from backtrajectory import (
    AtmosphericState,
    BackTrajectorySolver,
    Detection,
    EnsembleEstimator,
    OpenMeteoProvider,
    Result,
    _wind_to_uv,
)


class AccurateOpenMeteoProvider(OpenMeteoProvider):
    """Backtrajectory provider with bilinear horizontal interpolation.

    The base implementation selects the nearest meteorological cell. For a
    trajectory moving across a coarse 5x5 grid that can introduce artificial
    jumps when crossing a cell boundary. This class interpolates the wind
    vector and thermodynamic state between the four surrounding cells.
    """

    @staticmethod
    def _surrounding(values: list[float], target: float) -> tuple[float, float, float]:
        if target <= values[0]:
            return values[0], values[0], 0.0
        if target >= values[-1]:
            return values[-1], values[-1], 0.0
        i1 = bisect_right(values, target)
        a, b = values[i1 - 1], values[i1]
        f = (target - a) / (b - a) if b != a else 0.0
        return a, b, f

    def _state_cell(self, cell: dict[str, Any], altitude_m: float, time: datetime) -> AtmosphericState:
        hourly = cell["hourly"]
        times = [datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc) for t in hourly["time"]]
        if time < times[0] or time > times[-1]:
            raise ValueError("Время вне загруженного метеорологического ряда.")
        if time == times[-1]:
            t0 = t1 = len(times) - 1
            tf = 0.0
        else:
            t1 = bisect_right(times, time)
            t0 = max(0, t1 - 1)
            span = (times[t1] - times[t0]).total_seconds()
            tf = (time - times[t0]).total_seconds() / span if span > 0 else 0.0

        vectors = []
        for pressure_hpa, level in self._variables_by_level():
            try:
                s0 = float(hourly[f"wind_speed_{level}"][t0]); s1 = float(hourly[f"wind_speed_{level}"][t1])
                d0 = float(hourly[f"wind_direction_{level}"][t0]); d1 = float(hourly[f"wind_direction_{level}"][t1])
                temp0 = float(hourly[f"temperature_{level}"][t0]); temp1 = float(hourly[f"temperature_{level}"][t1])
                h0 = float(hourly[f"geopotential_height_{level}"][t0]); h1 = float(hourly[f"geopotential_height_{level}"][t1])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            e0, n0 = _wind_to_uv(s0, d0); e1, n1 = _wind_to_uv(s1, d1)
            vectors.append((h0 + (h1 - h0) * tf, e0 + (e1 - e0) * tf, n0 + (n1 - n0) * tf,
                            temp0 + (temp1 - temp0) * tf, float(pressure_hpa)))
        if not vectors:
            raise ValueError("Нет данных ветра для выбранного времени/места.")
        vectors.sort(key=lambda x: x[0])
        if altitude_m <= vectors[0][0]:
            h, u, v, temp_c, pressure_hpa = vectors[0]
        elif altitude_m >= vectors[-1][0]:
            h, u, v, temp_c, pressure_hpa = vectors[-1]
        else:
            h = altitude_m
            u = v = temp_c = pressure_hpa = 0.0
            for a, b in zip(vectors, vectors[1:]):
                h0, u0, v0, t0, p0 = a; h1, u1, v1, t1, p1 = b
                if h0 <= altitude_m <= h1:
                    f = (altitude_m - h0) / (h1 - h0) if abs(h1 - h0) > 0.1 else 0.0
                    u = u0 + (u1 - u0) * f; v = v0 + (v1 - v0) * f
                    temp_c = t0 + (t1 - t0) * f
                    pressure_hpa = math.exp(math.log(p0) + (math.log(p1) - math.log(p0)) * f)
                    break
        return AtmosphericState(u_mps=u, v_mps=v, temperature_k=temp_c + 273.15,
                                pressure_pa=pressure_hpa * 100.0,
                                geopotential_m2s2=h * 9.80665, altitude_m=h)

    @staticmethod
    def _variables_by_level():
        return [(1000,"1000hPa"),(975,"975hPa"),(950,"950hPa"),(925,"925hPa"),(900,"900hPa"),(850,"850hPa"),(800,"800hPa"),(700,"700hPa"),(600,"600hPa"),(500,"500hPa"),(400,"400hPa"),(300,"300hPa"),(250,"250hPa"),(200,"200hPa")]

    def state(self, lat: float, lon: float, altitude_m: float, time: datetime) -> AtmosphericState:
        if not self.cells or not self.times:
            raise RuntimeError("Данные Open-Meteo ещё не загружены.")
        lats = sorted(float(c["latitude"]) for c in self.cells)
        lons = sorted(float(c["longitude"]) for c in self.cells)
        lat0, lat1, fy = self._surrounding(lats, lat)
        lon0, lon1, fx = self._surrounding(lons, lon)
        lookup = {(round(float(c["latitude"]), 6), round(float(c["longitude"]), 6)): c for c in self.cells}
        cells = [lookup.get((round(a, 6), round(b, 6))) for a, b in ((lat0, lon0),(lat0, lon1),(lat1, lon0),(lat1, lon1))]
        if any(c is None for c in cells):
            return super().state(lat, lon, altitude_m, time)
        states = [self._state_cell(c, altitude_m, time) for c in cells]
        def bilinear(attr: str) -> float:
            v00 = getattr(states[0], attr); v01 = getattr(states[1], attr)
            v10 = getattr(states[2], attr); v11 = getattr(states[3], attr)
            a = v00 + (v01 - v00) * fx; b = v10 + (v11 - v10) * fx
            return a + (b - a) * fy
        return AtmosphericState(u_mps=bilinear("u_mps"), v_mps=bilinear("v_mps"),
                                temperature_k=bilinear("temperature_k"), pressure_pa=bilinear("pressure_pa"),
                                geopotential_m2s2=bilinear("geopotential_m2s2"), altitude_m=altitude_m)


class AccurateBackTrajectorySolver(BackTrajectorySolver):
    """Backtrajectory solver with a member-specific, altitude-scaled wind bias."""

    def __init__(self, *args, wind_bias_e_mps: float = 0.0, wind_bias_n_mps: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.wind_bias_e_mps = wind_bias_e_mps
        self.wind_bias_n_mps = wind_bias_n_mps

    def _derivative(self, lat, lon, altitude, time, rng):
        east, north, vertical, state = super()._derivative(lat, lon, altitude, time, rng)
        # Forecast errors are not constant with height; taper the perturbation
        # above the lower troposphere rather than injecting the same error everywhere.
        factor = 0.65 + 0.35 * min(max(altitude / 10000.0, 0.0), 1.0)
        return east - self.wind_bias_e_mps * factor, north - self.wind_bias_n_mps * factor, vertical, state


class AccurateEnsembleEstimator(EnsembleEstimator):
    """Ensemble with member-specific correlated wind bias plus observation uncertainty."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self, detection: Detection) -> Result:
        # Keep the parent result contract but make wind_sigma_mps actually
        # influence every member through a coherent vector bias.
        launches = []
        all_trajectories = []
        for _ in range(self.members):
            dt_error = self.rng.normal(0.0, self.detection_time_sigma_s)
            altitude_error = self.rng.normal(0.0, self.altitude_sigma_m)
            wind_e = self.rng.normal(0.0, self.wind_sigma_mps)
            wind_n = self.rng.normal(0.0, self.wind_sigma_mps)
            member_detection = Detection(detection.lat, detection.lon,
                                         max(100.0, detection.altitude_m + altitude_error),
                                         detection.time + __import__('datetime').timedelta(seconds=float(dt_error)))
            solver = self.solver
            old_e = getattr(solver, "wind_bias_e_mps", 0.0); old_n = getattr(solver, "wind_bias_n_mps", 0.0)
            solver.wind_bias_e_mps = float(wind_e); solver.wind_bias_n_mps = float(wind_n)
            try:
                trajectory, launch = solver.integrate(member_detection, self.rng)
                launches.append((launch.lat, launch.lon, launch.time))
                all_trajectories.append([p.__dict__.copy() for p in trajectory])
            except (ValueError, RuntimeError, IndexError, KeyError):
                continue
            finally:
                solver.wind_bias_e_mps = old_e; solver.wind_bias_n_mps = old_n
        if not launches:
            raise RuntimeError("Ни одна ансамблевая траектория не завершилась успешно.")
        launch_array = np.array([[x[0], x[1]] for x in launches], dtype=float)
        center_lat = float(np.mean(launch_array[:, 0])); center_lon = float(np.mean(launch_array[:, 1]))
        from backtrajectory import Zone, LaunchEstimate, percentile_radius
        zones = [Zone(probability=p, radius_m=percentile_radius(launch_array, p), center_lat=center_lat, center_lon=center_lon) for p in (0.50, 0.80, 0.95)]
        timestamps = np.array([datetime.fromisoformat(x[2]).timestamp() for x in launches], dtype=float)
        launch_estimate = LaunchEstimate(lat=center_lat, lon=center_lon,
            time=datetime.fromtimestamp(float(np.median(timestamps)), tz=timezone.utc).isoformat(), altitude_m=0.0)
        return Result(detection={"lat": detection.lat, "lon": detection.lon, "altitude_m": detection.altitude_m, "time": detection.time.isoformat()},
                      launch_estimate=launch_estimate.__dict__.copy(), zones=[z.__dict__.copy() for z in zones],
                      ensemble_size=self.members, valid_members=len(launches), trajectories=all_trajectories)
