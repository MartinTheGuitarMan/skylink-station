"""Scoring from InfluxDB: MAE, skill vs persistence with a block bootstrap (1 h blocks).

    uv run python -m skylink.analysis --run dev-1 [--warmup-days 2] [--json out.json]
    uv run python -m skylink.analysis --run dev-1 --event-windows   # C4: online vs static after regime changes

Skill = 1 - sum(abs_err) / sum(pers_abs_err), over the same steps (the engine writes the paired
persistence error on every error line). The bootstrap resamples whole hours."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
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
    """{(stream, arm, model, horizon, phase, rt): {hour: [n, sum_err, sum_pers]}} within [start, stop).
    Runs from before phase/rt tags existed get phase="normal", rt="1"."""
    base = f'''from(bucket: "forecasts") |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r._measurement == "error" and r.run == "{run}")'''
    out: dict = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))
    for fld, fn, col in (("abs_err", "count", 0), ("abs_err", "sum", 1), ("pers_abs_err", "sum", 2)):
        q = base + f'''
  |> filter(fn: (r) => r._field == "{fld}")
  |> group(columns: ["stream", "arm", "model", "horizon", "phase", "rt"])
  |> aggregateWindow(every: 1h, fn: {fn}, createEmpty: false)'''
        for r in _rows(influx.query(q)):
            key = (r["stream"], r["arm"], r["model"], int(r["horizon"]), r.get("phase") or "normal", r.get("rt") or "1")
            out[key][r["_time"]][col] = float(r["_value"])
    return out


def collapse(hours: dict, by_phase: bool = False, include_replay: bool = False) -> dict:
    """Merge phases (unless by_phase) and drop rt=0 hindcasts (unless include_replay)."""
    out: dict = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))
    for (stream, arm, model, h, phase, rt), per in hours.items():
        if rt == "0" and not include_replay:
            continue
        g = phase if by_phase else "all"
        for t, v in per.items():
            acc = out[(stream, arm, model, h, g)][t]
            for k in range(3):
                acc[k] += v[k]
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
        res.append({"stream": key[0], "arm": key[1], "model": key[2], "horizon": key[3],
                    "phase": key[4] if len(key) > 4 else "all", "n": int(n.sum()),
                    "mae": float(e.sum() / n.sum()), "mae_persistence": float(p.sum() / n.sum()),
                    "skill": float(skill), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                    "hours": len(a)})
    return res


def table(rows: list[dict]) -> str:
    multi_arm = len({r["arm"] for r in rows}) > 1
    multi_phase = len({r["phase"] for r in rows}) > 1
    head = ["stream"] + (["arm"] if multi_arm else []) + ["model", "h (s)"] + (["phase"] if multi_phase else []) + \
           ["n", "MAE", "MAE persist", "skill", "95% CI"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cells = [r["stream"]] + ([r["arm"]] if multi_arm else []) + [r["model"], str(r["horizon"])] + \
                ([r["phase"]] if multi_phase else []) + [str(r["n"]), f"{r['mae']:.4g}", f"{r['mae_persistence']:.4g}",
                f"{r['skill']:+.3f}", f"[{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}]"]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def base_vs_edge(rows: list[dict], edge_arm: str = "river") -> str:
    """For each stream/model/horizon/phase: MAE of each base arm relative to the edge arm, and how many
    real-time forecasts it produced relative to the edge (coverage)."""
    idx = {(r["stream"], r["arm"], r["model"], r["horizon"], r["phase"]): r for r in rows}
    out = ["| stream | model | h (s) | phase | base arm | MAE ratio vs edge | coverage vs edge |", "|---|---|---|---|---|---|---|"]
    for (stream, arm, model, h, phase), r in sorted(idx.items()):
        if not arm.startswith("base-"):
            continue
        e = idx.get((stream, edge_arm, model, h, phase))
        if not e or e["mae"] == 0:
            continue
        out.append(f"| {stream} | {model} | {h} | {phase} | {arm} | {r['mae'] / e['mae']:.3f} | {r['n'] / e['n']:.2f} |")
    return "\n".join(out)


# ---- C4: online vs static in the hour after regime changes -------------------------------------
# Regime changes = events that move the level the model must follow. Windows start at the logged onset
# (and, for steps and drifts, also at the logged end, when the sensor snaps back).
WINDOW_KINDS = ("front", "step", "drift", "seasonal", "step_end", "drift_end")


def change_windows(events: list[dict], warm_s: float, stop_s: float, window_s: float = 3600.0) -> dict:
    """{kind: [(a, b)]} score windows in event seconds, clipped to [warm_s, stop_s). `events` are dicts with
    stream, kind, t0, t1 (seconds since run start); the stream is kept in the key's second slot."""
    out: dict = defaultdict(list)
    for e in events:
        for kind, t in ((e["kind"], e["t0"]), (e["kind"] + "_end", e["t1"])):
            if kind not in WINDOW_KINDS:
                continue
            a, b = max(t, warm_s), min(t + window_s, stop_s)
            if b > a:
                out[(e["stream"], kind)].append((a, b))
    return out


