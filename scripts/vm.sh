#!/bin/bash
# The colima VM and the Docker stack, on the night host. The VM is on only when something needs it
# (docs/vm-on-demand.md); nightly.sh starts it and stops it again.
#
#   scripts/vm.sh up          start the VM if it is off and wait until Docker answers (bounded)
#   scripts/vm.sh stack       docker compose up -d and wait until InfluxDB is healthy (bounded)
#   scripts/vm.sh down        compose stop, then colima stop, unless a lease or a job still needs it
#   scripts/vm.sh lease [pid] register a user of the VM (default: the caller's pid); down leaves the VM up while that pid
#                             is alive. A job that needs Docker in the night window (the coding bench's sandbox) does:
#                             vm.sh up; vm.sh lease $$; ...work...; vm.sh unlease $$; vm.sh down
#   scripts/vm.sh unlease [pid]
#   scripts/vm.sh state       one word: on / off
#
# Exit 0 on success; up/stack exit 1 with a line on stderr when the wait ran out. Settings (environment or .env):
#   VM_CPU=4 VM_MEMORY=6 VM_DISK=100   VM_WAIT_S=240 (Docker)   INFLUX_WAIT_S=240   VM_LEASE_DIR=runs/vm-leases
set -u
cd "$(dirname "$0")/.."
export PATH=$PATH:/opt/homebrew/bin:/usr/local/bin
[ -f .env ] && { set -a; . ./.env; set +a; }
VM_CPU="${VM_CPU:-4}"; VM_MEMORY="${VM_MEMORY:-6}"; VM_DISK="${VM_DISK:-100}"
VM_WAIT_S="${VM_WAIT_S:-240}"; INFLUX_WAIT_S="${INFLUX_WAIT_S:-240}"
LEASES="${VM_LEASE_DIR:-runs/vm-leases}"
LOG=runs/colima.log
# processes that talk to the stack; a VM stop under them would break the run
BUSY_RE="${VM_BUSY_RE:-skylink-sim run|agent_proposals\.py|agent_eval\.py|verdict\.py|escalate\.py}"

say() { echo "vm: $*" >&2; }
docker_up() { docker info >/dev/null 2>&1; }
vm_on() { colima status >/dev/null 2>&1; }
influx_health() { docker inspect -f '{{.State.Health.Status}}' skylink-influxdb-1 2>/dev/null; }
waitfor() {  # $1 = seconds, rest = command; polls every 3 s
  local n=$1; shift; local t=0
  until "$@"; do [ $t -ge "$n" ] && return 1; sleep 3; t=$((t + 3)); done
}
influx_ok() { [ "$(influx_health)" = healthy ]; }
live_leases() {  # pids with a live lease; stale lease files are removed
  local f p; mkdir -p "$LEASES"
  for f in "$LEASES"/*; do
    [ -e "$f" ] || continue
    p=$(basename "$f")
    if kill -0 "$p" 2>/dev/null; then echo "$p"; else rm -f "$f"; fi
  done
}

case "${1:-}" in
up)
  mkdir -p runs
  if ! vm_on; then
    say "starting colima (cold start)"
    colima start --cpu "$VM_CPU" --memory "$VM_MEMORY" --disk "$VM_DISK" --vm-type vz >> "$LOG" 2>&1 \
      || { say "colima start failed once, retrying"; sleep 5; colima start --cpu "$VM_CPU" --memory "$VM_MEMORY" --disk "$VM_DISK" --vm-type vz >> "$LOG" 2>&1; }
  fi
  waitfor "$VM_WAIT_S" docker_up || { say "Docker did not answer within ${VM_WAIT_S}s (see $LOG)"; exit 1; }
  say "docker ready"
  ;;
stack)
  docker compose up -d >/dev/null 2>&1 || { say "docker compose up failed"; exit 1; }
  waitfor "$INFLUX_WAIT_S" influx_ok || { say "InfluxDB not healthy within ${INFLUX_WAIT_S}s (status: $(influx_health))"; exit 1; }
  say "stack ready"
  ;;
down)
  l=$(live_leases | tr '\n' ' ')
  [ -n "$l" ] && { say "kept up: leased by pid $l"; exit 0; }
  busy=$(pgrep -fl "$BUSY_RE" | grep -v "pgrep" | head -1 | cut -c1-80)
  [ -n "$busy" ] && { say "kept up: still running: $busy"; exit 0; }
  if vm_on; then
    docker compose stop >/dev/null 2>&1 || say "docker compose stop failed (colima stop follows)"
    colima stop >> "$LOG" 2>&1 && say "stopped" || { say "colima stop failed"; exit 1; }
  else
    say "already off"
  fi
  ;;
lease)   mkdir -p "$LEASES"; : > "$LEASES/${2:-$PPID}";;
unlease) rm -f "$LEASES/${2:-$PPID}";;
state)   if vm_on; then echo on; else echo off; fi;;
*) echo "usage: $0 up|stack|down|lease [pid]|unlease [pid]|state" >&2; exit 2;;
esac
