"""nightly.sh and vm.sh: the colima VM is started for the night and stopped after it (stubs, no docker)."""
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STUBS = {
    # sim: finish the run (or hang when SIM_HANG is set, to test a stop while a job runs)
    "uv": '''#!/bin/bash
if [ "$1" = run ] && [ "$2" = skylink-sim ]; then
  while [ $# -gt 0 ]; do [ "$1" = --run-id ] && id=$2; shift; done
  [ -n "${SIM_HANG:-}" ] && exec sleep 37
  mkdir -p runs/$id; echo '{"finished": true}' > runs/$id/summary.json
fi
exit 0''',
    "docker": '''#!/bin/bash
echo "docker $*" >> "$CALLS"
case "$1" in
  info) [ -z "${DOCKER_DOWN:-}" ]; exit $?;;
  inspect) echo "${INFLUX_STATE:-healthy}";;
  compose) [ "$2 $COMPOSE_FAIL" = "up up" ] && exit 1; exit 0;;
  exec) [ -n "${VM_DISK_DEAD:-}" ] && { echo "OCI runtime exec failed: input/output error"; exit 1; }
        printf "Filesystem 1024-blocks Used Available\\nx 100000000 1 90000000 1%% /\\n";;
esac
exit 0''',
    # colima keeps its state in a file: status fails while off
    "colima": '''#!/bin/bash
echo "colima $1" >> "$CALLS"
case "$1" in
  status) [ -f "$VMSTATE" ];;
  start) touch "$VMSTATE";;
  stop) rm -f "$VMSTATE";;
esac''',
    "curl": "#!/bin/bash\nexit 0",
}


def sandbox(tmp: Path) -> Path:
    for d in ("scripts", "config", "runs"):
        (tmp / d).mkdir()
    for f in ("nightly.sh", "vm.sh"):
        shutil.copy(ROOT / "scripts" / f, tmp / "scripts" / f)
    (tmp / ".env").write_text("")
    (tmp / "config/queue.txt").write_text("q1 cfg.toml 1 7 60\n")
    (tmp / "config/default-queue.txt").write_text("")
    bindir = tmp / "bin"
    bindir.mkdir()
    for name, body in STUBS.items():
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x"], cwd=tmp, check=True)
    return bindir


def env_for(tmp: Path, bindir: Path, **extra) -> dict:
    return {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FORCE": "1", "WINDOW_END": "23:59", "MIN_FREE_GB": "0", "MIN_SIM_FREE_GB": "0",
            "CALLS": str(tmp / "calls.txt"), "VMSTATE": str(tmp / "vm-on"), "VM_WAIT_S": "0", "INFLUX_WAIT_S": "0",
            "VM_BUSY_RE": "sleep 37", **extra}


def night(tmp: Path, bindir: Path, **extra) -> tuple[int, str, list[str]]:
    p = subprocess.run(["bash", "scripts/nightly.sh"], cwd=tmp, env=env_for(tmp, bindir, **extra), capture_output=True)
    calls = (tmp / "calls.txt").read_text().splitlines() if (tmp / "calls.txt").exists() else []
    return p.returncode, (tmp / "runs/last-night.txt").read_text(), calls


def test_night_starts_the_vm_cold_and_stops_it_after(tmp_path):
    b = sandbox(tmp_path)
    rc, summary, calls = night(tmp_path, b)
    assert rc == 0 and "sim q1: ok" in summary
    assert calls.index("colima start") < calls.index("docker compose up -d")
    assert calls.index("docker compose stop") < calls.index("colima stop")
    assert "vm disk at end: influx data" in summary   # sizes are read before the VM goes off
    assert "vm: stopped" in summary and summary.splitlines()[-1].startswith("end ")
    assert not (tmp_path / "vm-on").exists()


def test_switch_off_leaves_the_vm_running(tmp_path):
    b = sandbox(tmp_path)
    _, summary, calls = night(tmp_path, b, VM_STOP_AFTER_NIGHT="0")
    assert "colima stop" not in calls and "docker compose stop" not in calls and (tmp_path / "vm-on").exists()
    assert "vm: stopped" not in summary


def test_vm_already_on_is_not_restarted(tmp_path):
    b = sandbox(tmp_path)
    (tmp_path / "vm-on").touch()
    _, _, calls = night(tmp_path, b)
    assert "colima start" not in calls and "colima stop" in calls


def test_stack_failure_still_stops_the_vm(tmp_path):
    b = sandbox(tmp_path)
    rc, summary, calls = night(tmp_path, b, COMPOSE_FAIL="up")
    assert rc == 1 and "failed: docker stack not available" in summary
    assert "colima stop" in calls and not (tmp_path / "vm-on").exists()


def test_docker_never_answering_is_a_visible_failed_night(tmp_path):
    b = sandbox(tmp_path)
    rc, summary, calls = night(tmp_path, b, DOCKER_DOWN="1")
    assert rc == 1 and "failed: docker VM did not start" in summary and "Docker did not answer" in summary
    assert (tmp_path / "runs/night-log.tsv").exists()          # the night is logged, not missing
    assert "docker compose up -d" not in calls and "colima stop" in calls


