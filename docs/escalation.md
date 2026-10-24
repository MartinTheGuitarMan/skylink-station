# Escalation: the edge asks the big brain

Design, 2026-10-24 (owner: "the smaller model has a mandate to escalate questions to the big brain when connections allow; big brain =
Claude"). Evidence: `reports/escalation-dev-2026-10-24.md` (`dev`). Pre-registration: C5e and its follow-up in the Amendments of
`docs/success-criteria.md`.

## What the eval says, in one paragraph
Claude is a far better triager than any model the edge can run (two-class macro-F1 0.935 on 200 blind dev questions, against 0.71 for
the 4B edge model and 0.75-0.76 for 14-20B local models). Asking about *every* alert therefore lifts the edge by +0.23, and the uplink
cost is trivial (about 400 bytes a question, about 156 questions a day). But the edge cannot tell which of its own answers are wrong:
the disagreement triggers escalated 24-38 % of alerts and caught only a third of the errors, so no policy met the pre-registered bar
(+0.10 at ≤ 50 % escalated). The bigger win came from the other direction: Claude's answers followed five rules, and those rules, sent
down to the edge, score 0.912 on 3079 alerts they were never fitted to (job-T rules: 0.645). **Escalate to learn, not to ask forever.**

## The loop
```
edge: alert -> facts (script) -> rules (sent down) -> provisional label
                                     |  residue only
                                     v
                    question queue (priority, TTL, budget) --link up--> shore inbox
                                                                            |
                                                         Claude answers (schema, checked)
                                                                            |
edge: final label  <--link up-- answers + new rules + worked examples <-----+
```
1. **Decide locally, always.** The edge labels every alert at +2 min with the rules it has, then the small model for what the rules
   leave open. Nothing waits for the shore: safety actions and the forecast loop never block on a question (C5c).
2. **Escalate the residue.** A question goes ashore only for alerts the current rules mark as uncertain (today: wind, and short
   vibration excursions; see the eval) or where the edge voters disagree. The mandate is a budget, not a free-for-all: at most N
   questions a day, oldest dropped first when the queue is full.
3. **Questions ride ahead of the backfill.** At link-up the question queue (a few kB) goes before the replay of outage data.
4. **The shore answers in a schema.** `{q, label, kind, why <= 80 chars, keep_as_example}` with the label limited to the causes the
   station ontology allows for that stream; checked in code like every other model output. A failed check leaves the provisional label.
5. **Answers come back with knowledge.** Each pass, the shore also sends down (a) rules it is confident in, as code or thresholds a
   person approves, and (b) a few reviewed questions as worked examples for the small model. The next day's residue is smaller.
6. **Everything is logged.** Question, provisional label, answer, time to answer, whether the answer changed the label. That log is
   how the trigger and the rules are re-tuned, on fresh cases.

## Where the big brain runs (two modes, both measured)
| mode | how | time to answer (escalated alerts, dev) | cost | fits |
|---|---|---|---|---|
| Daily pass | the edge's questions land in an inbox file in the repo's run folder; the scheduled Claude session (the daily loop) answers them and writes answers plus rule proposals back; the Mini picks them up at the next sync | median 12.8 h, p95 23 h | none extra | review, rules, examples; not live alerts |
| On call | a small service ashore calls the Claude API when a question arrives | median 3 min, p95 42 min (outages) | per call; needs a key | live alerts |

**Built 2026-10-24** (the daily pass): `skylink.agent.inbox`, `scripts/escalate.py`, the nightly step in `scripts/nightly.sh`, `scripts/mini-sync.sh answers`, step 2b of `docs/daily-loop.md`, queue `config/escalation-queue.txt` (dev seeds 11-30, one day a night, 40 questions). A simulated day gives about 200 edge alerts, 90 residue, 40 questions of about 440 bytes.

Start with the daily pass: it needs no new infrastructure or money, and the eval says most of the value is in the rules it sends down,
which do not need to be fast. On call is a later decision for the owner (it costs money).

## Packet sketch
Question (edge to shore, about 400 bytes):
```json
{"q": "s3-wind-418226", "job": "triage", "t": 418226, "stream": "wind", "edge": "real_event",
 "trigger": "residue:wind", "facts": {"onset_z": 9.7, "peak_z_next_2min": 16.3, "flat_fraction_next_2min": 0.55, "...": "..."}}
```
Answer (shore to edge):
```json
{"q": "s3-wind-418226", "label": "sensor_fault", "kind": "stuck", "why": "flat half the time after a jump; wind never repeats",
 "keep_as_example": true}
```

## Open (next experiments, pre-register each first)
1. A residue trigger (escalate wind and short vibration excursions only) with the distilled rules as the edge, on fresh cases.
2. Local models given the same station physics text Claude had (is the gap the model or the knowledge?).
3. The teacher loop: does the 4B edge model improve with Claude's reviewed answers as its worked examples?
4. The same with hindsight (job R windows), where the edge's own rules already reach 0.94.
