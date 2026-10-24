# Escalation to Claude, dev cases (C5e), 2026-10-24

200 edge alerts (100 real event, 100 sensor fault) from the 300 balanced job-T dev cases (seeds 1-3, seed 7 sample). Two-class
macro-F1, 95% bootstrap CIs over cases. Edge: gemma-4-e4b 3-shot (stored run `air-fs3`); voter Jev 0.8B. Local shores: stored
3-shot runs of gpt-oss-20b and Qwen3-14B. Claude answered all 200 blind (shuffled, renamed Q001-Q200, no labels), in one pass,
before any score; answers fingerprinted (SHA-256 `70db7245...0606`) and kept in `escalation-claude-answers-2026-10-24.json`.
Timing from each seed's link chain; script `scripts/escalation_eval.py`.

## Each answerer alone
| answerer | F1 [95% CI] |
|---|---|
| job-T rules | 0.510 [0.437, 0.579] |
| Jev 0.8B | 0.433 [0.374, 0.500] |
| gemma-4-e4b 3-shot (edge) | 0.707 [0.643, 0.767] |
| gpt-oss-20b 3-shot | 0.750 [0.689, 0.808] |
| Qwen3-14B 3-shot | 0.761 [0.702, 0.817] |
| Claude | **0.935** [0.899, 0.965] |

Claude by seed: 0.937 (s1, 82), 0.926 (s2, 54), 0.931 (s3, 64). Seed 3 was not looked at when the wind threshold Claude used was
noticed (job R tuning, seeds 1-2), and it scores the same. Claude's 13 errors: 12 faults called real (9 on wind), 1 real called fault.

## Policies (final label = shore's answer if escalated, else the edge's)
| policy | shore | F1 | vs edge alone [95% CI] | escalated | questions/day (natural mix) | fixed / broke |
|---|---|---|---|---|---|---|
| P2 escalate all | Claude | 0.935 | +0.228 [0.163, 0.295] | 100 % | 156 | 60 / 5 |
| P2 escalate all | Qwen3-14B | 0.761 | +0.054 [-0.011, 0.117] | 100 % | 156 | 23 / 14 |
| P2 escalate all | gpt-oss-20b | 0.750 | +0.043 [-0.026, 0.113] | 100 % | 156 | 35 / 19 |
| P2 escalate all | oracle | 1.000 | +0.293 | 100 % | 156 | 68 / 0 |
| P3 edge vs rules disagree | Claude | 0.727 | +0.020 [-0.021, 0.057] | 24 % | 28.5 | 10 / 5 |
| P3 edge vs rules disagree | oracle | 0.762 | +0.055 [0.026, 0.088] | 24 % | 28.5 | 11 / 0 |
| P4 edge voters disagree | Claude | 0.781 | +0.074 [0.022, 0.126] | 36 % | 42.8 | 19 / 5 |
| P4 edge voters disagree | Qwen3-14B | 0.761 | +0.054 [0.008, 0.102] | 36 % | 42.8 | 15 / 5 |
| P4 edge voters disagree | oracle | 0.815 | +0.108 [0.066, 0.155] | 36 % | 42.8 | 20 / 0 |
| P5 P3 or P4 | Claude | 0.781 | +0.074 [0.022, 0.126] | 38 % | 43.7 | 19 / 5 |

Questions average 397 bytes (P2: 156 a day is about 62 kB a day). Time from alert to answer back at the edge, escalated alerts:
on call median 3.0 min, p95 42 min (P2; the tail is outages), 3.0 / 3.0 min for P3-P5; daily pass median 12.8 h, p95 23 h.

## Verdict wording (pre-registered)
**"Escalation pays": not shown.** No policy reaches +0.10 with the CI above 0 at ≤ 50 % escalated with Claude. Best within the cap:
P4/P5 +0.074 [0.022, 0.126] at 36-38 %. Escalating everything to Claude gives +0.228 [0.163, 0.295], but at 100 %. The limit is the
trigger, not the shore: with a perfect shore P3 buys only +0.055 and P4 +0.108, because the edge's disagreements cover a third of
its errors. **"Big brain needed": not applicable** (no policy passed with Claude); descriptively, Claude on all alerts is +0.17 to +0.19
above either local stand-in.

## H11
Partly wrong. P3 escalated 24 % (guessed 30-45 %) and recovered little of the oracle gain; P4 did better than P3 (guessed the
opposite). Claude reached 0.935, not about 0.85, and is well above gpt-oss-20b (0.750), not a little. Staleness as guessed:
minutes on call except after outages, 12-24 h for the daily pass.

## Follow-up: rules sent down (pre-registered after the scores above, before this run)
Claude's 200 answers follow five rules exactly (200/200 agreement once written as code, `escalation.distilled_rules`). On the
3079 other edge alerts of seeds 1-3 (natural mix, 2231 real, 848 fault), never used to write them: **0.912 [0.901, 0.923]**
(s1 0.899, s2 0.921, s3 0.917), against 0.645 [0.623, 0.665] for the job-T rules. Prediction (≥ 0.85) holds. What is left: wind
(fault recall 0.73, real recall 0.69) and vibration faults (recall 0.73); temp, pressure and solar are near perfect. That residue is
what a future trigger should escalate.

Caveats: dev only; one sample of 200; Claude had the station physics in `docs/slm-backend.md`, the local models only three worked
examples, so the gap mixes model and knowledge; the rule thresholds were Claude's reading of the physics plus a wind threshold seen on
seeds 1-2.
