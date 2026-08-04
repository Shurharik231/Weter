from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator

from backtrajectory import BalloonModel, Detection
from backtrajectory_accuracy import AccurateBackTrajectorySolver, AccurateEnsembleEstimator, AccurateOpenMeteoProvider
from models import FlightParameters, StartPoint
from trajectory import calculate_trajectory
from weather import build_grid, fetch_grid, interpolate_wind
from favorable_launch_planner import GeoPoint, find_favorable_windows

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Wind Trajectory", version="3.6.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

class StartModel(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)

class TrajectoryRequest(BaseModel):
    start: StartModel
    start_time: datetime
    start_altitude: float = Field(0, ge=0)
    ascent_rate: float = Field(5, ge=0)
    max_altitude: float = Field(10000, ge=0)
    duration_hours: float = Field(24, gt=0, le=168)
    step_minutes: int = Field(5, ge=1, le=60)

class BackTrajectoryRequest(BaseModel):
    detection: StartModel
    detection_time: datetime
    altitude: float = Field(..., ge=0)
    ascent_rate: float | None = Field(None, gt=0, le=50)
    start_altitude: float | None = Field(None, ge=0)
    duration_hours: float | None = Field(None, gt=0, le=48)
    step_minutes: int | None = Field(None, ge=1, le=30)
    members: int = Field(150, ge=20, le=500)

class FavorableRequest(BaseModel):
    target: StartModel | None = None
    target_polygon: list[StartModel] = Field(default_factory=list)
    launch_center: StartModel
    search_start: datetime
    search_end: datetime
    launch_radius_m: float = Field(1000, ge=100, le=50000)
    target_radius_m: float = Field(5000, ge=100, le=50000)
    time_step_hours: float = Field(1, gt=0, le=6)
    duration_hours: float = Field(4, gt=0, le=168)
    step_minutes: float = Field(2, ge=0.5, le=30)
    ascent_rate: float = Field(5, ge=0, le=20)
    max_altitude: float = Field(8000, ge=1000, le=35000)
    start_altitude: float = Field(0, ge=0)
    launch_points_rings: int = Field(2, ge=1, le=6)
    launch_points_per_ring: int = Field(12, ge=8, le=48)
    surface_wind_limit_mps: float = Field(10, ge=0, le=50)
    shear_limit_s_inv: float = Field(0.002, gt=0, le=0.02)
    ensemble_members: int = Field(50, ge=5, le=150)
    ensemble_wind_sigma_mps: float = Field(1.5, ge=0, le=10)
    precipitation_limit_mm: float = Field(5, ge=0, le=100)
    restricted_zones: list[list[StartModel]] = Field(default_factory=list)
    hazard_zones: list[list[StartModel]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target(self):
        if self.target is None and len(self.target_polygon) < 3:
            raise ValueError("Укажите target или минимум 3 точки target_polygon")
        return self

def ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def safe_detail(exc: Exception) -> str:
    return str(exc)[:500] or exc.__class__.__name__

def trajectory_grid_radius_km(duration_hours: float) -> float:
    # Larger horizons require a materially larger meteorological domain.
    # The integrator now fails rather than silently clamping wind at the edge.
    return min(8000.0, max(600.0, 600.0 + duration_hours * 44.0))

def serialize_window(window) -> dict:
    candidates = []
    for c in window.candidates:
        candidates.append({
            "launch_time": c.launch_time.isoformat(),
            "launch_point": {"lat": c.launch_point.lat, "lon": c.launch_point.lon},
            "min_distance_to_target_m": round(c.min_distance_m, 1),
            "time_in_target_s": round(c.time_in_target_s, 1),
            "surface_wind_mps": round(c.surface_wind_mps, 2),
            "shear_s_inv": c.shear_s_inv,
            "ensemble_success_rate": round(c.ensemble_success_rate, 4),
            "ensemble_median_distance_m": round(c.ensemble_median_distance_m, 1),
            "ensemble_p90_distance_m": round(c.ensemble_p90_distance_m, 1),
            "score": round(c.score, 4),
            "closest_point": {"time": c.closest_point.time.isoformat(), "lat": c.closest_point.lat, "lon": c.closest_point.lon, "altitude": round(c.closest_point.altitude, 1)},
            "trajectory": c.trajectory.to_dict(),
        })
    return {"window_start": window.window_start.isoformat(), "window_end": window.window_end.isoformat(), "recommended_time": window.recommended_time.isoformat(), "best_candidates": candidates}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "wind-trajectory", "version": app.version}

