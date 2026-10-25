# Success criteria and pre-registered hypotheses

Written 2026-10-14, **before any model was run** (iteration 0). Git history is the audit trail.
Changes after this commit go only in the *Amendments* section at the bottom, dated, with a reason.
Never edit a threshold in place.

## 0. Definitions

- **Event time**: the simulated clock. All windows, horizons and "minutes" below are event time unless marked *wall*.
- **Step**: one second. Every stream is aggregated to 1 s (mean; RMS for vibration) before forecasting. Raw data stays at full rate in InfluxDB.
- **Horizon h**: forecast made at step t for the aggregate at t+h seconds.
- **Prequential**: test-then-train. A forecast is scored only against data that arrived after it was made; a model is updated only after its forecast for that step was scored. No other evaluation is accepted.
- **Persistence**: ŷ(t+h) = y(t). **Seasonal naive**: ŷ(t+h) = y(t+h−P), P = one simulated day. Both always run.
- **Skill** = 1 − MAE_model / MAE_persistence, same steps, same horizon. Positive = better than persistence.
- **Warm-up**: the first 2 simulated days of any run are excluded from scoring (one day for seasonal naive to exist, one to settle).
- **Arms**: *edge* (River sees the local, in-order, gap-free sensor tap, so it is unaffected by Skylink) and *base* (River sees only what crossed Skylink: gaps during outages, then a late, out-of-order backfill burst). Sensor dropouts hit both.
- **Seeds**: dev seeds 1–3 (tuning allowed). **Locked test seeds 101–105**: not looked at, not used for tuning, until the final report. Every number in a verdict comes from locked seeds, mean ± sd over seeds, with a block bootstrap (1 h blocks, 2000 resamples) 95% CI.
- **Run length** for verdicts: ≥ 7 simulated days, all five streams, with the event/outage schedule of `config/scenario-default.toml`.
- **Target machine**: the Mac Mini. Numbers measured on any other host are labelled with that host and do not count towards C2/C7 verdicts.

## 1. Criteria (each has a number, a method, and a pass rule)

### C1 Accuracy: does River beat the baselines?
For at least **3 of 5 streams**, at at least one pre-set horizon each, the best River model has skill ≥ **0.10** against persistence on the edge arm, and the bootstrap CI of the skill excludes 0. Also report skill against seasonal naive, but C1 does not depend on it.

### C2 Resource budget at the edge
On the Mac Mini, with all five streams at real-time (1× speed), the River service (forecasting + evaluation + writes) must stay within: mean CPU ≤ **0.5 core**, RSS ≤ **512 MB**, p99 per-step latency (all models, all horizons, one stream) ≤ **50 ms**. It must also sustain **≥ 60× time compression** on at least the cheapest model set (this is what makes the nightly runs useful). Local model servers (Ollama/LM Studio) are *excluded* from this budget and reported separately under C5.

### C3 Recovery after disturbance
Recovery time = steps from the event until a 5-minute rolling MAE stays within **25 %** of the pre-event steady-state MAE (median of the 30 min before). Applies to: end of an outage + backfill (base arm), front passage, step change, drift end. Pass: **median recovery ≤ 15 min** per event kind for the best model, **without re-initialising the model** (a reset counts as a failure of the model, but is reported as an alternative strategy).

### C4 Online vs static
Static = same model class trained once on the first 2 simulated days, then frozen. Online = same class with drift detection. Pass: online reduces MAE by ≥ **15 %** in the 60 min after regime changes (front, step, seasonal shift), and loses no more than **3 %** in stationary periods.

