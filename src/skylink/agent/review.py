"""Job R, retrospective review (C5d in docs/success-criteria.md): one-hour windows of event time, read after the fact.

Scripts make every number: the alerts of job T (edge detector plus artefact alerts from the arrival-order series), each with
*hindsight* numbers from the full event-time series, and the link outages. A method returns a cause per alert, the streams
with a sensor fault, and a summary of at most 80 words. Everything a method returns is checked here, in code."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

import numpy as np

from ..sim.streams import SPECS
from . import alerts
from .alerts import FLOOR, LABELS, Case

WINDOW = 3600
MAX_WORDS = 80
STREAMS = ["temp", "pressure", "wind", "vibration", "solar"]


def _med(seg: np.ndarray) -> float | None:
    seg = seg[~np.isnan(seg)]
    return float(np.median(seg)) if len(seg) else None


def typical_change(y: np.ndarray, s: int, lag: int) -> float:
    """Median |y(t+lag) - y(t)| over the day before s, sampled every 60 s: what a normal change over `lag` looks like."""
    t = np.arange(max(0, s - 86400), s - lag, 60)
    if len(t) < 10:
        return float("nan")
    d = np.abs(y[t + lag] - y[t])
    d = d[~np.isnan(d)]
    return float(np.median(d)) if len(d) else float("nan")


def hindsight(y: np.ndarray, s: int, stream: str, outs: list[tuple[int, int]]) -> dict:
    """Numbers about the alert second s that only the full event-time series can give (read after the window)."""
    n, floor = len(y), FLOOR[stream]
    pre = y[max(0, s - 600):max(0, s - 5)]
    pre = pre[~np.isnan(pre)]
    base = float(np.median(pre[-115:])) if len(pre) else float(y[s])
    sc = max(1.4826 * float(np.median(np.abs(pre - np.median(pre)))) if len(pre) else 0.0, floor)

    def noise_units(a, b):
        m = _med(y[min(n, s + a):min(n, s + b)])
        return None if m is None else round((m - base) / sc, 1)

    def typical_units(lag):
        m, typ = _med(y[min(n, s + lag):min(n, s + lag + 60)]), typical_change(y, s, lag)
        if m is None or not typ or np.isnan(typ):
            return None
        return round((m - base) / max(typ, floor), 1)

    width = 0
    while s + width < n and width < 3600 and not np.isnan(y[s + width]) and abs(y[s + width] - base) / sc > 4:
        width += 1
    flat = 0
    if not np.isnan(y[s]):
        lo = s
        while lo > max(0, s - 7200) and y[lo - 1] == y[s]:
            lo -= 1
        hi = s
        while hi < min(n - 1, s + 7200) and y[hi + 1] == y[s]:
            hi += 1
        flat = hi - lo + 1 if hi > lo else 0
    return {"event_time_z_at_alert": round((float(y[s]) - base) / sc, 1) if not np.isnan(y[s]) else None,
            "seconds_beyond_4_sigma_from_alert": width,
            "level_after_10s_z": noise_units(10, 15), "level_after_1min_z": noise_units(60, 70),
            "level_after_10min_z": noise_units(600, 660),
            "offset_after_30min_vs_typical_30min_change": typical_units(1800),
            "offset_after_2h_vs_typical_2h_change": typical_units(7200),
            "identical_value_run_s": flat,
            "missing_seconds_from_1min_before_to_5min_after": int(np.isnan(y[max(0, s - 60):min(n, s + 300)]).sum()),
            "alert_second_inside_uplink_outage": "yes" if any(d <= s < u for d, u in outs) else "no"}


@dataclass
class Alert:
    aid: str            # A1, A2, ... inside the window
    case_id: str
    stream: str
    t: int              # seconds from the window start (event time)
    kind: str           # detector kind: jump | flat
    label: str          # truth
    ctx: dict = field(default_factory=dict)
    hs: dict = field(default_factory=dict)


@dataclass
class Window:
    id: str
    seed: int
    start: int
    outages: list = field(default_factory=list)   # [(from_t, to_t)] relative, clipped to the window
    alerts: list = field(default_factory=list)

    def fault_streams(self) -> list[str]:
        return sorted({a.stream for a in self.alerts if a.label == "sensor_fault"})

    def text(self) -> str:
        """The whole input of a window method. No truth in it."""
        units = ", ".join(f"{s} ({SPECS[s].unit})" for s in STREAMS)
        outs = "; ".join(f"t={a} to t={b}" for a, b in self.outages) or "none"
        lines = [f"Window {self.id}: 3600 s of event time, t = seconds from the window start. Streams: {units}.",
                 f"Uplink outages in this window: {outs}. Data from an outage reached shore late, replayed out of order after link-up.",
                 f"Alerts in this window: {len(self.alerts)}."]
        for a in self.alerts:
            lines.append(alert_text(a))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"id": self.id, "seed": self.seed, "start": self.start, "outages": self.outages,
                "alerts": [asdict(a) for a in self.alerts]}

    @staticmethod
    def from_dict(d: dict) -> "Window":
        return Window(d["id"], d["seed"], d["start"], [tuple(o) for o in d["outages"]], [Alert(**a) for a in d["alerts"]])


def alert_text(a: Alert) -> str:
    ctx = {k: v for k, v in a.ctx.items() if k not in ("stream", "unit")}
    two = "; ".join(f"{k}={v}" for k, v in ctx.items())
    hs = "; ".join(f"{k}={v}" for k, v in a.hs.items())
    return f"{a.aid} | stream={a.stream} | t={a.t} | detector={a.kind} | first 2 min: {two} | hindsight: {hs}"


def build_seed(seed: int, days: float, streams=STREAMS) -> list[Window]:
    """All one-hour windows of a seed that hold at least one labelled alert (job T labels, warm-up excluded by the detector)."""
    assert not 100 < seed < 106, "locked seeds are not for development"
    series, plan = alerts.aggregate_series(seed, days, streams)
    n = len(next(iter(series.values())))
    edge, info = alerts.edge_cases(series, plan, seed, n)
    cases: list[Case] = edge + alerts.artefact_cases(series, plan, seed, info)
    outs = info["outages"]
    wins: dict[int, Window] = {}
    for c in sorted(cases, key=lambda c: (c.second, c.stream)):
        k = c.second // WINDOW
        w = wins.setdefault(k, Window(f"s{seed}-w{k:03d}", seed, k * WINDOW,
                                      [(max(d, k * WINDOW) - k * WINDOW, min(u, (k + 1) * WINDOW) - k * WINDOW)
                                       for d, u in outs if d < (k + 1) * WINDOW and u > k * WINDOW]))
        w.alerts.append(Alert("", c.id, c.stream, c.second - w.start, c.kind, c.label, c.context,
                              hindsight(series[c.stream], c.second, c.stream, outs)))
    for w in wins.values():
        for i, a in enumerate(w.alerts, 1):
            a.aid = f"A{i}"
    return [wins[k] for k in sorted(wins)]


def sample(windows: list[Window], n: int, seed: int = 24) -> list[Window]:
    """Every window holding an artefact alert, then random others up to n (fixed seed), in time order."""
    art = [w for w in windows if any(a.label == "backfill_artefact" for a in w.alerts)]
    rest = [w for w in windows if w not in art]
    rng = np.random.default_rng(seed)
    pick = art[:n] + [rest[i] for i in rng.permutation(len(rest))[:max(0, n - len(art))]]
    return sorted(pick, key=lambda w: w.start)


# ---- methods without a model ----------------------------------------------------------------------------------

def rules_r0(a: Alert) -> str:
    return alerts.rules_baseline(Case(a.case_id, a.stream, a.t, a.label, a.kind, a.ctx))


# R1 thresholds, from the simulator's event definitions; set on dev seeds 1-2 only (grid in JOURNAL iteration 13).
# A 2 h step-offset test was tried there and dropped: it did not help (solar clouds and diurnal change look like steps).
R1 = {"flat_s": 60, "quiet_z": 2.0, "spike_width_s": 1, "wind_z": 10.0}


def rules_r1(a: Alert, th: dict = R1) -> str:
    """Hindsight rules: a stuck sensor is flat; an alert the event-time series does not show is an artefact of the replay;
    a one-second excursion is a spike; a wind jump beyond what a gust can do (gusts are at most 2.6x) is a fault."""
    h = a.hs
    if h["identical_value_run_s"] >= th["flat_s"]:
        return "sensor_fault"
    z = h["event_time_z_at_alert"]
    if z is None or abs(z) < th["quiet_z"]:
        return "backfill_artefact"
    if h["seconds_beyond_4_sigma_from_alert"] <= th["spike_width_s"]:
        return "sensor_fault"
    if a.stream == "wind" and abs(z) >= th["wind_z"]:
        return "sensor_fault"
    return "real_event"


def template_summary(w: Window, labels: dict[str, str]) -> str:
    """Code-written summary, used by R0-R2 (and as the reference for what a valid summary may say)."""
    by = {lab: [aid for aid, l in labels.items() if l == lab] for lab in LABELS}
    faults = sorted({a.stream for a in w.alerts if labels.get(a.aid) == "sensor_fault"})
    parts = [f"Window {w.id}: {len(w.alerts)} alerts."]
    if faults:
        parts.append("Sensor fault on " + ", ".join(faults) + " (" + ", ".join(by["sensor_fault"]) + ").")
    if by["backfill_artefact"]:
        parts.append(f"{len(by['backfill_artefact'])} backfill artefacts after the outage, ignore.")
    if by["real_event"]:
        parts.append(f"{len(by['real_event'])} real events.")
    return " ".join(parts)


# ---- what a model method must return, and the checks --------------------------------------------------------

def report_schema(w: Window, with_overrides: bool = False) -> dict:
    ids = [a.aid for a in w.alerts]
    label_item = {"type": "object", "properties": {"id": {"type": "string", "enum": ids},
                                                    "cause": {"type": "string", "enum": LABELS}},
                  "required": ["id", "cause"], "additionalProperties": False}
    props = {"labels": {"type": "array", "items": label_item, "minItems": len(ids), "maxItems": len(ids)},
             "fault_streams": {"type": "array", "items": {"type": "string", "enum": STREAMS}, "maxItems": len(STREAMS)},
             "summary": {"type": "string", "maxLength": 700}}
    req = ["labels", "fault_streams"]   # summary is free text: minions extract refuses a required value not in the source; summary_check below judges it
    if with_overrides:
        props["overrides"] = {"type": "array", "maxItems": len(ids), "items": {
            "type": "object", "properties": {"id": {"type": "string", "enum": ids}, "cause": {"type": "string", "enum": LABELS},
                                             "reason": {"type": "string", "maxLength": 200}},
            "required": ["id", "cause"], "additionalProperties": False}}
        del props["labels"]
        req = ["overrides", "fault_streams"]
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


NUM = re.compile(r"(?<![A-Za-z])-?\d+(?:\.\d+)?")


def summary_check(w: Window, summary: str, labels: dict[str, str], fault_streams: list[str]) -> tuple[bool, str]:
    """Valid = at most 80 words; every alert id named exists; every number is in the input or is a count of the report's own
    labels (per cause, total, fault streams). Numbers inside window and alert ids (s3-w012, A7) are not counted twice."""
    if not summary or not summary.strip():
        return False, "empty"
    words = len(summary.split())
    if words > MAX_WORDS:
        return False, f"{words} words"
    ids = {a.aid for a in w.alerts}
    named = set(re.findall(r"\bA\d+\b", summary))
    if named - ids:
        return False, f"unknown alert ids {sorted(named - ids)}"
    text = re.sub(r"\bA\d+\b|\bs\d+-w\d+\b", " ", summary)
    known = {float(x) for x in NUM.findall(w.text())}
    counts = {float(len(w.alerts)), float(len(fault_streams))} | {float(sum(1 for v in labels.values() if v == lab)) for lab in LABELS}
    bad = sorted({x for x in NUM.findall(text) if float(x) not in known | counts and float(abs(float(x))) not in known})
    return (False, f"numbers not in the input: {bad}") if bad else (True, "")


@dataclass
class Report:
    window: str
    method: str
    labels: dict                      # aid -> cause (None when the method failed for that alert)
    fault_streams: list
    summary: str
    valid: bool                       # output parsed and passed the schema
    summary_ok: bool
    why: str = ""
    latency_s: float = 0.0
    overrides: int = 0


def from_labels(w: Window, method: str, labels: dict, latency_s: float = 0.0, valid: bool = True, why: str = "") -> Report:
    faults = sorted({a.stream for a in w.alerts if labels.get(a.aid) == "sensor_fault"})
    s = template_summary(w, labels)
    ok, why2 = summary_check(w, s, labels, faults)
    return Report(w.id, method, labels, faults, s, valid, ok, why or why2, latency_s)


def from_model(w: Window, method: str, data: dict | None, latency_s: float, err: str = "", base: dict | None = None) -> Report:
    """A model report. For R4 (`base` = R1 labels) the model's overrides are applied on top of the rules."""
    if data is None:
        return Report(w.id, method, {a.aid: None for a in w.alerts}, [], "", False, False, err or "no output", latency_s)
    n_over = 0
    if base is not None:
        labels = dict(base)
        for o in data.get("overrides", []):
            if o["id"] in labels and labels[o["id"]] != o["cause"]:
                labels[o["id"]] = o["cause"]
                n_over += 1
    else:
        labels = {a.aid: None for a in w.alerts}
        for item in data.get("labels", []):
            labels[item["id"]] = item["cause"]
    faults = sorted(set(data.get("fault_streams", [])))
    ok, why = summary_check(w, data.get("summary", ""), labels, faults)
    return Report(w.id, method, labels, faults, data.get("summary", ""), True, ok, why, latency_s, n_over)


