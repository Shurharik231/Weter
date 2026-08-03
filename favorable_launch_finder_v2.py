from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import cos, radians, sin, sqrt
from typing import Callable, List, Optional, Tuple

from favorable_launch_finder import (
    Trajectory,
    TrajectoryPoint,
    FlightParameters,
    calculate_trajectory,
    _distance_m,
)


@dataclass
class GeoPoint:
    lat: float
    lon: float


@dataclass
class LaunchCandidate:
    launch_time: datetime
    launch_point: GeoPoint
    trajectory: Trajectory
    min_distance_to_target_m: float
    closest_point: TrajectoryPoint
    time_in_target_s: float = 0.0
    score: float = 0.0


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
        return min(self.best_candidates, key=lambda c: c.score).launch_time


def _offset_point(center: GeoPoint, east_m: float, north_m: float) -> GeoPoint:
    lat = center.lat + north_m / 111_320.0
    cos_lat = max(0.15, cos(radians(center.lat)))
    lon = center.lon + east_m / (111_320.0 * cos_lat)
    return GeoPoint(lat=lat, lon=lon)


def generate_launch_points(
    center: GeoPoint,
    radius_m: float = 1000.0,
    radius_tolerance_m: float = 100.0,
    num_points: int = 9,
) -> List[GeoPoint]:
    """Deterministically cover the permitted launch area.

    The previous implementation used random radii, so identical calculations
    could inspect different launch points. We now use the center plus evenly
    spaced rings, making results reproducible.
    """
    radius_m = max(0.0, radius_m)
    tolerance = max(0.0, radius_tolerance_m)
    outer = radius_m + tolerance
    inner = max(0.0, radius_m - tolerance)

    points = [center]
    count = max(4, int(num_points))
    ring_radius = (inner + outer) / 2.0

    for i in range(count):
        angle = 2.0 * 3.141592653589793 * i / count
        points.append(_offset_point(
            center,
            east_m=ring_radius * sin(angle),
            north_m=ring_radius * cos(angle),
        ))

    # If the allowed radius is large, add a second deterministic outer ring.
    if outer > 0 and count >= 8:
        for i in range(count):
            angle = 2.0 * 3.141592653589793 * (i + 0.5) / count
            points.append(_offset_point(
                center,
                east_m=outer * sin(angle),
                north_m=outer * cos(angle),
            ))

    return points


def _trajectory_quality(
    trajectory: Trajectory,
    target: GeoPoint,
    target_radius_m: float,
) -> Tuple[float, Optional[TrajectoryPoint], float]:
    min_distance = float("inf")
    closest: Optional[TrajectoryPoint] = None
    inside_seconds = 0.0

    for a, b in zip(trajectory.points, trajectory.points[1:]):
        da = _distance_m(a.lat, a.lon, target.lat, target.lon)
        db = _distance_m(b.lat, b.lon, target.lat, target.lon)
        if da < min_distance:
            min_distance, closest = da, a
        if db < min_distance:
            min_distance, closest = db, b

        # Count the interval when the trajectory is inside the target area.
        # Linear interpolation is sufficient for the short integration step.
        dt = max(0.0, (b.time - a.time).total_seconds())
        if da <= target_radius_m and db <= target_radius_m:
            inside_seconds += dt
        elif da <= target_radius_m or db <= target_radius_m:
            inside_seconds += dt * 0.5

    if trajectory.points and closest is None:
        p = trajectory.points[0]
        min_distance = _distance_m(p.lat, p.lon, target.lat, target.lon)
        closest = p

    return min_distance, closest, inside_seconds


