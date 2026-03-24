"""Bench CLI — persistent daemon + one-shot client for instant .pltg queries.

Server keeps a Bench loaded in memory. Client sends commands over a Unix socket.

Start:
    pg-bench serve path/to/file.pltg &   # foreground (blocking)
    pg-bench start path/to/file.pltg     # daemonized (returns immediately)
    pg-bench up path/to/file.pltg        # foreground; pg-bench up -d to detach
    pg-bench wait                         # block until ready
    pg-bench index parseltongue/core      # index source files for search

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
    pg-bench search '(near 2 "raise" "ValueError")'  # proximity
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

Screen (consistency checks):
    pg-bench diagnose                          # summary (alias: screen)
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
import os
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
        import time as _time

        from .store import BENCH_DIR

        dump_dir = Path(BENCH_DIR) / "dumps"
        dump_dir.mkdir(parents=True, exist_ok=True)
        ts = _time.strftime("%Y%m%d_%H%M%S")
        dump_path = dump_dir / f"oversized_{ts}_{length}.txt"

        # Read full payload, then pretty-print to file
        buf = b""
        try:
            while len(buf) < length:
                chunk = sock.recv(min(length - len(buf), 65536))
                if not chunk:
                    break
                buf += chunk
        except Exception:
            pass
        try:
            obj = json.loads(buf)
            # If it's a response envelope, extract the payload for readability
            if isinstance(obj, dict) and "result" in obj:
                payload = obj["result"]
                if isinstance(payload, str):
                    text = payload
                else:
                    text = json.dumps(payload, indent=2, ensure_ascii=False)
            else:
                text = json.dumps(obj, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, UnicodeDecodeError):
            text = buf.decode("utf-8", errors="replace")
        # Normalize: strip trailing whitespace per line, collapse 3+ blank lines to 2
        import re

        lines = [line.rstrip() for line in text.splitlines()]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
        dump_path.write_text(text + "\n")
        log.error("Oversized message (%d bytes) dumped to %s", length, dump_path)
        raise ValueError(f"Message too large: {length} bytes — written to {dump_path}")
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

    def __init__(self, pltg_path: str, *, background: bool = False, effects: dict | None = None):
        from .bench import Bench

        self.bench = Bench()
        self.pltg_path = pltg_path
        self._effects = effects
        self._last_search: dict | None = None  # cached last search query+params
        if not background:
            self.bench.prepare(pltg_path, effects=effects)

    def start_background_load(self):
        t = threading.Thread(
            target=self.bench.prepare, args=(self.pltg_path,), kwargs={"effects": self._effects}, daemon=True
        )
        t.start()

    def _is_ready(self) -> bool:
        return str(self.bench.status) != "Status(initialized)"

    def _is_initialized(self) -> bool:
        return str(self.bench.status) == "Status(initialized)"

    def _register_hologram_scope(self, hologram):
        """Register hologram search system as a scope in the main search engine."""
        search = self.bench.index
        search.register_scope("hologram", hologram.search_system)

    @staticmethod
    def _apply_bias(hologram, bias_name: str):
        """Apply a named bias to a hologram, returning a new hologram."""
        from .optics.hologram import Bias

        bias_map = {
            "neutral": Bias.NEUTRAL,
            "left": Bias.LEFT,
            "right": Bias.RIGHT,
            "divergence": Bias.DIVERGENCE,
        }
        bias = bias_map.get(bias_name)
        if bias is not None and bias is not Bias.NEUTRAL:
            return hologram.bias(bias)
        return hologram

    def dispatch(self, cmd: dict) -> dict:
        """Execute a command dict, return a result dict."""
        action = cmd.get("action", "")

        if action == "ping":
            return {"ok": True, "text": "pong" if self._is_ready() else "loading"}

        if action == "status":
            lines = [
                f"path={self.pltg_path}",
                f"status={self.bench.status!r}",
                f"integrity={self.bench.integrity!r}",
            ]
            # Elaborate on corrupted integrity
            path = self.bench._current_path
            if path and self.bench.integrity[path] == "corrupted":
                try:
                    dx = self.bench.evaluate()
                    loader_items = dx.loader()
                    if loader_items:
                        errors = [i for i in loader_items if i.type == "error"]
                        skipped = [i for i in loader_items if i.type == "skipped"]
                        warnings = [i for i in loader_items if i.type == "warning"]
                        if errors:
                            lines.append(f"\n{len(errors)} load error(s):")
                            for i in errors[:10]:
                                detail = str(i.detail or i.type).strip().splitlines()[-1].strip()
                                lines.append(f"  {i.name}: {detail}")
                        if skipped:
                            lines.append(f"{len(skipped)} skipped (cascading)")
                        if warnings:
                            lines.append(f"{len(warnings)} warning(s)")
                except Exception:
                    pass
            return {"ok": True, "text": "\n".join(lines)}

        if self._is_initialized():
            return {"ok": False, "error": "Still initializing, no data loaded yet."}
        try:
            if action == "eval":
                query = cmd.get("query", "")
                query, sexp_warn = _validate_sexp(query)
                if cmd.get("profile"):
                    import cProfile
                    import pstats
                    import time as _time

                    prof = cProfile.Profile()
                    prof.enable()
                    result = self.bench.eval(query)
                    if cmd.get("raw"):
                        text = _format_eval_raw(result)
                    else:
                        text = _format_eval_result(result, bench=self.bench)
                    prof.disable()
                    prof_dir = BENCH_DIR / "profiles"
                    prof_dir.mkdir(parents=True, exist_ok=True)
                    ts = _time.strftime("%Y%m%d_%H%M%S")
                    prof_path = prof_dir / f"eval_{ts}.prof"
                    prof.dump_stats(str(prof_path))
                    # Also write human-readable stats
                    import io

                    s = io.StringIO()
                    ps = pstats.Stats(prof, stream=s).sort_stats("cumulative")
                    ps.print_stats(40)
                    txt_path = prof_dir / f"eval_{ts}.txt"
                    txt_path.write_text(s.getvalue())
                    text = f"[profile saved: {prof_path} + {txt_path}]\n\n{text}"
                else:
                    result = self.bench.eval(query)
                    if cmd.get("raw"):
                        text = _format_eval_raw(result)
                    else:
                        text = _format_eval_result(result, bench=self.bench)
                if sexp_warn:
                    text = f"⚠ {sexp_warn}\n\n{text}"
                return {"ok": True, "text": text}

            elif action == "interpret":
                query = cmd.get("query", "")
                query, sexp_warn = _validate_sexp(query)
                result = self.bench.interpret(query)
                if cmd.get("raw"):
                    text = _format_eval_raw(result)
                else:
                    text = _format_eval_result(result, bench=self.bench)
                if sexp_warn:
                    text = f"⚠ {sexp_warn}\n\n{text}"
                return {"ok": True, "text": text}

            elif action == "find":
                scope = cmd.get("scope", "all")
                pattern = cmd.get("pattern", "")
                mx = cmd.get("max", 50)
                results = []
                if scope in ("all", "lens"):
                    results.extend(self.bench.lens().find(pattern, mx))
                if scope in ("all", "screen"):
                    results.extend(self.bench.screen().find(pattern, mx))
                return {"ok": True, "results": results[:mx]}

            elif action == "fuzzy":
                scope = cmd.get("scope", "all")
                query = cmd.get("query", "")
                mx = cmd.get("max", 10)
                results = []
                if scope in ("all", "lens"):
                    results.extend(self.bench.lens().fuzzy(query, mx))
                if scope in ("all", "screen"):
                    results.extend(self.bench.screen().fuzzy(query, mx))
                return {"ok": True, "results": results[:mx]}

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

            elif action in ("diagnose", "screen"):
                dx = self.bench.screen()
                focus = cmd.get("focus")
                if focus:
                    dx = dx.focus(focus)
                what = cmd.get("what", "summary")
                if what == "summary":
                    text = dx.summary()
                elif what == "issues":
                    items = dx.issues()
                    text = "\n".join(str(i) for i in items) if items else "No issues."
                elif what == "loader":
                    items = dx.loader()
                    parts = []
                    for i in items:
                        parts.append(f"[{i.type}] {i.name} @ {i.loc}")
                        if i.detail:
                            parts.append(str(i.detail))
                        parts.append("")
                    text = "\n".join(parts).strip() if items else "No loader errors."
                elif what == "warnings":
                    items = dx.warnings()
                    text = "\n".join(str(i) for i in items) if items else "No warnings."
                elif what == "danglings":
                    items = dx.danglings()
                    text = "\n".join(str(i) for i in items) if items else "No danglings."
                elif what == "ok":
                    ok_items = [i for i in dx._items if i.category not in ("issue", "loader")]
                    text = "\n".join(str(i) for i in ok_items) if ok_items else "All items have issues."
                elif what == "stats":
                    import json as _json

                    text = _json.dumps(dx.stats(), indent=2)
                else:
                    text = dx.summary()
                return {"ok": True, "text": str(text)}

            elif action == "dissect":
                h = self.bench.dissect(cmd["name"])
                h = self._apply_bias(h, cmd.get("bias", "neutral"))
                self._register_hologram_scope(h)
                text = h.view()
                return {"ok": True, "text": str(text)}

            elif action == "compose":
                names = cmd.get("names", [])
                h = self.bench.compose(*names)
                h = self._apply_bias(h, cmd.get("bias", "neutral"))
                self._register_hologram_scope(h)
                text = h.view()
                return {"ok": True, "text": str(text)}

            elif action == "stain":
                names = cmd.get("names", [])
                h = self.bench.stain(*names)
                h = self._apply_bias(h, cmd.get("bias", "neutral"))
                self._register_hologram_scope(h)
                text = h.view()
                return {"ok": True, "text": str(text)}

            elif action == "search":
                limit = cmd.get("limit", 20)
                offset = cmd.get("offset", 0)
                query = cmd.get("query", "")
                query, sexp_warn = _validate_sexp(query)
                search_warn = _validate_search_query(query)

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

                # Group results by document, preserving first-seen order
                from collections import OrderedDict

                by_doc: OrderedDict[str, list[dict]] = OrderedDict()
                for r in search_result.get("lines", []):
                    by_doc.setdefault(r["document"], []).append(r)

                out_lines: list[str] = []
                for doc, entries in by_doc.items():
                    if out_lines:
                        out_lines.append("")
                    out_lines.append(doc)
                    prev_line = None
                    for r in entries:
                        line_no = r["line"]
                        if prev_line and line_no - prev_line > 1:
                            out_lines.append("")
                        callers = ", ".join(c["name"] for c in r.get("callers", []))
                        prefix = f"[{callers}] " if callers else ""
                        out_lines.append(f"  {line_no:<6} {prefix}{r['context']}")
                        prev_line = line_no
                total = search_result.get("total_lines", 0)
                shown = sum(len(v) for v in by_doc.values())
                page = offset // limit + 1 if limit else 1
                pages = (total + limit - 1) // limit if limit else 1
                out_lines.append("")
                if total > limit:
                    out_lines.append(f"({offset + 1}-{offset + shown}/{total} results, page {page}/{pages})")
                else:
                    out_lines.append(f"({total} results)")
                if sexp_warn:
                    out_lines.insert(0, f"⚠ {sexp_warn}")
                if search_warn:
                    out_lines.insert(0, f"⚠ {search_warn}")
                    out_lines.insert(1, "")
                return {"ok": True, "results": out_lines}

            elif action == "index":
                # Handled separately via dispatch_stream
                return {"ok": False, "error": "use dispatch_stream for index"}

            elif action == "clean":
                self.bench.clean()
                return {"ok": True, "text": "Eval system reset."}

            elif action == "history":
                return self._dispatch_history(cmd)

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
                force = cmd.get("force", False)

                def _progress(count, total, rel):
                    _send(conn, {"progress": True, "count": count, "total": total, "file": rel})

                exclude = cmd.get("exclude")
                count = self.bench.index.index_dir(
                    directory,
                    extensions,
                    exclude=exclude,
                    on_progress=_progress,
                    force=force,
                )
                total = len(self.bench.index._index.documents)
                msg = f"Indexed {count} new files from {directory} ({total} total)"
                _send(conn, {"ok": True, "done": True, "text": msg})

            elif action == "reindex":
                force = cmd.get("force", False)

                def _progress(count, total, rel):
                    _send(conn, {"progress": True, "count": count, "total": total, "file": rel})

                count = self.bench.index.reindex(on_progress=_progress, force=force)
                _send(conn, {"ok": True, "done": True, "text": f"Reindexed {count} files"})
        except Exception:
            _send(conn, {"ok": False, "done": True, "error": traceback.format_exc()})

    def _dispatch_history(self, cmd: dict) -> dict:
        """Handle history sub-commands."""
        import time as _time

        store = self.bench._store
        path = self.bench._current_path
        if not path:
            return {"ok": False, "error": "No project loaded"}
        h = store.history(path)
        sub = cmd.get("sub", "layers")

        if sub == "layers":
            infos = h.layers()
            if not infos:
                return {"ok": True, "text": f"No layers. Total commits: {h.total_commits}"}
            lines = [f"Layers: {len(infos)}  Total commits: {h.total_commits}"]
            for li in infos:
                ts = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(li.timestamp))
                lines.append(
                    f"  [{li.index}] {ts}  files={li.file_count}  "
                    f"+{li.keys_added} ~{li.keys_modified} -{li.keys_deleted}  "
                    f"({li.disk_bytes:,}B)"
                )
            return {"ok": True, "text": "\n".join(lines)}

        elif sub == "files":
            layer = cmd.get("layer")
            state = h.at(layer) if layer is not None else h.current()
            lines = [f"Files ({len(state)}):"]
            for name in sorted(state):
                lines.append(f"  {name} ({len(state[name]):,} chars)")
            return {"ok": True, "text": "\n".join(lines)}

        elif sub == "file":
            name = cmd.get("name")  # type: ignore[assignment]
            if not name:
                return {"ok": False, "error": "Missing file name"}
            layer = cmd.get("layer")
            text = h.file_at(name, layer) if layer is not None else h.current().get(name)
            if text is None:
                return {"ok": True, "text": f"File '{name}' not found at layer {layer}"}
            return {"ok": True, "text": text}

        elif sub == "diff":
            fr = cmd.get("from_layer", 0)
            to = cmd.get("to_layer")
            if to is None:
                to = h.layer_count() - 1
            d = h.diff(fr, to)
            lines = [f"Diff layer {fr} → {to}: +{len(d.added)} ~{len(d.modified)} -{len(d.deleted)}"]
            for name in sorted(d.added):
                lines.append(f"  + {name}")
            for name in sorted(d.modified):
                lines.append(f"  ~ {name}")
            for name in sorted(d.deleted):
                lines.append(f"  - {name}")
            return {"ok": True, "text": "\n".join(lines)}

        elif sub == "diff_file":
            name = cmd.get("name")  # type: ignore[assignment]
            if not name:
                return {"ok": False, "error": "Missing file name"}
            fr = cmd.get("from_layer", 0)
            to = cmd.get("to_layer")
            if to is None:
                to = h.layer_count() - 1
            fd = h.diff_file(name, fr, to)
            if fd.status == "unchanged":
                return {"ok": True, "text": f"[unchanged] {fd.name}"}
            if fd.old_text is None and fd.new_text is not None:
                return {"ok": True, "text": f"[added] {fd.name}\n" + fd.new_text}
            if fd.old_text is not None and fd.new_text is None:
                return {"ok": True, "text": f"[deleted] {fd.name}"}
            import difflib

            diff_lines = difflib.unified_diff(
                (fd.old_text or "").splitlines(keepends=True),
                (fd.new_text or "").splitlines(keepends=True),
                fromfile=f"{fd.name} (layer {fr})",
                tofile=f"{fd.name} (layer {to})",
            )
            return {"ok": True, "text": "".join(diff_lines) or f"[{fd.status}] {fd.name}"}

        elif sub == "restore":
            layer = cmd.get("layer")
            if layer is None:
                return {"ok": False, "error": "Missing layer number"}
            h.restore(layer)
            return {"ok": True, "text": f"Restored to layer {layer}"}

        elif sub == "restore_file":
            name = cmd.get("name")  # type: ignore[assignment]
            layer = cmd.get("layer")
            if not name or layer is None:
                return {"ok": False, "error": "Missing file name or layer number"}
            h.restore_file(name, layer)
            return {"ok": True, "text": f"Restored '{name}' to layer {layer}"}

        elif sub == "compact":
            if not cmd.get("confirm"):
                return {"ok": False, "error": "Compact squashes all layers into one. Pass --yes to confirm."}
            h.compact()
            return {"ok": True, "text": "Compacted to single base layer."}

        else:
            return {"ok": False, "error": f"Unknown history sub-command: {sub!r}"}


def _validate_sexp(query: str) -> tuple[str, str | None]:
    """Validate and auto-fix S-expression syntax.

    Returns (corrected_query, warning).
    warning is None if no fixes were needed.
    Auto-fixes: stray shell quotes, unclosed parens, trailing extra parens.
    Shows roundtrip on fix so user sees what was actually parsed.
    """
    from parseltongue.core.grammar import read_tokens, to_sexp, tokenize

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


def _validate_search_query(query: str) -> str | None:
    """Check if query normalization changes string literals in ways the user should know about.

    Works for both plain text queries and string arguments inside s-expressions.
    Returns a warning if normalization alters any search term, None otherwise.
    """
    import re as _re

    from parseltongue.core.quote_verifier.config import QuoteVerifierConfig
    from parseltongue.core.quote_verifier.normalizer import normalize_with_mapping

    q = query.strip()
    if not q:
        return None

    config = QuoteVerifierConfig(remove_stopwords=True)

    # Extract string literals to check: plain text or quoted strings in s-exprs
    if q.startswith("("):
        literals = _re.findall(r'"([^"]*)"', q)
    else:
        literals = [q]

    warnings = []
    for lit in literals:
        if not lit:
            continue
        normalized, _, _ = normalize_with_mapping(lit, config)
        tokens = normalized.split()
        if not tokens:
            warnings.append(f'"{lit}" → empty (all stopwords?)')
        else:
            rejoined = " ".join(tokens)
            if rejoined != lit.lower():
                warnings.append(f'"{lit}" → "{rejoined}"')

    if not warnings:
        return None
    return "Normalized: " + ", ".join(warnings) + ' — use (re "...") for exact match'


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
    "dx": "bench_pg.screen.dx",
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
        return bench.eval_system.engine.evaluate([Symbol("fmt"), perspective, result])
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
    if name == "viz":
        from parseltongue.core.inspect.perspectives.viz import VizRenderer as VizPerspective

        lens = bench.lens()
        loader = lens._loader
        loc_fn = None
        if loader:
            index = {node.name: node for node in loader.ast if node.name}

            def loc_fn(name):
                dn = index.get(name)
                if not dn:
                    return ""
                parts = []
                if dn.source_file:
                    parts.append(os.path.relpath(dn.source_file))
                if dn.source_line:
                    parts.append(str(dn.source_line))
                return ":".join(parts)

        store = getattr(bench, "_store", None)
        merkle_root = getattr(bench, "_merkle_root", "")
        return VizPerspective(loc_fn=loc_fn, store=store, merkle_root=merkle_root)
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
        lines: list[str] = []
        sorted_keys = sorted(
            result.keys(),
            key=lambda k: (k[0], k[1]) if isinstance(k, tuple) else (str(k), 0),
        )
        prev_doc = None
        for i, key in enumerate(sorted_keys[:50], 1):
            entry = result[key]
            if isinstance(entry, dict) and "context" in entry:
                callers = entry.get("callers", [])
                prefix = f"[{', '.join(c['name'] for c in callers)}] " if callers else ""
                doc = entry["document"]
                ln = entry["line"]
                if doc != prev_doc:
                    if lines:
                        lines.append("")
                    lines.append(doc)
                    prev_doc = doc
                lines.append(f"  {ln:<6} {prefix}{entry['context']}")
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
    from parseltongue.core.grammar import to_sexp

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
    """Add a rotating file handler to .parseltongue-bench/bench.log.

    Rotates at 100 MB, keeps 3 backups (bench.log.1, .2, .3).
    """
    from logging.handlers import RotatingFileHandler

    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    log_path = BENCH_DIR / "bench.log"
    root = logging.getLogger("parseltongue")
    file_level = getattr(logging, console_level.upper(), logging.INFO)
    # File: same level as console (default INFO), rotating at 100 MB
    fh = RotatingFileHandler(
        log_path,
        maxBytes=100 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    fh.setLevel(file_level)
    root.addHandler(fh)
    # Console: same level
    sh = logging.StreamHandler()
    sh.setLevel(file_level)
    root.addHandler(sh)
    # Root matches lowest handler level
    root.setLevel(file_level)


def _run_server(
    pltg_path: str, sock_path: Path, refresh_s: int = 0, log_level: str = "ERROR", effects: dict | None = None
):
    _setup_file_logging(log_level)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    # Socket first — queryable immediately (ping/status work while loading)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(sock_path))
    sock.listen(4)

    server = BenchServer(pltg_path, background=True, effects=effects)
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
    LLM AGENTS — learn kung-fu:
      pg-bench learn kung-fu           # full skill reference
      This is the one skill an LLM should acquire before using pg-bench.

    \b
    eval and interpret are the primary interface. eval is pure (clean
    copy each time), interpret accumulates state (clean resets it).
    Both accept S-expressions with the full std library, scopes (lens,
    screen, ops, search, hologram), and fmt for formatted output.

    \b
    EVALUATE (pure — clean copy, never mutated):
      pg-bench '(+ 1 2)'                          => 3
      pg-bench eval '(scope lens (find "engine"))'
      pg-bench eval '(fmt "viz" (scope lens (kind "fact")))' > out.html
      pg-bench eval --help                         # full operator reference

    \b
    INTERPRET (stateful — accumulates across calls):
      pg-bench interpret '(defterm my-val 42 :origin "test")'
      pg-bench interpret '(fact check true :evidence ("f.py" :quotes ("x")))'
      pg-bench interpret -f setup.pltg
      pg-bench clean                               # reset interpret scope
      pg-bench interpret --help                    # details

    \b
    SEARCH (S-expression query language — see search --help):
      pg-bench search "raise ValueError"
      pg-bench search '(in "engine.py" "raise")'
      pg-bench search '(and "import" "quote")'
      pg-bench search '(not-in "engine.py" "raise")'
      pg-bench search '(scope lens (find "engine"))'
      pg-bench search '(scope screen (issues))'
      pg-bench search '(count (in "engine.py" "raise"))'

    \b
    LENS (structural navigation — see find/view/subgraph --help):
      pg-bench find "error"           pg-bench fuzzy "eval"
      pg-bench find "error" --scope screen
      pg-bench view engine.eval-bind  pg-bench view
      pg-bench focus "engine."        pg-bench kinds
      pg-bench consumer engine.derive pg-bench inputs engine.derive
      pg-bench subgraph engine.derive [-d downstream|both]
      pg-bench roots

    \b
    HOLOGRAM (multi-lens, requires live — see dissect/compose/stain --help):
      pg-bench dissect atoms.theorem-derivation-sources [--bias divergence]
      pg-bench compose engine.eval-bind engine.derive [--bias left]
      pg-bench stain all-contract-facts-ok all-product-facts-ok

    \b
    SCREEN (alias: diagnose — see screen --help):
      pg-bench screen [--what issues|warnings|danglings|ok|stats]
      pg-bench screen [--focus "engine."]

    \b
    VIZ — interactive HTML visualization (pipe to file, open in browser):
      pg-bench eval '(fmt "viz" (scope lens (kind "fact")))' > viz.html
      pg-bench eval '(fmt "viz" (scope lens (focus "engine.")))' > eng.html
      pg-bench eval '(fmt "viz" (scope screen (issues)))' > issues.html
      pg-bench eval '(fmt "viz" (scope hologram (divergent)))' > holo.html
      Renders any scope result as self-contained HTML with cards, layers,
      D3 graph, search, kind filters, and evidence panel. Cached on disk.

    \b
    HISTORY (time travel over indexed states — see history --help):
      pg-bench history layers          pg-bench history files
      pg-bench history diff            pg-bench history diff-file NAME
      pg-bench history restore LAYER   pg-bench history compact --yes

    \b
    OPERATIONS (see serve/index/status --help):
      pg-bench serve file.pltg     # foreground (blocking)
      pg-bench start file.pltg     # daemonized (returns immediately)
      pg-bench up file.pltg        # foreground; pg-bench up -d to detach
      pg-bench wait                # block until ready
      pg-bench index parseltongue/core
      pg-bench ping   pg-bench status   pg-bench reload   pg-bench purge

    \b
    See advanced usage patterns in parseltongue/core/demos/ and
    parseltongue/llm/demos/ — governance pipelines, spec validation,
    revenue reports, all driven by eval/interpret + scopes + fmt.

    \b
    LLM AGENTS — learn kung-fu:
      pg-bench learn kung-fu           # full skill reference
      This is the one skill an LLM should acquire before using pg-bench.
    """


