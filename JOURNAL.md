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

## Iteration 1 (2026-10-14, evening): River models, paired scoring, offline bench

**Did.** Models behind one interface: persistence, seasonal naive, seasonal anchor (seasonal naive
plus the present offset), Holt, SNARIMAX, direct per-horizon models on increments
(`lin_lag` = standardised, clipped features into River's BayesianLinearRegression; `lin_lag_static`
frozen after 2 days; `lin_lag_adwin` challenger on ADWIN detections; `lin_lag_reset` naive reset),
Hoeffding adaptive tree (`hat`). The engine writes the persistence error of the same step on every
error line, so skill is paired by construction (`skylink.analysis`: hourly sums, block bootstrap).
`scripts/bench.py` runs the engine offline on dev seeds. Per-model CPU cost per step is measured and
exported. All five streams run through the full stack at 60x for one simulated hour: river ~0.45 core
with 9 models (Air VM), p99 step 13 ms (SNARIMAX forecasting steps).

**Dev seed 1, 4 simulated days, 2 scored (low power; no verdict; dev seed only).** Skill vs persistence:
| stream | lin_lag | note |
|---|---|---|
| temp | +5 %, +15 %, +19 %, +33 % at 10/60/600/3600 s | static: same at short h, +13 %/+18 % at 600/3600 s |
| wind | +8 %, +24 %, +27 %, +27 % at 1/5/30/120 s | |
| vibration | +27 %, +20 %, +18 %, +18 % at 1/5/30/120 s | partly the deterministic 0.2 Hz microseism in the simulator |
| pressure | +3 % at 60 s, about 0 at 600/3600 s | fronts and the slow process are unpredictable |
| solar | -24 % at 5 s ... -10 % at 300 s | worse than persistence at every horizon |

**What this says against the pre-registered hypotheses (provisional, dev seed).**
- H1/H2 (pressure forecastable like temperature, vibration not): contradicted on this seed. Pressure has no useful horizon beyond 60 s; vibration RMS has +18 % (microseism, a simulator feature).
- H4/H5: online beat static on temp at long horizons (+33 % vs +18 % at 3600 s) while equal at short ones. Direction as predicted, size untested on locked seeds.
- H8: HAT costs 110-520 us/step, linear 55-75 us; ARF not run yet. Measured, not guessed.

**Negative results worth keeping.**
1. SGD-trained linear models diverged (MAE ~1e9) on spike faults; PA-II was stable but worse than persistence; Bayesian ridge on clipped features was stable and best. Clipping and a robust learner are needed before any "online linear" claim.
2. Drift handling is harmful as built. Reset on every ADWIN detection ruins h >= 60 (skill -75 % ... -136 % on temp). The challenger variant fixes short horizons but still loses at 600/3600 s: ADWIN on the absolute error fires on the diurnal change of error variance, and a challenger cannot learn a diurnal pattern in a 10 min probation. Error-stream drift detection does not fit increment models: a level step is a single transient in persistence-anchored errors.
3. Holt with defaults was worse than persistence; with alpha 0.02, beta 0.0003 (tuned on dev seed 1, one parameter pair for all horizons) it is +10 % at 60 s and +43 % at 3600 s but -23 % at 10 s.
4. SNARIMAX diverged with the default regressor and crashed with a Bayesian one (feature set grows); with a clipped Huber-SGD regressor it is stable but weak (+1 % at 10-60 s, +10 % at 600 s) and about 1 ms per step.
5. Seasonal naive is terrible here (MAE 3.96 on temp, flat in h): the simulator's step/drift faults last hours, so repeating yesterday repeats yesterday's fault. The anchored version is worse than persistence below 600 s.
6. A 12 h harmonic feature (for the pressure tide) made things worse (pressure -18 % at 3600 s). Reverted.
7. Hoeffding trees raise ZeroDivisionError on constant input (stuck sensor, night-time solar). The engine now contains model exceptions, resets the model, counts it. Unit-tested.

**Decisions.** Keep the simulator as is (not tuned to flatter a baseline). Default model set is in
`config/edge.toml`. Next: base arm and backfill strategies (RQ1), a drift mechanism that fits
increment models (ADWIN on volatility-normalised error, or exponentially forgetting least squares),
then the agent layer. Nothing run in the night window; the launchd job and the Mini move wait for a yes.
