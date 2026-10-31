"""Cold export: fake query source, no InfluxDB, no real Cold volume."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from skylink import coldexport as ce

ROOT = Path(__file__).resolve().parents[1]
H = 3_600_000_000


class Fake:
    """Two streams over 3 hours; `a` has one field, `b` has two. Optional faults."""
    def __init__(self, drop_one=False, die_after=None):
        self.drop_one, self.die_after, self.calls = drop_one, die_after, 0
        self.n = {"a": 2500, "b": 1000}
        self.t0 = 1_700_000_000_000_000

    def streams(self, run):
        return ["a", "b"]

    def span_us(self, run, stream):
        return self.t0, self.t0 + 2 * H + 5

    def _all(self, stream):
        n = self.n[stream]
        times = [self.t0 + i * (2 * H // n) for i in range(n)]
        cols = {"value": [i * 0.5 for i in range(n)]}
        if stream == "b":
            cols["aux"] = [float(i) for i in range(n)]
        return times, cols

    def chunks(self, run, stream, a, b):
        self.calls += 1
        if self.die_after is not None and self.calls > self.die_after:
            raise RuntimeError("influx went away")
        times, cols = self._all(stream)
        idx = [i for i, t in enumerate(times) if a <= t < b]
        if self.drop_one and stream == "a" and idx and a == self.t0 - self.t0 % H:
            idx = idx[1:]
        if idx:
            yield ce.Chunk([times[i] for i in idx], {k: [v[i] for i in idx] for k, v in cols.items()})


@pytest.fixture
def env(tmp_path):
    cold, runs = tmp_path / "Cold", tmp_path / "runs"
    cold.mkdir()
    def summary(run="dev-1", **kw):
        (runs / run).mkdir(parents=True, exist_ok=True)
        s = {"run": run, "finished": True, "hash": "h", "emitted": {"a": 2500, "b": 1000}, **kw}
        (runs / run / "summary.json").write_text(json.dumps(s))
    summary()
    return cold, runs, summary


def do(src, env, run="dev-1", **kw):
    cold, runs, _ = env
    return ce.export_run(src, run, cold, runs, require_mount=False, **kw)


def test_export_roundtrip(env):
    cold = env[0]
    m = do(Fake(), env)
    d = cold / "skylink" / "dev-1"
    assert {k: v["points"] for k, v in m["streams"].items()} == {"a": 2500, "b": 1000}
    t = pq.read_table(d / "b.parquet")
    assert t.column_names == ["aux", "time_us", "value"] or set(t.column_names) == {"time_us", "aux", "value"}
    assert t.num_rows == 1000 and pq.ParquetFile(d / "a.parquet").metadata.row_group(0).column(0).compression == "ZSTD"
    assert (d / "SHA256SUMS").read_text().count("\n") == 3          # a, b, manifest
    assert not list((cold / "skylink").glob(".partial-*"))
    assert ce.verify_dir(d, json.loads((env[1] / "dev-1/summary.json").read_text()), "dev-1")["run"] == "dev-1"


def test_chunked_into_row_groups(env):
    do(Fake(), env)
    assert pq.ParquetFile(env[0] / "skylink/dev-1/a.parquet").num_row_groups == 3     # one per hour window


def test_missing_volume(env, tmp_path):
    with pytest.raises(ce.ExportError, match="not mounted"):
        ce.export_run(Fake(), "dev-1", tmp_path / "nothere", env[1])
    with pytest.raises(ce.ExportError, match="not mounted"):       # exists but is not a mount point
        ce.export_run(Fake(), "dev-1", env[0], env[1])


def test_interrupted_export_never_looks_finished(env):
    cold = env[0]
    with pytest.raises(RuntimeError):
        do(Fake(die_after=4), env)
    assert not (cold / "skylink" / "dev-1").exists() and not list((cold / "skylink").glob(".partial-*"))
    do(Fake(), env)                                              # a retry works
    assert (cold / "skylink" / "dev-1" / "manifest.json").exists()


def test_killed_export_leaves_only_a_partial_dir_which_a_retry_clears(env):
    cold = env[0]
    stale = cold / "skylink" / ".partial-dev-1-999"
    stale.mkdir(parents=True)
    (stale / "a.parquet").write_bytes(b"half")
    assert not (cold / "skylink" / "dev-1").exists()
    do(Fake(), env)
    assert not stale.exists()


def test_count_mismatch_is_refused(env):
    cold = env[0]
    with pytest.raises(ce.ExportError, match="summary.json expects 2500"):
        do(Fake(drop_one=True), env)
    assert not (cold / "skylink" / "dev-1").exists()


def test_overflow_drops_are_subtracted_like_c8(env):
    env[2](overflow_dropped={"a": 1})
    do(Fake(drop_one=True), env)


def test_not_finished_and_locked(env):
    env[2]("dev-2", finished=False)
    with pytest.raises(ce.ExportError, match="not finished"):
        do(Fake(), env, run="dev-2")
    env[2]("locked-101")
    with pytest.raises(ce.ExportError, match="locked"):
        do(Fake(), env, run="locked-101")
    do(Fake(), env, run="locked-101", allow_locked=True)


def test_existing_export_is_not_overwritten(env):
    do(Fake(), env)
    with pytest.raises(ce.ExportError, match="already exported"):
        do(Fake(), env)


def test_verify_catches_corruption(env):
    d = env[0] / "skylink" / "dev-1"
    do(Fake(), env)
    s = json.loads((env[1] / "dev-1/summary.json").read_text())
    ce.verify_dir(d, s, "dev-1")
    with open(d / "a.parquet", "r+b") as f:
        f.seek(40); f.write(b"\xff\xff")
    with pytest.raises(ce.ExportError, match="checksum"):
        ce.verify_dir(d, s, "dev-1")


def test_verify_catches_summary_drift(env):
    do(Fake(), env)
    s = {"emitted": {"a": 2501, "b": 1000}}
    with pytest.raises(ce.ExportError, match="expects 2501"):
        ce.verify_dir(env[0] / "skylink" / "dev-1", s, "dev-1")


def test_time_parse():
    assert ce._parse_time_us("2023-11-14T22:13:20.123456789Z") == 1_700_000_000_123_456
    assert ce._parse_time_us("2023-11-14T22:13:20Z") == 1_700_000_000_000_000


# ---- drop-raw.sh refuses a run without a verified export -------------------------------------------------------------

def drop_sandbox(tmp):
    for d in ("scripts", "runs", "bin"):
        (tmp / d).mkdir()
    shutil.copy(ROOT / "scripts/drop-raw.sh", tmp / "scripts")
    (tmp / ".env").write_text("INFLUX_ORG=o\nINFLUX_TOKEN=secret-token\n")
    for n, body in {
        "vm.sh": '#!/bin/bash\necho "vm $*" >> "$CALLS"\n[ "$1" = state ] && echo on\nexit 0\n',
    }.items():
        (tmp / "scripts" / n).write_text(body); (tmp / "scripts" / n).chmod(0o755)
    stubs = {
        "docker": '#!/bin/bash\necho "docker $*" >> "$CALLS"\nexit 0\n',
        # uv run python ... -> the project's interpreter, so the real verify runs
        "uv": f'#!/bin/bash\nshift 2; PYTHONPATH={ROOT}/src exec {sys.executable} "$@"\n',
    }
    for n, body in stubs.items():
        (tmp / "bin" / n).write_text(body); (tmp / "bin" / n).chmod(0o755)


def drop(tmp, cold, *runs):
    env = {**os.environ, "PATH": f"{tmp}/bin:{os.environ['PATH']}", "CALLS": str(tmp / "calls.txt"), "COLD_ROOT": str(cold)}
    p = subprocess.run(["bash", "scripts/drop-raw.sh", *runs], cwd=tmp, env=env, capture_output=True, text=True)
    calls = (tmp / "calls.txt").read_text() if (tmp / "calls.txt").exists() else ""
    return p, calls


def test_drop_raw_refuses_without_verified_export(env, tmp_path, monkeypatch):
    cold, runs, _ = env
    sb = tmp_path / "repo"; sb.mkdir(); drop_sandbox(sb)
    shutil.copytree(runs, sb / "runs", dirs_exist_ok=True)
    # the sandbox cold volume is not a mount point, so verify itself refuses: no docker call, VM untouched
    p, calls = drop(sb, cold, "dev-1")
    assert p.returncode == 1 and "no verified cold export" in p.stderr
    assert "docker" not in calls and "vm " not in calls
    assert "secret-token" not in p.stdout + p.stderr


def test_drop_raw_deletes_after_verified_export(env, tmp_path, monkeypatch):
    cold, runs, _ = env
    do(Fake(), env)
    sb = tmp_path / "repo"; sb.mkdir(); drop_sandbox(sb)
    shutil.copytree(runs, sb / "runs", dirs_exist_ok=True)
    # make the temp dir count as a mount point for the child process too
    (sb / "mounted.py").write_text(
        "import os, sys\nos.path.ismount = lambda p: True\nsys.path.insert(0, %r)\n"
        "from skylink.coldexport import main\nsys.exit(main(sys.argv[1:]))\n" % str(ROOT / "src"))
    (sb / "bin" / "uv").write_text(f"#!/bin/bash\n# uv run python -m skylink.coldexport <args>\nexec {sys.executable} {sb}/mounted.py \"${{@:5}}\"\n")
    p, calls = drop(sb, cold, "dev-1")
    assert p.returncode == 0, p.stderr
    assert "influx delete" in calls
    # damage the export: refused again
    with open(cold / "skylink/dev-1/a.parquet", "r+b") as f:
        f.seek(40); f.write(b"\xff\xff")
    (sb / "calls.txt").unlink()
    p, calls = drop(sb, cold, "dev-1")
    assert p.returncode == 1 and "influx delete" not in calls


def test_cold_export_script_refusals(tmp_path):
    sb = tmp_path / "repo"; (sb / "scripts").mkdir(parents=True); (sb / "bin").mkdir()
    shutil.copy(ROOT / "scripts/cold-export.sh", sb / "scripts")
    (sb / "bin/docker").write_text("#!/bin/bash\necho docker >> $CALLS\n"); (sb / "bin/docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{sb}/bin:{os.environ['PATH']}", "COLD_ROOT": str(tmp_path / "Cold"), "CALLS": str(sb / "calls")}
    def run(*a):
        return subprocess.run(["bash", "scripts/cold-export.sh", *a], cwd=sb, env=env, capture_output=True, text=True)
    p = run("locked-101")
    assert p.returncode == 1 and "locked run" in p.stderr
    p = run("dev-1")
    assert p.returncode == 1 and "not mounted" in p.stderr
    assert not (sb / "calls").exists()
