"""Bench CLI — persistent daemon + one-shot client for instant .pltg queries.

Server keeps a Bench loaded in memory. Client sends commands over a Unix socket.

Start:
    pg-bench serve path/to/file.pltg &
    pg-bench wait
    pg-bench index parseltongue/core

Evaluate (default command — bare string arg evaluates):
    pg-bench '(+ 1 2)'                              # => 3
    pg-bench eval '(counting.sum-values x y)'        # same thing
    pg-bench '(if (> x 0) "positive" "negative")'   # conditionals, arithmetic

Search (S-expression query language over indexed documents):
    pg-bench search "raise ValueError"               # literal phrase
    pg-bench search '(in "engine.py" "raise")'       # document filter
    pg-bench search '(and "import" "quote")'          # intersection
    pg-bench search '(or "raise" "return")'           # union
    pg-bench search '(not (in "e.py" "raise") "Key")' # difference
    pg-bench search '(near "raise" "ValueError" 2)'  # proximity
    pg-bench search '(re "def \\w+")'                 # regex
    pg-bench search '(seq "def derive" "raise")'      # a before b
    pg-bench search '(lines 400 500 (in "e.py" .))'  # line range
    pg-bench search '(count (in "engine.py" "raise"))' # count matches

Lens (structural navigation over pltg nodes):
    pg-bench find "error"              # regex over all pltg names
    pg-bench fuzzy "eval"              # ranked substring search
    pg-bench view engine.eval-bind     # single node — quotes, file:line, confidence
    pg-bench view                      # entire structure
    pg-bench focus "engine."           # narrow to namespace
    pg-bench consumer engine.derive    # node with its inputs
    pg-bench inputs engine.derive      # just the inputs
    pg-bench subgraph engine.derive    # upstream dependencies
    pg-bench subgraph engine.derive -d downstream
    pg-bench subgraph engine.derive -d both
    pg-bench kinds                     # node kinds with counts
    pg-bench roots                     # root nodes

Hologram (multi-lens views):
    pg-bench dissect atoms.theorem-derivation-sources  # diff side-by-side
    pg-bench compose engine.eval-bind engine.derive     # parallel lenses

Evaluation (diagnosis — consistency checks):
    pg-bench diagnose                          # summary
    pg-bench diagnose --what issues            # only failures
    pg-bench diagnose --what ok                # only passing
    pg-bench diagnose --focus "engine."        # focus on namespace

Operations:
    pg-bench ping      # "pong" when ready
    pg-bench wait      # blocks until ready
    pg-bench status    # path, status, integrity
    pg-bench reload    # invalidate + re-prepare
    pg-bench purge     # nuclear — clear all caches
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

    def _register_hologram_scope(self, hologram):
        """Register hologram search system as a scope in the main search engine."""
        search = self.bench.index
        search.register_scope("hologram", hologram.search_system._system)

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
            if action == "eval":
                query = cmd.get("query", "")
                query, sexp_warn = _validate_sexp(query)
                result = self.bench.eval(query)
                if cmd.get("raw"):
                    text = _format_eval_raw(result)
                else:
                    text = _format_eval_result(result, bench=self.bench)
                if sexp_warn:
                    text = f"⚠ {sexp_warn}\n\n{text}"
                return {"ok": True, "text": text}

            elif action == "find":
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
                self._register_hologram_scope(h)
                text = h.view()
                return {"ok": True, "text": str(text)}

            elif action == "compose":
                names = cmd.get("names", [])
                h = self.bench.compose(*names)
                self._register_hologram_scope(h)
                text = h.view()
                return {"ok": True, "text": str(text)}

            elif action == "search":
                limit = cmd.get("limit", 20)
                offset = cmd.get("offset", 0)
                query = cmd.get("query", "")
                query, sexp_warn = _validate_sexp(query)

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
                if sexp_warn:
                    lines.insert(0, f"⚠ {sexp_warn}")
                    lines.insert(1, "")
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
                total = len(self.bench.index._index.documents)
                msg = f"Indexed {count} new files from {directory} ({total} total)"
                _send(conn, {"ok": True, "done": True, "text": msg})

            elif action == "reindex":

                def _progress(count, total, rel):
                    _send(conn, {"progress": True, "count": count, "total": total, "file": rel})

                count = self.bench.index.reindex(on_progress=_progress)
                _send(conn, {"ok": True, "done": True, "text": f"Reindexed {count} files"})
        except Exception:
            _send(conn, {"ok": False, "done": True, "error": traceback.format_exc()})


def _validate_sexp(query: str) -> tuple[str, str | None]:
    """Validate and auto-fix S-expression syntax.

    Returns (corrected_query, warning).
    warning is None if no fixes were needed.
    Auto-fixes: stray shell quotes, unclosed parens, trailing extra parens.
    Shows roundtrip on fix so user sees what was actually parsed.
    """
    from parseltongue.core.atoms import read_tokens, to_sexp, tokenize

    q = query.strip()
    if not q or not q.startswith("("):
        return q, None  # plain text, skip

    fixes: list[str] = []

    # Single quotes are never valid in s-expressions — always shell artifacts.
    # Strip them (outside double-quoted strings).
    cleaned: list[str] = []
    in_dq = False
    esc = False
    had_sq = False
    for ch in q:
        if esc:
            cleaned.append(ch)
            esc = False
            continue
        if ch == "\\" and in_dq:
            cleaned.append(ch)
            esc = True
            continue
        if ch == '"':
            in_dq = not in_dq
            cleaned.append(ch)
            continue
        if ch == "'" and not in_dq:
            had_sq = True
            continue
        cleaned.append(ch)
    if had_sq:
        q = "".join(cleaned)
        fixes.append("stripped stray ' (shell quoting artifact)")

    # Balanced parens (outside strings)
    depth = 0
    in_str = False
    escaped = False
    for ch in q:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            if in_str:
                escaped = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1

    if in_str:
        return q, 'Unclosed string literal (missing closing ")'
    if depth > 0:
        q += ")" * depth
        fixes.append(f"added {depth} closing paren(s)")
    elif depth < 0:
        # Strip trailing extra parens
        extra = -depth
        for _ in range(extra):
            idx = q.rfind(")")
            if idx >= 0:
                q = q[:idx] + q[idx + 1 :]
        fixes.append(f"removed {extra} extra closing paren(s)")

    # Parse and roundtrip
    warning = None
    try:
        tokens = tokenize(q)
        if tokens:
            parsed = read_tokens(list(tokens))
            roundtrip = to_sexp(parsed)
            if fixes:
                warning = f"Auto-fixed: {', '.join(fixes)}\n  parsed as: {roundtrip}"
    except SyntaxError as e:
        # Can't fix this — return error as warning, let caller decide
        warning = f"Parse error: {e}\n  tokens: {tokenize(q)}"

    return q, warning


_BENCH_FORM_TAGS = {"sr", "ln", "dx", "hn"}
_FMT_FORM_TAGS = {"sr-fmt", "ln-fmt", "dx-fmt", "hn-fmt"}


def _form_tag(item) -> str | None:
    """Return the bare tag name if item is a tagged bench/display form, else None."""
    from parseltongue.core.atoms import Symbol

    if isinstance(item, list) and len(item) >= 2 and isinstance(item[0], Symbol):
        name = str(item[0])
        bare = name.rsplit(".", 1)[-1] if "." in name else name
        if bare in _BENCH_FORM_TAGS or bare in _FMT_FORM_TAGS:
            return bare
    return None


_TAG_QUALIFY = {
    "sr": "bench_pg.search.sr",
    "ln": "bench_pg.lens.ln",
    "dx": "bench_pg.evaluation.dx",
    "hn": "bench_pg.hologram.hn",
}


def _fmt_via_bench(bench, result, perspective="md"):
    """Evaluate (fmt perspective result) through view.pltg axioms."""
    from parseltongue.core.atoms import Symbol

    try:
        # Qualify bare tags so axiom patterns match
        if isinstance(result, list) and result and isinstance(result[0], Symbol):
            bare = str(result[0])
            if bare in _TAG_QUALIFY:
                result = [Symbol(_TAG_QUALIFY[bare])] + result[1:]
        path = bench._require_current()
        _, system = bench._ensure_eval_system(path)
        return system.engine.evaluate([Symbol("fmt"), perspective, result])
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("fmt failed: %s", e)
        return None


def _get_perspective(bench, name="md"):
    """Get a Perspective instance from the bench lens."""
    if name == "md":
        from parseltongue.core.inspect.perspectives.md_debugger import MDebuggerPerspective

        return bench.lens()._get(MDebuggerPerspective)
    if name == "ascii":
        from parseltongue.core.inspect.perspectives.ascii import AsciiPerspective

        return bench.lens()._get(AsciiPerspective)
    return None


def _format_eval_result(result, bench=None) -> str:
    """Format an eval result for display.

    If bench is provided, evaluates (fmt "md" result) through view.pltg
    axioms and renders via the MDebuggerPerspective. View structure is
    defined in the language; rendering goes through perspectives.
    """
    from parseltongue.core.atoms import Symbol

    if result is None:
        return "nil"
    if isinstance(result, bool):
        return "true" if result else "false"
    if isinstance(result, (int, float)):
        return str(result)
    if isinstance(result, Symbol):
        return str(result)
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        tag = _form_tag(result)
        # Single bench form → fmt → perspective render
        if tag in _BENCH_FORM_TAGS and bench:
            fmt_result = _fmt_via_bench(bench, result)
            if fmt_result and _form_tag(fmt_result) in _FMT_FORM_TAGS:
                perspective = _get_perspective(bench)
                if perspective:
                    return str(perspective.render_form(fmt_result))
        # Already a display form
        if tag in _FMT_FORM_TAGS and bench:
            perspective = _get_perspective(bench)
            if perspective:
                return str(perspective.render_form(result))
        # List of bench forms → fmt each → perspective render_form_list
        if result and _form_tag(result[0]) in _BENCH_FORM_TAGS and bench:
            fmt_forms = []
            for item in result:
                fmt_result = _fmt_via_bench(bench, item)
                if fmt_result and _form_tag(fmt_result) in _FMT_FORM_TAGS:
                    fmt_forms.append(fmt_result)
            if fmt_forms:
                perspective = _get_perspective(bench)
                if perspective:
                    return str(perspective.render_form_list(fmt_forms))
        # List of display forms
        if result and _form_tag(result[0]) in _FMT_FORM_TAGS and bench:
            perspective = _get_perspective(bench)
            if perspective:
                return str(perspective.render_form_list(result))
        # Generic list
        parts = [_format_eval_result(item, bench=bench) for item in result]
        return "(" + " ".join(parts) + ")"
    if isinstance(result, dict):
        # Posting set — show as doc:line  [callers] context
        if not result:
            return "(empty)"
        lines = []
        sorted_keys = sorted(
            result.keys(),
            key=lambda k: (k[0], k[1]) if isinstance(k, tuple) else (str(k), 0),
        )
        for i, key in enumerate(sorted_keys[:50], 1):
            entry = result[key]
            if isinstance(entry, dict) and "context" in entry:
                callers = entry.get("callers", [])
                prefix = f"[{', '.join(c['name'] for c in callers)}] " if callers else ""
                doc = entry["document"]
                ln = entry["line"]
                lines.append(f"{i}. {doc}:{ln}  {prefix}{entry['context']}")
            elif isinstance(key, tuple) and len(key) == 2:
                lines.append(f"{i}. {key[0]}:{key[1]}")
            else:
                lines.append(f"{i}. {key}")
        if len(result) > 50:
            lines.append(f"  ... and {len(result) - 50} more")
        lines.append(f"({len(result)} results)")
        return "\n\n".join(lines)
    return str(result)


def _format_eval_raw(result) -> str:
    """Format an eval result as raw S-expression."""
    from parseltongue.core.atoms import to_sexp

    return to_sexp(result)


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


BENCH_DIR = Path(".parseltongue-bench")


def _setup_file_logging(console_level: str):
    """Add a file handler to .parseltongue-bench/bench.log."""
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    log_path = BENCH_DIR / "bench.log"
    root = logging.getLogger("parseltongue")
    # File: always DEBUG
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)
    # Console: respect --log-level / --verbose
    sh = logging.StreamHandler()
    sh.setLevel(getattr(logging, console_level.upper(), logging.ERROR))
    root.addHandler(sh)
    # Root open, handlers filter
    root.setLevel(logging.DEBUG)


def _run_server(pltg_path: str, sock_path: Path, refresh_s: int = 0, log_level: str = "ERROR"):
    _setup_file_logging(log_level)
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


class _EvalFallbackGroup(click.Group):
    """Group that treats unrecognized commands as eval expressions."""

    def parse_args(self, ctx, args):
        # If first arg is not a known command and not a flag, treat as eval
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["eval"] + args
        return super().parse_args(ctx, args)


@click.group(cls=_EvalFallbackGroup)
def cli():
    """pg-bench — persistent .pltg inspection daemon.

    \b
    EVALUATE (default — bare expression evaluates directly):
      pg-bench '(+ 1 2)'                          => 3
      pg-bench '(counting.sum-values x y)'         => 30
      pg-bench '(if (> x 0) "pos" "neg")'          => pos

    \b
    SEARCH (S-expression query language):
      pg-bench search "raise ValueError"
      pg-bench search '(in "engine.py" "raise")'
      pg-bench search '(and "import" "quote")'
      pg-bench search '(or "raise" "return")'
      pg-bench search '(not (in "e.py" "raise") "Key")'
      pg-bench search '(re "def \\\\w+")'
      pg-bench search '(seq "def derive" "raise")'
      pg-bench search '(count (in "engine.py" "raise"))'

    \b
    LENS (structural navigation):
      pg-bench find "error"           pg-bench fuzzy "eval"
      pg-bench view engine.eval-bind  pg-bench view
      pg-bench focus "engine."        pg-bench kinds
      pg-bench consumer engine.derive pg-bench inputs engine.derive
      pg-bench subgraph engine.derive [-d downstream|both]
      pg-bench roots

    \b
    HOLOGRAM (multi-lens):
      pg-bench dissect atoms.theorem-derivation-sources
      pg-bench compose engine.eval-bind engine.derive

    \b
    DIAGNOSIS:
      pg-bench diagnose [--what issues|ok] [--focus "engine."]

    \b
    OPERATIONS:
      pg-bench serve file.pltg &   pg-bench wait
      pg-bench index parseltongue/core
      pg-bench ping   pg-bench status   pg-bench reload   pg-bench purge
    """


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
    """Start the bench server. Loads PATH and listens for queries.

    \b
    The server holds a Bench in memory with Merkle-cached loading (~20ms
    after first cold start ~300ms). Queries arrive over a Unix socket.
    Background reindex watches for file changes every --refresh-index seconds.

    \b
    Typical startup:
      pg-bench serve parseltongue/core/validation/core.pltg &
      pg-bench wait
      pg-bench index parseltongue/core
    """
    if verbose and log_level != "ERROR":
        raise click.UsageError("Cannot use --verbose and --log-level together.")
    if verbose:
        log_level = "INFO"
    _run_server(path, Path(sock), refresh_s=refresh_s, log_level=log_level)


@cli.command("eval")
@click.argument("expression")
@click.option("--raw", is_flag=True, help="Output raw S-expression (to_sexp).")
def eval_cmd(expression: str, raw: bool):
    """Evaluate an S-expression in the bench engine (main + std + scopes).

    \b
    Combines the loaded .pltg system, the full std library, and three
    registered scopes (lens, evaluation, count). Module aliases resolve
    automatically: counting.X, epistemics.Y, lists.Z work without std.
    Built-in arithmetic (+, -, *, /, mod), comparison (>, <, >=, <=, =,
    !=), logic (and, or, not, implies), conditionals (if), bindings (let),
    and quoting (quote) are always available.

    \b
    SCOPES — cross-system evaluation:
      Three scopes give eval access to the lens (structure) and evaluation
      (diagnosis) systems. Use (scope name expr) to evaluate in a scope.

    \b
      Lens scope — structural navigation over the pltg graph:
        (scope lens (kind "fact"))        all fact nodes as posting set
        (scope lens (kind "diff"))        all diff nodes
        (scope lens (inputs "engine.derive"))   upstream deps of a node
        (scope lens (downstream "engine.derive"))  what depends on it
        (scope lens (roots))              root nodes (depth 0, no inputs)
        (scope lens (layer 2))            all nodes at depth 2
        (scope lens (focus "engine."))    filter to namespace prefix
        (scope lens (node "engine.derive"))  single node posting set
        (scope lens (depth "engine.derive"))   depth as int
        (scope lens (value "engine.derive"))   node value as string
        (scope lens (terms "axiom"))      list of axiom names (not posting set)
        (scope lens (quotes "engine.derive"))  list of quote strings

    \b
      Evaluation scope — consistency diagnosis results:
        (scope evaluation (issues))       all failing diffs
        (scope evaluation (warnings))     all warnings
        (scope evaluation (danglings))    all dangling definitions
        (scope evaluation (kind "diff"))  items by directive kind
        (scope evaluation (category "issue"))   by category
        (scope evaluation (type "diverge"))     by issue type substring
        (scope evaluation (focus "engine."))    filter to namespace
        (scope evaluation (consistent))         true if no issues
        (scope evaluation (ns))                 all top-level namespaces

    \b
      Count — posting set size:
        (count (scope lens (kind "fact")))       how many facts
        (count (scope evaluation (issues)))      how many issues

    \b
    PROJECT — resolve in parent before crossing scope boundary:
      (scope lens (focus (project engine-prefix)))
        Evaluates engine-prefix in the bench engine first, passes the
        concrete value to the lens scope. Without project, the lens
        scope would try to resolve engine-prefix itself.
      (scope evaluation (focus (project (if use-engine "engine." "atoms."))))
        Conditional resolution: the if-expression evaluates in the parent
        engine, the result string crosses into the evaluation scope.

    \b
    DELEGATE — happens-before transport across scope chains:
      (delegate body)
        Each scope in the chain posts a proposal. The innermost scope
        whose proposal succeeds provides the result.
      (delegate (= ?answer 42) ?answer)
        Conditional: bind ?answer from each scope's env, return body
        only from the scope where answer equals 42.
      (delegate (= ?_level 2) (scope signer (sign data)))
        ?_level binds to nesting depth — pick a specific scope layer.

    \b
    SPLATS — variadic patterns via ?...rest:
      Axioms use ?...rest to match zero or more remaining args. The
      bound list is spliced (not nested) during substitution.
        (counting.count-exists a b c d)   4 args — step axiom peels
          first, recurses on ?...rest until base case
        (lists.cons a b c)               builds [a, b, c] via peel-
          recurse-prepend with ?...rest splat
        (lists.concat (quote (1 2)) (quote (3 4)))  double splat
          (?...xs ?...ys) merges two lists

    \b
    STD LIBRARY:
      counting.count-exists a b c      count truthy args (variadic)
      counting.sum-values x y z        sum numeric args (variadic)
      epistemics.witness STATUS         label with epistemic status
      epistemics.joint-status s1 s2     group status (hallucination absorbs)
      epistemics.collapse (epistemics.superpose ...) OBS
                                        collapse superposition via observation
      epistemics.count-hallucinated s1 s2   count hallucinated in args
      lists.cons a b c                  build list from evaluated args
      lists.concat L1 L2               concatenate quoted lists
      lists.filter TARGET PAIRS        select names matching target value
      util.export val                   identity — marks for cross-module use
      util.stub                         universal placeholder, always diverges

    \b
    SEARCH — posting-set operators over indexed documents:
      The search system is the central navigation layer. Every operator
      works on posting sets keyed by (document, line). Compose freely.

    \b
      Document filter — restrict to file(s) by exact name, suffix, or glob:
        (in "engine.py" "raise")            only engine.py
        (in "tests/*" "assert")             glob pattern
        (in "*.pltg" "import")              by extension

    \b
      Set operations — combine posting sets:
        (and "import" "quote")              intersection: both on same line
        (or "raise ValueError" "raise Key") union: either match
        (not "raise" "KeyError")            difference: first minus rest

    \b
      Proximity and ordering:
        (near "raise" "ValueError" 2)       within 2 lines of each other
        (near "def" "return" 5)             definition near its return
        (seq "def derive" "raise")          a appears before b in same doc

    \b
      Regex:
        (re "def \\w+")                     Python regex over all documents
        (in "engine.py" (re "raise.*Error"))  regex within a document

    \b
      Line range:
        (lines 400 500 (in "engine.py" .))  restrict to line range
        (lines 1 50 (re "import"))          imports in first 50 lines

    \b
      Context expansion — grow matches to surrounding lines:
        (before 3 "raise")                  include 3 lines before each match
        (after 5 "def derive")             include 5 lines after each match
        (context 2 "raise ValueError")     2 lines before AND after

    \b
      Count — posting set cardinality:
        (count (in "engine.py" "raise"))    how many lines match
        (count (and "import" "quote"))      count co-occurrences

    \b
      Scope — delegate to a registered system:
        (scope lens (kind "fact"))          evaluate in the lens system
        (scope evaluation (issues))        evaluate in diagnosis system
        (scope hologram (divergent))        evaluate in hologram system

    \b
      Composition — operators nest and compose:
        (count (not (in "engine.py" (near "raise" "ValueError" 3)) "KeyError"))
          Count raises near ValueError in engine.py, excluding KeyError.
        (in "*.py" (and (re "def \\w+") (not (re "def test_"))))
          Find non-test function definitions across all Python files.
        (seq (in "engine.py" "def derive") (in "engine.py" "raise"))
          Find derives that have a raise somewhere below them.

    \b
    HOLOGRAM — multi-lens comparison operators (via scope hologram):
      After dissect or compose, a hologram scope is registered:
        (scope hologram (left))              all nodes in first lens
        (scope hologram (right))             all nodes in last lens
        (scope hologram (lens 0))            nodes in Nth lens (0-based)
        (scope hologram (divergent))         nodes in some lenses but not all
        (scope hologram (common))            nodes present in ALL lenses
        (scope hologram (only 0))            nodes exclusive to lens 0
        (scope hologram (left (kind "fact")))  facts in left side only

    \b
    COMPOSITION EXAMPLES:
      Count facts in the engine namespace that have issues:
        (count (scope evaluation (focus "engine." (issues))))

      Check if more than half the diffs pass:
        (let ((total (count (scope lens (kind "diff"))))
              (bad   (count (scope evaluation (issues)))))
          (> total (* 2 bad)))

      List all axiom names from the lens graph:
        (scope lens (terms "axiom"))

      Get quotes from a specific node:
        (scope lens (quotes "engine.derive"))

      Epistemic status of a group of claims, then branch:
        (if (= (epistemics.joint-status s1 s2 s3) epistemics.hallucinated)
          "contaminated" "clean")

      Find engine functions that raise, count them, check threshold:
        (let ((raises (count (in "engine.py" (near "def" "raise" 10))))
              (total  (count (in "engine.py" (re "def \\w+")))))
          (> raises (* total 0.3)))
    """
    _print_result(_query({"action": "eval", "query": expression, "raw": raw}))


@cli.command()
@click.argument("pattern")
@click.option("--max", "max_results", default=50, help="Max results.")
def find(pattern: str, max_results: int):
    """Regex search over all pltg node names in the lens graph.

    \b
    Returns names matching PATTERN (Python regex). Each name is a pltg
    definition (fact, axiom, theorem, term, diff) with file:line location.

    \b
    Examples:
      pg-bench find "engine"        # all names containing "engine"
      pg-bench find "^engine\\."     # names starting with "engine."
      pg-bench find "count.*exist"  # count-exists variants
    """
    _print_result(_query({"action": "find", "pattern": pattern, "max": max_results}))


@cli.command()
@click.argument("query")
@click.option("--max", "max_results", default=10, help="Max results.")
def fuzzy(query: str, max_results: int):
    """Ranked substring search over all pltg names.

    \b
    Scores names by substring match quality (prefix > infix > suffix).
    Returns top --max results sorted by score.

    \b
    Examples:
      pg-bench fuzzy "eval"     # eval-bind, evaluate, eval-rewritten, ...
      pg-bench fuzzy "count"    # count-exists, count-hallucinated, ...
    """
    _print_result(_query({"action": "fuzzy", "query": query, "max": max_results}))


@cli.command()
@click.argument("name", default="")
def view(name: str):
    """View a single node or the full probe structure.

    \b
    Without NAME: shows the entire CoreToConsequence structure — all nodes
    organized by layer with truncated quotes (brief mode).

    \b
    With NAME: shows detailed view of one node — full quotes with document
    line numbers, source file:line, QuoteVerifier confidence score.

    \b
    Examples:
      pg-bench view                    # full structure
      pg-bench view engine.eval-bind   # single node detail
    """
    _print_result(_query({"action": "view", "name": name}))


@cli.command()
@click.argument("name")
def consumer(name: str):
    """View a node together with all its input dependencies.

    \b
    Shows the node itself plus each input it consumes, with full detail
    (quotes, file:line, confidence). Useful for understanding what feeds
    into a derive or diff.
    """
    _print_result(_query({"action": "view_consumer", "name": name}))


@cli.command()
@click.argument("name")
def inputs(name: str):
    """View just the input dependencies of a node (without the node itself)."""
    _print_result(_query({"action": "view_inputs", "name": name}))


@cli.command()
@click.argument("name")
@click.option("--direction", "-d", default="upstream", type=click.Choice(["upstream", "downstream", "both"]))
def subgraph(name: str, direction: str):
    """View the dependency subgraph around a name.

    \b
    Directions:
      upstream    — what NAME depends on (default)
      downstream  — what depends on NAME
      both        — full dependency neighborhood
    """
    _print_result(_query({"action": "view_subgraph", "name": name, "direction": direction}))


@cli.command()
def kinds():
    """View all node kinds (fact, axiom, theorem, term, diff) with counts."""
    _print_result(_query({"action": "view_kinds"}))


@cli.command()
def roots():
    """View root nodes (not consumed by any derivation)."""
    _print_result(_query({"action": "view_roots"}))


@cli.command()
@click.argument("name")
def focus(name: str):
    """Narrow the lens to nodes matching a namespace prefix, then view.

    \b
    Examples:
      pg-bench focus "engine."      # only engine.* nodes
      pg-bench focus "atoms."       # only atoms.* nodes
    """
    _print_result(_query({"action": "focus", "name": name}))


@cli.command()
@click.option("--focus", "focus_name", default=None, help="Focus on a subsystem prefix.")
@click.option("--what", default="summary", type=click.Choice(["summary", "issues", "ok"]))
def diagnose(focus_name: str | None, what: str):
    """Run consistency diagnosis (Merkle-cached).

    \b
    Evaluates all diffs in the loaded .pltg and reports divergences.
    Cached — same Merkle root = same diagnosis. Incremental when
    only some files change.

    \b
    --what summary  issue + dangling counts (default)
    --what issues   only failing diffs with values
    --what ok       only passing diffs
    --focus         filter to a namespace prefix
    """
    cmd = {"action": "diagnose", "what": what}
    if focus_name:
        cmd["focus"] = focus_name
    _print_result(_query(cmd))


@cli.command()
@click.argument("name")
def dissect(name: str):
    """Dissect a diff into a side-by-side hologram.

    \b
    Creates two lenses — one for :replace, one for :with — showing the
    full probe structure of each side. The hologram is registered as a
    search scope so you can query it via (scope hologram ...).
    """
    _print_result(_query({"action": "dissect", "name": name}))


@cli.command()
@click.argument("names", nargs=-1, required=True)
def compose(names: tuple[str, ...]):
    """Compose N system names into a hologram — one lens per name.

    \b
    Each name gets its own probe structure displayed in parallel.
    Useful for comparing how different subsystems relate.

    \b
    Example:
      pg-bench compose engine.eval-bind engine.derive engine._rewrite
    """
    _print_result(_query({"action": "compose", "names": list(names)}))


@cli.command()
@click.argument("query", default="")
@click.option("-n", "--limit", default=20, help="Results per page.")
@click.option("--offset", default=0, help="Skip first N results.")
@click.option("--page", default=0, type=int, help="Jump to page (1-based). Overrides offset.")
@click.option("--next", "go_next", is_flag=True, help="Next page of last search.")
@click.option("--prev", "go_prev", is_flag=True, help="Previous page of last search.")
def search(query: str, limit: int, offset: int, page: int, go_next: bool, go_prev: bool):
    """Full-text search across indexed documents with pltg provenance.

    \b
    Plain strings are literal phrase searches:
      pg-bench search "raise ValueError"

    \b
    Queries starting with ( are S-expressions — set operators:
      (and "import" "quote")                   intersection
      (or "raise ValueError" "raise Syntax")   union
      (not "raise" "test")                     difference
      (in "engine.py" "raise")                 document filter (exact/suffix/glob)
      (near "raise" "ValueError" 3)            proximity within N lines
      (seq "def derive" "raise")               a before b in same doc
      (re "raise (ValueError|NameError)")      regex
      (lines 400 500 query)                    line range filter

    \b
    Context expansion (add surrounding lines):
      (context 3 "raise")                      N lines before + after
      (before 3 "raise")                       N lines before only
      (after 3 "raise")                        N lines after only

    \b
    Ranking and output:
      (rank "callers" query)                   rank by caller count
      (rank "coverage" query)                  rank by overlap
      (rank "document" query)                  group by doc
      (rank "line" query)                      sort by doc:line
      (count query)                            integer count
      (results query)                          convert to sr forms
      (limit N query)                          first N entries

    \b
    Compose freely:
      (not (in "engine.py" (near "raise" "ValueError" 3)) "KeyError")

    Results include pltg provenance: [node.name] matching line
    """
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
    """Re-index all previously indexed directories (detects file changes)."""
    for msg in _query_stream({"action": "reindex"}):
        if msg.get("progress"):
            click.echo(f"\r  {msg['count']}/{msg['total']}  {msg['file']}", nl=False)
        elif msg.get("done"):
            click.echo()
            _print_result(msg)


@cli.command()
def reload():
    """Invalidate Merkle cache and reload the .pltg file from scratch."""
    _print_result(_query({"action": "reload"}))


@cli.command()
def purge():
    """Nuclear — purge all caches (memory + disk) and reload from scratch."""
    _print_result(_query({"action": "purge"}))


@cli.command()
def status():
    """Show server status (path, status, integrity)."""
    _print_result(_query({"action": "status"}))


@cli.command()
def ping():
    """Check if server is running and ready."""
    _print_result(_query({"action": "ping"}))


@cli.command()
@click.option("--timeout", "timeout_s", default=60, help="Max seconds to wait.")
def wait(timeout_s: int):
    """Block until server is loaded and ready. Use after backgrounded serve."""
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
