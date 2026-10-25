# Backlog (ranked; shown five at a time)

Top five:
1. **Base arm and backfill strategies**: arrival order vs event-time order vs ignore-late (RQ1). C6 ratios per phase exist (iteration 2); C3 recovery scoring built and run on dev seeds 1-3 (iteration 12; strategies alike, base arm recovers slower than the edge control). Left: fold C3 (best River model only, edge control column) and C6 into the verdict pipeline (road step 4).
2. ~~Drift mechanism that fits increment models~~ **Closed on dev seeds in iteration 8**: C4/H5 not supported; forgetting and volatility-normalised boost did not beat plain online in event windows. Locked-seed runs report both references (frozen and `lin_lag_retrain`).
3. **Agent layer**, remaining gaps (audit 2026-10-18; client, jobs, guardrails, rules twin, async worker, call log with verdicts and C5b/C5c summaries exist):
   a. *Large:* run jobs P, N, E live with at least two model sizes. P ran live on dev seeds 1-3 (gemma3:4b, qwen3:8b; nights 2026-10-22/23 and 10-24/25; dev reading: lift not shown); N and E not yet (need 3d).
   b. *Large:* the agent in the live stack (engine serves the chosen model per arm; twin arms on the same replay). C5b is offline only for now.
   c. *Medium:* ~~nightly.sh section and all five streams~~ done (iteration 11 added the window stop). Left: several horizons per stream (one each now).
   d. *Medium:* scoring for jobs N (numbers in the stats, words) and E (cause against the truth event overlapping the window); no eval script yet.
   e. *Small:* bootstrap CI of the macro MAE ratio in `c5b_check`; mirror the call log to the Influx `agent` bucket (measurement `call`; bucket exists, nothing writes it).
   f. *Small:* the 10-min post-switch outcome (`CallLog.verdict(outcome=...)`) is never filled in by the bench.
4. ~~Solar models~~ **Done offline in iteration 6**: clear-sky ratio beats persistence by 1-3 % on dev seeds; learned models still lose. Waiting for the night host runs. Robust (quantile, Huber) learner on the shape residual tried in iteration 9: no win, out of the default set.
5. **Locked-seed verdict runs** (seeds 101-105, 7 days, all streams) once 1-4 are in; needs the night window and the night host.

Next:
1a. ~~**Cause of the dev-s2-drift raw hole**~~ Found: the colima VM disk (40 GB) filled; guard added. Needs room before the locked runs (owner). (iteration 18, C8): about 1.3 days of event time missing in the raw bucket. Look at the night host's logs of 2026-10-18/19 (Node-RED buffer, colima, reboots) before the locked runs; a hole there voids a locked run.
1b. **Job R, retrospective review (C5d)**: rules arm done on dev seed 3 (iteration 13, R1 0.943). Pilot on 8 windows done for Qwen3-14B and gemma-4-e4b, R2-R4 (iterations 16, 19). Left: 40 windows with two model sizes; then ask the owner whether job R joins the locked runs.
1d. **Influx raw data growth** (31 GB on 2026-10-24, retention forever): owner said keep it for now and watch it (daily loop, disk watch). Option when needed: delete a run's raw data after its C8 check; the simulator recreates it from the seed.
1h. **Checked reference for wear (C9 follow-up)**: the frozen 2-day reference missed 5 of 23 dev runs, all with sensor faults inside it (iteration 20). Pre-register a reference built only from hours the edge rules call clean (or commissioned and confirmed ashore), test on fresh dev seeds 61-80.
1e. **Escalation** (`docs/escalation.md`, C5e `dev`): next, pre-register and run (a) a residue trigger (wind, short vibration excursions) with the distilled rules as the edge, on fresh cases answered blind; (b) local models with the same physics text; (c) the teacher loop (Claude's reviewed answers as the edge model's examples). Daily-pass inbox built (iteration 15), running e11-e17; read after 5 answered nights. On-call API mode costs money: ask the owner.
1f. **Knowledge or model?** Give Qwen3-14B and gemma-4-e4b the station physics text Claude had (`docs/slm-backend.md`) on the 200 escalation edge cases; if most of the gap to Claude (0.935 vs 0.76) closes, the edge needs to escalate far less. Pre-register first.
1g. **Teacher loop.** After 5+ inbox nights: Claude's reviewed answers (`examples.jsonl` on the night host) as the 4B edge model's worked examples; does its accuracy on the residue rise night by night? Pre-register first.
1c. **Station ontology for the model jobs** (`docs/slm-backend.md`): one JSON file of streams, kinds, signatures and allowed causes; generate schemas, menus and prompt definitions from it. Five experiments ranked there; first: per-stream menus for R2/R3.
2b. **Event-window scoring** in `skylink.analysis` (MAE in the 60 min after logged fronts, steps, drifts vs static): needed for the C4 verdict.
0. Keep `docs/recipe.md` current after each night's results (deliverable; upgrade tags to `locked` only after the verdict runs).
6. ARF regressor on a dedicated heavy config, to measure the cost/benefit break-even (RQ5).
7. Score script charts (weekly report): skill vs horizon per stream, recovery curves after events.
8. Downsampling task in InfluxDB so Grafana can show multi-day ranges.
9. Persist the Node-RED buffer (file context) so a restart does not void a run.
10. Move the stack to the night host (needs the human; the day host is the dev host for now).
