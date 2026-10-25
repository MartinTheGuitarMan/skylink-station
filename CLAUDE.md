# skylink-station

An experiment run by an autonomous lead engineer. The brief is in `docs/success-criteria.md`
(criteria and hypotheses, pre-registered: amend only in its Amendments section, dated) and
`JOURNAL.md` (what was tried, why, result, decision). `BACKLOG.md` is the ranked list of ideas.

## Rules
- Never touch anything outside this directory without asking (launchd, other repos, system settings).
  Docker is the exception: the stack runs in colima profile `skylink`.
- Small reversible improvements: just do them, commit, log in JOURNAL.md. Larger code changes in this
  repo that serve the road in `docs/daily-loop.md`: do them step by step. New infra, model downloads,
  big model swaps, things that cost money or run outside the night window 23:00-06:00
  Europe/Stockholm: backlog, and ask in the report.
- The day's work follows `docs/daily-loop.md` (one pass a day, scheduled on the day host).
- Change one thing at a time so results stay attributable.
- Locked seeds 101-105 are for the final verdict only. Log every locked-seed run in the journal.
- No secrets in git (`.env` is ignored; only `.env.example` is tracked). Git identity is global; do not change it.
- The agent proposes, guardrails decide. Always keep the River-alone arm on the same replay.
- Heavy runs only in the night window, `nice`d. Daytime: light analysis and reporting.
- Lists shown to the human: five items at a time, ranked.
- The GitHub remote is public: never push, the owner does. The night host (`ssh $NIGHT_HOST`, set in `.env`) gets code
  with `scripts/night-sync.sh push` and results come back with `scripts/night-sync.sh pull` (into `runs/night/`).
- `docs/recipe.md` is a deliverable: after every night's results update it, keep the evidence tags honest (`dev`, `locked`, `untested`), and put its final form in the final report.
- Stop rule (see Amendments in docs/success-criteria.md): done after the locked-seed verdict is written up AND three consecutive night cycles give no new finding. Until then, keep going; log each night as `finding` or `no finding` in the journal.