def _import_effects(spec: str) -> dict:
    """Import effects dict from 'module:attr' spec, e.g.
    'parseltongue.core.demos.data_governance_pltg.operators:GOVERNANCE_EFFECTS'."""
    import importlib

    if ":" not in spec:
        raise click.BadParameter(f"Effects spec must be 'module:attr', got: {spec}")
    mod_path, attr = spec.rsplit(":", 1)
    mod = importlib.import_module(mod_path)
    obj = getattr(mod, attr)
    if not isinstance(obj, dict):
        raise click.BadParameter(f"{spec} resolved to {type(obj).__name__}, expected dict")
    return obj


_LIFECYCLE_HELP = (
    "Lifecycle: the server loads a frozen cache immediately (~20ms) so queries\n"
    "work right away, then computes a live evaluation in a background thread.\n"
    "Use 'pg-bench status' to check whether the bench is frozen or live."
)

_INDEX_HELP = (
    "After startup, index source files so search works:\n"
    "  pg-bench index <directory>\n\n"
    "Place a .pgignore in the indexed directory to exclude paths (same syntax\n"
    "as .gitignore). Default ignores: .git, .*, node_modules."
)

_VARIANTS_HELP = (
    "Start variants:\n"
    "  pg-bench serve file.pltg     foreground (blocking)\n"
    "  pg-bench start file.pltg     daemonized (returns immediately)\n"
    "  pg-bench up file.pltg        foreground; pg-bench up -d to detach"
)


