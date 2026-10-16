"""Alerts and labelled triage cases, built offline from the simulator (seed -> truth -> labels).

Detector (deliberately plain): a 1 s aggregate that departs from its 60 s EWMA by more than 8 mean
absolute deviations raises a `jump`; 120 identical seconds raise a `flat`; at most one alert per stream
per 300 s. Truth label of an alert = the simulator events overlapping it:
  sensor faults (stuck, spike, drift, step)  -> sensor_fault
  process events (front, gust, burst, cloud) -> real_event
  neither: the detector's own false alarm, dropped from the evaluation (counted)
  both: ambiguous, dropped (counted)
Backfill artefacts come from running the same detector over the arrival-order series that Skylink
produces (outage data replayed late, chunks shuffled inside windows): an alert at an arrival
discontinuity with no counterpart in event time is labelled backfill_artefact."""
from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from ..sim.events import FAULT_KINDS, StreamPlan, build_plan
from ..sim.streams import BLOCK_S, SPECS, StreamGen
from . import linkmodel

LABELS = ["real_event", "sensor_fault", "backfill_artefact"]
FLOOR = {"temp": 0.02, "pressure": 0.01, "wind": 0.2, "vibration": 0.05, "solar": 1.0}
FAULT = {"stuck", "spike", "drift", "step"}
REAL = {"front", "gust", "burst", "cloud"}
LOOK = 120          # seconds of look-ahead the triage may wait for
SUPPRESS = 300
WARM = 900


class Detector:
    def __init__(self, stream: str):
        self.floor = FLOOR[stream]
        self.m = self.d = None
        self.n = 0
        self.last = -10**9
        self.win: deque[float] = deque(maxlen=120)

    def update(self, i: int, y: float):
        """i is the position in the fed sequence (one step per element). Returns (kind, z, scale, m) or None."""
        self.n += 1
        self.win.append(y)
        if self.m is None:
            self.m, self.d = y, self.floor
            return None
        scale = max(self.d, self.floor)
        z = (y - self.m) / scale
        alert = None
        if self.n > WARM and i - self.last >= SUPPRESS:
            if abs(z) > 8:
                alert = ("jump", z, scale, self.m)
            elif len(self.win) == 120 and max(self.win) - min(self.win) < 1e-9 and self.d > 2 * self.floor:
                alert = ("flat", 0.0, scale, self.m)
            if alert:
                self.last = i
        # the baseline must not chase an alert it just raised
        if alert is None or alert[0] == "flat":
            self.m += (y - self.m) / 60.0
            self.d += (abs(y - self.m) - self.d) / 600.0
        return alert


