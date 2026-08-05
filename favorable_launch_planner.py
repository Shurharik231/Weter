from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import asin, cos, degrees, radians, sin, sqrt, atan2
import random
import time
from typing import Any, Callable

from models import FlightParameters, StartPoint, Trajectory, TrajectoryPoint
from trajectory import calculate_trajectory
from weather import interpolate_wind

EARTH_RADIUS_M = 6_371_000.0
ProgressCallback = Callable[[dict], None]


def _utc(value: datetime) -> datetime:
    """Normalize every internal datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _seconds_between(a: datetime, b: datetime) -> float:
    return (_utc(a) - _utc(b)).total_seconds()

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
    ensemble_p90_distance_m: float = 0.0
    score: float = float("inf")

@dataclass
class FavorableWindow:
    window_start: datetime
    window_end: datetime
    recommended_time: datetime
    candidates: list[Candidate] = field(default_factory=list)

def _distance_m(a: GeoPoint, b: GeoPoint) -> float:
    p1, p2 = radians(a.lat), radians(b.lat)
    dp = radians(b.lat - a.lat); dl = radians(b.lon - a.lon)
    h = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(max(0.0, min(1.0, h))))

def _offset(center: GeoPoint, east_m: float, north_m: float) -> GeoPoint:
    lat = center.lat + north_m / 111_320.0
    lon = center.lon + east_m / (111_320.0 * max(0.15, cos(radians(center.lat))))
    return GeoPoint(lat, lon)

def generate_launch_points(center: GeoPoint, radius_m: float, rings: int = 2, points_per_ring: int = 12) -> list[GeoPoint]:
    result = [center]
    rings = max(1, int(rings)); points_per_ring = max(8, int(points_per_ring))
    for ring in range(1, rings + 1):
        radius = radius_m * ring / rings
        count = max(8, points_per_ring * ring)
        for i in range(count):
            angle = 2 * 3.141592653589793 * i / count
            result.append(_offset(center, radius * sin(angle), radius * cos(angle)))
    return result

def _point_in_polygon(point: GeoPoint, polygon: list[GeoPoint]) -> bool:
    if len(polygon) < 3: return False
    inside = False; j = len(polygon) - 1
    for i, p in enumerate(polygon):
        q = polygon[j]
        if (p.lon > point.lon) != (q.lon > point.lon):
            x = (q.lat - p.lat) * (point.lon - p.lon) / (q.lon - p.lon) + p.lat
            if point.lat < x: inside = not inside
        j = i
    return inside

def _trajectory_hits_polygon(points: list[TrajectoryPoint], polygon: list[GeoPoint]) -> bool:
    return len(polygon) >= 3 and any(_point_in_polygon(GeoPoint(p.lat, p.lon), polygon) for p in points)

def _target_membership(point: GeoPoint, target: GeoPoint | None, radius_m: float, polygon: list[GeoPoint] | None) -> bool:
    if polygon and len(polygon) >= 3:
        return _point_in_polygon(point, polygon)
    return target is not None and _distance_m(point, target) <= radius_m

def _trajectory_quality(points: list[TrajectoryPoint], target: GeoPoint | None, radius_m: float, target_polygon: list[GeoPoint] | None = None) -> tuple[float, TrajectoryPoint, float, bool]:
    if not points: raise ValueError("Траектория не содержит точек")
    best_d = float("inf"); best = points[0]; inside = 0.0; hit = False
    for a, b in zip(points, points[1:]):
        if target is not None:
            da = _distance_m(GeoPoint(a.lat, a.lon), target); db = _distance_m(GeoPoint(b.lat, b.lon), target)
            if da < best_d: best_d, best = da, a
            if db < best_d: best_d, best = db, b
        ia = _target_membership(GeoPoint(a.lat, a.lon), target, radius_m, target_polygon)
        ib = _target_membership(GeoPoint(b.lat, b.lon), target, radius_m, target_polygon)
        dt = max(0.0, _seconds_between(b.time, a.time))
        if ia and ib: inside += dt; hit = True
        elif ia != ib: inside += dt * 0.5; hit = True
    if target is not None and len(points) == 1:
        best_d = _distance_m(GeoPoint(points[0].lat, points[0].lon), target)
    if target_polygon and len(target_polygon) >= 3:
        hit = hit or any(_point_in_polygon(GeoPoint(p.lat, p.lon), target_polygon) for p in points)
        if not hit: best_d = float("inf")
    return best_d, best, inside, hit

def _wind_vector(forecast: dict[str, Any], lat: float, lon: float, altitude: float, when: datetime) -> tuple[float, float]:
    speed, direction = interpolate_wind(forecast, lat, lon, altitude, _utc(when))
    towards = radians((direction + 180) % 360)
    return speed * sin(towards), speed * cos(towards)

def _surface_and_shear(forecast: dict[str, Any], point: GeoPoint, when: datetime, top_m: float) -> tuple[float, float]:
    when = _utc(when)
    surface = interpolate_wind(forecast, point.lat, point.lon, 10.0, when)[0]
    top_u, top_v = _wind_vector(forecast, point.lat, point.lon, max(100.0, top_m), when)
    low_u, low_v = _wind_vector(forecast, point.lat, point.lon, 10.0, when)
    return surface, sqrt((top_u-low_u)**2 + (top_v-low_v)**2) / max(1.0, top_m-10.0)

def _weather_hazard(forecast: dict[str, Any], points: list[TrajectoryPoint], precipitation_limit_mm: float) -> bool:
    cells = forecast.get("cells", [])
    if not cells: return False
    for p in points:
        cell = min(cells, key=lambda c: (float(c.get("latitude", 0))-p.lat)**2 + (float(c.get("longitude", 0))-p.lon)**2)
        hourly = cell.get("hourly", {}); times = hourly.get("time", [])
        if not times: continue
        p_time = _utc(p.time)
        parsed_times = [_utc(datetime.fromisoformat(t.replace("Z", "+00:00"))) for t in times]
        idx = min(range(len(parsed_times)), key=lambda i: abs(_seconds_between(parsed_times[i], p_time)))
        codes = hourly.get("weather_code", []); precip = hourly.get("precipitation", [])
        code = codes[idx] if idx < len(codes) else None; rain = precip[idx] if idx < len(precip) and precip[idx] is not None else 0.0
        if code is not None and int(code) in {95, 96, 99}: return True
        if float(rain) > precipitation_limit_mm: return True
    return False

def _perturb_forecast(forecast: dict[str, Any], seed: int, wind_sigma_mps: float) -> dict[str, Any]:
    rng = random.Random(seed); result = deepcopy(forecast)
    for cell in result.get("cells", []):
        hourly = cell.get("hourly", {}); time_count = len(hourly.get("time", []))
        if not time_count: continue
        common_e = common_n = 0.0; series_e = series_n = 0.0
        for level in [k[len("wind_speed_"):] for k in hourly if k.startswith("wind_speed_")]:
            sk, dk = f"wind_speed_{level}", f"wind_direction_{level}"
            speeds, directions = hourly.get(sk), hourly.get(dk)
            if not speeds or not directions: continue
            for i, (s, d) in enumerate(zip(speeds, directions)):
                if s is None or d is None: continue
                sigma = wind_sigma_mps * (1.0 + 0.35 * sqrt(max(0.0, i) / 24.0))
                common_e = 0.82 * common_e + rng.gauss(0, sigma * 0.30)
                common_n = 0.82 * common_n + rng.gauss(0, sigma * 0.30)
                series_e = 0.88 * series_e + rng.gauss(0, sigma * 0.55)
                series_n = 0.88 * series_n + rng.gauss(0, sigma * 0.55)
                towards = radians((float(d)+180) % 360)
                u = float(s) * sin(towards) + common_e + series_e
                v = float(s) * cos(towards) + common_n + series_n
                speed = sqrt(u*u + v*v)
                directions[i] = (degrees(atan2(u, v)) + 180) % 360 if speed > 1e-9 else 0.0
                speeds[i] = speed
    return result

def _ensemble_metrics(params: FlightParameters, base_forecast: dict[str, Any], target: GeoPoint | None, target_polygon: list[GeoPoint] | None, radius_m: float, members: int, wind_sigma_mps: float, restricted: list[list[GeoPoint]], hazards: list[list[GeoPoint]], progress: Callable[[int], None] | None = None) -> tuple[float, float, float]:
    distances: list[float] = []; successes = 0
    for member in range(max(1, members)):
        forecast = base_forecast if member == 0 else _perturb_forecast(base_forecast, member * 1009, wind_sigma_mps)
        try: trajectory = calculate_trajectory(params, forecast)
        except Exception: continue
        d, _, _, hit = _trajectory_quality(trajectory.points, target, radius_m, target_polygon); distances.append(d)
        restricted_hit = any(_trajectory_hits_polygon(trajectory.points, poly) for poly in restricted)
        hazard_hit = any(_trajectory_hits_polygon(trajectory.points, poly) for poly in hazards)
        if hit and not restricted_hit and not hazard_hit: successes += 1
        if progress: progress(member + 1)
    if not distances: return 0.0, float("inf"), float("inf")
    distances.sort(); n = len(distances)
    return successes / n, distances[n//2], distances[min(n-1, int(0.90*(n-1)))]

def find_favorable_windows(*, target: GeoPoint | None, target_polygon: list[GeoPoint] | None = None, launch_center: GeoPoint, forecast: dict[str, Any], search_start: datetime, search_end: datetime, launch_radius_m: float, target_radius_m: float, time_step_hours: float, duration_hours: float, step_minutes: float, ascent_rate: float, max_altitude: float, start_altitude: float, launch_points_rings: int, launch_points_per_ring: int, surface_wind_limit_mps: float, shear_limit_s_inv: float, ensemble_members: int, ensemble_wind_sigma_mps: float, precipitation_limit_mm: float, restricted_zones: list[list[GeoPoint]] | None = None, hazard_zones: list[list[GeoPoint]] | None = None, progress_callback: ProgressCallback | None = None) -> list[FavorableWindow]:
    search_start, search_end = _utc(search_start), _utc(search_end)
    restricted_zones = restricted_zones or []; hazard_zones = hazard_zones or []
    if target is None and not target_polygon: raise ValueError("Нужно задать target или target_polygon")
    points = generate_launch_points(launch_center, launch_radius_m, launch_points_rings, launch_points_per_ring)
    candidates: list[Candidate] = []; t = search_start; step = timedelta(hours=time_step_hours)
    times: list[datetime] = []
    while t <= search_end: times.append(t); t += step
    total_screen = len(points) * len(times); processed = 0; started = time.monotonic()
    if progress_callback: progress_callback({"stage":"screen","processed":0,"total":total_screen,"percent":0,"elapsed_s":0,"eta_s":None,"message":"Быстрый первичный отбор точек и времени","force":True})
    for t in times:
        for launch in points:
            params = FlightParameters(StartPoint(launch.lat, launch.lon), _utc(t), start_altitude, ascent_rate, max_altitude, duration_hours, int(max(1, round(step_minutes))))
            try: trajectory = calculate_trajectory(params, forecast)
            except Exception: processed += 1; continue
            d, closest, inside, hit = _trajectory_quality(trajectory.points, target, target_radius_m, target_polygon)
            surface, shear = _surface_and_shear(forecast, launch, _utc(t), max_altitude)
            restricted_hit = any(_trajectory_hits_polygon(trajectory.points, z) for z in restricted_zones)
            hazard_hit = _weather_hazard(forecast, trajectory.points, precipitation_limit_mm) or any(_trajectory_hits_polygon(trajectory.points, z) for z in hazard_zones)
            if hit and surface <= surface_wind_limit_mps and shear <= shear_limit_s_inv and not restricted_hit and not hazard_hit:
                pre_score = d / max(100.0, target_radius_m) - min(inside / 3600.0, 2.0) * 0.15 + (surface / max(0.1, surface_wind_limit_mps))*0.05 + (shear / max(1e-9, shear_limit_s_inv))*0.05
                candidates.append(Candidate(_utc(t), launch, trajectory, d, closest, inside, surface, shear, hazard_hit, restricted_hit, score=pre_score))
            processed += 1
            if progress_callback:
                elapsed = time.monotonic() - started; eta = elapsed / processed * (total_screen - processed) if processed else None
                progress_callback({"stage":"screen","processed":processed,"total":total_screen,"percent":100*processed/max(1,total_screen),"elapsed_s":elapsed,"eta_s":eta,"message":"Быстрый первичный отбор"})
    if not candidates:
        if progress_callback: progress_callback({"stage":"done","processed":1,"total":1,"percent":100,"elapsed_s":time.monotonic()-started,"eta_s":0,"message":"Подходящих кандидатов не найдено","force":True})
        return []
    candidates.sort(key=lambda c: c.score)
    target_count = min(len(candidates), max(24, int(len(candidates) * 0.20)))
    selected = candidates[:target_count]
    best_per_time: dict[datetime, Candidate] = {}
    for c in candidates:
        best_per_time.setdefault(c.launch_time, c)
    selected_ids = {id(c) for c in selected}
    for c in best_per_time.values():
        if len(selected) >= min(len(candidates), target_count + len(best_per_time)): break
        if id(c) not in selected_ids:
            selected.append(c); selected_ids.add(id(c))
    selected.sort(key=lambda c: c.score)
    total_ensemble = len(selected) * max(1, ensemble_members); ensemble_done = 0
    if progress_callback: progress_callback({"stage":"ensemble","processed":0,"total":total_ensemble,"percent":0,"elapsed_s":time.monotonic()-started,"eta_s":None,"message":f"Точный ансамблевый расчёт: {len(selected)} перспективных кандидатов","force":True})
    final: list[Candidate] = []
    for idx, c in enumerate(selected, 1):
        def member_progress(done: int, _idx=idx):
            nonlocal ensemble_done
            ensemble_done += 1
            if progress_callback:
                elapsed = time.monotonic() - started; eta = elapsed / ensemble_done * (total_ensemble - ensemble_done) if ensemble_done else None
                progress_callback({"stage":"ensemble","processed":ensemble_done,"total":total_ensemble,"percent":100*ensemble_done/max(1,total_ensemble),"elapsed_s":elapsed,"eta_s":eta,"message":f"Ансамблевый расчёт: кандидат {_idx}/{len(selected)}"})
        params = FlightParameters(StartPoint(c.launch_point.lat, c.launch_point.lon), _utc(c.launch_time), start_altitude, ascent_rate, max_altitude, duration_hours, int(max(1, round(step_minutes))))
        success, median, p90 = _ensemble_metrics(params, forecast, target, target_polygon, target_radius_m, ensemble_members, ensemble_wind_sigma_mps, restricted_zones, hazard_zones, member_progress)
        c.ensemble_success_rate, c.ensemble_median_distance_m, c.ensemble_p90_distance_m = success, median, p90
        c.score = c.ensemble_p90_distance_m / max(100.0, target_radius_m) - c.ensemble_success_rate * 2.0 + c.min_distance_m / max(100.0, target_radius_m)
        final.append(c)
    final.sort(key=lambda c: c.score)
    windows: list[FavorableWindow] = []
    for c in final:
        if not windows or _seconds_between(c.launch_time, windows[-1].window_end) > 3600:
            windows.append(FavorableWindow(c.launch_time, c.launch_time, c.launch_time, [c]))
        else:
            windows[-1].window_end = max(windows[-1].window_end, c.launch_time)
            windows[-1].candidates.append(c)
            windows[-1].recommended_time = min(windows[-1].candidates, key=lambda x: x.score).launch_time
    if progress_callback: progress_callback({"stage":"done","processed":1,"total":1,"percent":100,"elapsed_s":time.monotonic()-started,"eta_s":0,"message":"Расчёт завершён","force":True})
    return windows