@app.get("/api/wind")
async def get_wind(lat: float, lon: float, altitude: float = 1000):
    try:
        now = datetime.now(timezone.utc)
        latitudes, longitudes = build_grid(lat, lon, 150)
        forecast = await fetch_grid(latitudes, longitudes, now, now)
        speed, direction = interpolate_wind(forecast, lat, lon, altitude, now)
        return {"lat": lat, "lon": lon, "altitude": altitude, "wind_speed": speed, "wind_direction": direction, "time": now.isoformat()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Weather provider error: {safe_detail(exc)}") from exc

@app.post("/api/trajectory")
async def create_trajectory(request: TrajectoryRequest):
    try:
        start_time = ensure_utc(request.start_time)
        end_time = start_time + timedelta(hours=request.duration_hours)
        radius = trajectory_grid_radius_km(request.duration_hours)
        latitudes, longitudes = build_grid(request.start.lat, request.start.lon, radius)
        forecast = await fetch_grid(latitudes, longitudes, start_time, end_time)
        params = FlightParameters(StartPoint(request.start.lat, request.start.lon), start_time, request.start_altitude, request.ascent_rate, request.max_altitude, request.duration_hours, request.step_minutes)
        return calculate_trajectory(params, forecast).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trajectory/weather error: {safe_detail(exc)}") from exc

@app.post("/api/backtrajectory")
async def create_backtrajectory(request: BackTrajectoryRequest):
    try:
        detection_time = ensure_utc(request.detection_time)
        detection = Detection(lat=request.detection.lat, lon=request.detection.lon, altitude_m=request.altitude, time=detection_time)
        duration_hours = request.duration_hours or 4.0
        weather = AccurateOpenMeteoProvider(workdir=BASE_DIR / "weather_cache")
        weather.download(detection=detection, max_hours=duration_hours, max_ascent_rate_mps=60.0)
        balloon = BalloonModel(ascent_rate_mps=request.ascent_rate or 5.0, ascent_rate_sigma_mps=0.7)
        solver = AccurateBackTrajectorySolver(weather=weather, balloon=balloon, step_seconds=float((request.step_minutes or 1)*60), max_duration_hours=duration_hours)
        estimator = AccurateEnsembleEstimator(solver=solver, members=request.members, wind_sigma_mps=1.5, detection_time_sigma_s=60.0, altitude_sigma_m=50.0, seed=42)
        result = estimator.run(detection)
        representative = result.trajectories[0] if result.trajectories else []
        return {"status":"ok","result":{"detection":result.detection,"launch_estimate":result.launch_estimate,"zones":result.zones,"ensemble_size":result.ensemble_size,"valid_members":result.valid_members,"trajectories":result.trajectories,"trajectory":representative,"points":representative}}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Backtrajectory/weather error: {safe_detail(exc)}") from exc

@app.post("/api/favorable")
async def create_favorable(request: FavorableRequest):
    try:
        start, end = ensure_utc(request.search_start), ensure_utc(request.search_end)
        if end <= start: raise HTTPException(status_code=400, detail="search_end must be after search_start")
        radius = trajectory_grid_radius_km(request.duration_hours) + request.launch_radius_m / 1000.0
        target_center = request.target or request.target_polygon[0]
        center_lat = (request.launch_center.lat + target_center.lat) / 2; center_lon = (request.launch_center.lon + target_center.lon) / 2
        latitudes, longitudes = build_grid(center_lat, center_lon, radius)
        forecast = await fetch_grid(latitudes, longitudes, start, end + timedelta(hours=request.duration_hours))
        target = GeoPoint(request.target.lat, request.target.lon) if request.target else None
        target_polygon = [GeoPoint(p.lat, p.lon) for p in request.target_polygon] or None
        restricted = [[GeoPoint(p.lat,p.lon) for p in poly] for poly in request.restricted_zones]
        hazards = [[GeoPoint(p.lat,p.lon) for p in poly] for poly in request.hazard_zones]
        windows = find_favorable_windows(target=target, target_polygon=target_polygon, launch_center=GeoPoint(request.launch_center.lat, request.launch_center.lon), forecast=forecast, search_start=start, search_end=end, launch_radius_m=request.launch_radius_m, target_radius_m=request.target_radius_m, time_step_hours=request.time_step_hours, duration_hours=request.duration_hours, step_minutes=request.step_minutes, ascent_rate=request.ascent_rate, max_altitude=request.max_altitude, start_altitude=request.start_altitude, launch_points_rings=request.launch_points_rings, launch_points_per_ring=request.launch_points_per_ring, surface_wind_limit_mps=request.surface_wind_limit_mps, shear_limit_s_inv=request.shear_limit_s_inv, ensemble_members=request.ensemble_members, ensemble_wind_sigma_mps=request.ensemble_wind_sigma_mps, precipitation_limit_mm=request.precipitation_limit_mm, restricted_zones=restricted, hazard_zones=hazards)
        return {"status":"ok","count":len(windows),"windows":[serialize_window(w) for w in windows]}
    except HTTPException: raise
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc: raise HTTPException(status_code=502, detail=f"Favorable search/weather error: {safe_detail(exc)}") from exc

@app.get("/api/config")
async def config():
    return {"max_trajectory_hours":168,"default_step_minutes":5,"backtrajectory":{"bilinear_spatial_wind":True,"correlated_wind_bias":True,"observation_uncertainty":True},"favorable":{"ensemble":True,"correlated_uncertainty":True,"surface_wind_filter":True,"wind_shear_filter":True,"weather_hazard_filter":True,"restricted_zones":True,"target_polygon":True,"ensemble_p90":True}}