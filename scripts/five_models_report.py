#!/usr/bin/env python3
"""Tables for reports/five-models-2026-10-20.md from runs/agent/five-models/* and runs/agent/five-<name>-{t0,t3,en}.
Bootstrap 95% CIs (2000 resamples over cases, seed 0) are computed here; the eval scripts do not give any."""
import json
import sys
from pathlib import Path

import numpy as np

from skylink.agent import alerts
from skylink.agent.jobs import macro_f1
from five_models import loops   # scripts/ is on sys.path when run as a script

R, OUT = Path("runs/agent"), Path("runs/agent/five-models")
NAMES = {"gptoss": "gpt-oss-20b MXFP4", "q14": "Qwen3 14B MLX 4-bit", "ministral": "Ministral 3 14B Q4_K_M",
         "lfm2": "LFM2 24B-A2B MLX 4-bit", "q35": "Qwen3.5 9B MLX 8-bit (thinking off)"}


def f1ci(truth, pred, n=2000):
    rng = np.random.default_rng(0)
    t, p = np.array(truth), np.array([x or "none" for x in pred])
    f = lambda i: macro_f1(list(t[i]), list(p[i]), alerts.LABELS)
    vals = [f(rng.integers(0, len(t), len(t))) for _ in range(n)]
    return f(np.arange(len(t))), np.percentile(vals, 2.5), np.percentile(vals, 97.5)


def triage_row(path):
    d = json.loads(Path(path).read_text())
    return d["truth"], list(d["preds"].values())[0], d["results"]


def honesty_arms():
    """(arm label, list of runs) from the raw honesty outputs. Each run: dict(prompt, answer, finish, loop, ...)."""
    arms = {}
    for k, nm in NAMES.items():
        b = json.loads((OUT / k / "bench.json").read_text())
        runs = [dict(r, prompt=p) for p, rs in b["honesty"].items() for r in rs]
        h2 = OUT / k / "hippo2.json"
        if h2.exists():
            runs += [dict(r, prompt=p) for p, rs in json.loads(h2.read_text()).get("honesty", {}).items() for r in rs if p not in b["honesty"]]
        arms[f"{nm}, honesty set"] = runs
        for rt in ("raw_triage_nothink",):
            if rt in b:
                arms[f"{nm}, free-form triage (30)"] = b[rt]["rows"]
        t = OUT / k / "think.json"
        if t.exists():
            td = json.loads(t.read_text())
            if "honesty_think" in td:
                arms[f"{nm.replace(' (thinking off)', '')}, thinking on, honesty set"] = [dict(r, prompt=p) for p, rs in td["honesty_think"].items() for r in rs]
            if "raw_triage_think" in td:
                arms[f"{nm.replace(' (thinking off)', '')}, thinking on, free-form triage (30)"] = td["raw_triage_think"]["rows"]
    return arms


def loop_tables():
    """Runs that hit the token cap (finish_reason length) or contain a sentence/line repeated 5+ times (answer; for runs recorded after
    2026-10-20 also the reasoning text). Constrained job T/E/N/P calls keep no raw text, so they are not counted."""
    print("\n### Runs that hit the token cap or loop (per arm)")
    print("| arm | runs | hit cap | repeated-line loop | cap or loop |\n|---|---|---|---|---|")
    for arm, runs in honesty_arms().items():
        cap = [r.get("finish") == "length" for r in runs]
        lp = [bool(r.get("loop")) or loops(r.get("answer", "")) for r in runs]
        print(f"| {arm} | {len(runs)} | {sum(cap)} | {sum(lp)} | {sum(a or b for a, b in zip(cap, lp))} |")


