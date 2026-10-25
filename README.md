# Skylink Station

**A remote weather research station, a satellite link that drops out for hours at a time, and an AI that runs the whole experiment
by itself: it plans each night's runs, reads the results each morning, writes its own lab journal, and is not allowed to move the
goalposts.**

The station is simulated, so every surprise is known in advance and every answer can be checked. The question it asks is real:
*at the edge, with a weak uplink, where do online learning and language models actually earn their keep, and where are a few
rules just as good?*

## The station

Picture a mast on a ridge, far from anyone. Five sensors stream at 5-100 Hz:

| stream | what it is | what goes wrong |
|---|---|---|
| temperature | ambient air, daily cycle, seasons shifting | sensors freeze, drift, jump |
| pressure | weather systems, fronts passing over hours | same, plus fronts that look like faults |
| wind | speed and direction, gusts of 3-15 s | gusts that look like spikes |
| solar | sunshine, cloud edges that cut it in seconds | cliffs no model can predict |
| vibration | an accelerometer on the pedestal of the station's **scanning weather radar**: the antenna turns at 12 rpm, the mast sways near 2 Hz, the drive kicks when the scan pattern changes | the radar's bearing slowly wears out |

All of it reaches the shore over **Skylink**, a satellite link that is up for about four hours and then down for minutes to hours.
During an outage the station buffers. When the link returns, the backlog arrives late, in chunks, out of order, mixed with live data.
Nobody is there to look, so the station has to think for itself.

## Loop engineering

Prompt engineering tunes one call to a model. **Loop engineering** designs the cycle an AI agent runs again and again: what it
observes, what it may do, how its work is checked by something other than its own word, what it remembers, when a human must say
yes, and when it stops. This repo is a loop-engineering experiment. The prompts are short; the engineering is in the loops.
It is organised like a small company:

