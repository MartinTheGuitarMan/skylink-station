# Daily loop

How the experiment moves without the owner. One pass a day on the Air (a scheduled Claude task in the
morning), after the night on the Mini. Do one pass, report, stop. The rules in `CLAUDE.md` still hold.

## The pass
1. **Look.** `git status -sb`, `git log --oneline -5`, then `scripts/mini-sync.sh status` and `scripts/mini-sync.sh pull`.
   Read `runs/mini/last-night.txt` and whatever is new under `runs/mini/` (`agent/proposals-*.txt`, `*/summary.json`,
   `reports/`). If the Mini has commits missing here, merge `mini/main` first.
2. **Write up the night.** In `JOURNAL.md`: one entry per finished item (Why, Result, Read honestly, Decision) and the line
   `Night YYYY-MM-DD: finding` or `no finding` (a finding is defined in the Amendments of `docs/success-criteria.md`).
   Log incidents too: an item cut at the window end, a failure, `disk low`, `nothing ran`. Update `docs/recipe.md` (tags
   honest) and `BACKLOG.md`. Copy a report into `reports/` only when it is cited.
3. **Build the next step.** Take the first open item on the road below. Small commits, one change at a time,
   `uv run pytest -q` green before each commit. Offline checks on the Air are fine if short (under 30 min, `nice`d).
4. **Queue tonight.** Add lines to `config/queue.txt`, `config/agent-queue.txt` or `config/proposal-queue.txt`.
   The window is 7 h (23:00-06:00). Budget from measured wall times: a 7-day simulation at 60x about 3.5 h; the job P bench,
   3 days, five streams, gemma3:4b + qwen3:8b about 6 h (qwen3:8b is 5 of those). A cut simulation or agent eval resumes; a cut
   job P bench starts over, so never queue one that does not fit. Do not leave a night empty when something useful fits:
   a replicate on another dev seed is better than nothing.
5. **Ship.** Commit (one logical change each), then `scripts/mini-sync.sh push`. It refuses while a night job runs; then
   push after 06:00 the next day, or let tomorrow's pass do it. Never push to GitHub: the owner does that.
6. **Report** (the final message, in Swedish, short): what the night gave (1-3 lines), what was built, what runs tonight, and at
   most one line `Behöver dig:` with the default you will take if there is no answer within two passes. Only things the
   rules reserve for the owner go there.

## Road to the verdict (keep this list current; it is the plan the pass follows)
1. **Job P on dev seed 3** (`mini-p3`, queued 2026-10-23) to finish the dev triple for C5b/C5c. Then write the dev reading of C5b.
   A larger model (Qwen3-14B, about 8 GB) would need disk on the Mini (5 GB free on 2026-10-23): ask, do not download.
2. **Backlog 1, base arm and backfill strategies** (C3, C6). Check the journal first: the arrival-order vs event-time-order
   part has dev numbers in recipe section 4; close what is done, build what the verdict still needs.
3. **Backlog 3d, scoring for jobs N and E**, then a live night for them with two model sizes (3a). Backlog 3b (the agent in the
   live stack) is not needed for the verdict: C5b is defined on the same replayed data, which the closed-loop bench provides.
4. **Verdict pipeline.** One script that turns the locked run ids into every C1-C8 number and the verdict lines of
   section 2 of `docs/success-criteria.md`. Dry-run it end to end on dev seeds and commit before any locked run.
5. **Locked runs.** Seeds 101-105, 7 days, all five streams, `config/scenario-default.toml` (about two nights), then C5a/C5b on
   locked cases. Log every locked run in the journal. Write `reports/verdict.md` with the final form of the recipe.
6. **Stop rule.** After the verdict, count nights: three consecutive `no finding` nights end the experiment. Then write the final
   report and start the report with `STOPP NÅTT`, asking the owner to turn off the scheduled task and the Mini's nightly daemon.

## Ask the owner first (in the report, never by waiting mid-pass)
Model downloads or anything else that uses disk on the Mini beyond run outputs; deleting data on the Mini; anything outside this
directory other than the Mini checkout and its stack (colima, ollama); runs outside the night window; anything that costs money;
pushing to GitHub. Never change a pre-registered threshold, verdict rule or hypothesis.
