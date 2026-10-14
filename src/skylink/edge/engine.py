"""Prequential evaluation engine for one run: aggregation, scoring, model stepping, writing."""
from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

from ..influx import Influx, esc_tag
from ..sim.streams import SPECS
from .models import REGISTRY, History


class StreamState:
    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.spec = SPECS[name]
        self.horizons: list[int] = cfg["streams"][name]["horizons"]
        self.hist = History(int(cfg["day_s"]) + max(self.horizons) + 10)
        self.models = [REGISTRY[m](self.horizons, cfg) for m in cfg["models"]]
        self.pending = {(m.name, h): deque() for m in self.models for h in self.horizons}
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

    def configure(self, run: str, epoch_us: int) -> None:
        with self.lock:
            self.run, self.epoch_us = run, epoch_us
            self.streams = {n: StreamState(n, self.cfg) for n in self.cfg["streams"]}
            self.buf.clear()
            self.base = {"n": 0, "late": 0, "max_lag_us": 0, "max_t": 0}
            self.max_event_us = 0
            self.step_ms.clear()

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
                if s <= st.last_s:
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
                    _, yhat = q.popleft()
                    ts = self.epoch_us + s * 1_000_000
                    tags = f"run={run},arm={arm},stream={st.name},model={m.name},horizon={h}"
                    self.buf.append(f"forecast,{tags} yhat={yhat} {ts}")
                    self.buf.append(f"error,{tags} err={yhat - y},abs_err={abs(yhat - y)},y={y} {ts}")
        for m in st.models:  # train/forecast after scoring
            for h, yhat in m.step(s, y, st.hist).items():
                st.pending[(m.name, h)].append((s + h, yhat))

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
                "late_dropped": {n: s.late_dropped for n, s in self.streams.items()},
                "step_ms_p50": float(np.percentile(ms, 50)), "step_ms_p99": float(np.percentile(ms, 99)),
                "base": dict(self.base),
            }