def _serve_doc(*sections: str):
    """Decorator: build help text from shared sections."""

    def decorator(fn):
        base = (fn.__doc__ or "").rstrip()
        for s in sections:
            base += "\n\n    \b\n    " + s.replace("\n", "\n    ")
        fn.__doc__ = base
        return fn

    return decorator


def _serve_options(fn):
    """Shared options for serve/start/up commands."""
    fn = click.argument("path")(fn)
    fn = click.option("--socket", "sock", default=str(SOCK_PATH), help="Unix socket path.")(fn)
    fn = click.option(
        "--refresh-index", "refresh_s", default=2, type=int, help="Background reindex interval in seconds (0=off)."
    )(fn)
    fn = click.option(
        "--effects",
        "effects_spec",
        default=None,
        help="Effects dict as 'module:attr', e.g. 'mypackage.ops:EFFECTS'.",
    )(fn)
    fn = click.option("--verbose", "-v", is_flag=False, help="Shorthand for --log-level INFO.")(fn)
    fn = click.option(
        "--log-level",
        default="ERROR",
        type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
        help="Log level (default: ERROR).",
    )(fn)
    return fn


def _resolve_log_level(verbose: bool, log_level: str) -> str:
    if verbose and log_level != "ERROR":
        raise click.UsageError("Cannot use --verbose and --log-level together.")
    return "INFO" if verbose else log_level