def window_mae(err_sum: np.ndarray, err_n: np.ndarray, wins: list[tuple[float, float]], bin_s: int) -> dict | None:
    """Pooled MAE over the bins inside the windows, bootstrap over windows. Bins hold sum and count of abs error."""
    if not wins:
        return None
    sums = np.array([err_sum[int(a // bin_s):int(-(-b // bin_s))].sum() for a, b in wins])
    cnts = np.array([err_n[int(a // bin_s):int(-(-b // bin_s))].sum() for a, b in wins])
    return {"sum": sums, "n": cnts}


def compare_windows(online: tuple, static: tuple, wins: list[tuple[float, float]], bin_s: int,
                    n_boot: int = 2000, seed: int = 0) -> dict | None:
    """Reduction = 1 - MAE_online / MAE_static pooled over `wins`; 95% CI from resampling windows (events)."""
    o, s = window_mae(*online, wins, bin_s), window_mae(*static, wins, bin_s)
    if o is None or s is None or o["n"].sum() == 0 or s["sum"].sum() == 0:
        return None
    red = 1 - o["sum"].sum() / o["n"].sum() / (s["sum"].sum() / s["n"].sum())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(wins), (n_boot, len(wins)))
    mo = o["sum"][idx].sum(1) / np.maximum(o["n"][idx].sum(1), 1)
    ms = s["sum"][idx].sum(1) / np.maximum(s["n"][idx].sum(1), 1)
    boots = 1 - mo / np.maximum(ms, 1e-12)
    return {"events": len(wins), "mae_online": float(o["sum"].sum() / o["n"].sum()),
            "mae_static": float(s["sum"].sum() / s["n"].sum()), "reduction": float(red),
            "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]}


def event_window_table(series: dict, events: list[dict], static, warm_s: float, stop_s: float, bin_s: int,
                       window_s: float = 3600.0) -> list[dict]:
    """series: {(stream, model, horizon): (err_sum, err_n)} arrays per bin of bin_s seconds.
    One row per stream, horizon, online model, reference and window kind (plus kind "stationary"): the C4 numbers.
    `static` is one reference model name or a list of them; the first is the pre-registered one (frozen after
    warm-up), further ones are extra columns (e.g. a periodically retrained model). Row key "ref" names it."""
    refs = [static] if isinstance(static, str) else list(static)
    rows = []
    for r in refs:
        rows += _event_window_rows(series, events, r, warm_s, stop_s, bin_s, window_s)
    return rows


def _event_window_rows(series: dict, events: list[dict], static: str, warm_s: float, stop_s: float, bin_s: int,
                       window_s: float) -> list[dict]:
    wins = change_windows(events, warm_s, stop_s, window_s)
    rows = []
    for (stream, model, h), ser in sorted(series.items()):
        if model == static or (stream, static, h) not in series:
            continue
        ref = series[(stream, static, h)]
        for (st, kind), ws in sorted(wins.items()):
            if st != stream:
                continue
            r = compare_windows(ser, ref, ws, bin_s)
            if r:
                rows.append({"stream": stream, "model": model, "horizon": h, "kind": kind, "ref": static, **r})
        # stationary: bins outside every change window, resampled by day
        n = len(ser[0])
        free = np.ones(n, bool)
        for (st, _), ws in wins.items():
            if st == stream:
                for a, b in ws:
                    free[int(a // bin_s):int(-(-b // bin_s))] = False
        free[:int(warm_s // bin_s)] = False
        free[int(stop_s // bin_s):] = False
        per_day = int(86400 // bin_s)
        days = [(d * per_day, min((d + 1) * per_day, n)) for d in range(int(warm_s // 86400), -(-n // per_day))]
        so = np.array([ser[0][a:b][free[a:b]].sum() for a, b in days])
        no = np.array([ser[1][a:b][free[a:b]].sum() for a, b in days])
        ss = np.array([ref[0][a:b][free[a:b]].sum() for a, b in days])
        ns = np.array([ref[1][a:b][free[a:b]].sum() for a, b in days])
        if no.sum() == 0 or ns.sum() == 0 or ss.sum() == 0:
            continue
        rng = np.random.default_rng(0)
        idx = rng.integers(0, len(days), (2000, len(days)))
        boots = 1 - (so[idx].sum(1) / np.maximum(no[idx].sum(1), 1)) / np.maximum(ss[idx].sum(1) / np.maximum(ns[idx].sum(1), 1), 1e-12)
        rows.append({"stream": stream, "model": model, "horizon": h, "kind": "stationary", "ref": static, "events": len(days),
                     "mae_online": float(so.sum() / no.sum()), "mae_static": float(ss.sum() / ns.sum()),
                     "reduction": float(1 - (so.sum() / no.sum()) / (ss.sum() / ns.sum())),
                     "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]})
    return rows


def c4_verdict(rows: list[dict]) -> list[dict]:
    """Per stream, horizon and online model: pooled change-window reduction (front, step, seasonal, drift onsets)
    against the pre-registered rule: reduction >= 15 % there, and no more than 3 % loss in stationary bins.
    One verdict per reference model ("ref"); `event_gain` = window minus stationary reduction, the part of the
    gain that is specific to events (a stale reference gives the same gain everywhere, so it is about 0)."""
    out = []
    keys = sorted({(r["stream"], r["model"], r["horizon"], r.get("ref", "")) for r in rows})
    for stream, model, h, ref_name in keys:
        sub = [r for r in rows if (r["stream"], r["model"], r["horizon"], r.get("ref", "")) == (stream, model, h, ref_name)]
        ch = [r for r in sub if r["kind"] in ("front", "step", "drift", "seasonal")]
        st = next((r for r in sub if r["kind"] == "stationary"), None)
        if not ch or not st:
            continue
        # pooled by event-weighted MAE of the windows
        wo = sum(r["mae_online"] * r["events"] for r in ch) / sum(r["events"] for r in ch)
        ws = sum(r["mae_static"] * r["events"] for r in ch) / sum(r["events"] for r in ch)
        red = 1 - wo / ws
        out.append({"stream": stream, "model": model, "horizon": h, "ref": ref_name, "events": sum(r["events"] for r in ch),
                    "change_reduction": red, "stationary_reduction": st["reduction"],
                    "event_gain": red - st["reduction"],
                    "pass": bool(red >= 0.15 and st["reduction"] >= -0.03)})
    return out


def ew_table(rows: list[dict]) -> str:
    lines = ["| stream | model | h (s) | window | ref | n | MAE online | MAE ref | reduction | 95% CI |", "|" + "---|" * 10]
    for r in rows:
        lines.append(f"| {r['stream']} | {r['model']} | {r['horizon']} | {r['kind']} | {r.get('ref', '')} | {r['events']} | {r['mae_online']:.4g} | "
                     f"{r['mae_static']:.4g} | {r['reduction']:+.3f} | [{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}] |")
    return "\n".join(lines)


def verdict_table(rows: list[dict]) -> str:
    lines = ["| stream | model | h (s) | ref | change windows | reduction in windows | reduction stationary | event gain | C4 rule |",
             "|" + "---|" * 9]
    for r in rows:
        lines.append(f"| {r['stream']} | {r['model']} | {r['horizon']} | {r.get('ref', '')} | {r['events']} | {r['change_reduction']:+.3f} | "
                     f"{r['stationary_reduction']:+.3f} | {r['event_gain']:+.3f} | {'pass' if r['pass'] else 'fail'} |")
    return "\n".join(lines)


def influx_series(influx: Influx, run: str, start_s: int, stop_s: int, e0: int, bin_s: int = 60) -> dict:
    """Per-bin sum and count of abs_err for every (stream, model, horizon) of the edge arm, rt=1 only
    (bins are relative to the run start e0, in event seconds)."""
    out: dict = {}
    n = int(-(-(stop_s - e0) // bin_s))
    base = f'''from(bucket: "forecasts") |> range(start: {start_s}, stop: {stop_s})
  |> filter(fn: (r) => r._measurement == "error" and r.run == "{run}" and r._field == "abs_err")
  |> filter(fn: (r) => r.arm == "river" and (not exists r.rt or r.rt == "1"))
  |> group(columns: ["stream", "model", "horizon"])
  |> aggregateWindow(every: {bin_s}s, fn: %s, createEmpty: false)'''
    for fn, slot in (("sum", 0), ("count", 1)):
        for r in _rows(influx.query(base % fn)):
            key = (r["stream"], r["model"], int(r["horizon"]))
            arrs = out.setdefault(key, (np.zeros(n), np.zeros(n)))
            t = int((_epoch(r["_time"]) - e0 - 1) // bin_s)  # aggregateWindow stamps the window end
            if 0 <= t < n:
                arrs[slot][t] = float(r["_value"])
    return out


def _epoch(ts: str) -> float:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def influx_events(influx: Influx, run: str, e0: int) -> list[dict]:
    q = f'''from(bucket: "raw") |> range(start: {e0 - 1}) |> filter(fn: (r) => r._measurement == "truth_event" and r.run == "{run}")
  |> filter(fn: (r) => r._field == "t1_us") |> keep(columns: ["_time", "_value", "stream", "kind"])'''
    return [{"stream": r["stream"], "kind": r["kind"], "t0": _epoch(r["_time"]) - e0,
             "t1": float(r["_value"]) / 1e6 - e0} for r in _rows(influx.query(q))]




def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--config", default="config/scenario-default.toml")
    ap.add_argument("--warmup-days", type=float, default=2.0)
    ap.add_argument("--days", type=float, help="score up to this many days (default: all data)")
    ap.add_argument("--by-phase", action="store_true", help="split scores into normal / post (10 min after link-up) / outage")
    ap.add_argument("--base", action="store_true", help="print the base-arm vs edge comparison (implies --by-phase)")
    ap.add_argument("--event-windows", action="store_true",
                    help="C4: MAE of each model vs the static one in the 60 min after logged regime changes, and in stationary bins")
    ap.add_argument("--static", default="lin_lag_static", help="reference model(s), comma-separated; the first is the pre-registered one")
    ap.add_argument("--json")
    a = ap.parse_args()
    cfg = load_cfg(a.config)
    e0 = epoch_us(cfg) // 1_000_000
    start = e0 + int(a.warmup_days * 86400)
    stop = e0 + int((a.days or 400) * 86400)
    if a.event_windows:
        stop_s = e0 + int((a.days or cfg["run"]["duration_days"]) * 86400)
        series = influx_series(Influx(), a.run, e0, stop_s, e0)
        evs = influx_events(Influx(), a.run, e0)
        rows = event_window_table(series, evs, a.static.split(","), a.warmup_days * 86400, stop_s - e0, 60)
        print(ew_table(rows) + "\n\n" + verdict_table(c4_verdict(rows)))
        if a.json:
            json.dump(rows, open(a.json, "w"), indent=1)
        return
    raw = hourly(Influx(), a.run, str(start), str(stop))
    rows = summarise(collapse(raw, by_phase=a.by_phase or a.base))
    print(table(rows))
    if a.base:
        print("\n" + base_vs_edge(rows))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
