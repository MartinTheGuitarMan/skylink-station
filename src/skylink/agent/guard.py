"""Guardrails for model-switch proposals: the agent proposes, this decides.

Rules (docs/agent.md): switch only among running models; at most one switch per (stream, horizon) per
`min_dwell_s`; reject a proposal whose trailing MAE is more than 50 % worse than the incumbent's;
roll a switch back if the MAE in the `check_s` after it exceeds the MAE in the `check_s` before by more than 20 %."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Slot:
    model: str
    since: int = 0
    prev_model: str | None = None
    pre_mae: float | None = None
    check_at: int | None = None
    switches: int = 0
    rollbacks: int = 0


class Trailing:
    """Trailing mean absolute error per key over a window of event seconds."""

    def __init__(self, window_s: int):
        self.w, self.q, self.sum = window_s, deque(), 0.0

    def add(self, s: int, err: float) -> None:
        self.q.append((s, err)); self.sum += err
        while self.q and self.q[0][0] < s - self.w:
            self.sum -= self.q.popleft()[1]

    def mae(self) -> float | None:
        return self.sum / len(self.q) if len(self.q) >= 60 else None


@dataclass
class Switchboard:
    default: str
    allowed: list
    min_dwell_s: int = 1800
    check_s: int = 600
    slots: dict = field(default_factory=dict)
    log: list = field(default_factory=list)

    def slot(self, key) -> Slot:
        return self.slots.setdefault(key, Slot(self.default))

    def served(self, key) -> str:
        return self.slot(key).model

    def _switch(self, key, model: str, now: int, pre_mae: float | None) -> None:
        sl = self.slot(key)
        sl.prev_model, sl.model, sl.since, sl.pre_mae, sl.check_at = sl.model, model, now, pre_mae, now + self.check_s
        sl.switches += 1

    def propose(self, key, model: str, now: int, trailing: dict, source: str) -> tuple[bool, str]:
        """trailing: {model: trailing MAE or None}. Returns (accepted, reason)."""
        sl = self.slot(key)
        if model not in self.allowed:
            return self._rec(key, now, source, model, False, "not in action space")
        if model == sl.model:
            return self._rec(key, now, source, model, False, "no change")
        if now - sl.since < self.min_dwell_s and sl.switches > 0:
            return self._rec(key, now, source, model, False, "dwell")
        new, cur = trailing.get(model), trailing.get(sl.model)
        if new is None or cur is None:
            return self._rec(key, now, source, model, False, "no evidence yet")
        if new > 1.5 * cur:
            return self._rec(key, now, source, model, False, "worse than incumbent by more than 50 %")
        self._switch(key, model, now, cur)
        return self._rec(key, now, source, model, True, "accepted")

    def check_rollback(self, key, now: int, current_mae: float | None) -> bool:
        sl = self.slot(key)
        if sl.check_at is None or now < sl.check_at:
            return False
        sl.check_at = None
        if sl.pre_mae and current_mae is not None and current_mae > 1.2 * sl.pre_mae and sl.prev_model:
            sl.model, sl.prev_model, sl.since = sl.prev_model, None, now
            sl.rollbacks += 1
            self._rec(key, now, "guard", sl.model, True, "rollback")
            return True
        return False

    def _rec(self, key, now, source, model, ok, why):
        self.log.append({"key": key, "t": now, "source": source, "model": model, "accepted": ok, "why": why})
        return ok, why
