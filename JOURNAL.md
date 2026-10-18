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
