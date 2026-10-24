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

## Move to the Mac Mini (2026-10-14, 23:00)

Approved by the owner. Mini (8 cores, 16 GB, 94 GB free) had no container runtime: installed
colima, docker, docker-compose, uv, node with Homebrew (user level, no sudo). colima VM 4 CPU / 6 GB.
`~/.docker/config.json` pointed at a missing Docker Desktop credential helper; fixed it (backup:
`config.json.bak-skylink`) and added the compose plugin path. Repo copied with git bundle (no remote).
`make up` works; 17 tests pass; five-stream smoke at 60x: stream hash identical to the Air
(267cdade...), so the simulator is reproducible across machines. Mini load during that run:
river 32 %, nodered 17 % of a core, p99 step 22 ms, no model crashes.
Installed `~/Library/LaunchAgents/se.skylink.nightly.plist` (23:00 daily, niced, ends 06:00).
Started the first run by hand at 23:09 (inside the window): `dev-s1`, seed 1, 7 days, 60x, all five
streams, default models. Air stack stopped and its colima profile deleted.
Open: the job only runs while the main user is logged in on the Mini (it is, console session).

## First night, dev-s1 (2026-10-14 23:09 to 2026-10-15 01:57)

Seed 1, 7 simulated days, 60x, all five streams, 10 models, on the Mini. Finished in 2 h 48 m, 301 558
posts, 43 Skylink outages, no model crashes seen at the start; stream hash 91d31f49... (dev seed).
**C8:** raw points in InfluxDB equal points emitted for all five streams (wind counts double
because it has two fields). **Scores** (5 scored days, `reports/dev-s1-scores.md`) match the 4-day
bench: temp lin_lag +5 %/+15 %/+23 %/+41 % at 10/60/600/3600 s, online beats static at 600/3600 s
(+23 vs +20, +41 vs +35); pressure no skill beyond 60 s; solar worse than persistence for every
River model (SNARIMAX is +2 % at best); vibration +18-20 %; hat loses on pressure and solar.
**Incident:** the Mini rebooted before 21:05 on 2026-10-15 (uptime 3 min when I looked). After a reboot
nobody is logged in, so colima is down and a per-user launchd job cannot run. In-memory counters
(Node-RED link state, river stats) were lost; InfluxDB data survived. I restarted colima and the stack by
hand. Needs a decision: auto-login for the main user, or accept manual start after reboots.

## Second night, dev-s2 (2026-10-15 23:00); no-login reboot test passed

`dev-s2` (seed 2, 7 days, 60x) started 23:00:06 by the system daemon and finished (301 515 posts, hash
f421e217...). Scores (`reports/dev-s2-scores.md`) agree with dev-s1 within a few points everywhere, so
the dev-seed findings are not seed noise: lin_lag temp +5/+15/+21/+37 %, wind +6/+21/+25/+24 %,
vibration +16-21 %, pressure about 0, solar -17 to -24 %; online beats static on temp at long horizons
(+37 vs +26 % at 3600 s); reset and ADWIN-challenger variants lose heavily at h >= 60 on both seeds;
HAT collapses on solar (-6x to -20x); seasonal anchor is worse than persistence below 1 h.
The Mini rebooted again around 16:05 on 2026-10-16 with nobody logged in (uptime 5 h at 21:08); colima
and all four containers came back on their own. That is the intended behaviour of
`se.skylink.colima`. No data loss. Queue is empty.

## Iteration 2 (2026-10-16): base arms and backfill strategies (RQ1)

**Did.** The base side is now three River arms that only see what crossed Skylink (models:
persistence, lin_lag, holt; the edge arm keeps its 10): `base-ignore` (late data dropped),
`base-arrival` (everything in arrival order, even when event time goes backwards), `base-sorted`
(on a replay notice it holds live data until all backfill chunks arrived, then processes everything in
event-time order). Forecasts made from replayed data are hindcasts, tagged `rt=0`; only `rt=1` counts as
real-time. Every error line also carries a `phase` tag (outage / post = first 10 min after link-up /
normal) from link labels that never reach a model. `skylink.analysis --base` prints MAE ratio and
coverage (real-time forecasts relative to the edge) per phase.
**Bugs found while wiring it up.**
1. Node-RED sent link labels, the replay notice and the live batch to the river service as separate,
   concurrent HTTP requests, so they could overtake each other (the sorted arm then lost data). Live
   base messages now travel in one ordered request after the edge call; backfill chunks wait 300 ms
   behind it. The base endpoint has a lock.
2. A new outage can start before the previous replay finished; the sorted arm overwrote its hold and
   dropped data. Holds now accumulate (unit-tested).
