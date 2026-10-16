"""Python twin of the Node-RED Skylink chain (mulberry32, stepped once per event second).

Used offline to know when outages and replays happened without asking InfluxDB on another machine.
`tests/test_agent_cases.py` checks it against the JavaScript gate, transition by transition."""
from __future__ import annotations

M32 = 0xFFFFFFFF


def _s32(x: int) -> int:
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


class Mulberry32:
    def __init__(self, state: int):
        self.s = _s32(state)

    def next(self) -> float:
        self.s = _s32(self.s + 0x6D2B79F5)
        s = self.s & M32
        t = _s32(((s ^ (s >> 15)) * (1 | s)) & M32)
        tu = t & M32
        t = _s32(tu + _s32(((tu ^ (tu >> 7)) * (61 | tu)) & M32)) ^ t
        tu = t & M32
        return ((tu ^ (tu >> 14)) & M32) / 4294967296.0


def link_rng(seed: int) -> Mulberry32:
    return Mulberry32(_s32(((seed * 2654435761) & M32) ^ 0x9E3779B9))


def schedule(seed: int, seconds: int, mean_up_s: float = 14400, mean_down_s: float = 2400) -> list[tuple[int, int]]:
    """Transitions [(event second, up)] for seconds 1..seconds. up=0 is the start of an outage."""
    rng, up, out = link_rng(seed), True, []
    for clock in range(1, seconds + 1):
        u = rng.next()
        if up:
            if u < 1 / mean_up_s:
                up = False
                out.append((clock, 0))
        elif u < 1 / mean_down_s:
            up = True
            out.append((clock, 1))
    return out


def outages(trans: list[tuple[int, int]], seconds: int) -> list[tuple[int, int]]:
    """[(down_s, up_s)] outage intervals (an unfinished one ends at `seconds`)."""
    res, d = [], None
    for t, up in trans:
        if not up:
            d = t
        elif d is not None:
            res.append((d, t))
            d = None
    if d is not None:
        res.append((d, seconds))
    return res
