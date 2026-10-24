import numpy as np

from skylink.analysis import c3_verdict, recovery_events, recovery_table, recovery_time

BIN = 60


def _err(n, base=1.0):
    return np.full(n, base), np.ones(n)


def test_recovery_is_time_until_rolling_mae_stays_under_the_bar():
    s, n = _err(200)
    t = 100 * BIN
    s[100:110] = 3.0  # 10 bins of disturbance; the 5-bin trailing window clears 5 bins later
    r = recovery_time(s, n, t, BIN, until=t + 3600)
    assert r == (114 - 100 + 1) * BIN


def test_no_disturbance_recovers_at_once_and_late_relapse_counts():
    s, n = _err(200)
    assert recovery_time(s, n, 100 * BIN, BIN, until=160 * BIN) == BIN
    s[155:160] = 3.0  # relapse at the end of the look window: never stays recovered
    assert recovery_time(s, n, 100 * BIN, BIN, until=160 * BIN) == float("inf")


def test_no_steady_state_before_the_event_is_skipped():
    s, n = _err(200)
    n[70:100] = 0
    assert recovery_time(s, n, 100 * BIN, BIN, until=160 * BIN) is None


def test_events_table_and_verdict():
    evs = [{"stream": "temp", "kind": "front", "t0": 100 * BIN, "t1": 120 * BIN},
           {"stream": "temp", "kind": "drift", "t0": 200 * BIN, "t1": 300 * BIN},
           {"stream": "temp", "kind": "stuck", "t0": 5, "t1": 9}]
    rec = recovery_events(evs, outages=[(400 * BIN, 450 * BIN)])
    assert [(e["kind"], e["t"]) for e in rec] == [("front", 6000), ("drift_end", 18000), ("outage_end", 27000)]
    fast, slow = _err(600), _err(600)
    slow[0][100:130] = 3.0  # 30 bins bad after the front: 34 min
    rows = recovery_table({("temp", "fast", 60): fast, ("temp", "slow", 60): slow}, rec, warm_s=0, stop_s=600 * BIN, bin_s=BIN)
    by = {(r["model"], r["kind"]): r for r in rows}
    assert by[("slow", "front")]["median_s"] == 35 * BIN and by[("fast", "front")]["median_s"] == BIN
    v = {r["kind"]: r for r in c3_verdict(rows)}
    assert v["front"]["model"] == "fast" and v["front"]["pass"]
    assert set(v) == {"front", "drift_end", "outage_end"}
