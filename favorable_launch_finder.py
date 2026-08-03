from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from typing import Callable, Dict, List, Optional, Tuple
import random

EARTH_RADIUS_M = 6_371_000.0


@dataclass
class GeoPoint:
    lat: float
    lon: float


@dataclass
class TrajectoryPoint:
    time: datetime
    lat: float
    lon: float
    altitude: float
    wind_speed: float = 0.0
    wind_direction: float = 0.0


@dataclass
class Trajectory:
    start: TrajectoryPoint
    end: TrajectoryPoint
    distance_km: float
    average_wind_speed: float
    max_wind_speed: float
    prevailing_direction: float
    points: List[TrajectoryPoint] = field(default_factory=list)


@dataclass
class FlightParameters:
    start: GeoPoint
    start_time: datetime
    start_altitude: float = 0.0
    max_altitude: float = 8000.0
    ascent_rate: float = 5.0
    duration_hours: float = 4.0
    step_minutes: float = 2.0


@dataclass
class LaunchCandidate:
    launch_time: datetime
    launch_point: GeoPoint
    trajectory: Trajectory
    min_distance_to_target_m: float
    closest_point: TrajectoryPoint


@dataclass
class FavorableWindow:
    date: str
    window_start: datetime
    window_end: datetime
    best_candidates: List[LaunchCandidate] = field(default_factory=list)

    @property
    def recommended_time(self) -> datetime:
        if not self.best_candidates:
            return self.window_start
        return min(
            self.best_candidates,
            key=lambda c: c.min_distance_to_target_m
        ).launch_time


def _destination(
    lat: float,
    lon: float,
    east_m: float,
    north_m: float,
) -> Tuple[float, float]:
    distance_m = sqrt(east_m * east_m + north_m * north_m)
    if distance_m < 1e-9:
        return lat, lon

    bearing = atan2(east_m, north_m)
    angular_distance = distance_m / EARTH_RADIUS_M

    lat1 = radians(lat)
    lon1 = radians(lon)
    sin_lat1 = sin(lat1)
    cos_lat1 = cos(lat1)
    sin_angular = sin(angular_distance)
    cos_angular = cos(angular_distance)

    lat2 = asin(
        sin_lat1 * cos_angular
        + cos_lat1 * sin_angular * cos(bearing)
    )
    lon2 = lon1 + atan2(
        sin(bearing) * sin_angular * cos_lat1,
        cos_angular - sin_lat1 * sin(lat2),
    )

    new_lat = degrees(lat2)
    new_lon = (degrees(lon2) + 540.0) % 360.0 - 180.0
    return new_lat, new_lon


def _distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    p1 = radians(lat1)
    p2 = radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)

    a = (
        sin(dp / 2.0) ** 2
        + cos(p1) * cos(p2) * sin(dl / 2.0) ** 2
    )
    a = max(0.0, min(1.0, a))
    return 2.0 * EARTH_RADIUS_M * asin(sqrt(a))


def _wind_to_uv(speed: float, direction_from: float) -> Tuple[float, float]:
    direction_towards = radians((direction_from + 180.0) % 360.0)
    east = sin(direction_towards) * speed
    north = cos(direction_towards) * speed
    return east, north


def _average_wind_direction(
    speeds: List[float],
    directions: List[float],
) -> float:
    if not directions:
        return 0.0

    x = 0.0
    y = 0.0
    total_weight = 0.0

    for speed, direction in zip(speeds, directions):
        weight = max(0.0, speed)
        angle = radians(direction)
        x += cos(angle) * weight
        y += sin(angle) * weight
        total_weight += weight

    if total_weight <= 1e-12:
        return 0.0

    return (degrees(atan2(y, x)) + 360.0) % 360.0


def default_interpolate_wind(
    forecast: dict,
    lat: float,
    lon: float,
    altitude: float,
    when: datetime,
) -> Tuple[float, float]:
    return 12.0, 270.0


