"""Job W (C9): does the station flag slow wear, or does the online side adapt it away?

Two arms on the same 1 s aggregates, rules fixed in the C9 amendment of docs/success-criteria.md:
  (a) the edge alert detector as it is (jump / flat against a 60 s EWMA), and that EWMA's one-step error;
  (b) a reference comparison per stream: the 24 h median of hourly medians against a reference from the first
      2 days, in units of the reference's spread. (b) keeps the reference frozen; (b') re-baselines it slowly
      while no alert is active.
Every wear run has a healthy twin (same seed, wear off), identical until onset, so a flag is attributable."""
from __future__ import annotations

import warnings

import numpy as np

from .agent.alerts import Detector, _label
from .sim.events import StreamPlan

HOUR = 3600
REF_H = 48          # reference window: hours 0-47, the C4 static window
WIN_H = 24          # online level: median of the last 24 hourly medians
MIN_WIN = 12
MIN_VALID = 1800    # seconds an hour needs for its median
K_ON, K_OFF, PERSIST = 4.0, 2.0, 6
REBASE_H = 720      # (b'): 30-day time constant
EXCUSE_S = 30 * HOUR  # after a step or drift fault: 24 h window + 6 h persistence
MATCH_S = 5


def hourly_medians(y: np.ndarray) -> np.ndarray:
    n = len(y) // HOUR
    h = y[:n * HOUR].reshape(n, HOUR)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN hours
        med = np.nanmedian(h, axis=1)
    med[(~np.isnan(h)).sum(1) < MIN_VALID] = np.nan
    return med


def reference_arm(hm: np.ndarray, floor: float, rebaseline: bool = False) -> dict:
    """Gap g(k) and alert state per hour; hours before REF_H are not scored (g NaN, inactive)."""
    ref = hm[:REF_H][~np.isnan(hm[:REF_H])]
    mu = float(np.median(ref))
    sigma = max(1.4826 * float(np.median(np.abs(ref - mu))), floor)
    n = len(hm)
    g, active, starts = np.full(n, np.nan), np.zeros(n, dtype=bool), []
    on, run = False, 0
    for k in range(REF_H, n):
        w = hm[k - WIN_H + 1:k + 1]
        w = w[~np.isnan(w)]
        if len(w) < MIN_WIN:
            run, active[k] = 0, on
            continue
        level = float(np.median(w))
        g[k] = (level - mu) / sigma
        if on:
            on = abs(g[k]) >= K_OFF
        else:
            run = run + 1 if abs(g[k]) > K_ON else 0
            if run >= PERSIST:
                on, run = True, 0
                starts.append(k)
        active[k] = on
        if rebaseline and not on and abs(g[k]) <= K_OFF:
            mu += (level - mu) / REBASE_H
    return {"mu_end": mu, "sigma": sigma, "g": g, "active": active, "starts": starts}


def excused_hours(plan, stream: str, n_hours: int) -> np.ndarray:
    """Hours where a reference gap is a real anomaly (a long sensor fault), not a false alert."""
    out = np.zeros(n_hours, dtype=bool)
    for e in plan:
        if e.stream == stream and e.kind in ("step", "drift"):
            out[int(e.t0 // HOUR):int(np.ceil((e.t1 + EXCUSE_S) / HOUR))] = True
    return out


def false_alerts(arm: dict, excused: np.ndarray) -> dict:
    scored = np.arange(len(excused)) >= REF_H
    healthy_days = float((scored & ~excused).sum()) / 24.0
    starts = arm["starts"]
    n_false = sum(1 for k in starts if not excused[k])
    return {"false": n_false, "excused_alerts": len(starts) - n_false, "healthy_days": healthy_days}


def detection(wear_arm: dict, twin_arm: dict, t0: float) -> dict:
    """First hour at or after onset where the wear run alerts and the twin does not."""
    n = len(wear_arm["active"])
    k0 = int(t0 // HOUR)
    hit = np.flatnonzero(wear_arm["active"][k0:] & ~twin_arm["active"][k0:n])
    if not len(hit):
        return {"detected": False, "delay_days": None, "hold": None}
    k = k0 + int(hit[0])
    return {"detected": True, "delay_days": ((k + 1) * HOUR - t0) / 86400.0,
            "hold": float(wear_arm["active"][k:].mean())}


def detector_pass(y: np.ndarray, stream: str) -> tuple[list[int], np.ndarray]:
    """The edge detector over a series: alert seconds, and the absolute one-step error of its EWMA."""
    det = Detector(stream)
    alerts, err = [], np.full(len(y), np.nan)
    for i in range(len(y)):
        if np.isnan(y[i]):
            continue
        if det.m is not None:
            err[i] = abs(y[i] - det.m)
        if det.update(i, float(y[i])):
            alerts.append(i)
    return alerts, err


def online_arm(y_wear, y_twin, plan_wear, ev, stream: str = "vibration") -> dict:
    """Arm (a): unexplained wear-run alerts after onset that the twin does not raise, and the EWMA error ratio."""
    a_w, e_w = detector_pass(y_wear, stream)
    a_t, e_t = detector_pass(y_twin, stream)
    sp = StreamPlan(plan_wear, stream)
    twin = np.array(a_t)
    flags = [s for s in a_w if s >= ev.t0 and _label(sp, s) is None
             and not (len(twin) and np.min(np.abs(twin - s)) <= MATCH_S)]
    lo, hi = int(max(ev.t1 - 86400, ev.t0)), int(ev.t1)
    return {"flags": len(flags), "first_flag_delay_days": (flags[0] - ev.t0) / 86400.0 if flags else None,
            "alerts_after_onset": sum(1 for s in a_w if s >= ev.t0),
            "twin_alerts_after_onset": sum(1 for s in a_t if s >= ev.t0),
            "error_ratio_last_ramp_day": float(np.nanmean(e_w[lo:hi]) / np.nanmean(e_t[lo:hi]))}
