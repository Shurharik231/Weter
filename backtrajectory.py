from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np


EARTH_RADIUS_M = 6371000.0
G = 9.80665
R_D = 287.05

# Те же уровни, что используются в weather.py
PRESSURE_LEVELS = [
    (1000, "1000hPa"),
    (975, "975hPa"),
    (950, "950hPa"),
    (925, "925hPa"),
    (900, "900hPa"),
    (850, "850hPa"),
    (800, "800hPa"),
    (700, "700hPa"),
    (600, "600hPa"),
    (500, "500hPa"),
    (400, "400hPa"),
    (300, "300hPa"),
    (250, "250hPa"),
    (200, "200hPa"),
]

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 1800


@dataclass
class Detection:
    lat: float
    lon: float
    altitude_m: float
    time: datetime


@dataclass
class AtmosphericState:
    u_mps: float
    v_mps: float
    temperature_k: float
    pressure_pa: float
    geopotential_m2s2: float
    altitude_m: float


@dataclass
class TrajectoryPoint:
    time: str
    lat: float
    lon: float
    altitude_m: float
    u_mps: float
    v_mps: float
    wind_speed_mps: float


@dataclass
class LaunchEstimate:
    lat: float
    lon: float
    time: str
    altitude_m: float


@dataclass
class Zone:
    probability: float
    radius_m: float
    center_lat: float
    center_lon: float


@dataclass
class Result:
    detection: dict
    launch_estimate: dict
    zones: list[dict]
    ensemble_size: int
    valid_members: int
    trajectories: list[list[dict]]


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_lon(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def clamp_lat(lat: float) -> float:
    return max(-89.999999, min(89.999999, lat))


def move_point(
    lat: float,
    lon: float,
    east_m: float,
    north_m: float,
) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    dlat = north_m / EARTH_RADIUS_M
    dlon = east_m / (EARTH_RADIUS_M * max(math.cos(lat_rad), 1e-8))
    return (
        clamp_lat(lat + math.degrees(dlat)),
        normalize_lon(lon + math.degrees(dlon)),
    )


def haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2.0) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2.0) ** 2
    )

    return 2.0 * EARTH_RADIUS_M * math.asin(
        math.sqrt(max(0.0, min(1.0, a)))
    )


def percentile_radius(
    points: np.ndarray,
    probability: float,
) -> float:
    lat0 = math.radians(float(np.mean(points[:, 0])))
    lon0 = math.radians(float(np.mean(points[:, 1])))

    x = (
        np.radians(points[:, 1]) - lon0
    ) * EARTH_RADIUS_M * math.cos(lat0)

    y = (
        np.radians(points[:, 0]) - math.radians(float(np.mean(points[:, 0])))
    ) * EARTH_RADIUS_M

    distances = np.sqrt(x * x + y * y)

    return float(np.quantile(distances, probability))


def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _wind_to_uv(speed: float, direction_from: float) -> tuple[float, float]:
    direction_towards = math.radians((direction_from + 180.0) % 360.0)
    east = math.sin(direction_towards) * speed
    north = math.cos(direction_towards) * speed
    return east, north


def _uv_to_wind(east: float, north: float) -> tuple[float, float]:
    speed = math.sqrt(east * east + north * north)
    if speed < 1e-6:
        return 0.0, 0.0
    towards = (math.degrees(math.atan2(east, north)) + 360.0) % 360.0
    direction_from = (towards + 180.0) % 360.0
    return speed, direction_from


