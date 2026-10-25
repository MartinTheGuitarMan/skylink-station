# How to structure the backend so small language models are effective and accurate

Design note, 2026-10-24 (owner's question: "how to structure the backend at Skylink so SLMs are effective and accurate? Ontologies?").
A proposal, not a result. Evidence tags as in `docs/recipe.md`; every claim below that has a number comes from this repo.

## Short answer
Make the model's job small and closed: scripts turn signals into **named facts with ids**, a small **station ontology** says which
causes are even possible and what each one looks like, rules decide what they can, and the model only picks from an
ontology-generated menu, cites fact ids, and writes words that code checks. The ontology is worth having, as one JSON file that
everything is generated from, not as a triple store or a reasoner at the edge.

## What this experiment already shows (all `dev`)
1. **Raw numbers are the wrong interface.** Zero-shot, no local model beat a three-line rule on alert triage (best 0.60 vs 0.63
   macro-F1); 1B models answer one class for everything. Picking a forecast model (job P), qwen3:8b was a slower copy of a
   trailing-MAE rule.
2. **Facts beat models.** Job R: five hindsight numbers made by a script, read by four rules, reach 0.943 macro-F1 on seed 3, against
   0.68 for the rules that see only the first two minutes. No model was involved.
3. **Domain constraints are free accuracy.** On seeds 1-2, temperature and pressure never have a real *fast* event (their processes,
   seasonal shift and fronts, take hours); every jump there is a fault or a replay artefact. The two-minute rules called 112 of 257
   such alerts "real event", all wrong. A constraint "stream → possible kinds" removes that error class before any model runs.
4. **Examples and definitions matter more than size.** Three worked examples per class took gpt-oss-20b from 0.23 to 0.82 and
   Qwen3-14B from 0.68 to 0.80; a 12B model was below a 4B model zero-shot. (Outside this repo, sharper class descriptions in an
   ontology lifted a small extractor's class accuracy from 50 to 71 %, same model.)
5. **Constrained decoding solves validity, not truth.** Schema-constrained output was valid 100 % for every model; honesty prompts
   still showed nearly every tested model inventing history when told a service was down. So: validity from the schema, truth from facts
   and checks in code.

## The layers
| layer | what it does | who | at the edge? |
|---|---|---|---|
| 1. Signals | streams, forecasts, errors, link state (Influx) | River, simulator, Node-RED | yes |
| 2. Facts | detectors and hindsight features turn signals into typed facts with ids: `Alert A7`, `Outage O2`, `Excursion(width=1 s)`, `InvisibleInTrueOrder(A7)` | scripts | yes |
| 3. Knowledge | the station ontology: streams, quantities, units, event kinds, which kinds each stream can have, each kind's signature (duration, magnitude limits, shape), cause classes, physical limits | one JSON file, versioned in git | read-only copy |
| 4. Decisions | rules generated from or checked against the ontology decide; a model is asked only about the residue (rules near a threshold, rules disagree, or a kind the rules cannot see) | rules first, SLM second | yes |
| 5. Checks | schema (constrained decoding), ontology constraints (allowed kind for this stream, cited ids exist, physics limits), numbers traceable to facts; a failed check falls back to the rules' answer | code | yes |
| 6. Words | the model verbalises validated facts (uplink summary, operator note); the words are checked like any output | SLM | yes |
| 7. Learning | disagreements and overrides are logged, reviewed by a person, and become worked examples or new rules; only a person changes the ontology | person + scripts | ashore |

The model never sees a raw series, never computes a number, and never chooses from an open vocabulary.

## What the ontology is for, concretely
- **Closed vocabularies → schemas.** Enums for stream, kind and cause in every JSON schema are generated from the ontology, so
  constrained decoding can only emit terms that exist.
- **Per-alert menus.** The schema for one alert lists only the kinds its stream can have (temp: stuck, spike, drift, step, dropout,
  seasonal, artefact), which removes impossible answers (finding 3) and shrinks the choice a small model has to make.
- **Kind signatures → rules and prompts.** "Gust: 3-15 s, at most about 2.6x the mean" lives once in the ontology; R1 reads its
  limit from there and the prompt's definitions are rendered from the same text, so rules and prompts cannot drift apart.
- **Fine-grained kinds, coarse verdicts.** The model names a kind (spike, stuck, cloud edge, ...) whose definition is crisp; code maps
  kind → cause class. Easier for a small model than an abstract three-way label.
- **Evidence and provenance.** Every claim in a report must cite fact ids (`A7`, `O2`); the ontology defines which relations are
  allowed (`Artefact` must lie inside a `Replay` after an `Outage`; `SensorFault` must name a sensor on that stream), and code
  checks them, like SHACL shapes but in plain Python.
- **Governance.** Facts emerge from runs; the ontology governs; a fact that does not fit (a new kind of alert) is flagged for a
  person instead of being forced into a class.

Not worth it here: OWL reasoning, a triple store, SPARQL at the edge, or a knowledge-graph RAG. The station has about ten kinds and
five streams; a JSON file with a JSON-LD export (for sharing) covers it, and it fits in a prompt.

## Sketch of the file (`config/station-ontology.json`, not yet created)
```json
{
  "version": "0.1",
  "causes": {"real_event": "the world changed", "sensor_fault": "the sensor misreports", "backfill_artefact": "late data replayed out of order"},
  "kinds": {
    "spike":  {"cause": "sensor_fault", "duration_s": [0.1, 0.3], "definition": "one-second excursion that returns at once"},
    "stuck":  {"cause": "sensor_fault", "duration_s": [60, 1200], "definition": "exactly the same value for a minute or more"},
    "gust":   {"cause": "real_event", "duration_s": [3, 15], "max_ratio_to_mean": 2.6, "definition": "short rise in wind speed"},
    "front":  {"cause": "real_event", "duration_s": [21600, 57600], "definition": "slow pressure change over hours"},
    "artefact": {"cause": "backfill_artefact", "requires": "inside_replay", "definition": "alert not visible in true time order"}
  },
  "streams": {
    "temp":     {"unit": "degC", "kinds": ["spike", "stuck", "drift", "step", "dropout", "seasonal", "artefact"]},
    "pressure": {"unit": "hPa",  "kinds": ["spike", "stuck", "drift", "step", "dropout", "front", "artefact"]},
    "wind":     {"unit": "m/s",  "kinds": ["spike", "stuck", "drift", "step", "dropout", "gust", "artefact"]}
  }
}
```
The simulator's event plan (`sim/events.py`) is the source for the first version; in a real station the same file is written from
the sensor datasheets and the site's physics, and reviewed by a person.

## Experiments that would test this (ranked; each pre-registered before it runs, dev seeds only)
1. **Ontology menus.** R2 and R3 with per-stream enums vs the three global labels. Prediction: the temp/pressure "real event"
   errors vanish and small models (≤ 4B) gain most.
2. **Facts as named predicates.** The same hindsight numbers rendered as predicates from the ontology ("lasted 1 s, shorter than any
   gust", "not visible in true time order") vs raw numbers. Tests whether the model reads facts better than figures.
3. **Kinds, then causes.** The model names a fine kind from the stream's menu; code maps it to a cause. Against direct three-way labels.
4. **Residue routing with abstain.** The model sees only alerts where R1 sits near a threshold or two rules conflict, may answer
   "unsure", and its answer replaces the rule's only when a check passes. Measures lift where lift is still possible (R1 is at 0.94).
5. **Retrieved examples.** Worked examples chosen by same stream and kind from reviewed cases vs random examples.

Each is cheap: the facts and checks exist (`skylink.agent.review`), and the runs are minutes per model on the day host.

## What not to do
No thinking mode for these jobs (108 s vs 2 s per case, not better). No number written by a model. No open vocabulary. No model in
front of a decision a rule can make. No fine-tuning before experiments 1-5 have said where the remaining errors are.
