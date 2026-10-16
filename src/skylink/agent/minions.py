"""Talk to the mcp-minions MCP server over stdio. One server process (one local model setup) per client.

`call()` never raises for model trouble: it returns a Reply with ok=False and the server's error code
(MINION_DOWN, MINION_SCHEMA, MINION_NO_QUORUM, ...), so the caller can count it. Latency is measured here."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Reply:
    ok: bool
    data: dict | None = None
    error: str | None = None       # stable code when the server gave one
    latency_ms: float = 0.0
    raw: str = ""


class Transport(Protocol):
    name: str
    def call(self, tool: str, args: dict) -> Reply: ...
    def close(self) -> None: ...


@dataclass
class FakeTransport:
    """Scripted transport for tests: `handler(tool, args) -> dict | Exception`."""
    handler: callable
    name: str = "fake"
    calls: list = field(default_factory=list)

    def call(self, tool: str, args: dict) -> Reply:
        self.calls.append((tool, args))
        out = self.handler(tool, args)
        if isinstance(out, Exception):
            m = re.search(r"MINION_[A-Z_]+", str(out))
            return Reply(False, None, m.group(0) if m else "ERROR", 1.0, str(out))
        return Reply(True, out, None, 1.0, json.dumps(out))

    def close(self) -> None:
        pass


class MinionsClient:
    def __init__(self, model: str, backend: str = "lmstudio", minions_dir: str | None = None,
                 roster: str | None = None, timeout_s: int = 120, extra_env: dict | None = None, name: str | None = None):
        self.name = name or model
        self.dir = Path(minions_dir or os.environ.get("MINIONS_DIR", "~/Code/mcp-minions")).expanduser()
        env = {**os.environ, "MINION_BACKEND": backend, "MINION_TIMEOUT": str(timeout_s), **(extra_env or {})}
        if roster:
            env["MINION_ROSTER"] = roster
        else:
            env["MINION_MODEL"] = model
        self._env, self.timeout_s = env, timeout_s
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._ready = threading.Event()
        self._session = None
        self._stop: asyncio.Event | None = None
        fut = asyncio.run_coroutine_threadsafe(self._run(), self._loop)
        self._fut = fut
        if not self._ready.wait(60):
            raise RuntimeError("mcp-minions did not start")

    async def _run(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        params = StdioServerParameters(command="uv", args=["--directory", str(self.dir), "run", "mcp-minions"], env=self._env)
        self._stop = asyncio.Event()
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                self._session = session
                self._ready.set()
                await self._stop.wait()

    def call(self, tool: str, args: dict) -> Reply:
        t0 = time.perf_counter()
        fut = asyncio.run_coroutine_threadsafe(self._session.call_tool(tool, args), self._loop)
        try:
            res = fut.result(self.timeout_s + 30)
        except Exception as e:  # transport failure, not a model failure
            return Reply(False, None, "TRANSPORT", (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {e}")
        ms = (time.perf_counter() - t0) * 1000
        text = "".join(getattr(c, "text", "") for c in res.content)
        if res.isError:
            m = re.search(r"MINION_[A-Z_]+", text)
            return Reply(False, None, m.group(0) if m else "ERROR", ms, text)
        data = getattr(res, "structuredContent", None)
        if not data:
            try:
                data = json.loads(text)
            except ValueError:
                return Reply(False, None, "UNPARSEABLE", ms, text)
        return Reply(True, data, None, ms, text)

    def close(self) -> None:
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(10) if not self._thread.is_alive() else None
