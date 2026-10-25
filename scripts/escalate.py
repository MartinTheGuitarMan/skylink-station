#!/usr/bin/env python3
"""Daily-pass escalation inbox (C5e inbox run; docs/escalation.md).

On the night host (nightly.sh calls these):
    uv run python scripts/escalate.py night      apply answers that arrived, score, then ask for the next queued night
On the day host (the daily pass, docs/daily-loop.md):
    uv run python scripts/escalate.py pending    question files pulled from the night host that have no answers yet
    uv run python scripts/escalate.py show <night>   the questions as text, to answer blind
    uv run python scripts/escalate.py check <night>  validate runs/escalation/outbox/<night>.jsonl before sending
    scripts/night-sync.sh answers                 send the outbox to the night host

config/escalation-queue.txt lines: <night-id>|<seed 11-30>|<days>|<budget>; one new night is asked per run."""
import argparse
import json
import sys
from pathlib import Path

from skylink.agent import inbox

ROOT = Path("runs/escalation")            # on the night host
PULLED = Path("runs/night/escalation")    # on the day host, after night-sync.sh pull
OUTBOX = ROOT / "outbox"                  # on the day host: answers written by the daily pass
QUEUE = Path("config/escalation-queue.txt")


def night(a):
    for p in sorted((ROOT / "inbox").glob("*.jsonl")):
        r = inbox.apply(ROOT, p.stem)
        if r:
            print(f"applied {p.stem}: {r['answers_ok']} answers, {len(r['answers_rejected'])} rejected")
    s = inbox.score(ROOT)
    if s.get("pooled"):
        print(f"scored {s['pooled']['nights']} nights: gain {s['pooled']['gain']:+.3f} {s['pooled']['gain_ci']}")
    if not QUEUE.exists():
        return
    for line in QUEUE.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        nid, seed, days, budget = line.split("|")
        if (ROOT / "inbox" / f"{nid}.jsonl").exists():
            continue
        m = inbox.ask(ROOT, nid, int(seed), float(days), int(budget))
        print(f"asked {nid}: {m['asked']} questions ({m['residue']} residue of {m['alerts']} alerts)")
        return
    print("escalation queue: nothing left to ask")


def pending(a):
    ps = inbox.pending(PULLED, OUTBOX)
    print("\n".join(f"{p.stem}: {sum(1 for _ in p.open())} questions" for p in ps) or "no unanswered questions")


def show(a):
    print(inbox.show(PULLED / "inbox" / f"{a.night}.jsonl"))


def check(a):
    ok, errs = inbox.check_answers(PULLED / "inbox" / f"{a.night}.jsonl", OUTBOX / f"{a.night}.jsonl")
    print(f"{ok} usable answers")
    for e in errs:
        print("  " + e)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("night"); sub.add_parser("pending")
    s = sub.add_parser("show"); s.add_argument("night")
    c = sub.add_parser("check"); c.add_argument("night")
    args = ap.parse_args()
    {"night": night, "pending": pending, "show": show, "check": check}[args.cmd](args)
