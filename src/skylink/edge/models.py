"""Forecasters. One interface: after the true value for second s is known (and was already
scored), `step` returns forecasts {horizon: yhat for second s+horizon}. Test-then-train is
enforced by the engine: scoring for target s always happens before `step(s, ...)`."""
from __future__ import annotations

import numpy as np


class History:
    """Ring of the last `size` one-second aggregates, addressed by absolute second."""

    def __init__(self, size: int):
        self.size = size
        self.vals = np.full(size, np.nan)
        self.stamps = np.full(size, -1, dtype=np.int64)

    def put(self, s: int, y: float) -> None:
        self.vals[s % self.size] = y
        self.stamps[s % self.size] = s

    def get(self, s: int) -> float | None:
        if s < 0:
            return None
        i = s % self.size
        return float(self.vals[i]) if self.stamps[i] == s else None


class Persistence:
    name = "persistence"

    def __init__(self, horizons, cfg):
        self.horizons = horizons

    def step(self, s: int, y: float, hist: History) -> dict[int, float]:
        return {h: y for h in self.horizons}


class SeasonalNaive:
    name = "seasonal_naive"

    def __init__(self, horizons, cfg):
        self.horizons = horizons
        self.period = int(cfg["day_s"])

    def step(self, s: int, y: float, hist: History) -> dict[int, float]:
        out = {}
        for h in self.horizons:
            v = hist.get(s + h - self.period)
            if v is not None:
                out[h] = v
        return out


REGISTRY = {"persistence": Persistence, "seasonal_naive": SeasonalNaive}
