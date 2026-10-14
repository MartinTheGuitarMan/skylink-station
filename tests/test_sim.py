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
