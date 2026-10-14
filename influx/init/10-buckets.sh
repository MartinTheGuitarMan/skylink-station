#!/bin/bash
# Runs once, after the first-time setup created the `raw` bucket. Retention 0 = keep forever:
# event time is simulated (2026-01-01 onwards), so age-based retention would delete live data.
set -e
for b in forecasts metrics agent; do
  influx bucket create --name "$b" --org "$DOCKER_INFLUXDB_INIT_ORG" --retention 0 --token "$DOCKER_INFLUXDB_INIT_ADMIN_TOKEN"
done
