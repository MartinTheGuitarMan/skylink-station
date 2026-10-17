#!/usr/bin/env python3
"""Triage evaluation (C5a): labelled alert cases from DEV seeds, rules baseline vs local models via mcp-minions.

    uv run --extra agent python scripts/agent_eval.py build --seeds 1,2,3 --days 7
    uv run --extra agent python scripts/agent_eval.py run --models e4b=google/gemma-4-e4b --per-class 30 --id t1
    uv run --extra agent python scripts/agent_eval.py report --id t1

Model specs are name=lmstudio-model-id (or name=ollama:<model>). Locked seeds 101-105 are refused."""
import argparse
import datetime as dt
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from skylink.agent import alerts
from skylink.agent.jobs import TRIAGE_HINT, Agent, CallLog, macro_f1
from skylink.sim.replay import window_end
from skylink.agent.minions import MinionsClient

OUT = Path("runs/agent")
STREAMS = ["temp", "pressure", "wind", "vibration", "solar"]


def build(a):
    seeds = [int(x) for x in a.seeds.split(",")]
    assert not any(100 < s < 106 for s in seeds), "locked seeds are not for development"
    cases, dropped = [], Counter()
    for sd in seeds:
        series, plan = alerts.aggregate_series(sd, a.days, STREAMS)
        e, info = alerts.edge_cases(series, plan, sd, len(next(iter(series.values()))))
        cases += e + alerts.artefact_cases(series, plan, sd, info)
        dropped.update(info["dropped"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cases.json").write_text(json.dumps([c.__dict__ for c in cases]))
    print(Counter(c.label for c in cases), dict(dropped))


def load():
    return [alerts.Case(**c) for c in json.loads((OUT / "cases.json").read_text())]


def metrics(truth, pred, lats=None, invalid=0):
    ok = [(t, p) for t, p in zip(truth, pred) if p is not None]
    t2, p2 = ([x[0] for x in ok], [x[1] for x in ok]) if ok else ([], [])
    f1 = macro_f1(truth, [p or "none" for p in pred], alerts.LABELS)   # an invalid answer counts as wrong
    out = {"n": len(truth), "macro_f1": round(f1, 3), "accuracy": round(sum(t == p for t, p in zip(truth, pred)) / len(truth), 3),
           "invalid": invalid}
    if lats:
        s = sorted(lats)
        out.update(p50_s=round(statistics.median(s) / 1000, 2), p95_s=round(s[int(0.95 * (len(s) - 1))] / 1000, 2))
    return out


def run(a):
    pool = load()
    cases = alerts.balanced(pool, a.per_class, seed=7)
    truth = [c.label for c in cases]
    hint = TRIAGE_HINT if not a.fewshot else alerts.fewshot_hint(TRIAGE_HINT, pool, {c.id for c in cases}, a.fewshot)
    deadline = window_end(a.until)
    res = {"rules": metrics(truth, [alerts.rules_baseline(c) for c in cases]),
           "constant_real_event": metrics(truth, ["real_event"] * len(cases))}
    d = OUT / a.id
    d.mkdir(parents=True, exist_ok=True)
    preds = {}
    for spec in a.models.split(","):
        name, model = spec.split("=", 1)
        if model.startswith("roster:"):      # e.g. jev=roster:config/roster-jev.json (decision model, classify only)
            client = MinionsClient(name, name=name, timeout_s=a.timeout, roster=str(Path(model[7:]).resolve()),
                                   extra_env={"MINION_META": "1"})
        else:
            backend, model = ("ollama", model[7:]) if model.startswith("ollama:") else ("lmstudio", model)
            client = MinionsClient(model, backend=backend, name=name, timeout_s=a.timeout)
        ag, lats, bad, pred = Agent(client, CallLog(d / f"{name}.jsonl")), [], 0, []
        t0 = time.time()
        for i, c in enumerate(cases):
            if deadline and dt.datetime.now(deadline.tzinfo) >= deadline:
                print(f"{name}: window over after {i} cases, stopping", file=sys.stderr)
                break
            o = ag.triage(c.text(), hint)
            pred.append(o.value if o.valid else None)
            bad += not o.valid
            lats.append(o.reply.latency_ms)
            if i % 10 == 0:
                print(f"{name}: {i + 1}/{len(cases)}", file=sys.stderr, flush=True)
        client.close()
        done = len(pred)
        res[name] = metrics(truth[:done], pred, lats, bad)
        if done < len(cases):
            res[name]["partial"] = f"{done}/{len(cases)}"
        res[name]["wall_s"] = round(time.time() - t0)
        preds[name] = pred
    (d / "result.json").write_text(json.dumps({"results": res, "truth": truth, "preds": preds,
                                               "ids": [c.id for c in cases]}, indent=1))
    report(a)


def report(a):
    r = json.loads((OUT / a.id / "result.json").read_text())["results"]
    base = r["rules"]["macro_f1"]
    lines = ["| arm | n | macro-F1 | vs rules | accuracy | invalid | p50 s | p95 s |", "|---|---|---|---|---|---|---|---|"]
    for k, v in r.items():
        lines.append(f"| {k}{' (partial ' + v['partial'] + ')' if v.get('partial') else ''} | {v['n']} | {v['macro_f1']} | {v['macro_f1'] - base:+.3f} | {v['accuracy']} | {v['invalid']} | "
                     f"{v.get('p50_s', '')} | {v.get('p95_s', '')} |")
    print("\n".join(lines))
    (OUT / a.id / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--seeds", default="1,2,3"); b.add_argument("--days", type=float, default=7)
    r = sub.add_parser("run"); r.add_argument("--models", required=True); r.add_argument("--per-class", type=int, default=30)
    r.add_argument("--id", required=True); r.add_argument("--timeout", type=int, default=120)
    r.add_argument("--fewshot", type=int, default=0, help="worked examples per class in the hint (from cases outside the eval set)")
    r.add_argument("--until", help="stop cleanly at this Europe/Stockholm clock time, e.g. 06:00")
    p = sub.add_parser("report"); p.add_argument("--id", required=True)
    args = ap.parse_args()
    {"build": build, "run": run, "report": report}[args.cmd](args)