WindInterpolator = Callable[
    [dict, float, float, float, datetime],
    Tuple[float, float]
]


def _trajectory_derivative(
    forecast: dict,
    lat: float,
    lon: float,
    altitude: float,
    when: datetime,
    ascent_rate: float,
    max_altitude: float,
    interpolate_wind: WindInterpolator,
) -> Tuple[float, float, float]:
    speed, direction = interpolate_wind(
        forecast, lat, lon, altitude, when
    )
    east, north = _wind_to_uv(speed, direction)
    vertical = 0.0 if altitude >= max_altitude else ascent_rate
    return east, north, vertical


def calculate_trajectory(
    params: FlightParameters,
    forecast: dict,
    interpolate_wind: WindInterpolator = default_interpolate_wind,
) -> Trajectory:
    if params.start_altitude < 0:
        raise ValueError("Высота старта не может быть отрицательной.")
    if params.max_altitude < 0:
        raise ValueError("Максимальная высота не может быть отрицательной.")
    if params.start_altitude > params.max_altitude:
        raise ValueError("Высота старта не может быть выше максимальной.")
    if params.duration_hours <= 0:
        raise ValueError("Продолжительность должна быть больше 0.")
    if params.step_minutes <= 0:
        raise ValueError("Шаг расчёта должен быть больше 0.")
    if params.ascent_rate < 0:
        raise ValueError("Скорость набора высоты не может быть отрицательной.")

    total_seconds = params.duration_hours * 3600.0
    nominal_dt = params.step_minutes * 60.0

    lat = params.start.lat
    lon = params.start.lon
    altitude = params.start_altitude
    current_time = params.start_time
    elapsed_seconds = 0.0

    points: List[TrajectoryPoint] = []
    speeds: List[float] = []
    directions: List[float] = []

    first_speed, first_direction = interpolate_wind(
        forecast, lat, lon, altitude, current_time
    )

    points.append(TrajectoryPoint(
        time=current_time,
        lat=lat,
        lon=lon,
        altitude=altitude,
        wind_speed=first_speed,
        wind_direction=first_direction,
    ))
    speeds.append(first_speed)
    directions.append(first_direction)

    while elapsed_seconds < total_seconds:
        dt = min(nominal_dt, total_seconds - elapsed_seconds)

        k1_east, k1_north, k1_up = _trajectory_derivative(
            forecast, lat, lon, altitude, current_time,
            params.ascent_rate, params.max_altitude, interpolate_wind
        )

        k2_lat, k2_lon = _destination(lat, lon, k1_east * dt / 2.0, k1_north * dt / 2.0)
        k2_altitude = min(params.max_altitude, altitude + k1_up * dt / 2.0)
        k2_time = current_time + timedelta(seconds=dt / 2.0)
        k2_east, k2_north, k2_up = _trajectory_derivative(
            forecast, k2_lat, k2_lon, k2_altitude, k2_time,
            params.ascent_rate, params.max_altitude, interpolate_wind
        )

        k3_lat, k3_lon = _destination(lat, lon, k2_east * dt / 2.0, k2_north * dt / 2.0)
        k3_altitude = min(params.max_altitude, altitude + k2_up * dt / 2.0)
        k3_time = current_time + timedelta(seconds=dt / 2.0)
        k3_east, k3_north, k3_up = _trajectory_derivative(
            forecast, k3_lat, k3_lon, k3_altitude, k3_time,
            params.ascent_rate, params.max_altitude, interpolate_wind
        )

        k4_lat, k4_lon = _destination(lat, lon, k3_east * dt, k3_north * dt)
        k4_altitude = min(params.max_altitude, altitude + k3_up * dt)
        k4_time = current_time + timedelta(seconds=dt)
        k4_east, k4_north, k4_up = _trajectory_derivative(
            forecast, k4_lat, k4_lon, k4_altitude, k4_time,
            params.ascent_rate, params.max_altitude, interpolate_wind
        )

        east_disp = dt / 6.0 * (k1_east + 2.0 * k2_east + 2.0 * k3_east + k4_east)
        north_disp = dt / 6.0 * (k1_north + 2.0 * k2_north + 2.0 * k3_north + k4_north)
        vert_disp = dt / 6.0 * (k1_up + 2.0 * k2_up + 2.0 * k3_up + k4_up)

        lat, lon = _destination(lat, lon, east_disp, north_disp)
        altitude = min(params.max_altitude, altitude + vert_disp)
        current_time += timedelta(seconds=dt)
        elapsed_seconds += dt

        speed, direction = interpolate_wind(
            forecast, lat, lon, altitude, current_time
        )

        points.append(TrajectoryPoint(
            time=current_time,
            lat=lat,
            lon=lon,
            altitude=altitude,
            wind_speed=speed,
            wind_direction=direction,
        ))
        speeds.append(speed)
        directions.append(direction)

    if not points:
        raise ValueError("Траектория не содержит точек.")

    segment_distances = [
        _distance_m(a.lat, a.lon, b.lat, b.lon)
        for a, b in zip(points, points[1:])
    ]

    prevailing_direction = _average_wind_direction(speeds, directions)

    return Trajectory(
        start=points[0],
        end=points[-1],
        distance_km=sum(segment_distances) / 1000.0,
        average_wind_speed=sum(speeds) / len(speeds),
        max_wind_speed=max(speeds),
        prevailing_direction=prevailing_direction,
        points=points,
    )


