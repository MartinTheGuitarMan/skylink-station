"""Cold storage export of one run's raw sensor points (docs/daily-loop.md, retention by run).

InfluxDB (bucket `raw`, measurement `sensor`) -> `<cold>/skylink/<run>/`:
  <stream>.parquet   zstd Parquet, columns `time_us` (int64, microseconds since epoch) + one float64 column per field
  manifest.json      per-stream point counts, SHA-256, time span; the run's `emitted` counts from summary.json
  SHA256SUMS         `sha256sum -c` format, covers the Parquet files and manifest.json

The query is streamed in one-hour windows of event time and written row group by row group, so memory stays flat
whatever the run size. The export is built in a hidden `.partial-*` directory next to the target, verified there
(files re-read, counts compared with summary.json, checksums), and only then renamed. A directory without the
`.partial` prefix is therefore a finished, verified export; a killed export leaves only a partial directory.

    python -m skylink.coldexport export <run> [--allow-locked] [--cold /Volumes/Cold] [--runs-dir runs]
    python -m skylink.coldexport verify <run> [--cold ...] [--runs-dir ...]    (offline; exit 0 only if verified)
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_COLD = "/Volumes/Cold"
SUBDIR = "skylink"
WINDOW_S = 3600
FORMAT = "skylink-cold-v1"
MANIFEST = "manifest.json"
SUMS = "SHA256SUMS"


class ExportError(Exception):
    pass


@dataclass
class Chunk:
    """Points of one stream, ordered by time. columns: field name -> values, same length as times_us."""
    times_us: list[int]
    columns: dict[str, list[float]]


class Source(Protocol):
    def streams(self, run: str) -> list[str]: ...
    def span_us(self, run: str, stream: str) -> tuple[int, int] | None: ...  # first, last point time; None if no points
    def chunks(self, run: str, stream: str, start_us: int, stop_us: int) -> Iterator[Chunk]: ...  # [start, stop)


# ---- checks before any work ------------------------------------------------------------------------------------------

def cold_root(cold: str | Path, require_mount: bool = True) -> Path:
    p = Path(cold)
    if require_mount and not os.path.ismount(p):
        raise ExportError(f"cold volume not mounted at {p}")
    if not p.is_dir():
        raise ExportError(f"cold volume path {p} is not a directory")
    return p


def load_summary(runs_dir: Path, run: str) -> dict:
    f = Path(runs_dir) / run / "summary.json"
    if not f.is_file():
        raise ExportError(f"no summary.json for {run} at {f}")
    return json.loads(f.read_text())


def expected_counts(summary: dict) -> dict[str, int]:
    """Raw points that must be in the store: emitted minus logged overflow drops (C8)."""
    drop = summary.get("overflow_dropped", {}) or {}
    return {s: int(n) - int(drop.get(s, 0)) for s, n in (summary.get("emitted") or {}).items()}


def check_exportable(run: str, summary: dict, allow_locked: bool) -> None:
    if not run or "/" in run or run.startswith("."):
        raise ExportError(f"bad run id {run!r}")
    if run.startswith("locked") and not allow_locked:
        raise ExportError(f"{run} is a locked run: needs --allow-locked (after the locked verdict is written)")
    if summary.get("finished") is not True:
        raise ExportError(f"{run} is not finished (summary.json finished != true)")
    if not summary.get("emitted"):
        raise ExportError(f"{run}: summary.json has no emitted counts")


# ---- helpers ---------------------------------------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _fsync_dir(d: Path) -> None:
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _windows(first_us: int, last_us: int) -> Iterator[tuple[int, int]]:
    w = WINDOW_S * 1_000_000
    t = first_us - first_us % w
    while t <= last_us:
        yield t, t + w
        t += w


def _schema(fields: list[str]) -> pa.Schema:
    return pa.schema([("time_us", pa.int64())] + [(f, pa.float64()) for f in fields])


# ---- export ----------------------------------------------------------------------------------------------------------

def _write_stream(src: Source, run: str, stream: str, path: Path) -> dict:
    span = src.span_us(run, stream)
    if span is None:
        return {"file": path.name, "points": 0, "fields": [], "first_us": None, "last_us": None}
    n, fields, writer = 0, None, None
    first = last = None
    try:
        for a, b in _windows(*span):
            for ch in src.chunks(run, stream, a, b):
                if not ch.times_us:
                    continue
                if fields is None:
                    fields = sorted(ch.columns)
                    writer = pq.ParquetWriter(path, _schema(fields), compression="zstd", compression_level=6)
                if sorted(ch.columns) != fields:
                    raise ExportError(f"{stream}: field set changed inside the run ({sorted(ch.columns)} vs {fields})")
                if any(len(v) != len(ch.times_us) for v in ch.columns.values()):
                    raise ExportError(f"{stream}: column lengths differ")
                writer.write_table(pa.table({"time_us": pa.array(ch.times_us, pa.int64()),
                                             **{f: pa.array(ch.columns[f], pa.float64()) for f in fields}},
                                            schema=_schema(fields)))
                n += len(ch.times_us)
                first = ch.times_us[0] if first is None else min(first, ch.times_us[0])
                last = ch.times_us[-1] if last is None else max(last, ch.times_us[-1])
    finally:
        if writer is not None:
            writer.close()
    return {"file": path.name, "points": n, "fields": fields or [], "first_us": first, "last_us": last}


def verify_dir(d: Path, summary: dict, run: str) -> dict:
    """Re-read everything in `d`. Returns the manifest if it holds, else raises ExportError."""
    mf = d / MANIFEST
    if not mf.is_file() or not (d / SUMS).is_file():
        raise ExportError(f"{d}: manifest or checksum file missing")
    manifest = json.loads(mf.read_text())
    if manifest.get("format") != FORMAT or manifest.get("run") != run:
        raise ExportError(f"{d}: manifest is not a {FORMAT} manifest of {run}")
    # checksums: every line of SHA256SUMS, and every file the manifest names must be listed
    sums = {}
    for line in (d / SUMS).read_text().splitlines():
        if line.strip():
            h, _, name = line.partition("  ")
            sums[name] = h
    want = {s["file"] for s in manifest["streams"].values() if s["file"]} | {MANIFEST}
    if set(sums) != want:
        raise ExportError(f"{d}: SHA256SUMS lists {sorted(sums)}, expected {sorted(want)}")
    for name, h in sums.items():
        if not (d / name).is_file() or sha256_file(d / name) != h:
            raise ExportError(f"{d}: checksum mismatch or missing file: {name}")
    # counts: re-read the data (not just the footer) and compare with the manifest and with summary.json
    expected = expected_counts(summary)
    seen = set()
    for stream, m in manifest["streams"].items():
        seen.add(stream)
        n = 0
        if m["points"]:
            pf = pq.ParquetFile(d / m["file"])
            for batch in pf.iter_batches(batch_size=1_000_000, columns=["time_us"]):
                n += batch.num_rows
        if n != m["points"]:
            raise ExportError(f"{stream}: file has {n} points, manifest says {m['points']}")
        if n != expected.get(stream, 0):
            raise ExportError(f"{stream}: {n} points exported, summary.json expects {expected.get(stream, 0)}")
    missing = {s for s, n in expected.items() if n} - seen
    if missing:
        raise ExportError(f"streams missing from the export: {sorted(missing)}")
    return manifest


def export_run(src: Source, run: str, cold: str | Path = DEFAULT_COLD, runs_dir: str | Path = "runs",
               allow_locked: bool = False, require_mount: bool = True) -> dict:
    root = cold_root(cold, require_mount)
    summary = load_summary(Path(runs_dir), run)
    check_exportable(run, summary, allow_locked)
    parent = root / SUBDIR
    final = parent / run
    if final.exists():
        raise ExportError(f"{final} exists: already exported (use `verify`); remove it by hand to redo")
    parent.mkdir(exist_ok=True)
    for stale in parent.glob(f".partial-{run}-*"):   # left by a killed export; never finished, safe to clear
        shutil.rmtree(stale, ignore_errors=True)
    part = parent / f".partial-{run}-{os.getpid()}"
    part.mkdir()
    try:
        streams = sorted(set(src.streams(run)) | set(summary["emitted"]))
        manifest = {"format": FORMAT, "run": run, "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source": "influxdb bucket raw, measurement sensor", "compression": "zstd",
                    "emitted": summary["emitted"], "overflow_dropped": summary.get("overflow_dropped", {}),
                    "summary_hash": summary.get("hash"), "streams": {}}
        for s in streams:
            info = _write_stream(src, run, s, part / f"{s}.parquet")
            if not (part / info["file"]).exists():
                info["sha256"] = None
            else:
                info["sha256"] = sha256_file(part / info["file"])
                info["bytes"] = (part / info["file"]).stat().st_size
            manifest["streams"][s] = info
        # a stream with no points has no file; drop it from the checksum set but keep it in the manifest
        for s, info in manifest["streams"].items():
            if info["points"] == 0:
                info["file"] = None
        (part / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
        names = sorted(i["file"] for i in manifest["streams"].values() if i["file"]) + [MANIFEST]
        (part / SUMS).write_text("".join(f"{sha256_file(part / n)}  {n}\n" for n in names))
        _verify_partial(part, summary, run)
        for f in part.iterdir():
            fd = os.open(f, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        _fsync_dir(part)
        os.rename(part, final)    # the one step that makes it look finished
        _fsync_dir(parent)
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    return manifest


def _verify_partial(part: Path, summary: dict, run: str) -> None:
    verify_dir(part, summary, run)


# ---- InfluxDB source -------------------------------------------------------------------------------------------------

def _parse_time_us(s: str) -> int:
    s = s.strip().rstrip("Z")
    head, _, frac = s.partition(".")
    secs = calendar.timegm(datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").timetuple())
    return secs * 1_000_000 + int((frac + "000000")[:6])


class InfluxSource:
    def __init__(self, influx=None):
        if influx is None:
            from .influx import Influx
            influx = Influx()
        self.ix = influx

    @staticmethod
    def _rows(txt: str):
        from .analysis import _rows
        return _rows(txt)

    def _base(self, run: str, extra: str = "") -> str:
        if not run.replace("-", "").replace("_", "").isalnum():
            raise ExportError(f"bad run id {run!r}")
        return (f'from(bucket: "raw") |> range(start: 0) |> filter(fn: (r) => r._measurement == "sensor" and r.run == "{run}"{extra})')

    def streams(self, run: str) -> list[str]:
        q = self._base(run) + ' |> keep(columns: ["stream"]) |> group() |> distinct(column: "stream")'
        return sorted(r["_value"] for r in self._rows(self.ix.query(q)))

    def span_us(self, run: str, stream: str):
        ext = f' and r.stream == "{stream}"'
        lo = [_parse_time_us(r["_time"]) for r in self._rows(self.ix.query(self._base(run, ext) + " |> first()"))]
        hi = [_parse_time_us(r["_time"]) for r in self._rows(self.ix.query(self._base(run, ext) + " |> last()"))]
        return (min(lo), max(hi)) if lo and hi else None

    def chunks(self, run: str, stream: str, start_us: int, stop_us: int) -> Iterator[Chunk]:
        q = (f'from(bucket: "raw") |> range(start: time(v: {start_us * 1000}), stop: time(v: {stop_us * 1000}))'
             f' |> filter(fn: (r) => r._measurement == "sensor" and r.run == "{run}" and r.stream == "{stream}")'
             ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")')
        times: list[int] = []
        cols: dict[str, list[float]] = {}
        meta = {"", "result", "table", "_start", "_stop", "_time", "_measurement", "run", "stream"}
        for r in self._rows(self.ix.query(q)):
            times.append(_parse_time_us(r["_time"]))
            for k, v in r.items():
                if k not in meta:
                    cols.setdefault(k, []).append(float(v))
        if any(len(v) != len(times) for v in cols.values()):
            raise ExportError(f"{stream}: a point lacks a field in window {start_us}")
        order = sorted(range(len(times)), key=times.__getitem__)
        if times:
            yield Chunk([times[i] for i in order], {k: [v[i] for i in order] for k, v in cols.items()})


# ---- CLI -------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="skylink.coldexport")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("export", "verify"):
        p = sub.add_parser(name)
        p.add_argument("run")
        p.add_argument("--cold", default=os.environ.get("COLD_ROOT", DEFAULT_COLD))
        p.add_argument("--runs-dir", default="runs")
        if name == "export":
            p.add_argument("--allow-locked", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "export":
            m = export_run(InfluxSource(), a.run, a.cold, a.runs_dir, a.allow_locked)
        else:
            root = cold_root(a.cold)
            m = verify_dir(root / SUBDIR / a.run, load_summary(Path(a.runs_dir), a.run), a.run)
    except ExportError as e:
        print(f"cold-export: {e}", file=sys.stderr)
        return 1
    tot = sum(s["points"] for s in m["streams"].values())
    print(f"{a.cmd} ok: {a.run}, {tot} points, " + ", ".join(f"{k} {v['points']}" for k, v in sorted(m["streams"].items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
