# skylink-station

An experiment run by an autonomous lead engineer. The brief is in `docs/success-criteria.md`
(criteria and hypotheses, pre-registered: amend only in its Amendments section, dated) and
`JOURNAL.md` (what was tried, why, result, decision). `BACKLOG.md` is the ranked list of ideas.

## Rules
- Never touch anything outside this directory without asking (launchd, other repos, system settings).
  Docker is the exception: the stack runs in colima profile `skylink`.
- Small reversible improvements: just do them, commit, log in JOURNAL.md. Larger changes (new
  infra, big model swaps, things that cost money or run outside the night window 23:00-06:00
  Europe/Stockholm): backlog, and ask in the report.
- Change one thing at a time so results stay attributable.
- Locked seeds 101-105 are for the final verdict only. Log every locked-seed run in the journal.
- No secrets in git (`.env` is ignored; only `.env.example` is tracked). Git identity is global; do not change it.
- The agent proposes, guardrails decide. Always keep the River-alone arm on the same replay.
- Heavy runs only in the night window, `nice`d. Daytime: light analysis and reporting.
- Lists shown to the human: five items at a time, ranked.
- Do not push; there is no remote.
