# Design notes

## Time and data
- Event time is owned by the simulator (epoch 2026-01-01T00:00:00Z, µs integers on the wire because
  ns timestamps do not fit a JSON double). Wall time only paces the replay (`--speed`).
- Streams (rate): temp 10 Hz, pressure 10 Hz, wind 20 Hz (speed + direction), vibration 100 Hz,
  solar 5 Hz. Aggregated to 1 s at the edge (mean; RMS for vibration).
- Generators are block-based (60 s), sequential and seeded per stream. Output depends only on
  seed, plan and block index, never on batching. Resume = regenerate and discard up to the checkpoint.
- The event plan (faults: stuck, spike, drift, step, dropout; process events: seasonal shift,
  fronts, gusts, vibration bursts, cloud edges) is drawn up front per stream and written to
  InfluxDB (`truth_event`) and `runs/<id>/events.jsonl`.

## Skylink
Node-RED steps a Markov on/off chain once per event second (seeded, so resume reproduces it).
Granularity is the batch (10 s): the state at the batch's last second applies to the whole batch.
Down: batches go into a finite in-memory buffer (oldest dropped on overflow, counted).
Up: buffered batches are merged into chunks per stream, chunk order shuffled inside windows
(late, out-of-order), released at 20 chunks/s each to InfluxDB and to the base arm. Live data
passes immediately, so backfill interleaves with fresh data. Point accounting (C8):
in = live + buffered; buffered = backfilled + dropped + still buffered.

## Arms
- **edge**: local tap, never affected by Skylink. Always on.
- **base**: sees only what crossed Skylink. In iteration 0 only arrival lateness is measured.
- Forecasts, errors, metrics and truth bypass Skylink (instrumentation plane).

## Known limits
- Node-RED buffer is in memory: a Node-RED restart loses buffered data (flagged by C8, run void).
- InfluxDB retention is infinite (simulated time starts in 2026-01; age-based retention would eat it).
- Wide Grafana ranges query raw 10-100 Hz data; keep ranges to a few hours or add a downsampling task.