class OpenMeteoProvider:
    """
    Бесплатный провайдер на Open-Meteo Archive / Forecast.
    Полностью заменяет старый ERA5Provider (cdsapi).
    """

    def __init__(
        self,
        workdir: str | Path = "./era5_cache",
        spatial_margin_deg: float = 6.0,
    ) -> None:
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.spatial_margin_deg = spatial_margin_deg
        self.data: dict[str, Any] | None = None
        self.times: list[datetime] = []
        self.coordinates: list[tuple[float, float]] = []
        self.cells: list[dict[str, Any]] = []

    def _bbox(
        self,
        detection: Detection,
        max_hours: float,
        max_ascent_rate_mps: float,
    ) -> tuple[float, float, float, float]:
        horizontal_distance_km = (
            max_ascent_rate_mps * max_hours * 3600.0 / 1000.0 * 1.8
        )
        margin = max(
            self.spatial_margin_deg,
            horizontal_distance_km / 111.0,
        )
        north = min(90.0, detection.lat + margin)
        south = max(-90.0, detection.lat - margin)
        west = detection.lon - margin
        east = detection.lon + margin
        return north, west, south, east

    def _make_grid(
        self,
        north: float,
        west: float,
        south: float,
        east: float,
        steps: int = 5,
    ) -> list[tuple[float, float]]:
        lats = np.linspace(south, north, steps)
        lons = np.linspace(west, east, steps)
        return [(float(lat), float(lon)) for lat in lats for lon in lons]

    def _variables(self) -> list[str]:
        result = []
        for _, level in PRESSURE_LEVELS:
            result.append(f"wind_speed_{level}")
            result.append(f"wind_direction_{level}")
            result.append(f"temperature_{level}")
            result.append(f"geopotential_height_{level}")
        return result

    def download(
        self,
        detection: Detection,
        max_hours: float,
        max_ascent_rate_mps: float,
    ) -> None:
        start = detection.time - timedelta(hours=max_hours + 3.0)
        end = detection.time + timedelta(hours=2.0)

        north, west, south, east = self._bbox(
            detection, max_hours, max_ascent_rate_mps
        )

        coordinates = self._make_grid(north, west, south, east, steps=5)
        self.coordinates = coordinates

        request_lats = ",".join(f"{lat:.4f}" for lat, _ in coordinates)
        request_lons = ",".join(f"{lon:.4f}" for _, lon in coordinates)

        # Решаем, какой эндпоинт использовать
        now = datetime.now(timezone.utc)
        days_ago = (now - detection.time).total_seconds() / 86400.0

        if days_ago > 5.5:
            # Старые данные → Archive (ERA5)
            url = OPEN_METEO_ARCHIVE_URL
            params = {
                "latitude": request_lats,
                "longitude": request_lons,
                "hourly": ",".join(self._variables()),
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
                "timezone": "UTC",
                "wind_speed_unit": "ms",
                "temperature_unit": "celsius",
            }
        else:
            # Свежие данные → Forecast + past_days
            url = OPEN_METEO_FORECAST_URL
            past_days = min(92, max(1, int(days_ago) + 3))
            params = {
                "latitude": request_lats,
                "longitude": request_lons,
                "hourly": ",".join(self._variables()),
                "past_days": past_days,
                "forecast_days": 1,
                "timezone": "UTC",
                "wind_speed_unit": "ms",
                "temperature_unit": "celsius",
            }

        cache_key = f"{url}|{request_lats}|{request_lons}|{start.date()}|{end.date()}"
        cached = CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0] < CACHE_TTL_SECONDS):
            data = cached[1]
        else:
            with httpx.Client(timeout=90.0) as client:
                response = client.get(url, params=params)

            if response.status_code != 200:
                raise RuntimeError(
                    f"Open-Meteo HTTP {response.status_code}: {response.text[:400]}"
                )

            data = response.json()
            if isinstance(data, dict):
                data = [data]

            if not data:
                raise RuntimeError("Open-Meteo вернул пустой ответ.")

            CACHE[cache_key] = (time.monotonic(), data)

            if len(CACHE) > 12:
                oldest = min(CACHE, key=lambda k: CACHE[k][0])
                CACHE.pop(oldest, None)

        self.cells = data

        # Собираем общее время
        first_hourly = data[0].get("hourly", {})
        time_strings = first_hourly.get("time", [])
        self.times = [_parse_time(t) for t in time_strings]

        if not self.times:
            raise RuntimeError("Open-Meteo не вернул временной ряд.")

        self.data = {
            "coordinates": coordinates,
            "cells": data,
            "times": self.times,
        }

    def _find_nearest_cell(self, lat: float, lon: float) -> dict[str, Any]:
        return min(
            self.cells,
            key=lambda cell: (
                (float(cell["latitude"]) - lat) ** 2
                + (float(cell["longitude"]) - lon) ** 2
            ),
        )

    def _time_indices(self, target: datetime) -> tuple[int, int, float]:
        times = self.times
        if target <= times[0]:
            return 0, 0, 0.0
        if target >= times[-1]:
            n = len(times) - 1
            return n, n, 0.0

        # бинарный поиск
        lo, hi = 0, len(times) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if times[mid] < target:
                lo = mid + 1
            else:
                hi = mid

        i1 = lo
        i0 = max(0, i1 - 1)
        total = (times[i1] - times[i0]).total_seconds()
        if total <= 0:
            return i0, i0, 0.0
        factor = (target - times[i0]).total_seconds() / total
        return i0, i1, factor

    def state(
        self,
        lat: float,
        lon: float,
        altitude_m: float,
        time: datetime,
    ) -> AtmosphericState:
        if not self.cells or not self.times:
            raise RuntimeError("Данные Open-Meteo ещё не загружены. Вызовите download().")

        cell = self._find_nearest_cell(lat, lon)
        hourly = cell["hourly"]

        t0, t1, tf = self._time_indices(time)

        vectors: list[tuple[float, float, float, float, float]] = []
        # (height, u, v, temperature_k, pressure_hpa)

        for pressure_hpa, level in PRESSURE_LEVELS:
            try:
                speed0 = float(hourly[f"wind_speed_{level}"][t0])
                speed1 = float(hourly[f"wind_speed_{level}"][t1])
                dir0 = float(hourly[f"wind_direction_{level}"][t0])
                dir1 = float(hourly[f"wind_direction_{level}"][t1])
                temp0 = float(hourly[f"temperature_{level}"][t0])
                temp1 = float(hourly[f"temperature_{level}"][t1])
                height0 = float(hourly[f"geopotential_height_{level}"][t0])
                height1 = float(hourly[f"geopotential_height_{level}"][t1])
            except (KeyError, TypeError, ValueError, IndexError):
                continue

            e0, n0 = _wind_to_uv(speed0, dir0)
            e1, n1 = _wind_to_uv(speed1, dir1)

            east = e0 + (e1 - e0) * tf
            north = n0 + (n1 - n0) * tf
            height = height0 + (height1 - height0) * tf
            temp_c = temp0 + (temp1 - temp0) * tf
            temp_k = temp_c + 273.15

            vectors.append((height, east, north, temp_k, float(pressure_hpa)))

        if not vectors:
            raise ValueError("Нет данных ветра для выбранного времени/места.")

        vectors.sort(key=lambda x: x[0])

        # Ниже самого нижнего уровня
        if altitude_m <= vectors[0][0]:
            h, u, v, t, p = vectors[0]
            return AtmosphericState(
                u_mps=u,
                v_mps=v,
                temperature_k=t,
                pressure_pa=p * 100.0,
                geopotential_m2s2=h * G,
                altitude_m=h,
            )

        # Выше самого верхнего уровня
        if altitude_m >= vectors[-1][0]:
            h, u, v, t, p = vectors[-1]
            return AtmosphericState(
                u_mps=u,
                v_mps=v,
                temperature_k=t,
                pressure_pa=p * 100.0,
                geopotential_m2s2=h * G,
                altitude_m=h,
            )

        # Вертикальная интерполяция
        for i in range(len(vectors) - 1):
            h0, u0, v0, t0, p0 = vectors[i]
            h1, u1, v1, t1, p1 = vectors[i + 1]

            if h0 <= altitude_m <= h1:
                dh = h1 - h0
                factor = 0.0 if abs(dh) < 0.1 else (altitude_m - h0) / dh

                u = u0 + (u1 - u0) * factor
                v = v0 + (v1 - v0) * factor
                t = t0 + (t1 - t0) * factor
                # давление интерполируем логарифмически
                log_p = math.log(p0) + (math.log(p1) - math.log(p0)) * factor
                p = math.exp(log_p)

                return AtmosphericState(
                    u_mps=u,
                    v_mps=v,
                    temperature_k=t,
                    pressure_pa=p * 100.0,
                    geopotential_m2s2=altitude_m * G,
                    altitude_m=altitude_m,
                )

        # fallback
        h, u, v, t, p = vectors[-1]
        return AtmosphericState(
            u_mps=u,
            v_mps=v,
            temperature_k=t,
            pressure_pa=p * 100.0,
            geopotential_m2s2=h * G,
            altitude_m=h,
        )


