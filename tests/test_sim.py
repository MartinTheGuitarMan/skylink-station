import json

import numpy as np

from skylink.sim.events import build_plan
from skylink.sim.replay import load_cfg, make_gens, stream_hash
from skylink.sim.streams import BLOCK_S, SPECS

CFG = "config/scenario-default.toml"


def test_plan_is_deterministic_and_seed_sensitive():
    a = build_plan(1, 3 * 86400, list(SPECS))
    assert a == build_plan(1, 3 * 86400, list(SPECS))
    assert a != build_plan(2, 3 * 86400, list(SPECS))
    # adding a stream must not change another stream's events
    only = build_plan(1, 3 * 86400, ["temp"])
    assert [e for e in a if e.stream == "temp"] == only


def test_stream_hash_reproducible():
    cfg = load_cfg(CFG, seed=7)
    assert stream_hash(cfg, 1800) == stream_hash(cfg, 1800)
    assert stream_hash(cfg, 1800) != stream_hash(load_cfg(CFG, seed=8), 1800)


def test_blocks_are_independent_of_batching():
    cfg = load_cfg(CFG, seed=3)
    g1, _ = make_gens(cfg)
    g2, _ = make_gens(cfg)
    for k in range(5):
        for s in g1:
            a, b = g1[s].block(k), g2[s].block(k)
            assert np.array_equal(a["value"], b["value"])


def test_physical_sanity():
    cfg = load_cfg(CFG, seed=1, days=2)
    cfg["run"]["fault_rate_scale"] = 0.0
    gens, _ = make_gens(cfg)
    n = 24 * 60  # one day of blocks
    vals = {s: np.concatenate([g.block(k)["value"] for k in range(n)]) for s, g in gens.items()}
    assert -25 < vals["temp"].min() and vals["temp"].max() < 15
    assert 960 < vals["pressure"].min() and vals["pressure"].max() < 1060
    assert vals["wind"].min() >= 0 and vals["wind"].max() > 3 * np.median(vals["wind"])  # heavy tail
    assert vals["solar"].min() >= 0 and vals["solar"].max() > 300
    assert 0.5 < vals["vibration"].std() < 3


def test_dropout_removes_points_and_stuck_holds():
    cfg = load_cfg(CFG, seed=5, days=2)
    cfg["run"]["fault_rate_scale"] = 10.0
    cfg["run"]["streams"] = ["temp"]
    gens, plan = make_gens(cfg)
    g = gens["temp"]
    dropped = 0
    for k in range(24 * 60):
        b = g.block(k)
        dropped += int((~b["valid"]).sum())
    assert any(e.kind == "dropout" for e in plan) and dropped > 0
    stuck = next(e for e in plan if e.kind == "stuck")
    g2 = make_gens(cfg)[0]["temp"]
    k0 = int(stuck.t0 // BLOCK_S)
    for k in range(k0 + 1):
        b = g2.block(k)
    m = (b["t"] >= stuck.t0) & (b["t"] < stuck.t1)
    if m.sum() > 2:
        assert np.ptp(b["value"][m]) < 1e-9


def _replay(tmp_path, monkeypatch, run_id, free_gb, resume=False):
    """Run the replay offline (stub Influx and HTTP) on 0.01 days; free_gb(call number) is the disk's free space."""
    import argparse
    import types

    from skylink.sim import replay

    class Http:
        def __init__(self, **_): pass
        def post(self, *_, **__): return types.SimpleNamespace(raise_for_status=lambda: None)

    calls = iter(range(10**6))
    monkeypatch.setattr(replay.httpx, "Client", Http)
    monkeypatch.setattr(replay, "Influx", lambda: types.SimpleNamespace(write=lambda *_: None))
    monkeypatch.setattr(replay.shutil, "disk_usage", lambda _: types.SimpleNamespace(free=free_gb(next(calls)) * 2**30))
    args = argparse.Namespace(config="config/scenario-default.toml", run_id="r", seed=1, days=0.01, speed=0, until=None,
                              nodered="http://x", edge="", runs_dir=str(tmp_path / run_id), resume=resume, min_free_gb=10)
    assert replay.run(args) == 0
    return json.loads((tmp_path / run_id / "r/summary.json").read_text())


def test_low_disk_stops_at_a_block_boundary_and_resume_keeps_the_chain_hash(tmp_path, monkeypatch):
    whole = _replay(tmp_path, monkeypatch, "whole", lambda _: 500)
    assert whole["finished"]
    cut = _replay(tmp_path, monkeypatch, "cut", lambda i: 500 if i < 5 else 5)
    assert not cut["finished"] and cut["next_block"] == 5
    resumed = _replay(tmp_path, monkeypatch, "cut", lambda _: 500, resume=True)
    assert resumed["finished"] and resumed["hash"] == whole["hash"] and resumed["emitted"] == whole["emitted"]
