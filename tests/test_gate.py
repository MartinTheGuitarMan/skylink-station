import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def gate(**kw):
    inp = {"seed": 1, "seconds": 3000, "hz": 10, "cfg": {"mean_up_s": 60, "mean_down_s": 40,
           "backfill_chunk_points": 100, "backfill_shuffle_window": 6, "max_buffer_points": 10**9}} | kw
    out = subprocess.run(["node", str(ROOT / "tests/gate_harness.mjs")], input=json.dumps(inp),
                         capture_output=True, text=True, check=True, cwd=ROOT).stdout
    return json.loads(out)


def test_schedule_deterministic_and_seeded():
    a, b, c = gate(), gate(), gate(seed=2)
    assert a["trace"] == b["trace"] and len(a["trace"]) > 6
    assert a["trace"] != c["trace"]


def test_point_accounting_c8():
    r = gate()
    n = r["n"]
    assert n["in"] == r["emitted"]
    assert n["live"] + n["buffered"] == n["in"]
    assert n["buffered"] == n["backfilled"] + n["dropped"] + r["bufPts"]
    assert r["bfOut"] == n["backfilled"] and n["dropped"] == 0
    assert n["outages"] > 2


def test_backfill_is_out_of_order():
    r = gate()
    order = r["backfillOrder"]
    assert len(order) > 10 and order != sorted(order)


def test_overflow_drops_oldest_and_is_counted():
    r = gate(cfg={"mean_up_s": 30, "mean_down_s": 400, "backfill_chunk_points": 100,
                  "backfill_shuffle_window": 4, "max_buffer_points": 500})
    n = r["n"]
    assert n["dropped"] > 0
    assert n["buffered"] == n["backfilled"] + n["dropped"] + r["bufPts"]


def test_resume_reproduces_schedule():
    full = gate(seconds=2000)
    first = gate(seconds=1000)
    tail = gate(seconds=1000, resume_s=1000)
    t = lambda tr: [x for x in tr]
    cut = [x for x in full["trace"] if float(x.split("@")[1]) > 1000]
    assert t(tail["trace"]) == cut
