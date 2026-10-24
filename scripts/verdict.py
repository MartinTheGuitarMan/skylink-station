#!/usr/bin/env python3
"""Verdict pipeline (road step 4; rules and open choices in src/skylink/verdict.py).

On the Mini (InfluxDB), one JSON per run into runs/verdict/<label>/:
    uv run python scripts/verdict.py collect --label locked --runs locked-101,locked-102,... [--c2-run locked-1x]
Anywhere (pure), after scripts/mini-sync.sh pull on the Air the files are under runs/mini/verdict/<label>/:
    uv run python scripts/verdict.py decide --label locked [--dir runs/mini/verdict/locked] [--triage runs/agent/<id>/result.json]
        [--bench runs/agent/proposals-<id>/result.json] [--replicate locked-101:locked-101b,...]
Writes <dir>/verdict.json and reports/verdict-<label>.md. Dev labels (dry runs) may use any dev run; a label starting with
"locked" must be given locked runs only, and every locked run it reads is logged in the journal by the pass that runs it."""
import argparse
import datetime as dt
import json
from pathlib import Path

from skylink import analysis as A
from skylink import verdict as V
from skylink.agent import linkmodel
from skylink.influx import Influx

BASE_ARMS = ("base-arrival", "base-sorted", "base-ignore")


def _speed(run: str) -> float:
    for line in Path("config/queue.txt").read_text().splitlines():
        f = line.split()
        if f and f[0] == run:
            return float(f[4])
    return 0.0


def collect_run(ix: Influx, run: str, warmup_days: float) -> dict:
    cfg = json.loads(Path(f"runs/{run}/config.json").read_text())
    summ = json.loads(Path(f"runs/{run}/summary.json").read_text())
    e0 = int(dt.datetime.fromisoformat(cfg["run"]["epoch"].replace("Z", "+00:00")).timestamp())
    days, seed = cfg["run"]["duration_days"], cfg["run"]["seed"]
    stop = e0 + int(days * 86400)
    hours = []
    for (stream, arm, model, h, phase, rt), per in A.hourly(ix, run, str(e0), str(stop)).items():
        for t, (n, e, p) in per.items():
            hours.append([stream, arm, model, h, phase, rt, int(A._epoch(t) - e0), n, e, p])
    evs = A.influx_events(ix, run, e0)
    sk = cfg["skylink"]
    outs = linkmodel.outages(linkmodel.schedule(seed, stop - e0, sk["mean_up_s"], sk["mean_down_s"]), stop - e0)
    rec_ev = A.recovery_events(evs, outs)
    c3 = {}
    for arm in ("river",) + BASE_ARMS:
        series = A.influx_series(ix, run, e0, stop, e0, arm=arm)
        if series:
            c3[arm] = A.recovery_table(series, rec_ev, warmup_days * 86400, stop - e0, 60)
    series = A.influx_series(ix, run, e0, stop, e0)
    c4 = A.event_window_table(series, evs, ["lin_lag_static"], warmup_days * 86400, stop - e0, 60)
    q = f'''from(bucket: "raw") |> range(start: {e0 - 1}, stop: {stop + 86400})
  |> filter(fn: (r) => r._measurement == "sensor" and r.run == "{run}" and r._field == "value")
  |> group(columns: ["stream"]) |> count()'''
    raw = {r["stream"]: int(r["_value"]) for r in A._rows(ix.query(q))}
    return {"run": run, "seed": seed, "days": days, "speed": _speed(run), "hash": summ.get("hash"), "emitted": summ.get("emitted", {}),
            "overflow_dropped": summ.get("overflow_dropped", {}), "raw_points": raw, "warm_until": int(warmup_days * 86400),
            "hours": hours, "c3": c3, "c4": c4}


def collect_resource(ix: Influx, run: str) -> list[dict]:
    q = f'''from(bucket: "metrics") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "resource" and r.run == "{run}" and r.arm == "river")
  |> filter(fn: (r) => r._field == "cpu_pct" or r._field == "rss_mb" or r._field == "step_ms_p99")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'''
    return [{k: float(r[k]) for k in ("cpu_pct", "rss_mb", "step_ms_p99")} for r in A._rows(ix.query(q)) if r.get("cpu_pct")]


def collect(a):
    runs = a.runs.split(",")
    if a.label.startswith("locked"):
        assert all(r.startswith("locked") for r in runs), "a locked label takes locked runs only"
    else:
        assert not any(r.startswith("locked") for r in runs), "locked runs only under a locked label"
    out = Path("runs/verdict") / a.label
    out.mkdir(parents=True, exist_ok=True)
    ix = Influx()
    for r in runs:
        (out / f"{r}.json").write_text(json.dumps(collect_run(ix, r, a.warmup_days), default=float))
        print(f"collected {r}")
    if a.c2_run:
        (out / "resource.json").write_text(json.dumps(collect_resource(ix, a.c2_run)))
        print(f"collected resource samples of {a.c2_run}")


def decide(a):
    d = Path(a.dir or f"runs/verdict/{a.label}")
    runs = {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json")) if p.stem not in ("resource", "verdict")}
    res_path = d / "resource.json"
    reps = []
    for pair in filter(None, (a.replicate or "").split(",")):
        x, y = pair.split(":")
        reps.append((runs.pop(x) if x in runs else None, runs.pop(y)))
    res = V.decide(list(runs.values()), json.loads(res_path.read_text()) if res_path.exists() else None,
                   json.loads(Path(a.triage).read_text()) if a.triage else None,
                   json.loads(Path(a.bench).read_text()) if a.bench else None, [p for p in reps if p[0]])
    (d / "verdict.json").write_text(json.dumps(res, indent=1, default=str))
    md = V.report_md(res, a.label)
    Path("reports").mkdir(exist_ok=True)
    Path(f"reports/verdict-{a.label}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--label", required=True); c.add_argument("--runs", required=True)
    c.add_argument("--c2-run"); c.add_argument("--warmup-days", type=float, default=2.0)
    d = sub.add_parser("decide"); d.add_argument("--label", required=True); d.add_argument("--dir")
    d.add_argument("--triage"); d.add_argument("--bench"); d.add_argument("--replicate")
    args = ap.parse_args()
    {"collect": collect, "decide": decide}[args.cmd](args)
