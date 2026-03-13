"""Bench CLI — persistent daemon + one-shot client for instant .pltg queries.

Server keeps a Bench loaded in memory. Client sends commands over a Unix socket.

    # Start server (blocks):
    python -m parseltongue.core.inspect.bench_cli serve path/to/file.pltg

    # Query from another terminal (instant):
    python -m parseltongue.core.inspect.bench_cli find "error"
    python -m parseltongue.core.inspect.bench_cli view engine.eval-bind
    python -m parseltongue.core.inspect.bench_cli diagnose
    python -m parseltongue.core.inspect.bench_cli dissect atoms.theorem-derivation-sources
"""

from __future__ import annotations

import json
import logging
import signal
import socket
import struct
import sys
import threading
import traceback
from pathlib import Path

import click

log = logging.getLogger("parseltongue.bench_cli")

SOCK_PATH = Path.home() / ".parseltongue" / "bench.sock"
MAX_MSG = 16 * 1024 * 1024  # 16 MB


# ── Wire protocol: length-prefixed JSON ──


def _send(sock: socket.socket, data: dict):
    raw = json.dumps(data).encode()
    sock.sendall(struct.pack("!I", len(raw)) + raw)


def _recv(sock: socket.socket) -> dict:
    header = b""
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            raise ConnectionError("Connection closed")
        header += chunk
    (length,) = struct.unpack("!I", header)
    if length > MAX_MSG:
        raise ValueError(f"Message too large: {length}")
    buf = b""
    while len(buf) < length:
        chunk = sock.recv(min(length - len(buf), 65536))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return json.loads(buf)


# ── Server ──


