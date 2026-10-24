#!/bin/bash
# Delete the raw sensor points of runs whose purpose is served (scored, written up, or void), on the Mini.
# Keeps each run's truth events (C3/C4 need them) and all forecasts. Refuses locked runs. The simulator can recreate the raw
# data of any run from its seed (C7). InfluxDB frees the space at its next compactions, not at once.
#   scripts/drop-raw.sh mini-smoke-1 base-smoke-1 ...          (run on the Mini, in the repo)
set -eu
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export PATH=/opt/homebrew/bin:$PATH
[ $# -gt 0 ] || { echo "usage: $0 <run-id>..." >&2; exit 2; }
for run in "$@"; do
  case "$run" in locked*) echo "refusing locked run $run" >&2; exit 1;; esac
  docker exec skylink-influxdb-1 influx delete --org "$INFLUX_ORG" --token "$INFLUX_TOKEN" --bucket raw \
    --start 2025-01-01T00:00:00Z --stop 2027-01-01T00:00:00Z --predicate "_measurement=\"sensor\" AND run=\"$run\""
  echo "deleted raw sensor points of $run"
done
docker exec skylink-influxdb-1 df -h /var/lib/influxdb2 | tail -1
