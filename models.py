from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class StartPoint:

    lat: float
    lon: float


@dataclass
class FlightParameters:

    start: StartPoint

    start_time: datetime

    start_altitude: float

    ascent_rate: float

    max_altitude: float

    duration_hours: float

    step_minutes: int = 10


@dataclass
class WindPoint:

    time: datetime

    lat: float

    lon: float

    altitude: float

    speed: float

    direction: float


@dataclass
class TrajectoryPoint:

    time: datetime

    lat: float

    lon: float

    altitude: float

    wind_speed: float

    wind_direction: float


@dataclass
class Trajectory:

    start: TrajectoryPoint

    end: TrajectoryPoint

    distance_km: float

    average_wind_speed: float

    max_wind_speed: float

    prevailing_direction: float

    points: list[TrajectoryPoint]

    def to_dict(self) -> dict[str, Any]:

        return {
            "start": {
                "time": self.start.time.isoformat(),
                "lat": self.start.lat,
                "lon": self.start.lon,
                "altitude": self.start.altitude,
                "wind_speed": self.start.wind_speed,
                "wind_direction": (
                    self.start.wind_direction
                ),
            },

            "end": {
                "time": self.end.time.isoformat(),
                "lat": self.end.lat,
                "lon": self.end.lon,
                "altitude": self.end.altitude,
                "wind_speed": self.end.wind_speed,
                "wind_direction": (
                    self.end.wind_direction
                ),
            },

            "distance_km": self.distance_km,

            "average_wind_speed": (
                self.average_wind_speed
            ),

            "max_wind_speed": (
                self.max_wind_speed
            ),

            "prevailing_direction": (
                self.prevailing_direction
            ),

            "trajectory": [
                {
                    "time": point.time.isoformat(),
                    "lat": point.lat,
                    "lon": point.lon,
                    "altitude": point.altitude,
                    "wind_speed": (
                        point.wind_speed
                    ),
                    "wind_direction": (
                        point.wind_direction
                    ),
                }

                for point in self.points
            ],
        }