def _daemonize(path: str, sock: str, refresh_s: int, log_level: str, effects: dict | None = None):
    """Double-fork daemonize, then exec _run_server in the grandchild."""
    pid = os.fork()
    if pid > 0:
        click.echo(f"Daemon launching for {path} (pid {pid})")
        return

    os.setsid()

    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # Grandchild — redirect stdio, run server
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    _run_server(path, Path(sock), refresh_s=refresh_s, log_level=log_level, effects=effects)
    os._exit(0)


@cli.command()
@_serve_options
@_serve_doc(_LIFECYCLE_HELP, _INDEX_HELP, _VARIANTS_HELP)
def serve(path: str, sock: str, refresh_s: int, effects_spec: str | None, verbose: bool, log_level: str):
    """Start the bench server in the foreground (blocking)."""
    effects = _import_effects(effects_spec) if effects_spec else None
    _run_server(
        path, Path(sock), refresh_s=refresh_s, log_level=_resolve_log_level(verbose, log_level), effects=effects
    )


@cli.command()
@_serve_options
@_serve_doc(_LIFECYCLE_HELP, _INDEX_HELP, _VARIANTS_HELP)
def start(path: str, sock: str, refresh_s: int, effects_spec: str | None, verbose: bool, log_level: str):
    """Start the bench server as a daemon (returns immediately).

    \b
    Double-fork daemonization — the server survives terminal close.
    """
    effects = _import_effects(effects_spec) if effects_spec else None
    _daemonize(path, sock, refresh_s, _resolve_log_level(verbose, log_level), effects=effects)