class BalloonModel:
    def __init__(
        self,
        ascent_rate_mps: float = 1.5,
        ascent_rate_sigma_mps: float = 0.7,
    ) -> None:
        if ascent_rate_mps <= 0:
            raise ValueError("ascent_rate_mps должен быть > 0.")
        if ascent_rate_sigma_mps < 0:
            raise ValueError("ascent_rate_sigma_mps должен быть >= 0.")

        self.ascent_rate_mps = ascent_rate_mps
        self.ascent_rate_sigma_mps = ascent_rate_sigma_mps

    def ascent_rate(
        self,
        altitude_m: float,
        temperature_k: float,
        pressure_pa: float,
        rng: np.random.Generator,
    ) -> float:
        rho = pressure_pa / (R_D * max(temperature_k, 150.0))
        rho_ref = 1.225
        density_factor = math.sqrt(rho_ref / max(rho, 0.05))

        base = self.ascent_rate_mps * (
            0.65 + 0.35 * min(density_factor, 1.8)
        )

        value = base + rng.normal(0.0, self.ascent_rate_sigma_mps)
        return max(0.5, value)


class BackTrajectorySolver:
    def __init__(
        self,
        weather: OpenMeteoProvider,
        balloon: BalloonModel,
        step_seconds: float = 60.0,
        max_duration_hours: float = 4.0,
    ) -> None:
        self.weather = weather
        self.balloon = balloon
        self.step_seconds = step_seconds
        self.max_duration_hours = max_duration_hours

    def _derivative(
        self,
        lat: float,
        lon: float,
        altitude: float,
        time: datetime,
        rng: np.random.Generator,
    ) -> tuple[float, float, float, AtmosphericState]:
        state = self.weather.state(lat, lon, altitude, time)

        ascent_rate = self.balloon.ascent_rate(
            altitude,
            state.temperature_k,
            state.pressure_pa,
            rng,
        )

        # Обратная траектория → знак минус
        return (
            -state.u_mps,
            -state.v_mps,
            -ascent_rate,
            state,
        )

    def integrate(
        self,
        detection: Detection,
        rng: np.random.Generator,
    ) -> tuple[list[TrajectoryPoint], LaunchEstimate]:
        lat = detection.lat
        lon = detection.lon
        altitude = detection.altitude_m
        time = detection.time

        points: list[TrajectoryPoint] = []
        elapsed = 0.0
        max_seconds = self.max_duration_hours * 3600.0

        while elapsed < max_seconds and altitude > 10.0:
            dt = min(self.step_seconds, max_seconds - elapsed)

            k1_e, k1_n, k1_z, s1 = self._derivative(
                lat, lon, altitude, time, rng
            )

            lat2, lon2 = move_point(lat, lon, k1_e * dt / 2.0, k1_n * dt / 2.0)
            alt2 = max(1.0, altitude + k1_z * dt / 2.0)
            time2 = time - timedelta(seconds=dt / 2.0)

            k2_e, k2_n, k2_z, _ = self._derivative(
                lat2, lon2, alt2, time2, rng
            )

            lat3, lon3 = move_point(lat, lon, k2_e * dt / 2.0, k2_n * dt / 2.0)
            alt3 = max(1.0, altitude + k2_z * dt / 2.0)

            k3_e, k3_n, k3_z, _ = self._derivative(
                lat3, lon3, alt3, time2, rng
            )

            lat4, lon4 = move_point(lat, lon, k3_e * dt, k3_n * dt)
            alt4 = max(1.0, altitude + k3_z * dt)
            time4 = time - timedelta(seconds=dt)

            k4_e, k4_n, k4_z, _ = self._derivative(
                lat4, lon4, alt4, time4, rng
            )

            east = dt / 6.0 * (k1_e + 2.0 * k2_e + 2.0 * k3_e + k4_e)
            north = dt / 6.0 * (k1_n + 2.0 * k2_n + 2.0 * k3_n + k4_n)
            vertical = dt / 6.0 * (k1_z + 2.0 * k2_z + 2.0 * k3_z + k4_z)

            if altitude + vertical <= 0.0:
                fraction = altitude / max(altitude - vertical, 1e-9)
                east *= fraction
                north *= fraction
                dt *= fraction
                vertical = -altitude

            lat, lon = move_point(lat, lon, east, north)
            altitude += vertical
            time -= timedelta(seconds=dt)
            elapsed += dt

            wind_speed = math.sqrt(s1.u_mps ** 2 + s1.v_mps ** 2)

            points.append(
                TrajectoryPoint(
                    time=time.isoformat(),
                    lat=lat,
                    lon=lon,
                    altitude_m=max(0.0, altitude),
                    u_mps=s1.u_mps,
                    v_mps=s1.v_mps,
                    wind_speed_mps=wind_speed,
                )
            )

            if altitude <= 10.0:
                break

        if not points:
            raise RuntimeError("Не удалось построить траекторию.")

        launch = LaunchEstimate(
            lat=points[-1].lat,
            lon=points[-1].lon,
            time=points[-1].time,
            altitude_m=points[-1].altitude_m,
        )

        return points, launch


