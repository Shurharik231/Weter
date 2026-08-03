from __future__ import annotations

from datetime import timedelta
from math import (
    asin,
    atan2,
    cos,
    degrees,
    radians,
    sin,
    sqrt,
)

from models import (
    FlightParameters,
    Trajectory,
    TrajectoryPoint,
)

from weather import interpolate_wind


EARTH_RADIUS_M = 6_371_000.0


def _destination(
    lat: float,
    lon: float,
    east_m: float,
    north_m: float,
) -> tuple[float, float]:
    distance_m = sqrt(
        east_m * east_m
        + north_m * north_m
    )

    if distance_m < 1e-9:
        return lat, lon

    bearing = atan2(
        east_m,
        north_m,
    )

    angular_distance = (
        distance_m / EARTH_RADIUS_M
    )

    lat1 = radians(lat)
    lon1 = radians(lon)

    sin_lat1 = sin(lat1)
    cos_lat1 = cos(lat1)

    sin_angular = sin(
        angular_distance
    )
    cos_angular = cos(
        angular_distance
    )

    lat2 = asin(
        sin_lat1 * cos_angular
        +
        cos_lat1
        * sin_angular
        * cos(bearing)
    )

    lon2 = (
        lon1
        +
        atan2(
            sin(bearing)
            * sin_angular
            * cos_lat1,
            cos_angular
            -
            sin_lat1 * sin(lat2),
        )
    )

    new_lat = degrees(lat2)

    new_lon = (
        degrees(lon2)
        + 540.0
    ) % 360.0 - 180.0

    return new_lat, new_lon


def _distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    p1 = radians(lat1)
    p2 = radians(lat2)

    dp = radians(
        lat2 - lat1
    )

    dl = radians(
        lon2 - lon1
    )

    a = (
        sin(dp / 2.0) ** 2
        +
        cos(p1)
        * cos(p2)
        * sin(dl / 2.0) ** 2
    )

    a = max(
        0.0,
        min(1.0, a),
    )

    return (
        2.0
        * EARTH_RADIUS_M
        * asin(sqrt(a))
    )


def _wind_to_uv(
    speed: float,
    direction_from: float,
) -> tuple[float, float]:
    direction_towards = radians(
        (
            direction_from
            + 180.0
        ) % 360.0
    )

    east = (
        sin(direction_towards)
        * speed
    )

    north = (
        cos(direction_towards)
        * speed
    )

    return east, north


def _wind_state(
    forecast: dict,
    lat: float,
    lon: float,
    altitude: float,
    when,
) -> tuple[float, float, float, float]:
    speed, direction = interpolate_wind(
        forecast=forecast,
        lat=lat,
        lon=lon,
        altitude=altitude,
        when=when,
    )

    east, north = _wind_to_uv(
        speed,
        direction,
    )

    return (
        east,
        north,
        speed,
        direction,
    )


def _trajectory_derivative(
    forecast: dict,
    lat: float,
    lon: float,
    altitude: float,
    when,
    ascent_rate: float,
    max_altitude: float,
) -> tuple[float, float, float]:
    east, north, _, _ = _wind_state(
        forecast=forecast,
        lat=lat,
        lon=lon,
        altitude=altitude,
        when=when,
    )

    if altitude >= max_altitude:
        vertical = 0.0
    else:
        vertical = ascent_rate

    return (
        east,
        north,
        vertical,
    )


def _average_wind_direction(
    speeds: list[float],
    directions: list[float],
) -> float:
    if not directions:
        return 0.0

    x = 0.0
    y = 0.0
    total_weight = 0.0

    for speed, direction in zip(
        speeds,
        directions,
    ):
        weight = max(
            0.0,
            speed,
        )

        angle = radians(
            direction
        )

        x += (
            cos(angle)
            * weight
        )

        y += (
            sin(angle)
            * weight
        )

        total_weight += weight

    if total_weight <= 1e-12:
        return 0.0

    return (
        degrees(
            atan2(y, x)
        )
        + 360.0
    ) % 360.0