def generate_launch_points(
    center: GeoPoint,
    radius_m: float = 1000.0,
    radius_tolerance_m: float = 100.0,
    num_points: int = 9,
) -> List[GeoPoint]:
    points = [center]
    r_min = max(0.0, radius_m - radius_tolerance_m)
    r_max = radius_m + radius_tolerance_m

    for i in range(num_points - 1):
        angle = 2.0 * 3.141592653589793 * i / (num_points - 1)
        r = (r_min + r_max) / 2.0 if num_points <= 5 else random.uniform(r_min, r_max)
        dlat = (r * cos(angle)) / 111_320.0
        dlon = (r * sin(angle)) / (111_320.0 * cos(radians(center.lat)))
        points.append(GeoPoint(
            lat=center.lat + dlat,
            lon=center.lon + dlon,
        ))

    return points


def find_favorable_conditions(
    target: GeoPoint,
    launch_center: GeoPoint,
    forecast: dict,
    search_start: datetime,
    search_end: datetime,
    *,
    launch_radius_m: float = 1000.0,
    radius_tolerance_m: float = 100.0,
    time_step_hours: float = 1.0,
    window_half_width_hours: float = 3.0,
    max_acceptable_distance_m: float = 5000.0,
    ascent_rate: float = 5.0,
    max_altitude: float = 8000.0,
    duration_hours: float = 4.0,
    step_minutes: float = 2.0,
    start_altitude: float = 0.0,
    points_per_circle: int = 7,
    interpolate_wind: WindInterpolator = default_interpolate_wind,
) -> List[FavorableWindow]:
    if search_end <= search_start:
        raise ValueError("search_end должен быть позже search_start")

    launch_times: List[datetime] = []
    t = search_start
    delta = timedelta(hours=time_step_hours)
    while t <= search_end:
        launch_times.append(t)
        t += delta

    launch_points = generate_launch_points(
        center=launch_center,
        radius_m=launch_radius_m,
        radius_tolerance_m=radius_tolerance_m,
        num_points=points_per_circle,
    )

    all_candidates: List[LaunchCandidate] = []

    for launch_time in launch_times:
        for lp in launch_points:
            params = FlightParameters(
                start=lp,
                start_time=launch_time,
                start_altitude=start_altitude,
                max_altitude=max_altitude,
                ascent_rate=ascent_rate,
                duration_hours=duration_hours,
                step_minutes=step_minutes,
            )

            try:
                traj = calculate_trajectory(
                    params,
                    forecast,
                    interpolate_wind=interpolate_wind,
                )
            except Exception:
                continue

            min_dist = float("inf")
            closest_pt: Optional[TrajectoryPoint] = None

            for pt in traj.points:
                dist = _distance_m(pt.lat, pt.lon, target.lat, target.lon)
                if dist < min_dist:
                    min_dist = dist
                    closest_pt = pt

            if closest_pt is None:
                continue

            if min_dist <= max_acceptable_distance_m:
                all_candidates.append(LaunchCandidate(
                    launch_time=launch_time,
                    launch_point=lp,
                    trajectory=traj,
                    min_distance_to_target_m=min_dist,
                    closest_point=closest_pt,
                ))

    if not all_candidates:
        return []

    all_candidates.sort(key=lambda c: c.launch_time)

    windows: List[FavorableWindow] = []
    used = set()

    for cand in all_candidates:
        if id(cand) in used:
            continue

        window_start = cand.launch_time - timedelta(hours=window_half_width_hours)
        window_end = cand.launch_time + timedelta(hours=window_half_width_hours)

        group = [
            c for c in all_candidates
            if window_start <= c.launch_time <= window_end
        ]

        for c in group:
            used.add(id(c))

        group.sort(key=lambda c: c.min_distance_to_target_m)
        best = group[:5]

        windows.append(FavorableWindow(
            date=cand.launch_time.strftime("%Y-%m-%d"),
            window_start=window_start,
            window_end=window_end,
            best_candidates=best,
        ))

    windows.sort(
        key=lambda w: min(c.min_distance_to_target_m for c in w.best_candidates)
    )

    return windows