class EnsembleEstimator:
    def __init__(
        self,
        solver: BackTrajectorySolver,
        members: int = 1000,
        wind_sigma_mps: float = 1.5,
        detection_time_sigma_s: float = 60.0,
        altitude_sigma_m: float = 50.0,
        seed: int = 42,
    ) -> None:
        self.solver = solver
        self.members = members
        self.wind_sigma_mps = wind_sigma_mps
        self.detection_time_sigma_s = detection_time_sigma_s
        self.altitude_sigma_m = altitude_sigma_m
        self.rng = np.random.default_rng(seed)

    def run(self, detection: Detection) -> Result:
        launches = []
        all_trajectories = []

        for _ in range(self.members):
            dt_error = self.rng.normal(0.0, self.detection_time_sigma_s)
            altitude_error = self.rng.normal(0.0, self.altitude_sigma_m)

            member_detection = Detection(
                lat=detection.lat,
                lon=detection.lon,
                altitude_m=max(100.0, detection.altitude_m + altitude_error),
                time=detection.time + timedelta(seconds=float(dt_error)),
            )

            try:
                trajectory, launch = self.solver.integrate(
                    member_detection, self.rng
                )
                launches.append((launch.lat, launch.lon, launch.time))
                all_trajectories.append([asdict(point) for point in trajectory])
            except (ValueError, RuntimeError, IndexError, KeyError):
                continue

        if not launches:
            raise RuntimeError(
                "Ни одна ансамблевая траектория не завершилась успешно."
            )

        launch_array = np.array(
            [[x[0], x[1]] for x in launches],
            dtype=float,
        )

        center_lat = float(np.mean(launch_array[:, 0]))
        center_lon = float(np.mean(launch_array[:, 1]))

        zones = []
        for probability in (0.50, 0.80, 0.95):
            zones.append(
                Zone(
                    probability=probability,
                    radius_m=percentile_radius(launch_array, probability),
                    center_lat=center_lat,
                    center_lon=center_lon,
                )
            )

        launch_times = [
            datetime.fromisoformat(x[2]) for x in launches
        ]
        timestamp_seconds = np.array(
            [t.timestamp() for t in launch_times], dtype=float
        )
        median_timestamp = float(np.median(timestamp_seconds))

        launch_estimate = LaunchEstimate(
            lat=center_lat,
            lon=center_lon,
            time=datetime.fromtimestamp(
                median_timestamp, tz=timezone.utc
            ).isoformat(),
            altitude_m=0.0,
        )

        return Result(
            detection={
                "lat": detection.lat,
                "lon": detection.lon,
                "altitude_m": detection.altitude_m,
                "time": detection.time.isoformat(),
            },
            launch_estimate=asdict(launch_estimate),
            zones=[asdict(zone) for zone in zones],
            ensemble_size=self.members,
            valid_members=len(launches),
            trajectories=all_trajectories,
        )


