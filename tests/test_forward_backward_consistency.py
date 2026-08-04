from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backtrajectory_consistent import BackTrajectorySolver, BalloonModel, Detection


class ConstantWindProvider:
    """Minimal deterministic provider for a numerical reversibility test."""

    def __init__(self, east_mps: float = 10.0, north_mps: float = 0.0):
        self.east_mps = east_mps
        self.north_mps = north_mps
        self.cells = [
            {"latitude": lat, "longitude": lon}
            for lat in (49.0, 50.0, 51.0)
            for lon in (5.0, 6.0, 7.0)
        ]

    def state(self, lat, lon, altitude_m, time):
        return SimpleNamespace(
            u_mps=self.east_mps,
            v_mps=self.north_mps,
            temperature_k=273.15,
            pressure_pa=101325.0,
            geopotential_m2s2=altitude_m * 9.80665,
            altitude_m=altitude_m,
        )


def test_reverse_returns_to_launch_for_constant_wind():
    provider = ConstantWindProvider()
    launch_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    detection_time = launch_time + timedelta(hours=6)
    detection = Detection(lat=50.0, lon=6.0, altitude_m=10_000.0, time=detection_time)

    solver = BackTrajectorySolver(
        weather=provider,
        balloon=BalloonModel(ascent_rate_mps=5.0),
        step_seconds=300.0,
        max_duration_hours=6.0,
    )
    points = solver.solve(detection, duration_hours=6.0)
    launch = points[-1]

    assert abs(launch["altitude_m"]) < 1e-6
    assert abs((datetime.fromisoformat(launch["time"]) - launch_time).total_seconds()) <= 1.0
    assert abs(launch["lat"] - 50.0) < 2e-5
    assert abs(launch["lon"] - 6.0) < 2e-5
