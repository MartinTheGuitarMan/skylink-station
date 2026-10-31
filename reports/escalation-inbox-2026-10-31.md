# Escalation inbox, pooled over five nights (C5e, dev seeds 11-15)

Pre-registered read (Amendments, `docs/success-criteria.md`): "residue escalation pays" if the pooled gain is >= +0.02 with the paired
bootstrap CI excluding 0, after at least 5 answered nights. Numbers from the night host's `escalation/summary.json`.

**Result: residue escalation pays on dev.** Pooled over 5 nights and 737 alerts: edge F1 0.866, final F1 0.898, gain +0.032 [0.019, 0.047]; labels fixed 19, broken 0.

| night | seed | alerts | asked | edge F1 | final F1 | answer acc | edge acc on asked | fixed / broke | h to apply |
|---|---|---|---|---|---|---|---|---|---|
| e11 | 11 | 157 | 40 | 0.913 | 0.931 | 0.9 | 0.85 | 2 / 0 | 96.0 |
| e12 | 12 | 188 | 40 | 0.883 | 0.895 | 0.625 | 0.575 | 2 / 0 | 72.0 |
| e13 | 13 | 85 | 30 | 0.802 | 0.864 | 0.733 | 0.567 | 5 / 0 | 48.0 |
| e14 | 14 | 128 | 40 | 0.808 | 0.844 | 0.675 | 0.575 | 4 / 0 | 24.0 |
| e15 | 15 | 179 | 40 | 0.88 | 0.935 | 0.9 | 0.75 | 6 / 0 | 24.0 |

Answers: 190 of 190 asked, accuracy 0.768 on the asked alerts against 0.668 for the edge's own labels on the same alerts.
Hours from question to applied answer: 24.0 to 96.0 (the 48-96 h values are the passes missed on 2026-10-26 to 2026-10-28).

## Read honestly

- The point gain clears +0.02, but the CI's lower end (0.019) sits just under it; the rule asks that the CI excludes 0, so the rule is met, narrowly enough to say so.
- H12 guessed +0.01 to +0.03; the gain is just above that range.
- Dev seeds only, five one-day simulations, one answerer. Answers follow signatures written down over the first nights, so later nights are not independent of earlier ones.
- The pooled line of e11-e14 was seen before e15 was answered (journal, 2026-10-30); e15 followed the earlier signatures unchanged.
- Most asked alerts are alerts the edge already gets right: 19 fixes from 190 answers. The value per question is low; the cost per question is about 400 bytes.
- The locked runs have not tested this.