# ---- scoring ------------------------------------------------------------------------------------------------

def _f1(truth, pred):
    from .jobs import macro_f1
    return macro_f1(truth, [p or "none" for p in pred], LABELS)


def score(windows: list[Window], reports: list[Report], boot: int = 2000, seed: int = 0) -> dict:
    by = {r.window: r for r in reports}
    rows = []   # per window: (truth labels, predicted labels, fault tp, fault fp, fault fn, summary ok, valid, latency, bytes)
    for w in windows:
        r = by.get(w.id)
        if r is None:
            continue
        truth = [a.label for a in w.alerts]
        pred = [r.labels.get(a.aid) for a in w.alerts]
        tf, pf = set(w.fault_streams()), set(r.fault_streams)
        rows.append((truth, pred, len(tf & pf), len(pf - tf), len(tf - pf), r.summary_ok, r.valid, r.latency_s,
                     len(json.dumps({"labels": r.labels, "fault_streams": r.fault_streams, "summary": r.summary}).encode()),
                     r.overrides))
    if not rows:
        return {"windows": 0}

    def agg(rs):
        t = [x for r in rs for x in r[0]]
        p = [x for r in rs for x in r[1]]
        tp, fp, fn = sum(r[2] for r in rs), sum(r[3] for r in rs), sum(r[4] for r in rs)
        return _f1(t, p), (tp / (tp + fp) if tp + fp else 1.0), (tp / (tp + fn) if tp + fn else 1.0)

    f1, prec, rec = agg(rows)
    rng = np.random.default_rng(seed)
    bs = [agg([rows[i] for i in rng.integers(0, len(rows), len(rows))])[0] for _ in range(boot)]
    lat = sorted(r[7] for r in rows)
    return {"windows": len(rows), "alerts": sum(len(r[0]) for r in rows), "macro_f1": round(f1, 3),
            "macro_f1_ci": [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)],
            "accuracy": round(sum(t == p for r in rows for t, p in zip(r[0], r[1])) / sum(len(r[0]) for r in rows), 3),
            "fault_precision": round(prec, 3), "fault_recall": round(rec, 3),
            "summary_validity": round(sum(r[5] for r in rows) / len(rows), 3),
            "invalid_rate": round(sum(not r[6] for r in rows) / len(rows), 3),
            "p50_s_per_window": round(lat[len(lat) // 2], 2), "p95_s_per_window": round(lat[int(0.95 * (len(lat) - 1))], 2),
            "report_bytes_mean": round(sum(r[8] for r in rows) / len(rows)), "overrides": sum(r[9] for r in rows)}


def paired_diff(windows: list[Window], a: list[Report], b: list[Report], boot: int = 2000, seed: int = 0) -> dict:
    """macro-F1(a) - macro-F1(b) with a paired bootstrap over windows (C5d pass rule)."""
    ra, rb = {r.window: r for r in a}, {r.window: r for r in b}
    ws = [w for w in windows if w.id in ra and w.id in rb]

    def f1(sel, rr):
        return _f1([x.label for w in sel for x in w.alerts], [rr[w.id].labels.get(x.aid) for w in sel for x in w.alerts])

    d = f1(ws, ra) - f1(ws, rb)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(boot):
        sel = [ws[i] for i in rng.integers(0, len(ws), len(ws))]
        bs.append(f1(sel, ra) - f1(sel, rb))
    return {"diff": round(d, 3), "ci": [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)],
            "windows": len(ws)}


def window_bytes(w: Window) -> int:
    """Bytes of the window's 1 s aggregates for all five streams as float32: what the report replaces on the uplink."""
    return WINDOW * len(STREAMS) * 4