@cli.command()
@_serve_options
@click.option("-d", "--detach", is_flag=True, help="Detach — run as daemon (like start).")
@_serve_doc(_LIFECYCLE_HELP, _INDEX_HELP)
def up(path: str, sock: str, refresh_s: int, effects_spec: str | None, verbose: bool, log_level: str, detach: bool):
    """Start the bench server. Foreground by default, -d to detach.

    \b
    Combines serve and start:
      pg-bench up file.pltg      foreground (blocking)
      pg-bench up -d file.pltg   detached daemon
    """
    level = _resolve_log_level(verbose, log_level)
    effects = _import_effects(effects_spec) if effects_spec else None
    if detach:
        _daemonize(path, sock, refresh_s, level, effects=effects)
    else:
        _run_server(path, Path(sock), refresh_s=refresh_s, log_level=level, effects=effects)


def _read_expression(expression: str | None, file: str | None) -> str:
    """Resolve expression from arg, -f file, or stdin pipe."""
    if file:
        return Path(file).read_text()
    if expression:
        return expression
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise click.UsageError("No expression provided. Pass as argument, use -f FILE, or pipe via stdin.")


@cli.command("eval")
@click.argument("expression", required=False)
@click.option("-f", "--file", "file", default=None, help="Read expression from file.")
@click.option("--raw", is_flag=True, help="Output raw S-expression (to_sexp).")
@click.option("--profile", is_flag=True, help="Profile server-side and save to .parseltongue-bench/.")
def eval_cmd(expression: str | None, file: str | None, raw: bool, profile: bool):
    """Evaluate an S-expression in the bench engine (main + std + scopes).

    \b
    Pure evaluation — uses a clean copy of the loaded system. Never
    polluted by interpret. Pipe output to files for viz or further processing.

    \b
    Expression can be provided as argument, from a file (-f), or piped via stdin:
      pg-bench eval '(+ 1 2)'
      pg-bench eval -f script.pltg
      echo '(+ 1 2)' | pg-bench eval
      pg-bench eval '(fmt "viz" (scope lens (kind "fact")))' > out.html

    \b
    Combines the loaded .pltg system, the full std library, and registered
    scopes (lens, screen, ops, search, hologram). Module aliases resolve
    automatically: counting.X, epistemics.Y, lists.Z work without std.
    Built-in arithmetic (+, -, *, /, mod), comparison (>, <, >=, <=, =,
    !=), logic (and, or, not, implies), conditionals (if), bindings (let),
    and quoting (quote) are always available.

    \b
    FMT — format bench forms for display:
      (fmt "perspective" expr) rewrites tagged bench forms (sr, ln, dx, hn)
      into display forms. Perspectives come from view.pltg axioms.
        (fmt "md" (scope lens (kind "fact")))        markdown output
        (fmt "viz" (scope lens (focus "engine.")))   HTML visualization
        (fmt "viz" (scope hologram (divergent)))      hologram viz

    \b
    SCOPES — cross-system evaluation:
      Use (scope name expr) to evaluate in a registered scope.

    \b
      Lens scope — structural navigation over the pltg graph:
        (scope lens (kind "fact"))        all fact nodes as posting set
        (scope lens (kind "diff"))        all diff nodes
        (scope lens (inputs "name"))      upstream deps of a node
        (scope lens (downstream "name"))  what depends on it
        (scope lens (roots))              root nodes (depth 0, no inputs)
        (scope lens (layer 2))            all nodes at depth 2
        (scope lens (focus "engine."))    filter to namespace prefix
        (scope lens (node "name"))        single node posting set
        (scope lens (depth "name"))       depth as int
        (scope lens (value "name"))       node value as string
        (scope lens (terms "axiom"))      list of names matching kind
        (scope lens (quotes "name"))      list of quote strings
        (scope lens (atom "name"))        atom as pltg tagged list
        (scope lens (find "pattern"))     regex search (posting set)
        (scope lens (fuzzy "query"))      ranked substring (posting set)

    \b
      Screen scope — consistency results (alias: diagnose, evaluation):
        (scope screen (issues))           all failing diffs
        (scope screen (warnings))         all warnings
        (scope screen (danglings))        all dangling definitions
        (scope screen (loader))           loader issues
        (scope screen (kind "diff"))      items by directive kind
        (scope screen (category "issue"))      by category
        (scope screen (type "diverge"))        by issue type substring
        (scope screen (focus "engine."))       filter to namespace
        (scope screen (consistent))            true if no issues
        (scope screen (ns))                    all top-level namespaces
        (scope screen (find "pattern"))        regex search (posting set)
        (scope screen (fuzzy "query"))         ranked substring (posting set)

    \b
      Ops scope — fast set operations over tagged form lists:
        (scope ops (and-forms L1 L2))     intersection by identity key
        (scope ops (or-forms L1 L2))      union
        (scope ops (not-forms L1 L2))     difference
        (scope ops (count-forms L))       count forms
        (scope ops (limit-forms N L))     first N forms
        (scope ops (str form))            form to string
        (scope ops (list a b c))          build list
        Dispatches by tag to registered subsystem morphisms.
        Falls through to pltg engine for unknown operations.

    \b
      Count — posting set size:
        (count (scope lens (kind "fact")))       how many facts
        (count (scope screen (issues)))          how many issues

    \b
    PROJECT — resolve in parent before crossing scope boundary:
      (scope lens (focus (project engine-prefix)))
        Evaluates engine-prefix in the bench engine first, passes the
        concrete value to the lens scope. Without project, the lens
        scope would try to resolve engine-prefix itself.
      (scope screen (focus (project (if use-engine "engine." "atoms."))))
        Conditional resolution: the if-expression evaluates in the parent
        engine, the result string crosses into the screen scope.

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
        (in "engine" "raise")               bare name → auto-glob *engine*
        (not-in "engine.py" "raise")        inverse of in

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
      Ranking and strategy:
        (rank "callers" query)              rank by caller count
        (rank "coverage" query)             rank by overlap
        (rank "document" query)             group by document
        (rank "line" query)                 sort by doc:line
        (strategy "stemmed" query)          explicit strategy selection

    \b
      Count and output:
        (count query)                       posting set cardinality
        (results query)                     convert to sr forms
        (limit N query)                     first N entries

    \b
      Scope — delegate to a registered system:
        (scope lens (kind "fact"))          evaluate in the lens system
        (scope screen (issues))            evaluate in screen system
        (scope hologram (divergent))        evaluate in hologram system
        (scope ops (and-forms L1 L2))       evaluate in ops system

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
      Hologram scope also supports inline dissect/compose/stain:
        (scope hologram (dissect "diff-name"))     create hologram from diff
        (scope hologram (compose name1 name2))     compose from names
        (scope hologram (dissect (stain "name")))  stain marks for live probe

    \b
    COMPOSITION EXAMPLES:

    \b
      (count (scope screen (focus "engine." (issues))))
      (scope lens (terms "axiom"))
      (scope lens (quotes "engine.derive"))
      (fmt "viz" (scope lens (focus "engine.")))

    \b
      (let ((total (count (scope lens (kind "diff"))))
            (bad   (count (scope screen (issues)))))
        (> total (* 2 bad)))

    \b
      (if (= (epistemics.joint-status s1 s2 s3) epistemics.hallucinated)
        "contaminated" "clean")

    \b
      (let ((raises (count (in "engine.py" (near "def" "raise" 10))))
            (total  (count (in "engine.py" (re "def \\w+")))))
        (> raises (* total 0.3)))
    """
    expr = _read_expression(expression, file)
    _print_result(_query({"action": "eval", "query": expr, "raw": raw, "profile": profile}))


