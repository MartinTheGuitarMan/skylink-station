#!/usr/bin/env python3
"""Closed-loop model-switch bench (C5b), offline, DEV seeds only: fixed vs rules vs agent twins on the same data.

All candidate models run all the time; each arm only chooses which one is *served*. The agent's decision
takes effect after its measured latency (wall seconds x speed, default 60x, in event seconds).

    uv run --extra agent python scripts/agent_proposals.py --seed 1 --days 3 --streams temp,wind \
        --models e4b=google/gemma-4-e4b [--fake]
"""
import argparse
import datetime as dt
import json
import sys
import time
import tomllib
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

from skylink.agent.guard import Switchboard, Trailing
from skylink.agent.jobs import ALLOWED_MODELS, Agent, CallLog, c5b_check, summarise_log
from skylink.agent.minions import FakeTransport, MinionsClient
from skylink.edge.engine import Engine
from skylink.sim.replay import load_cfg, make_gens, window_end
from skylink.sim.streams import BLOCK_S, SPECS, to_points

CANDS = ["lin_lag", "lin_lag_static", "holt", "persistence", "hat"]
DECIDE_S = 3600


def context(key, board, trail, now):
    stream, h = key
    lines = [f"stream: {stream}", f"horizon_s: {h}", f"current_model: {board.served(key)} "
             f"(served for {(now - board.slot(key).since) // 60} min)", "recent_mean_abs_error_last_30_min:"]
    for m in CANDS:
        v = trail[(stream, h, m)].mae()
        lines.append(f"- {m}: {'n/a' if v is None else round(v, 4)}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("--warmup-days", type=float, default=1)
    ap.add_argument("--streams", default="temp,wind")
    ap.add_argument("--models", default="")
    ap.add_argument("--fake", action="store_true", help="scripted agent (plumbing only)")
    ap.add_argument("--speed", type=float, default=60)
    ap.add_argument("--out", default="runs/agent/proposals")
    ap.add_argument("--until", help="stop at this Europe/Stockholm clock time, e.g. 06:00; no result is written (exit 3)")
    a = ap.parse_args()
    deadline = window_end(a.until)
    assert not 100 < a.seed < 106, "locked seeds are not for development"
    cfg = tomllib.load(open("config/edge.toml", "rb"))
    streams = a.streams.split(",")
    horizons = {"temp": [600], "wind": [30], "pressure": [600], "vibration": [30], "solar": [60]}
    cfg["streams"] = {s: {"horizons": horizons[s]} for s in streams}
    cfg["models"] = CANDS
    cfg["model"]["lin_lag_static"]["static_after"] = int(a.warmup_days * 86400)
    sc = load_cfg("config/scenario-default.toml", seed=a.seed, days=a.days)
    sc["run"]["streams"] = streams
    gens, _ = make_gens(sc)
    eng = Engine(cfg, None)
    eng.configure("prop", 0)

    arms = {"fixed": None, "rules": "rules"}
    clients = {}
    for spec in [x for x in a.models.split(",") if x]:
        name, model = spec.split("=", 1)
        arms[f"agent:{name}"] = name
        backend, model = ("ollama", model[7:]) if model.startswith("ollama:") else ("lmstudio", model)
        clients[name] = MinionsClient(model, backend=backend, name=name, timeout_s=300) if not a.fake else None
    if a.fake:
        arms["agent:fake"] = "fake"
        clients["fake"] = FakeTransport(lambda t, args: {"action": "switch", "model": "hat", "reason": "scripted"}, name="fake")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    boards = {k: Switchboard("lin_lag", CANDS) for k in arms}
    agents = {k: Agent(clients[arms[k]], CallLog(out / f"{arms[k]}.jsonl")) for k in arms if k.startswith("agent:")}
    trail = defaultdict(lambda: Trailing(1800))
    pre = defaultdict(lambda: Trailing(600))
    served = {k: defaultdict(lambda: defaultdict(lambda: [0, 0.0])) for k in arms}   # arm -> (stream,h) -> hour -> [n, sum]
    pending = []   # (apply_at_s, arm, key, model)
    stats = defaultdict(lambda: defaultdict(int))
    next_decide = {}
    warm = a.warmup_days * 86400

    def hook(stream, model, h, s, y, yhat, yp):
        err = abs(yhat - y)
        trail[(stream, h, model)].add(s, err)
        key = (stream, h)
        for arm, board in boards.items():
            if board.served(key) == model and s >= warm:
                r = served[arm][key][s // 3600]
                r[0] += 1; r[1] += err
            if board.served(key) == model:
                pre[(arm, key)].add(s, err)
                if board.check_rollback(key, s, pre[(arm, key)].mae()):
                    stats[arm]["rollbacks"] += 1
        for item in [p for p in pending if p[0] <= s]:
            pending.remove(item)
            _, arm, k, m, call = item
            ok, why = boards[arm].propose(k, m, s, {c: trail[(k[0], k[1], c)].mae() for c in CANDS}, "agent")
            agents[arm].log.verdict(call, ok, why)
            stats[arm]["accepted" if ok else "rejected"] += 1
        if s >= next_decide.setdefault(key, warm - 7200 + (sum(map(ord, str(key))) % 600)) and model == "lin_lag":
            next_decide[key] = s + DECIDE_S
            tr = {c: trail[(stream, h, c)].mae() for c in CANDS}
            # rules twin: best trailing MAE if clearly better than the incumbent
            cur = tr.get(boards["rules"].served(key))
            best = min((c for c in CANDS if tr[c] is not None), key=lambda c: tr[c], default=None)
            if best and cur and best != boards["rules"].served(key) and tr[best] < 0.9 * cur:
                ok, _ = boards["rules"].propose(key, best, s, tr, "rules")
                stats["rules"]["accepted" if ok else "rejected"] += 1
            for arm, ag in agents.items():
                o = ag.propose(context(key, boards[arm], trail, s))
                stats[arm]["calls"] += 1
                stats[arm]["lat_ms_sum"] += int(o.reply.latency_ms)
                if not o.valid:
                    stats[arm]["invalid"] += 1
                elif o.value["action"] == "switch":
                    pending.append((s + int(o.reply.latency_ms / 1000 * a.speed), arm, key, o.value["model"], o.call))

    eng.hook = hook
    t0 = time.time()
    for k in range(int(a.days * 86400 // BLOCK_S)):
        if deadline and dt.datetime.now(deadline.tzinfo) >= deadline:
            for c in clients.values():
                c.close()
            done = round(k * BLOCK_S / 86400, 2)
            (out / "cut.json").write_text(json.dumps({"until": a.until, "days_done": done, "days": a.days,
                                                      "wall_s": round(time.time() - t0), "stats": {x: dict(v) for x, v in stats.items()}}))
            print(f"cut at {a.until}: {done} of {a.days} days done, no result (the bench has no checkpoint)")
            sys.exit(3)
        for st, g in gens.items():
            blk = g.block(k)
            p = to_points(SPECS[st], blk, 0, len(blk["t"]), 0)
            if p["t"]:
                eng.ingest(st, p["t"], p["v"][0])
        eng.buf.clear()
    for c in clients.values():
        c.close()
    # report: MAE served per arm, paired by hour against fixed
    rng, rows = np.random.default_rng(0), []
    for key in sorted(served["fixed"]):
        hours = sorted(served["fixed"][key])
        f = np.array([served["fixed"][key][h] for h in hours])
        for arm in arms:
            x = np.array([served[arm][key][h] for h in hours])
            mae = x[:, 1].sum() / max(x[:, 0].sum(), 1)
            idx = rng.integers(0, len(hours), (2000, len(hours)))
            ratio = (x[idx, 1].sum(1) / np.maximum(x[idx, 0].sum(1), 1)) / np.maximum(f[idx, 1].sum(1) / np.maximum(f[idx, 0].sum(1), 1), 1e-12)
            rows.append({"stream": key[0], "h": key[1], "arm": arm, "mae": round(float(mae), 4),
                         "ratio_vs_fixed": round(float(x[:, 1].sum() / x[:, 0].sum() / (f[:, 1].sum() / f[:, 0].sum())), 4),
                         "ci": [round(float(np.percentile(ratio, 2.5)), 3), round(float(np.percentile(ratio, 97.5)), 3)],
                         "switches": boards[arm].slot(key).switches})
    per_hour = {f"{k[0]}/{k[1]}": {arm: {str(h): [float(v) for v in served[arm][k][h]] for h in served[arm][k]} for arm in arms}
                for k in served["fixed"]}
    res = {"rows": rows, "hours": per_hour, "stats": {k: dict(v) for k, v in stats.items()}, "wall_s": round(time.time() - t0)}
    (out / "result.json").write_text(json.dumps(res, indent=1))
    print("| stream | h | arm | MAE | ratio vs fixed | 95% CI | switches |\n|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['stream']} | {r['h']} | {r['arm']} | {r['mae']} | {r['ratio_vs_fixed']} | {r['ci']} | {r['switches']} |")
    print(json.dumps(res["stats"]))
    for arm in arms:
        if arm.startswith("agent:") or arm == "rules":
            print("C5b", json.dumps(c5b_check(rows, arm, hours=per_hour)))
    for arm in agents:
        print("C5c", arm, json.dumps(summarise_log(out / f"{arms[arm]}.jsonl")))


if __name__ == "__main__":
    main()
