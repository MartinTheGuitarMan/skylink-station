"""Minimal InfluxDB 2.x line-protocol writer. No client library: one HTTP call per flush."""
from __future__ import annotations

import os

import httpx


def esc_tag(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")


class Influx:
    def __init__(self, url: str | None = None, token: str | None = None, org: str | None = None):
        self.url = (url or os.environ.get("INFLUX_URL", "http://localhost:8086")).rstrip("/")
        self.org = org or os.environ.get("INFLUX_ORG", "skylink")
        token = token or os.environ.get("INFLUX_TOKEN", "")
        self.client = httpx.Client(timeout=30, headers={"Authorization": f"Token {token}"})

    def write(self, bucket: str, lines: list[str], precision: str = "us") -> None:
        if not lines:
            return
        r = self.client.post(
            f"{self.url}/api/v2/write",
            params={"org": self.org, "bucket": bucket, "precision": precision},
            content="\n".join(lines).encode(),
        )
        r.raise_for_status()

    def query(self, flux: str) -> str:
        r = self.client.post(
            f"{self.url}/api/v2/query",
            params={"org": self.org},
            json={"query": flux, "type": "flux"},
            headers={"Accept": "application/csv"},
        )
        r.raise_for_status()
        return r.text
