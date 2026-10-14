"""Seedable, time-compressed, resumable replay: simulator -> Node-RED.

    skylink-sim run --config config/scenario-default.toml --run-id r1 --speed 60
    skylink-sim hash --config ... --seconds 3600       # reproducibility check, no network
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import signal
import sys
import time
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np

from ..influx import Influx, esc_tag
from .events import StreamPlan, build_plan
from .streams import BLOCK_S, SPECS, StreamGen, to_points


def load_cfg(path: str, seed: int | None = None, days: float | None = None) -> dict:
    cfg = tomllib.loads(Path(path).read_text())
    if seed is not None:
        cfg["run"]["seed"] = seed
    if days is not None:
        cfg["run"]["duration_days"] = days
    return cfg


def epoch_us(cfg: dict) -> int:
    return int(dt.datetime.fromisoformat(cfg["run"]["epoch"].replace("Z", "+00:00")).timestamp() * 1_000_000)


def make_gens(cfg: dict) -> tuple[dict[str, StreamGen], list]:
    r = cfg["run"]
    duration_s = r["duration_days"] * 86400.0
    plan = build_plan(r["seed"], duration_s, r["streams"], r.get("fault_rate_scale", 1.0))
    gens = {s: StreamGen(SPECS[s], r["seed"], StreamPlan(plan, s)) for s in r["streams"]}
    return gens, plan


def _chain(prev: bytes, stream: str, blk: dict, spec) -> bytes:
    h = hashlib.sha256(prev)
    h.update(stream.encode())
    m = blk["valid"]
    h.update(np.rint(blk["t"][m] * 1e6).astype(np.int64).tobytes())
    for f in spec.fields:
        h.update(np.round(blk[f][m], 4).tobytes())
    return h.digest()


def stream_hash(cfg: dict, seconds: float) -> str:
    gens, _ = make_gens(cfg)
    chain = b""
    for k in range(int(seconds // BLOCK_S)):
        for s, g in gens.items():
            chain = _chain(chain, s, g.block(k), g.spec)
    return chain.hex()


def truth_lines(run_id: str, plan, e_us: int) -> list[str]:
    out = []
    for e in plan:
        out.append(
            f"truth_event,run={esc_tag(run_id)},stream={e.stream},kind={e.kind} "
            f"id={e.id}i,t1_us={e_us + int(e.t1 * 1e6)}i,mag={e.mag},aux={e.aux} {e_us + int(e.t0 * 1e6)}"
        )
    return out


def window_end(spec: str | None) -> dt.datetime | None:
    """'06:00' -> next 06:00 in Europe/Stockholm."""
    if not spec:
        return None
    now = dt.datetime.now(ZoneInfo("Europe/Stockholm"))
    hh, mm = map(int, spec.split(":"))
    end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return end if end > now else end + dt.timedelta(days=1)


def run(args: argparse.Namespace) -> int:
    cfg = load_cfg(args.config, args.seed, args.days)
    r = cfg["run"]
    run_id = args.run_id
    out_dir = Path(args.runs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "checkpoint.json"
    e_us = epoch_us(cfg)
    gens, plan = make_gens(cfg)
    batch_s = r.get("batch_s", 10)
    assert BLOCK_S % batch_s == 0, "batch_s must divide 60"
    total_blocks = int(r["duration_days"] * 86400 // BLOCK_S)

    ck = {"next_block": 0, "chain": "", "emitted": {s: 0 for s in gens}}
    resumed = args.resume and ckpt_path.exists()
    if resumed:
        ck = json.loads(ckpt_path.read_text())
    influx = Influx()
    if not resumed:
        (out_dir / "events.jsonl").write_text("".join(json.dumps(e.to_dict()) + "\n" for e in plan))
        (out_dir / "config.json").write_text(json.dumps(cfg, indent=1))
        lines = truth_lines(run_id, plan, e_us)
        for i in range(0, len(lines), 5000):
            influx.write("raw", lines[i : i + 5000])

    http = httpx.Client(timeout=60)
    sky = dict(cfg.get("skylink", {}))
    http.post(f"{args.nodered}/config", json={
        "run": run_id, "seed": r["seed"], "epoch_us": e_us, "resume_s": ck["next_block"] * BLOCK_S,
        "fields": {s: list(g.spec.fields) for s, g in gens.items()}, **sky,
    }).raise_for_status()
    if args.edge:
        http.post(f"{args.edge}/config", json={"run": run_id, "epoch_us": e_us}).raise_for_status()

    for k in range(ck["next_block"]):  # fast-forward: regenerate to restore generator state
        for g in gens.values():
            g.block(k)

    stop = {"flag": False}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.update(flag=True))
    deadline = window_end(args.until)
    wall0, t_start = time.monotonic(), ck["next_block"] * BLOCK_S
    chain = bytes.fromhex(ck["chain"])
    posted = 0
    for k in range(ck["next_block"], total_blocks):
        if stop["flag"] or (deadline and dt.datetime.now(deadline.tzinfo) >= deadline):
            break
        blocks = {s: g.block(k) for s, g in gens.items()}
        per = {s: SPECS[s].rate_hz * batch_s for s in gens}
        for b in range(BLOCK_S // batch_s):
            for s, blk in blocks.items():
                pts = to_points(SPECS[s], blk, b * per[s], (b + 1) * per[s], e_us)
                if not pts["t"]:
                    continue
                payload = {"run": run_id, "stream": s, "fields": list(SPECS[s].fields), **pts}
                http.post(f"{args.nodered}/ingest", json=payload).raise_for_status()
                ck["emitted"][s] += len(pts["t"])
                posted += 1
        for s, blk in blocks.items():
            chain = _chain(chain, s, blk, SPECS[s])
        ck.update(next_block=k + 1, chain=chain.hex())
        ckpt_path.write_text(json.dumps(ck))
        if args.speed > 0:
            lag = wall0 + ((k + 1) * BLOCK_S - t_start) / args.speed - time.monotonic()
            if lag > 0:
                time.sleep(lag)
        elif k % 60 == 0:
            print(f"block {k + 1}/{total_blocks}", file=sys.stderr, flush=True)
    done = ck["next_block"] >= total_blocks
    summary = {"run": run_id, "finished": done, "next_block": ck["next_block"], "hash": ck["chain"],
               "emitted": ck["emitted"], "posts": posted}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="skylink-sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--config", default="config/scenario-default.toml")
    p.add_argument("--run-id", required=True)
    p.add_argument("--seed", type=int)
    p.add_argument("--days", type=float)
    p.add_argument("--speed", type=float, default=1.0, help="event seconds per wall second; 0 = unpaced")
    p.add_argument("--nodered", default="http://localhost:1880")
    p.add_argument("--edge", default="http://localhost:8000")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--until", help="stop cleanly at this Europe/Stockholm clock time, e.g. 06:00")
    h = sub.add_parser("hash")
    h.add_argument("--config", default="config/scenario-default.toml")
    h.add_argument("--seed", type=int)
    h.add_argument("--seconds", type=float, default=3600)
    a = ap.parse_args()
    if a.cmd == "hash":
        print(stream_hash(load_cfg(a.config, a.seed), a.seconds))
        return 0
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
