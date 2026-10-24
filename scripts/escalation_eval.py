#!/usr/bin/env python3
"""Escalation eval (C5e): edge model + policy + shore (Claude, local stand-ins, oracle) on the 200 edge job-T dev cases.

    uv run python scripts/escalation_eval.py

Inputs (all dev, not tracked): runs/agent/cases.json, the stored runs air-fs3 (edge gemma-4-e4b 3-shot, voter Jev 0.8B),
five-gptoss-t3 and five-q14-t3 (local shores), runs/escalation/{key,claude-answers}.json (Claude's blind answers, Q -> case).
Writes runs/escalation/result.json and prints the report tables."""
import json
import statistics
from pathlib import Path

from skylink.agent import alerts, escalation as E

RUNS = Path("runs/agent")
OUT = Path("runs/escalation")
# natural mix of edge alerts on dev seeds 1-3 (job-T cases: 2331 real, 948 fault over 21 simulated days)
NATURAL = {"real_event": 2331 / 3279, "sensor_fault": 948 / 3279}
ALERTS_PER_DAY = 3279 / 21


def preds(run, name):
    r = json.loads((RUNS / run / "result.json").read_text())
    return dict(zip(r["ids"], r["preds"][name]))


def main():
    cases = {c["id"]: alerts.Case(**c) for c in json.loads((RUNS / "cases.json").read_text())}
    ids = [i for i in json.loads((RUNS / "air-t1" / "result.json").read_text())["ids"] if "art" not in i]
    edge, voter = preds("air-fs3", "e4b"), preds("air-fs3", "j08")
    key = json.loads((OUT / "key.json").read_text())
    claude = {key[q]: lab for q, lab in json.loads((OUT / "claude-answers.json").read_text()).items()}
    shores = {"Claude": claude, "gpt-oss-20b": preds("five-gptoss-t3", "gptoss"), "Qwen3-14B": preds("five-q14-t3", "q14"),
              "oracle": {i: cases[i].label for i in ids}}
    items = []
    for i in ids:
        c = cases[i]
        items.append(E.Item(i, int(i.split("-")[0][1:]), c.second, c.label, c.text(), alerts.rules_baseline(c), edge[i], voter[i]))
    truth = [it.truth for it in items]
    outs = {sd: E.outages(sd) for sd in {it.seed for it in items}}

    res = {"n": len(items), "alone": {}, "policies": []}
    for name, p in [("edge gemma-4-e4b 3-shot", [it.edge for it in items]), ("voter Jev 0.8B", [it.voter for it in items]),
                    ("rules", [it.rules for it in items])] + [(f"shore {k} on all", [s.get(it.cid) for it in items]) for k, s in shores.items()]:
        res["alone"][name] = {"f1": round(E.f1(truth, p), 3), "ci": E.boot_f1(truth, p)}
    p0 = [it.edge for it in items]
    for pol in E.POLICIES:
        for sname, shore in shores.items():
            if E.POLICIES[pol] is None and sname != "Claude":
                continue
            lab, esc = E.final_labels(items, pol, shore)
            n_esc = sum(esc)
            rate_nat = sum(NATURAL[c] * sum(e for e, it in zip(esc, items) if it.truth == c) / sum(1 for it in items if it.truth == c)
                           for c in NATURAL)
            row = {"policy": pol, "shore": sname if E.POLICIES[pol] is not None else "-", "f1": round(E.f1(truth, lab), 3),
                   "ci": E.boot_f1(truth, lab), "vs_p0": round(E.f1(truth, lab) - E.f1(truth, p0), 3),
                   "vs_p0_ci": E.boot_diff(truth, lab, p0), "escalated": n_esc, "rate": round(n_esc / len(items), 3),
                   "q_per_day_natural": round(rate_nat * ALERTS_PER_DAY, 1),
                   "changed_right": sum(1 for e, it, l in zip(esc, items, lab) if e and it.edge != l and l == it.truth),
                   "changed_wrong": sum(1 for e, it, l in zip(esc, items, lab) if e and it.edge != l and it.edge == it.truth)}
            if n_esc:
                qb = [E.question_bytes(it) for it, e in zip(items, esc) if e]
                row["question_bytes_mean"] = round(statistics.mean(qb))
                for mode in ("on_call", "daily"):
                    st = sorted(E.timing(it, outs[it.seed], mode) for it, e in zip(items, esc) if e)
                    row[f"stale_{mode}_median_min"] = round(st[len(st) // 2] / 60, 1)
                    row[f"stale_{mode}_p95_min"] = round(st[int(0.95 * (len(st) - 1))] / 60, 1)
            row["pass"] = bool(row["vs_p0"] >= 0.10 and row["vs_p0_ci"][0] > 0 and row["rate"] <= 0.50)
            res["policies"].append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(res, indent=1))
    print(f"{len(items)} edge cases (100 real, 100 fault), two-class macro-F1 [95% CI]")
    for k, v in res["alone"].items():
        print(f"  {k}: {v['f1']} {v['ci']}")
    print("\n| policy | shore | F1 [95% CI] | vs P0 [95% CI] | escalated | q/day (natural mix) | fixed / broke | on call stale median / p95 min | daily stale median / p95 h | pass |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in res["policies"]:
        st = (f"{r.get('stale_on_call_median_min', '')} / {r.get('stale_on_call_p95_min', '')}",
              f"{round(r['stale_daily_median_min'] / 60, 1)} / {round(r['stale_daily_p95_min'] / 60, 1)}" if r.get("stale_daily_median_min") else "")
        print(f"| {r['policy']} | {r['shore']} | {r['f1']} {r['ci']} | {r['vs_p0']:+.3f} {r['vs_p0_ci']} | {r['escalated']} ({r['rate']:.0%}) | "
              f"{r['q_per_day_natural']} | {r['changed_right']} / {r['changed_wrong']} | {st[0]} | {st[1]} | {'yes' if r['pass'] else 'no'} |")


if __name__ == "__main__":
    main()
