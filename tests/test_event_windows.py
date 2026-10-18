import numpy as np

from skylink.analysis import c4_verdict, change_windows, compare_windows, event_window_table

DAY = 86400


def ev(stream, kind, t0, t1):
    return {"stream": stream, "kind": kind, "t0": t0, "t1": t1}


def test_windows_start_at_onset_and_end_and_skip_other_kinds():
    w = change_windows([ev("temp", "step", 10000, 20000), ev("temp", "stuck", 5000, 5600), ev("wind", "gust", 1, 9)],
                       warm_s=0, stop_s=DAY)
    assert w[("temp", "step")] == [(10000, 13600)]
    assert w[("temp", "step_end")] == [(20000, 23600)]
    assert ("temp", "stuck") not in w and ("wind", "gust") not in w


def test_windows_clip_to_scored_range():
    w = change_windows([ev("temp", "front", 100, 200), ev("temp", "front", DAY - 100, DAY + 5)], warm_s=1000, stop_s=DAY)
    assert w[("temp", "front")] == [(1000, 3700), (DAY - 100, DAY)]  # first clipped at warm-up, second at the run end


def _flat(n, v):
    return np.full(n, v), np.ones(n)


def test_reduction_is_one_minus_mae_ratio():
    wins = [(100, 160), (400, 460)]
    r = compare_windows(_flat(1000, 0.5), _flat(1000, 1.0), wins, 1)
    assert abs(r["reduction"] - 0.5) < 1e-9 and r["events"] == 2


def test_gain_only_in_windows_separates_windows_from_stationary():
    n = 3 * DAY
    stat_s, stat_n = _flat(n, 1.0)
    onl_s, onl_n = _flat(n, 1.0)
    onl_s = onl_s.copy()
    events = [ev("temp", "step", d * DAY + 3600, d * DAY + 7200) for d in (1, 2)]
    for e in events:  # online is 40 % better in the hour after each onset only
        onl_s[int(e["t0"]):int(e["t0"]) + 3600] = 0.6
    series = {("temp", "online", 60): (onl_s, onl_n), ("temp", "lin_lag_static", 60): (stat_s, stat_n)}
    rows = event_window_table(series, events, "lin_lag_static", warm_s=DAY, stop_s=n, bin_s=1)
    by = {r["kind"]: r for r in rows}
    assert abs(by["step"]["reduction"] - 0.4) < 1e-9
    assert abs(by["stationary"]["reduction"]) < 1e-9
    assert by["step"]["events"] == 2
    v = c4_verdict(rows)
    assert len(v) == 1 and v[0]["pass"]


def test_verdict_fails_when_online_loses_in_stationary_bins():
    n = 3 * DAY
    events = [ev("temp", "step", DAY + 3600, DAY + 7200)]
    onl_s, onl_n = _flat(n, 1.1)  # 10 % worse everywhere, except far better in the window
    onl_s = onl_s.copy()
    onl_s[DAY + 3600:DAY + 7200] = 0.5
    series = {("temp", "online", 60): (onl_s, onl_n), ("temp", "lin_lag_static", 60): _flat(n, 1.0)}
    v = c4_verdict(event_window_table(series, events, "lin_lag_static", DAY, n, 1))
    assert v[0]["change_reduction"] > 0.15 and v[0]["stationary_reduction"] < -0.03 and not v[0]["pass"]
