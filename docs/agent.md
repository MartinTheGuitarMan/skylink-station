# Agent layer (mcp-minions): design

Status (2026-10-16): implemented and unit-tested with a fake transport; no live model call made yet. This is written before any
agent call is made, so the evaluation cannot be fitted afterwards.

## Principle
The agent proposes. Guardrails decide. The forecast loop never waits for the agent. Every call is
logged. Every agent arm has a River-alone twin on the same replayed data.

## Transport
`mcp-minions` over MCP stdio from Python (the `mcp` client SDK), one server process per local model
configuration, launched with `MINION_BACKEND` / `MINION_MODEL` (single model) or a roster file.
Tools used: `classify` (triage), `extract` (schema-constrained proposals and failure explanations),
`summarize` (situation notes). The repo itself is not modified. Calls run in a worker thread with a
queue; when the queue is full, the oldest request is dropped and logged as `dropped`.

## Jobs, inputs, outputs
| Job | Tool | Input (built in code from stats, never raw streams) | Output, validated in code |
|---|---|---|---|
| T. Alert triage | `classify` | stream, time, magnitude in sigma, duration, flat-line flag, link state, minutes since backfill, other streams moving? | one of `real_event`, `sensor_fault`, `backfill_artefact` |
| P. Proposal | `extract` | per stream and horizon: rolling MAE of each candidate model, dwell time, recent alerts | `{action: keep or switch, model: <one of the allowed>, horizon, reason<=200 chars}` |
| N. Situation note | `summarize` | structured hourly stats | text of at most 80 words; every number in it must appear in the input stats |
| E. Failure explanation | `extract` | window around a large error: events seen, link state, model | `{cause: one of enum, evidence<=200 chars}` |

## Action space and guardrails (job P)
Allowed: switch the *served* model for one (stream, horizon) among the models already running
(`lin_lag`, `lin_lag_static`, `hat`, `holt`, `persistence`, `seasonal_naive`). No new model, no
hyperparameter outside a fixed list, no code. Guardrails: at most 1 switch per (stream, horizon)
per 30 min of event time; a switch is rolled back automatically if the 10 min MAE after it exceeds
the 10 min MAE before it by more than 20 %; a proposal for a model with a worse trailing MAE than
the incumbent by more than 50 % is rejected; invalid or out-of-enum output is rejected and counted.
The twin without agent serves the fixed default (`lin_lag`). A *rules* twin (switch to the best
trailing-MAE model, same guardrails) is added, because "agent beats nothing" is a weak claim;
the agent has to beat the rules to count.

## Logging
Every call to `agent` bucket measurement `call` (tags run, job, model; fields latency_ms, ok,
accepted, valid_json) and a JSONL file `runs/<run>/agent_calls.jsonl` with prompt-relevant input,
raw output, parsed output, verdict and outcome (the 10 min MAE change after an accepted switch).

## Scoring (feeds C5)
- T: macro-F1 against simulator truth, vs the rules baseline and vs a constant-class baseline.
- P: paired MAE difference, agent twin vs fixed twin vs rules twin, block bootstrap.
- N: factual-consistency rate (numbers present in the stats), mean words.
- E: accuracy of `cause` against the truth event overlapping the window.
- All: latency p50/p95, invalid-JSON rate, accepted fraction, per model.

## Models to try (LM Studio, already on disk)
`google/gemma-3-1b` (1B), `google/gemma-4-e4b` (4B), `google/gemma-4-12b` (12B), `openai/gpt-oss-20b`
(20B, reasoning). Smallest passing model counts as "good enough". Only one big model loaded at a
time on the Air; the Mini decides what can run in parallel.

## Dependencies
Triage needs the base arm (alerts that can be backfill artefacts), backlog item 4.

## Implementation map
- `src/skylink/agent/minions.py`: MCP stdio client (`MinionsClient`), `FakeTransport` for tests. Errors come back as codes, never raise.
- `src/skylink/agent/jobs.py`: triage (classify), proposal and explanation (extract with a JSON schema), note (summarize; numbers must appear in the input), call log (JSONL).
- `src/skylink/agent/alerts.py`: plain detector, truth-labelled cases from the simulator, arrival-order artefact cases, rules baseline.
- `src/skylink/agent/linkmodel.py`: Python twin of the Node-RED outage chain (tested against the JS, transition by transition).
- `src/skylink/agent/guard.py`: guardrails (action space, dwell, evidence, 50 % worse rejection, 20 % rollback).
- `scripts/agent_eval.py`: triage evaluation. `scripts/agent_proposals.py`: closed-loop fixed vs rules vs agent bench.
Dev-seed case set (seeds 1-3, 7 days): 2331 real events, 948 sensor faults, 216 backfill artefacts
(1022 ambiguous and 26 unexplained alerts dropped). Rules baseline macro-F1 on a balanced set: 0.658, so C5a
needs 0.81 or more. The rules fail on faults that look like events and on real events during replays.
Caveat: artefact cases come from a Python re-implementation of Skylink's replay (same mechanism, own random
shuffle), not from the live Node-RED run.
