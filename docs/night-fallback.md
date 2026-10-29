# Night fallback

The day host is often off or its app closed, so a daily pass can be missing. Between 2026-10-26 and 2026-10-28 no pass ran:
the night host kept old code with an empty queue and three nights ran nothing. The fallback keeps the night useful without
the pass and without changing the experiment.

## What `scripts/nightly.sh` does
1. It records the code it runs (`code: <commit>` in `runs/last-night.txt`) and appends one line per night to `runs/night-log.tsv`:
   `date, commit, queue_changed, mode, note, queue fingerprint`. `queue_changed` is `no` when `queue.txt`, `agent-queue.txt`,
   `proposal-queue.txt` and `verdict-queue.txt` are the same as on the previous night. `mode` is `queued` (a queued simulation,
   collect, agent eval or bench ran), `fallback` (nothing queued ran, a default run did) or `idle` (nothing ran at all).
   The escalation inbox takes seconds and does not count as work.
2. When nothing queued ran, it works through `config/default-queue.txt` (same columns as `queue.txt`). Finished runs are skipped,
   so the list is used up one run at a time; an exhausted list ends in `idle`. **Dev seeds only:** a locked seed (101-105)
   in that file is refused by the script and a test checks the file. The night host cannot update its own code, so the fallback
   runs the code it has; the commit in the log says which.
3. Nothing else changes: the window, the disk guards, resume and the verdict collect work as before. The verdict collect queue
   still re-scores finished runs every night, fallback or not.

## Default queue (chosen 2026-10-29)
`dev-s3-r` and `dev-s3-r2`: two replicates of dev seed 3, 7 days at 60x (about 3 h 40 min each, so one a night). They are the
road's own kind of filler ("a replicate on another dev seed is better than nothing", `docs/daily-loop.md` step 4) and test
that a seed replays exactly (same chain hash) on whatever code the night host has. Each run adds raw data to InfluxDB
(disk watch applies; the guard stops the night under 6 GB free in the VM). Add more dev lines when the road needs them.

## Missed passes
`uv run python scripts/missed_passes.py --main-commits` (after `night-sync.sh pull`) lists nights after the last journaled night
that ran without new work: unchanged queue fingerprint, or mode `fallback`/`idle`. The pass puts its output line in the journal
entry and carries on. It does not rerun missed days or work around them. A fallback night is never a finding on its own.

## Amendments
None needed: no criterion, threshold or locked seed changes, and the recipe is untouched.