**Unit tests:** 24 pass (gate notices, three strategies on a scripted outage, overlapping replays).
**Mini smoke (1 simulated hour, 5 streams, 7 outages, not a result):** steps processed per stream
edge 3286-3600; ignore 1596-1760 (outage + replay never processed); arrival and sorted = all.
**Decision.** Queued `dev-s3` (seed 3, 7 days, 60x) for tonight: first multi-day run with the base arms.
Pre-registered expectation stays H3: arrival order hurts most in the 10 min after link-up, sorted
removes most of it, at the price of coverage while the replay is pending.

## Iteration 3 (2026-10-16): agent layer built, not yet run live

Built per `docs/agent.md` (see its implementation map): MCP client for mcp-minions, four jobs with
in-code validation, labelled triage cases from dev seeds, guardrails, closed-loop switch bench.
37 tests pass. The Python link model reproduces the Node-RED outage chain exactly (checked over three
seeds). **Baseline fact:** the rules baseline scores macro-F1 0.658 on a balanced dev set (artefacts
perfect by construction; 122 of 175 faults called real events; 27 of 216 real events called artefacts),
so the C5a bar is 0.81. **Plumbing check of the closed loop with a scripted agent** (always proposes
`hat`): MAE 11 % worse than fixed (CI 1.06-1.16) even behind the guardrails; 22 of 26 proposals
rejected, 3 rollbacks. A bad agent really can hurt. No live model has been called: LM Studio's server is off.

## Local models and Jev wired in (2026-10-16 evening)

