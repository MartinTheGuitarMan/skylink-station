import jsonschema
import numpy as np

from skylink.agent import review
from skylink.agent.review import Alert, Window


def _hs(**kw):
    h = {"event_time_z_at_alert": 9.0, "seconds_beyond_4_sigma_from_alert": 6, "level_after_10s_z": 0.0,
         "level_after_1min_z": 0.0, "level_after_10min_z": 0.0, "offset_after_30min_vs_typical_30min_change": None,
         "offset_after_2h_vs_typical_2h_change": None, "identical_value_run_s": 0,
         "missing_seconds_from_1min_before_to_5min_after": 0, "alert_second_inside_uplink_outage": "no"}
    return {**h, **kw}


def _window():
    al = [Alert("A1", "c1", "wind", 100, "jump", "sensor_fault", {"onset_z": 12.5}, _hs(event_time_z_at_alert=14.0)),
          Alert("A2", "c2", "vibration", 400, "jump", "real_event", {"onset_z": 9.1}, _hs()),
          Alert("A3", "c3", "temp", 2000, "jump", "backfill_artefact", {"onset_z": 8.4}, _hs(event_time_z_at_alert=0.4))]
    return Window("s3-w007", 3, 7 * 3600, [(1500, 1900)], al)


def test_hindsight_spike_and_flat():
    rng = np.random.default_rng(0)
    y = 10 + rng.normal(0, 0.1, 4000)
    y[1000] = 15.0                       # one-second spike
    y[2000:2300] = 10.0                  # stuck
    h = review.hindsight(y, 1000, "temp", [])
    assert h["seconds_beyond_4_sigma_from_alert"] == 1 and h["event_time_z_at_alert"] > 20
    assert review.hindsight(y, 2200, "temp", [(2100, 2500)])["identical_value_run_s"] == 300
    assert review.hindsight(y, 2200, "temp", [(2100, 2500)])["alert_second_inside_uplink_outage"] == "yes"


def test_rules_r1_branches():
    w = _window()
    assert [review.rules_r1(a) for a in w.alerts] == ["sensor_fault", "real_event", "backfill_artefact"]
    flat = Alert("A9", "c", "solar", 0, "flat", "sensor_fault", {}, _hs(identical_value_run_s=200, event_time_z_at_alert=0.0))
    spike = Alert("A9", "c", "temp", 0, "jump", "sensor_fault", {}, _hs(seconds_beyond_4_sigma_from_alert=1))
    assert review.rules_r1(flat) == "sensor_fault" and review.rules_r1(spike) == "sensor_fault"


def test_summary_check():
    w = _window()
    labels = {"A1": "sensor_fault", "A2": "real_event", "A3": "backfill_artefact"}
    assert review.summary_check(w, "Wind sensor fault (A1) at t=100; outage 1500 to 1900; 1 artefact.", labels, ["wind"])[0]
    assert not review.summary_check(w, "Wind fault A1 lasted 42 s.", labels, ["wind"])[0]          # invented number
    assert not review.summary_check(w, "Wind fault A7.", labels, ["wind"])[0]                       # unknown alert id
    assert not review.summary_check(w, "word " * 81, labels, [])[0]
    assert review.summary_check(w, review.template_summary(w, labels), labels, ["wind"])[0]


def test_schema_and_model_reports():
    w = _window()
    data = {"labels": [{"id": "A1", "cause": "sensor_fault"}, {"id": "A2", "cause": "real_event"},
                       {"id": "A3", "cause": "backfill_artefact"}], "fault_streams": ["wind"], "summary": "Wind fault A1."}
    jsonschema.validate(data, review.report_schema(w))
    r = review.from_model(w, "m/r3", data, 1.0)
    assert r.valid and r.summary_ok and r.labels["A3"] == "backfill_artefact"
    base = {a.aid: review.rules_r1(a) for a in w.alerts}
    over = {"overrides": [{"id": "A2", "cause": "sensor_fault", "reason": "x"}], "fault_streams": ["wind", "vibration"],
            "summary": "Faults on wind and vibration."}
    jsonschema.validate(over, review.report_schema(w, with_overrides=True))
    r4 = review.from_model(w, "m/r4", over, 1.0, base=base)
    assert r4.overrides == 1 and r4.labels["A2"] == "sensor_fault"
    assert not review.from_model(w, "m/r3", None, 1.0, "MINION_DOWN").valid


def test_score_and_paired_diff():
    w = _window()
    good = review.from_labels(w, "r1", {"A1": "sensor_fault", "A2": "real_event", "A3": "backfill_artefact"})
    bad = review.from_labels(w, "r0", {"A1": "real_event", "A2": "real_event", "A3": "real_event"})
    s = review.score([w], [good], boot=50)
    assert s["macro_f1"] == 1.0 and s["fault_recall"] == 1.0 and s["summary_validity"] == 1.0
    assert review.score([w], [bad], boot=50)["fault_recall"] == 0.0
    assert review.paired_diff([w], [good], [bad], boot=50)["diff"] > 0.5


def test_sample_keeps_artefact_windows():
    ws = [Window(f"s3-w{i:03d}", 3, i * 3600, [], [Alert("A1", "c", "temp", 0, "jump",
                 "backfill_artefact" if i in (3, 9) else "real_event", {}, _hs())]) for i in range(20)]
    got = review.sample(ws, 5)
    assert len(got) == 5 and {"s3-w003", "s3-w009"} <= {w.id for w in got}