class BenchServer:
    """Holds a Bench instance, dispatches commands from socket clients."""

    def __init__(self, pltg_path: str, *, background: bool = False):
        from .bench import Bench

        self.bench = Bench()
        self.pltg_path = pltg_path
        self._last_search: dict | None = None  # cached last search query+params
        if not background:
            self.bench.prepare(pltg_path)

    def start_background_load(self):
        t = threading.Thread(target=self.bench.prepare, args=(self.pltg_path,), daemon=True)
        t.start()

    def _is_ready(self) -> bool:
        return str(self.bench.status) != "Status(initialized)"

    def dispatch(self, cmd: dict) -> dict:
        """Execute a command dict, return a result dict."""
        action = cmd.get("action", "")

        if action == "ping":
            return {"ok": True, "text": "pong" if self._is_ready() else "loading"}

        if action == "status":
            return {
                "ok": True,
                "text": f"path={self.pltg_path}\nstatus={self.bench.status!r}\nintegrity={self.bench.integrity!r}",
            }

        if not self._is_ready():
            return {"ok": False, "error": "Still loading, try again shortly."}
        try:
            if action == "find":
                results = self.bench.lens().find(cmd.get("pattern", ""), cmd.get("max", 50))
                return {"ok": True, "results": results}

            elif action == "fuzzy":
                results = self.bench.lens().fuzzy(cmd.get("query", ""), cmd.get("max", 10))
                return {"ok": True, "results": results}

            elif action == "view":
                name = cmd.get("name", "")
                lens = self.bench.lens()
                text = str(lens.view_node(name) if name else lens.view())
                return {"ok": True, "text": str(text)}

            elif action == "view_consumer":
                text = self.bench.lens().view_consumer(cmd["name"])
                return {"ok": True, "text": str(text)}

            elif action == "view_inputs":
                text = self.bench.lens().view_inputs(cmd["name"])
                return {"ok": True, "text": str(text)}

            elif action == "view_subgraph":
                direction = cmd.get("direction", "upstream")
                text = self.bench.lens().view_subgraph(cmd["name"], direction=direction)
                return {"ok": True, "text": str(text)}

            elif action == "view_kinds":
                text = self.bench.lens().view_kinds()
                return {"ok": True, "text": str(text)}

            elif action == "view_roots":
                text = self.bench.lens().view_roots()
                return {"ok": True, "text": str(text)}

            elif action == "focus":
                name = cmd.get("name", "")
                focused = self.bench.lens().focus(name)
                # Return the view of the focused lens
                text = focused.view()
                return {"ok": True, "text": str(text)}

            elif action == "diagnose":
                dx = self.bench.evaluate()
                focus = cmd.get("focus")
                if focus:
                    dx = dx.focus(focus)
                what = cmd.get("what", "summary")
                if what == "summary":
                    text = dx.summary()
                elif what == "issues":
                    items = dx.issues()
                    text = "\n".join(str(i) for i in items) if items else "No issues."
                elif what == "ok":
                    ok_items = [i for i in dx._items if i.category not in ("issue",)]
                    text = "\n".join(str(i) for i in ok_items) if ok_items else "All items have issues."
                else:
                    text = dx.summary()
                return {"ok": True, "text": str(text)}

            elif action == "dissect":
                h = self.bench.dissect(cmd["name"])
                text = h.view()
                return {"ok": True, "text": str(text)}

            elif action == "compose":
                names = cmd.get("names", [])
                h = self.bench.compose(*names)
                text = h.view()
                return {"ok": True, "text": str(text)}

            elif action == "search":
                limit = cmd.get("limit", 20)
                offset = cmd.get("offset", 0)
                query = cmd.get("query", "")

                # next/prev with query: use that query, shift from cached offset
                # next/prev without query: reuse last query entirely
                if cmd.get("next"):
                    if not query and self._last_search:
                        query = self._last_search["query"]
                        limit = self._last_search["limit"]
                    ref = self._last_search or {"offset": 0, "limit": limit}
                    offset = ref["offset"] + limit
                elif cmd.get("prev"):
                    if not query and self._last_search:
                        query = self._last_search["query"]
                        limit = self._last_search["limit"]
                    ref = self._last_search or {"offset": 0, "limit": limit}
                    offset = max(0, ref["offset"] - limit)

                search_result = self.bench.search(
                    query,
                    max_lines=limit,
                    max_callers=5,
                    offset=offset,
                )
                self._last_search = {"query": query, "limit": limit, "offset": offset}

                lines: list[str] = []
                prev_doc = None
                prev_line = None
                rank = offset
                for r in search_result.get("lines", []):
                    doc = r["document"]
                    line_no = r["line"]
                    if lines and (doc != prev_doc or (prev_line and line_no - prev_line > 1)):
                        lines.append("")
                    rank += 1
                    callers = ", ".join(c["name"] for c in r.get("callers", []))
                    prefix = f"[{callers}] " if callers else ""
                    lines.append(f"{rank}. {doc}:{line_no}  {prefix}{r['context']}")
                    prev_doc = doc
                    prev_line = line_no
                total = search_result.get("total_lines", 0)
                shown = rank - offset
                page = offset // limit + 1 if limit else 1
                pages = (total + limit - 1) // limit if limit else 1
                lines.append("")
                if total > limit:
                    lines.append(f"({offset + 1}-{offset + shown}/{total} results, page {page}/{pages})")
                else:
                    lines.append(f"({total} results)")
                return {"ok": True, "results": lines}

            elif action == "index":
                # Handled separately via dispatch_stream
                return {"ok": False, "error": "use dispatch_stream for index"}

            elif action == "reload":
                self.bench.invalidate()
                self.bench.prepare(self.pltg_path)
                return {"ok": True, "text": "Reloaded."}

            elif action == "purge":
                self.bench.purge()
                self.bench.prepare(self.pltg_path)
                return {"ok": True, "text": "Purged all caches and reloaded."}

            else:
                return {"ok": False, "error": f"Unknown action: {action!r}"}

        except KeyError as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            return {"ok": False, "error": traceback.format_exc()}

    def dispatch_stream(self, cmd: dict, conn: socket.socket):
        """Handle streaming actions that send progress over the socket."""
        action = cmd.get("action", "")
        try:
            if action == "index":
                directory = cmd.get("directory", ".")
                extensions = cmd.get("extensions")

                def _progress(count, total, rel):
                    _send(conn, {"progress": True, "count": count, "total": total, "file": rel})

                exclude = cmd.get("exclude")
                count = self.bench.index.index_dir(directory, extensions, exclude=exclude, on_progress=_progress)
                _send(conn, {"ok": True, "done": True, "text": f"Indexed {count} files from {directory}"})

            elif action == "reindex":

                def _progress(count, total, rel):
                    _send(conn, {"progress": True, "count": count, "total": total, "file": rel})

                count = self.bench.index.reindex(on_progress=_progress)
                _send(conn, {"ok": True, "done": True, "text": f"Reindexed {count} files"})
        except Exception:
            _send(conn, {"ok": False, "done": True, "error": traceback.format_exc()})


_STREAM_ACTIONS = {"index", "reindex"}


def _handle_client(server: BenchServer, conn: socket.socket):
    try:
        cmd = _recv(conn)
        if cmd.get("action") in _STREAM_ACTIONS:
            server.dispatch_stream(cmd, conn)
        else:
            result = server.dispatch(cmd)
            _send(conn, result)
    except Exception as e:
        try:
            _send(conn, {"ok": False, "error": str(e)})
        except Exception:
            pass
    finally:
        conn.close()


