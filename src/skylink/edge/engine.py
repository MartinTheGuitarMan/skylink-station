"""Prequential evaluation engine for one run: aggregation, scoring, model stepping, writing."""
from __future__ import annotations

import bisect
import math
import threading
import time
from collections import deque

import httpx
import numpy as np

from ..influx import Influx, esc_tag
from ..sim.streams import SPECS
from .models import Features, FeatHist, History, build


class StreamState:
    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.spec = SPECS[name]
        self.horizons: list[int] = cfg["streams"][name]["horizons"]
        self.hist = History(int(cfg["day_s"]) + max(self.horizons) + 10)
        params = cfg.get("model", {})
        self.models = [build(m, self.horizons, cfg, params.get(m, {})) for m in cfg["models"]]
        self.feat, self.fh = Features(), FeatHist(max(self.horizons) + 2)
        self.crashes: dict[str, int] = {}
        self.cost: dict[str, list] = {}  # model -> [seconds spent in step(), calls]
        # bounded: with out-of-order input (late policy 'process') stale targets are never popped
        self.pending = {(m.name, h): deque(maxlen=2 * h + 64) for m in self.models for h in self.horizons}
        self.cur: list | None = None  # [second, sum, sumsq, count]
        self.last_s = -1
        self.steps = 0
        self.late_dropped = 0
        self.cfg = cfg


