#!/usr/bin/env python3
"""Job W, slow degradation (C9): online-only arm vs reference comparison on wear runs and their healthy twins.

    uv run python scripts/wear_eval.py --id w-dev --seeds 1-3,41-60

Offline, no Influx, a few seconds per seed. Dev seeds only: locked seeds 101-105 are refused.
Writes runs/wear/<id>/{result.json,report.md}."""
import argparse
import json
import sys
import tomllib
from pathlib import Path

import numpy as np

from skylink import degradation as dg
from skylink.agent.alerts import FLOOR, aggregate_series

OUT = Path("runs/wear")
CFG = "config/scenario-wear.toml"
STREAMS = ["temp", "pressure", "wind", "vibration", "solar"]


def parse_seeds(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def one_seed(seed: int, days: float, wear: dict) -> dict:
    twin, plan_t = aggregate_series(seed, days, STREAMS)
    worn, plan_w = aggregate_series(seed, days, ["vibration"], wear=wear)
    ev = next(e for e in plan_w if e.kind == "wear")
    row = {"seed": seed, "t0_days": ev.t0 / 86400, "ramp_days": ev.aux / 86400, "factor": ev.mag, "arms": {}, "false": {}}
    hm_t = {s: dg.hourly_medians(twin[s]) for s in STREAMS}
    hm_w = dg.hourly_medians(worn["vibration"])
    for name, reb in (("b", False), ("b_slow", True)):
        arms_t = {s: dg.reference_arm(hm_t[s], FLOOR[s], reb) for s in STREAMS}
        arm_w = dg.reference_arm(hm_w, FLOOR["vibration"], reb)
        row["arms"][name] = dg.detection(arm_w, arms_t["vibration"], ev.t0)
        row["arms"][name]["g_at_end"] = float(arm_w["g"][-1])
        row["false"][name] = {s: dg.false_alerts(arms_t[s], dg.excused_hours(plan_t, s, len(hm_t[s]))) for s in STREAMS}
    row["arms"]["a"] = dg.online_arm(worn["vibration"], twin["vibration"], plan_w, ev)
    return row


def summarise(rows: list[dict]) -> dict:
    out = {"n": len(rows)}
    for name in ("b", "b_slow"):
        det = [r["arms"][name] for r in rows if r["arms"][name]["detected"]]
        fa = {s: (sum(r["false"][name][s]["false"] for r in rows), sum(r["false"][name][s]["healthy_days"] for r in rows),
                  sum(r["false"][name][s]["excused_alerts"] for r in rows)) for s in STREAMS}
        out[name] = {"detection_rate": len(det) / len(rows),
                     "median_delay_days": float(np.median([d["delay_days"] for d in det])) if det else None,
                     "hold_pooled": float(np.mean([d["hold"] for d in det])) if det else None,
                     "false_per_day": {s: (f / d if d else None) for s, (f, d, _) in fa.items()},
                     "false_counts": {s: f for s, (f, _, _) in fa.items()},
                     "healthy_days": {s: d for s, (_, d, _) in fa.items()},
                     "alerts_on_long_faults": {s: x for s, (_, _, x) in fa.items()}}
        b = out[name]
        b["pass"] = {"detection>=0.90": b["detection_rate"] >= 0.90,
                     "median_delay<=5d": b["median_delay_days"] is not None and b["median_delay_days"] <= 5.0,
                     "hold>=0.90": b["hold_pooled"] is not None and b["hold_pooled"] >= 0.90,
                     "vib_false<=0.05/d": (b["false_per_day"]["vibration"] or 0.0) <= 0.05}
        b["verdict"] = "flags the degradation" if all(b["pass"].values()) else "not shown"
    a = [r["arms"]["a"] for r in rows]
    flagged = sum(1 for x in a if x["flags"])
    out["a"] = {"runs_flagged": flagged, "flag_rate": flagged / len(rows),
                "adapts_it_away": flagged / len(rows) < 0.10,
                "error_ratio_median": float(np.median([x["error_ratio_last_ramp_day"] for x in a]))}
    return out


def report(rows: list[dict], s: dict) -> str:
    L = [f"# Job W (C9) dev result: {s['n']} seeds, 21 days, wear on vibration", ""]
    for name, label in (("b", "(b) frozen reference"), ("b_slow", "(b') slow re-baseline")):
        b = s[name]
        L += [f"## Arm {label}: {b['verdict']}", "",
              f"- detection {b['detection_rate']:.2f}, median delay {b['median_delay_days'] if b['median_delay_days'] is None else round(b['median_delay_days'], 2)} d, "
              f"hold {b['hold_pooled'] if b['hold_pooled'] is None else round(b['hold_pooled'], 3)}",
              "- pass parts: " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in b["pass"].items()),
              "", "| stream | false alerts | healthy days | per day | alerts on long faults |", "|---|---|---|---|---|"]
        for st in STREAMS:
            pd = b["false_per_day"][st]
            L.append(f"| {st} | {b['false_counts'][st]} | {b['healthy_days'][st]:.1f} | {'-' if pd is None else f'{pd:.3f}'} | "
                     f"{b['alerts_on_long_faults'][st]} |")
        L.append("")
    a = s["a"]
    L += ["## Arm (a) online only", "",
          f"- runs with a wear flag: {a['runs_flagged']} of {s['n']} (adapts it away: {'yes' if a['adapts_it_away'] else 'no'})",
          f"- EWMA one-step error, last ramp day, wear / twin: median {a['error_ratio_median']:.2f}", "",
          "## Per seed", "",
          "| seed | t0 d | ramp d | F | (b) delay d | (b) hold | (b') delay d | (a) flags | (a) alerts wear/twin | (a) err ratio |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, p=2: "miss" if v is None else f"{v:.{p}f}"
    for r in rows:
        b, bs, aa = r["arms"]["b"], r["arms"]["b_slow"], r["arms"]["a"]
        L.append(f"| {r['seed']} | {r['t0_days']:.1f} | {r['ramp_days']:.1f} | {r['factor']:.2f} | {f(b['delay_days'])} | "
                 f"{f(b['hold'])} | {f(bs['delay_days'])} | {aa['flags']} | {aa['alerts_after_onset']}/{aa['twin_alerts_after_onset']} | "
                 f"{aa['error_ratio_last_ramp_day']:.2f} |")
    return "\n".join(L) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True)
    p.add_argument("--seeds", default="1-3,41-60")
    p.add_argument("--config", default=CFG)
    a = p.parse_args()
    seeds = parse_seeds(a.seeds)
    if any(101 <= sd <= 105 for sd in seeds):
        sys.exit("locked seeds 101-105 are for the final verdict only")
    cfg = tomllib.loads(Path(a.config).read_text())
    rows = []
    for sd in seeds:
        rows.append(one_seed(sd, cfg["run"]["duration_days"], cfg["wear"]))
        print(f"seed {sd}: (b) {rows[-1]['arms']['b']}  (a) flags {rows[-1]['arms']['a']['flags']}", flush=True)
    s = summarise(rows)
    out = OUT / a.id
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps({"seeds": seeds, "summary": s, "rows": rows}, indent=1))
    (out / "report.md").write_text(report(rows, s))
    print(report(rows, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