Ollama installed on the Mini (Homebrew, with approval): models gemma3:1b, gemma3:4b, qwen3:4b; the
server is started by the nightly job if it is not running (optional daemon `ops/se.skylink.ollama.plist`
needs the sudo installer). mcp-minions cloned to the Mini. Air: LM Studio server started for the run only.
Jev (TypeSafe's System One decision model, jev-style 0.4.0, 0.8B v3, MLX) runs on the Air at port 8765 and
is used through mcp-minions' `systemone` backend (`config/roster-jev.json`).
**Live smoke, 18 triage cases each:** gemma3:1b collapses to one class (F1 0.17); gemma-4-e4b F1 0.57;
Jev 0.8B 0.69 (all within noise at n=18, rules 0.648).
**Jev 0.8B on the full balanced dev set (648 cases):** macro-F1 0.587 (rules 0.658), accuracy 0.619, 0 invalid,
p50 0.16 s. It finds 58 of 175 faults. A rules-first hybrid (rules decide artefacts and flat lines, Jev
decides the rest) gets 0.643. Its confidence is **not** calibrated on this task: accuracy among the 20 %
most confident answers is 0.37, overall 0.56. So the shortcut-by-confidence mechanism has nothing to
work with here, zero-shot. A decision model needs domain data (or a better description of the numbers).
**Night queue 2026-10-16/17:** Mini: `dev-s3` (7 days with base arms), then `mini-t1` (gemma3 1b/4b, qwen3 4b,
100 cases per class). Air (started by hand under caffeinate, waits for 23:00): gemma-3-1b, gemma-4-e4b,
Jev 0.8B, then gemma-4-12b, then gpt-oss-20b, same cases (seed 7 balanced). The Air must stay awake and
plugged in; its job is not installed as a launchd agent.

## Night 2026-10-16/17 results

**Base arms, dev-s3 (7 days, 40+ outages), MAE ratio against the edge arm, lin_lag / persistence:**
normal phase 1.00 for all three strategies; first 10 min after link-up: ignore 1.03 / 1.00, arrival 1.00 / 0.99,
sorted 0.98 / 0.99; real-time coverage in that phase: ignore 0.79, arrival 0.70, sorted 0.65. So H3 is **not supported**
(predicted >= 20 % worse with arrival order): feeding backfill in arrival order costs about nothing in MAE. Likely reason: the
engine addresses history by absolute event second, so lag features survive out-of-order arrival; only the EWMA features see the
disorder. The price of waiting for a clean replay (sorted) is coverage (65 % vs 79 %), not accuracy. During the outage itself
the base arms produce nothing in real time (coverage 0-12 %), which is the actual degradation. Table: `reports/dev-s3-base.md`.
**Triage, local models:** see `reports/agent-triage-dev-2026-10-17.md`. No model beats the rules zero-shot (Jev 0.8B 0.599, e4b 0.527,
12B 0.491 vs rules 0.630). 0 invalid outputs everywhere.
**Process issues:** (1) the Mini evaluation overran the 06:00 window (qwen3:4b at about 97 s per case); I stopped it at 08:30 and
scored the logged answers. The eval script needs a deadline (`--until`) like the simulator. (2) gpt-oss-20b was skipped by the
memory guard on the Air (34 % free). (3) The Mini ran under heavy memory pressure (153 MB unused, 6.9 GB compressed) during the
Ollama run on top of the 6 GB Docker VM.

## Iteration 4 (2026-10-18): drift mechanism for increment models (RQ2), built, run queued

**Why the old detectors failed (from iteration 1 and the dev-s1/s2 scores).** ADWIN watched the raw
absolute error. That error is not stationary even when nothing is wrong: its scale follows the time
of day (temperature and wind are noisier by day). So ADWIN fired on the diurnal swing, and the two
responses were destructive: reset throws away a model that was fine (skill -75 to -136 % at h >= 60
on temp), and the challenger cannot learn a diurnal pattern in a 10 min probation. A level step
adds only one transient to an increment error (the model predicts y[t+h] - y[t]), so it is also a weak
signal for an error detector.

**What is different now (two changes, kept separate so the result is attributable).**
1. `lin_rls` (lam 0.9999, memory about 3 h) and `lin_rls_slow` (lam 0.99999, about 28 h): the same
   features and increment target as `lin_lag`, but an exponentially forgetting ridge regression
   (`ForgettingRidge`: decayed A and b, ridge term that does not decay, so a stuck sensor cannot wind it
   up; untrained = persistence). Forgetting is continuous, needs no detector, and never discards
   everything. This is the RQ2 arm without any detector.
2. `lin_rls_vn`: `lin_rls` plus ADWIN on the **volatility-normalised** error (abs error divided by
   its own slow EWMA, tau 1800 s, clipped at 10; delta 0.002). The slow diurnal change in error scale is divided
   out, so what is left for ADWIN is a sudden change in error relative to recent error. The response is **soft**:
   forgetting runs at 0.998 (memory about 8 min) for the next 600 learns, then returns to 0.9999. No reset, no
   challenger, no probation. Detections and boosts are logged in the `drift` measurement (kinds `detected`, `boost`).
Unit-tested (`tests/test_drift.py`, 45 tests pass): forgetting follows a sign flip where no forgetting does not, the normalised detector
stays quiet on a 4x slow swing in error scale where the raw one fires at least 3 times, and fires on a sudden
5x jump; stuck-sensor input stays finite. Cost on the Air, 4 temp horizons: 37-39 us per step per model
(`lin_lag` 48 us), no crashes.

**Honest expectation.** The pre-registered H5 (online beats static by >= 15 % in the hour after a
step or drift) may still fail for a mechanism reason I cannot fix by detection: persistence-anchored
increment forecasts barely notice a level step. Plain forgetting is more likely to help than the
detector. The detector variant earns its place only if it beats `lin_rls` itself.

**Plan.** Queued `dev-s1-drift` and `dev-s2-drift` (seeds 1 and 2, 7 days, 60x, default scenario) in
`config/queue.txt`; the three new models are in the default model set beside `lin_lag`, `lin_lag_static`,
`lin_lag_adwin`, `lin_lag_reset`, so every comparison is paired inside one run. Dev seeds only, nothing locked.
Resumable across nights (about 3 h each). Not run on the Air. **The Mini needs the new code first:** the
river image bakes the source in, so after syncing this repo to the Mini run `make up` (rebuild) once;
the nightly job does a plain `docker compose up -d` and would otherwise skip the new models.
**Read-out (scores with `skylink.analysis`, 2 day warm-up, per stream and horizon):**
- *Support for forgetting (RQ2):* `lin_rls` or `lin_rls_slow` skill >= `lin_lag_static` + 0.03 on temp at 600 and 3600 s on **both** seeds,
  and within 0.03 of `lin_lag` (no more than 3 % loss) on the stationary streams (wind, vibration) and pressure.
- *Support for the detector:* `lin_rls_vn` beats `lin_rls` by >= 0.02 skill on at least two of the
  stream/horizon cells where any event-driven gain is expected (temp 600/3600, wind 120), on both seeds, and its boosts per day
  stay below about 24 per horizon (a detector that fires hourly is the diurnal-swing failure again).
- *No support:* anything else. Specifically, `lin_rls_vn` equal to `lin_rls` means the detector adds nothing and the answer to RQ2 is "forget, do not detect".
- *Harm:* any new variant below `lin_lag` by more than 0.03 at h >= 60 on temp, as the reset variant was.
Not yet measured: the C4 window (MAE in the 60 min after logged fronts, steps and drifts, against static). The truth events are
in InfluxDB, but `analysis` has no event-window mode yet; add it before calling C4 (backlog 2b). The recipe line in section 3
stays `untested` until then.

## Iteration 5 (2026-10-18): event-window scoring for C4 (backlog 2b), built and tested offline

**Did.** `skylink.analysis --event-windows` and `scripts/bench.py --event-windows` score each model against the static model
(`lin_lag_static`) in the 60 min after logged regime changes: front, step, drift, seasonal onsets, plus the end of steps and drifts
(`step_end`, `drift_end`, reported but not part of the C4 rule), and in "stationary" bins (outside every window, resampled by day).
Reduction = 1 - MAE_online / MAE_static, pooled over windows, 95% CI by resampling events. `c4_verdict` applies the pre-registered
rule: >= 15 % reduction in the windows (front, step, drift, seasonal pooled, event-weighted) and no worse than -3 % in stationary bins,
per stream and horizon. The window starts at the logged onset on the target-time axis (the error is stamped when the truth arrives).
The Influx path (per-minute sums, truth events from the raw bucket) is written but could not be exercised here: there is no
InfluxDB on the Air and no dev run output on disk (`runs/` holds only agent logs), so it is untested against live data until the dev
runs sync back. 50 tests pass (5 new, synthetic series).

**Offline check** (bench, seed 1, 5 days, 2 warm-up, temp only, 2 drifts in the windows): `lin_rls` vs static: window reduction
+34 % at 600 s and +54 % at 3600 s, but stationary +21 % and +65 %. So the gain is not specific to events: the static model, frozen
after 2 days, is simply a worse model everywhere. Read the C4 rule literally and `lin_rls` passes; read it as "event-specific gain"
and it does not. I report both columns and will say so in the verdict; the pre-registered rule is unchanged. Too few events here
(2 drifts) to say anything about the 15 %; the 7-day dev runs have more.

**Support / no support for H5 / C4 when the drift runs return:** support = C4 rule passes on temp at >= 2 horizons on both seeds *and*
window reduction exceeds stationary reduction by >= 0.05 on at least one of them (event-specific gain). No support = rule passes only
because stationary gain is as large as the window gain (static is just stale), or fails.

## Iteration 6 (2026-10-18): solar, ratio to a clear-sky shape (backlog 4), offline only

**Why.** Every River model lost to persistence on solar (-10 to -24 %). Cloud cliffs are unpredictable steps, but the daily ramp
is deterministic and persistence ignores it; the linear learners lose because squared-error fitting chases cliffs and noise.
**Tried (bench, dev seeds 1-3, solar only, 7 days, 2 warm-up, skill vs persistence; seed 1 4-day runs for the dead ends):**
1. `clearsky` (self-learned per-minute envelope, maximum over days with decay; forecast = envelope(s+h) * recent clearness): -25 to
   -320 %. The envelope is jagged (max of noisy minutes, spike faults), and a persistence of a *ratio* to a noisy envelope is worse than
   persistence of the level. Anchored form (y + k * (env(s+h) - env(s))) with a 21-minute smoothed envelope: -1 to -7 %; the ramp
   it implies is wrong in the morning because the seasonal events shift phase and amplitude and a max over earlier days remembers the
   old curve. Class kept for the record, not in the default set.
2. `clearsky_shape`: yhat(s+h) = y(s) * f(s+h) / f(s), f = max(cos(2 pi (t - noon) / day), 0)^p, no fitted parameters, persistence
   at night (f below 0.05) and the ratio capped at 2. This is the first model that beats persistence on solar. Fixed noon 12:00, p=1
   (p=1.3 is the simulator's exponent: +0.5 point, so not used): seed 1 +0.1/+1.0/+1.7/+2.6 % at 5/30/60/300 s, seed 3 +0.0/+0.3/+0.6/+1.4 %,
   **seed 2 -0.3/-1.0/-1.1/-0.7 %** (CIs mostly exclude 0 on the negative side): a fixed noon is wrong after a seasonal phase shift.
3. `clearsky_adapt`: same, noon moved each day to the centroid of the previous day's curve (blend 0.5). Seed 1 +0.1/+0.9/+1.6/+2.2 %,
   seed 2 +0.2/+1.5/+2.2/+3.1 %, seed 3 +0.1/+0.8/+1.3/+2.1 %; all CIs exclude 0 for h >= 30. Cost 0.9 us per step (persistence 0.3, `lin_lag` 60).
4. `lin_cs` (linear learner on the residual of the shape forecast, day regime only): -25/-20/-19/-7 %, same as `lin_lag`. Nothing is left
   for a squared-error learner once the ramp is removed; the residual is cloud cliffs. Class kept for the record, not in the default set.
**Read honestly.** +2 to +3 % at 300 s is small and a development result with the shape tuned on these seeds (the adaptive rule was chosen
after seeing seed 2). It is far from C1's 0.10, so solar does not move C1 toward 3 of 5 streams by itself. What it does change is the
recipe line "persistence is the product on solar": a one-line geometric correction beats persistence at every horizon from 30 s, a learned
model does not. Not tested: a robust (quantile or Huber) learner on the shape residual; a seasonal fit of the amplitude (irrelevant for a
ratio). H1/H2 (solar useful horizon <= 60 s): consistent but at skill 0.01-0.02, below the 0.05 bar of H2's "useful".
**Plan.** No dedicated run. `clearsky_shape` and `clearsky_adapt` (cheap) are in the default model set, so they ride on the queued
`dev-s1-drift` and `dev-s2-drift` runs after the Mini sync (the image must be rebuilt anyway for the drift models).
**Support / no support for "solar is forecastable beyond persistence with geometry":** support = on the Mini runs `clearsky_adapt` has skill
> 0 with CI excluding 0 at h >= 30 s on both seeds, and `clearsky_adapt` >= `clearsky_shape` on the seed with a phase shift. No support = skill
<= 0 on either seed or CI covering 0 at 60 and 300 s. Result for the recipe: stays `dev` until locked seeds.

## Iteration 7 (2026-10-18): audit of the agent layer (backlog 3) and the small gaps built

**What exists (code, tests, evidence).** (1) MCP stdio client for mcp-minions (`MinionsClient`), errors returned as codes, latency measured,
`FakeTransport` for tests. (2) Four jobs with in-code validation (triage, proposal, explanation, note). (3) Guardrails (`guard.py`: action
space, dwell, 50 % worse rejection, 20 % rollback), tested. (4) Rules twin and fixed twin in the closed-loop bench. (5) Call log (JSONL).
(6) Local models: LM Studio gemma-3-1b, gemma-4-e4b, gemma-4-12b (gpt-oss-20b skipped by the memory guard), Ollama gemma3 1b/4b and qwen3:4b,
Jev 0.8B: **only used for job T**. Dev-seed result so far: no zero-shot model beats the rules (best 0.60 vs 0.63); with three worked
examples gemma-4-e4b 0.76, still below the 0.81 bar.
**What was missing against `docs/agent.md` and C5.** (a) The asynchronous worker with a bounded queue and dropped-call logging (C5c says
"enforced by test"): none; the bench called the agent inline. (b) The guardrail verdict was never attached to a call, so accepted fraction
and per-call outcome could not be computed; no run id, no call id. (c) No C5c summary (p50/p95, invalid rate, accepted fraction) from
the proposal bench, and no C5b rule check. (d) The doc listed `seasonal_naive` in the action space; the code has `seasonal_anchor`. (e) Jobs
P, N, E never called live; no scoring for N and E. (f) The agent is not in the live stack. (g) The bench ran one horizon on two streams.
(h) Nothing writes the `agent` Influx bucket.
**Built (small).** `AsyncAgent` (non-blocking submit, drop-oldest with a `DROPPED` log record; two tests incl. a slow model that never
holds the caller), call ids and `CallLog.verdict`, `summarise_log` (C5c), `c5b_check` (macro ratio <= 0.97 and no stream worse than +1 %),
wired into `scripts/agent_proposals.py` (verdicts logged, C5b/C5c printed), doc fixed. 59 tests pass. Scripted-agent smoke (2 dev days,
temp): rules twin 0.953 of fixed MAE (CI 0.91-0.99), the scripted bad agent 1.12, as before. Large gaps are in BACKLOG item 3 (a-f).
**Not run:** no live model, no new queue line. A closed-loop live run needs a model server on the Mini plus a section in the Mini's
`nightly.sh`, which I did not touch. Read-out when it is run: *support for the agent* = C5b macro ratio <= 0.97 over all five streams, no
stream worse than +1 %, **and** better than the rules twin; *no support* otherwise (H7 predicts |delta MAE| < 1 %).

## Iteration 8 (2026-10-20): C4 / H5 verdict on the dev drift runs, and a fairer yardstick

**Data.** `dev-s1-drift` and `dev-s2-drift` (7 days, 2 warm-up, all streams) finished on the Mini on 2026-10-19 and were scored there with
`analysis --event-windows` (reports read read-only; copies of the numbers are in `reports/dev-drift-c4.md`). The Mini had already scored
seed 2 as well. Pre-registered rule, unchanged: online beats the frozen model by >= 15 % in the 60 min after regime changes and loses
no more than 3 % in stationary bins. Windows per stream and seed: 1-7 (many streams have 1-3 events of one kind, so every CI is wide).
**Result (static reference = frozen after 2 days, the pre-registered one).**
1. **Temperature, pressure, wind, vibration: no model passes at any horizon on either seed** (266 stream/model/horizon rows per seed).
   Only solar rows pass, and only for persistence, snarimax and the clear-sky shapes at 5-60 s (seed 1) or 300 s (seed 2); none of those
   learns anything, so that is the frozen linear model being a bad solar forecaster, not adaptation.
2. **The learners the hypothesis is about gain nothing in windows.** Temperature seed 1, `lin_rls` window / stationary reduction: +0.017 /
   +0.040 at 60 s, -0.214 / +0.136 at 600 s, -0.084 / +0.049 at 3600 s; seed 2: -0.082 / +0.031, -0.409 / +0.163, -0.193 / +0.143. `lin_lag`,
   `lin_rls_slow` look the same. Online is better than the frozen model in quiet hours (it is not 2 days stale) and not better, mostly
   worse, in the hour after an event. Wind: `lin_rls` +0.01 to +0.03 in windows and +0.01 to +0.04 stationary (both seeds), so within
   2-4 points of each other, far from 15 %. Vibration: `lin_lag_adwin` / `lin_lag_reset` / `hat` +0.06 to +0.12 at 1 s, mostly negative at 5-120 s.
   Pressure: nothing beyond 0.02 except detector variants that are 100-300 % worse than static.
3. **Drift detectors made it worse**, as in iteration 1: `lin_lag_reset` and `lin_lag_adwin` lose 100-300 % at 60-600 s on temperature and pressure
   in windows and stationary alike (the error-variance swings with the time of day; see recipe section 3). `lin_rls_vn` (soft boost) is
   at -0.3 to -2.1 in windows at 60-600 s on temperature, +0.06 / -0.05 at 3600 s: no help either.
**Verdict (pre-registered wording).** *C4 / H5 not supported on the dev seeds.* The rule fails everywhere that matters, and where online is
ahead it is ahead in stationary bins by as much as or more than in windows, i.e. the frozen model is just stale. The "event-specific gain"
(window minus stationary reduction) is negative in 89 of 120 temp/pressure/wind/vibration learner rows of the bench re-run (below). No locked seed has been used.

**Yardstick (additional reported column, rule unchanged).** A frozen-after-2-days reference confounds "adaptation helps" with "the reference
is old". Added `lin_lag_retrain` (same linear class; a fresh shadow model learns for one period, then is frozen and served for the next
while a new shadow starts; period 1 day, so it is 1-2 days old and never learns inside an event) as a second reference, `--static
lin_lag_static,lin_lag_retrain` in `bench.py` and `analysis`, rows carry `ref`, verdict rows carry `event_gain`. It is in the default
model set (cost: one extra linear model per horizon plus a shadow). Tests: model freezes within a period and swaps at the boundary; two
references are separate columns and `event_gain` isolates a gain that exists only in windows (the new test also checks the old
single-reference path still works). 64 tests pass.
**Bench, same scenario, seeds 1-2, 7 days, 2 warm-up, all streams** (columns in `reports/dev-drift-c4.md`). The static column reproduces the
Mini's within about 0.01-0.05. Against the retrained reference the rule passes once in 120 learner rows (4 learners, all horizons, 2 seeds, solar excluded) (seed 2, pressure, `lin_lag` 3600 s:
window +0.172, stationary +0.234, event gain -0.06, i.e. not event-specific; the stationary stretch is where the retrained model, which sees
one day, is weak). Event gain >= 0.05 with a positive window gain appears in 2 of 120 rows per reference, both seed 1: `lin_rls_vn` on
pressure and temperature at 3600 s against the frozen model (+1.4 / +0.17), which is a stationary loss, not a window win, and `lin_lag` on
pressure at 3600 s against the retrained one (+0.06, window +0.04). So the stale-reference explanation holds: removing it does not
uncover event-specific gain, it moves the window reductions by only 0.01-0.1 in most rows and the stationary ones up (the retrained model sees one
day of data, so quiet-hour gains of online learners get larger, not smaller, at long horizons); event gain is negative in 101 of 120 rows.
**Read honestly.** (a) Small N of events and 2 seeds; CIs of window reductions are wide (a single front or step can swing a row by 0.1-0.5).
(b) The scenario's regime changes may be slow or small relative to the diurnal swing for the models to profit; this tests the model classes
as built, not every possible adaptation mechanism. (c) Retrain period (1 day) and training length are choices; a 2-hour retrain would
shrink the staleness further but is not a "static" model any more. (d) The C4 text says "same class with drift detection"; the detector
variants are the worst rows. The stricter reading of the rule (detector, not forgetting) fails by a large margin as well.
**Decision.** Recipe section 3 updated. Nothing else queued; the drift question is closed for dev seeds (`dev`). The locked-seed runs will
report both references; the rule and the support wording stay as pre-registered.

