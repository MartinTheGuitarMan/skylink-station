#!/usr/bin/env python3
"""Offline prequential bench: simulator -> engine, no network, no Influx. For tuning on DEV seeds only.

    uv run python scripts/bench.py --seed 1 --days 3 --streams temp --models persistence,lin_lag,hat
"""
import argparse
import time
import tomllib
from collections import defaultdict

import numpy as np

from skylink.analysis import c4_verdict, event_window_table, ew_table, summarise, table, verdict_table
from skylink.edge.engine import Engine
from skylink.sim.replay import load_cfg, make_gens
from skylink.sim.streams import BLOCK_S, SPECS, to_points

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--days", type=float, default=3)
ap.add_argument("--warmup-days", type=float, default=2)
ap.add_argument("--streams", default="temp")
ap.add_argument("--models", default=None)
ap.add_argument("--faults", type=float, default=1.0)
ap.add_argument("--edge", default="config/edge.toml")
ap.add_argument("--event-windows", action="store_true", help="C4: MAE vs the static model in the 60 min after logged regime changes")
ap.add_argument("--static", default="lin_lag_static", help="reference model(s), comma-separated; the first is the pre-registered one")
ap.add_argument("--set", action="append", default=[], help="model.<name>.<key>=<number>")
a = ap.parse_args()
assert a.seed < 100 or a.seed > 105, "locked seeds 101-105 are not for benches"

cfg = tomllib.load(open(a.edge, "rb"))
streams = a.streams.split(",")
cfg["streams"] = {s: cfg["streams"][s] for s in streams}
if a.models:
    cfg["models"] = a.models.split(",")
cfg["model"]["lin_lag_static"]["static_after"] = int(a.warmup_days * 86400)
for kv in a.set:
    k, v = kv.split("=")
    _, mname, key = k.split(".")
    cfg["model"].setdefault(mname, {})[key] = float(v)
sc = load_cfg("config/scenario-default.toml", seed=a.seed, days=a.days)
sc["run"]["streams"], sc["run"]["fault_rate_scale"] = streams, a.faults
gens, plan = make_gens(sc)
eng = Engine(cfg, None)
eng.configure("bench", 0)
hours = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))
warm = a.warmup_days * 86400
n_s = int(a.days * 86400)
ew = defaultdict(lambda: (np.zeros(n_s), np.zeros(n_s)))  # per second: sum and count of abs error


def hook(stream, model, h, s, y, yhat, yp):
    if s < warm or yp is None:
        return
    r = hours[(stream, "bench", model, h)][s // 3600]
    r[0] += 1; r[1] += abs(yhat - y); r[2] += abs(yp - y)
    if a.event_windows and s < n_s:
        e = ew[(stream, model, h)]
        e[0][s] += abs(yhat - y); e[1][s] += 1


eng.hook = hook
t0 = time.time()
for k in range(int(a.days * 86400 // BLOCK_S)):
    for st, g in gens.items():
        blk = g.block(k)
        p = to_points(SPECS[st], blk, 0, len(blk["t"]), 0)
        if p["t"]:
            eng.ingest(st, p["t"], p["v"][0])
    eng.buf.clear()
print(f"wall {time.time() - t0:.0f}s, nonfinite forecasts: {eng.nonfinite}")
print(table(summarise(hours)))
print({k: round(v, 1) for k, v in eng.stats()["cost_us_per_step"].items()})
if a.event_windows:
    evs = [e.to_dict() for e in plan if e.stream in streams]
    rows = event_window_table(dict(ew), evs, a.static.split(","), warm, n_s, 1)
    print("\n" + ew_table(rows) + "\n\n" + verdict_table(c4_verdict(rows)))
