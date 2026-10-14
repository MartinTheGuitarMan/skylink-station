# Backlog (ranked; shown five at a time)

Top five:
1. **River models + drift detectors** (linear on lag features, HoltWinters, SNARIMAX, ARF; ADWIN). Small, in-repo. Next iteration.
2. **Score script**: skill vs persistence per stream and horizon, block-bootstrap CIs, markdown + charts. Needed before any number can be claimed.
3. **All five streams through the stack**, at 1x and 60x: first real CPU/RAM and latency numbers (C2).
4. **Base arm and backfill strategies**: arrival order vs event-time order vs ignore-late, for RQ1.
5. **Nightly runner** (`scripts/nightly.sh`, checkpointed, ends 06:00). Installing the launchd job is outside the repo: needs the human's yes.

Next:
6. Static-model arm for RQ2 (train 2 days, freeze).
7. Agent layer: mcp-minions client, JSON schemas, guardrails, call log (RQ3); try several local models.
8. Downsampling task in InfluxDB so Grafana can show multi-day ranges.
9. Persist the Node-RED buffer (file context) so a restart does not void a run.
10. Move the stack to the Mac Mini (needs the human; the Air is the dev host for now).
