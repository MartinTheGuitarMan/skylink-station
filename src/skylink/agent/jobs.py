"""The four narrow agent jobs. Every output is validated here, in code; the agent only proposes."""
from __future__ import annotations

import json
import re
import time
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


class CallLog:
    """JSONL log of every agent call (input, raw output, parsed, verdict). Later: also the `agent` bucket."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **rec) -> None:
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps({"ts": time.time(), **rec}, default=str) + "\n")


class Agent:
    def __init__(self, transport: Transport, log: CallLog | None = None):
        self.t, self.log = transport, log or CallLog(None)

    def _done(self, o: Outcome, inp: str, extra: dict | None = None) -> Outcome:
        self.log.write(job=o.job, model=self.t.name, input=inp, raw=o.reply.raw[:2000], valid=o.valid,
                       value=o.value, why=o.why, error=o.reply.error, latency_ms=round(o.reply.latency_ms, 1), **(extra or {}))
        return o

    def triage(self, text: str, hint: str = TRIAGE_HINT) -> Outcome:
        r = self.t.call("classify", {"text": text, "labels": LABELS, "hint": hint, "descriptions": DESCRIPTIONS})
        if not r.ok:
            return self._done(Outcome("triage", False, None, r, r.error or "error"), text)
        lab = (r.data or {}).get("label")
        ok = lab in LABELS
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
