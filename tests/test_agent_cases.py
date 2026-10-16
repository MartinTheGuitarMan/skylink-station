import json
import subprocess
from pathlib import Path

from skylink.agent import linkmodel

ROOT = Path(__file__).resolve().parent.parent


def test_link_model_matches_the_nodered_gate():
    for seed in (1, 2, 7):
        inp = {"seed": seed, "seconds": 4000, "hz": 1,
               "cfg": {"mean_up_s": 60, "mean_down_s": 40, "backfill_chunk_points": 100,
                       "backfill_shuffle_window": 6, "max_buffer_points": 10**9}}
        out = subprocess.run(["node", str(ROOT / "tests/gate_harness.mjs")], input=json.dumps(inp),
                             capture_output=True, text=True, check=True, cwd=ROOT).stdout
        js = [(int(x.split("@")[1].split(".")[0]), 0 if x.startswith("up=0") else 1) for x in json.loads(out)["trace"]]
        # the gate steps the chain per batch end (1 s here), so every transition is seen at its own second
        py = linkmodel.schedule(seed, 3999, 60, 40)
        assert js == py[: len(js)] and len(js) > 10