| role | who | does | never does |
|---|---|---|---|
| **CEO / CTO** | the human owner | sets direction ("test whether wear gets adapted away"), approves anything outward-facing or costly, pushes to GitHub | the daily work |
| **Lead engineer and project manager** | Claude | turns an idea into a pre-registered test, writes the code and tests, queues the nights, reads the results, keeps the journal and the recipe honest, answers the edge's questions, reports in a few lines | push, spend money, touch locked seeds, move a threshold after the fact |
| **Workers** | minions: small local models through [mcp-minions](https://github.com/MartinTheGuitarMan/mcp-minions) | one narrow job each (triage an alert, extract fields, write a short note), structured output, checked in code | decide alone: the rules go first, guardrails decide, numbers come from scripts |

The loops below are how that company works without meetings. There are three of them, one inside the other.

**1. The learning loop (seconds, River at the edge).** Every stream is forecast at several horizons by online models from
[River](https://riverml.xyz): predict, score, then learn, every second, never the other way round. The edge sees its own sensors and
never notices the outages; the shore sees only what crossed the link. Both run side by side on the same data, so the cost of the
outage is measured, not guessed.

**2. The edge-to-shore loop (hours, small models up the mast, Claude ashore).** An alert fires: a real gust, a broken sensor, or an
artefact of late data? Rules answer first. A small local model takes the rest through
[mcp-minions](https://github.com/MartinTheGuitarMan/mcp-minions), an MCP server that gives a small model one narrow job, forces
structured output and checks the answer in code. The doubtful cases wait for the link and go ashore, where Claude answers them
blind. What comes back up is not only answers but **rules** distilled from them, so the edge asks less the next night.
*Escalate to learn, not to ask forever.*

**3. The experiment loop (days, Claude as lead engineer, the owner as CEO/CTO).** Claude runs the experiment itself, one cycle a day:

| loop part | how it is built here |
|---|---|
| act | nights (23:00-06:00) on a Mac Mini: simulations at 60x, model benches, the escalation inbox |
| observe | a daily pass on a laptop pulls the night's results ([`docs/daily-loop.md`](docs/daily-loop.md)) |
| verify | numbers come from scripts against the simulator's ground truth, never from a model's say-so; every agent arm has a twin without the agent on the same data |
| guard | the bar is fixed before the code: criteria, thresholds and guesses are pre-registered in [`docs/success-criteria.md`](docs/success-criteria.md) and changed only by dated amendments; locked test seeds stay unread until the verdict; the agent proposes, guardrails decide |
| remember | [`JOURNAL.md`](JOURNAL.md) (what was tried, why, result, decision), [`BACKLOG.md`](BACKLOG.md), git history as the audit trail |
| human in the loop | the CEO/CTO sets direction and holds the keys: pushing to GitHub, new infrastructure, anything that costs money; the report ends with at most one question, with the default that will be taken without an answer |
| stop | done when the locked-seed verdict is written, three passes in a row find nothing new, and every backlog idea is tested or written off |

The loop is built so that the agent cannot fool itself: a wrong guess stays in the record as a wrong guess.

## What it has found so far (development seeds; nothing is a verdict until the locked seeds)

- **Rules plus hindsight beat models at reading alerts.** A handful of numbers computed after the fact label alerts at 0.94
  macro-F1; models reading the same hour alone scored far lower.
- **A big brain ashore is worth it, as a teacher.** Claude triaged blind edge alerts at 0.935 two-class F1 against 0.71 for the 4B
  model the edge can run. Five rules distilled from its answers then scored 0.91 on 3079 alerts they had never seen, running at the
  edge with no link at all.
- **A tiny ontology is worth a model size.** Offering only the causes the station allows on a stream lifted a 4B model to the level
  of a 14B model.
- **Online learning keeps models fresh; it does not make them react to events.** The pre-registered "adaptation helps after regime
  changes" hypothesis was not supported.
- **The edge does not need the uplink to forecast.** The shore loses most real-time forecasts during an outage and recovers more
  slowly afterwards; how backfill is fed matters little if history is keyed by event time.

The running answer is a deliverable of its own: [`docs/recipe.md`](docs/recipe.md), an evidence-tagged recipe for where River and
language models create value at the edge (`dev`, `locked` or `untested` on every line).

**Newest: the worn bearing (C9).** Does an online learner adapt the radar bearing's slow wear away? Pre-registered, then run on
23 development seeds, each against a healthy twin. The online alerts barely noticed: as the bearing wore, they got a third
*quieter*. Comparing the online level with a frozen reference from the first healthy days caught the wear after a median of four
days and kept flagging it. But it missed 5 of 23 runs, each time because a sensor fault had poisoned the reference. Verdict by its
own rule: not shown. Lesson: remember what healthy looked like, and check that memory before trusting it
([`reports/wear-dev-2026-10-25.md`](reports/wear-dev-2026-10-25.md)).

## Under the hood

```
simulator (seeded, replayable, time-compressed)
   └─POST batches─> Node-RED ──edge tap (always)──────────────> river /edge  (River, prequential)
                       │   └─ Skylink gate: seeded Markov on/off in event time
                       │        up:   InfluxDB raw  + river /base
                       │        down: store-and-forward buffer (finite)
                       │        up again: backfill, late and out-of-order, rate limited
                       └────────────────> InfluxDB: raw | forecasts | metrics | agent ──> Grafana
```

Every event (a frozen sensor, a front, a gust, a worn bearing) is drawn up front from the seed and logged as ground truth, so the
same seed always gives the same station, and every alert and error can be traced to its cause.

## Run it
```bash
make up        # .env with random secrets, build flows + dashboard, docker compose up
make smoke     # 1 simulated hour, one stream, frequent outages (SPEED=60 by default)
make test      # unit tests, no docker needed (node is needed for the gate tests)
make down      # stop; `make wipe` deletes the data volumes
```
Grafana http://localhost:3000 (user `admin`, password in `.env`), dashboard "Skylink Station".
Event time starts at 2026-01-01T00:00:00Z, so the dashboard time range is absolute. Pick `run`.
Ports bind to 127.0.0.1; set `BIND=0.0.0.0` in `.env` to open them to the LAN.

## Layout
- `src/skylink/sim/`: stream generators, event plan with ground truth, replayer (`skylink-sim`).
- `src/skylink/edge/`: River service: aggregation to 1 s, prequential engine, models, HTTP front.
- `src/skylink/agent/`: alerts, triage, escalation, review: the language-model jobs and their rules baselines.
- `nodered/functions/*.js` are the source; `scripts/build_flows.py` assembles `nodered/flows.json`.
- `config/`: scenarios (`scenario-*.toml`), the edge service config (`edge.toml`), the night queues.
- `grafana/`: provisioning; the dashboard JSON is generated by `scripts/gen_dashboard.py`.
- `docs/`: success criteria (pre-registered), design, daily loop, agent layer, escalation, recipe.
- `JOURNAL.md`, `BACKLOG.md`, `reports/`: what was tried and found, what is next, the cited reports.

## Resource limits (docker compose)
| service | CPUs | memory |
|---|---|---|
| influxdb | 1.5 | 1 GB |
| nodered | 1.0 | 1 GB |
| river | 1.0 | 768 MB |
| grafana | 0.5 | 768 MB |

The Docker VM on the development laptop (colima profile `skylink`) has 4 CPUs and 6 GB.
