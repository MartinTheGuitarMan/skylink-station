"""scripts/missed_passes.py: nights that ran without a daily pass."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import missed_passes as M  # noqa: E402


def test_missed_passes_from_log_and_journal(tmp_path):
    log = tmp_path / "log.tsv"
    log.write_text("2026-10-25\tabc\tyes\tqueued\t\tf1\n2026-10-26\tabc\tno\tidle\t\tf1\n"
                   "2026-10-27\tabc\tno\tfallback\t\tf1\n2026-10-27\tabc\tno\tfallback\t\tf1\n2026-10-29\tdef\tyes\tqueued\t\tf2\n")
    j = "Night 2026-10-25/26: no finding. Nights 2026-10-26/27 to 2026-10-28/29: nothing ran."
    assert M.journal_nights(j) == ["2026-10-25", "2026-10-26", "2026-10-28"]
    rows = M.read_log(log)
    assert [r["date"] for r in M.missed(rows, ["2026-10-25"])] == ["2026-10-26", "2026-10-27"]
    assert M.missed(rows, ["2026-10-29"]) == []