### C5 Agent lift (mcp-minions)
Agent arm vs River-alone arm, same seeds, same replayed data, same guardrails. The agent *proposes*; guardrails decide. Three sub-claims, each judged on its own:
- **C5a Triage**: classify alerts into {real event, sensor fault, backfill artefact} against the simulator's ground truth. Pass: macro-F1 ≥ **0.80** *and* ≥ **+0.15** over a rules-only baseline (rule: inside a backfill window → artefact; flat-line → fault; else → real).
- **C5b Forecast lift**: MAE of the agent arm lower than the River-alone arm by ≥ **3 %** overall, paired bootstrap CI excluding 0, and not worse by more than 1 % on any single stream.
- **C5c Cost**: agent calls never block the forecast loop (asynchronous, enforced by test); report p50/p95 latency, accepted/rejected proposal fractions, and the invalid-JSON rate per model.
Verdict wording is fixed: "agent adds lift" only if C5a or C5b passes; otherwise "lift not shown", with the measured effect size. A negative result is a result. At least **two model sizes** are tested; "good enough" = the smallest model that passes.

### C6 Outage degradation (measurement, with a soft target)
Report the ratio MAE_base / MAE_edge during outage, in the first 10 min after backfill, and after. Soft target: with the best backfill handling strategy, the base arm is within **10 %** of the edge arm 10 min after link-up.

### C7 Reproducibility
Same seed + same config ⇒ identical raw-stream hash and identical truth-event log (hard requirement, unit-tested). Re-running a replay changes the per-model MAE by < **1 %** (River models seeded).

### C8 Data integrity under Skylink
After every outage cycle, points stored in the InfluxDB raw bucket = points the simulator emitted − points the buffer logged as dropped on overflow. Any other difference is a bug, and results from that run are void.

## 2. Verdicts (fixed in advance)

- **"Edge forecasting is valuable"** = C1 ∧ C2 ∧ C3.
- **"Online learning is justified"** = C4.
- **"The agent layer is justified"** = C5a ∨ C5b, *and* C5c holds.
- Anything else is reported as the specific failure, not as "mostly worked".

## 3. Pre-registered hypotheses (guesses, written before runs; direction matters more than size)

| # | Question | Hypothesis |
|---|---|---|
| H1 | RQ4 | Forecastability ranks temperature ≈ pressure > solar (outside cloud cliffs) > wind > vibration. Vibration RMS has no horizon where a model beats persistence by 5 %. |
| H2 | RQ4 | Useful horizon (skill ≥ 0.05): temperature ≥ 600 s, pressure ≥ 3600 s, solar ≤ 60 s, wind ≤ 5 s, vibration none. At h ≤ 10 s on temperature and pressure persistence is within 3 % of the best model. |
| H3 | RQ1 | The edge arm degrades only through sensor dropouts. The base arm shows ≥ 20 % MAE increase in the first 10 min after a backfill if late data are fed in arrival order; feeding in event-time order removes most of it. |
| H4 | RQ1 | Linear models on lag features (and HoltWinters) recover fastest after backfill and front passages (≤ 5 min); Hoeffding/ARF trees slowest (> 15 min). |
| H5 | RQ2 | Online + drift detection beats static by ≥ 15 % in the hour after a step change or sensor drift. In stationary stretches the two are within 3 %. |
| H6 | RQ3 | Models ≤ 4 B parameters fail C5a (macro-F1 < 0.80, with invalid-JSON rates above 5 %). A 12–20 B model reaches 0.80 on triage but is no better than the rules baseline by +0.15. |
| H7 | RQ3 | Agent-proposed model switches and hyperparameter changes give no measurable forecast lift (|Δ MAE| < 1 %): C5b fails. Agent calls add 1–30 s latency each and do not slow forecasting. |
| H8 | RQ5 | A linear-lag model costs 50–200 µs per step-horizon update; an ARF regressor costs 5–30 ms, i.e. ≥ 50× more, for ≤ 3 % extra skill. Break-even for complexity at the edge is around the linear/HoltWinters/SNARIMAX class. |
| H9 | RQ5 | The five-stream, three-horizon River service fits C2 at 1× with margin (< 0.2 core). |

## 4. Design choices that bind the experiment

- The simulator owns event time. Skylink outages are a seeded Markov on/off chain stepped in event time, so outage schedules are replayable and independent of wall-clock speed.
- Instrumentation (truth events, forecasts, errors, metrics) writes to InfluxDB directly and does **not** cross Skylink; otherwise nothing could be measured during outages. Only raw sensor data crosses the simulated link.
- The store-and-forward buffer has a finite size. Overflow drops the oldest points and is logged (C8).
- No tuning on locked seeds. No re-running a locked seed to "get a better number": every locked-seed run is logged in `JOURNAL.md`.

