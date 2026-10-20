import math

from skylink.edge.models import ClearSkyShape, build

DAY = 86400


def test_shape_forecast_follows_the_clear_sky_ramp():
    m = ClearSkyShape([300], {}, {"p": 1.0})
    s = 9 * 3600  # morning, sun rising
    ratio = math.cos(2 * math.pi * (s + 300 - 43200) / DAY) / math.cos(2 * math.pi * (s - 43200) / DAY)
    assert abs(m.step(s, 100.0, None, None, None)[300] - 100.0 * ratio) < 1e-9
    assert m.step(s, 100.0, None, None, None)[300] > 100.0


def test_shape_forecast_is_persistence_at_night_and_ratio_is_capped():
    m = ClearSkyShape([60, 300], {}, {})
    assert m.step(2 * 3600, 3.0, None, None, None) == {60: 3.0, 300: 3.0}
    # shortly after the floor is crossed the raw ratio would explode; it is capped
    s = int(43200 - 0.25 * DAY + 600)
    out = m.step(s, 10.0, None, None, None)
    assert out[300] <= 10.0 * m.max_ratio + 1e-9


def test_cloud_scales_the_ramp_it_does_not_replace_it():
    m = ClearSkyShape([300], {}, {})
    s = 9 * 3600
    assert abs(m.step(s, 20.0, None, None, None)[300] / m.step(s, 100.0, None, None, None)[300] - 0.2) < 1e-9


def test_registered_in_build():
    assert build("clearsky_shape", [5], {}, {}).name == "clearsky_shape"


def test_adaptive_noon_follows_a_phase_shift():
    m = build("clearsky_adapt", [60], {}, {})
    assert m.name == "clearsky_adapt"
    for d in range(6):  # a bell centred at 14:00 every day
        for s in range(0, DAY, 30):
            t = d * DAY + s
            m.step(t, max(0.0, 500 * math.cos(2 * math.pi * (s - 14 * 3600) / DAY)), None, None, None)
    assert abs(m.noon - 14 * 3600) < 600


def test_robust_residual_learners_are_registered_and_start_as_the_shape_forecast():
    import pytest
    for name in ("lin_cs_huber", "lin_cs_quant"):
        m = build(name, [60], {}, {})
        ref = build("clearsky_adapt", [60], {}, {})
        s = 9 * 3600
        a = m.step(s, 50.0, {}, {"a": 1.0}, {})[60]
        assert a == pytest.approx(ref.step(s, 50.0, None, None, None)[60])  # nothing learned yet: residual is 0


def test_scaled_robust_ignores_outliers_where_squared_loss_would_not():
    from skylink.edge.models import ScaledRobust
    import random
    random.seed(0)
    m = ScaledRobust("huber", lr=0.01)
    for i in range(6000):
        x = {"a": random.gauss(0, 1)}
        y = 10.0 + (5000.0 if i % 50 == 0 else 0.0)  # constant target with a 2 % huge outlier
        m.learn_one(x, y)
    assert m.predict_one({"a": 0.0}) < 400.0  # the median is 10; a mean-fitter lands near 110
