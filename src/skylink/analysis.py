"""Scoring from InfluxDB: MAE, skill vs persistence with a block bootstrap (1 h blocks).

    uv run python -m skylink.analysis --run dev-1 [--warmup-days 2] [--json out.json]

Skill = 1 - sum(abs_err) / sum(pers_abs_err), over the same steps (the engine writes the paired
persistence error on every error line). The bootstrap resamples whole hours."""
from __future__ import annotations

import argparse
import csv
import io
import json
from collections import defaultdict

import numpy as np

from .influx import Influx
from .sim.replay import epoch_us, load_cfg


def _rows(txt: str):
    for block in txt.strip().split("\n\n"):
        rows = [r for r in csv.reader(io.StringIO(block)) if r]
        if len(rows) < 2:
            continue
        hdr = rows[0]
        for r in rows[1:]:
            yield dict(zip(hdr, r))


def hourly(influx: Influx, run: str, start: str, stop: str) -> dict:
    """{(stream, arm, model, horizon): {hour: [n, sum_err, sum_pers]}} within [start, stop)."""
    base = f'''from(bucket: "forecasts") |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r._measurement == "error" and r.run == "{run}")'''
    out: dict = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))
    for fld, fn, col in (("abs_err", "count", 0), ("abs_err", "sum", 1), ("pers_abs_err", "sum", 2)):
        q = base + f'''
  |> filter(fn: (r) => r._field == "{fld}")
  |> group(columns: ["stream", "arm", "model", "horizon"])
  |> aggregateWindow(every: 1h, fn: {fn}, createEmpty: false)
  |> keep(columns: ["_time", "_value", "stream", "arm", "model", "horizon"])'''
        for r in _rows(influx.query(q)):
            if col == 2 and False:
                continue
            out[(r["stream"], r["arm"], r["model"], int(r["horizon"]))][r["_time"]][col] = float(r["_value"])
    return out


def summarise(hours: dict, n_boot: int = 2000, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    res = []
    for key, per in sorted(hours.items()):
        a = np.array(list(per.values()))
        n, e, p = a[:, 0], a[:, 1], a[:, 2]
        if n.sum() == 0 or p.sum() == 0:
            continue
        skill = 1 - e.sum() / p.sum()
        idx = rng.integers(0, len(a), (n_boot, len(a)))
        boots = 1 - e[idx].sum(1) / np.maximum(p[idx].sum(1), 1e-12)
        res.append({"stream": key[0], "arm": key[1], "model": key[2], "horizon": key[3], "n": int(n.sum()),
                    "mae": float(e.sum() / n.sum()), "mae_persistence": float(p.sum() / n.sum()),
                    "skill": float(skill), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                    "hours": len(a)})
    return res


def table(rows: list[dict]) -> str:
    lines = ["| stream | model | h (s) | n | MAE | MAE persist | skill | 95% CI |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['stream']} | {r['model']} | {r['horizon']} | {r['n']} | {r['mae']:.4g} | "
                     f"{r['mae_persistence']:.4g} | {r['skill']:+.3f} | [{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}] |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--config", default="config/scenario-default.toml")
    ap.add_argument("--warmup-days", type=float, default=2.0)
    ap.add_argument("--days", type=float, help="score up to this many days (default: all data)")
    ap.add_argument("--json")
    a = ap.parse_args()
    cfg = load_cfg(a.config)
    e0 = epoch_us(cfg) // 1_000_000
    start = e0 + int(a.warmup_days * 86400)
    stop = e0 + int((a.days or 400) * 86400)
    rows = summarise(hourly(Influx(), a.run, str(start), str(stop)))
    print(table(rows))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