## Iteration 9 (2026-10-20): robust learner on the solar clear-sky residual (backlog 4 leftover), offline

**Why.** Iteration 6 left one hole: the squared-error linear learner on the residual of the shape forecast (`lin_cs`) loses 7-25 % because
cloud cliffs dominate the squared loss. A median or Huber loss should not chase them.
**Built.** `ScaledRobust` (linear learner with Huber or quantile-0.5 loss on a target divided by an EWMA of its own absolute size, so the
knee means the same on every stream) on the residual of `clearsky_adapt` (the adaptive-noon shape; `lin_cs` used the fixed noon), day
regime only, as `lin_cs_huber` and `lin_cs_quant`. Not in the default set. 2 tests (registration; outlier-robust fit).
**Bench (solar only, 7 days, 2 warm-up, dev seeds 1-3, skill vs persistence, 95 % CIs as printed by the bench).**
1. Learning rate 0.003 (as `lin_lag`): Huber -1 / -8 / -21 / -60 % at 5/30/60/300 s, quantile -0.4 / -4 / -9 / -42 % (seed 1; seeds 2-3 within 5 points);
   squared loss (`lin_cs`) -26 / -21 / -21 / -10 %. Robust loss helps at short horizons and is worse at 300 s, where the SGD residual
   model injects a large wrong bias.
