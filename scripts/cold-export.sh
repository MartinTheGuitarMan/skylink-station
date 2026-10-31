#!/bin/bash
# Export one run's raw sensor points from InfluxDB to cold storage (zstd Parquet + manifest + SHA-256), verify, then publish.
# Reads only: nothing is deleted (scripts/drop-raw.sh does that, and only for a run with a verified export).
# Refuses when the Cold volume is not mounted, the run is not finished, or the id starts with "locked" (unless --allow-locked,
# which is for after the locked verdict is written). Rule: docs/daily-loop.md, "Raw data retention".
#   scripts/cold-export.sh <run-id> [--allow-locked]          (run on the night host, in the repo)
#   scripts/cold-export.sh --verify <run-id>                  (offline check of an existing export; no VM needed)
# COLD_ROOT overrides the volume path (default /Volumes/Cold). Run summaries are read from runs/<run>/summary.json.
set -eu
cd "$(dirname "$0")/.."
export PATH=$PATH:/opt/homebrew/bin
if [ "${1:-}" = --verify ]; then
  [ $# -eq 2 ] || { echo "usage: $0 --verify <run-id>" >&2; exit 2; }
  exec uv run python -m skylink.coldexport verify "$2"
fi
[ $# -ge 1 ] || { echo "usage: $0 <run-id> [--allow-locked] | --verify <run-id>" >&2; exit 2; }
run=$1; shift
# cheap refusals first, before the VM is started (the Python module repeats them)
COLD="${COLD_ROOT:-/Volumes/Cold}"
case "$run" in locked*) case " $* " in *" --allow-locked "*) ;; *) echo "cold-export: refusing locked run $run without --allow-locked" >&2; exit 1;; esac;; esac
mount | grep -q " on $COLD " || { echo "cold-export: cold volume not mounted at $COLD" >&2; exit 1; }
[ -f "runs/$run/summary.json" ] || { echo "cold-export: no runs/$run/summary.json" >&2; exit 1; }
set -a; . ./.env; set +a      # INFLUX_URL/ORG/TOKEN; values are never printed
started_vm=0
if [ "$(scripts/vm.sh state)" = off ]; then
  scripts/vm.sh up && scripts/vm.sh stack || { echo "could not start the Docker VM" >&2; scripts/vm.sh down; exit 1; }
  started_vm=1
fi
scripts/vm.sh lease $$
trap 'scripts/vm.sh unlease $$; [ $started_vm = 1 ] && scripts/vm.sh down' EXIT
uv run python -m skylink.coldexport export "$run" "$@"