def print_favorable_windows(
    windows: List[FavorableWindow],
    top_n: int = 5,
) -> None:
    if not windows:
        print("Благоприятных условий не найдено.")
        return

    print(f"Найдено благоприятных окон: {len(windows)}\n")

    for i, w in enumerate(windows[:top_n], 1):
        best = w.best_candidates[0]
        print("=" * 72)
        print(f"Окно #{i}")
        print(f"Дата: {w.date}")
        print(f"Рекомендуемое время: {w.recommended_time.strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"Окно запуска (±3 ч): {w.window_start.strftime('%H:%M')} — {w.window_end.strftime('%H:%M')} UTC")
        print(f"Лучшее расстояние: {best.min_distance_to_target_m:.0f} м")
        print(f"Точка запуска: {best.launch_point.lat:.5f}, {best.launch_point.lon:.5f}")
        print(f"Точка максимального сближения: "
              f"{best.closest_point.lat:.5f}, {best.closest_point.lon:.5f} "
              f"(h={best.closest_point.altitude:.0f} м, t={best.closest_point.time.strftime('%H:%M')})")
        print(f"Длина траектории: {best.trajectory.distance_km:.1f} км")
        print(f"Средний ветер: {best.trajectory.average_wind_speed:.1f} м/с")
        print(f"Преобладающее направление ветра: {best.trajectory.prevailing_direction:.0f}°")
        print()


if __name__ == "__main__":
    from datetime import timezone

    target = GeoPoint(lat=55.7558, lon=37.6173)
    launch_center = GeoPoint(lat=55.8200, lon=37.5000)
    forecast: Dict = {}

    search_start = datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)
    search_end = datetime(2026, 8, 8, 23, 0, tzinfo=timezone.utc)

    windows = find_favorable_conditions(
        target=target,
        launch_center=launch_center,
        forecast=forecast,
        search_start=search_start,
        search_end=search_end,
        time_step_hours=1.0,
        window_half_width_hours=3.0,
        max_acceptable_distance_m=8000.0,
        ascent_rate=5.0,
        max_altitude=9000.0,
        duration_hours=5.0,
        points_per_circle=7,
    )

    print_favorable_windows(windows, top_n=5)