def _candidate_score(
    min_distance_m: float,
    target_radius_m: float,
    time_in_target_s: float,
) -> float:
    """Lower is better; this is a ranking score, not a probability."""
    radius = max(100.0, target_radius_m)
    distance_term = min_distance_m / radius
    dwell_bonus = min(time_in_target_s / 3600.0, 2.0)
    return distance_term - 0.75 * dwell_bonus


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
    interpolate_wind: Callable = None,
) -> List[FavorableWindow]:
    if search_end <= search_start:
        raise ValueError("search_end должен быть позже search_start")
    if time_step_hours <= 0:
        raise ValueError("time_step_hours должен быть больше 0")
    if duration_hours <= 0:
        raise ValueError("duration_hours должен быть больше 0")

    # max_acceptable_distance_m is the target capture radius in the current UI.
    target_radius = max(100.0, max_acceptable_distance_m)
    launch_points = generate_launch_points(
        launch_center,
        radius_m=launch_radius_m,
        radius_tolerance_m=radius_tolerance_m,
        num_points=points_per_circle,
    )

    candidates: List[LaunchCandidate] = []
    current = search_start
    time_delta = timedelta(hours=time_step_hours)

    while current <= search_end:
        for launch_point in launch_points:
            params = FlightParameters(
                start=launch_point,
                start_time=current,
                start_altitude=start_altitude,
                max_altitude=max_altitude,
                ascent_rate=ascent_rate,
                duration_hours=duration_hours,
                step_minutes=step_minutes,
            )
            try:
                if interpolate_wind is None:
                    trajectory = calculate_trajectory(params, forecast)
                else:
                    trajectory = calculate_trajectory(
                        params, forecast, interpolate_wind=interpolate_wind
                    )
            except Exception:
                continue

            min_distance, closest, inside_seconds = _trajectory_quality(
                trajectory, target, target_radius
            )
            if closest is None or min_distance > target_radius:
                continue

            score = _candidate_score(
                min_distance, target_radius, inside_seconds
            )
            candidates.append(LaunchCandidate(
                launch_time=current,
                launch_point=launch_point,
                trajectory=trajectory,
                min_distance_to_target_m=min_distance,
                closest_point=closest,
                time_in_target_s=inside_seconds,
                score=score,
            ))

        current += time_delta

    if not candidates:
        return []

    # For every launch time keep only the best spatial candidate. This prevents
    # one time slot from dominating the result merely because many nearby
    # launch points were sampled.
    best_by_time = {}
    for candidate in candidates:
        key = candidate.launch_time
        old = best_by_time.get(key)
        if old is None or candidate.score < old.score:
            best_by_time[key] = candidate

    ranked = sorted(best_by_time.values(), key=lambda c: (c.score, c.launch_time))

    # Group successful launch times into actual windows. Nearby successful
    # times belong to one window; gaps create separate windows.
    successful = sorted(best_by_time.values(), key=lambda c: c.launch_time)
    groups: List[List[LaunchCandidate]] = []
    gap = time_delta * 1.5
    for candidate in successful:
        if not groups or candidate.launch_time - groups[-1][-1].launch_time > gap:
            groups.append([candidate])
        else:
            groups[-1].append(candidate)

    windows: List[FavorableWindow] = []
    for group in groups:
        group.sort(key=lambda c: c.score)
        center_time = group[0].launch_time
        window_start = max(
            search_start,
            group[0].launch_time - timedelta(hours=window_half_width_hours),
        )
        window_end = min(
            search_end,
            group[-1].launch_time + timedelta(hours=window_half_width_hours),
        )
        windows.append(FavorableWindow(
            date=center_time.strftime("%Y-%m-%d"),
            window_start=window_start,
            window_end=window_end,
            best_candidates=group[:5],
        ))

    windows.sort(key=lambda w: min(c.score for c in w.best_candidates))
    return windows


def print_favorable_windows(windows: List[FavorableWindow], top_n: int = 5) -> None:
    if not windows:
        print("Благоприятных условий не найдено.")
        return
    for i, window in enumerate(windows[:top_n], 1):
        best = min(window.best_candidates, key=lambda c: c.score)
        print("=" * 72)
        print(f"Окно #{i}: {window.window_start} — {window.window_end}")
        print(f"Рекомендуемый запуск: {window.recommended_time}")
        print(f"Точка запуска: {best.launch_point.lat:.5f}, {best.launch_point.lon:.5f}")
        print(f"Минимальное расстояние: {best.min_distance_to_target_m:.0f} м")
        print(f"Время в целевой области: {best.time_in_target_s / 60:.1f} мин")
        print(f"Сближение: {best.closest_point.time} на высоте {best.closest_point.altitude:.0f} м")
        print(f"Оценка: {best.score:.3f} (меньше — лучше)")
