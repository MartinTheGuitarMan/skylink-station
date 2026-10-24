"""Verdict pipeline (road step 4): every C1-C8 number and the verdict lines of section 2 of docs/success-criteria.md.

Two steps (scripts/verdict.py). `collect` runs on the Mini, where InfluxDB is, and writes one JSON per run. `decide` is pure:
it pools the runs (seeds), applies the rules and writes the report. This module holds `decide`; the tests feed it synthetic runs.

Choices the criteria leave open, fixed on 2026-10-24 before any locked run (dry-run on dev seeds only):
- Models: a "River model" is anything but the baselines (persistence, seasonal_naive, seasonal_anchor), and it must be scored
  in every run pooled (model sets differed between dev runs). C1 and C3 take the
  best River model (C3: decision of iteration 12). Edge arm = "river".
- C1: pooled skill over the hourly blocks of all runs (warm-up excluded, real-time forecasts only, all phases) =
  1 - sum(err) / sum(persistence err); 95% CI by block bootstrap over those hours (1 h blocks, 2000). Mean and sd of the per-run
  skill are reported. A stream passes if some (River model, horizon) has pooled skill >= 0.10 with CI low > 0. Holds: >= 3 streams.
- C2: from the `resource` measurement of a designated run at 1x on the Mini: mean cpu_pct <= 50 (0.5 core), max rss_mb <= 512,
  p99 over the samples of step_ms_p99 <= 50; compression: every scored run finished at speed >= 60. No 1x run: not measured,
  C2 does not hold.
- C3: front, step and drift_end on the edge arm; outage_end on each base arm, and the base arm (backfill strategy) with the most
  passing (stream, horizon) rows is taken; the edge arm at the same link-ups is reported as the control. Per (stream, horizon,
  kind): pooled median recovery over all runs' events of the best River model; per (stream, kind) pass if some horizon has a
  median <= 900 s. Holds if every (stream, kind) with >= 3 pooled events passes.
- C4: online lin_lag against lin_lag_static (the pre-registered pair); change windows pooled over runs, weighted by events;
  analysis.c4_verdict per (stream, horizon). Holds if lin_lag passes on some horizon on >= 3 of the streams with change windows.
- C5: C5a from a triage eval on locked cases (best model macro-F1 >= 0.80 and >= rules + 0.15); C5b from the job P bench rows
  (jobs.c5b_check per model arm; any arm); C5c holds when the bench's call-log summary exists (non-blocking is enforced by the
  async test) and is reported. Inputs missing: "not run", which counts as not holding.
- C6: MAE ratio base / edge per phase (outage, post = first 10 min after link-up, normal), pooled, median over (stream, River
  model, horizon) rows; soft target on the best strategy: ratio in "normal" <= 1.10.
- C7: given replicate pairs: identical stream hash (hard) and every per-model MAE within 1 %. No pairs: not run.
- C8: per run and stream, raw points in InfluxDB = points emitted (minus logged overflow drops). A run that fails is void and is
  left out of every other criterion."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict

import numpy as np

from .analysis import c4_verdict

BASELINES = {"persistence", "seasonal_naive", "seasonal_anchor"}
EDGE = "river"


def river(model: str) -> bool:
    return model not in BASELINES


# ---- C1 -----------------------------------------------------------------------------------------------------

def c1(runs: list[dict], n_boot: int = 2000, seed: int = 0) -> dict:
    """runs[i]["hours"]: rows [stream, arm, model, h, phase, rt, hour, n, err, pers]."""
    pooled: dict = defaultdict(list)          # (stream, model, h) -> [(n, e, p)] per (run, hour), phases summed
    per_run: dict = defaultdict(dict)
    for r in runs:
        acc: dict = defaultdict(lambda: [0.0, 0.0, 0.0])
        for stream, arm, model, h, phase, rt, hour, n, e, p in r["hours"]:
            if arm != EDGE or rt != "1" or not river(model) or hour < r["warm_until"]:
                continue
            a = acc[(stream, model, int(h), hour)]
            a[0] += n; a[1] += e; a[2] += p
        tot: dict = defaultdict(lambda: [0.0, 0.0])
        for (stream, model, h, hour), (n, e, p) in acc.items():
            pooled[(stream, model, h)].append((n, e, p))
            tot[(stream, model, h)][0] += e; tot[(stream, model, h)][1] += p
        for k, (e, p) in tot.items():
            if p > 0:
                per_run[k][r["run"]] = 1 - e / p
    rng = np.random.default_rng(seed)
    rows = []
    for (stream, model, h), blocks in sorted(pooled.items()):
        if len(per_run[(stream, model, h)]) < len(runs):      # a model must be scored in every run to be eligible
            continue
        a = np.array(blocks)
        if a[:, 2].sum() <= 0:
            continue
        skill = 1 - a[:, 1].sum() / a[:, 2].sum()
        idx = rng.integers(0, len(a), (n_boot, len(a)))
        boots = 1 - a[idx, 1].sum(1) / np.maximum(a[idx, 2].sum(1), 1e-12)
        runs_sk = list(per_run[(stream, model, h)].values())
        rows.append({"stream": stream, "model": model, "horizon": h, "skill": float(skill),
                     "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                     "seed_mean": float(np.mean(runs_sk)), "seed_sd": float(np.std(runs_sk, ddof=1)) if len(runs_sk) > 1 else 0.0,
                     "hours": len(a)})
    streams = {}
    for st in sorted({r["stream"] for r in rows}):
        ok = [r for r in rows if r["stream"] == st and r["skill"] >= 0.10 and r["ci95"][0] > 0]
        best = max((r for r in rows if r["stream"] == st), key=lambda r: r["skill"])
        streams[st] = {"pass": bool(ok), "best": best, "passing_rows": len(ok)}
    return {"rows": rows, "streams": streams, "holds": sum(s["pass"] for s in streams.values()) >= 3}


# ---- C2 -----------------------------------------------------------------------------------------------------

def c2(resource: list[dict] | None, speeds: list[float]) -> dict:
    comp = bool(speeds) and min(speeds) >= 60
    if not resource:
        return {"measured": False, "compression_ok": comp, "holds": False}
    cpu = statistics.mean(r["cpu_pct"] for r in resource)
    rss = max(r["rss_mb"] for r in resource)
    p99 = float(np.percentile([r["step_ms_p99"] for r in resource], 99))
    ok = cpu <= 50 and rss <= 512 and p99 <= 50
    return {"measured": True, "cpu_core_mean": round(cpu / 100, 3), "rss_mb_max": round(rss, 1), "step_ms_p99": round(p99, 2),
            "compression_ok": comp, "holds": bool(ok and comp)}


# ---- C3 -----------------------------------------------------------------------------------------------------

def _median(ts: list) -> float:
    return float(np.median([np.inf if t is None else t for t in ts])) if ts else float("nan")


def _c3_rows(runs: list[dict], arm: str, kinds: tuple) -> list[dict]:
    pool: dict = defaultdict(list)
    seen: dict = defaultdict(set)
    have = sum(1 for r in runs if r["c3"].get(arm))
    for r in runs:
        for row in r["c3"].get(arm, []):
            if row["kind"] in kinds and river(row["model"]):
                pool[(row["stream"], row["horizon"], row["kind"], row["model"])] += row["times_s"]
                seen[row["model"]].add(r["run"])
    best: dict = {}
    for (stream, h, kind, model), ts in pool.items():
        if len(seen[model]) < have:                            # a model must be in every run that has this arm
            continue
        m = _median(ts)
        k = (stream, h, kind)
        if k not in best or m < best[k]["median_s"]:
            best[k] = {"stream": stream, "horizon": h, "kind": kind, "model": model, "events": len(ts),
                       "censored": sum(t is None for t in ts), "median_s": m, "pass": bool(m <= 900)}
    return sorted(best.values(), key=lambda x: (x["stream"], x["kind"], x["horizon"]))


def _c3_pairs(rows: list[dict]) -> dict:
    out = {}
    for stream, kind in sorted({(r["stream"], r["kind"]) for r in rows}):
        sub = [r for r in rows if (r["stream"], r["kind"]) == (stream, kind)]
        out[f"{stream}/{kind}"] = {"pass": any(r["pass"] for r in sub), "events": max(r["events"] for r in sub),
                                   "best_median_s": min(r["median_s"] for r in sub)}
    return out


def c3(runs: list[dict]) -> dict:
    edge_rows = _c3_rows(runs, EDGE, ("front", "step", "drift_end"))
    base_arms = sorted({a for r in runs for a in r["c3"] if a != EDGE})
    by_arm = {a: _c3_rows(runs, a, ("outage_end",)) for a in base_arms}
    best_arm = max(base_arms, key=lambda a: sum(x["pass"] for x in by_arm[a])) if base_arms else None
    control = _c3_rows(runs, EDGE, ("outage_end",))
    pairs = _c3_pairs(edge_rows + (by_arm[best_arm] if best_arm else []))
    judged = {k: v for k, v in pairs.items() if v["events"] >= 3}
    return {"edge_rows": edge_rows, "base_rows": by_arm, "best_base_arm": best_arm, "edge_control_at_link_ups": control,
            "pairs": pairs, "holds": bool(judged) and all(v["pass"] for v in judged.values())}


# ---- C4 -----------------------------------------------------------------------------------------------------

def c4(runs: list[dict], online: str = "lin_lag", ref: str = "lin_lag_static") -> dict:
    acc: dict = {}
    for r in runs:
        for row in r["c4"]:
            if row["model"] != online or row.get("ref", ref) != ref:
                continue
            k = (row["stream"], row["model"], row["horizon"], row["kind"], ref)
            a = acc.setdefault(k, [0, 0.0, 0.0])
            a[0] += row["events"]; a[1] += row["mae_online"] * row["events"]; a[2] += row["mae_static"] * row["events"]
    pooled = [{"stream": s, "model": m, "horizon": h, "kind": kd, "ref": rf, "events": n, "mae_online": eo / n, "mae_static": es / n,
               "reduction": 1 - eo / es} for (s, m, h, kd, rf), (n, eo, es) in sorted(acc.items()) if n and es]
    v = c4_verdict(pooled)
    streams = {}
    for st in sorted({x["stream"] for x in v}):
        streams[st] = any(x["pass"] for x in v if x["stream"] == st)
    return {"rows": v, "streams": streams, "holds": sum(streams.values()) >= 3}


# ---- C5 -----------------------------------------------------------------------------------------------------

def c5(triage: dict | None, bench: dict | None) -> dict:
    from .agent.jobs import c5b_check
    out = {"c5a": {"run": triage is not None}, "c5b": {"run": bench is not None}, "c5c": {"run": bench is not None}}
    if triage:
        res = triage["results"]
        rules = res["rules"]["macro_f1"]
        models = {k: v["macro_f1"] for k, v in res.items() if k not in ("rules", "constant_real_event")}
        best = max(models, key=models.get) if models else None
        out["c5a"].update({"rules": rules, "models": models, "best": best,
                           "holds": bool(best and models[best] >= 0.80 and models[best] >= rules + 0.15)})
    if bench:
        arms = sorted({r["arm"] for r in bench["rows"]} - {"fixed", "rules"})
        checks = {a: c5b_check(bench["rows"], a) for a in arms}
        out["c5b"].update({"arms": checks, "holds": any(c["pass"] for c in checks.values())})
        out["c5c"].update({"stats": bench.get("stats"), "holds": bool(bench.get("stats"))})
    for k in ("c5a", "c5b", "c5c"):
        out[k].setdefault("holds", False)
    out["layer_justified"] = (out["c5a"]["holds"] or out["c5b"]["holds"]) and out["c5c"]["holds"]
    return out


# ---- C6 -----------------------------------------------------------------------------------------------------

def c6(runs: list[dict]) -> dict:
    acc: dict = defaultdict(lambda: [0.0, 0.0])   # (stream, arm, model, h, phase) -> [n, err]
    for r in runs:
        for stream, arm, model, h, phase, rt, hour, n, e, p in r["hours"]:
            if rt == "1" and river(model) and hour >= r["warm_until"]:
                a = acc[(stream, arm, model, int(h), phase)]
                a[0] += n; a[1] += e
    ratios: dict = defaultdict(list)
    for (stream, arm, model, h, phase), (n, e) in acc.items():
        if arm == EDGE or not n:
            continue
        en, ee = acc.get((stream, EDGE, model, h, phase), (0, 0))
        if en and ee:
            ratios[(arm, phase)].append((e / n) / (ee / en))
    table = {f"{arm}/{phase}": round(float(np.median(v)), 3) for (arm, phase), v in sorted(ratios.items())}
    arms = sorted({a for a, _ in ratios})
    normal = {a: float(np.median(ratios[(a, "normal")])) for a in arms if ratios.get((a, "normal"))}
    best = min(normal, key=normal.get) if normal else None
    return {"median_ratio": table, "best_arm": best, "soft_target_met": bool(best and normal[best] <= 1.10)}


# ---- C7, C8 -------------------------------------------------------------------------------------------------

def c7(pairs: list[tuple[dict, dict]]) -> dict:
    if not pairs:
        return {"run": False, "holds": False}
    res = []
    for a, b in pairs:
        ma, mb = _model_mae(a), _model_mae(b)
        worst = max((abs(mb[k] / ma[k] - 1) for k in ma if k in mb and ma[k]), default=0.0)
        res.append({"runs": [a["run"], b["run"]], "hash_equal": a["hash"] == b["hash"], "max_mae_change": round(worst, 4),
                    "holds": bool(a["hash"] == b["hash"] and worst < 0.01)})
    return {"run": True, "pairs": res, "holds": all(x["holds"] for x in res)}


def _model_mae(r: dict) -> dict:
    acc: dict = defaultdict(lambda: [0.0, 0.0])
    for stream, arm, model, h, phase, rt, hour, n, e, p in r["hours"]:
        if arm == EDGE and rt == "1" and hour >= r["warm_until"]:
            acc[(stream, model, h)][0] += n; acc[(stream, model, h)][1] += e
    return {k: e / n for k, (n, e) in acc.items() if n}


def c8(r: dict) -> dict:
    diffs = {s: int(r["raw_points"].get(s, 0)) - (int(n) - int(r.get("overflow_dropped", {}).get(s, 0)))
             for s, n in r["emitted"].items()}
    return {"run": r["run"], "diffs": diffs, "holds": all(d == 0 for d in diffs.values())}


# ---- all ----------------------------------------------------------------------------------------------------

def decide(runs: list[dict], resource: list[dict] | None = None, triage: dict | None = None, bench: dict | None = None,
           replicates: list[tuple[dict, dict]] = ()) -> dict:
    integrity = [c8(r) for r in runs]
    good = [r for r, i in zip(runs, integrity) if i["holds"]]
    res = {"runs": [r["run"] for r in runs], "void": [i["run"] for i in integrity if not i["holds"]], "C8": integrity}
    if not good:
        res["verdict"] = {"note": "every run is void (C8)"}
        return res
    res.update({"C1": c1(good), "C2": c2(resource, [r["speed"] for r in good]), "C3": c3(good), "C4": c4(good),
                "C5": c5(triage, bench), "C6": c6(good), "C7": c7(list(replicates))})
    res["verdict"] = {
        "Edge forecasting is valuable": res["C1"]["holds"] and res["C2"]["holds"] and res["C3"]["holds"],
        "Online learning is justified": res["C4"]["holds"],
        "The agent layer is justified": res["C5"]["layer_justified"]}
    return res


def _yn(b) -> str:
    return "holds" if b else "does not hold"


def report_md(res: dict, label: str) -> str:
    L = [f"# Verdict pipeline: {label}", "", f"Runs: {', '.join(res['runs'])}. Void (C8): {', '.join(res['void']) or 'none'}.", ""]
    if "C1" not in res:
        return "\n".join(L + [res["verdict"]["note"]])
    L += ["## Verdict lines (section 2)", ""] + [f"- **{k}**: {'yes' if v else 'no'}" for k, v in res["verdict"].items()] + [""]
    c = res["C1"]
    L += ["## C1 accuracy", f"C1 {_yn(c['holds'])}: {sum(s['pass'] for s in c['streams'].values())} of {len(c['streams'])} streams pass.", "",
          "| stream | pass | best River model | h (s) | pooled skill [95% CI] | per-seed mean ± sd |", "|---|---|---|---|---|---|"]
    for st, s in c["streams"].items():
        b = s["best"]
        L.append(f"| {st} | {'yes' if s['pass'] else 'no'} | {b['model']} | {b['horizon']} | {b['skill']:+.3f} "
                 f"[{b['ci95'][0]:+.3f}, {b['ci95'][1]:+.3f}] | {b['seed_mean']:+.3f} ± {b['seed_sd']:.3f} |")
    c2r = res["C2"]
    L += ["", "## C2 resource budget",
          (f"C2 {_yn(c2r['holds'])}: mean {c2r['cpu_core_mean']} core, max RSS {c2r['rss_mb_max']} MB, p99 step {c2r['step_ms_p99']} ms, "
           f"compression >= 60x: {'yes' if c2r['compression_ok'] else 'no'}." if c2r["measured"] else
           f"C2 not measured (no 1x run given); compression >= 60x: {'yes' if c2r['compression_ok'] else 'no'}. C2 does not hold."), ""]
    c3r = res["C3"]
    L += ["## C3 recovery", f"C3 {_yn(c3r['holds'])}. Backfill strategy taken for link-ups: {c3r['best_base_arm']}.", "",
          "| stream / event | pooled events (max) | best median (min) | pass |", "|---|---|---|---|"]
    for k, v in c3r["pairs"].items():
        m = "never" if np.isinf(v["best_median_s"]) else f"{v['best_median_s'] / 60:.1f}"
        L.append(f"| {k} | {v['events']} | {m} | {'yes' if v['pass'] else 'no'}{'' if v['events'] >= 3 else ' (too few, not judged)'} |")
    ctrl = [r for r in c3r["edge_control_at_link_ups"] if r["pass"]]
    L += ["", f"Edge control at the same link-ups: {len(ctrl)} of {len(c3r['edge_control_at_link_ups'])} (stream, horizon) rows pass.", ""]
    c4r = res["C4"]
    L += ["## C4 online vs static", f"C4 {_yn(c4r['holds'])}: lin_lag passes on " +
          (", ".join(s for s, ok in c4r["streams"].items() if ok) or "no stream") + ".", ""]
    c5r = res["C5"]
    L += ["## C5 agent lift"]
    for k in ("c5a", "c5b", "c5c"):
        v = c5r[k]
        L.append(f"- {k.upper()}: " + ("not run" if not v["run"] else _yn(v["holds"])))
    c6r = res["C6"]
    L += ["", "## C6 outage degradation (median MAE ratio base / edge)", "",
          "| arm / phase | ratio |", "|---|---|"] + [f"| {k} | {v} |" for k, v in c6r["median_ratio"].items()]
    L += ["", f"Soft target (best strategy within 10 % after the first 10 min): {'met' if c6r['soft_target_met'] else 'not met'} ({c6r['best_arm']}).", ""]
    c7r = res["C7"]
    L += ["## C7 reproducibility", "not run (no replicate pairs)" if not c7r["run"] else
          "; ".join(f"{p['runs'][0]} vs {p['runs'][1]}: hash {'equal' if p['hash_equal'] else 'DIFFERENT'}, max MAE change {p['max_mae_change']:.2%}"
                    for p in c7r["pairs"]), ""]
    L += ["## C8 integrity"] + [f"- {i['run']}: {'ok' if i['holds'] else 'VOID ' + json.dumps(i['diffs'])}" for i in res["C8"]]
    return "\n".join(L) + "\n"