class Engine:
    def __init__(self, cfg: dict, influx: Influx | None):
        self.cfg = cfg
        self.influx = influx
        self.run = "unset"
        self.epoch_us = 0
        self.streams: dict[str, StreamState] = {}
        self.lock = threading.RLock()
        self.buf: list[str] = []
        self.last_flush = time.monotonic()
        self.step_ms: deque[float] = deque(maxlen=5000)
        self.max_event_us = 0
        self.base = {"n": 0, "late": 0, "max_lag_us": 0, "max_t": 0}
        self.hook = None  # optional callback(stream, model, h, s, y, yhat, y_persistence) for offline benches
        self.nonfinite = 0
        self.late_policy = cfg.get("late_policy", "drop")  # drop | process (naive arrival order)
        self.rt = True            # False while the caller feeds replayed (backfill) data: forecasts are hindcasts
        self.link: list[tuple[int, int]] = []  # (event second, up) labels, for phase tags only
        self.post_s = 600         # seconds after link-up counted as the "post" phase

    def set_link(self, up: int, t_s: int) -> None:
        with self.lock:
            i = bisect.bisect_left(self.link, (t_s, up))
            self.link.insert(i, (t_s, up))

    def phase(self, s: int) -> str:
        """outage / post (first 10 min after link-up) / normal, by event second. A label, never a model input."""
        i = bisect.bisect_right(self.link, (s, 2)) - 1
        if i < 0:
            return "normal"
        t, up = self.link[i]
        if not up:
            return "outage"
        return "post" if s - t < self.post_s else "normal"

    def configure(self, run: str, epoch_us: int) -> None:
        with self.lock:
            self.run, self.epoch_us = run, epoch_us
            self.streams = {n: StreamState(n, self.cfg) for n in self.cfg["streams"]}
            self.buf.clear()
            self.base = {"n": 0, "late": 0, "max_lag_us": 0, "max_t": 0}
            self.max_event_us = 0
            self.step_ms.clear()
            self.link = []

    # ---- ingest ----------------------------------------------------------------------
    def ingest(self, stream: str, t_us: list[int], values: list[float]) -> None:
        if stream not in self.streams or not t_us:
            return
        with self.lock:
            st = self.streams[stream]
            t = np.asarray(t_us, dtype=np.int64)
            v = np.asarray(values, dtype=float)
            sec = (t - self.epoch_us) // 1_000_000
            uniq, idx = np.unique(sec, return_index=True)
            sums = np.add.reduceat(v, idx)
            sq = np.add.reduceat(v * v, idx)
            cnt = np.diff(np.append(idx, len(sec)))
            for s, su, q, c in zip(uniq.tolist(), sums.tolist(), sq.tolist(), cnt.tolist()):
                if st.cur is not None and s == st.cur[0]:
                    st.cur[1] += su; st.cur[2] += q; st.cur[3] += c
                    continue
                if st.cur is not None:
                    self._close(st)
                if s <= st.last_s and self.late_policy == "drop":
                    st.late_dropped += c
                    st.cur = None
                    continue
                st.cur = [s, su, q, c]
            self.max_event_us = max(self.max_event_us, int(t[-1]))
            self._maybe_flush()

    def ingest_base(self, t_us: list[int]) -> None:
        """Base arm stub (iteration 0): only measure what crossed Skylink and how late it was."""
        with self.lock:
            b = self.base
            prev = b["max_t"]
            b["n"] += len(t_us)
            if prev - max(t_us) > 2_000_000:  # newest point is older than what already arrived: late
                b["late"] += len(t_us)
                b["max_lag_us"] = max(b["max_lag_us"], prev - min(t_us))
            b["max_t"] = max(prev, max(t_us))

    def _close(self, st: StreamState) -> None:
        s, su, q, c = st.cur
        y = (q / c) ** 0.5 if st.spec.agg == "rms" else su / c
        t0 = time.perf_counter()
        self._on_step(st, s, y)
        self.step_ms.append((time.perf_counter() - t0) * 1000)
        st.last_s = s
        st.steps += 1

    def _on_step(self, st: StreamState, s: int, y: float) -> None:
        arm, run = self.cfg["arm"], esc_tag(self.run)
        st.hist.put(s, y)
        for m in st.models:
            for h in st.horizons:
                q = st.pending[(m.name, h)]
                while q and q[0][0] < s:
                    q.popleft()
                if q and q[0][0] == s:
                    _, yhat, rt = q.popleft()
                    if not math.isfinite(yhat):  # a diverged model must not poison the store: score it as persistence
                        self.nonfinite += 1
                        yhat = st.hist.get(s - h) if st.hist.get(s - h) is not None else y
                    ts = self.epoch_us + s * 1_000_000
                    tags = (f"run={run},arm={arm},stream={st.name},model={m.name},rt={int(rt)},"
                            f"phase={self.phase(s)},horizon={h}")
                    if self.hook:
                        self.hook(st.name, m.name, h, s, y, yhat, st.hist.get(s - h))
                    self.buf.append(f"forecast,{tags} yhat={yhat} {ts}")
                    yp = st.hist.get(s - h)  # what persistence said for this very step: pairs the scores
                    pers = f",pers_abs_err={abs(yp - y)}" if yp is not None else ""
                    self.buf.append(f"error,{tags} err={yhat - y},abs_err={abs(yhat - y)}{pers},y={y} {ts}")
                    if hasattr(m, "on_score"):
                        try:
                            m.on_score(s, h, abs(yhat - y))
                        except Exception:
                            st.crashes[m.name] = st.crashes.get(m.name, 0) + 1
        x = st.feat.update(s, y, st.hist)
        for m in st.models:  # train/forecast after scoring
            t0 = time.perf_counter()
            try:
                fc = m.step(s, y, st.hist, x, st.fh)
            except Exception as e:  # a library bug on odd data (stuck sensor, zero variance) must not stop the station
                fc = {}
                st.crashes[m.name] = st.crashes.get(m.name, 0) + 1
                if hasattr(m, "recover"):
                    m.recover()
                self.buf.append(f"drift,run={run},arm={arm},stream={st.name},model={m.name},horizon=0,kind=crash "
                                f"n=1i {self.epoch_us + s * 1_000_000}")
                if st.crashes[m.name] <= 3:
                    print(f"model {m.name} on {st.name} crashed at s={s}: {type(e).__name__}: {e}", flush=True)
            c = st.cost.setdefault(m.name, [0.0, 0])
            c[0] += time.perf_counter() - t0
            c[1] += 1
            for h, yhat in fc.items():
                st.pending[(m.name, h)].append((s + h, yhat, self.rt))
            for ds, dh, kind in getattr(m, "events", ()):
                self.buf.append(f"drift,run={run},arm={arm},stream={st.name},model={m.name},horizon={dh},kind={kind} "
                                f"n=1i {self.epoch_us + ds * 1_000_000}")
            if hasattr(m, "events"):
                m.events.clear()
        st.fh.put(s, x)

    # ---- output ----------------------------------------------------------------------
    def _maybe_flush(self, force: bool = False) -> None:
        if not self.influx:
            return
        if force or len(self.buf) >= 4000 or time.monotonic() - self.last_flush > 1.0:
            lines, self.buf = self.buf, []
            self.last_flush = time.monotonic()
            try:
                for i in range(0, len(lines), 5000):
                    self.influx.write("forecasts", lines[i : i + 5000])
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:  # malformed lines never become valid: drop, do not retry forever
                    print("influx rejected a batch (400), dropped", len(lines), "lines; first:", lines[0], flush=True)
                    return
                self.buf = lines + self.buf
                self.buf = self.buf[-200_000:]
                print("influx write failed:", e, flush=True)
            except Exception as e:  # keep the data, retry next flush; never crash ingest
                self.buf = lines + self.buf
                self.buf = self.buf[-200_000:]
                print("influx write failed:", e, flush=True)

    def flush(self) -> None:
        with self.lock:
            for st in self.streams.values():
                if st.cur is not None:
                    self._close(st)
                    st.cur = None
            self._maybe_flush(force=True)

    def stats(self) -> dict:
        with self.lock:
            ms = np.array(self.step_ms) if self.step_ms else np.zeros(1)
            return {
                "run": self.run, "arm": self.cfg["arm"], "buffered_lines": len(self.buf),
                "steps": {n: s.steps for n, s in self.streams.items()},
                "nonfinite_forecasts": self.nonfinite,
                "model_crashes": {f"{n}/{m}": c for n, st in self.streams.items() for m, c in st.crashes.items()}, "late_dropped": {n: s.late_dropped for n, s in self.streams.items()},
                "step_ms_p50": float(np.percentile(ms, 50)), "step_ms_p99": float(np.percentile(ms, 99)),
                "base": dict(self.base),
                "cost_us_per_step": {f"{n}/{m}": c[0] / c[1] * 1e6 for n, st in self.streams.items()
                                     for m, c in st.cost.items() if c[1]},
            }
