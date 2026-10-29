# Backlog (ranked; shown five at a time)

Triaged with the owner on 2026-10-25: open ideas cut from about 20 to 7. An idea leaves this list only when it is tested or
written off with a reason (stop rule, `docs/success-criteria.md`). New ideas go into **Open**, ranked.

## Open
1. **Locked-seed verdict runs** (seeds 101-105, 7 days, all streams; road step 5), after their two inputs: the C2 run at 1x
   (`dev-c2-1x` ran 2026-10-25/26; collect queued 2026-10-29) and the C7 replicate (one locked seed twice, both logged).
   One 7-day run fits a night (3 h 40 min), so about six nights.
2. **Job R, retrospective review (C5d)**: rules arm done on dev seed 3 (iteration 13, R1 0.943). Pilot on 8 windows done for
   Qwen3-14B and gemma-4-e4b, R2-R4 (iterations 16, 19). Left: 40 windows with two model sizes; then ask the owner whether job R joins
   the locked runs.
3. **Escalation inbox** (C5e inbox run): e11-e14 were asked 2026-10-25 to 10-28 but answered only on 2026-10-29 (no pass
   ran 10-26 to 10-28); read the pooled result after 5 answered nights and write it up.
4. **Knowledge or model?** Give Qwen3-14B and gemma-4-e4b the station physics text Claude had (`docs/slm-backend.md`) on the 200
   escalation edge cases; if most of the gap to Claude (0.935 vs 0.76) closes, the edge needs to escalate far less. Pre-register
   first. One short day-host run on stored cases.
5. **Teacher loop.** After 5+ inbox nights: Claude's reviewed answers (`examples.jsonl` on the night host) as the 4B edge model's
   worked examples; does its accuracy on the residue rise night by night? Pre-register first.
6. **ARF cost (H8, RQ5)**: a short per-step cost measurement of the ARF regressor on the day host (a few hours of event time, not a
   night), enough to read H8's cost ratio and the complexity break-even.

## Closed (done)
- **Bootstrap CI of the macro MAE ratio in `c5b_check`** (2026-10-29): paired on hours across streams; the bench stores
  per-hour sums from now on. The dev job P readings (seeds 1-3) predate it and stay point readings.
- **Base arm and backfill strategies** (RQ1): C6 ratios per phase and C3 recovery on dev seeds 1-3 (iterations 2, 12); both are in
  the verdict pipeline (iteration 18).
- **Drift mechanism that fits increment models**: closed on dev seeds in iteration 8 (C4/H5 not supported). Locked runs report both
  references (frozen and `lin_lag_retrain`).
- **Solar models**: clear-sky ratio, iteration 6; robust learners on the residue, iteration 9 (no win).
- **Cause of the dev-s2-drift raw hole**: the Docker VM disk filled; guard added, disk grown (2026-10-24).
- **Event-window scoring** for C4: built (`event_window_table`, `c4_verdict`) and used in iteration 8.
- **Move the stack to the night host**: done; the stack runs there every night.
- **Agent layer: nightly section and all five streams**: done (iteration 11).
- Standing tasks, not ideas (now only in `docs/daily-loop.md`): keep `docs/recipe.md` current after each night; watch the InfluxDB
  raw data growth (disk watch).

## Written off (2026-10-25, owner, with the reason)
- **Agent in the live stack** (was 3b): C5b is defined on the same replayed data, which the closed-loop bench provides; no verdict needs it.
- **Several horizons per stream for job P** (3c): job P showed no lift on three dev seeds; more horizons would not change the claim.
- **Jobs N and E live, and their scoring** (3a, 3d): no criterion or verdict depends on them; job R already tests the model as a
  summary writer (C5d).
- **Mirror the call log to the Influx `agent` bucket** (3e, second half): cosmetic; the JSONL call log is the record.
- **Post-switch outcome field in the call log** (3f): no criterion reads it.
- **Ontology experiments 2-5** (1c): O1 answered the question (a small station ontology is worth about a model size); the rest refine it.
- **Escalation follow-ups (a)-(c)** (1e): (a) is the inbox run itself (open item 4); (b) and (c) are open items 5 and 6.
- **Checked reference for wear** (1h, C9 follow-up): moved to the next experiment (Water Plant Co, its virtual pump sensors), where a checked reference
  is the central question.
- **Score charts** and **InfluxDB downsampling** (7, 8): presentation only; no finding can come from them.
- **Persist the Node-RED buffer** (9): C8 already voids a run hit by a restart; mitigation for the locked runs: no restarts or
  updates on the night host while they run.
