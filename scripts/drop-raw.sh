#!/bin/bash
# Delete the raw sensor points of runs whose purpose is served (scored, written up, or void), on the night host.
# Keeps each run's truth events (C3/C4 need them) and all forecasts. Refuses locked runs. The simulator can recreate the raw
# data of any run from its seed (C7). InfluxDB frees the space at its next compactions, not at once.
#   scripts/drop-raw.sh night-smoke-1 base-smoke-1 ...          (run on the night host, in the repo)
set -eu
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export PATH=/opt/homebrew/bin:$PATH
# the VM is off by day (docs/vm-on-demand.md): start it and the stack for this job, and stop it again if it was off
started_vm=0
if [ "$(scripts/vm.sh state)" = off ]; then
  scripts/vm.sh up && scripts/vm.sh stack || { echo "could not start the Docker VM" >&2; scripts/vm.sh down; exit 1; }
  started_vm=1
fi
scripts/vm.sh lease $$
trap 'scripts/vm.sh unlease $$; [ $started_vm = 1 ] && scripts/vm.sh down' EXIT
[ $# -gt 0 ] || { echo "usage: $0 <run-id>..." >&2; exit 2; }
for run in "$@"; do
  case "$run" in locked*) echo "refusing locked run $run" >&2; exit 1;; esac
  docker exec skylink-influxdb-1 influx delete --org "$INFLUX_ORG" --token "$INFLUX_TOKEN" --bucket raw \
    --start 2025-01-01T00:00:00Z --stop 2027-01-01T00:00:00Z --predicate "_measurement=\"sensor\" AND run=\"$run\""
  echo "deleted raw sensor points of $run"
done
docker exec skylink-influxdb-1 df -h /var/lib/influxdb2 | tail -1
