#!/usr/bin/env python3
"""Profile local models on the jobs this project needs: triage (3-shot), failure explanation, situation notes.

    uv run --extra agent python scripts/model_profile.py --models g1b=google/gemma-3-1b,e4b=google/gemma-4-e4b \
        --id day-profile-1 --until 06:00

Dev cases only. Per model: macro-F1 / accuracy per job, valid-output rate (schema + checks in code), latency, and the
memory LM Studio reports for the loaded model. Writes runs/agent/<id>/profile.json and reports/model-profile-<id>.md."""
import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from skylink.agent import alerts
from skylink.agent.jobs import EXPLAIN_SCHEMA, TRIAGE_HINT, Agent, CallLog, macro_f1
from skylink.agent.minions import MinionsClient
from skylink.sim.replay import window_end

OUT = Path("runs/agent")
CAUSE = {"sensor_fault": "sensor_fault", "backfill_artefact": "backfill_artefact", "real_event": "regime_change"}


def lms_ps() -> str:
    try:
        return subprocess.run(["lms", "ps"], capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return ""


def notes_inputs(n: int, seed: int = 5) -> list[dict]:
    rng = np.random.default_rng(seed)
    kinds = ["gust", "burst", "front", "cloud edge", "sensor step", "stuck sensor", "backfill replay"]
    out = []
    for i in range(n):
        out.append({"stream": str(rng.choice(["temp", "pressure", "wind", "vibration", "solar"])),
                    "window_hours": int(rng.choice([1, 6, 24])), "outages": int(rng.integers(0, 4)),
                    "outage_minutes_total": int(rng.integers(0, 180)), "alerts": int(rng.integers(0, 12)),
                    "mae_persistence": round(float(rng.uniform(0.05, 3)), 3),
                    "mae_best_model": round(float(rng.uniform(0.04, 2.5)), 3),
                    "dominant_event": str(rng.choice(kinds))})
    return out


def run_model(name, spec, cases, hint, deadline, d, args):
    if spec.startswith("roster:"):
        client = MinionsClient(name, name=name, timeout_s=args.timeout, roster=str(Path(spec[7:]).resolve()))
    else:
        client = MinionsClient(spec, name=name, timeout_s=args.timeout)
    ag = Agent(client, CallLog(d / f"{name}-profile.jsonl"))
    res, mem = {}, ""
    stop = lambda: deadline and dt.datetime.now(deadline.tzinfo) >= deadline

    # job 1: triage, 3-shot
    truth, pred, lats = [], [], []
    for c in cases["triage"]:
        if stop(): break
        o = ag.triage(c.text(), hint)
        truth.append(c.label); pred.append(o.value if o.valid else None); lats.append(o.reply.latency_ms)
    if truth:
        mem = mem or lms_ps()
        res["triage"] = {"n": len(truth), "macro_f1": round(macro_f1(truth, [p or "none" for p in pred], alerts.LABELS), 3),
                         "accuracy": round(sum(t == p for t, p in zip(truth, pred)) / len(truth), 3),
                         "valid": round(sum(p is not None for p in pred) / len(pred), 3),
                         "p50_s": round(float(np.median(lats)) / 1000, 2)}
    # job 2: explanation of a forecast failure (cause enum)
    if name != "j08":
        ok, valid, lats = 0, 0, []
        done = 0
        for c in cases["explain"]:
            if stop(): break
            o = ag.explain(c.text())
            done += 1; valid += o.valid; lats.append(o.reply.latency_ms)
            ok += bool(o.valid and o.value["cause"] == CAUSE[c.label])
        if done:
            res["explain"] = {"n": done, "accuracy": round(ok / done, 3), "valid": round(valid / done, 3),
                              "p50_s": round(float(np.median(lats)) / 1000, 2)}
        # job 3: situation notes (numbers must come from the stats; <= 80 words)
        valid, lats, done = 0, [], 0
        for st in cases["notes"]:
            if stop(): break
            o = ag.note(st)
            done += 1; valid += o.valid; lats.append(o.reply.latency_ms)
        if done:
            res["notes"] = {"n": done, "valid": round(valid / done, 3), "p50_s": round(float(np.median(lats)) / 1000, 2)}
    client.close()
    res["memory"] = mem
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="name=lmstudio-model-id or name=roster:path")
    ap.add_argument("--id", required=True)
    ap.add_argument("--per-class", type=int, default=100)
    ap.add_argument("--explain-per-class", type=int, default=20)
    ap.add_argument("--notes", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--until")
    ap.add_argument("--min-free-pct", type=int, default=40)
    a = ap.parse_args()
    pool = [alerts.Case(**c) for c in json.loads((OUT / "cases.json").read_text())]
    triage = alerts.balanced(pool, a.per_class, seed=7)
    ex_pool = [c for c in pool if c.id not in {x.id for x in triage}]
    cases = {"triage": triage, "explain": alerts.balanced(ex_pool, a.explain_per_class, seed=3), "notes": notes_inputs(a.notes)}
    hint = alerts.fewshot_hint(TRIAGE_HINT, pool, {c.id for c in triage}, 3)
    d = OUT / a.id
    d.mkdir(parents=True, exist_ok=True)
    deadline, results = window_end(a.until), {}
    for spec in a.models.split(","):
        name, model = spec.split("=", 1)
        free = subprocess.run("memory_pressure | awk '/free percentage/ {gsub(\"%\",\"\",$NF); print $NF}'", shell=True,
                              capture_output=True, text=True).stdout.strip()
        if free and int(free) < a.min_free_pct:
            results[name] = {"skipped": f"only {free}% memory free"}
            print(f"skip {name}: {free}% free", file=sys.stderr)
            continue
        t0 = time.time()
        print(f"{dt.datetime.now():%H:%M:%S} {name}", file=sys.stderr, flush=True)
        results[name] = run_model(name, model, cases, hint, deadline, d, a)
        results[name]["wall_min"] = round((time.time() - t0) / 60, 1)
        (d / "profile.json").write_text(json.dumps(results, indent=1))
        subprocess.run(["lms", "unload", "--all"], capture_output=True)
    rules = alerts.rules_baseline
    base = macro_f1([c.label for c in triage], [rules(c) for c in triage], alerts.LABELS)
    lines = [f"# Model profile {a.id}", "", f"Dev cases, 3-shot triage ({len(triage)} cases, rules baseline macro-F1 {base:.3f}), "
             f"explanation ({len(cases['explain'])}), notes ({len(cases['notes'])}). Valid = schema and checks in code passed.", "",
             "| model | triage F1 | triage acc | triage valid | explain acc | explain valid | notes valid | p50 triage s | wall min |",
             "|---|---|---|---|---|---|---|---|---|"]
    for n, r in results.items():
        if "skipped" in r:
            lines.append(f"| {n} | skipped: {r['skipped']} | | | | | | | |"); continue
        t, e, nt = r.get("triage", {}), r.get("explain", {}), r.get("notes", {})
        lines.append(f"| {n} | {t.get('macro_f1', '')} | {t.get('accuracy', '')} | {t.get('valid', '')} | {e.get('accuracy', '-')} | "
                     f"{e.get('valid', '-')} | {nt.get('valid', '-')} | {t.get('p50_s', '')} | {r.get('wall_min', '')} |")
    lines += ["", "LM Studio memory while loaded:"] + [f"- {n}: `{(r.get('memory') or '').splitlines()[-1] if r.get('memory') else ''}`" for n, r in results.items() if 'skipped' not in r]
    Path("reports").mkdir(exist_ok=True)
    Path(f"reports/model-profile-{a.id}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
