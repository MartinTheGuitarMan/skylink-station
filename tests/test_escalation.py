from skylink.agent import escalation as E


def _item(second, edge="real_event", rules="real_event", voter="real_event"):
    return E.Item("s1-wind-1", 1, second, "sensor_fault", "stream: wind", rules, edge, voter)


def test_next_up_and_on_call_timing():
    outs = [(1000, 4000)]
    assert E.next_up(500, outs) == 500 and E.next_up(2000, outs) == 4000
    # alert at 100: ready at 220, sent at once, answered 60 s later
    assert E.timing(_item(100), outs, "on_call") == 180
    # alert inside the outage waits for link-up at 4000
    assert E.timing(_item(1500), outs, "on_call") == 4000 + E.ON_CALL_S - 1500


def test_daily_pass_timing():
    # sent at 07:00 on day 0 -> answered at 06:15 on day 1
    t = E.timing(_item(7 * 3600 - E.LOOK), [], "daily")
    assert t == E.DAY + E.DAILY_AT - (7 * 3600 - E.LOOK)
    # an answer due inside an outage comes back at link-up
    t2 = E.timing(_item(0), [(E.DAILY_AT - 10, E.DAILY_AT + 500)], "daily")
    assert t2 == E.DAILY_AT + 500


def test_policies_and_final_labels():
    a = _item(0, edge="real_event", rules="sensor_fault")
    b = _item(0, edge="sensor_fault", rules="sensor_fault", voter="real_event")
    shore = {"s1-wind-1": "sensor_fault"}
    lab, esc = E.final_labels([a, b], "P3 edge vs rules disagree", shore)
    assert esc == [True, False] and lab == ["sensor_fault", "sensor_fault"]
    assert E.final_labels([a, b], "P1 rules alone", shore)[0] == ["sensor_fault", "sensor_fault"]
    assert E.final_labels([a, b], "P4 edge voters disagree", shore)[1] == [False, True]


def test_two_class_f1_counts_other_labels_wrong():
    assert E.f1(["real_event", "sensor_fault"], ["real_event", "sensor_fault"]) == 1.0
    assert E.f1(["real_event", "sensor_fault"], ["real_event", "backfill_artefact"]) < 1.0
