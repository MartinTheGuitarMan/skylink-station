import numpy as np

from skylink.edge.engine import Engine
from skylink.edge.models import ForgettingRidge, build
from test_engine import errors, feed


def _fit(m, f, n, seed=0):
    rng = np.random.default_rng(seed)
    for _ in range(n):
        x = {"a": float(rng.normal()), "b": float(rng.normal())}
        m.learn_one(x, f(x))


def test_forgetting_ridge_untrained_is_zero_increment():
    assert ForgettingRidge().predict_one({"a": 1.0}) == 0.0


def test_forgetting_ridge_learns_linear_target():
    m = ForgettingRidge(lam=0.9999)
    _fit(m, lambda x: 2 * x["a"] - x["b"], 3000)
    x = {"a": 0.5, "b": 0.5}
    assert abs(m.predict_one(x) - 0.5) < 0.1


def test_forgetting_follows_a_regime_change_faster_than_not_forgetting():
    def run(lam):
        m = ForgettingRidge(lam=lam)
        _fit(m, lambda x: x["a"], 4000, seed=1)
        _fit(m, lambda x: -x["a"], 600, seed=2)
        return m.predict_one({"a": 1.0, "b": 0.0})
    assert run(0.99) < -0.7          # followed the sign flip
    assert run(1.0) > 0.0            # no forgetting still remembers the old regime


def test_boost_speeds_up_forgetting_then_expires():
    m = ForgettingRidge(lam=0.9999, lam_fast=0.9)
    m.boost(3)
    _fit(m, lambda x: x["a"], 5)
    assert m.boost_left == 0


def test_stuck_sensor_does_not_blow_up_the_solver():
    m = ForgettingRidge(lam=0.99)
    for _ in range(20000):
        m.learn_one({"a": 0.0, "b": 0.0}, 0.0)
    assert np.isfinite(m.A).all() and np.isfinite(m.predict_one({"a": 1.0, "b": 1.0}))


def test_normalised_adwin_ignores_slow_variance_change_but_fires_on_a_sudden_one():
    m = build("lin_rls_vn", [5], {"day_s": 1000}, {"vn_tau": 300.0})
    rng = np.random.default_rng(3)
    fired = []
    for s in range(6000):  # error scale swells slowly 1 -> 4 (a diurnal-like swing)
        m.on_score(s, 5, abs(rng.normal()) * (1 + 3 * s / 6000))
        fired += [e for e in m.events if e[2] == "boost"]
        m.events.clear()
    slow = len(fired)
    for s in range(6000, 7000):  # error scale jumps 5x at once
        m.on_score(s, 5, abs(rng.normal()) * 20)
        fired += [e for e in m.events if e[2] == "boost"]
        m.events.clear()
    assert slow <= 3 and len(fired) - slow >= 1


def test_raw_error_adwin_fires_on_the_same_slow_swing():
    # the variant that was harmful in iteration 1 reacts to the swing the normalised one ignores
    m = build("lin_lag_adwin", [5], {"day_s": 1000}, {})
    rng = np.random.default_rng(3)
    n = 0
    for s in range(6000):
        m.on_score(s, 5, abs(rng.normal()) * (1 + 3 * s / 6000))
        n += sum(e[2] == "detected" for e in m.events)
        m.events.clear()
    assert n >= 3


def test_rls_models_learn_a_trend_in_the_engine_and_start_as_persistence():
    cfg = {"day_s": 1000, "models": ["lin_rls", "lin_rls_vn", "persistence"],
           "streams": {"temp": {"horizons": [5]}}, "arm": "t", "model": {}}
    eng = Engine(cfg, None)
    eng.configure("r", 0)
    feed(eng, 3000, lambda s: 0.01 * s + (s % 7) * 0.001)
    eng.flush()
    e = errors(eng)
    per = np.array(e[("persistence", 5)])
    for name in ("lin_rls", "lin_rls_vn"):
        lin = np.array(e[(name, 5)])
        assert abs(lin[0] - per[0]) < 1e-6
        assert lin[-500:].mean() < 0.5 * per[-500:].mean()