def calculate_trajectory(
    params: FlightParameters,
    forecast: dict,
) -> Trajectory:

    if params.start_altitude < 0:
        raise ValueError(
            "Высота старта не может быть отрицательной."
        )

    if params.max_altitude < 0:
        raise ValueError(
            "Максимальная высота не может быть отрицательной."
        )

    if params.start_altitude > params.max_altitude:
        raise ValueError(
            "Высота старта не может быть выше максимальной."
        )

    if params.duration_hours <= 0:
        raise ValueError(
            "Продолжительность должна быть больше 0."
        )

    if params.step_minutes <= 0:
        raise ValueError(
            "Шаг расчёта должен быть больше 0."
        )

    if params.ascent_rate < 0:
        raise ValueError(
            "Скорость набора высоты не может быть отрицательной."
        )

    total_seconds = (
        params.duration_hours
        * 3600.0
    )

    nominal_dt = (
        params.step_minutes
        * 60.0
    )

    lat = params.start.lat
    lon = params.start.lon
    altitude = params.start_altitude

    current_time = params.start_time

    elapsed_seconds = 0.0

    points: list[TrajectoryPoint] = []

    speeds: list[float] = []
    directions: list[float] = []

    first_speed, first_direction = (
        interpolate_wind(
            forecast=forecast,
            lat=lat,
            lon=lon,
            altitude=altitude,
            when=current_time,
        )
    )

    points.append(
        TrajectoryPoint(
            time=current_time,
            lat=lat,
            lon=lon,
            altitude=altitude,
            wind_speed=first_speed,
            wind_direction=first_direction,
        )
    )

    speeds.append(
        first_speed
    )

    directions.append(
        first_direction
    )

    while elapsed_seconds < total_seconds:

        dt = min(
            nominal_dt,
            total_seconds
            - elapsed_seconds,
        )

        old_lat = lat
        old_lon = lon

        old_altitude = altitude

        old_time = current_time

        k1_east, k1_north, k1_up = (
            _trajectory_derivative(
                forecast=forecast,
                lat=lat,
                lon=lon,
                altitude=altitude,
                when=current_time,
                ascent_rate=params.ascent_rate,
                max_altitude=params.max_altitude,
            )
        )

        k2_lat, k2_lon = _destination(
            lat,
            lon,
            k1_east * dt / 2.0,
            k1_north * dt / 2.0,
        )

        k2_altitude = min(
            params.max_altitude,
            altitude
            + k1_up * dt / 2.0,
        )

        k2_time = (
            current_time
            + timedelta(
                seconds=dt / 2.0
            )
        )

        k2_east, k2_north, k2_up = (
            _trajectory_derivative(
                forecast=forecast,
                lat=k2_lat,
                lon=k2_lon,
                altitude=k2_altitude,
                when=k2_time,
                ascent_rate=params.ascent_rate,
                max_altitude=params.max_altitude,
            )
        )

        k3_lat, k3_lon = _destination(
            lat,
            lon,
            k2_east * dt / 2.0,
            k2_north * dt / 2.0,
        )

        k3_altitude = min(
            params.max_altitude,
            altitude
            + k2_up * dt / 2.0,
        )

        k3_time = (
            current_time
            + timedelta(
                seconds=dt / 2.0
            )
        )

        k3_east, k3_north, k3_up = (
            _trajectory_derivative(
                forecast=forecast,
                lat=k3_lat,
                lon=k3_lon,
                altitude=k3_altitude,
                when=k3_time,
                ascent_rate=params.ascent_rate,
                max_altitude=params.max_altitude,
            )
        )

        k4_lat, k4_lon = _destination(
            lat,
            lon,
            k3_east * dt,
            k3_north * dt,
        )

        k4_altitude = min(
            params.max_altitude,
            altitude
            + k3_up * dt,
        )

        k4_time = (
            current_time
            + timedelta(
                seconds=dt
            )
        )

        k4_east, k4_north, k4_up = (
            _trajectory_derivative(
                forecast=forecast,
                lat=k4_lat,
                lon=k4_lon,
                altitude=k4_altitude,
                when=k4_time,
                ascent_rate=params.ascent_rate,
                max_altitude=params.max_altitude,
            )
        )

        east_displacement = (
            dt / 6.0
            * (
                k1_east
                + 2.0 * k2_east
                + 2.0 * k3_east
                + k4_east
            )
        )

        north_displacement = (
            dt / 6.0
            * (
                k1_north
                + 2.0 * k2_north
                + 2.0 * k3_north
                + k4_north
            )
        )

        vertical_displacement = (
            dt / 6.0
            * (
                k1_up
                + 2.0 * k2_up
                + 2.0 * k3_up
                + k4_up
            )
        )

        lat, lon = _destination(
            lat,
            lon,
            east_displacement,
            north_displacement,
        )

        altitude = min(
            params.max_altitude,
            altitude
            + vertical_displacement,
        )

        current_time = (
            current_time
            + timedelta(
                seconds=dt
            )
        )

        elapsed_seconds += dt

        speed, direction = (
            interpolate_wind(
                forecast=forecast,
                lat=lat,
                lon=lon,
                altitude=altitude,
                when=current_time,
            )
        )

        points.append(
            TrajectoryPoint(
                time=current_time,
                lat=lat,
                lon=lon,
                altitude=altitude,
                wind_speed=speed,
                wind_direction=direction,
            )
        )

        speeds.append(speed)
        directions.append(direction)

        if (
            old_altitude < params.max_altitude
            and altitude >= params.max_altitude
        ):
            altitude = params.max_altitude

    if not points:
        raise ValueError(
            "Траектория не содержит точек."
        )

    segment_distances = [
        _distance_m(
            a.lat,
            a.lon,
            b.lat,
            b.lon,
        )
        for a, b in zip(
            points,
            points[1:],
        )
    ]

    prevailing_direction = (
        _average_wind_direction(
            speeds=speeds,
            directions=directions,
        )
    )

    return Trajectory(
        start=points[0],
        end=points[-1],
        distance_km=(
            sum(segment_distances)
            / 1000.0
        ),
        average_wind_speed=(
            sum(speeds)
            / len(speeds)
        ),
        max_wind_speed=max(
            speeds
        ),
        prevailing_direction=(
            prevailing_direction
        ),
        points=points,
    )