@cli.command("interpret")
@click.argument("expression", required=False)
@click.option("-f", "--file", "file", default=None, help="Read expression from file.")
@click.option("--raw", is_flag=True, help="Output raw S-expression (to_sexp).")
def interpret_cmd(expression: str | None, file: str | None, raw: bool):
    """Interpret a directive or expression in the bench engine.

    \b
    Like eval, but also accepts directives (defterm, fact, axiom, derive).
    State accumulates across calls — defined terms persist in the interpret
    scope until 'pg-bench clean' resets it. Does not affect the main
    loaded system or the eval scope.

    \b
    Expression can be provided as argument, from a file (-f), or piped via stdin:
      pg-bench interpret '(defterm my-val 42 :origin "test")'
      pg-bench interpret -f setup.pltg
      cat setup.pltg | pg-bench interpret

    \b
    Examples:
      pg-bench interpret '(defterm or-test (lists.concat (strict ?a) (strict ?b)))'
      pg-bench interpret '(fact my-val 42 :origin "test")'
      pg-bench clean   # reset interpret scope
    """
    expr = _read_expression(expression, file)
    _print_result(_query({"action": "interpret", "query": expr, "raw": raw}))


@cli.command()
@click.argument("pattern")
@click.option("--max", "max_results", default=50, help="Max results.")
@click.option("--scope", default="all", type=click.Choice(["all", "lens", "screen"]), help="Search scope.")
def find(pattern: str, max_results: int, scope: str):
    """Regex search over pltg names — lens graph + screen items.

    \b
    Returns matching names with kind/category and source file:line.
    By default searches both lens (structure) and screen (consistency).
    Use --scope to narrow: lens for definitions, screen for issues/danglings.

    \b
    Examples:
      pg-bench find "engine"                # all names containing "engine"
      pg-bench find "^engine\\."             # names starting with "engine."
      pg-bench find "count.*exist"          # count-exists variants
      pg-bench find "diverge" --scope screen # only screen items
    """
    _print_result(_query({"action": "find", "pattern": pattern, "max": max_results, "scope": scope}))