2. Smaller steps (0.0003: quantile -4.9 % at 300 s; 0.00003: **quantile +0.6 / +1.3 / +1.7 / +1.8 %** seed 1; 0.00001 +0.3 / +1.2 / +1.8 / +2.4 %).
   The learner is effectively switched off at that rate, so this is almost `clearsky_adapt` plus a small correction.
3. Seeds 1-3 at 0.00003, `lin_cs_quant` vs `clearsky_adapt` (both vs persistence, 5/30/60/300 s):
   seed 1 +0.6/+1.3/+1.7/+1.8 vs +0.1/+0.9/+1.6/+2.2; seed 2 +0.4/+1.7/+2.4/+2.9 vs +0.2/+1.5/+2.2/+3.1; seed 3 +0.6/+1.1/+1.5/+1.8 vs +0.1/+0.8/+1.3/+2.1.
   All CIs exclude 0; Huber at the same rate is +0.1 to +1.3 at 5-60 s and -1.7 to -3.2 % at 300 s (CIs exclude 0 on seeds 1 and 3, not on 2).
**Read honestly.** The robust quantile learner at a very small rate is 0.3-0.6 points better than `clearsky_adapt` at 5 s, 0.2-0.4 at 30 s,
about equal at 60 s, 0.2-0.4 points worse at 300 s, at 20-25 times the per-step cost (35 us vs 1.5 us). Differences are inside what the three
seeds can resolve, and the learning rate was picked after looking at seed 1 (tuning on dev). It is not a win: **kept out of the default set.**
The informative result is the other direction: a robust loss turns -10 to -26 % into about +-2 %, which confirms the cloud cliffs, not
the loss, were the problem, and that nothing learnable remains in the residual beyond what the geometry gives.
**Decision.** Backlog item 4 closed. Recipe sentence added (solar). Stays `dev`.

