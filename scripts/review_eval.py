#!/usr/bin/env python3
"""Job R, retrospective review (C5d): rules R0/R1 vs model methods R2/R3/R4 on one-hour windows of dev seed 3.

    uv run python scripts/review_eval.py build --seeds 1,2,3 --days 7
    uv run --extra agent python scripts/review_eval.py run --id r-pilot --windows 12 \
        --models q14=qwen/qwen3-14b --methods r0,r1,r2,r3,r4 --until 06:00
    uv run python scripts/review_eval.py report --id r-pilot

Model specs as in agent_eval.py (name=lmstudio-model-id or name=ollama:<model>). Few-shot examples come from seeds 1-2 only;
the comparison uses seed 3. Locked seeds are refused. Writes runs/review/<id>/{reports.jsonl,result.json,report.md}."""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np

from skylink.agent import review
from skylink.agent.alerts import LABELS
from skylink.agent.jobs import DESCRIPTIONS, TRIAGE_HINT
from skylink.sim.replay import window_end

OUT = Path("runs/review")
EVAL_SEED, POOL_SEEDS = 3, (1, 2)

FIELDS = ("Hindsight numbers come from the full event-time series after the window, in order: event_time_z_at_alert is the "
          "value at the alert second in true time order, in units of the noise before it (near 0: the true series shows "
          "nothing there); seconds_beyond_4_sigma_from_alert is how long the excursion lasted; level_after_* is the level "
          "later, same units; offset_after_*_vs_typical_* compares the later level with a normal change of the stream over "
          "that lag (1 = normal); identical_value_run_s is how long the value stayed exactly the same; an alert inside an "
          "uplink outage was computed from data that arrived late. Physics of the station: wind gusts last 3-15 s and are "
          "at most about 2.6 times the mean; vibration bursts decay over several seconds; solar cloud edges change the level "
          "for minutes; pressure fronts take hours. Sensor faults: a stuck value, a spike of one second, a ramp, an offset step.")
REPORT_HINT = ("You review one hour of a remote station after the fact. Give every alert a cause, list the streams that had a "
               "sensor fault, and write a summary of at most 80 words for an operator ashore. Name alerts by their id (A1, A2). "
               "Use only numbers that appear in the input, or counts of your own labels. " + FIELDS)
HYBRID_HINT = ("You review one hour of a remote station after the fact. Each alert already has a label from fixed rules "
               "(rules_label). Override a label only when the numbers clearly contradict it, and give the reason; otherwise "
               "return no override. Then list the streams that had a sensor fault and write a summary of at most 80 words for "
               "an operator ashore. Name alerts by their id (A1, A2). Use only numbers that appear in the input, or counts of "
               "the final labels. " + FIELDS)


def load(seed: int) -> list[review.Window]:
    return [review.Window.from_dict(d) for d in json.loads((OUT / f"windows-s{seed}.json").read_text())]


def build(a):
    OUT.mkdir(parents=True, exist_ok=True)
    for sd in (int(x) for x in a.seeds.split(",")):
        ws = review.build_seed(sd, a.days)
        (OUT / f"windows-s{sd}.json").write_text(json.dumps([w.to_dict() for w in ws]))
        print(f"seed {sd}: {len(ws)} windows, {sum(len(w.alerts) for w in ws)} alerts")


def fewshot(per_class: int = 3, seed: int = 11) -> str:
    pool = [x for sd in POOL_SEEDS for w in load(sd) for x in w.alerts]
    rng = np.random.default_rng(seed)
    parts = ["Worked examples from other runs (the alert, then the correct cause):"]
    for lab in LABELS:
        cands = [x for x in pool if x.label == lab]
        for i in rng.permutation(len(cands))[:per_class]:
            parts.append(review.alert_text(cands[i]) + f"\n=> {lab}")
    return "\n".join(parts)


def hybrid_text(w: review.Window, base: dict) -> str:
    lines = w.text().splitlines()
    head, rest = lines[:3], lines[3:]
    return "\n".join(head + [f"{ln} | rules_label={base[x.aid]}" for ln, x in zip(rest, w.alerts)])


def client_for(name: str, spec: str, timeout: int):
    from skylink.agent.minions import MinionsClient
    backend, model = ("ollama", spec[7:]) if spec.startswith("ollama:") else ("lmstudio", spec)
    return MinionsClient(model, backend=backend, name=name, timeout_s=timeout)


