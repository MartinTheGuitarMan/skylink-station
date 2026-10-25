"""Generators for the five streams. Known processes, so every error is attributable.

Each generator is sequential and block-based (fixed 60 s blocks), so output depends only on
(seed, plan, block index) and never on how the replayer batches it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
from scipy.signal import lfilter

from .events import DAY_S, StreamPlan

BLOCK_S = 60


@dataclass(frozen=True)
class StreamSpec:
    name: str
    rate_hz: int
    fields: tuple[str, ...] = ("value",)
    unit: str = ""
    agg: str = "mean"  # how the edge aggregates to 1 s: mean or rms


SPECS: dict[str, StreamSpec] = {
    "temp": StreamSpec("temp", 10, unit="degC"),
    "pressure": StreamSpec("pressure", 10, unit="hPa"),
    "wind": StreamSpec("wind", 20, ("value", "dir"), unit="m/s"),
    "vibration": StreamSpec("vibration", 100, unit="um/s", agg="rms"),
    "solar": StreamSpec("solar", 5, unit="W/m2"),
}


class StreamGen:
    def __init__(self, spec: StreamSpec, seed: int, plan: StreamPlan):
        self.spec = spec
        self.plan = plan
        digest = hashlib.sha256(f"{seed}:{spec.name}:gen".encode()).digest()
        self.rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        self.state: dict[str, float] = {}
        self.zi: dict[str, np.ndarray] = {}
        self.stuck: dict[int, float] = {}
        self.next_block = 0
        self.n = spec.rate_hz * BLOCK_S
        if spec.name == "solar":
            self._build_cloud_knots()

    # ---- helpers ---------------------------------------------------------------------
    def _ar1(self, key: str, tau_s: float, sigma: float) -> np.ndarray:
        phi = float(np.exp(-1.0 / (self.spec.rate_hz * tau_s)))
        if key not in self.state:
            self.state[key] = float(self.rng.normal(0, sigma))
        e = self.rng.normal(0, sigma * np.sqrt(1 - phi * phi), self.n)
        y, _ = lfilter([1.0], [1.0, -phi], e, zi=[phi * self.state[key]])
        self.state[key] = float(y[-1])
        return y

    def _seasonal(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Amplitude multiplier and phase shift (s), each moving smoothly over ~3 h."""
        scale = np.ones_like(t)
        phase = np.zeros_like(t)
        for e in self.plan.kind("seasonal"):
            s = 0.5 * (1 + np.tanh((t - e.t0) / (3 * 3600.0)))
            scale += e.mag * s
            phase += e.aux * s
        return scale, phase

    def _build_cloud_knots(self) -> None:
        tk, vk = [0.0], [1.0]
        for e in self.plan.kind("cloud"):
            tk += [e.t0, e.t1]
            vk += [e.aux, e.mag]
        tk_arr = np.maximum.accumulate(np.array(tk))
        tk_arr += np.arange(len(tk_arr)) * 1e-6  # strictly increasing for interp
        self._cloud_t, self._cloud_v = tk_arr, np.array(vk)

    # ---- processes -------------------------------------------------------------------
    def _temp(self, t):
        scale, phase = self._seasonal(t)
        diurnal = 6.0 * scale * np.cos(2 * np.pi * (t - 15 * 3600 - phase) / DAY_S)
        slow = self._ar1("slow", 3 * DAY_S, 0.8)
        fast = self._ar1("fast", 30.0, 0.15)
        return {"value": -8.0 + diurnal + slow + fast + self.rng.normal(0, 0.05, self.n)}

    def _pressure(self, t):
        x = 1013.0 + self._ar1("slow", 36 * 3600.0, 3.0) + 0.25 * np.sin(2 * np.pi * t / (DAY_S / 2))
        bump = np.zeros_like(t)
        for e in self.plan.kind("front"):
            tc, half = e.t1 - 2 * e.aux, e.aux
            x += e.mag * 0.5 * (1 + np.tanh((t - tc) / half))
            bump += 1.0 / np.cosh((t - tc) / half) ** 2  # volatility rises around a front
        noise = self._ar1("fast", 20.0, 0.03) + self.rng.normal(0, 0.01, self.n)
        return {"value": x + noise * (1 + 4 * np.clip(bump, 0, 1))}

    def _wind(self, t):
        logm = 1.8 + self._ar1("slowlog", 6 * 3600.0, 0.35)
        speed = np.exp(logm + self._ar1("fastlog", 2.0, 0.25))
        for e in self.plan.overlapping("gust", t[0], t[-1] + 1):
            m = (t >= e.t0) & (t < e.t1)
            speed[m] *= 1 + (e.mag - 1) * 0.5 * (1 - np.cos(2 * np.pi * (t[m] - e.t0) / (e.t1 - e.t0)))
        direction = (270.0 + self._ar1("dirslow", 3 * 3600.0, 40.0) + self._ar1("dirfast", 10.0, 10.0)) % 360.0
        return {"value": speed, "dir": direction}

    def _vibration(self, t):
        r, th = 0.97, 2 * np.pi * 2.0 / self.spec.rate_hz
        a = [1.0, -2 * r * np.cos(th), r * r]
        gain = np.sqrt((1 - r * r) * ((1 + r * r) ** 2 - 4 * r * r * np.cos(th) ** 2) / (1 + r * r))
        zi = self.zi.get("ar2", np.zeros(2))
        bg, self.zi["ar2"] = lfilter([gain], a, self.rng.normal(0, 1.0, self.n), zi=zi)
        for e in self.plan.kind("wear"):  # bearing wear: the broadband background grows, held after the ramp
            u = np.clip((t - e.t0) / e.aux, 0.0, 1.0)
            bg = bg * (1 + (e.mag - 1) * u * u)
        x = bg + 0.8 * np.sin(2 * np.pi * 0.2 * t)
        for e in self.plan.overlapping("burst", t[0], t[-1] + 1):
            m = (t >= e.t0) & (t < e.t1)
            dt = t[m] - e.t0
            freq = 8.0 + 7.0 * ((e.id * 2654435761) % 1000) / 1000.0
            x[m] += e.mag * np.exp(-dt / e.aux) * np.sin(2 * np.pi * freq * dt)
        return {"value": x}

    def _solar(self, t):
        scale, phase = self._seasonal(t)
        clear = 700.0 * scale * np.clip(np.cos(2 * np.pi * (t - 12 * 3600 - phase) / DAY_S), 0, None) ** 1.3
        trans = np.interp(t, self._cloud_t, self._cloud_v)
        flick = self._ar1("flick", 3.0, 0.05) * (1 - trans)
        return {"value": clear * np.clip(trans * (1 + flick), 0, None) + self.rng.normal(0, 1.5, self.n)}

    # ---- sensor faults ---------------------------------------------------------------
    def _faults(self, t: np.ndarray, x: np.ndarray) -> np.ndarray:
        valid = np.ones(self.n, dtype=bool)
        lo, hi = t[0], t[-1] + 1.0 / self.spec.rate_hz
        dt = 1.0 / self.spec.rate_hz
        for e in self.plan.overlapping("spike", lo, hi):
            x[(t >= e.t0) & (t < max(e.t1, e.t0 + dt))] += e.mag
        for e in self.plan.overlapping("drift", lo, hi):
            m = (t >= e.t0) & (t < e.t1)
            x[m] += e.mag * (t[m] - e.t0) / (e.t1 - e.t0)
        for e in self.plan.overlapping("step", lo, hi):
            x[(t >= e.t0) & (t < e.t1)] += e.mag
        for e in self.plan.overlapping("stuck", lo, hi):  # a frozen sensor hides every other fault
            m = (t >= e.t0) & (t < e.t1)
            if m.any():
                self.stuck.setdefault(e.id, float(x[m][0]))
                x[m] = self.stuck[e.id]
        for e in self.plan.overlapping("dropout", lo, hi):
            valid[(t >= e.t0) & (t < e.t1)] = False
        return valid

    # ---- public ----------------------------------------------------------------------
    def block(self, k: int) -> dict[str, np.ndarray]:
        assert k == self.next_block, f"blocks must be read in order (want {self.next_block}, got {k})"
        self.next_block += 1
        t = k * BLOCK_S + np.arange(self.n) / self.spec.rate_hz
        out = getattr(self, "_" + self.spec.name)(t)
        valid = self._faults(t, out["value"])
        if self.spec.name in ("wind", "solar"):
            out["value"] = np.clip(out["value"], 0, None)
        out["t"] = t
        out["valid"] = valid
        return out


def to_points(spec: StreamSpec, blk: dict[str, np.ndarray], i0: int, i1: int, epoch_us: int) -> dict:
    """Columnar payload for samples i0:i1 of a block: integer microsecond timestamps, rounded values."""
    m = blk["valid"][i0:i1]
    t_us = epoch_us + np.rint(blk["t"][i0:i1][m] * 1e6).astype(np.int64)
    cols = [np.round(blk[f][i0:i1][m], 4).tolist() for f in spec.fields]
    return {"t": t_us.tolist(), "v": cols}
