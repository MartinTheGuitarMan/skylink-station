# Journal

Format: what I tried, why, result, decision. Newest last.

## Iteration 0 (2026-10-14): criteria, scaffold, one stream end to end

**Context found.** This machine is the MacBook Air, not the Mac Mini the brief names. Docker was
installed (colima, default profile 2 CPU / 2 GB, stopped). LM Studio is running with
gemma-3-1b, gemma-4-e4b (4B), gemma-4-12b, gpt-oss-20b; Ollama is installed but its server is
down. mcp-minions (v0.2, public repo, not touched) is clean on main. **Decision:** develop on the
Air in a separate colima profile `skylink` (4 CPU, 6 GB, default profile untouched); everything is
config-as-code, so moving to the Mini is a `make up`. Numbers from the Air do not count for C2.

**Did.** Pre-registered criteria and hypotheses first (commit 7515c2a, before any code). Then:
simulator for all five streams with a seeded event plan and ground truth; replayer (paced,
time-compressed, checkpointed, resumable, SIGTERM-safe, `--until` window end); Node-RED flows
(Skylink Markov gate, finite buffer, out-of-order rate-limited backfill, edge tap); River
service with a prequential engine and two baselines (persistence, seasonal naive); InfluxDB with
four buckets; Grafana dashboard as code; unit tests (14: determinism, engine scoring, gate
accounting and resume, run under node).

**Bugs the tests or the first run caught (all fixed).**
1. A stuck sensor was hidden by a later spike fault in the same stream: stuck now wins.
2. History lookup for second -1 matched the empty ring (NaN forecasts). Added `s < 0` guard.
3. The backfill shuffle drew from the same PRNG as the Markov chain, so a resumed run saw a
   different outage schedule. Separate generator (`rb`) for the shuffle.
4. Node-RED does not substitute `${ENV}` in http-request URLs; URLs are now set per message.
5. InfluxDB init script must not pass `--host` (temporary server runs on another port).
6. "Late data" metric flagged every batch (10 s span); now compares with the newest earlier arrival.
7. Grafana at 512 MB sat at 400 MB; raised to 768 MB.

**Smoke result** (1 simulated hour, temperature only, faults at 24x, 7 outages, seed 1; plumbing
check, not a result). Raw points in InfluxDB 31779 = emitted 31779 (C8 holds); 14179 points came
through backfill. Same seed gives the identical stream hash on three runs (C7 hard part holds).
Persistence MAE: h=10 s 0.118, h=60 s 0.228, h=600 s 0.96 degC. Dev-host resource use at 240x:
river 3-5 % of a core, 111 MB, p99 step latency 0.05 ms; Node-RED 12 %, 65 MB.

**Decision.** Next iteration: River models + score script (backlog 1, 2). Nothing run in the
night window yet; no launchd job installed (needs approval).
