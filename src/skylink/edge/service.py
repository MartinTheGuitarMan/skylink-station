"""HTTP front for the edge engine. Node-RED posts the local sensor tap to /edge/ingest and the
post-Skylink stream to /base/ingest. Resource samples go to the metrics bucket."""
from __future__ import annotations

import os
import threading
import time
import tomllib

import psutil
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from ..influx import Influx
from .basearm import BaseArm
from .engine import Engine


class Cfg(BaseModel):
    run: str
    epoch_us: int


class Batch(BaseModel):
    run: str
    stream: str = ""
    fields: list[str] = []
    t: list[int] = []
    v: list[list[float]] = []
    ctrl: str | None = None   # link | bf_start (labelling and link-layer notices)
    up: int | None = None
    t_us: int | None = None
    bf: bool = False          # backfill chunk
    bf_id: int | None = None
    bf_n: int | None = None
    n: int | None = None


def build_app(cfg_path: str | None = None, influx: Influx | None = None):
    cfg = tomllib.load(open(cfg_path or os.environ.get("EDGE_CONFIG", "config/edge.toml"), "rb"))
    eng = Engine(cfg, influx)
    bases = [BaseArm(cfg, influx, s) for s in cfg.get("base", {}).get("strategies", [])]
    app = FastAPI(title="skylink-edge")

    @app.post("/config")
    def config(c: Cfg):
        eng.configure(c.run, c.epoch_us)
        for b in bases:
            b.configure(c.run, c.epoch_us)
        return {"ok": True}

    @app.post("/edge/ingest")
    def edge(b: Batch):
        if b.run == eng.run:
            eng.ingest(b.stream, b.t, b.v[0])
        return {"n": len(b.t)}

    @app.post("/base/ingest")
    def base(b: Batch):
        if b.run != eng.run:
            return {"n": 0}
        if b.ctrl == "link":  # label for phases; the edge arm is scored by phase too
            eng.set_link(b.up, (b.t_us - eng.epoch_us) // 1_000_000)
        if b.t:
            eng.ingest_base(b.t)
        for arm in bases:
            arm.on_message(b.model_dump())
        return {"n": len(b.t)}

    @app.post("/flush")
    def flush():
        eng.flush()
        for b in bases:
            b.flush()
        return {**eng.stats(), "base_arms": {b.engine.cfg["arm"]: b.engine.stats()["steps"] for b in bases}}

    @app.get("/stats")
    def stats():
        return {**eng.stats(), "base_arms": {b.engine.cfg["arm"]: b.engine.stats()["steps"] for b in bases}}

    @app.get("/health")
    def health():
        return {"ok": True}

    return app, eng


def _sampler(eng: Engine, influx: Influx, period: float = 5.0) -> None:
    proc = psutil.Process()
    proc.cpu_percent(None)
    while True:
        time.sleep(period)
        try:
            s = eng.stats()
            if not eng.max_event_us:
                continue
            tags = f"run={eng.run},arm={s['arm']}"
            cost = [f"model_cost,{tags},stream={k.split('/')[0]},model={k.split('/')[1]} us_per_step={v} {eng.max_event_us}"
                    for k, v in s["cost_us_per_step"].items()]
            influx.write("metrics", cost + [
                f"resource,{tags} cpu_pct={proc.cpu_percent(None)},rss_mb={proc.memory_info().rss / 1e6},"
                f"step_ms_p50={s['step_ms_p50']},step_ms_p99={s['step_ms_p99']},"
                f"steps={sum(s['steps'].values())}i,buffered_lines={s['buffered_lines']}i {eng.max_event_us}",
                f"base_arrival,{tags} n={s['base']['n']}i,late_n={s['base']['late']}i,"
                f"max_lag_s={s['base']['max_lag_us'] / 1e6} {eng.max_event_us}",
            ])
        except Exception as e:
            print("sampler:", e, flush=True)


def main() -> None:
    influx = Influx()
    app, eng = build_app(influx=influx)
    threading.Thread(target=_sampler, args=(eng, influx), daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="warning")


if __name__ == "__main__":
    main()
