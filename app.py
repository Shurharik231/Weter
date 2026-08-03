from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from backtrajectory import (
    BalloonModel,
    Detection,
    ERA5Provider,
    EnsembleEstimator,
    BackTrajectorySolver,
)

from models import (
    FlightParameters,
    StartPoint,
)

from trajectory import calculate_trajectory

from weather import (
    build_grid,
    fetch_grid,
    interpolate_wind,
)

from favorable_launch_finder import (
    GeoPoint,
    find_favorable_conditions,
    print_favorable_windows,
    FavorableWindow,
    LaunchCandidate,
)


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Wind Trajectory",
    version="3.2.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "templates"
)


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
    step_minutes: int = Field(10, ge=1, le=60)


class BackTrajectoryRequest(BaseModel):
    detection: StartModel
    detection_time: datetime
    altitude: float = Field(..., ge=0)
    ascent_rate: float | None = Field(None, gt=0, le=50)
    start_altitude: float | None = Field(None, ge=0)
    duration_hours: float | None = Field(None, gt=0, le=48)
    step_minutes: int | None = Field(None, ge=1, le=60)


class FavorableRequest(BaseModel):
    target: StartModel
    launch_center: StartModel
    search_start: datetime
    search_end: datetime
    launch_radius_m: float = Field(1000.0, ge=100, le=5000)
    radius_tolerance_m: float = Field(100.0, ge=0, le=500)
    time_step_hours: float = Field(1.0, gt=0, le=6)
    window_half_width_hours: float = Field(3.0, gt=0, le=12)
    max_acceptable_distance_m: float = Field(5000.0, ge=100, le=50000)
    ascent_rate: float = Field(5.0, ge=0, le=20)
    max_altitude: float = Field(8000.0, ge=1000, le=35000)
    duration_hours: float = Field(4.0, gt=0, le=48)
    step_minutes: float = Field(2.0, ge=0.5, le=30)
    start_altitude: float = Field(0.0, ge=0)
    points_per_circle: int = Field(7, ge=3, le=25)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def grid_radius_for_duration(duration_hours: float) -> float:
    if duration_hours <= 12:
        return 250
    if duration_hours <= 24:
        return 400
    if duration_hours <= 48:
        return 600
    if duration_hours <= 72:
        return 800
    return 1200


def serialize_candidate(c: LaunchCandidate) -> dict:
    return {
        "launch_time": c.launch_time.isoformat(),
        "launch_point": {
            "lat": c.launch_point.lat,
            "lon": c.launch_point.lon,
        },
        "min_distance_to_target_m": round(c.min_distance_to_target_m, 1),
        "closest_point": {
            "time": c.closest_point.time.isoformat(),
            "lat": c.closest_point.lat,
            "lon": c.closest_point.lon,
            "altitude": round(c.closest_point.altitude, 1),
            "wind_speed": round(c.closest_point.wind_speed, 2),
            "wind_direction": round(c.closest_point.wind_direction, 1),
        },
        "trajectory": {
            "distance_km": round(c.trajectory.distance_km, 2),
            "average_wind_speed": round(c.trajectory.average_wind_speed, 2),
            "max_wind_speed": round(c.trajectory.max_wind_speed, 2),
            "prevailing_direction": round(c.trajectory.prevailing_direction, 1),
            "points": [
                {
                    "time": p.time.isoformat(),
                    "lat": p.lat,
                    "lon": p.lon,
                    "altitude": round(p.altitude, 1),
                    "wind_speed": round(p.wind_speed, 2),
                    "wind_direction": round(p.wind_direction, 1),
                }
                for p in c.trajectory.points
            ],
        },
    }


def serialize_window(w: FavorableWindow) -> dict:
    return {
        "date": w.date,
        "window_start": w.window_start.isoformat(),
        "window_end": w.window_end.isoformat(),
        "recommended_time": w.recommended_time.isoformat(),
        "best_candidates": [serialize_candidate(c) for c in w.best_candidates],
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "wind-trajectory",
        "version": "3.2.0",
    }