## Amendments

- 2026-10-17: added a deliverable, `docs/recipe.md` (evidence-tagged recipe for where River and language models create value at the edge), requested by the owner. It is not a criterion and changes no threshold, verdict rule or hypothesis. It is part of the final report.
- 2026-10-17: stop rule, proposed by the owner and made precise. A *finding* is anything that changes a claim in `docs/recipe.md`, an evidence tag, or the status of a hypothesis. The experiment and the recipe are finished when (a) the locked-seed verdict runs (seeds 101-105, 7 days, all five streams) have been done once and written up, and (b) three consecutive night cycles after that produce no finding. Until (a), "no new findings on dev seeds" does not end the experiment, because dev findings are not verdicts. No threshold, verdict rule or hypothesis is changed.
- 2026-10-24: added **C5d Retrospective review (job R)**, requested by the owner ("use the models to analyse results instead of
  selecting"). Written before any job-R code or number exists. It is a separate, reported claim: it is **not** part of the verdict rule
  "the agent layer is justified" (still C5a ∨ C5b, and C5c), and it changes no threshold, verdict rule or hypothesis above.
  - *Task.* One-hour windows of event time, all five streams. Input, made by scripts only: the link outages in the window and every
    alert in it (edge detector, plus artefact alerts from the arrival-order series), each with the 2-min context of job T plus
    *hindsight* numbers computed from the full event-time series afterwards (event-time z at the alert second, width above threshold,
    level offset after 10 s / 1 min / 10 min / 30 min / 2 h, flat run length, missing seconds, inside an outage or not). Output per
    window: a cause per alert {real_event, sensor_fault, backfill_artefact}, the list of streams with a sensor fault, and a summary of at
    most 80 words for the uplink. Truth: the simulator's event log (labels as in job T).
  - *Methods, fixed now.* R0 the job-T rules (no hindsight). R1 hindsight rules in code, written from the simulator's event
    definitions, thresholds set on dev seeds 1-2 only. R2 a model labels each alert alone (classify, hindsight numbers, 3 worked
    examples per class from seeds 1-2). R3 a model reads the whole window and returns labels, fault streams and summary in one
    schema-constrained call. R4 hybrid: the model gets R1's labels, may override one only with a stated reason, and writes the fault
    streams and summary. R0-R2 get a template summary written by code.
  - *Data.* Development comparison on **dev seed 3** (7 days), windows sampled with a fixed seed: every window holding an artefact
    alert plus random windows up to 40. Few-shot examples and R1 thresholds come from seeds 1-2 only. Locked seeds only if the owner
    adds job R to the locked runs.
  - *Metrics.* Cause macro-F1 over the alerts of the sampled windows; fault-stream precision and recall per window; summary validity
    (at most 80 words, every number, stream name and alert id in it appears in the input; checked in code); invalid-output rate;
    latency per window; bytes of the report vs bytes of the window's 1 s data. 95% CIs by bootstrap over windows (2000 resamples).
  - *Pass rule, per model method (R2, R3, R4) on its own.* "Review adds lift" if macro-F1 − R1's macro-F1 ≥ **+0.05** with the
    paired bootstrap CI of the difference excluding 0, fault-stream recall not below R1's, and summary validity ≥ **0.95**.
    "Safe as report writer" (R4 only) if summary validity ≥ 0.95 and its overrides lower macro-F1 by no more than **0.01** vs R1.
    Otherwise "lift not shown", with the effect size. At least two model sizes; three methods are tested, so a single pass is read
    with that in mind.
  - *H10 (guess, before runs).* Hindsight is what helps, not the model: R1 reaches macro-F1 ≥ 0.85 (R0 is about 0.63 on job-T cases).
    No model method beats R1 by +0.05. R3 (whole window, no rules) is below R1. R4 keeps R1's accuracy within 0.01 and writes valid
    summaries ≥ 0.95 of the time with 9-14 B models, less often with ≤ 4 B models.
- 2026-10-24: added **C5e Escalation**, requested by the owner: the small model at the edge may send a question to a "big brain"
  ashore when the link allows; the owner named the big brain: Claude. Written before any escalation code or number exists. A separate,
  reported claim, not part of the verdict rule in section 2; no threshold, verdict rule or hypothesis above changes.
  - *Cases.* The 200 edge alerts (100 real event, 100 sensor fault) of the 300 balanced job-T dev cases (seed 7) that every stored model
    run already answered. Artefact cases are left out: they arise only in the shore's view of the data, so the edge never asks about them.
    Score: two-class macro-F1 (an artefact answer counts as wrong), bootstrap over cases (2000 resamples).
  - *Edge.* gemma-4-e4b with three worked examples per class (stored run `air-fs3`), the 4B model that fits the edge. Second voter for
    the quorum trigger: Jev 0.8B (`air-fs3`). Rules: the job-T rules.
  - *Shore.* (a) Claude, answering the escalated alerts blind: questions exported without labels or ids that reveal them, in shuffled
    order, answered in one pass from the question text, the job-T hint and the station physics in `docs/slm-backend.md`, before any
    score is computed; Claude answers all 200 so every policy can be scored. (b) gpt-oss-20b and Qwen3-14B 3-shot (stored), as local
    stand-ins. (c) An oracle (truth), for the upper bound of what escalation can buy.
  - *Policies, fixed now.* P0 edge alone; P1 rules alone; P2 escalate everything; P3 escalate when edge model and rules disagree;
    P4 escalate when the two edge voters disagree (no quorum); P5 P3 or P4. The final label is the shore's answer for an escalated
    alert, the edge's otherwise.
  - *Link and timing.* Questions leave only while Skylink is up (the seeded link chain of each seed); an alert raised during an outage
    waits for link-up. Two shore modes: on call (answer 60 s after the question arrives) and daily pass (answer at the next 06:15 of
    event time, returned at the next link-up after that). Reported: escalation rate, questions per simulated day, uplink bytes,
    staleness (alert to final answer: median, p95).
  - *Pass rule, per policy and shore.* "Escalation pays" if the final macro-F1 − P0's macro-F1 ≥ **+0.10** with the paired bootstrap CI
    excluding 0, at an escalation rate ≤ **50 %**. "Big brain needed" if a policy passes with Claude and fails with both local
    stand-ins. Otherwise "not shown", with the effect sizes.
  - *H11 (guess, before runs).* P3 escalates 30-45 % and recovers most of the oracle gain; P4 is weaker (the 0.8B voter adds noise).
    Claude on the escalated alerts reaches about 0.85 two-class F1, a little above gpt-oss-20b. On-call staleness is minutes, except after
    outages (median outage 40 min); the daily pass is 12-24 h, which is fine for review and useless for alerts.
- 2026-10-24 (later the same day, after the C5e scores): **C5e follow-up, rules sent down.** Claude's 200 answers followed five
  rules, written out here before they are run on any other case: a flat alert is a fault; any temp or pressure jump is a fault; wind is
  a fault when onset z >= 10, peak z >= 15 or the next 2 min are at least half flat; vibration is a fault when the level drops and stays
  down (onset z < 0 and >= 60 s beyond threshold) or a one-second excursion has z >= 15; solar is a fault when a one-second excursion
  has |z| >= 15; everything else is a real event. Test: the 3079 edge alerts of dev seeds 1-3 not among the 200, natural mix,
  two-class macro-F1 vs the job-T rules. Prediction: >= 0.85. Exploratory (dev, rules distilled from Claude's own answers), reported
  apart from C5e's pass rule.
- 2026-10-24 (evening): **C5e inbox run**, the daily-pass escalation loop (owner: build it). Dev seeds **11-30** are added for this
  loop only (same rules as dev seeds; never 101-105), so every night brings alerts nobody has looked at. Each night the Mini simulates
  one day of one such seed, labels every edge alert with the rules sent down (`escalation.distilled_rules`), and writes questions for
  the *residue*: every wind alert, then vibration alerts with at most 2 s beyond threshold, at most 40 a night (wind first, then in
  time order). The questions hold the job-T facts and the edge's label, never the truth. The daily pass (Claude) answers them blind;
  the answers go back to the Mini and are applied and scored the next night against the simulator's truth.
  Measured per night and pooled: two-class macro-F1 of the final labels vs the distilled rules alone over **all** edge alerts of the
  night, Claude's accuracy on the escalated alerts, labels fixed / broken, questions per night, hours from question to applied answer.
  Read after at least 5 answered nights: "residue escalation pays" if the pooled gain is ≥ **+0.02** with the paired bootstrap CI
  (over nights' alerts) excluding 0. *H12 (guess):* gain +0.01 to +0.03; Claude stays near 0.7 on wind, where the 2-min facts
  are thin, so most of the value comes later from rules and hindsight, not from answers.
- 2026-10-24: **stop rule made stricter**, owner's words: continue "until we reach a stable state", "no new findings and ideas".
  The experiment ends when (a) the locked-seed verdict is written up, (b) three consecutive daily passes after it give no finding, and
  (c) no idea in `BACKLOG.md` is still open: each has been tested or written off with a reason. A new idea, from a result or from the
  owner, keeps the experiment running. No threshold, verdict rule or hypothesis changes.
- 2026-10-24: **O1, per-stream menus** (first ontology experiment, `docs/slm-backend.md`). Written before the run. The job-T triage
  call offers only the causes the station allows on the alert's stream: temp and pressure get {sensor_fault, backfill_artefact} (their
  real processes, seasonal shift and fronts, are too slow to raise a jump or flat alert); wind, vibration and solar keep all three.
  Same 300 balanced dev cases (seed 7), same three worked examples per class, same models: Qwen3-14B and gemma-4-e4b on the Air.
  Compared with the stored runs without menus (`five-q14-t3`, `air-fs3`). Reported claim, not a verdict rule. "Menus help" for a
  model if three-class macro-F1 rises by >= **+0.03** with the paired bootstrap CI excluding 0. *H13:* both models gain, the 4B
  model more; nearly all of the gain is on temp and pressure.
- 2026-10-25: added **C9 Slow degradation (job W)**, requested by the owner: an online learner may adapt to slow wear and never
  alarm. Written before any job-W code or number exists. A separate, reported claim, not part of the verdict rules in section 2; no
  threshold, verdict rule or hypothesis above changes, and the default scenario is unchanged (no wear event unless a scenario asks).
  - *Event `wear`* (a process event: the machine changes, not the sensor). One per run, on vibration only, drawn from its own RNG
    (`seed:vibration:wear`) so every other event and sample of a seed stays as it is until onset. The broadband background of the
    vibration signal (not the 0.2 Hz line, not bursts) is multiplied by g(t) = 1 + (F - 1) u^2, u = (t - t0) / D clipped to [0, 1]:
    no step, no spike, slow at first and faster later, then held at F to the end of the run (no repair). Onset t0 ~ U[3, 7] days,
    ramp D ~ U[4, 14] days, final factor F ~ U[1.5, 3.0], so the rate (F - 1) / D is 0.04-0.5 per day. Sensor faults (spike, drift,
    step, stuck, dropout) and bursts act on top of it as before; a stuck sensor hides it. Temperature is left out: the temp stream is
    ambient air at the station, with no physical path from a bearing.
  - *Runs.* 21 simulated days, all five streams, `config/scenario-wear.toml`. Each seed runs twice: with wear, and its healthy twin
    (same seed, wear off), identical until t0. Offline 1 s aggregates as in job T; no Influx, no models served, light enough for the day.
  - *Seeds.* Dev seeds 1-3, plus dev seeds **41-60**, added for job W only (same rules as dev seeds; never 101-105). Locked seeds stay
    untouched and unread. Rules and thresholds below are fixed now and are not tuned on these seeds; a revised rule goes into a new
    dated amendment and is tested on fresh dev seeds 61-80.
  - *Arm (a), online only, as now.* The edge alert detector unchanged (jump / flat against its 60 s EWMA, see job T). It flags the
    wear if, inside [t0, end], it raises a vibration alert that no other truth event explains (no fault or process event within 5 s)
    and that the healthy twin does not raise within 5 s. Its online error: MAE of the detector's EWMA as a one-step forecast over the
    last 24 h of the ramp, wear run / twin (reported, not an alert). River forecasters are not run: their errors feed no alert today.
  - *Arm (b), reference comparison, rule fixed now.* Per stream: hourly median of the 1 s aggregate (NaN if < 1800 valid seconds).
    Reference from hours 0-47 (the first 2 days, the C4 static window): mu_R = median of the 48 hourly medians, sigma_R =
    max(1.4826 MAD of them, the job-T floor of the stream). Online level L(k) = median of the hourly medians of hours k-23..k (needs
    >= 12). Gap g(k) = (L(k) - mu_R) / sigma_R. An alert starts when |g| > 4 for 6 consecutive hours and ends at the first hour with
    |g| < 2. Scored from hour 48. **(b) frozen**: mu_R never moves (re-baseline only by an operator, e.g. after maintenance; never in
    these runs). **(b') slow re-baseline**: each hour with no active alert and |g| <= 2, mu_R += (L(k) - mu_R) / 720 (30-day time
    constant); sigma_R fixed. (b) is the arm the pass rule judges; (b') is reported beside it.
  - *Metrics.* Detection: the first hour >= t0 in which the wear run's alert is active and the twin's is not; detection delay = that
    hour's end - t0, in days; no such hour = a miss. Hold: share of hours from detection to the end of the run with the alert active.
    False alerts per stream per day: alert starts in the twin runs (all five streams) outside excused stretches, divided by the days
    not excused; excused = from t0 of a step or drift sensor fault on that stream to its t1 + 30 h (24 h window + 6 h persistence),
    because there the gap is a real anomaly; alerts there are counted and reported apart. Arm (a): flags per run, ever flagged or not,
    and the error ratio. All pooled over the 23 seeds, with per-seed values in the note.
  - *Pass rule, arm (b) on vibration.* "Flags the degradation, does not adapt it away" if all four hold: detection in >= **90 %** of
    wear runs; median detection delay <= **5 days**; hold >= **0.90** pooled over detected runs; false alerts on vibration <= **0.05 per
    day** pooled over the twins. Otherwise "not shown", with the numbers. Arm (a) "adapts it away" if it flags in < 10 % of runs.
  - *H14 (owner's guess, before runs).* The online-only arm never flags the wear (0 of 23); the reference comparison flags it, with a
    delay of days. *Added before runs:* the online error ratio rises to about F by the end of the ramp, unseen by the detector; (b') flags
    later than (b) or misses the slowest ramps; arm (b) passes on vibration but gives more than 0.05 false alerts per day on pressure
    (slow weather and fronts are not in a 2-day reference), so it is a rule for machine streams, not weather.
- 2026-10-25 (later the same day): **C9 event made physical, owner's choice.** The vibration sensor is an accelerometer on the
  pedestal of the station's scanning weather radar: the antenna turns at 12 rpm (the 0.2 Hz line), the mast sways near 2 Hz (the
  resonance), and the bursts are the drive speeding up or slowing down when the scan pattern changes. `wear` is the radar's slewing
  bearing wearing out. Definition change, written before any C9 number was read: g(t) now multiplies the 12 rpm line as well as the
  broadband background (a worn bearing runs rough at the rotation rate too), so the 1 s RMS of the healthy signal grows by exactly
  g(t); bursts stay as they are. Same draws, same RNG, same onset, ramp and factor ranges, same arms, metrics, pass rule, seeds and H14.
  The first job-W run (old definition) finished but was deleted unread; the dev seeds are therefore still unseen for C9.
