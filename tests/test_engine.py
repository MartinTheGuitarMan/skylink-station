import re

import numpy as np

from skylink.edge.engine import Engine

CFG = {"arm": "t", "day_s": 100, "models": ["persistence", "seasonal_naive"],
       "streams": {"temp": {"horizons": [3, 10]}}}


def feed(eng, seconds, f, hz=10):
    for s in range(seconds):
        t = [s * 1_000_000 + i * (1_000_000 // hz) for i in range(hz)]
        eng.ingest("temp", t, [f(s)] * hz)


def errors(eng):
    out = {}
    for line in eng.buf:
        if line.startswith("error,"):
            m = re.match(r"error,.*model=(\w+),horizon=(\d+) err=(\S+),abs_err=([^,\s]+)", line)
            out.setdefault((m[1], int(m[2])), []).append(float(m[4]))
    return out


def test_persistence_error_on_ramp_equals_horizon():
    eng = Engine(CFG, None)
    eng.configure("r", 0)
    feed(eng, 60, lambda s: float(s))
    eng.flush()
    e = errors(eng)
    assert np.allclose(e[("persistence", 3)], 3.0)
    assert np.allclose(e[("persistence", 10)], 10.0)
    assert ("seasonal_naive", 3) not in e  # no full period of history yet


def test_seasonal_naive_exact_on_periodic_signal():
    eng = Engine(CFG, None)
    eng.configure("r", 0)
    feed(eng, 260, lambda s: float(s % 100))
    eng.flush()
    e = errors(eng)
    assert len(e[("seasonal_naive", 10)]) > 100
    assert max(e[("seasonal_naive", 10)]) < 1e-9
    assert np.mean(e[("persistence", 10)]) > 1


def test_gap_is_skipped_not_interpolated():
    eng = Engine(CFG, None)
    eng.configure("r", 0)
    for s in list(range(20)) + list(range(30, 50)):
        eng.ingest("temp", [s * 1_000_000], [float(s)])
    eng.flush()
    assert eng.streams["temp"].steps == 40


def test_late_points_are_counted_not_scored():
    eng = Engine(CFG, None)
    eng.configure("r", 0)
    eng.ingest("temp", [5_000_000], [1.0])
    eng.ingest("temp", [6_000_000], [1.0])
    eng.ingest("temp", [1_000_000], [9.0])
    eng.flush()
    assert eng.streams["temp"].late_dropped == 1


def test_direct_model_starts_as_persistence_and_learns_a_trend():
    from skylink.edge.models import build
    cfg = {"day_s": 1000, "models": ["lin_lag", "persistence"], "streams": {"temp": {"horizons": [5]}},
           "arm": "t", "model": {}}
    eng = Engine(cfg, None)
    eng.configure("r", 0)
    feed(eng, 3000, lambda s: 0.01 * s + (s % 7) * 0.001)
    eng.flush()
    e = errors(eng)
    lin, per = np.array(e[("lin_lag", 5)]), np.array(e[("persistence", 5)])
    assert abs(lin[0] - per[0]) < 1e-6          # untrained == persistence
    assert lin[-500:].mean() < 0.5 * per[-500:].mean()  # the trend is learned


def test_nonfinite_forecast_is_replaced_and_counted():
    class Bad:
        name = "bad"
        def __init__(self): pass
        def step(self, s, y, hist, x, fh):
            return {5: float("nan")}
    eng = Engine(CFG | {"models": ["persistence"], "streams": {"temp": {"horizons": [5]}}}, None)
    eng.configure("r", 0)
    st = eng.streams["temp"]
    st.models.append(Bad())
    st.pending[("bad", 5)] = __import__("collections").deque()
    feed(eng, 30, lambda s: float(s))
    eng.flush()
    assert eng.nonfinite > 0 and "nan" not in " ".join(eng.buf).lower()


def test_model_exception_is_contained_and_counted():
    class Boom:
        name = "boom"
        def step(self, s, y, hist, x, fh):
            raise ZeroDivisionError("library bug")
    eng = Engine(CFG | {"models": ["persistence"], "streams": {"temp": {"horizons": [5]}}}, None)
    eng.configure("r", 0)
    eng.streams["temp"].models.append(Boom())
    eng.streams["temp"].pending[("boom", 5)] = __import__("collections").deque()
    feed(eng, 30, lambda s: float(s))
    eng.flush()
    assert eng.stats()["model_crashes"]["temp/boom"] > 20
    assert eng.streams["temp"].steps == 30
