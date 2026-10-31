# Daily loop

How the experiment moves without the owner. One pass a day on the day host (a scheduled Claude task in the
morning), after the night on the night host. Do one pass, report, stop. The rules in `CLAUDE.md` still hold.

## The pass
1. **Look.** `git status -sb`, `git log --oneline -5`, then `scripts/night-sync.sh status` and `scripts/night-sync.sh pull`.
   Read `runs/night/last-night.txt` and whatever is new under `runs/night/` (`agent/proposals-*.txt`, `*/summary.json`,
   `reports/`). If the night host has commits missing here, merge `night/main` first.
   **Disk watch** (retention is by run, see "Raw data retention" below; this replaces the owner's 2026-10-24 line "keep the Influx raw data, but watch it"): `status` prints the night host's free disk; the Influx
   data size and VM disk come from the `vm disk at end` line of `last-night.txt`, because the Docker VM is off by day (`docs/vm-on-demand.md`;
   `status` says `VM off`). Grafana and InfluxDB are not reachable by day either. Put both in the report's first line. Under 20 GB free, say so under `Behöver dig:`; the fix on the table is to export finished runs to cold storage and drop their raw points
   once the export is verified (`scripts/cold-export.sh`, then `scripts/drop-raw.sh`), which is the owner's call. Never delete data on the night host to make room.
   A simulation does not start under 100 GB free or when the VM disk does not answer (`MIN_SIM_FREE_GB`, `nightly.sh`), and stops itself under 10 GB (`MIN_RUN_FREE_GB`).
   `VM NOT ANSWERING` from `status` is an incident: read-only checks only, then `Behöver dig:`.
1b. **Missed passes.** `uv run python scripts/missed_passes.py --main-commits` (reads `runs/night/night-log.tsv`, see
   `docs/night-fallback.md`). If it lists nights, put its line in this pass's journal entry as is, note which code the night host
   ran, and go on with the pass: do not redo the missed days, and do not count a fallback run as a finding.
2. **Write up the night.** In `JOURNAL.md`: one entry per finished item (Why, Result, Read honestly, Decision) and the line
   `Night YYYY-MM-DD: finding` or `no finding` (a finding is defined in the Amendments of `docs/success-criteria.md`).
   Log incidents too: an item cut at the window end, a failure, `disk low`, `nothing ran`. Update `docs/recipe.md` (tags
   honest) and `BACKLOG.md`. Copy a report into `reports/` only when it is cited.
2b. **Answer the escalation inbox** (C5e inbox run, `docs/escalation.md`; you are the big brain). After the pull:
   `uv run python scripts/escalate.py pending`, then for each night `uv run python scripts/escalate.py show <night>`.
   Answer every question blind, from its facts, the station physics in `docs/slm-backend.md` and the edge's label: one JSON line
   per question in `runs/escalation/outbox/<night>.jsonl`, `{"q", "label": real_event|sensor_fault, "kind", "why" (<= 120 chars),
   "keep_as_example": true|false}`. Mark an example only when the facts make the case clear. Never run the simulator, open
   `runs/night/escalation/summary.*`, or look up truth for a night before its answers are written. Then
   `uv run python scripts/escalate.py check <night>` (must say no errors) and send in step 5. Read `runs/night/escalation/summary.md`
   for nights the night host has applied: one journal line per night; read the pooled result only after 5 nights. If the answers show a
   pattern the rules sent down miss, propose the rule under `Behöver dig:`; the edge's rules stay frozen during the inbox run unless
   an amendment says otherwise.
3. **Build the next step.** Take the first open item on the road below. Small commits, one change at a time,
   `uv run pytest -q` green before each commit. Offline checks on the day host are fine if short (under 30 min, `nice`d).
4. **Queue tonight.** Add lines to `config/queue.txt`, `config/agent-queue.txt` or `config/proposal-queue.txt`.
   The window is 7 h (23:00-06:00). Budget from measured wall times: a 7-day simulation at 60x about 3 h 40 min (dev-s2-r, 2026-10-26), so one fits a night, two do not; the job P bench,
   3 days, five streams, gemma3:4b + qwen3:8b about 6 h (qwen3:8b is 5 of those). A cut simulation or agent eval resumes; a cut
   job P bench starts over, so never queue one that does not fit. Do not leave a night empty when something useful fits:
   a replicate on another dev seed is better than nothing.
5. **Ship.** `scripts/night-sync.sh answers` (escalation answers, any time; the night host applies them next night). Commit (one logical change each), then `scripts/night-sync.sh push`. It refuses while a night job runs; then
   push after 06:00 the next day, or let tomorrow's pass do it. Never push to GitHub: the owner does that.
6. **Report** (the final message, in Swedish, short): what the night gave (1-3 lines), what was built, what runs tonight, and at
   most one line `Behöver dig:` with the default you will take if there is no answer within two passes. Only things the
   rules reserve for the owner go there.

## Road to the verdict (keep this list current; it is the plan the pass follows)
1. ~~**Job P on dev seed 3**~~ Done on the night 2026-10-24/25; dev reading of C5b on seeds 1-3 in the journal (lift not shown).
   A larger model (Qwen3-14B, about 8 GB) for job P would need disk on the night host: ask, do not download.
1b. ~~**Escalation inbox, pooled read**~~ Done 2026-10-31 on 5 nights (`reports/escalation-inbox-2026-10-31.md`): residue escalation pays on dev.
   The inbox keeps running: answer it in step 2b every pass.
1c. **Job R model arms** (C5d): on the day host, on power, at most 30 min a pass, `nice`d, one model loaded at a time (16k context):
   Qwen3-14B and gemma-4-e4b, R2-R4 (pilot on 8 windows done, iterations 16 and 19), then the full 40 windows in chunks (gemma-4-e4b done 2026-10-31, Qwen3-14B next)
   (`review_eval.py run --until`). Battery: skip, say so.
1d. ~~**Ontology experiments**~~ Experiments 2-5 written off 2026-10-25 (owner; O1 answered the question). Instead: backlog open
   items 4 (knowledge or model) and 6 (ARF cost), on the day host like 1c.
2. ~~**Backlog 1, base arm and backfill strategies** (C3, C6).~~ Done on dev seeds 1-3 (iteration 12): C6 ratios per phase
   (`--base`) and C3 recovery (`--recovery`). The verdict pipeline must take C3's best River model only and add the edge control.
3. ~~**Jobs N and E**~~ Written off 2026-10-25 (owner): no verdict depends on them. ~~Instead: the bootstrap CI for C5b~~ Built
   2026-10-29 (`jobs.macro_ratio_ci`, paired on hours; `c5b_check` and `verdict.py decide` use it when the bench has per-hour sums).
4. ~~**Verdict pipeline.**~~ Built and dry-run on dev (iteration 18): `scripts/verdict.py collect` on the night host (about 5 min a
   run), `decide` anywhere, `reports/verdict-<label>.md`. Before the locked runs it still needs two inputs the dry run showed missing:
   (a) a **C2 run at 1x** on the night host (dev seed, all five streams, about 2 h of the night window; then `collect --c2-run`;
   ran 2026-10-25/26 as `dev-c2-1x`; its collect is in `config/verdict-queue.txt`, which `nightly.sh` works through after the
   simulations since 2026-10-29), and
   (b) a **C7 replicate**: run one locked seed twice (both logged) and pass `--replicate`.
   Both ready 2026-10-30 (`reports/verdict-dev-r.md`): C2 holds on dev-c2-1x; C7 and C8 work on a dev replicate pair.
5. **Locked runs** (started 2026-10-30; **paused 2026-10-31**: `locked-101` was stopped at block 1774 of 10080 by a full host disk and the Docker VM's disk broke, journal 2026-10-31; before any locked run: VM answering, at least 100 GB free on the host, and the owner's call on the partial `locked-101`; next 102, 103, 104, 105, then `locked-101b` as the C7 replicate). Seeds 101-105, 7 days, all five streams, `config/scenario-default.toml` (one 7-day run a night: five seeds plus the C7 replicate is about six nights; queue each
   run's collect under label `locked` in `config/verdict-queue.txt`), then C5a/C5b on
   locked cases (first check job P on a dev seed: `extract` may refuse its required free-text `reason`, journal iteration 21). Default unless the owner says otherwise: job R (C5d) and escalation (C5e) are scored on the locked runs too,
   as reported claims outside the verdict rule. Log every locked run in the journal. Write `reports/verdict.md` with the final form of the recipe.
6. **Stop rule (stable state).** After the verdict, count passes: the experiment is stable when three consecutive passes give `no finding` **and** no idea is left open (owner, 2026-10-24: "no new findings and ideas"). Every pass ends its journal entry with `Open ideas: N` from `BACKLOG.md`; an idea leaves the list only when tested or written off with a reason. A new idea resets the count. Then write the final
   report and start the report with `STOPP NÅTT`, asking the owner to turn off the scheduled task and the night host's nightly daemon.

## Raw data retention (owner, 2026-10-31)
Raw sensor points leave InfluxDB by run, not by age. A finished run is scored, passes its C8 data check, is exported to cold
storage (`scripts/cold-export.sh <run>`: zstd Parquet, manifest with per-stream counts, SHA-256, verified against `summary.json`)
and only then may its raw points be dropped (`scripts/drop-raw.sh` refuses a run with no verified export).
- **Dev runs:** export, then drop.
- **Locked runs:** raw stays in InfluxDB until the locked verdict is written, then is exported (`--allow-locked`) and needs a second
  copy on other storage before anything is dropped. `drop-raw.sh` still refuses locked runs; the owner decides that drop.
- **Void or partial runs:** the owner decides per run.
- **Kept forever:** summaries, configs, truth events, reports and the journal.
- **Forecasts** stay until the final report, then are archived.
The simulator recreates any run's raw data from its seed (C7), which is why a dev export is a convenience, not the only copy.
Cold storage is an APFS volume on an external drive on the night host (`/Volumes/Cold`, or `COLD_ROOT`); nothing is exported when it
is not mounted. The export streams in one-hour windows and writes in a hidden directory that is renamed only after the check.

## Ask the owner first (in the report, never by waiting mid-pass)
Model downloads or anything else that uses disk on the night host beyond run outputs; deleting data on the night host; anything outside this
directory other than the night host's checkout and its stack (Docker VM, Ollama); runs outside the night window; anything that costs money;
pushing to GitHub. Never change a pre-registered threshold, verdict rule or hypothesis.