def _run_server(pltg_path: str, sock_path: Path, refresh_s: int = 0, log_level: str = "ERROR"):
    logging.getLogger("parseltongue").setLevel(getattr(logging, log_level.upper(), logging.ERROR))
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    # Socket first — queryable immediately (ping/status work while loading)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(sock_path))
    sock.listen(4)

    server = BenchServer(pltg_path, background=True)
    click.echo(f"Listening on {sock_path}")
    click.echo(f"Loading {pltg_path} ...")
    server.start_background_load()

    if refresh_s > 0:
        import time

        def _refresh_loop():
            while True:
                time.sleep(refresh_s)
                if server._is_ready():
                    try:
                        count = server.bench.index.reindex()
                        if count:
                            log.info("Background reindex: %d files", count)
                    except Exception as e:
                        log.warning("Background reindex failed: %s", e)

        t = threading.Thread(target=_refresh_loop, daemon=True)
        t.start()

    def _cleanup(*_):
        sock.close()
        sock_path.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        while True:
            conn, _ = sock.accept()
            t = threading.Thread(target=_handle_client, args=(server, conn), daemon=True)
            t.start()
    finally:
        _cleanup()


# ── Client helper ──


def _query(cmd: dict, sock_path: Path = SOCK_PATH) -> dict:
    """Send a command to the server and return the response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(sock_path))
    try:
        _send(sock, cmd)
        return _recv(sock)
    finally:
        sock.close()


def _query_stream(cmd: dict, sock_path: Path = SOCK_PATH):
    """Send a command and yield progress messages until done."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(sock_path))
    try:
        _send(sock, cmd)
        while True:
            msg = _recv(sock)
            yield msg
            if msg.get("done") or not msg.get("progress"):
                break
    finally:
        sock.close()


def _print_result(result: dict):
    if not result.get("ok"):
        click.echo(result.get("error", "Unknown error"), err=True)
        raise SystemExit(1)
    if "text" in result:
        click.echo(result["text"])
    elif "results" in result:
        for r in result["results"]:
            click.echo(r)


# ── Click CLI ──


@click.group()
def cli():
    """Bench CLI — persistent .pltg inspection daemon."""
    pass


@cli.command()
@click.argument("path")
@click.option("--socket", "sock", default=str(SOCK_PATH), help="Unix socket path.")
@click.option(
    "--refresh-index", "refresh_s", default=2, type=int, help="Background reindex interval in seconds (0=off)."
)
@click.option("--verbose", "-v", is_flag=True, help="Shorthand for --log-level INFO.")
@click.option(
    "--log-level",
    default="ERROR",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Log level (default: ERROR).",
)
def serve(path: str, sock: str, refresh_s: int, verbose: bool, log_level: str):
    """Start the bench server. Loads PATH and listens for queries."""
    if verbose and log_level != "ERROR":
        raise click.UsageError("Cannot use --verbose and --log-level together.")
    if verbose:
        log_level = "INFO"
    _run_server(path, Path(sock), refresh_s=refresh_s, log_level=log_level)


@cli.command()
@click.argument("pattern")
@click.option("--max", "max_results", default=50, help="Max results.")
def find(pattern: str, max_results: int):
    """Regex search over all names."""
    _print_result(_query({"action": "find", "pattern": pattern, "max": max_results}))


@cli.command()
@click.argument("query")
@click.option("--max", "max_results", default=10, help="Max results.")
def fuzzy(query: str, max_results: int):
    """Fuzzy substring search over all names."""
    _print_result(_query({"action": "fuzzy", "query": query, "max": max_results}))


@cli.command()
@click.argument("name", default="")
def view(name: str):
    """View a node (or full structure if no name given)."""
    _print_result(_query({"action": "view", "name": name}))


@cli.command()
@click.argument("name")
def consumer(name: str):
    """View a consumer node with its inputs."""
    _print_result(_query({"action": "view_consumer", "name": name}))


@cli.command()
@click.argument("name")
def inputs(name: str):
    """View inputs of a consumer."""
    _print_result(_query({"action": "view_inputs", "name": name}))


@cli.command()
@click.argument("name")
@click.option("--direction", "-d", default="upstream", type=click.Choice(["upstream", "downstream", "both"]))
def subgraph(name: str, direction: str):
    """View subgraph around a name."""
    _print_result(_query({"action": "view_subgraph", "name": name, "direction": direction}))


