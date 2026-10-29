"""nightly.sh in a sandbox with stubs (no docker, no simulator)."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STUBS = {
    "uv": '''#!/bin/bash
if [ "$1" = run ] && [ "$2" = skylink-sim ]; then
  while [ $# -gt 0 ]; do [ "$1" = --run-id ] && id=$2; shift; done
  mkdir -p runs/$id; echo '{"finished": true}' > runs/$id/summary.json; echo "$id" >> runs/sim-calls.txt
fi
exit 0''',
    "docker": '#!/bin/bash\n[ "$1" = exec ] && printf "Filesystem 1024-blocks Used Available\\nx 100000000 1 90000000 1%% /\\n"\nexit 0',
    "colima": "#!/bin/bash\nexit 0",
    "curl": "#!/bin/bash\nexit 0",
}


def sandbox(tmp: Path, queue: str, default: str) -> Path:
    for d in ("scripts", "config", "runs"):
        (tmp / d).mkdir()
    shutil.copy(ROOT / "scripts/nightly.sh", tmp / "scripts/nightly.sh")
    (tmp / ".env").write_text("")
    (tmp / "config/queue.txt").write_text(queue)
    (tmp / "config/default-queue.txt").write_text(default)
    bindir = tmp / "bin"
    bindir.mkdir()
    for name, body in STUBS.items():
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x"], cwd=tmp, check=True)
    return bindir


def night(tmp: Path, bindir: Path) -> str:
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FORCE": "1", "WINDOW_END": "23:59", "MIN_FREE_GB": "0"}
    subprocess.run(["bash", "scripts/nightly.sh"], cwd=tmp, env=env, check=True, capture_output=True)
    return (tmp / "runs/last-night.txt").read_text()


DEFAULT = "# c\nd-a cfg.toml 3 7 60\nd-locked cfg.toml 103 7 60\nd-b cfg.toml 2 7 60\n"


def test_empty_queue_runs_default_queue_and_records_commit(tmp_path):
    b = sandbox(tmp_path, "# nothing\n", DEFAULT)
    summary = night(tmp_path, b)
    assert "fallback:" in summary and "code: " in summary
    assert (tmp_path / "runs/sim-calls.txt").read_text().split() == ["d-a", "d-b"]   # locked seed refused
    row = (tmp_path / "runs/night-log.tsv").read_text().split("\t")
    assert row[1] == subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert row[3] == "fallback" and row[2] == "yes"


def test_queued_work_means_no_fallback(tmp_path):
    b = sandbox(tmp_path, "q1 cfg.toml 1 7 60\n", DEFAULT)
    night(tmp_path, b)
    assert (tmp_path / "runs/sim-calls.txt").read_text().split() == ["q1"]
    assert (tmp_path / "runs/night-log.tsv").read_text().split("\t")[3] == "queued"


def test_exhausted_default_queue_is_logged_idle_and_unchanged_queue_noted(tmp_path):
    b = sandbox(tmp_path, "", "d-a cfg.toml 3 7 60\n")
    night(tmp_path, b)
    night(tmp_path, b)   # d-a is finished: nothing left to run
    rows = [r.split("\t") for r in (tmp_path / "runs/night-log.tsv").read_text().splitlines()]
    assert [r[3] for r in rows] == ["fallback", "idle"] and rows[1][2] == "no"


def test_default_queue_file_holds_dev_seeds_only():
    for line in (ROOT / "config/default-queue.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            assert int(line.split()[2]) not in range(101, 106)
