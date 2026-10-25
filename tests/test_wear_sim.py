import numpy as np

from skylink.sim.events import Event, StreamPlan, build_plan
from skylink.sim.streams import SPECS, StreamGen

WEAR = {"streams": ["vibration"], "count": 1, "onset_days": [3.0, 7.0], "ramp_days": [4.0, 14.0], "factor": [1.5, 3.0]}


def test_wear_is_opt_in_and_moves_no_other_event():
    base = build_plan(1, 21 * 86400, list(SPECS))
    worn = build_plan(1, 21 * 86400, list(SPECS), wear=WEAR)
    assert not any(e.kind == "wear" for e in base)
    assert [e for e in worn if e.kind != "wear"] == base
    (w,) = [e for e in worn if e.kind == "wear"]
    assert w.stream == "vibration" and 3 * 86400 <= w.t0 <= 7 * 86400
    assert 4 * 86400 <= w.aux <= 14 * 86400 and 1.5 <= w.mag <= 3.0 and w.t1 == w.t0 + w.aux
    assert worn == build_plan(1, 21 * 86400, list(SPECS), wear=WEAR)


def test_wear_leaves_the_signal_alone_until_onset_then_grows():
    plan = build_plan(4, 86400, ["vibration"], rate_scale=0.0)
    ev = Event(999, "vibration", "wear", 600.0, 1800.0, 3.0, 1200.0)
    a = StreamGen(SPECS["vibration"], 4, StreamPlan(plan, "vibration"))
    b = StreamGen(SPECS["vibration"], 4, StreamPlan(plan + [ev], "vibration"))
    xa = np.concatenate([a.block(k)["value"] for k in range(40)])
    xb = np.concatenate([b.block(k)["value"] for k in range(40)])
    hz = SPECS["vibration"].rate_hz
    assert np.array_equal(xa[:600 * hz], xb[:600 * hz])
    rms = lambda x: float(np.sqrt(np.mean(x * x)))
    late = slice(1800 * hz, 2400 * hz)  # held at F after the ramp
    assert 2.0 < rms(xb[late]) / rms(xa[late]) < 3.0  # the 0.2 Hz line and bursts do not grow