@cli.command()
def kinds():
    """View all node kinds with counts."""
    _print_result(_query({"action": "view_kinds"}))


@cli.command()
def roots():
    """View root nodes."""
    _print_result(_query({"action": "view_roots"}))


@cli.command()
@click.argument("name")
def focus(name: str):
    """Focus lens on a name and view."""
    _print_result(_query({"action": "focus", "name": name}))


@cli.command()
@click.option("--focus", "focus_name", default=None, help="Focus on a subsystem.")
@click.option("--what", default="summary", type=click.Choice(["summary", "issues", "ok"]))
def diagnose(focus_name: str | None, what: str):
    """Run diagnosis (cached). Show summary, issues, or passing."""
    cmd = {"action": "diagnose", "what": what}
    if focus_name:
        cmd["focus"] = focus_name
    _print_result(_query(cmd))


@cli.command()
@click.argument("name")
def dissect(name: str):
    """Dissect a diff into a side-by-side hologram view."""
    _print_result(_query({"action": "dissect", "name": name}))


@cli.command()
@click.argument("names", nargs=-1, required=True)
def compose(names: tuple[str, ...]):
    """Compose N system names into a hologram view."""
    _print_result(_query({"action": "compose", "names": list(names)}))


@cli.command()
@click.argument("query", default="")
@click.option("-n", "--limit", default=20, help="Results per page.")
@click.option("--offset", default=0, help="Skip first N results.")
@click.option("--page", default=0, type=int, help="Jump to page (1-based). Overrides offset.")
@click.option("--next", "go_next", is_flag=True, help="Next page of last search.")
@click.option("--prev", "go_prev", is_flag=True, help="Previous page of last search.")
def search(query: str, limit: int, offset: int, page: int, go_next: bool, go_prev: bool):
    """Full-text search across loaded documents."""
    cmd: dict = {"action": "search", "limit": limit}
    if query:
        cmd["query"] = query
    if page > 0:
        offset = (page - 1) * limit
    if offset:
        cmd["offset"] = offset
    if go_next:
        cmd["next"] = True
    if go_prev:
        cmd["prev"] = True
    if not query and not go_next and not go_prev:
        raise click.UsageError("Provide a query or use --next/--prev.")
    _print_result(_query(cmd))


@cli.command("index")
@click.argument("directory", default=".")
@click.option(
    "--ext",
    "extensions",
    multiple=True,
    default=[".py", ".pltg", ".md", ".txt"],
    help="File extensions to index (repeatable).",
)
@click.option(
    "--exclude",
    "excludes",
    multiple=True,
    help="Glob patterns to exclude (repeatable, in addition to .pgignore).",
)
def index_dir(directory: str, extensions: tuple[str, ...], excludes: tuple[str, ...]):
    """Index all files in DIRECTORY into the search engine. Reads .pgignore from directory root."""
    cmd = {"action": "index", "directory": directory, "extensions": list(extensions)}
    if excludes:
        cmd["exclude"] = list(excludes)
    for msg in _query_stream(cmd):
        if msg.get("progress"):
            click.echo(f"\r  {msg['count']}/{msg['total']}  {msg['file']}", nl=False)
        elif msg.get("done"):
            click.echo()  # newline after progress
            _print_result(msg)


@cli.command()
def reindex():
    """Purge index cache and re-index all previously indexed directories."""
    for msg in _query_stream({"action": "reindex"}):
        if msg.get("progress"):
            click.echo(f"\r  {msg['count']}/{msg['total']}  {msg['file']}", nl=False)
        elif msg.get("done"):
            click.echo()
            _print_result(msg)


@cli.command()
def reload():
    """Invalidate cache and reload the .pltg file."""
    _print_result(_query({"action": "reload"}))


@cli.command()
def purge():
    """Purge all caches (memory + disk) and reload."""
    _print_result(_query({"action": "purge"}))


@cli.command()
def status():
    """Show server status."""
    _print_result(_query({"action": "status"}))


@cli.command()
def ping():
    """Check if server is running."""
    _print_result(_query({"action": "ping"}))


@cli.command()
@click.option("--timeout", "timeout_s", default=60, help="Max seconds to wait.")
def wait(timeout_s: int):
    """Block until server is loaded and ready."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            result = _query({"action": "ping"})
            if result.get("text") == "pong":
                click.echo("Ready.")
                return
        except (ConnectionError, FileNotFoundError, OSError):
            pass
        time.sleep(0.05)
    click.echo("Timed out waiting for server.", err=True)
    raise SystemExit(1)


if __name__ == "__main__":
    cli()