def test_influx_never_healthy_is_a_visible_failed_night(tmp_path):
    b = sandbox(tmp_path)
    rc, summary, _ = night(tmp_path, b, INFLUX_STATE="starting")
    assert rc == 1 and "InfluxDB not healthy" in summary and "failed: docker stack not available" in summary


def test_vm_disk_that_does_not_answer_stops_the_simulations(tmp_path):
    b = sandbox(tmp_path)                                       # the VM disk broke on 2026-10-30/31 with InfluxDB still reported as up
    (tmp_path / "config/queue.txt").write_text("q1 cfg.toml 101 7 60\n")
    _, summary, _ = night(tmp_path, b, VM_DISK_DEAD="1")
    assert "sim queue skipped: VM disk unreadable" in summary and "sim q1" not in summary


def test_host_disk_without_room_for_a_run_stops_the_simulations(tmp_path):
    b = sandbox(tmp_path)
    (tmp_path / "config/default-queue.txt").write_text("d-a cfg.toml 3 7 60\n")
    _, summary, _ = night(tmp_path, b, MIN_SIM_FREE_GB="100000000")
    assert "sim queue skipped: disk low for a simulation" in summary and "sim q1" not in summary and "sim d-a" not in summary


def test_simulation_is_told_when_to_stop_for_disk(tmp_path):
    b = sandbox(tmp_path)
    (b / "uv").write_text('#!/bin/bash\necho "$*" >> runs/sim-args.txt\nexit 0')
    night(tmp_path, b, MIN_RUN_FREE_GB="7")
    assert "--min-free-gb 7" in (tmp_path / "runs/sim-args.txt").read_text()


def test_early_stop_before_start_does_not_touch_the_vm(tmp_path):
    b = sandbox(tmp_path)
    (tmp_path / "vm-on").touch()
    _, summary, calls = night(tmp_path, b, MIN_FREE_GB="100000000")
    assert "not started" in summary and calls == [] and (tmp_path / "vm-on").exists()


def test_live_lease_keeps_the_vm_up_and_a_stale_one_does_not(tmp_path):
    b = sandbox(tmp_path)
    holder = subprocess.Popen(["sleep", "20"])
    try:
        leases = tmp_path / "runs/vm-leases"
        leases.mkdir()
        (leases / str(holder.pid)).touch()
        (leases / "999999").touch()                             # no such process
        _, summary, calls = night(tmp_path, b)
        assert "colima stop" not in calls and f"leased by pid {holder.pid}" in summary
        assert not (leases / "999999").exists()
        holder.kill(); holder.wait()
        _, summary, calls = night(tmp_path, b)
        assert "colima stop" in calls
    finally:
        holder.kill()


def test_terminated_night_keeps_the_vm_while_its_sim_still_runs(tmp_path):
    b = sandbox(tmp_path)
    p = subprocess.Popen(["bash", "scripts/nightly.sh"], cwd=tmp_path, env=env_for(tmp_path, b, SIM_HANG="1"),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        for _ in range(100):                                    # wait until the sim stub runs
            if subprocess.run(["pgrep", "-f", "sleep 37"], capture_output=True).returncode == 0:
                break
            time.sleep(0.1)
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=20)
        summary = (tmp_path / "runs/last-night.txt").read_text()
        assert "kept up: still running" in summary and (tmp_path / "vm-on").exists()
    finally:
        subprocess.run(["pkill", "-f", "sleep 37"])
        p.kill()


def test_status_says_vm_off_instead_of_failing(tmp_path):
    b = sandbox(tmp_path)
    shutil.copy(ROOT / "scripts/night-sync.sh", tmp_path / "scripts/night-sync.sh")
    (b / "ssh").write_text('#!/bin/bash\nshift 3\ncmd="$*"; exec bash -c "${cmd//\\/opt\\/homebrew\\/bin:/}"\n')   # "the night host" is the sandbox itself, minus a real Homebrew
    (b / "ssh").chmod(0o755)
    (tmp_path / "runs/last-night.txt").write_text("vm disk at end: influx data 49G; VM disk 40 GB free of 98\n")
    env = env_for(tmp_path, b, NIGHT_HOST="night", NIGHT_DIR=str(tmp_path))
    off = subprocess.run(["bash", "scripts/night-sync.sh", "status"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert off.returncode == 0 and "VM off" in off.stdout and "vm disk at end" in off.stdout
    assert "docker exec" not in (tmp_path / "calls.txt").read_text() if (tmp_path / "calls.txt").exists() else True
    (tmp_path / "vm-on").touch()
    on = subprocess.run(["bash", "scripts/night-sync.sh", "status"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert on.returncode == 0 and "VM off" not in on.stdout and "VM disk (InfluxDB): 85 GB free" in on.stdout
