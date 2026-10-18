# Recipe: where River (online ML) and language models create value at the edge

A living document and one of the experiment's deliverables. Every line carries an **evidence tag**:
`dev` = seen on development seeds only; `locked` = confirmed on locked seeds 101-105 (none yet);
`untested`. Nothing here is a verdict until `locked`. Source of truth for numbers: `JOURNAL.md`, `reports/`.

## 1. Decide per stream whether forecasting is worth it
Measure skill against persistence first (it is free and often hard to beat). `dev`:
- Smooth, strongly structured streams (temperature): a simple online linear model beats persistence by 5 % at 10 s, 15 % at 1 min, 20 % at 10 min, 35-40 % at 1 h.
- Gusty or oscillating streams (wind, vibration RMS): 18-27 % at seconds to minutes.
- Random-walk-like streams with unpredictable regime changes (pressure with fronts): nothing beyond about a minute. Do not spend compute on it.
- Streams dominated by sudden cliffs (solar with cloud edges): every *learned* model lost to persistence (-10 to -24 %). A parameter-free geometric correction does not: scale the present value by the ratio of a clear-sky shape between now and the horizon (`clearsky_adapt`, noon taken from yesterday's curve), +1 to +3 % from 30 s to 5 min, `dev` seeds 1-3; a fixed noon loses 1 % after a seasonal phase shift. Small, but the only gain on this stream. A linear learner on the residual of that forecast still loses 7-25 %: do not train on cloud cliffs.

## 2. Pick the cheapest model that clears the bar
Standardise, clip features (spikes must not blow up a linear learner), predict **increments** (y[t+h] - y[t]) so an untrained model equals persistence, and use a stable learner (Bayesian ridge, `dev`). Per-step cost `dev`: persistence 1 us, linear 55-75 us, Hoeffding adaptive tree 110-520 us, SNARIMAX about 1 ms for +1 % at short horizons. Trees collapse on solar and pressure and crash on constant input. Complexity has not paid anywhere yet.

## 3. Treat adaptation as something to prove, not assume
`dev`: online beat frozen at long horizons on temperature (about +6 to +10 points of skill at 10 min to 1 h). Drift detectors watching the absolute error with reset or challenger replacement hurt badly at 1 min and above (error variance moves with the time of day; a fresh model cannot relearn a diurnal pattern in 10 minutes). Use forgetting or volatility-normalised signals instead (`untested`).

## 4. Outages: design the edge so it does not need the uplink
`dev`: the edge forecaster is unaffected by Skylink; the base side loses real-time forecasts during an outage (coverage 0-12 %) and 21-35 % of them in the 10 minutes after link-up. Feeding backfill in arrival order costs about nothing in error when history is addressed by absolute time (MAE within 3 % of the edge); waiting for a clean time-ordered replay costs coverage (65 % vs 79 %), not accuracy. Rule: key history by event time, tag replayed data, never let hindcasts count as real-time forecasts.

## 5. Where language models fit (they are not forecasters)
- **Triage of alerts** (fault vs real event vs replay artefact). `dev`: zero-shot, no model beat a three-line rules baseline (best 0.60 vs 0.63 macro-F1; 1B models answer one class). With three worked examples per class in the prompt, gemma-4-e4b (4B) reached 0.76 (+0.13 over rules, still short of the preregistered bar). Decision models (Jev 0.8B) were fast (0.16 s), always valid, but not calibrated on numeric context. Reasoning models are too slow for alerts (qwen3:4b about 97 s per case).
- **Model selection**: `untested` live; a scripted agent that always proposes the wrong model lost 11 % even behind guardrails. The agent must beat a "pick the best trailing MAE" rule, not nothing.
- **Notes and explanations**: `untested`.
Recipe so far: rules first for what rules can decide; a small model only for the residue; few-shot examples written from reviewed cases; every output validated in code; the model proposes, guardrails decide.

Model choice for these jobs (general comparison of fifteen local model runs on an Air and a Mini, one run each, `dev`): honesty ("I don't have that" instead of an invented number) separates models more than size does; qwen3:8b was the best all-rounder, gemma-4-12b the most careful, llama3.1:8b and phi4-mini the fastest but they invent; below about 3B nothing is reliable on grounded questions. Thinking models need a token budget well above 3000 or they return nothing.

## 6. Guardrails that are cheap and worked in tests
Action space fixed in advance; one change per 30 min; reject proposals worse than the incumbent by 50 %; automatic rollback when the next 10 minutes are 20 % worse; log every call with input, output, latency, verdict. Count invalid outputs as failures.

## 7. Footprint to budget for `dev` (Air VM and Mini)
River service for five streams, ten models, base arms at 60x: roughly 0.3-0.45 of a core, about 130 MB. Local model servers dominate memory: a 4B model needs about 3-7 GB, Jev 0.8B about 5 GB resident (MLX), a 20B model 12 GB. On a 16 GB machine that already holds a 6 GB Docker VM, run one model at a time and never during family use.

## Open questions this recipe still needs answered
Does the agent add lift over a trailing-MAE rule (RQ3)? Does an adaptive mechanism that fits increment models beat frozen (RQ2)? Which of the above survives locked seeds? What is the break-even for model complexity on the Mini (RQ5)?