@cli.command()
@click.argument("query")
@click.option("--max", "max_results", default=10, help="Max results.")
@click.option("--scope", default="all", type=click.Choice(["all", "lens", "screen"]), help="Search scope.")
def fuzzy(query: str, max_results: int, scope: str):
    """Ranked substring search over pltg names — lens graph + screen items.

    \b
    Scores by match quality: exact > suffix > prefix > infix.
    Returns names with kind/category and source file:line.
    By default searches both lens and screen. Use --scope to narrow.

    \b
    Examples:
      pg-bench fuzzy "eval"                   # across lens + screen
      pg-bench fuzzy "diverge" --scope screen # only screen items
    """
    _print_result(_query({"action": "fuzzy", "query": query, "max": max_results, "scope": scope}))


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
    """View all node kinds with counts. Diffs not yet traversed by the lens."""
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


def _screen_impl(focus_name: str | None, what: str):
    """Shared implementation for screen/diagnose commands."""
    cmd = {"action": "screen", "what": what}
    if focus_name:
        cmd["focus"] = focus_name
    _print_result(_query(cmd))


_screen_opts = [
    click.option("--focus", "focus_name", default=None, help="Focus on a subsystem prefix."),
    click.option(
        "--what",
        default="summary",
        type=click.Choice(["summary", "issues", "warnings", "danglings", "loader", "ok", "stats"]),
    ),
]


@cli.command()
@_screen_opts[0]
@_screen_opts[1]
def screen(focus_name: str | None, what: str):
    """Run consistency screening (Merkle-cached).

    \b
    Screens all diffs in the loaded .pltg and reports divergences.
    Cached — same Merkle root = same screening. Incremental when
    only some files change.

    \b
    --what summary    counts by category and type, grouped by kind (default)
    --what issues     only failing diffs with values
    --what warnings   only warnings (unverified evidence, manual verification)
    --what danglings  only dangling definitions (consumed by nothing)
    --what loader     only loader errors (unresolved symbols, failed effects)
    --what ok         passing items (warnings + danglings, excludes issues/loader)
    --what stats      JSON breakdown by category, type, kind, namespace, file
    --focus           filter to a namespace prefix
    """
    _screen_impl(focus_name, what)


@cli.command(deprecated=True)
@_screen_opts[0]
@_screen_opts[1]
def diagnose(focus_name: str | None, what: str):
    """Run consistency screening (alias for 'screen')."""
    _screen_impl(focus_name, what)


_BIAS_CHOICES = ["neutral", "left", "right", "divergence"]

_BIAS_HELP = (
    "Biases control how lens outputs are combined in the view:\n"
    "  neutral     — show all lenses side by side (default)\n"
    "  left        — left lens primary, others indented\n"
    "  right       — right lens primary, others indented\n"
    "  divergence  — only show nodes that differ; skip identical\n\n"
    "The hologram scope in the search system (scope hologram ...)\n"
    "has analogous structural operators (divergent, common, only N)\n"
    "that work at the posting-set level rather than the view level."
)


@cli.command()
@click.argument("name")
@click.option("--bias", type=click.Choice(_BIAS_CHOICES), default="neutral", help="View combination bias.")
def dissect(name: str, bias: str):
    """Dissect a diff into a side-by-side hologram.

    \b
    Creates two lenses — one for :replace, one for :with — showing the
    full probe structure of each side. The hologram is registered as a
    search scope so you can query it via (scope hologram ...).

    \b
    Requires live evaluation (forces full load if still frozen).

    \b
    Biases control how lens outputs are combined in the view:
      neutral     — show all lenses side by side (default)
      left        — left lens primary, others indented
      right       — right lens primary, others indented
      divergence  — only show nodes that differ; skip identical

    \b
    The hologram scope in the search system (scope hologram ...)
    has analogous structural operators (divergent, common, only N)
    that work at the posting-set level rather than the view level.
    """
    _print_result(_query({"action": "dissect", "name": name, "bias": bias}))


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.option("--bias", type=click.Choice(_BIAS_CHOICES), default="neutral", help="View combination bias.")
def compose(names: tuple[str, ...], bias: str):
    """Compose N system names into a hologram — one lens per name.

    \b
    Each name gets its own probe structure displayed in parallel.
    Useful for comparing how different subsystems relate.

    \b
    Requires live evaluation (forces full load if still frozen).

    \b
    Biases control how lens outputs are combined in the view:
      neutral     — show all lenses side by side (default)
      left        — left lens primary, others indented
      right       — right lens primary, others indented
      divergence  — only show nodes that differ; skip identical

    \b
    The hologram scope in the search system (scope hologram ...)
    has analogous structural operators (divergent, common, only N)
    that work at the posting-set level rather than the view level.

    \b
    Example:
      pg-bench compose engine.eval-bind engine.derive engine._rewrite
      pg-bench compose engine.eval-bind engine.derive --bias divergence
    """
    _print_result(_query({"action": "compose", "names": list(names), "bias": bias}))


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.option("--bias", type=click.Choice(_BIAS_CHOICES), default="neutral", help="View combination bias.")
def stain(names: tuple[str, ...], bias: str):
    """Trace evaluation of N terms at execution time — one lens per name.

    \b
    Unlike compose (static probe), stain is a direct tracer: it
    re-evaluates each term's theorem WFF under trace, capturing the
    actual resolution edges at the moment of execution. This resolves
    dynamic terms whose dependencies may have changed since load.

    \b
    Shows runtime dependencies invisible to static probing.

    \b
    Requires live evaluation (forces full load if still frozen).

    \b
    Biases control how lens outputs are combined in the view:
      neutral     — show all lenses side by side (default)
      left        — left lens primary, others indented
      right       — right lens primary, others indented
      divergence  — only show nodes that differ; skip identical

    \b
    The hologram scope in the search system (scope hologram ...)
    has analogous structural operators (divergent, common, only N)
    that work at the posting-set level rather than the view level.

    \b
    Example:
      pg-bench stain all-contract-facts-ok all-product-facts-ok
    """
    _print_result(_query({"action": "stain", "names": list(names), "bias": bias}))


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
      (not-in "engine.py" "raise")             inverse of in
      (near "raise" "ValueError" 3)            proximity within N lines
      (seq "def derive" "raise")               a before b in same doc
      (re "raise (ValueError|NameError)")      regex
      (lines 400 500 query)                    line range filter

    \b
    (in ...) supports exact match, suffix match, and globs:
      (in "engine.py" ...)       exact or suffix match
      (in "tests/*" ...)         glob pattern
      (in "engine" ...)          bare name → auto-glob *engine*

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
      (strategy "stemmed" query)               explicit strategy selection
      (count query)                            integer count
      (results query)                          convert to sr forms
      (limit N query)                          first N entries

    \b
    Scopes — delegate into subsystem query languages:
      (scope lens (find "engine"))             lens structural search
      (scope screen (issues))                  screen diagnostic search
      (scope hologram (divergent))             hologram comparison search
      Registered scopes: lens, screen (aka diagnose, evaluation),
      hologram (after dissect/compose/stain), ops, self.

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
@click.option("--force", is_flag=True, help="Ignore stat/hash caches — full re-read of every file.")
def index_dir(directory: str, extensions: tuple[str, ...], excludes: tuple[str, ...], force: bool):
    """Index all files in DIRECTORY into the search engine.

    \b
    Additive — call multiple times for different directories, all get merged
    into one search index. Reindex re-walks all previously indexed directories.

    \b
    Reads .pgignore from each directory root (gitignore-style patterns).
    Uses stat fingerprinting + Merkle hashing: unchanged files are skipped.
    """
    cmd: dict = {"action": "index", "directory": directory, "extensions": list(extensions)}
    if excludes:
        cmd["exclude"] = list(excludes)
    if force:
        cmd["force"] = True
    for msg in _query_stream(cmd):
        if msg.get("progress"):
            click.echo(f"\r  {msg['count']}/{msg['total']}  {msg['file']}", nl=False)
        elif msg.get("done"):
            click.echo()  # newline after progress
            _print_result(msg)