def run_model(name, client, method, windows, log, deadline, shots):
    reports = []
    for i, w in enumerate(windows):
        if deadline and dt.datetime.now(deadline.tzinfo) >= deadline:
            print(f"{name}/{method}: window over after {i} windows", file=sys.stderr)
            break
        t0 = time.perf_counter()
        if method == "r2":
            labels, bad = {}, ""
            outs = "; ".join(f"t={x} to t={y}" for x, y in w.outages) or "none"
            for x in w.alerts:
                r = client.call("classify", {"text": f"Uplink outages in this hour: {outs}.\n" + review.alert_text(x),
                                             "labels": LABELS, "descriptions": DESCRIPTIONS,
                                             "hint": TRIAGE_HINT + " " + FIELDS + "\n" + shots})
                lab = (r.data or {}).get("label") if r.ok else None
                labels[x.aid] = lab if lab in LABELS else None
                bad = bad or ("" if r.ok else r.error or "error")
            rep = review.from_labels(w, f"{name}/r2", labels, time.perf_counter() - t0, valid=not bad, why=bad)
        else:
            base = {x.aid: review.rules_r1(x) for x in w.alerts} if method == "r4" else None
            schema = review.report_schema(w, with_overrides=method == "r4")
            text = hybrid_text(w, base) if base else w.text()
            r = client.call("extract", {"text": text, "schema": schema, "hint": HYBRID_HINT if base else REPORT_HINT})
            rep = review.from_model(w, f"{name}/{method}", r.data if r.ok else None, time.perf_counter() - t0,
                                    "" if r.ok else (r.error or "error"), base)
            log.write(json.dumps({"window": w.id, "method": rep.method, "raw": r.raw[:4000], "error": r.error}) + "\n")
        reports.append(rep)
        print(f"{name}/{method}: {i + 1}/{len(windows)} {rep.latency_s:.1f}s summary_ok={rep.summary_ok} {rep.why[:60]}",
              file=sys.stderr, flush=True)
    return reports


def run(a):
    windows = review.sample(load(EVAL_SEED), a.windows)
    d = OUT / a.id
    d.mkdir(parents=True, exist_ok=True)
    methods = a.methods.split(",")
    reports = []
    if "r0" in methods:
        reports += [review.from_labels(w, "r0", {x.aid: review.rules_r0(x) for x in w.alerts}) for w in windows]
    if "r1" in methods:
        reports += [review.from_labels(w, "r1", {x.aid: review.rules_r1(x) for x in w.alerts}) for w in windows]
    deadline = window_end(a.until)
    shots = fewshot() if "r2" in methods else ""
    with (d / "raw.jsonl").open("a") as log:
        for spec in (a.models.split(",") if a.models else []):
            name, model = spec.split("=", 1)
            client = client_for(name, model, a.timeout)
            try:
                for m in [m for m in methods if m in ("r3", "r4", "r2")]:
                    reports += run_model(name, client, m, windows, log, deadline, shots)
            finally:
                client.close()
    with (d / "reports.jsonl").open("w") as f:
        for r in reports:
            f.write(json.dumps(r.__dict__) + "\n")
    (d / "windows.json").write_text(json.dumps([w.id for w in windows]))
    report(a)


def report(a):
    d = OUT / a.id
    ids = json.loads((d / "windows.json").read_text())
    windows = [w for w in load(EVAL_SEED) if w.id in set(ids)]
    reps = [review.Report(**json.loads(x)) for x in (d / "reports.jsonl").read_text().splitlines()]
    methods = list(dict.fromkeys(r.method for r in reps))
    res = {m: review.score(windows, [r for r in reps if r.method == m]) for m in methods}
    base = [r for r in reps if r.method == "r1"]
    for m in methods:
        if m not in ("r0", "r1") and base:
            res[m]["vs_r1"] = review.paired_diff(windows, [r for r in reps if r.method == m], base)
    lines = [f"Job R on dev seed {EVAL_SEED}: {len(windows)} windows, {sum(len(w.alerts) for w in windows)} alerts, "
             f"{sum(1 for w in windows for x in w.alerts if x.label == 'backfill_artefact')} artefacts. "
             f"Raw 1 s data per window: {review.window_bytes(windows[0])} bytes.", "",
             "| method | windows | macro-F1 [95% CI] | vs R1 [95% CI] | fault P / R | summary valid | invalid | p50 s/window | report bytes | overrides |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for m, v in res.items():
        vs = v.get("vs_r1")
        vs_s = f"{vs['diff']:+.3f} [{vs['ci'][0]:+.3f}, {vs['ci'][1]:+.3f}]" if vs else ""
        lines.append(f"| {m} | {v['windows']} | {v['macro_f1']} [{v['macro_f1_ci'][0]}, {v['macro_f1_ci'][1]}] | {vs_s} | "
                     f"{v['fault_precision']} / {v['fault_recall']} | {v['summary_validity']} | {v['invalid_rate']} | "
                     f"{v['p50_s_per_window']} | {v['report_bytes_mean']} | {v['overrides']} |")
    (d / "result.json").write_text(json.dumps(res, indent=1))
    (d / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--seeds", default="1,2,3"); b.add_argument("--days", type=float, default=7)
    r = sub.add_parser("run"); r.add_argument("--id", required=True); r.add_argument("--windows", type=int, default=40)
    r.add_argument("--models", default=""); r.add_argument("--methods", default="r0,r1,r2,r3,r4")
    r.add_argument("--timeout", type=int, default=300); r.add_argument("--until", help="stop at this Europe/Stockholm time")
    p = sub.add_parser("report"); p.add_argument("--id", required=True)
    args = ap.parse_args()
    {"build": build, "run": run, "report": report}[args.cmd](args)