## Iteration 10 (2026-10-20): five-model test on the Air (local models for jobs T, E, N, P and honesty)

**Why.** The owner asked for a comprehensive, comparable test of five candidate local models while the Air was idle. Four ran; Qwen3.5-9B is
on disk but LM Studio never indexed it (load by key, name and path all fail with "No model found that matches model key"), so it was not tested.
**Built.** `scripts/five_models.py` (load at context 4096 with free-memory record, speed/TTFT, honesty prompts from the llm-bench set plus a second
hippo case, unconstrained JSON adherence for E and P, constrained P, thinking arm) around the existing `agent_eval.py` and `model_profile.py`;
`scripts/five_models_report.py` for tables and bootstrap CIs. No locked seeds used.
**Result (`dev`, one run each, details in `reports/five-models-2026-10-20.md`).** Triage with three examples: gpt-oss-20b 0.822 [0.78, 0.86],
Qwen3-14B 0.797 [0.75, 0.84], Ministral 3 14B 0.524, LFM2 24B-A2B 0.492 (rules 0.630, previous best e4b 0.76). Zero-shot: Qwen3-14B 0.680, Ministral
0.509, gpt-oss 0.234, LFM2 0.160. Speed at ctx 4096: LFM2 79 tok/s, gpt-oss 45, Qwen3-14B 15, Ministral 10. Honesty core 3 (of 3): Qwen3-14B 2.0,
Ministral 2.0, gpt-oss 1.0, LFM2 0.0; all invent sister-vessel history. Second hippo case: only LFM2 passes. Thinking on made Qwen3-14B worse and 50x
slower on triage (16/30 vs 21/30). Constrained decoding gives 100 % valid output for T, E, P everywhere; unconstrained gpt-oss manages only 10/30 on E.
**Incidents.** LM Studio's server was stopped and restarted at 21:40 during the first LFM2 run (not by the harness); that run was discarded and redone.
**Decision.** Recipe section 5 updated (`dev`). Nothing changes in the pipeline: the pre-registered C5a bar (>= 0.80 and +0.15 over rules) is met at the
point estimate by gpt-oss-20b with examples, but that is one dev run with the examples drawn from the same pool, so it goes to the locked-seed plan, not to a verdict.
**Open.** Qwen3.5-9B needs re-adding through the LM Studio UI; thinking on/off on honesty for the second hippo case was not run.