@app.get("/api/wind")
async def get_wind(
    lat: float,
    lon: float,
    altitude: float = 1000,
):
    try:
        now = datetime.now(timezone.utc)

        latitudes, longitudes = build_grid(lat, lon, 150)

        forecast = await fetch_grid(
            latitudes=latitudes,
            longitudes=longitudes,
            start=now,
            end=now,
        )

        speed, direction = interpolate_wind(
            forecast=forecast,
            lat=lat,
            lon=lon,
            altitude=altitude,
            when=now,
        )

        return {
            "lat": lat,
            "lon": lon,
            "altitude": altitude,
            "wind_speed": speed,
            "wind_direction": direction,
            "time": now.isoformat(),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/trajectory")
async def create_trajectory(request: TrajectoryRequest):
    try:
        start_time = ensure_utc(request.start_time)
        end_time = start_time + timedelta(hours=request.duration_hours)
        radius = grid_radius_for_duration(request.duration_hours)

        latitudes, longitudes = build_grid(
            request.start.lat,
            request.start.lon,
            radius,
        )

        forecast = await fetch_grid(
            latitudes=latitudes,
            longitudes=longitudes,
            start=start_time,
            end=end_time,
        )

        parameters = FlightParameters(
            start=StartPoint(
                lat=request.start.lat,
                lon=request.start.lon,
            ),
            start_time=start_time,
            start_altitude=request.start_altitude,
            ascent_rate=request.ascent_rate,
            max_altitude=request.max_altitude,
            duration_hours=request.duration_hours,
            step_minutes=request.step_minutes,
        )

        result = calculate_trajectory(
            params=parameters,
            forecast=forecast,
        )

        return result

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/backtrajectory")
async def create_backtrajectory(request: BackTrajectoryRequest):
    try:
        detection_time = ensure_utc(request.detection_time)

        detection = Detection(
            lat=request.detection.lat,
            lon=request.detection.lon,
            altitude_m=request.altitude,
            time=detection_time,
        )

        duration_hours = 4.0
        step_seconds = 60.0
        ascent_rate_mps = 5.0
        ascent_rate_sigma_mps = 0.7
        members = 250
        wind_sigma_mps = 1.5
        detection_time_sigma_s = 60.0
        altitude_sigma_m = 50.0

        workdir = BASE_DIR / "era5_cache"

        weather = ERA5Provider(workdir=workdir)
        weather.download(
            detection=detection,
            max_hours=duration_hours,
            max_ascent_rate_mps=15.0,
        )

        balloon = BalloonModel(
            ascent_rate_mps=ascent_rate_mps,
            ascent_rate_sigma_mps=ascent_rate_sigma_mps,
        )

        solver = BackTrajectorySolver(
            weather=weather,
            balloon=balloon,
            step_seconds=step_seconds,
            max_duration_hours=duration_hours,
        )

        estimator = EnsembleEstimator(
            solver=solver,
            members=members,
            wind_sigma_mps=wind_sigma_mps,
            detection_time_sigma_s=detection_time_sigma_s,
            altitude_sigma_m=altitude_sigma_m,
            seed=42,
        )

        result = estimator.run(detection)

        representative = []
        if result.trajectories:
            representative = result.trajectories[0]

        result_data = {
            "detection": result.detection,
            "launch_estimate": result.launch_estimate,
            "zones": result.zones,
            "ensemble_size": result.ensemble_size,
            "valid_members": result.valid_members,
            "trajectories": result.trajectories,
            "trajectory": representative,
            "points": representative,
        }

        return {
            "status": "ok",
            "result": result_data,
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/favorable")
async def create_favorable(request: FavorableRequest):
    try:
        search_start = ensure_utc(request.search_start)
        search_end = ensure_utc(request.search_end)

        if search_end <= search_start:
            raise HTTPException(
                status_code=400,
                detail="search_end must be after search_start",
            )

        # Радиус сетки с запасом под возможный дрейф
        max_duration = request.duration_hours
        radius = grid_radius_for_duration(max_duration) + 100

        # Берём центр между launch_center и target для покрытия обеих зон
        mid_lat = (request.launch_center.lat + request.target.lat) / 2.0
        mid_lon = (request.launch_center.lon + request.target.lon) / 2.0

        latitudes, longitudes = build_grid(mid_lat, mid_lon, radius)

        forecast = await fetch_grid(
            latitudes=latitudes,
            longitudes=longitudes,
            start=search_start,
            end=search_end + timedelta(hours=request.duration_hours),
        )

        target = GeoPoint(
            lat=request.target.lat,
            lon=request.target.lon,
        )
        launch_center = GeoPoint(
            lat=request.launch_center.lat,
            lon=request.launch_center.lon,
        )

        windows = find_favorable_conditions(
            target=target,
            launch_center=launch_center,
            forecast=forecast,
            search_start=search_start,
            search_end=search_end,
            launch_radius_m=request.launch_radius_m,
            radius_tolerance_m=request.radius_tolerance_m,
            time_step_hours=request.time_step_hours,
            window_half_width_hours=request.window_half_width_hours,
            max_acceptable_distance_m=request.max_acceptable_distance_m,
            ascent_rate=request.ascent_rate,
            max_altitude=request.max_altitude,
            duration_hours=request.duration_hours,
            step_minutes=request.step_minutes,
            start_altitude=request.start_altitude,
            points_per_circle=request.points_per_circle,
            interpolate_wind=interpolate_wind,
        )

        return {
            "status": "ok",
            "count": len(windows),
            "windows": [serialize_window(w) for w in windows],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/config")
async def config():
    return {
        "backtrajectory": {
            "duration_hours": 4.0,
            "step_seconds": 60.0,
            "members": 250,
        },
        "favorable": {
            "default_launch_radius_m": 1000.0,
            "default_window_half_width_hours": 3.0,
            "default_time_step_hours": 1.0,
            "default_max_acceptable_distance_m": 5000.0,
        },
    }