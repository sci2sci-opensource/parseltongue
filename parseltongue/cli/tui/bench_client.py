"""Bench client — async wrapper around the pg-bench Unix socket protocol.

Connects to the running pg-bench daemon and sends commands. All methods
are async so they can be called from Textual workers without blocking
the event loop.
"""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import AsyncIterator

SOCK_PATH = Path.home() / ".parseltongue" / "bench.sock"
MAX_MSG = 16 * 1024 * 1024


class BenchClientError(Exception):
    """Error from the bench server or connection failure."""


class BenchClient:
    """Async client for the pg-bench daemon.

    Usage::

        client = BenchClient()
        await client.ping()
        results = await client.search("raise ValueError")
        view = await client.view("engine.derive")
    """

    def __init__(self, sock_path: Path = SOCK_PATH):
        self._sock_path = sock_path

    async def _send(self, writer: asyncio.StreamWriter, data: dict):
        raw = json.dumps(data).encode()
        writer.write(struct.pack("!I", len(raw)) + raw)
        await writer.drain()

    async def _recv(self, reader: asyncio.StreamReader) -> dict:
        header = await reader.readexactly(4)
        (length,) = struct.unpack("!I", header)
        if length > MAX_MSG:
            raise BenchClientError(f"Message too large: {length}")
        buf = await reader.readexactly(length)
        return json.loads(buf)

    async def _query(self, cmd: dict) -> dict:
        """Send a command and return the response."""
        try:
            reader, writer = await asyncio.open_unix_connection(str(self._sock_path))
        except (ConnectionError, FileNotFoundError, OSError) as e:
            raise BenchClientError(f"Cannot connect to bench server: {e}") from e
        try:
            await self._send(writer, cmd)
            return await self._recv(reader)
        finally:
            writer.close()
            await writer.wait_closed()

    async def _query_stream(self, cmd: dict) -> AsyncIterator[dict]:
        """Send a command and yield progress messages until done."""
        try:
            reader, writer = await asyncio.open_unix_connection(str(self._sock_path))
        except (ConnectionError, FileNotFoundError, OSError) as e:
            raise BenchClientError(f"Cannot connect to bench server: {e}") from e
        try:
            await self._send(writer, cmd)
            while True:
                msg = await self._recv(reader)
                yield msg
                if msg.get("done") or not msg.get("progress"):
                    break
        finally:
            writer.close()
            await writer.wait_closed()

    def _check(self, result: dict) -> dict:
        """Raise on error responses."""
        if not result.get("ok"):
            raise BenchClientError(result.get("error", "Unknown error"))
        return result

    # ── High-level commands ──

    async def ping(self) -> str:
        """Returns 'pong' if ready, 'loading' if still starting."""
        r = self._check(await self._query({"action": "ping"}))
        return r["text"]

    async def is_connected(self) -> bool:
        """Check if the server is reachable."""
        try:
            await self.ping()
            return True
        except BenchClientError:
            return False

    async def is_ready(self) -> bool:
        """Check if the server is loaded and ready."""
        try:
            return await self.ping() == "pong"
        except BenchClientError:
            return False

    async def wait_ready(self, timeout: float = 60.0):
        """Block until server is ready or timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if await self.is_ready():
                return
            await asyncio.sleep(0.1)
        raise BenchClientError("Timed out waiting for bench server")

    async def status(self) -> str:
        r = self._check(await self._query({"action": "status"}))
        return r["text"]

    # ── Eval ──

    async def eval(self, expression: str, raw: bool = False) -> str:
        r = self._check(await self._query({"action": "eval", "query": expression, "raw": raw}))
        return r["text"]

    # ── Search ──

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        go_next: bool = False,
        go_prev: bool = False,
    ) -> list[str]:
        cmd: dict = {"action": "search", "query": query, "limit": limit}
        if offset:
            cmd["offset"] = offset
        if go_next:
            cmd["next"] = True
        if go_prev:
            cmd["prev"] = True
        r = self._check(await self._query(cmd))
        return r.get("results", [])

    # ── Lens ──

    async def find(self, pattern: str, max_results: int = 50) -> list[str]:
        r = self._check(await self._query({"action": "find", "pattern": pattern, "max": max_results}))
        return r.get("results", [])

    async def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        r = self._check(await self._query({"action": "fuzzy", "query": query, "max": max_results}))
        return r.get("results", [])

    async def view(self, name: str = "") -> str:
        r = self._check(await self._query({"action": "view", "name": name}))
        return r["text"]

    async def view_consumer(self, name: str) -> str:
        r = self._check(await self._query({"action": "view_consumer", "name": name}))
        return r["text"]

    async def view_inputs(self, name: str) -> str:
        r = self._check(await self._query({"action": "view_inputs", "name": name}))
        return r["text"]

    async def view_subgraph(self, name: str, direction: str = "upstream") -> str:
        r = self._check(await self._query({"action": "view_subgraph", "name": name, "direction": direction}))
        return r["text"]

    async def view_kinds(self) -> str:
        r = self._check(await self._query({"action": "view_kinds"}))
        return r["text"]

    async def view_roots(self) -> str:
        r = self._check(await self._query({"action": "view_roots"}))
        return r["text"]

    async def focus(self, name: str) -> str:
        r = self._check(await self._query({"action": "focus", "name": name}))
        return r["text"]

    # ── Hologram ──

    async def dissect(self, name: str) -> str:
        r = self._check(await self._query({"action": "dissect", "name": name}))
        return r["text"]

    async def compose(self, *names: str) -> str:
        r = self._check(await self._query({"action": "compose", "names": list(names)}))
        return r["text"]

    # ── Evaluation ──

    async def diagnose(self, what: str = "summary", focus: str | None = None) -> str:
        cmd: dict = {"action": "diagnose", "what": what}
        if focus:
            cmd["focus"] = focus
        r = self._check(await self._query(cmd))
        return r["text"]

    # ── Operations ──

    async def reload(self) -> str:
        r = self._check(await self._query({"action": "reload"}))
        return r["text"]

    async def purge(self) -> str:
        r = self._check(await self._query({"action": "purge"}))
        return r["text"]

    async def index_dir(self, directory: str = ".", extensions: list[str] | None = None) -> AsyncIterator[dict]:
        cmd: dict = {"action": "index", "directory": directory}
        if extensions:
            cmd["extensions"] = extensions
        async for msg in self._query_stream(cmd):
            yield msg
