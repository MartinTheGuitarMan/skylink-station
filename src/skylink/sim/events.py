"""Seeded event plan: sensor faults and process events with logged ground truth.

The whole plan for a run is drawn up front from the seed, so truth is known before data
flows and replays are exact. Times are seconds of event time since the start of the run.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

import numpy as np

# Sensor faults: change what the sensor reports, not the world.
FAULT_KINDS = ("stuck", "spike", "drift", "step", "dropout")
# Process events: change the world (the model should follow them).
PROCESS_KINDS = ("seasonal", "front", "gust", "burst", "cloud")
# Slow degradation (C9): the machine wears; to be flagged, not followed. Off unless a scenario asks.
DEGRADATION_KINDS = ("wear",)
DAY_S = 86400.0


@dataclass(frozen=True)
class Event:
    id: int
    stream: str
    kind: str
    t0: float
    t1: float
    mag: float = 0.0
    aux: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# Faults per day and magnitude scale (the unit of mag for each stream).
FAULT_RATES = {"stuck": 0.8, "spike": 4.0, "drift": 0.5, "step": 0.5, "dropout": 1.5}
SEASONAL_RATE = 0.25  # per day, temp and solar only
FAULT_SCALE = {"temp": 2.0, "pressure": 3.0, "wind": 3.0, "vibration": 3.0, "solar": 80.0}
SEASONAL_STREAMS = ("temp", "solar")


def _poisson_times(rng: np.random.Generator, rate_per_day: float, duration_s: float) -> np.ndarray:
    n = rng.poisson(rate_per_day * duration_s / DAY_S)
    return np.sort(rng.uniform(0.0, duration_s, n))


def _fault_events(rng, stream, duration_s, rate_scale, start_id):
    out: list[Event] = []
    eid = start_id
    scale = FAULT_SCALE[stream]
    for kind in FAULT_KINDS:
        for t0 in _poisson_times(rng, FAULT_RATES[kind] * rate_scale, duration_s):
            if kind == "stuck":
                t1 = t0 + rng.uniform(60, 1200)
                mag = 0.0
            elif kind == "spike":
                t1 = t0 + rng.integers(1, 4) * 0.1  # 1-3 raw samples at ~10 Hz
                mag = float(rng.choice([-1, 1]) * rng.uniform(5, 15) * scale)
            elif kind == "drift":
                t1 = t0 + rng.uniform(2, 6) * 3600
                mag = float(rng.choice([-1, 1]) * rng.uniform(1, 3) * scale)
            elif kind == "step":
                t1 = t0 + rng.uniform(6, 48) * 3600
                mag = float(rng.choice([-1, 1]) * rng.uniform(1, 2.5) * scale)
            else:  # dropout
                t1 = t0 + rng.uniform(10, 300)
                mag = 0.0
            out.append(Event(eid, stream, kind, float(t0), float(min(t1, duration_s)), mag))
            eid += 1
    return out, eid


def _process_events(rng, stream, duration_s, start_id):
    out: list[Event] = []
    eid = start_id
    if stream in SEASONAL_STREAMS:
        for t0 in _poisson_times(rng, SEASONAL_RATE, duration_s):
            # mag: amplitude multiplier delta (relative), aux: phase shift in seconds
            out.append(Event(eid, stream, "seasonal", float(t0), float(duration_s),
                             float(rng.uniform(-0.35, 0.5)), float(rng.uniform(-3, 3) * 3600)))
            eid += 1
    if stream == "pressure":
        t = rng.exponential(2.0 * DAY_S)
        while t < duration_s:
            half = rng.uniform(1.5, 4.0) * 3600  # half-width of the transition
            out.append(Event(eid, stream, "front", float(max(t - 2 * half, 0)), float(t + 2 * half),
                             float(rng.normal(0, 6.0)), float(half)))
            eid += 1
            t += rng.exponential(2.0 * DAY_S)
    if stream == "wind":
        t = rng.exponential(600.0)
        while t < duration_s:
            dur = rng.uniform(3, 15)
            out.append(Event(eid, stream, "gust", float(t), float(t + dur), float(rng.uniform(1.5, 2.6))))
            eid += 1
            t += rng.exponential(600.0)
    if stream == "vibration":
        t = rng.exponential(180.0)
        while t < duration_s:
            tau = rng.uniform(2, 8)
            out.append(Event(eid, stream, "burst", float(t), float(t + 5 * tau),
                             float(np.exp(rng.normal(1.5, 0.8))), float(tau)))
            eid += 1
            t += rng.exponential(180.0)
    if stream == "solar":
        t, level = 0.0, 1.0
        while t < duration_s:
            t += rng.exponential(8 * 60.0)
            new = float(rng.choice([1.0, rng.uniform(0.3, 0.8), rng.uniform(0.05, 0.3)], p=[0.4, 0.35, 0.25]))
            if t < duration_s:
                out.append(Event(eid, stream, "cloud", float(t), float(t + 4.0), new, level))
                eid += 1
            level = new
    return out, eid


def _wear_events(seed, stream, duration_s, wear, start_id):
    """One wear ramp: mag = final background factor F, aux = ramp duration D (s); held at F after t1 = t0 + D.
    Own RNG, so turning wear on changes no other event of the seed."""
    digest = hashlib.sha256(f"{seed}:{stream}:wear".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
    out: list[Event] = []
    eid = start_id
    for _ in range(int(wear.get("count", 1))):
        t0 = rng.uniform(*wear["onset_days"]) * DAY_S
        ramp = rng.uniform(*wear["ramp_days"]) * DAY_S
        factor = rng.uniform(*wear["factor"])
        if t0 < duration_s:
            out.append(Event(eid, stream, "wear", float(t0), float(min(t0 + ramp, duration_s)), float(factor), float(ramp)))
            eid += 1
    return out, eid


def build_plan(seed: int, duration_s: float, streams, rate_scale: float = 1.0, wear: dict | None = None) -> list[Event]:
    """Deterministic plan: the same (seed, duration, streams, rate_scale, wear) always gives the same events."""
    events: list[Event] = []
    eid = 0
    for stream in streams:
        # one RNG per stream, so adding a stream never changes another stream's events
        digest = hashlib.sha256(f"{seed}:{stream}".encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        f, eid = _fault_events(rng, stream, duration_s, rate_scale, eid)
        p, eid = _process_events(rng, stream, duration_s, eid)
        events += f + p
    if wear:  # after all other events, so their ids do not move either
        for stream in streams:
            if stream in wear.get("streams", ["vibration"]):
                w, eid = _wear_events(seed, stream, duration_s, wear, eid)
                events += w
    return sorted(events, key=lambda e: (e.t0, e.id))


class StreamPlan:
    """Events for one stream with cheap overlap queries."""

    def __init__(self, events: list[Event], stream: str):
        self.stream = stream
        self.events = [e for e in events if e.stream == stream]
        self.by_kind: dict[str, list[Event]] = {}
        for e in self.events:
            self.by_kind.setdefault(e.kind, []).append(e)

    def overlapping(self, kind: str, t0: float, t1: float) -> list[Event]:
        return [e for e in self.by_kind.get(kind, ()) if e.t0 < t1 and e.t1 >= t0]

    def kind(self, kind: str) -> list[Event]:
        return self.by_kind.get(kind, [])
