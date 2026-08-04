from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import asin, cos, degrees, radians, sin, sqrt, atan2
import random
from typing import Any

from models import FlightParameters, StartPoint, Trajectory, TrajectoryPoint
from trajectory import calculate_trajectory
from weather import interpolate_wind

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float


@dataclass
class Candidate:
    launch_time: datetime
    launch_point: GeoPoint
    trajectory: Trajectory
    min_distance_m: float
    closest_point: TrajectoryPoint
    time_in_target_s: float
    surface_wind_mps: float
    shear_s_inv: float
    hazard_hit: bool
    restricted_hit: bool
    ensemble_success_rate: float = 0.0
    ensemble_median_distance_m: float = 0.0
    score: float = float("inf")


@dataclass
class FavorableWindow:
    window_start: datetime
    window_end: datetime
    recommended_time: datetime
    candidates: list[Candidate] = field(default_factory=list)


def _distance_m(a: GeoPoint, b: GeoPoint) -> float:
    p1, p2 = radians(a.lat), radians(b.lat)
    dp = radians(b.lat - a.lat)
    dl = radians(b.lon - a.lon)
    h = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(max(0.0, min(1.0, h))))


def _offset(center: GeoPoint, east_m: float, north_m: float) -> GeoPoint:
    lat = center.lat + north_m / 111_320.0
    lon = center.lon + east_m / (111_320.0 * max(0.15, cos(radians(center.lat))))
    return GeoPoint(lat, lon)


def generate_launch_points(center: GeoPoint, radius_m: float, rings: int = 2, points_per_ring: int = 12) -> list[GeoPoint]:
    """Deterministic coverage of the launch area; no random launch points."""
    result = [center]
    for ring in range(1, max(1, rings) + 1):
        radius = radius_m * ring / max(1, rings)
        count = max(8, points_per_ring * ring)
        for i in range(count):
            angle = 2 * 3.141592653589793 * i / count
            result.append(_offset(center, radius * sin(angle), radius * cos(angle)))
    return result


