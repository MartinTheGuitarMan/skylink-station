"""Daily-pass escalation inbox (C5e inbox run in docs/success-criteria.md; design in docs/escalation.md).

At night the night host simulates one day of a fresh dev seed (11-30), labels every edge alert with the rules sent down and writes
questions for the residue (`ask`). The daily pass on the day host (Claude) answers them blind; `night-sync.sh answers` sends the answers
back. The next night the night host applies them (`apply`) and scores every applied night against the simulator's truth (`score`).

Files under the root (runs/escalation on the night host):
  inbox/<night>.jsonl      questions: facts and the edge's label, never the truth
  ledger/<night>.jsonl     every alert of the night with the edge's label and whether it was asked
  ledger/<night>.meta.json seed, days, budget, asked-at time
  answers/<night>.jsonl    the shore's answers, as received
  final/<night>.json       final labels after applying the answers
  examples.jsonl           answers marked keep_as_example (worked examples for the edge model, later)
  summary.json / summary.md  scores per night and pooled"""
from __future__ import annotations

import json
import time
from pathlib import Path


from . import alerts
from .escalation import EDGE_LABELS, boot_diff, distilled_rules, f1

STREAMS = ["temp", "pressure", "wind", "vibration", "solar"]
INBOX_SEEDS = range(11, 31)
MAX_WHY = 120
KINDS = {"temp": ["spike", "stuck", "drift", "step", "dropout", "seasonal"],
         "pressure": ["spike", "stuck", "drift", "step", "dropout", "front"],
         "wind": ["spike", "stuck", "drift", "step", "dropout", "gust"],
         "vibration": ["spike", "stuck", "drift", "step", "dropout", "burst"],
         "solar": ["spike", "stuck", "drift", "step", "dropout", "seasonal", "cloud"]}


def is_residue(stream: str, ctx: dict) -> bool:
    return stream == "wind" or (stream == "vibration" and ctx["seconds_beyond_threshold_in_2min"] <= 2)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def night_cases(seed: int, days: float) -> list[alerts.Case]:
    assert seed in INBOX_SEEDS, "the inbox uses dev seeds 11-30 only"
    series, plan = alerts.aggregate_series(seed, days, STREAMS)
    cases, _ = alerts.edge_cases(series, plan, seed, len(next(iter(series.values()))))
    return sorted(cases, key=lambda c: (c.second, c.stream))


def ask(root: Path, night: str, seed: int, days: float, budget: int, cases: list[alerts.Case] | None = None) -> dict:
    cases = night_cases(seed, days) if cases is None else cases
    rows = []
    for c in cases:
        rows.append({"q": f"{night}-{c.stream}-{c.second}", "stream": c.stream, "t": c.second, "detector": c.kind,
                     "edge": distilled_rules(c.stream, c.kind, c.context), "residue": is_residue(c.stream, c.context),
                     "asked": False, "facts": {k: v for k, v in c.context.items() if k not in ("stream", "unit")}})
    res = [r for r in rows if r["residue"]]
    for r in ([r for r in res if r["stream"] == "wind"] + [r for r in res if r["stream"] != "wind"])[:budget]:
        r["asked"] = True
    _write_jsonl(root / "inbox" / f"{night}.jsonl",
                 [{"q": r["q"], "stream": r["stream"], "t": r["t"], "detector": r["detector"], "edge": r["edge"],
                   "trigger": "residue", "facts": r["facts"]} for r in rows if r["asked"]])
    _write_jsonl(root / "ledger" / f"{night}.jsonl", [{k: v for k, v in r.items() if k != "facts"} for r in rows])
    meta = {"night": night, "seed": seed, "days": days, "budget": budget, "asked_at": time.time(),
            "alerts": len(rows), "residue": len(res), "asked": sum(r["asked"] for r in rows)}
    (root / "ledger" / f"{night}.meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def check_answer(a: dict, questions: dict) -> str:
    """'' when the answer is usable, else why not."""
    q = questions.get(a.get("q"))
    if q is None:
        return "unknown question"
    if a.get("label") not in EDGE_LABELS:
        return f"label {a.get('label')!r} not allowed"
    if a.get("kind") not in (None, "", *KINDS[q["stream"]]):
        return f"kind {a.get('kind')!r} not possible on {q['stream']}"
    if not isinstance(a.get("why", ""), str) or len(a.get("why", "")) > MAX_WHY:
        return "why missing or too long"
    if not isinstance(a.get("keep_as_example", False), bool):
        return "keep_as_example must be true or false"
    return ""


def check_answers(questions_path: Path, answers_path: Path) -> tuple[int, list[str]]:
    qs = {q["q"]: q for q in _jsonl(questions_path)}
    ans = _jsonl(answers_path)
    errs = [f"{a.get('q')}: {w}" for a in ans if (w := check_answer(a, qs))]
    missing = sorted(set(qs) - {a.get("q") for a in ans})
    errs += [f"{m}: no answer" for m in missing]
    return len(ans) - sum(1 for e in errs if not e.endswith("no answer")), errs


def apply(root: Path, night: str) -> dict | None:
    """Merge the answers for a night into final labels. None when there are no answers yet or the night is already applied."""
    ans_path, out = root / "answers" / f"{night}.jsonl", root / "final" / f"{night}.json"
    if not ans_path.exists() or out.exists():
        return None
    qs = {q["q"]: q for q in _jsonl(root / "inbox" / f"{night}.jsonl")}
    ledger = _jsonl(root / "ledger" / f"{night}.jsonl")
    good, bad = {}, []
    for a in _jsonl(ans_path):
        why = check_answer(a, qs)
        (bad.append({"q": a.get("q"), "why": why}) if why else good.__setitem__(a["q"], a))
    rows = []
    for r in ledger:
        a = good.get(r["q"])
        rows.append({**r, "answer": a["label"] if a else None, "final": a["label"] if a else r["edge"]})
    examples = [{**qs[q], "label": a["label"], "kind": a.get("kind"), "why": a.get("why", "")}
                for q, a in good.items() if a.get("keep_as_example")]
    if examples:
        with (root / "examples.jsonl").open("a") as f:
            f.writelines(json.dumps(e) + "\n" for e in examples)
    res = {"night": night, "applied_at": time.time(), "answers_ok": len(good), "answers_rejected": bad, "rows": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res))
    return res