def aggregate_series(seed: int, days: float, streams: list[str], fault_rate_scale: float = 1.0):
    """1 s aggregates per stream plus the event plan. (Simulates the raw rate: slow for vibration.)"""
    dur = days * 86400.0
    plan = build_plan(seed, dur, streams, fault_rate_scale)
    out = {}
    for s in streams:
        spec, gen = SPECS[s], StreamGen(SPECS[s], seed, StreamPlan(plan, s))
        n = int(dur // BLOCK_S) * BLOCK_S
        y = np.full(n, np.nan)
        for k in range(n // BLOCK_S):
            b = gen.block(k)
            v, ok = b["value"].reshape(BLOCK_S, spec.rate_hz), b["valid"].reshape(BLOCK_S, spec.rate_hz)
            cnt = ok.sum(1)
            with np.errstate(invalid="ignore", divide="ignore"):
                if spec.agg == "rms":
                    agg = np.sqrt(((v * v) * ok).sum(1) / cnt)
                else:
                    agg = (v * ok).sum(1) / cnt
            agg[cnt == 0] = np.nan
            y[k * BLOCK_S:(k + 1) * BLOCK_S] = np.round(agg, 4)
        out[s] = y
    return out, plan


def _label(stream_plan: StreamPlan, s: int) -> str | None:
    kinds = {e.kind for e in stream_plan.events if e.t0 - 5 <= s <= e.t1 + 5 and e.kind in FAULT | REAL}
    f, r = bool(kinds & FAULT), bool(kinds & REAL)
    if f and r:
        return "ambiguous"
    return "sensor_fault" if f else "real_event" if r else None


def _context(stream, y, i, order, z, scale, m, extra):
    """Numbers an on-call person could read off a dashboard two minutes after onset."""
    idx = order[i:i + LOOK] if order is not None else np.arange(i, min(i + LOOK, len(y)))
    seg = y[idx]
    seg = seg[~np.isnan(seg)]
    zs = (seg - m) / scale if len(seg) else np.array([0.0])
    flat = float(np.mean(np.abs(np.diff(seg)) < 1e-9)) if len(seg) > 1 else 0.0
    at = lambda k: float((seg[min(k, len(seg) - 1)] - m) / scale) if len(seg) else 0.0
    prev = y[order[i - 10]] if order is not None and i >= 10 else y[i - 10] if i >= 10 else np.nan
    cur = y[order[i]] if order is not None else y[i]
    return {"stream": stream, "unit": SPECS[stream].unit, "onset_z": round(float(z), 1),
            "peak_z_next_2min": round(float(zs[np.argmax(np.abs(zs))]), 1),
            "z_after_1min": round(at(60), 1), "z_after_2min": round(at(119), 1),
            "seconds_beyond_threshold_in_2min": int((np.abs(zs) > 8).sum()),
            "flat_fraction_next_2min": round(flat, 2),
            "change_vs_10s_before_in_sigma": round(float((cur - prev) / scale), 1) if not np.isnan(prev) else 0.0,
            **extra}


@dataclass
class Case:
    id: str
    stream: str
    second: int
    label: str
    kind: str                  # detector kind: jump | flat
    context: dict = field(default_factory=dict)

    def text(self) -> str:
        c = self.context
        return "\n".join(f"{k}: {v}" for k, v in c.items())


def edge_cases(series: dict, plan, seed: int, seconds: int, mean_up=14400, mean_down=2400) -> tuple[list[Case], dict]:
    trans = linkmodel.schedule(seed, seconds, mean_up, mean_down)
    outs = linkmodel.outages(trans, seconds)
    cases, dropped = [], {"unexplained": 0, "ambiguous": 0}
    alert_times: dict[str, list[int]] = {}
    per: dict[str, list] = {}
    for st, y in series.items():
        det, sp = Detector(st), StreamPlan(plan, st)
        for i in range(len(y)):
            if np.isnan(y[i]):
                continue
            a = det.update(i, float(y[i]))
            if not a:
                continue
            per.setdefault(st, []).append((i, a, sp))
            alert_times.setdefault(st, []).append(i)
    for st, items in per.items():
        y = series[st]
        for i, (kind, z, scale, m), sp in items:
            lab = _label(sp, i)
            if lab is None or lab == "ambiguous":
                dropped["unexplained" if lab is None else "ambiguous"] += 1
                continue
            others = sum(1 for o, ts in alert_times.items() if o != st and any(abs(t - i) <= 60 for t in ts))
            in_out = any(d <= i < u for d, u in outs)
            ctx = _context(st, y, i, None, z, scale, m,
                           {"other_streams_alerting_within_1min": others,
                            "data_arrived_via_backfill_replay": "yes" if in_out else "no",
                            "backfill_replay_in_progress": "yes" if in_out else "no"})
            cases.append(Case(f"s{seed}-{st}-{i}", st, i, lab, kind, ctx))
    return cases, {"dropped": dropped, "alert_times": alert_times, "outages": outs}


def arrival_order(n: int, outs: list[tuple[int, int]], chunk_s: int, window: int = 8, seed: int = 0):
    """Arrival order of seconds 0..n-1 with Skylink's behaviour: outage data is replayed after link-up in
    chunks shuffled inside windows of `window` chunks, one chunk per 3 live seconds (rate limit at 60x).
    Returns (order, via_backfill flags, arrival second, replay start of the outage that produced each)."""
    rng = np.random.default_rng(seed)
    down = np.zeros(n, dtype=bool)
    for d, u in outs:
        down[d:min(u, n)] = True
    order, bf, arr, link_up = [], [], [], []
    pending: deque = deque()   # (second list, link-up second)
    live_since_chunk = 0
    for s in range(n):
        if not down[s]:
            order.append(s); bf.append(False); arr.append(s); link_up.append(-1)
            live_since_chunk += 1
            if pending and live_since_chunk >= 3:
                live_since_chunk = 0
                secs, up = pending.popleft()
                for q in secs:
                    order.append(q); bf.append(True); arr.append(s); link_up.append(up)
        for d, u in outs:
            if u == s + 1 and u - d > 0 and u <= n:      # link came back: queue the replay
                secs = list(range(d, u))
                chunks = [secs[k:k + chunk_s] for k in range(0, len(secs), chunk_s)]
                out = []
                for k in range(0, len(chunks), window):
                    w = chunks[k:k + window]
                    rng.shuffle(w)
                    out += w
                pending.extend((c, u) for c in out)
    while pending:
        secs, up = pending.popleft()
        for q in secs:
            order.append(q); bf.append(True); arr.append(n); link_up.append(up)
    return np.array(order), np.array(bf), np.array(arr), np.array(link_up)


def artefact_cases(series: dict, plan, seed: int, edge_info: dict, chunk_points: int = 5000) -> list[Case]:
    cases = []
    outs = edge_info["outages"]
    for st, y in series.items():
        n = len(y)
        order, bf, arr, link_up = arrival_order(n, outs, max(1, chunk_points // SPECS[st].rate_hz), seed=seed)
        det, sp = Detector(st), StreamPlan(plan, st)
        yy = y[order]
        for i in range(len(order)):
            if np.isnan(yy[i]):
                continue
            a = det.update(i, float(yy[i]))
            if not a or i == 0:
                continue
            s = int(order[i])
            jumped = abs(int(order[i]) - int(order[i - 1])) > 5
            near_edge = any(abs(t - s) <= 60 for t in edge_info["alert_times"].get(st, []))
            if not jumped or near_edge or _label(sp, s) is not None:
                continue
            kind, z, scale, m = a
            mins = (arr[i] - link_up[i]) / 60.0 if link_up[i] >= 0 else 0.0
            ctx = _context(st, y, i, order, z, scale, m,
                           {"other_streams_alerting_within_1min": 0,
                            "data_arrived_via_backfill_replay": "yes" if bf[i] else "no",
                            "backfill_replay_in_progress": "yes",
                            "minutes_since_link_up": round(float(mins), 1),
                            "previous_sample_came_from_event_time_gap_s": int(abs(int(order[i]) - int(order[i - 1])))})
            cases.append(Case(f"s{seed}-{st}-art{i}", st, s, "backfill_artefact", kind, ctx))
    return cases


def rules_baseline(case: Case) -> str:
    """The comparison for C5a: inside a backfill replay -> artefact; flat line -> fault; else real event."""
    c = case.context
    if c.get("backfill_replay_in_progress") == "yes" or c.get("data_arrived_via_backfill_replay") == "yes":
        return "backfill_artefact"
    if case.kind == "flat" or c.get("flat_fraction_next_2min", 0) > 0.9:
        return "sensor_fault"
    return "real_event"


def balanced(cases: list[Case], per_class: int, seed: int = 0) -> list[Case]:
    rng = np.random.default_rng(seed)
    out = []
    for lab in LABELS:
        pool = [c for c in cases if c.label == lab]
        pick = rng.permutation(len(pool))[:per_class]
        out += [pool[i] for i in sorted(pick)]
    return out