def _point_in_polygon(point: GeoPoint, polygon: list[GeoPoint]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, p in enumerate(polygon):
        pi = ((p.lon > point.lon) != (polygon[j].lon > point.lon))
        if pi:
            cross = (polygon[j].lat - p.lat) * (point.lon - p.lon) / (polygon[j].lon - p.lon) + p.lat
            if point.lat < cross:
                inside = not inside
        j = i
    return inside


def _trajectory_hits_polygon(points: list[TrajectoryPoint], polygon: list[GeoPoint]) -> bool:
    if len(polygon) < 3:
        return False
    return any(_point_in_polygon(GeoPoint(p.lat, p.lon), polygon) for p in points)


def _trajectory_quality(points: list[TrajectoryPoint], target: GeoPoint, radius_m: float) -> tuple[float, TrajectoryPoint, float]:
    best_d = float("inf")
    best = points[0]
    inside = 0.0
    for a, b in zip(points, points[1:]):
        da = _distance_m(GeoPoint(a.lat, a.lon), target)
        db = _distance_m(GeoPoint(b.lat, b.lon), target)
        if da < best_d:
            best_d, best = da, a
        if db < best_d:
            best_d, best = db, b
        dt = max(0.0, (b.time - a.time).total_seconds())
        if da <= radius_m and db <= radius_m:
            inside += dt
        elif (da <= radius_m) != (db <= radius_m):
            inside += dt * 0.5
    return best_d, best, inside


def _wind_vector(forecast: dict[str, Any], lat: float, lon: float, altitude: float, when: datetime) -> tuple[float, float]:
    speed, direction = interpolate_wind(forecast, lat, lon, altitude, when)
    towards = radians((direction + 180) % 360)
    return speed * sin(towards), speed * cos(towards)


def _surface_and_shear(forecast: dict[str, Any], point: GeoPoint, when: datetime, top_m: float) -> tuple[float, float]:
    surface = interpolate_wind(forecast, point.lat, point.lon, 10.0, when)[0]
    top_u, top_v = _wind_vector(forecast, point.lat, point.lon, max(100.0, top_m), when)
    low_u, low_v = _wind_vector(forecast, point.lat, point.lon, 10.0, when)
    shear = sqrt((top_u - low_u) ** 2 + (top_v - low_v) ** 2) / max(1.0, top_m - 10.0)
    return surface, shear


def _weather_hazard(forecast: dict[str, Any], points: list[TrajectoryPoint], precipitation_limit_mm: float) -> bool:
    """Use hourly weather_code/precipitation where available. Missing fields do not create a false hazard."""
    cells = forecast.get("cells", [])
    if not cells:
        return False
    for p in points:
        cell = min(cells, key=lambda c: (float(c.get("latitude", 0)) - p.lat) ** 2 + (float(c.get("longitude", 0)) - p.lon) ** 2)
        hourly = cell.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            continue
        # Nearest hourly sample; trajectory is already integrated at short intervals.
        idx = min(range(len(times)), key=lambda i: abs(datetime.fromisoformat(times[i].replace("Z", "+00:00")) - p.time))
        code = hourly.get("weather_code", [None] * len(times))[idx]
        precip = hourly.get("precipitation", [0.0] * len(times))[idx] or 0.0
        if code is not None and int(code) in {95, 96, 99}:
            return True
        if float(precip) > precipitation_limit_mm:
            return True
    return False


def _perturb_forecast(forecast: dict[str, Any], seed: int, wind_sigma_mps: float) -> dict[str, Any]:
    """Perturb wind vectors in u/v space so an ensemble samples forecast uncertainty."""
    rng = random.Random(seed)
    result = deepcopy(forecast)
    for cell in result.get("cells", []):
        hourly = cell.get("hourly", {})
        for level in [k[len("wind_speed_"):] for k in hourly if k.startswith("wind_speed_")]:
            sk, dk = f"wind_speed_{level}", f"wind_direction_{level}"
            speeds, directions = hourly.get(sk), hourly.get(dk)
            if not speeds or not directions:
                continue
            for i, (s, d) in enumerate(zip(speeds, directions)):
                if s is None or d is None:
                    continue
                towards = radians((float(d) + 180) % 360)
                u = float(s) * sin(towards) + rng.gauss(0, wind_sigma_mps)
                v = float(s) * cos(towards) + rng.gauss(0, wind_sigma_mps)
                speed = sqrt(u * u + v * v)
                direction_from = (degrees(atan2(u, v)) + 180) % 360 if speed > 1e-9 else 0.0
                speeds[i] = speed
                directions[i] = direction_from
    return result


def _ensemble_metrics(base_params: FlightParameters, base_forecast: dict[str, Any], target: GeoPoint, radius_m: float, members: int, wind_sigma_mps: float, restricted: list[list[GeoPoint]], hazards: list[list[GeoPoint]]) -> tuple[float, float]:
    distances = []
    successes = 0
    for member in range(max(1, members)):
        forecast = base_forecast if member == 0 else _perturb_forecast(base_forecast, member * 1009, wind_sigma_mps)
        try:
            trajectory = calculate_trajectory(base_params, forecast)
        except Exception:
            continue
        d, _, _ = _trajectory_quality(trajectory.points, target, radius_m)
        distances.append(d)
        restricted_hit = any(_trajectory_hits_polygon(trajectory.points, poly) for poly in restricted)
        hazard_hit = any(_trajectory_hits_polygon(trajectory.points, poly) for poly in hazards)
        if d <= radius_m and not restricted_hit and not hazard_hit:
            successes += 1
    if not distances:
        return 0.0, float("inf")
    distances.sort()
    median = distances[len(distances) // 2]
    return successes / len(distances), median


def find_favorable_windows(*, target: GeoPoint, launch_center: GeoPoint, forecast: dict[str, Any], search_start: datetime, search_end: datetime, launch_radius_m: float, target_radius_m: float, time_step_hours: float, duration_hours: float, step_minutes: float, ascent_rate: float, max_altitude: float, start_altitude: float, launch_points_rings: int, launch_points_per_ring: int, surface_wind_limit_mps: float, shear_limit_s_inv: float, ensemble_members: int, ensemble_wind_sigma_mps: float, precipitation_limit_mm: float, restricted_zones: list[list[GeoPoint]] | None = None, hazard_zones: list[list[GeoPoint]] | None = None) -> list[FavorableWindow]:
    restricted_zones = restricted_zones or []
    hazard_zones = hazard_zones or []
    points = generate_launch_points(launch_center, launch_radius_m, launch_points_rings, launch_points_per_ring)
    candidates: list[Candidate] = []
    t = search_start
    step = timedelta(hours=time_step_hours)

    while t <= search_end:
        for launch in points:
            params = FlightParameters(StartPoint(launch.lat, launch.lon), t, start_altitude, ascent_rate, max_altitude, duration_hours, int(max(1, round(step_minutes))))
            try:
                trajectory = calculate_trajectory(params, forecast)
            except Exception:
                continue
            d, closest, inside = _trajectory_quality(trajectory.points, target, target_radius_m)
            surface, shear = _surface_and_shear(forecast, launch, t, max_altitude)
            restricted_hit = any(_trajectory_hits_polygon(trajectory.points, z) for z in restricted_zones)
            hazard_hit = _weather_hazard(forecast, trajectory.points, precipitation_limit_mm) or any(_trajectory_hits_polygon(trajectory.points, z) for z in hazard_zones)
            if d > target_radius_m or surface > surface_wind_limit_mps or shear > shear_limit_s_inv or restricted_hit or hazard_hit:
                continue
            success_rate, median_d = _ensemble_metrics(params, forecast, target, target_radius_m, ensemble_members, ensemble_wind_sigma_mps, restricted_zones, hazard_zones)
            if success_rate <= 0:
                continue
            score = (median_d / max(100.0, target_radius_m)) + 1.5 * (1 - success_rate) - min(inside / 3600.0, 2.0) * 0.25
            candidates.append(Candidate(t, launch, trajectory, d, closest, inside, surface, shear, hazard_hit, restricted_hit, success_rate, median_d, score))
        t += step

    # One best launch point per launch time.
    best_by_time: dict[datetime, Candidate] = {}
    for c in candidates:
        if c.launch_time not in best_by_time or c.score < best_by_time[c.launch_time].score:
            best_by_time[c.launch_time] = c
    successful = sorted(best_by_time.values(), key=lambda c: c.launch_time)
    if not successful:
        return []

    groups: list[list[Candidate]] = []
    max_gap = step * 1.5
    for c in successful:
        if not groups or c.launch_time - groups[-1][-1].launch_time > max_gap:
            groups.append([c])
        else:
            groups[-1].append(c)

    windows = []
    half = timedelta(hours=max(0.0, time_step_hours) / 2)
    for group in groups:
        group.sort(key=lambda c: c.score)
        windows.append(FavorableWindow(group[0].launch_time - half, group[-1].launch_time + half, group[0].launch_time, group[:5]))
    return sorted(windows, key=lambda w: w.candidates[0].score)
