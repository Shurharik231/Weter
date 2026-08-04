from __future__ import annotations

from backtrajectory import Detection, OpenMeteoProvider
from backtrajectory_consistent import (
    BackTrajectorySolver as _ConsistentBackTrajectorySolver,
    EnsembleEstimator as _ConsistentEnsembleEstimator,
)


class AccurateOpenMeteoProvider(OpenMeteoProvider):
    """Compatibility name for the improved provider.

    Horizontal interpolation is performed by the shared reverse solver, so the
    provider itself can keep the existing Open-Meteo download/cache behavior.
    """


class AccurateBackTrajectorySolver(_ConsistentBackTrajectorySolver):
    """Reversible RK4/geodesic solver with an optional coherent wind bias."""

    def __init__(self, *args, wind_bias_e_mps: float = 0.0, wind_bias_n_mps: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.wind_bias_e_mps = float(wind_bias_e_mps)
        self.wind_bias_n_mps = float(wind_bias_n_mps)

    def _derivative(self, lat, lon, altitude, when, wind_du=(0.0, 0.0)):
        factor = 0.65 + 0.35 * min(max(altitude / 10000.0, 0.0), 1.0)
        return super()._derivative(
            lat, lon, altitude, when,
            (wind_du[0] + self.wind_bias_e_mps * factor,
             wind_du[1] + self.wind_bias_n_mps * factor),
        )


class AccurateEnsembleEstimator(_ConsistentEnsembleEstimator):
    """Compatibility name for the corrected correlated-wind ensemble."""


__all__ = [
    "AccurateOpenMeteoProvider",
    "AccurateBackTrajectorySolver",
    "AccurateEnsembleEstimator",
    "Detection",
]
