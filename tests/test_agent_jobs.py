from skylink.agent.alerts import Case, LABELS, balanced, rules_baseline
from skylink.agent.jobs import Agent, CallLog, macro_f1
from skylink.agent.minions import FakeTransport


def agent(handler, tmp_path=None):
    return Agent(FakeTransport(handler), CallLog(tmp_path / "log.jsonl" if tmp_path else None))


def test_triage_valid_and_invalid_label():
    assert agent(lambda t, a: {"label": "sensor_fault"}).triage("x").value == "sensor_fault"
    bad = agent(lambda t, a: {"label": "alien"}).triage("x")
    assert not bad.valid and "bad label" in bad.why


def test_server_errors_are_counted_not_raised():
    o = agent(lambda t, a: RuntimeError("MINION_SCHEMA: no")).triage("x")
    assert not o.valid and o.reply.error == "MINION_SCHEMA"
    o = agent(lambda t, a: RuntimeError("MINION_DOWN")).propose("x")
    assert not o.valid and o.reply.error == "MINION_DOWN"


def test_proposal_is_schema_checked_in_code():
    good = {"action": "switch", "model": "hat", "reason": "lower error"}
    assert agent(lambda t, a: good).propose("x").valid
    for bad in ({"action": "switch", "model": "arf", "reason": "x"},     # not in the action space
                {"action": "keep", "model": "hat"},                        # missing field
                {"action": "keep", "model": "hat", "reason": "x" * 300},   # too long
                {"action": "keep", "model": "hat", "reason": "r", "extra": 1}):
        assert not agent(lambda t, a, b=bad: b).propose("x").valid


def test_note_rejects_numbers_that_are_not_in_the_stats():
    stats = {"stream": "temp", "mae": 0.12}
    assert agent(lambda t, a: {"summary": "Temperature MAE was 0.12."}).note(stats).valid
    o = agent(lambda t, a: {"summary": "MAE was 0.12 and rose 40 percent."}).note(stats)
    assert not o.valid and "40" in o.why


def test_call_log_records_every_call(tmp_path):
    a = agent(lambda t, a: {"label": "real_event"}, tmp_path)
    a.triage("alert text"); a.triage("another")
    assert len((tmp_path / "log.jsonl").read_text().splitlines()) == 2


def test_macro_f1_and_rules_baseline():
    assert macro_f1(LABELS, LABELS, LABELS) == 1.0
    assert macro_f1(["real_event"] * 3, ["sensor_fault"] * 3, LABELS) == 0.0
    c = Case("1", "temp", 5, "real_event", "jump", {"backfill_replay_in_progress": "yes"})
    assert rules_baseline(c) == "backfill_artefact"
    assert rules_baseline(Case("2", "temp", 5, "x", "flat", {})) == "sensor_fault"
    cs = [Case(str(i), "temp", i, LABELS[i % 3], "jump") for i in range(30)]
    assert len(balanced(cs, 4)) == 12


def test_triage_menu_limits_labels():
    from skylink.agent.jobs import Agent
    from skylink.agent.minions import FakeTransport
    seen = []
    t = FakeTransport(lambda tool, args: (seen.append(args["labels"]), {"label": "real_event"})[1])
    o = Agent(t).triage("stream: temp", labels=["sensor_fault", "backfill_artefact"])
    assert seen[0] == ["sensor_fault", "backfill_artefact"] and not o.valid      # a label outside the menu is rejected
