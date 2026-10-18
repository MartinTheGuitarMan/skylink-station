# Backlog (ranked; shown five at a time)

Top five:
1. **Base arm and backfill strategies**: arrival order vs event-time order vs ignore-late (RQ1); prerequisite for alert triage.
2. **Drift mechanism that fits increment models**: ADWIN on volatility-normalised error, or exponentially forgetting least squares (RQ2). Error-stream ADWIN with reset or challenger was harmful (journal, iteration 1). **Built in iteration 4, dev run queued; waiting for the result.**
3. **Agent layer**, remaining gaps (audit 2026-10-18; client, jobs, guardrails, rules twin, async worker, call log with verdicts and C5b/C5c summaries exist):
   a. *Large:* run jobs P, N, E live with at least two model sizes (never called live; a 4B and a 12B on the Mini, night window).
   b. *Large:* the agent in the live stack (engine serves the chosen model per arm; twin arms on the same replay). C5b is offline only for now.
   c. *Medium:* closed-loop proposal bench on all five streams and several horizons per stream (it runs one horizon per stream; `--streams` already takes all five), plus a nightly.sh section for it (not touched: it is the Mini's script).
   d. *Medium:* scoring for jobs N (numbers in the stats, words) and E (cause against the truth event overlapping the window); no eval script yet.
   e. *Small:* bootstrap CI of the macro MAE ratio in `c5b_check`; mirror the call log to the Influx `agent` bucket (measurement `call`; bucket exists, nothing writes it).
   f. *Small:* the 10-min post-switch outcome (`CallLog.verdict(outcome=...)`) is never filled in by the bench.
4. ~~Solar models~~ **Done offline in iteration 6**: clear-sky ratio beats persistence by 1-3 % on dev seeds; learned models still lose. Waiting for the Mini runs. Left over: a robust (quantile) learner on the shape residual.
5. **Locked-seed verdict runs** (seeds 101-105, 7 days, all streams) once 1-4 are in; needs the night window and the Mini.

Next:
2b. **Event-window scoring** in `skylink.analysis` (MAE in the 60 min after logged fronts, steps, drifts vs static): needed for the C4 verdict.
0. Keep `docs/recipe.md` current after each night's results (deliverable; upgrade tags to `locked` only after the verdict runs).
6. ARF regressor on a dedicated heavy config, to measure the cost/benefit break-even (RQ5).
7. Score script charts (weekly report): skill vs horizon per stream, recovery curves after events.
8. Downsampling task in InfluxDB so Grafana can show multi-day ranges.
9. Persist the Node-RED buffer (file context) so a restart does not void a run.
10. Move the stack to the Mac Mini (needs the human; the Air is the dev host for now).
