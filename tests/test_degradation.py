import numpy as np

from skylink import degradation as dg
from skylink.sim.events import Event


def _hours(n, level=1.0, sd=0.01, seed=0):
    return level + np.random.default_rng(seed).normal(0, sd, n)


def test_reference_arm_quiet_on_a_flat_stream():
    arm = dg.reference_arm(_hours(500), 0.001)
    assert arm["starts"] == [] and not arm["active"].any()


def test_reference_arm_flags_a_slow_ramp_and_holds_it():
    hm = _hours(504)
    hm[100:] += np.linspace(0, 0.5, 404) ** 2  # convex, like wear
    arm = dg.reference_arm(hm, 0.001)
    assert len(arm["starts"]) == 1 and arm["starts"][0] > 100
    assert arm["active"][arm["starts"][0]:].all()
    twin = dg.reference_arm(_hours(504), 0.001)
    det = dg.detection(arm, twin, 100 * 3600.0)
    assert det["detected"] and det["hold"] == 1.0 and 0 < det["delay_days"] < 404 / 24
    slow = dg.reference_arm(hm, 0.001, rebaseline=True)
    assert slow["starts"][0] >= arm["starts"][0] and slow["mu_end"] > arm["mu_end"]


def test_alert_needs_six_hours_and_ends_with_hysteresis():
    hm = _hours(200)
    hm[100:105] += 1.0           # 5 h out, then back: not enough
    hm[150:] += 1.0              # stays out
    arm = dg.reference_arm(hm, 0.001)
    assert len(arm["starts"]) == 1 and arm["starts"][0] >= 150 + 12 + 5 - 1


def test_excused_hours_and_false_alerts():
    plan = [Event(1, "pressure", "step", 72 * 3600.0, 80 * 3600.0, 3.0)]
    ex = dg.excused_hours(plan, "pressure", 200)
    assert ex[72] and ex[80 + 29] and not ex[71] and not ex[80 + 31]
    arm = {"starts": [75, 150]}
    fa = dg.false_alerts(arm, ex)
    assert fa["false"] == 1 and fa["excused_alerts"] == 1
    assert fa["healthy_days"] == (200 - 48 - ex[48:].sum()) / 24


def test_hourly_median_needs_half_an_hour():
    y = np.ones(3 * 3600)
    y[3600:3600 + 1801] = np.nan
    hm = dg.hourly_medians(y)
    assert hm[0] == 1.0 and np.isnan(hm[1]) and hm[2] == 1.0
