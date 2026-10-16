#!/usr/bin/env python3
"""Generate grafana/dashboards/skylink.json (dashboards as code). Event time starts 2026-01-01."""
import json
from pathlib import Path

DS = {"type": "influxdb", "uid": "influx"}
RANGE = "range(start: v.timeRangeStart, stop: v.timeRangeStop)"
WIN = "if int(v: v.windowPeriod) > 1000000000 then v.windowPeriod else 1s"
_id = [0]


def panel(title, kind, queries, x, y, w, h, unit=None, desc="", extra=None, overrides=None):
    _id[0] += 1
    p = {"id": _id[0], "title": title, "type": kind, "datasource": DS, "description": desc,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": [{"refId": chr(65 + i), "datasource": DS, "query": q} for i, q in enumerate(queries)],
         "fieldConfig": {"defaults": {"unit": unit or "short"}, "overrides": overrides or []},
         "options": {}}
    if extra:
        for k, v in extra.items():
            p[k] = v
    return p


actual = f'''from(bucket: "raw") |> {RANGE}
  |> filter(fn: (r) => r._measurement == "sensor" and r.run == "${{run}}" and r.stream == "${{stream}}" and r._field == "value")
  |> aggregateWindow(every: {WIN}, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({{_time: r._time, _value: r._value, model: "actual"}}))
  |> group(columns: ["model"])'''
fcst = f'''from(bucket: "forecasts") |> {RANGE}
  |> filter(fn: (r) => r._measurement == "forecast" and r.run == "${{run}}" and r.stream == "${{stream}}" and (not exists r.rt or r.rt == "1") and r.horizon == "${{horizon}}" and r.arm =~ /^${{arm:regex}}$/ and r.model =~ /^${{model:regex}}$/)
  |> aggregateWindow(every: {WIN}, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({{_time: r._time, _value: r._value, model: r.arm + "/" + r.model}}))
  |> group(columns: ["model"])'''
mae = f'''from(bucket: "forecasts") |> {RANGE}
  |> filter(fn: (r) => r._measurement == "error" and r._field == "abs_err" and r.run == "${{run}}" and r.stream == "${{stream}}" and (not exists r.rt or r.rt == "1") and r.horizon == "${{horizon}}" and r.arm =~ /^${{arm:regex}}$/ and r.model =~ /^${{model:regex}}$/)
  |> aggregateWindow(every: if int(v: v.windowPeriod) > 60000000000 then v.windowPeriod else 1m, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({{_time: r._time, _value: r._value, model: r.arm + "/" + r.model}}))
  |> group(columns: ["model"])'''
mae_bar = f'''from(bucket: "forecasts") |> {RANGE}
  |> filter(fn: (r) => r._measurement == "error" and r._field == "abs_err" and r.run == "${{run}}" and r.stream == "${{stream}}" and r.arm =~ /^${{arm:regex}}$/)
  |> group(columns: ["model", "horizon"]) |> mean()
  |> map(fn: (r) => ({{_time: r._stop, _value: r._value, name: r.model + " h=" + r.horizon + "s"}}))
  |> group(columns: ["name"])'''
link = f'''from(bucket: "raw") |> {RANGE}
  |> filter(fn: (r) => r._measurement == "skylink" and r.run == "${{run}}" and r._field == "up")
  |> keep(columns: ["_time", "_value"]) |> map(fn: (r) => ({{r with _value: r._value, link: "Skylink"}})) |> group(columns: ["link"])'''
truth = f'''from(bucket: "raw") |> {RANGE}
  |> filter(fn: (r) => r._measurement == "truth_event" and r.run == "${{run}}" and (r.stream == "${{stream}}") and (r.kind != "spike" and r.kind != "burst" and r.kind != "gust" and r.kind != "cloud"))
  |> pivot(rowKey: ["_time", "stream", "kind"], columnKey: ["_field"], valueColumn: "_value")
  |> keep(columns: ["_time", "stream", "kind", "mag", "t1_us", "id"]) |> group()'''
agent = '''from(bucket: "agent") |> range(start: 2000-01-01T00:00:00Z)
  |> filter(fn: (r) => r._measurement == "decision" and r.run == "${run}")
  |> pivot(rowKey: ["_time", "stream", "kind"], columnKey: ["_field"], valueColumn: "_value") |> group()'''
