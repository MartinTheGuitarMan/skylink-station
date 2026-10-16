"""Base arms: forecasters that only see what crossed Skylink, with three ways to treat late data.

  ignore   live and backfill go straight in; seconds older than the newest processed one are dropped
  arrival  everything is processed in arrival order, even when event time goes backwards (naive)
  sorted   on a backfill notice, hold live data until the replay is complete, then process everything
           in event-time order (the base is blind for longer, but its models see a clean stream)

Forecasts made from replayed data are hindcasts and are tagged rt=0; only rt=1 forecasts count as
real-time. `ctrl: link` messages only label phases for scoring; `ctrl: bf_start` is the link-layer
notice of a replay (chunk count) and is used by `sorted` only."""
from __future__ import annotations

import copy

import numpy as np

from .engine import Engine


class BaseArm:
    def __init__(self, cfg: dict, influx, strategy: str):
        assert strategy in ("ignore", "arrival", "sorted"), strategy
        c = copy.deepcopy(cfg)
        c["arm"] = f"base-{strategy}"
        c["models"] = cfg.get("base", {}).get("models", ["persistence", "lin_lag"])
        c["late_policy"] = "process" if strategy == "arrival" else "drop"
        self.strategy = strategy
        self.engine = Engine(c, influx)
        self.hold: dict | None = None

    def configure(self, run: str, epoch_us: int) -> None:
        self.engine.configure(run, epoch_us)
        self.hold = None

    def on_message(self, b: dict) -> None:
        ctrl = b.get("ctrl")
        if ctrl == "link":
            self.engine.set_link(int(b["up"]), (int(b["t_us"]) - self.engine.epoch_us) // 1_000_000)
            return
        if ctrl == "bf_start":
            if self.strategy == "sorted":
                self.hold = {"id": b["bf_id"], "n": int(b["n"]), "got": 0, "batches": []}
            return
        if self.strategy == "sorted" and self.hold is not None:
            self.hold["batches"].append(b)
            if b.get("bf") and b.get("bf_id") == self.hold["id"]:
                self.hold["got"] += 1
                if self.hold["got"] >= self.hold["n"]:
                    self._replay()
            return
        self.engine.rt = not b.get("bf", False)
        self.engine.ingest(b["stream"], b["t"], b["v"][0])
        self.engine.rt = True

    def _replay(self) -> None:
        by: dict[str, tuple[list, list]] = {}
        for b in self.hold["batches"]:
            t, v = by.setdefault(b["stream"], ([], []))
            t.extend(b["t"])
            v.extend(b["v"][0])
        self.hold = None
        self.engine.rt = False
        for stream, (t, v) in by.items():
            order = np.argsort(np.asarray(t, dtype=np.int64), kind="stable")
            self.engine.ingest(stream, np.asarray(t)[order].tolist(), np.asarray(v)[order].tolist())
        self.engine.rt = True

    def flush(self) -> None:
        self.engine.flush()
