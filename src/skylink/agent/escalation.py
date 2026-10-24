"""Escalation (C5e in docs/success-criteria.md): the edge model may send a question ashore to a big brain when Skylink is up.

Offline and replayable: the edge's and the shores' answers come from stored runs on the same cases; this module decides which
alerts are escalated (policies), when each question can leave and when its answer comes back (the seeded link chain), and
scores the final labels. An escalated alert keeps the edge's provisional label until the shore's answer is back."""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from . import linkmodel
from .jobs import macro_f1

EDGE_LABELS = ["real_event", "sensor_fault"]
LOOK = 120            # the edge decides 2 min after onset (job T context)
ON_CALL_S = 60        # on-call shore: answer 60 s after the question arrives
DAILY_AT = 6 * 3600 + 15 * 60   # daily pass at 06:15 of event time (t = 0 is midnight)
DAY = 86400
RUN_S = 7 * DAY


@dataclass
class Item:
    cid: str
    seed: int
    second: int
    truth: str
    text: str
    rules: str
    edge: str | None
    voter: str | None


POLICIES = {
    "P0 edge alone": lambda it: False,
    "P1 rules alone": None,                       # special: final = rules, nothing escalated
    "P2 escalate all": lambda it: True,
    "P3 edge vs rules disagree": lambda it: it.edge != it.rules,
    "P4 edge voters disagree": lambda it: it.edge != it.voter,
    "P5 P3 or P4": lambda it: it.edge != it.rules or it.edge != it.voter,
}


def outages(seed: int, seconds: int = RUN_S) -> list[tuple[int, int]]:
    return linkmodel.outages(linkmodel.schedule(seed, seconds), seconds)


def next_up(t: float, outs: list[tuple[int, int]]) -> float:
    """First moment at or after t when the link is up."""
    for d, u in outs:
        if d <= t < u:
            return float(u)
    return float(t)


def timing(it: Item, outs, mode: str) -> float:
    """Seconds from alert onset until the shore's answer is back at the edge."""
    ready = it.second + LOOK
    sent = next_up(ready, outs)
    if mode == "on_call":
        answered = sent + ON_CALL_S
    else:   # daily pass
        day0 = (sent // DAY) * DAY
        answered = day0 + DAILY_AT if sent <= day0 + DAILY_AT else day0 + DAY + DAILY_AT
    return next_up(answered, outs) - it.second


def question_bytes(it: Item) -> int:
    return len(json.dumps({"q": it.cid, "job": "triage", "edge": it.edge, "text": it.text}).encode())


ANSWER_BYTES = len(json.dumps({"q": "s1-wind-123456", "label": "sensor_fault", "why": "x" * 80}).encode())


def f1(truth, pred) -> float:
    return macro_f1(truth, [p if p in EDGE_LABELS else "other" for p in pred], EDGE_LABELS)


def final_labels(items: list[Item], policy: str, shore: dict) -> tuple[list, list[bool]]:
    rule = POLICIES[policy]
    if rule is None:
        return [it.rules for it in items], [False] * len(items)
    esc = [rule(it) for it in items]
    return [shore.get(it.cid) if e else it.edge for it, e in zip(items, esc)], esc


def boot_diff(truth, a, b, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    t, a, b = np.array(truth, dtype=object), np.array(a, dtype=object), np.array(b, dtype=object)
    out = []
    for _ in range(n):
        i = rng.integers(0, len(t), len(t))
        out.append(f1(list(t[i]), list(a[i])) - f1(list(t[i]), list(b[i])))
    return [round(float(np.percentile(out, 2.5)), 3), round(float(np.percentile(out, 97.5)), 3)]


def boot_f1(truth, pred, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    t, p = np.array(truth, dtype=object), np.array(pred, dtype=object)
    out = [f1(list(t[i]), list(p[i])) for i in (rng.integers(0, len(t), len(t)) for _ in range(n))]
    return [round(float(np.percentile(out, 2.5)), 3), round(float(np.percentile(out, 97.5)), 3)]


def distilled_rules(stream: str, kind: str, c: dict) -> str:
    """Rules sent down from the shore: the five rules Claude's 200 blind answers followed (C5e follow-up, 2026-10-24)."""
    if kind == "flat" or stream in ("temp", "pressure"):
        return "sensor_fault"
    z, peak, width = c["onset_z"], c["peak_z_next_2min"], c["seconds_beyond_threshold_in_2min"]
    if stream == "wind" and (z >= 10 or peak >= 15 or c["flat_fraction_next_2min"] >= 0.5):
        return "sensor_fault"
    if stream == "vibration" and ((z < 0 and width >= 60) or (width == 1 and z >= 15)):
        return "sensor_fault"
    if stream == "solar" and width == 1 and abs(z) >= 15:
        return "sensor_fault"
    return "real_event"
