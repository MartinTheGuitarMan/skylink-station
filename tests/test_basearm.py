from skylink.edge.basearm import BaseArm

CFG = {"arm": "river", "day_s": 100, "models": ["persistence"], "model": {},
       "base": {"models": ["persistence"]}, "streams": {"temp": {"horizons": [5]}}}


def batch(s0, s1, **kw):
    t = [s * 1_000_000 for s in range(s0, s1)]
    return {"run": "r", "stream": "temp", "fields": ["value"], "t": t, "v": [[float(s) for s in range(s0, s1)]], **kw}


def scenario(strategy):
    arm = BaseArm(CFG, None, strategy)
    arm.configure("r", 0)
    msgs = [batch(s, s + 10) for s in range(0, 100, 10)]
    msgs += [{"run": "r", "ctrl": "link", "up": 0, "t_us": 100_000_000},
             {"run": "r", "ctrl": "link", "up": 1, "t_us": 200_000_000},
             {"run": "r", "ctrl": "bf_start", "bf_id": 200, "n": 2},
             batch(200, 210)]                                   # live data overtakes the replay
    msgs += [batch(150, 200, bf=True, bf_id=200, bf_n=2), batch(100, 150, bf=True, bf_id=200, bf_n=2)]
    msgs += [batch(s, s + 10) for s in range(210, 300, 10)]
    for m in msgs:
        arm.on_message(m)
    arm.flush()
    return arm


def lines(arm, kind="error"):
    return [l for l in arm.engine.buf if l.startswith(kind + ",")]


def test_ignore_drops_the_replay():
    a = scenario("ignore")
    assert a.engine.streams["temp"].late_dropped > 0
    assert a.engine.streams["temp"].steps < 220          # the outage window never gets processed


def test_arrival_processes_everything_out_of_order():
    a = scenario("arrival")
    st = a.engine.streams["temp"]
    assert st.late_dropped == 0 and st.steps >= 295


def test_sorted_waits_then_replays_in_order():
    a = scenario("sorted")
    st = a.engine.streams["temp"]
    assert st.late_dropped == 0 and st.steps >= 295
    rt0 = [l for l in lines(a) if ",rt=0," in l]
    assert rt0, "replayed steps must be tagged as hindcasts"
    # persistence at h=5 on the ramp is exact in sorted order: error is always 5
    errs = {float(l.split("abs_err=")[1].split(",")[0]) for l in lines(a)}
    assert errs == {5.0}


def test_arrival_order_loses_scored_pairs():
    # a forecast is only scored when its target second arrives after it was made; out-of-order data breaks that
    assert len(lines(scenario("arrival"))) < len(lines(scenario("sorted")))


def test_phase_labels_follow_link_events():
    a = scenario("sorted")
    e = a.engine
    assert e.phase(50) == "normal" and e.phase(150) == "outage"
    assert e.phase(205) == "post" and e.phase(900) == "normal"
