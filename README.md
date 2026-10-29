# Skylink Station

**A remote weather research station, a satellite link that drops out for hours at a time, and an AI that runs the whole experiment
by itself: it plans each night's runs, reads the results each morning, writes its own lab journal, and is not allowed to move the
goalposts.**

The station is simulated, so every surprise is known in advance and every answer can be checked. The question it asks is real:
*at the edge, with a weak uplink, where do online learning and language models actually earn their keep, and where are a few
rules just as good?*

## The station

**Skylink Station is a fictional, unmanned weather research station on a high mountain ridge.** A crew comes up in summer. From
autumn to spring nobody is there: the station watches the weather alone, with four weather instruments and its main research tool,
a scanning weather radar on the mast. Its only line to the world is **Skylink**, a satellite link that holds for a few hours and then
drops out for minutes to hours. When something breaks in January, help is months away, so the station has to notice for itself,
decide for itself, and tell the shore what matters in a few hundred bytes when the link allows.

The simulation starts on 1 January: a clear winter day high in the mountains, about -8 °C, with up to 700 W/m² of sun at noon.
Its crew is software, with a director ashore (see [Loop engineering](#loop-engineering)): River models are the station's reflexes,
small local models are the night shift, Claude is the chief engineer who visits by satellite once a day.

### The instruments (every signal the simulator makes)

| stream | rate | the instrument | what it measures, in numbers |
|---|---|---|---|
| temperature | 10 Hz | air thermometer on the mast | mean -8 °C; daily swing ±6 °C, warmest at 15:00; weather wander over about 3 days (sd 0.8 °C) and 30 s (sd 0.15 °C); sensor noise 0.05 °C |
| pressure | 10 Hz | barometer in the hut | 1013 hPa; weather wander over 36 h (sd 3 hPa); the twice-daily atmospheric tide (±0.25 hPa); **fronts** every 2 days on average, moving it by about 6 hPa (sd) over 3-8 h, with up to 5x the usual jitter as they pass |
| wind | 20 Hz | anemometer and vane, speed and direction | median about 6 m/s, changing over hours and seconds; **gusts** every 10 min on average, 3-15 s long, 1.5-2.6x the wind; from the west (270°), swinging ±40° over hours and ±10° over seconds |
| solar | 5 Hz | pyranometer | clear sky up to 700 W/m² at noon, zero at night; **cloud** changes every 8 min on average to clear (40 %), thin (30-80 % of clear sky, 35 %) or thick (5-30 %, 25 %), with 4 s edges and flicker under cloud; noise 1.5 W/m² |
| vibration | 100 Hz | accelerometer on the radar pedestal | broadband noise around the mast's 2 Hz sway; the antenna turning at 12 rpm (a 0.2 Hz line); **drive kicks** every 3 min on average when the scan pattern changes, 8-15 Hz, dying out over 2-8 s; reported as 1 s RMS |

The station turns all of this, about 145 samples a second or 12.5 million a day, into 1 s values at the edge (mean, RMS for
vibration) and forecasts each stream at its own horizons, from 1 s (wind, vibration) to 1 h (temperature, pressure).

### What goes wrong

The world changes (seasonal shifts on temperature and sun, about one every 4 days: the daily curve 35 % weaker to 50 % stronger,
or shifted by up to 3 h, over about 3 h; fronts; gusts; clouds; drive kicks), and the sensors break. Every stream gets, per day on
average:

| sensor fault | per day | what it looks like |
|---|---|---|
| spike | 4 | 1-3 raw samples off by 5-15 units |
| dropout | 1.5 | no data for 10 s to 5 min |
| stuck | 0.8 | the value freezes for 1-20 min |
| drift | 0.5 | a ramp of 1-3 units over 2-6 h, then back |
| step | 0.5 | an offset of 1-2.5 units for 6-48 h |

One unit is 2 °C, 3 hPa, 3 m/s, 3 µm/s of vibration or 80 W/m². In the wear scenario the radar's **slewing bearing** wears out too:
starting 3-7 days in, over 4-14 days, the pedestal vibrates 1.5-3x harder and stays that way.

### The link

Skylink is up for 4 h on average and down for 40 min on average (random, minutes to hours). During an outage the station buffers
up to 3 million points and drops the oldest beyond that, logging every dropped point. When the link returns, the backlog goes ashore
in chunks of 5,000 points, shuffled within groups of 8 and rate-limited, mixed with live data: late and out of order. The station's
own instruments never cross the link: the edge always sees its sensors, the shore sees only what Skylink delivered.

Every event above (each front, gust, frozen sensor, outage and worn bearing) is drawn up front from a seed and logged as ground
truth, so the same seed always gives the same winter, and every alert and forecast error can be traced to its cause.

## Loop engineering

Prompt engineering tunes one call to a model. **Loop engineering** designs the cycle an AI agent runs again and again: what it
observes, what it may do, how its work is checked by something other than its own word, what it remembers, when a human must say
yes, and when it stops. This repo is a loop-engineering experiment. The prompts are short; the engineering is in the loops.
It is organised like a small company:

| role | who | does | never does |
|---|---|---|---|
| **CEO / CTO** (station director) | the human owner | sets direction ("test whether wear gets adapted away"), approves anything outward-facing or costly, pushes to GitHub | the daily work |
| **Lead engineer and project manager** (chief engineer ashore) | Claude | turns an idea into a pre-registered test, writes the code and tests, queues the nights, reads the results, keeps the journal and the recipe honest, answers the edge's questions, reports in a few lines | push, spend money, touch locked seeds, move a threshold after the fact |
| **Workers** (the night shift) | minions: small local models through [mcp-minions](https://github.com/MartinTheGuitarMan/mcp-minions) | one narrow job each (triage an alert, extract fields, write a short note), structured output, checked in code | decide alone: the rules go first, guardrails decide, numbers come from scripts |

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
| act | nights (23:00-06:00) on a night host: simulations at 60x, model benches, the escalation inbox |
| observe | a daily pass on a day host pulls the night's results ([`docs/daily-loop.md`](docs/daily-loop.md)) |
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
- `config/`: scenarios (`scenario-*.toml`), the edge service config (`edge.toml`), the night queues and `default-queue.txt`, the night fallback (`docs/night-fallback.md`).
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

The Docker VM used in development has 4 CPUs and 6 GB.