res = f'''from(bucket: "metrics") |> {RANGE}
  |> filter(fn: (r) => r._measurement == "resource" and r.run == "${{run}}" and (r._field == "cpu_pct" or r._field == "rss_mb" or r._field == "step_ms_p99"))
  |> aggregateWindow(every: if int(v: v.windowPeriod) > 10000000000 then v.windowPeriod else 10s, fn: mean, createEmpty: false)
  |> group(columns: ["_field", "arm"])'''
late = f'''from(bucket: "metrics") |> {RANGE}
  |> filter(fn: (r) => r._measurement == "base_arrival" and r.run == "${{run}}" and (r._field == "late_n" or r._field == "max_lag_s"))
  |> group(columns: ["_field"])'''
state_ex = {"options": {"showValue": "never", "mergeValues": True},
            "fieldConfig": {"defaults": {"mappings": [{"type": "value", "options": {
                "0": {"text": "OUTAGE", "color": "red", "index": 0}, "1": {"text": "up", "color": "green", "index": 1}}}],
                "custom": {"fillOpacity": 70}, "unit": "short"}, "overrides": []}}


def var(name, label, q, multi=False, include_all=False, default=None):
    v = {"name": name, "label": label, "type": "query", "datasource": DS, "query": q, "refresh": 2,
         "multi": multi, "includeAll": include_all, "sort": 3, "hide": 0}
    if default:
        v["current"] = {"text": default, "value": default}
    return v


def tags(bucket, tag, meas=None):
    flt = f', predicate: (r) => r._measurement == "{meas}"' if meas else ""
    return (f'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "{bucket}", tag: "{tag}", '
            f'start: 2000-01-01T00:00:00Z{flt})')


dash = {
    "uid": "skylink-main", "title": "Skylink Station", "schemaVersion": 39, "version": 1, "editable": False,
    "timezone": "utc", "refresh": "10s", "time": {"from": "2026-01-01T00:00:00.000Z", "to": "2026-01-01T01:00:00.000Z"},
    "tags": ["skylink"], "annotations": {"list": []},
    "templating": {"list": [
        var("run", "Run", tags("raw", "run", "sensor")),
        var("stream", "Stream", tags("raw", "stream", "sensor")),
        var("arm", "Arm", tags("forecasts", "arm"), multi=True, include_all=True),
        var("model", "Model", tags("forecasts", "model"), multi=True, include_all=True),
        var("horizon", "Horizon (s)", tags("forecasts", "horizon", "forecast")),
    ]},
    "panels": [
        panel("Data vs forecast", "timeseries", [actual, fcst], 0, 0, 16, 9,
              desc="1 s mean of the raw stream against each model's forecast for the same instant, made `horizon` seconds earlier. Raw stream shows what crossed Skylink (gaps during outages, then backfill)."),
        panel("Skylink link state", "state-timeline", [link], 16, 0, 8, 4, extra=state_ex,
              desc="Seeded Markov on/off chain, stepped in event time."),
        panel("Ground-truth events (this stream)", "table", [truth], 16, 4, 8, 5,
              desc="Sensor faults and process events injected by the simulator. t1_us is the end of the event."),
        panel("Rolling error (MAE) by model", "timeseries", [mae], 0, 9, 12, 8, unit="short",
              desc="Mean absolute error per window, prequential. Lower is better; persistence is the bar to beat."),
        panel("MAE over the selected range, all horizons", "bargauge", [mae_bar], 12, 9, 12, 8,
              extra={"options": {"orientation": "horizontal", "displayMode": "gradient"}}),
        panel("Late / backfilled data reaching the base", "timeseries", [late], 0, 17, 8, 7,
              desc="Points that crossed Skylink late (more than 2 s behind the newest) and how far behind (s)."),
        panel("River service resource use", "timeseries", [res], 8, 17, 8, 7,
              desc="CPU percent of one core, RSS MB and p99 per-step latency (ms) of the river container's process."),
        panel("Agent decisions", "table", [agent], 16, 17, 8, 7,
              desc="Agent proposals and guardrail verdicts (empty until the agent layer is on)."),
    ],
}
out = Path(__file__).resolve().parent.parent / "grafana/dashboards/skylink.json"
out.write_text(json.dumps(dash, indent=1) + "\n")
print("wrote", out)
