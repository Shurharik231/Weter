from __future__ import annotations

import bisect
import time
from datetime import datetime, timezone
from math import cos, radians, sin, sqrt, atan2, degrees
from typing import Any

import httpx


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

CACHE_TTL_SECONDS = 900
CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

# Давление -> примерная высота.
# Реальная геометрическая высота берётся из geopotential_height,
# которое возвращает Open-Meteo.
PRESSURE_LEVELS = [
    (1000, "1000hPa"),
    (975, "975hPa"),
    (950, "950hPa"),
    (900, "900hPa"),
    (850, "850hPa"),
    (800, "800hPa"),
    (700, "700hPa"),
    (600, "600hPa"),
    (550, "550hPa"),
    (500, "500hPa"),
    (450, "450hPa"),
    (400, "400hPa"),
    (350, "350hPa"),
    (300, "300hPa"),
]


class WeatherError(RuntimeError):
    pass


def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _variables() -> list[str]:
    result = []

    for _, level in PRESSURE_LEVELS:
        result.append(f"wind_speed_{level}")
        result.append(f"wind_direction_{level}")
        result.append(f"geopotential_height_{level}")

    return result


def _cache_key(
    latitudes: list[float],
    longitudes: list[float],
    start: datetime,
    end: datetime,
) -> str:

    return "|".join([
        ",".join(f"{x:.3f}" for x in latitudes),
        ",".join(f"{x:.3f}" for x in longitudes),
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    ])


def build_grid(
    center_lat: float,
    center_lon: float,
    radius_km: float,
) -> tuple[list[float], list[float]]:

    lat_delta = radius_km / 111.0

    lon_delta = radius_km / max(
        20.0,
        111.0 * cos(radians(center_lat))
    )

    latitudes = [
        center_lat + lat_delta * x
        for x in (-1, -0.5, 0, 0.5, 1)
    ]

    longitudes = [
        center_lon + lon_delta * x
        for x in (-1, -0.5, 0, 0.5, 1)
    ]

    return latitudes, longitudes


def _make_coordinate_pairs(
    latitudes: list[float],
    longitudes: list[float],
) -> list[tuple[float, float]]:

    # ВАЖНО:
    # Open-Meteo получает пары latitude/longitude.
    # Поэтому здесь создаём настоящую 5x5 сетку = 25 точек.

    return [
        (lat, lon)
        for lat in latitudes
        for lon in longitudes
    ]


