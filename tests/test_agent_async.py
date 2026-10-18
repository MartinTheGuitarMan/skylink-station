import threading
import time

from skylink.agent.jobs import Agent, AsyncAgent, CallLog, c5b_check, summarise_log
from skylink.agent.minions import FakeTransport


def test_submit_never_blocks_the_caller_even_when_the_model_is_slow(tmp_path):
    release, done = threading.Event(), []

    def slow(tool, args):
        release.wait(5)
        return {"label": "real_event"}

    ag = AsyncAgent(Agent(FakeTransport(slow), CallLog(tmp_path / "l.jsonl")), lambda tag, o: done.append(tag), max_queue=4)
    t0 = time.perf_counter()
    for i in range(3):
        ag.submit("triage", i, "text")
    assert time.perf_counter() - t0 < 0.2          # the forecast loop's view: instant
    assert done == []                               # the model has not answered yet
    release.set()
    ag.close()
    assert sorted(done) == [0, 1, 2]


def test_full_queue_drops_the_oldest_and_logs_it(tmp_path):
    gate, done = threading.Event(), []
    log = CallLog(tmp_path / "l.jsonl")
    ag = AsyncAgent(Agent(FakeTransport(lambda t, a: (gate.wait(5), {"label": "real_event"})[1]), log),
                    lambda tag, o: done.append(tag), max_queue=2)
    ag.submit("triage", "first", "x")
    time.sleep(0.2)                                 # the worker holds "first"; the queue is empty
    for tag in ("a", "b", "c"):
        ag.submit("triage", tag, "x")               # "a" is dropped when "c" arrives
    assert ag.dropped == 1
    gate.set()
    ag.close()
    assert done == ["first", "b", "c"]
    s = summarise_log(tmp_path / "l.jsonl")["fake/triage"]
    assert s["dropped"] == 1 and s["calls"] == 3


def test_log_joins_guardrail_verdicts_and_reports_latency_and_invalid_rate(tmp_path):
    log = CallLog(tmp_path / "l.jsonl", run="r")
    answers = iter([{"action": "switch", "model": "hat", "reason": "x"}, {"action": "keep", "model": "bad", "reason": "x"},
                    {"action": "switch", "model": "holt", "reason": "x"}])
    ag = Agent(FakeTransport(lambda t, a: next(answers)), log)
    o1, o2, o3 = ag.propose("a"), ag.propose("b"), ag.propose("c")
    assert o1.valid and not o2.valid and o3.valid and o1.call != o3.call
    log.verdict(o1.call, True, "accepted")
    log.verdict(o3.call, False, "dwell")
    s = summarise_log(tmp_path / "l.jsonl")["fake/propose"]
    assert s["calls"] == 3 and abs(s["invalid_rate"] - 1 / 3) < 1e-3 and s["accepted_frac"] == 0.5


def test_c5b_needs_macro_gain_and_no_stream_worse_than_one_percent():
    rows = [{"arm": "agent:x", "stream": "temp", "h": 600, "ratio_vs_fixed": 0.90},
            {"arm": "agent:x", "stream": "wind", "h": 30, "ratio_vs_fixed": 1.00}]
    assert c5b_check(rows, "agent:x")["pass"]
    rows[1]["ratio_vs_fixed"] = 1.02
    assert not c5b_check(rows, "agent:x")["pass"]
    assert not c5b_check([{"arm": "agent:x", "stream": "t", "h": 1, "ratio_vs_fixed": 0.99}] * 2, "agent:x")["pass"]
