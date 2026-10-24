import json

from skylink.agent import inbox
from skylink.agent.alerts import Case


def _ctx(z=9.0, width=3, flat=0.0, peak=None):
    return {"stream": "x", "unit": "u", "onset_z": z, "peak_z_next_2min": peak or z, "z_after_1min": 0.0, "z_after_2min": 0.0,
            "seconds_beyond_threshold_in_2min": width, "flat_fraction_next_2min": flat, "change_vs_10s_before_in_sigma": z,
            "other_streams_alerting_within_1min": 0, "data_arrived_via_backfill_replay": "no", "backfill_replay_in_progress": "no"}


def _cases():
    return [Case("c1", "wind", 1000, "sensor_fault", "jump", _ctx(9.0)),          # residue, edge says real -> wrong
            Case("c2", "vibration", 2000, "real_event", "jump", _ctx(9.0, width=1)),  # residue, edge real -> right
            Case("c3", "temp", 3000, "sensor_fault", "jump", _ctx(30.0)),         # not residue
            Case("c4", "vibration", 4000, "real_event", "jump", _ctx(12.0, width=6))]  # not residue


def test_ask_writes_questions_without_truth(tmp_path):
    m = inbox.ask(tmp_path, "e11", 11, 1, budget=1, cases=_cases())
    assert m["alerts"] == 4 and m["residue"] == 2 and m["asked"] == 1
    qs = [json.loads(x) for x in (tmp_path / "inbox" / "e11.jsonl").read_text().splitlines()]
    assert [q["stream"] for q in qs] == ["wind"]                                 # wind first within the budget
    text = (tmp_path / "inbox" / "e11.jsonl").read_text() + (tmp_path / "ledger" / "e11.jsonl").read_text()
    assert "sensor_fault" not in text.replace('"edge": "sensor_fault"', "")     # truth never written (edge labels only)
    assert "label" not in text


def test_check_answer():
    qs = {"q1": {"q": "q1", "stream": "wind"}}
    assert inbox.check_answer({"q": "q1", "label": "sensor_fault", "kind": "stuck", "why": "flat"}, qs) == ""
    assert inbox.check_answer({"q": "q9", "label": "sensor_fault"}, qs) == "unknown question"
    assert "not allowed" in inbox.check_answer({"q": "q1", "label": "backfill_artefact"}, qs)
    assert "not possible" in inbox.check_answer({"q": "q1", "label": "real_event", "kind": "front"}, qs)
    assert "too long" in inbox.check_answer({"q": "q1", "label": "real_event", "why": "x" * 200}, qs)


def test_apply_and_score(tmp_path):
    inbox.ask(tmp_path, "e11", 11, 1, budget=2, cases=_cases())
    assert inbox.apply(tmp_path, "e11") is None                                  # no answers yet
    ans = [{"q": "e11-wind-1000", "label": "sensor_fault", "kind": "stuck", "why": "w", "keep_as_example": True},
           {"q": "e11-vibration-2000", "label": "real_event", "why": "burst"},
           {"q": "e11-temp-3000", "label": "real_event"}]                         # not asked -> rejected
    (tmp_path / "answers").mkdir()
    (tmp_path / "answers" / "e11.jsonl").write_text("".join(json.dumps(a) + "\n" for a in ans))
    r = inbox.apply(tmp_path, "e11")
    assert r["answers_ok"] == 2 and len(r["answers_rejected"]) == 1
    assert inbox.apply(tmp_path, "e11") is None                                  # applied once only
    assert len((tmp_path / "examples.jsonl").read_text().splitlines()) == 1
    truth = {(c.stream, c.second): c.label for c in _cases()}
    s = inbox.score(tmp_path, truth_fn=lambda seed, days: truth)
    n = s["nights"][0]
    assert n["fixed"] == 1 and n["broke"] == 0 and n["final_f1"] == 1.0 and n["answer_accuracy"] == 1.0
    assert s["pooled"]["gain"] > 0 and not s["pooled"]["readable"]
    assert (tmp_path / "summary.md").exists()


def test_pending_and_show(tmp_path):
    inbox.ask(tmp_path, "e11", 11, 1, budget=5, cases=_cases())
    out = tmp_path / "outbox"
    assert [p.stem for p in inbox.pending(tmp_path, out)] == ["e11"]
    out.mkdir(); (out / "e11.jsonl").write_text("")
    assert inbox.pending(tmp_path, out) == []
    assert "e11-wind-1000 | wind | detector=jump | edge=real_event" in inbox.show(tmp_path / "inbox" / "e11.jsonl")
