# Backlog (ranked; shown five at a time)

Top five:
1. **Base arm and backfill strategies**: arrival order vs event-time order vs ignore-late (RQ1); prerequisite for alert triage.
2. **Drift mechanism that fits increment models**: ADWIN on volatility-normalised error, or exponentially forgetting least squares (RQ2). Error-stream ADWIN with reset or challenger was harmful (journal, iteration 1).
3. **Agent layer** per `docs/agent.md`: mcp-minions client, guardrails, call log, four local models (RQ3).
4. **Solar models**: all lose to persistence; try the ratio to a clear-sky shape, night/day regimes.
5. **Locked-seed verdict runs** (seeds 101-105, 7 days, all streams) once 1-4 are in; needs the night window and the Mini.

Next:
6. ARF regressor on a dedicated heavy config, to measure the cost/benefit break-even (RQ5).
7. Score script charts (weekly report): skill vs horizon per stream, recovery curves after events.
8. Downsampling task in InfluxDB so Grafana can show multi-day ranges.
9. Persist the Node-RED buffer (file context) so a restart does not void a run.
10. Move the stack to the Mac Mini (needs the human; the Air is the dev host for now).
