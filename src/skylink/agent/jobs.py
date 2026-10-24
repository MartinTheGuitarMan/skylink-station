"""The four narrow agent jobs. Every output is validated here, in code; the agent only proposes."""
from __future__ import annotations

import itertools
import json
import queue
import re
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from .alerts import LABELS
from .minions import Reply, Transport

DESCRIPTIONS = {
    "real_event": "something really happened in the measured quantity (weather front, gust, cloud edge, seismic burst, seasonal shift)",
    "sensor_fault": "the sensor misbehaves: stuck at one value, a one-sample spike, a ramping drift, or an offset step",
    "backfill_artefact": "an artefact of late data replayed out of order after an uplink outage, not a real change at all",
}
TRIAGE_HINT = ("An alert fired on a 1 s aggregate of a station sensor stream. Decide the most likely cause from the "
               "numbers. z values are in units of the recent mean absolute deviation. A real event usually persists "
               "or has a natural shape; a spike fault is one or two seconds wide and returns at once; a step or drift "
               "fault stays offset without a natural shape; a stuck sensor is flat; a backfill artefact appears when "
               "late data arrive out of order after an outage.")
ALLOWED_MODELS = ["lin_lag", "lin_lag_static", "hat", "holt", "persistence", "seasonal_anchor"]
PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {"action": {"type": "string", "enum": ["keep", "switch"]},
                   "model": {"type": "string", "enum": ALLOWED_MODELS},
                   "reason": {"type": "string", "maxLength": 200}},
    "required": ["action", "model", "reason"], "additionalProperties": False}
CAUSES = ["sensor_fault", "backfill_artefact", "regime_change", "noise", "model_limit"]
EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {"cause": {"type": "string", "enum": CAUSES}, "evidence": {"type": "string", "maxLength": 200}},
    "required": ["cause", "evidence"], "additionalProperties": False}


@dataclass
class Outcome:
    job: str
    valid: bool
    value: object | None
    reply: Reply
    why: str = ""
    call: int = 0   # id in the call log, to attach the guardrail verdict later


class CallLog:
    """JSONL log of every agent call (input, raw output, parsed) with a `call` id. The guardrail verdict
    comes later and is logged as its own record (`kind: verdict`, same `call` id); `summarise_log` joins them.
    Not yet mirrored to the Influx `agent` bucket (backlog)."""

    def __init__(self, path: str | Path | None, run: str = ""):
        self.path, self.run = (Path(path) if path else None), run
        self._ids, self._lock = itertools.count(1), threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **rec) -> int:
        cid = next(self._ids)
        if self.path:
            with self._lock, self.path.open("a") as f:
                f.write(json.dumps({"ts": time.time(), "call": cid, "run": self.run, **rec}, default=str) + "\n")
        return cid

    def verdict(self, call: int, accepted: bool, why: str = "", outcome: float | None = None) -> None:
        """The guardrails' decision on a proposal; `outcome` = relative MAE change over the 10 min after an accepted switch."""
        if self.path:
            with self._lock, self.path.open("a") as f:
                f.write(json.dumps({"ts": time.time(), "kind": "verdict", "call": call, "accepted": accepted,
                                    "why": why, "outcome": outcome}) + "\n")


def summarise_log(path: str | Path) -> dict:
    """C5c numbers per (model, job) from a call log: calls, dropped, invalid-output rate, p50/p95 latency (s), accepted fraction."""
    calls, verdicts = {}, {}
    for line in Path(path).read_text().splitlines():
        r = json.loads(line)
        (verdicts.__setitem__(r["call"], r) if r.get("kind") == "verdict" else calls.__setitem__(r["call"], r))
    groups = defaultdict(list)
    for c in calls.values():
        groups[(c.get("model"), c.get("job"))].append(c)
    out = {}
    for (model, job), cs in sorted(groups.items(), key=str):
        done = [c for c in cs if c.get("error") != "DROPPED"]
        lat = sorted(c["latency_ms"] for c in done) or [0.0]
        vs = [verdicts[c["call"]] for c in done if c["call"] in verdicts]
        out[f"{model}/{job}"] = {
            "calls": len(done), "dropped": len(cs) - len(done),
            "invalid_rate": round(sum(1 for c in done if not c.get("valid")) / max(len(done), 1), 3),
            "p50_s": round(statistics.median(lat) / 1000, 2), "p95_s": round(lat[int(0.95 * (len(lat) - 1))] / 1000, 2),
            "accepted_frac": round(sum(1 for v in vs if v["accepted"]) / len(vs), 3) if vs else None}
    return out


def c5b_check(rows: list[dict], arm: str, min_gain: float = 0.03, max_loss: float = 0.01) -> dict:
    """C5b on the rows of `scripts/agent_proposals.py`: macro mean over (stream, horizon) of MAE ratio vs the fixed
    twin must be <= 1 - min_gain, and no stream may be worse than 1 + max_loss. Unit-free, so streams can be pooled.
    The bootstrap CI of the macro ratio is not computed here (backlog); per-row CIs are in the rows."""
    mine = [r for r in rows if r["arm"] == arm]
    if not mine:
        return {"arm": arm, "pass": False, "why": "no rows"}
    macro = sum(r["ratio_vs_fixed"] for r in mine) / len(mine)
    worst = max(mine, key=lambda r: r["ratio_vs_fixed"])
    ok = macro <= 1 - min_gain and worst["ratio_vs_fixed"] <= 1 + max_loss
    return {"arm": arm, "macro_ratio": round(macro, 4), "worst": f"{worst['stream']}/{worst['h']}", "worst_ratio": worst["ratio_vs_fixed"],
            "pass": bool(ok)}


