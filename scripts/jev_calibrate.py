#!/usr/bin/env python3
"""Ask the local Jev server directly (same question mcp-minions sends) to get its probabilities, then show
accuracy against coverage: does confidence pick out the cases it gets right? DEV cases only."""
import json
import sys
from pathlib import Path

import httpx

from skylink.agent import alerts
from skylink.agent.jobs import DESCRIPTIONS, TRIAGE_HINT

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/v1/systemone"
cases = alerts.balanced([alerts.Case(**c) for c in json.loads(Path("runs/agent/cases.json").read_text())], 216, seed=7)
rows = []
with httpx.Client(timeout=60) as cl:
    for c in cases:
        body = {"model": "jev-style-0.8b-decision-v3", "state": c.text(),
                "questions": {"label": {"type": "choice", "instructions": TRIAGE_HINT, "criteria": DESCRIPTIONS}}}
        a = cl.post(URL, json=body).json()["answers"]["label"]
        rows.append({"id": c.id, "truth": c.label, "rules": alerts.rules_baseline(c), "choice": a["choice"],
                     "conf": a.get("confidence"), "probs": a.get("probabilities")})
Path("runs/agent/jev-probs.json").write_text(json.dumps(rows))
print("sample:", rows[0])
rows.sort(key=lambda r: -(r["conf"] or 0))
for q in (0.2, 0.4, 0.6, 0.8, 1.0):
    top = rows[: int(len(rows) * q)]
    print(f"top {int(q*100):3d}% by confidence: n={len(top)} accuracy={sum(r['choice']==r['truth'] for r in top)/len(top):.3f} "
          f"min_conf={top[-1]['conf']:.3f}")
