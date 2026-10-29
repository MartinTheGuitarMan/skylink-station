"""Which nights ran without a daily pass? Read by the daily pass after `night-sync.sh pull` (docs/night-fallback.md).

    uv run python scripts/missed_passes.py [--log runs/night/night-log.tsv] [--journal JOURNAL.md] [--main-commits]

runs/night-log.tsv is appended by nightly.sh: date, commit, queue_changed, mode, note, queue fingerprint. A night is a
missed pass when it ran after the last journaled night and either the queues did not change since the night before
(nobody queued anything) or it ran the fallback or nothing. Prints a line ready for the journal; changes nothing.
"""
import argparse
import re
import subprocess
from pathlib import Path


def journal_nights(text: str) -> list[str]:
    """Start dates (YYYY-MM-DD) of every night the journal mentions, as `Night 2026-10-25/26` or `Nights A to B`."""
    return sorted(set(re.findall(r"Nights? (\d{4}-\d{2}-\d{2})", text)) | set(re.findall(r" to (\d{4}-\d{2}-\d{2})/", text)))


def read_log(path: Path) -> list[dict]:
    rows: dict[str, dict] = {}
    for line in path.read_text().splitlines() if path.exists() else []:
        f = line.split("\t")
        if len(f) >= 4:
            rows[f[0]] = {"date": f[0], "commit": f[1], "queue_changed": f[2], "mode": f[3]}   # last line of a date wins
    return [rows[d] for d in sorted(rows)]


def missed(rows: list[dict], journaled: list[str]) -> list[dict]:
    last = journaled[-1] if journaled else ""
    return [r for r in rows if r["date"] > last and (r["queue_changed"] == "no" or r["mode"] in ("fallback", "idle"))]


def behind(commit: str) -> str:
    c = commit.split("+")[0]
    r = subprocess.run(["git", "rev-list", "--count", f"{c}..main"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "?"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="runs/night/night-log.tsv")
    ap.add_argument("--journal", default="JOURNAL.md")
    ap.add_argument("--main-commits", action="store_true", help="also count the commits the night host's code lacks (needs git)")
    a = ap.parse_args()
    rows = read_log(Path(a.log))
    journaled = journal_nights(Path(a.journal).read_text())
    m = missed(rows, journaled)
    if not m:
        print("no missed passes")
        return
    parts = []
    for r in m:
        s = f"{r['date']} ({r['mode']}, code {r['commit']}"
        if a.main_commits:
            s += f", {behind(r['commit'])} behind main"
        parts.append(s + ")")
    print(f"Missed passes: {len(m)} night(s) ran without new work: " + "; ".join(parts) + ".")


if __name__ == "__main__":
    main()