## Night 2026-10-22/23 results: job P live on the Mini (C5b/C5c, dev seeds 1-2)

**Run.** `mini-p1` (seed 1) 23:00-05:10 and `mini-p2` (seed 2) 05:10-11:19: closed-loop bench, 3 days, 1 warm-up, all five streams,
one horizon each, arms fixed (`lin_lag`), rules twin (best trailing MAE if 10 % better), gemma3:4b and qwen3:8b through Ollama.
**Result (MAE ratio vs fixed, macro over streams; worst stream).** Seed 1: rules 0.950 (wind 1.00, C5b pass), qwen3:8b 0.984
(pressure 1.079, fail), gemma3:4b 1.000 (never switched, fail). Seed 2: rules 0.958 (pressure 1.175, fail), qwen3:8b 0.961
(pressure 1.168, fail), gemma3:4b 1.000. The gains are solar (0.71-0.86 for rules and qwen3:8b alike) and temperature on seed 2;
pressure loses for every arm that switches. C5c: gemma3:4b p50 11 s, 0 invalid, 250 calls, no switch proposed at all;
qwen3:8b p50 57-59 s, p95 154-158 s, invalid 1.2-1.6 %, 70-73 % of its switches accepted by the guardrails, 3-4 calls per run hit the 300 s timeout.
**Read honestly.** Two dev seeds, one horizon per stream. qwen3:8b behaves like a slower copy of the rules twin, not better than it; the
small model is a no-op. Pressure is where switching hurts (H2: nothing beyond about a minute), so a "never switch pressure" rule would
help both arms; that is tuning on dev and stays an idea. The pre-registered wording for now: "lift not shown" (`dev`).
**Incident.** `mini-p2` overran the window by 5 h 19 min: the bench had no deadline (the same gap as the eval script on 2026-10-17).
Fixed in iteration 11.
**Decision.** Recipe section 5 updated. Seed 3 queued to finish the dev triple.