def hippo_tables():
    print("\n### Hippo runs, per run (answer reached = non-empty final answer with finish_reason stop)")
    print("| model / arm | case | run | finish | thinking tokens | completion tokens | answer reached | loop |\n|---|---|---|---|---|---|---|---|")
    for arm, runs in honesty_arms().items():
        for r in runs:
            if r.get("prompt") in ("halluc", "halluc2") and "reasoning_tokens" in r:
                print(f"| {arm} | {'A' if r['prompt'] == 'halluc' else 'B'} | | {r.get('finish')} | {r.get('reasoning_tokens')} | {r.get('tokens')} | "
                      f"{'yes' if r.get('answer') and r.get('finish') == 'stop' else 'no'} | {'yes' if r.get('loop') or loops(r.get('answer', '')) else 'no'} |")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "hippo":
        return hippo_tables()
    print("### Speed and memory (context 4096)")
    print("| model | free % before load / loaded | peak LM Studio RSS GB | load s | short prompt TTFT s | tok/s | 2.3k-token prompt TTFT s |\n|---|---|---|---|---|---|---|")
    for k, nm in NAMES.items():
        b = json.loads((OUT / k / "bench.json").read_text())
        s, l = b["speed"]["short"], b["speed"]["long"]
        med = lambda xs: float(np.median([x for x in xs if x is not None]))
        print(f"| {nm} | {b['load']['free_before_pct']} / {b['load']['free_loaded_pct']} | {b['memory_sampler']['peak_rss_gb']} (min free {b['memory_sampler']['min_free_pct']} %) | "
              f"{b['load']['load_s']} | {med([x['ttft_s'] for x in s]):.2f} | {med([x['tok_s'] for x in s]):.1f} | {l[0]['ttft_s']} ({l[0]['prompt_tokens']} tok) |")
    print("\n### Job T triage, 300 dev cases (rules 0.630)")
    print("| model | zero-shot F1 [95% CI] | 3-shot F1 [95% CI] | 3-shot accuracy | invalid (of 300, 0-shot/3-shot) | 3-shot p50 s |\n|---|---|---|---|---|---|")
    for k, nm in NAMES.items():
        t0, p0, r0 = triage_row(R / f"five-{k}-t0" / "result.json")
        t3, p3, r3 = triage_row(R / f"five-{k}-t3" / "result.json")
        a, b = f1ci(t0, p0), f1ci(t3, p3)
        print(f"| {nm} | {a[0]:.3f} [{a[1]:.2f}, {a[2]:.2f}] | {b[0]:.3f} [{b[1]:.2f}, {b[2]:.2f}] | {r3[k]['accuracy']} | {r3[k]['invalid']+0}/{r0[k]['invalid']} | {r3[k].get('p50_s')} |")
    t, p, r = triage_row(R / "five-gptoss-t3" / "result.json")
    rb = f1ci(t, [alerts.rules_baseline(c) for c in alerts.balanced([alerts.Case(**c) for c in json.loads((R / 'cases.json').read_text())], 100, seed=7)])
    print(f"\nRules baseline: {rb[0]:.3f} [{rb[1]:.2f}, {rb[2]:.2f}]")
    print("\n### Jobs E, N, P and raw JSON")
    print("| model | E accuracy (60) | E valid, constrained | N valid (40) | P valid, constrained (30) | E valid, unconstrained (30) | P valid, unconstrained (30) |\n|---|---|---|---|---|---|---|")
    for k, nm in NAMES.items():
        pr = json.loads((R / f"five-{k}-en" / "profile.json").read_text())[k]
        b = json.loads((OUT / k / "bench.json").read_text())
        print(f"| {nm} | {pr['explain']['accuracy']} | {pr['explain']['valid']} | {pr['notes']['valid']} | {b['propose_constrained']['valid']}/30 | "
              f"{b['raw_json']['E']['valid_schema']}/30 | {b['raw_json']['P']['valid_schema']}/30 |")
    print("\n### Thinking on/off, Qwen3 14B, 30 triage cases (10 per class), 3-shot, free-form JSON, no constrained decoding")
    loop_tables()
    th = json.loads((OUT / "q14" / "think.json").read_text())
    off = json.loads((OUT / "q14" / "bench.json").read_text())["raw_triage_nothink"]["rows"]
    on = th["raw_triage_think"]["rows"]
    for lab, rows in (("off", off), ("on", on)):
        t_, p_ = [r["truth"] for r in rows], [r["pred"] for r in rows]
        f = f1ci(t_, p_)
        print(f"- thinking {lab}: {sum(a == b for a, b in zip(t_, p_))}/{len(rows)} correct, macro-F1 {f[0]:.3f} [{f[1]:.2f}, {f[2]:.2f}], no label {sum(x is None for x in p_)}, mean {np.mean([r['s'] for r in rows]):.1f} s per case")


if __name__ == "__main__":
    main()