@cli.command()
@click.option("--force", is_flag=True, help="Ignore stat/hash caches — full re-read of every file.")
def reindex(force: bool):
    """Re-index all previously indexed directories (detects file changes)."""
    cmd: dict = {"action": "reindex"}
    if force:
        cmd["force"] = True
    for msg in _query_stream(cmd):
        if msg.get("progress"):
            click.echo(f"\r  {msg['count']}/{msg['total']}  {msg['file']}", nl=False)
        elif msg.get("done"):
            click.echo()
            _print_result(msg)


@cli.command()
def clean():
    """Recreate the eval system of the bench. Use when interpret -f accumulated state you want to discard."""
    _print_result(_query({"action": "clean"}))


@cli.command()
def reload():
    """Invalidate memory cache and re-prepare the .pltg file.

    \b
    Disk cache (Merkle) is preserved, so re-prepare is fast (~20ms).
    Use 'purge' to clear disk caches too.
    """
    _print_result(_query({"action": "reload"}))


@cli.command()
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def purge(yes: bool):
    """Nuclear — purge all caches (memory + disk) and reload from scratch."""
    if not yes:
        click.confirm("This will destroy all caches and reload. Continue?", abort=True)
    _print_result(_query({"action": "purge"}))


@cli.command()
def status():
    """Show server status: path, status (frozen/live), integrity.

    \b
    When integrity is 'corrupted', also shows loader errors, skipped
    definitions, and warnings.
    """
    _print_result(_query({"action": "status"}))


@cli.command()
def ping():
    """Check if server is running. Returns 'pong' when ready, 'loading' during prepare."""
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


@cli.group()
def history():
    """Time travel over indexed file states.

    \b
    Each 'pg-bench index' commits an immutable delta layer. Layers
    record which files were added, modified, or deleted. Restore
    is non-destructive — it appends a reverse delta, keeping the
    full history intact. Compact squashes all layers into one base.
    """
    pass


@history.command("layers")
def history_layers():
    """Show all layers with metadata."""
    _print_result(_query({"action": "history", "sub": "layers"}))


@history.command("files")
@click.option("--layer", "-l", type=int, default=None, help="Layer number (default: current).")
def history_files(layer: int | None):
    """List files at a layer (default: current state)."""
    _print_result(_query({"action": "history", "sub": "files", "layer": layer}))


@history.command("file")
@click.argument("name")
@click.option("--layer", "-l", type=int, default=None, help="Layer number (default: current).")
def history_file(name: str, layer: int | None):
    """Show file content at a layer."""
    _print_result(_query({"action": "history", "sub": "file", "name": name, "layer": layer}))


@history.command("diff")
@click.option("--from", "from_layer", type=int, default=0, help="From layer (default: 0).")
@click.option("--to", "to_layer", type=int, default=None, help="To layer (default: latest).")
def history_diff(from_layer: int, to_layer: int | None):
    """Diff between two layers."""
    _print_result(_query({"action": "history", "sub": "diff", "from_layer": from_layer, "to_layer": to_layer}))


@history.command("diff-file")
@click.argument("name")
@click.option("--from", "from_layer", type=int, default=0, help="From layer (default: 0).")
@click.option("--to", "to_layer", type=int, default=None, help="To layer (default: latest).")
def history_diff_file(name: str, from_layer: int, to_layer: int | None):
    """Diff a single file between two layers."""
    _print_result(
        _query({"action": "history", "sub": "diff_file", "name": name, "from_layer": from_layer, "to_layer": to_layer})
    )


@history.command("restore")
@click.argument("layer", type=int)
def history_restore(layer: int):
    """Restore full state to a layer (non-destructive — appends reverse delta)."""
    _print_result(_query({"action": "history", "sub": "restore", "layer": layer}))


@history.command("restore-file")
@click.argument("name")
@click.argument("layer", type=int)
def history_restore_file(name: str, layer: int):
    """Restore a single file to its state at a layer."""
    _print_result(_query({"action": "history", "sub": "restore_file", "name": name, "layer": layer}))


@history.command("compact")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def history_compact(yes: bool):
    """Squash all layers into a single base (destructive)."""
    if not yes:
        click.confirm("This will squash all layers into one. Continue?", abort=True)
    _print_result(_query({"action": "history", "sub": "compact", "confirm": True}))


@cli.command("learn")
@click.argument("what", default="kung-fu")
def learn(what: str):
    """I know kung-fu.

    \b
    Usage:
      pg-bench learn kung-fu           # full pg-bench skill for LLM agents
      pg-bench learn kung-fu > pg.md   # save to file
    """
    skills = {"kung-fu": "PG-SKILL.md"}
    filename = skills.get(what)
    if not filename:
        click.echo(f"Unknown skill: {what}. Available: {', '.join(skills)}", err=True)
        raise SystemExit(1)
    skill_path = Path(__file__).parent / "skills" / filename
    if not skill_path.exists():
        click.echo(f"Skill file not found: {skill_path}", err=True)
        raise SystemExit(1)
    click.echo(skill_path.read_text())


if __name__ == "__main__":
    cli()