class AsyncAgent:
    """Runs agent calls on a worker thread so the forecast loop never waits (C5c). `submit` returns at once;
    the result goes to `on_done(tag, outcome)` on the worker thread. The queue is bounded: when it is full the
    oldest waiting request is dropped and logged as `DROPPED`."""

    def __init__(self, agent: Agent, on_done, max_queue: int = 8):
        self.agent, self.on_done = agent, on_done
        self.q: deque = deque()
        self.max_queue, self.dropped = max_queue, 0
        self._cv, self._stop = threading.Condition(), False
        self._t = threading.Thread(target=self._work, daemon=True)
        self._t.start()

    def submit(self, job: str, tag, *args) -> None:
        with self._cv:
            if len(self.q) >= self.max_queue:
                old = self.q.popleft()
                self.dropped += 1
                self.agent.log.write(job=old[0], model=self.agent.t.name, input=str(old[2])[:500], valid=False,
                                     error="DROPPED", why="queue full", latency_ms=0.0)
            self.q.append((job, tag, args))
            self._cv.notify()

    def _work(self) -> None:
        while True:
            with self._cv:
                while not self.q and not self._stop:
                    self._cv.wait()
                if self._stop and not self.q:
                    return
                job, tag, args = self.q.popleft()
            self.on_done(tag, getattr(self.agent, job)(*args))

    def close(self, drain: bool = True) -> None:
        with self._cv:
            if not drain:
                self.q.clear()
            self._stop = True
            self._cv.notify()
        self._t.join(30)


class Agent:
    def __init__(self, transport: Transport, log: CallLog | None = None):
        self.t, self.log = transport, log or CallLog(None)

    def _done(self, o: Outcome, inp: str, extra: dict | None = None) -> Outcome:
        o.call = self.log.write(job=o.job, model=self.t.name, input=inp, raw=o.reply.raw[:2000], valid=o.valid,
                                value=o.value, why=o.why, error=o.reply.error, latency_ms=round(o.reply.latency_ms, 1), **(extra or {}))
        return o

    def triage(self, text: str, hint: str = TRIAGE_HINT, labels: list[str] | None = None) -> Outcome:
        labels = labels or LABELS
        r = self.t.call("classify", {"text": text, "labels": labels, "hint": hint,
                                     "descriptions": {k: v for k, v in DESCRIPTIONS.items() if k in labels}})
        if not r.ok:
            return self._done(Outcome("triage", False, None, r, r.error or "error"), text)
        lab = (r.data or {}).get("label")
        ok = lab in labels
        return self._done(Outcome("triage", ok, lab if ok else None, r, "" if ok else f"bad label {lab!r}"), text)

    def propose(self, text: str) -> Outcome:
        r = self.t.call("extract", {"text": text, "schema": PROPOSAL_SCHEMA,
                                    "hint": "Choose which forecasting model should serve this stream and horizon. "
                                            "Prefer keeping the current model unless another has a clearly lower recent error."})
        return self._structured("propose", text, r, PROPOSAL_SCHEMA)

    def explain(self, text: str) -> Outcome:
        r = self.t.call("extract", {"text": text, "schema": EXPLAIN_SCHEMA,
                                    "hint": "Name the most likely cause of the large forecast error."})
        return self._structured("explain", text, r, EXPLAIN_SCHEMA)

    def note(self, stats: dict, max_words: int = 80) -> Outcome:
        text = "\n".join(f"{k}: {v}" for k, v in stats.items())
        r = self.t.call("summarize", {"text": text, "max_words": max_words})
        if not r.ok:
            return self._done(Outcome("note", False, None, r, r.error or "error"), text)
        s = (r.data or {}).get("summary", "")
        nums = set(re.findall(r"\d+(?:\.\d+)?", s))
        known = set(re.findall(r"\d+(?:\.\d+)?", text))
        bad = sorted(nums - known)
        ok = bool(s) and len(s.split()) <= max_words and not bad
        return self._done(Outcome("note", ok, s if ok else None, r, "" if ok else f"numbers not in the stats: {bad}"), text)

    def _structured(self, job: str, text: str, r: Reply, schema: dict) -> Outcome:
        if not r.ok:
            return self._done(Outcome(job, False, None, r, r.error or "error"), text)
        try:
            jsonschema.validate(r.data, schema)
        except jsonschema.ValidationError as e:
            return self._done(Outcome(job, False, None, r, f"schema: {e.message[:120]}"), text)
        return self._done(Outcome(job, True, r.data, r), text)


def macro_f1(truth: list[str], pred: list[str], labels: list[str]) -> float:
    f1s = []
    for lab in labels:
        tp = sum(1 for t, p in zip(truth, pred) if t == lab and p == lab)
        fp = sum(1 for t, p in zip(truth, pred) if t != lab and p == lab)
        fn = sum(1 for t, p in zip(truth, pred) if t == lab and p != lab)
        f1s.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return sum(f1s) / len(f1s)
