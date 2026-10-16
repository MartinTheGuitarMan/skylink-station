from skylink.agent.guard import Switchboard, Trailing

KEY = ("temp", 600)
TR = {"lin_lag": 0.20, "hat": 0.10, "holt": 0.35, "persistence": 0.5}


def board():
    return Switchboard("lin_lag", ["lin_lag", "hat", "holt", "persistence"])


def test_accepts_a_clearly_better_model_and_rejects_the_rest():
    b = board()
    assert b.propose(KEY, "hat", 10_000, TR, "agent") == (True, "accepted")
    assert b.served(KEY) == "hat"
    assert b.propose(KEY, "arf", 20_000, TR, "agent") == (False, "not in action space")
    assert b.propose(KEY, "hat", 20_000, TR, "agent")[1] == "no change"
    assert b.propose(KEY, "lin_lag", 10_500, TR, "agent")[1] == "dwell"          # one switch per 30 min


def test_rejects_a_proposal_that_is_much_worse():
    b = board()
    ok, why = b.propose(KEY, "persistence", 10_000, TR, "agent")                  # 0.5 > 1.5 * 0.2
    assert not ok and "worse" in why and b.served(KEY) == "lin_lag"


def test_needs_evidence():
    assert board().propose(KEY, "hat", 10_000, {"lin_lag": 0.2, "hat": None}, "agent")[1] == "no evidence yet"


def test_rollback_when_the_switch_hurts():
    b = board()
    b.propose(KEY, "hat", 10_000, TR, "agent")
    assert not b.check_rollback(KEY, 10_100, 0.5)            # too early
    assert b.check_rollback(KEY, 10_700, 0.30)               # pre 0.20 -> 0.30 is > 20 % worse
    assert b.served(KEY) == "lin_lag" and b.slot(KEY).rollbacks == 1


def test_no_rollback_when_it_helps():
    b = board()
    b.propose(KEY, "hat", 10_000, TR, "agent")
    assert not b.check_rollback(KEY, 10_700, 0.15)
    assert b.served(KEY) == "hat"


def test_trailing_window():
    t = Trailing(100)
    for s in range(200):
        t.add(s, 1.0 if s < 100 else 3.0)
    assert abs(t.mae() - 3.0) < 0.05