Night 2026-10-22/23: finding (model selection moves from `untested` to `dev`).

## Iteration 11 (2026-10-23): plumbing for unattended nights and days

**Why.** The owner asked for the experiment to run on its own until the goal. Three gaps: the queues were empty (nothing would have run
tonight), job P could overrun the window, and nothing did the daytime part (write-up, next step, next queue) without a session started by hand.
**Built.** (1) `agent_proposals.py --until HH:MM`: stops at the window end, writes `cut.json`, exits 3 (no checkpoint, so a cut bench starts
over). (2) `nightly.sh`: one stop check for window and disk (`MIN_FREE_GB`, default 3; the Mini had 5 GB free today), `--until` passed to
the bench, and `runs/last-night.txt` with one line per item (ok / stopped / cut / failed, nothing ran). (3) `scripts/mini-sync.sh`
status / pull / push between the Air and the Mini (git bundles over ssh, refuses while a night job runs or when the Mini has its own commits).
(4) `docs/daily-loop.md`: the daily pass and the road to the verdict; `CLAUDE.md` points to it and no longer says there is no remote.
(5) A daily scheduled task on the Air runs that pass (outside the repo, set up by the owner's request).
**Tested.** Scripted-agent bench runs to the end and, with `--until` one minute ahead, stops after 2.2 of 30 days with exit 3; stop check
gives "window over" and "disk low" in the right cases; `mini-sync.sh status` and `pull` against the Mini.

## Night 2026-10-23/24: nothing ran (disk low on the Mini)

**Run.** `mini-p3` (job P, dev seed 3) was queued. The nightly stop check refused at 23:00: 2 GB free, `MIN_FREE_GB` 3.
**Look on 2026-10-24 (read-only).** The Mini's data volume is full outside this repo: 3.2 GB free of 460 GB; the colima VM uses 39 GB,
Ollama models 15 GB, `~/Library/Caches` 8.6 GB. This repo's `runs/` is 30 MB, so the runs did not fill it. Free space went from 5 GB
(2026-10-23) to 2-3 GB without a run, so something outside the experiment is writing. Deleting anything on the Mini is the owner's call;
nothing was deleted and the guard was not lowered.
**Decision.** `mini-p3` stays queued; it starts tonight only if the guard sees at least 3 GB at 23:00. Asked in the report.

Night 2026-10-23/24: no finding (nothing ran).