def truth_for(seed: int, days: float) -> dict[tuple[str, int], str]:
    return {(c.stream, c.second): c.label for c in night_cases(seed, days)}


def score(root: Path, truth_fn=truth_for) -> dict:
    nights, pooled_t, pooled_e, pooled_f = [], [], [], []
    for p in sorted((root / "final").glob("*.json")):
        fin = json.loads(p.read_text())
        meta = json.loads((root / "ledger" / f"{fin['night']}.meta.json").read_text())
        truth = truth_fn(meta["seed"], meta["days"])
        t = [truth[(r["stream"], r["t"])] for r in fin["rows"]]
        e = [r["edge"] for r in fin["rows"]]
        fl = [r["final"] for r in fin["rows"]]
        asked = [(tt, r) for tt, r in zip(t, fin["rows"]) if r["answer"] is not None]
        nights.append({"night": fin["night"], "seed": meta["seed"], "alerts": len(t), "asked": meta["asked"],
                       "answered": len(asked), "rejected": len(fin["answers_rejected"]),
                       "edge_f1": round(f1(t, e), 3), "final_f1": round(f1(t, fl), 3),
                       "answer_accuracy": round(sum(tt == r["answer"] for tt, r in asked) / len(asked), 3) if asked else None,
                       "edge_accuracy_on_asked": round(sum(tt == r["edge"] for tt, r in asked) / len(asked), 3) if asked else None,
                       "fixed": sum(1 for tt, r in asked if r["edge"] != tt and r["answer"] == tt),
                       "broke": sum(1 for tt, r in asked if r["edge"] == tt and r["answer"] != tt),
                       "hours_to_apply": round((fin["applied_at"] - meta["asked_at"]) / 3600, 1)})
        pooled_t += t; pooled_e += e; pooled_f += fl
    out = {"nights": nights}
    if nights:
        out["pooled"] = {"nights": len(nights), "alerts": len(pooled_t), "edge_f1": round(f1(pooled_t, pooled_e), 3),
                         "final_f1": round(f1(pooled_t, pooled_f), 3),
                         "gain": round(f1(pooled_t, pooled_f) - f1(pooled_t, pooled_e), 3),
                         "gain_ci": boot_diff(pooled_t, pooled_f, pooled_e),
                         "fixed": sum(n["fixed"] for n in nights), "broke": sum(n["broke"] for n in nights)}
        out["pooled"]["readable"] = len(nights) >= 5
    root.mkdir(parents=True, exist_ok=True)                                       # first night: nothing asked yet
    (root / "summary.json").write_text(json.dumps(out, indent=1))
    lines = ["| night | seed | alerts | asked | answered | edge F1 | final F1 | answer acc | edge acc on asked | fixed / broke | h to apply |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in nights:
        lines.append(f"| {n['night']} | {n['seed']} | {n['alerts']} | {n['asked']} | {n['answered']} | {n['edge_f1']} | {n['final_f1']} | "
                     f"{n['answer_accuracy']} | {n['edge_accuracy_on_asked']} | {n['fixed']} / {n['broke']} | {n['hours_to_apply']} |")
    if nights:
        p = out["pooled"]
        lines.append(f"\nPooled over {p['nights']} nights ({p['alerts']} alerts): edge {p['edge_f1']}, final {p['final_f1']}, "
                     f"gain {p['gain']:+.3f} {p['gain_ci']}; fixed {p['fixed']}, broke {p['broke']}"
                     + ("" if p["readable"] else " (fewer than 5 nights: not read yet)"))
    (root / "summary.md").write_text("\n".join(lines) + "\n")
    return out


def pending(inbox_root: Path, outbox: Path) -> list[Path]:
    """Question files that have no answers file in the outbox yet (for the daily pass)."""
    return [p for p in sorted((inbox_root / "inbox").glob("*.jsonl")) if not (outbox / p.name).exists()]


def show(path: Path) -> str:
    """Questions as compact text for the shore to read (one block per question)."""
    out = []
    for q in _jsonl(path):
        facts = "; ".join(f"{k}={v}" for k, v in q["facts"].items())
        out.append(f"{q['q']} | {q['stream']} | detector={q['detector']} | edge={q['edge']} | {facts}")
    return "\n".join(out)