def write_geojson(result: Result, filename: str) -> None:
    center = result.launch_estimate
    features = [
        {
            "type": "Feature",
            "properties": {"type": "launch_estimate"},
            "geometry": {
                "type": "Point",
                "coordinates": [center["lon"], center["lat"]],
            },
        }
    ]

    for zone in result.zones:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "type": "uncertainty_zone",
                    "probability": zone["probability"],
                    "radius_m": zone["radius_m"],
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        zone["center_lon"],
                        zone["center_lat"],
                    ],
                },
            }
        )

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(
            {"type": "FeatureCollection", "features": features},
            f,
            ensure_ascii=False,
            indent=2,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--altitude", type=float, required=True)
    parser.add_argument("--time", required=True)
    parser.add_argument("--members", type=int, default=300)
    parser.add_argument("--ascent-rate", type=float, default=5.0)
    parser.add_argument("--ascent-rate-sigma", type=float, default=0.7)
    parser.add_argument("--step", type=float, default=60.0)
    parser.add_argument("--max-hours", type=float, default=4.0)
    parser.add_argument("--workdir", default="./era5_cache")
    parser.add_argument("--output", default="result.json")
    parser.add_argument("--geojson", default="launch_zone.geojson")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    detection = Detection(
        lat=args.lat,
        lon=args.lon,
        altitude_m=args.altitude,
        time=normalize_datetime(
            datetime.fromisoformat(args.time.replace("Z", "+00:00"))
        ),
    )

    weather = OpenMeteoProvider(workdir=args.workdir)

    weather.download(
        detection=detection,
        max_hours=args.max_hours,
        max_ascent_rate_mps=max(args.ascent_rate * 2.0, 15.0),
    )

    balloon = BalloonModel(
        ascent_rate_mps=args.ascent_rate,
        ascent_rate_sigma_mps=args.ascent_rate_sigma,
    )

    solver = BackTrajectorySolver(
        weather=weather,
        balloon=balloon,
        step_seconds=args.step,
        max_duration_hours=args.max_hours,
    )

    estimator = EnsembleEstimator(
        solver=solver,
        members=args.members,
        seed=args.seed,
    )

    result = estimator.run(detection)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(asdict(result), f, ensure_ascii=False, indent=2)

    write_geojson(result, args.geojson)

    print(
        json.dumps(
            {
                "launch_estimate": result.launch_estimate,
                "zones": result.zones,
                "ensemble_size": result.ensemble_size,
                "valid_members": result.valid_members,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

ERA5Provider = OpenMeteoProvider

if __name__ == "__main__":
    main()