async def fetch_grid(
    latitudes: list[float],
    longitudes: list[float],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:

    key = _cache_key(
        latitudes,
        longitudes,
        start,
        end,
    )

    cached = CACHE.get(key)

    if cached:
        created_at, data = cached

        if time.monotonic() - created_at < CACHE_TTL_SECONDS:
            return data

    coordinates = _make_coordinate_pairs(
        latitudes,
        longitudes,
    )

    request_lats = ",".join(
        f"{lat:.4f}"
        for lat, _ in coordinates
    )

    request_lons = ",".join(
        f"{lon:.4f}"
        for _, lon in coordinates
    )

    params = {
        "latitude": request_lats,
        "longitude": request_lons,

        "hourly": ",".join(_variables()),

        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),

        "timezone": "UTC",

        "wind_speed_unit": "ms",

        "forecast_days": None,
    }

    # Удаляем None, чтобы forecast_days вообще не отправлялся.
    params = {
        key: value
        for key, value in params.items()
        if value is not None
    }

    async with httpx.AsyncClient(timeout=60) as client:

        response = await client.get(
            OPEN_METEO_URL,
            params=params,
        )

    if response.status_code != 200:
        raise WeatherError(
            f"Open-Meteo HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    if isinstance(data, dict):
        data = [data]

    if not data:
        raise WeatherError(
            "Open-Meteo вернул пустой ответ."
        )

    for cell in data:

        if "hourly" not in cell:
            raise WeatherError(
                "В ответе Open-Meteo отсутствует hourly."
            )

    result = {
        "latitudes": latitudes,
        "longitudes": longitudes,
        "cells": data,
        "coordinates": coordinates,
    }

    CACHE[key] = (
        time.monotonic(),
        result,
    )

    # Не даём кэшу бесконечно расти.
    if len(CACHE) > 8:

        oldest_key = min(
            CACHE,
            key=lambda k: CACHE[k][0]
        )

        CACHE.pop(oldest_key, None)

    return result


def _wind_to_uv(
    speed: float,
    direction_from: float,
) -> tuple[float, float]:

    # Метеорологическое направление означает,
    # ОТКУДА дует ветер.

    direction_towards = radians(
        (direction_from + 180.0) % 360.0
    )

    east = sin(direction_towards) * speed
    north = cos(direction_towards) * speed

    return east, north


def _uv_to_wind(
    east: float,
    north: float,
) -> tuple[float, float]:

    speed = sqrt(
        east * east +
        north * north
    )

    if speed < 0.000001:
        return 0.0, 0.0

    towards = (
        degrees(
            atan2(east, north)
        ) + 360
    ) % 360

    direction_from = (
        towards + 180
    ) % 360

    return speed, direction_from


def _time_indices(
    times: list[datetime],
    target: datetime,
) -> tuple[int, int, float]:

    if target <= times[0]:
        return 0, 0, 0.0

    if target >= times[-1]:
        n = len(times) - 1
        return n, n, 0.0

    index = bisect.bisect_right(
        times,
        target,
    )

    i0 = index - 1
    i1 = index

    total = (
        times[i1] - times[i0]
    ).total_seconds()

    if total <= 0:
        return i0, i0, 0.0

    factor = (
        target - times[i0]
    ).total_seconds() / total

    return i0, i1, factor


def _cell_wind(
    cell: dict[str, Any],
    altitude: float,
    target_time: datetime,
) -> tuple[float, float]:

    hourly = cell["hourly"]

    times = [
        _parse_time(t)
        for t in hourly["time"]
    ]

    t0, t1, tf = _time_indices(
        times,
        target_time,
    )

    vectors = []

    for pressure, level in PRESSURE_LEVELS:

        speed_key = f"wind_speed_{level}"
        direction_key = f"wind_direction_{level}"
        height_key = f"geopotential_height_{level}"

        try:

            speed0 = float(
                hourly[speed_key][t0]
            )

            speed1 = float(
                hourly[speed_key][t1]
            )

            direction0 = float(
                hourly[direction_key][t0]
            )

            direction1 = float(
                hourly[direction_key][t1]
            )

            height0 = float(
                hourly[height_key][t0]
            )

            height1 = float(
                hourly[height_key][t1]
            )

        except (KeyError, TypeError, ValueError):
            continue

        # Сначала интерполируем время векторно.
        e0, n0 = _wind_to_uv(
            speed0,
            direction0,
        )

        e1, n1 = _wind_to_uv(
            speed1,
            direction1,
        )

        east = e0 + (
            e1 - e0
        ) * tf

        north = n0 + (
            n1 - n0
        ) * tf

        height = height0 + (
            height1 - height0
        ) * tf

        vectors.append(
            (
                height,
                east,
                north,
            )
        )

    if not vectors:
        raise WeatherError(
            "Для выбранного времени нет данных ветра."
        )

    vectors.sort(
        key=lambda item: item[0]
    )

    # Ниже минимального доступного уровня.
    if altitude <= vectors[0][0]:

        _, east, north = vectors[0]

        return _uv_to_wind(
            east,
            north,
        )

    # Выше максимального доступного уровня.
    if altitude >= vectors[-1][0]:

        _, east, north = vectors[-1]

        return _uv_to_wind(
            east,
            north,
        )

    # Вертикальная интерполяция.
    for i in range(len(vectors) - 1):

        h0, e0, n0 = vectors[i]
        h1, e1, n1 = vectors[i + 1]

        if h0 <= altitude <= h1:

            dh = h1 - h0

            if abs(dh) < 0.001:
                factor = 0.0
            else:
                factor = (
                    altitude - h0
                ) / dh

            east = e0 + (
                e1 - e0
            ) * factor

            north = n0 + (
                n1 - n0
            ) * factor

            return _uv_to_wind(
                east,
                north,
            )

    _, east, north = vectors[-1]

    return _uv_to_wind(
        east,
        north,
    )


def _find_cell(
    forecast: dict[str, Any],
    lat: float,
    lon: float,
) -> dict[str, Any]:

    cells = forecast["cells"]

    # Ищем ближайшие реальные точки Open-Meteo.
    return min(
        cells,
        key=lambda cell:
            (
                float(cell["latitude"]) - lat
            ) ** 2
            +
            (
                float(cell["longitude"]) - lon
            ) ** 2
    )


def _bilinear_wind(
    forecast: dict[str, Any],
    lat: float,
    lon: float,
    altitude: float,
    target_time: datetime,
) -> tuple[float, float]:

    lats = sorted(
        forecast["latitudes"]
    )

    lons = sorted(
        forecast["longitudes"]
    )

    # Ограничиваем координаты пределами полученной сетки.
    lat = max(
        lats[0],
        min(lats[-1], lat)
    )

    lon = max(
        lons[0],
        min(lons[-1], lon)
    )

    def surrounding(
        values: list[float],
        target: float,
    ):

        if target <= values[0]:
            return values[0], values[0], 0.0

        if target >= values[-1]:
            return values[-1], values[-1], 0.0

        i = bisect.bisect_right(
            values,
            target,
        )

        a = values[i - 1]
        b = values[i]

        factor = (
            target - a
        ) / (b - a)

        return a, b, factor

    lat0, lat1, fy = surrounding(
        lats,
        lat,
    )

    lon0, lon1, fx = surrounding(
        lons,
        lon,
    )

    c00 = _find_cell(
        forecast,
        lat0,
        lon0,
    )

    c01 = _find_cell(
        forecast,
        lat0,
        lon1,
    )

    c10 = _find_cell(
        forecast,
        lat1,
        lon0,
    )

    c11 = _find_cell(
        forecast,
        lat1,
        lon1,
    )

    w00 = _cell_wind(
        c00,
        altitude,
        target_time,
    )

    w01 = _cell_wind(
        c01,
        altitude,
        target_time,
    )

    w10 = _cell_wind(
        c10,
        altitude,
        target_time,
    )

    w11 = _cell_wind(
        c11,
        altitude,
        target_time,
    )

    e00, n00 = _wind_to_uv(*w00)
    e01, n01 = _wind_to_uv(*w01)
    e10, n10 = _wind_to_uv(*w10)
    e11, n11 = _wind_to_uv(*w11)

    e0 = e00 + (
        e01 - e00
    ) * fx

    e1 = e10 + (
        e11 - e10
    ) * fx

    east = e0 + (
        e1 - e0
    ) * fy

    n0 = n00 + (
        n01 - n00
    ) * fx

    n1 = n10 + (
        n11 - n10
    ) * fx

    north = n0 + (
        n1 - n0
    ) * fy

    return _uv_to_wind(
        east,
        north,
    )


def interpolate_wind(
    forecast: dict[str, Any],
    lat: float,
    lon: float,
    altitude: float,
    when: datetime,
) -> tuple[float, float]:

    return _bilinear_wind(
        forecast,
        lat,
        lon,
        altitude,
        when,
    )


def wind_field(
    forecast: dict[str, Any],
    lat: float,
    lon: float,
    altitude: float,
    when: datetime,
    radius_km: float = 150,
    count: int = 9,
) -> list[dict[str, float]]:

    latitudes, longitudes = build_grid(
        lat,
        lon,
        radius_km,
    )

    result = []

    for grid_lat in latitudes:

        for grid_lon in longitudes:

            speed, direction = interpolate_wind(
                forecast,
                grid_lat,
                grid_lon,
                altitude,
                when,
            )

            result.append({
                "lat": grid_lat,
                "lon": grid_lon,
                "speed": speed,
                "direction": direction,
            })

    return result