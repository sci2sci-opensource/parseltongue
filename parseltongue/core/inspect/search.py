"""Search — full-text search across loaded documents with pltg provenance tracing.

Supports pltg S-expression queries over the inverted index::

    "raise ValueError"                       — literal phrase lookup
    (or "raise ValueError" "raise Syntax")   — union of posting sets
    (and "def derive" "using")               — intersection (same line)
    (not "raise" "test")                     — difference (first minus second)
    (in "engine.py" "raise")                 — restrict to document
    (scope evaluation (kind "diff"))         — evaluate in a registered scope
    (context 3 "raise")                      — matches + 3 lines before/after
    (before 2 "raise")                       — matches + 2 lines before
    (after 2 "raise")                        — matches + 2 lines after

Queries starting with ``(`` are parsed as S-expressions and evaluated
by a SearchSystem whose operators work on posting sets.
Plain strings are literal phrase lookups (backwards compatible).

Scopes: external Systems registered via ``register_scope(name, system)``
define a defterm in the SearchSystem. ``(scope name expr)`` evaluates
``expr`` in that System.  ``unregister_scope(name)`` retracts the term.

Ranking strategies:
    callers   — lines with most pltg nodes quoting them first (default)
    coverage  — lines where query best overlaps a quote range first
    document  — group by document, most hits per document first
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Callable

from .store import SearchStore

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier import DocumentIndex
    from parseltongue.core.system import System


class Ranking(StrEnum):
    CALLERS = "callers"
    COVERAGE = "coverage"
    DOCUMENT = "document"


class SearchSystem:
    """Parseltongue System wired with posting-set operators for search queries.

    Wraps a ``System`` whose env contains ``and``, ``or``, ``not``, ``in``,
    ``count``, ``near``, ``seq``, ``re``, ``lines``, and ``scope``.
    String literals in S-expressions are resolved to posting sets via
    the document index.
    """

    def __init__(self, index: DocumentIndex, collect: Callable):
        from parseltongue.core.atoms import Symbol
        from parseltongue.core.system import System as PltgSystem

        self._index = index
        self._collect = collect
        self._scopes: dict[str, PltgSystem] = {}

        sys = self  # capture

        def _resolve(x):
            if isinstance(x, str):
                return sys._to_posting(x)
            return x

        def _and(*args):
            sets = [_resolve(a) for a in args]
            result = sets[0]
            for s in sets[1:]:
                result = {k: v for k, v in result.items() if k in s}
            return result

        def _or(*args):
            sets = [_resolve(a) for a in args]
            result = dict(sets[0])
            for s in sets[1:]:
                result.update(s)
            return result

        def _not(*args):
            base = _resolve(args[0])
            for a in args[1:]:
                exclude = _resolve(a)
                base = {k: v for k, v in base.items() if k not in exclude}
            return base

        def _in(doc_pattern, query):
            import fnmatch

            posting = _resolve(query)
            if "*" in doc_pattern or "?" in doc_pattern:
                return {k: v for k, v in posting.items() if fnmatch.fnmatch(k[0], doc_pattern)}
            return {k: v for k, v in posting.items() if k[0] == doc_pattern or k[0].endswith("/" + doc_pattern)}

        def _count(*args):
            return len(_resolve(args[0]))

        def _near(a, b, distance=5):
            sa, sb = _resolve(a), _resolve(b)
            n = int(distance) if not isinstance(distance, dict) else 5
            b_by_doc: dict[str, set[int]] = {}
            for doc, line in sb:
                b_by_doc.setdefault(doc, set()).add(line)
            result = {}
            for k, v in sa.items():
                doc, line = k
                b_lines = b_by_doc.get(doc, set())
                if any(abs(line - bl) <= n for bl in b_lines):
                    result[k] = v
            return result

        def _seq(a, b):
            sa, sb = _resolve(a), _resolve(b)
            b_by_doc: dict[str, int] = {}
            for doc, line in sb:
                if doc not in b_by_doc or line > b_by_doc[doc]:
                    b_by_doc[doc] = line
            return {k: v for k, v in sa.items() if k[0] in b_by_doc and k[1] < b_by_doc[k[0]]}

        def _re(pattern):
            import re as _re_mod

            rx = _re_mod.compile(pattern)
            result = {}
            for doc_name, doc in sys._index.documents.items():
                for i, line_text in enumerate(doc.original_text.splitlines(), 1):
                    if rx.search(line_text):
                        key = (doc_name, i)
                        result[key] = {
                            "document": doc_name,
                            "line": i,
                            "column": 1,
                            "context": line_text,
                            "callers": [],
                            "total_callers": 0,
                        }
            return result

        def _lines(start, end, query):
            posting = _resolve(query)
            s, e = int(start), int(end)
            return {k: v for k, v in posting.items() if s <= k[1] <= e}

        def _context_lines(n, query, before=True, after=True):
            """Expand matches to include surrounding lines."""
            posting = _resolve(query)
            n = int(n)
            expanded = dict(posting)
            for (doc, line), _ in posting.items():
                doc_obj = sys._index.documents.get(doc)
                if not doc_obj:
                    continue
                all_lines = doc_obj.original_text.splitlines()
                start = max(0, line - 1 - (n if before else 0))
                end = min(len(all_lines), line + (n if after else 0))
                for i in range(start, end):
                    key = (doc, i + 1)
                    if key not in expanded:
                        expanded[key] = {
                            "document": doc,
                            "line": i + 1,
                            "column": 1,
                            "context": all_lines[i],
                            "callers": [],
                            "total_callers": 0,
                        }
            return expanded

        def _before(n, query):
            return _context_lines(n, query, before=True, after=False)

        def _after(n, query):
            return _context_lines(n, query, before=False, after=True)

        def _context(n, query):
            return _context_lines(n, query, before=True, after=True)

        def _scope(name, *args):
            if name not in sys._scopes:
                raise KeyError(f"Unknown scope: {name!r}. Registered: {list(sys._scopes)}")
            scope_system = sys._scopes[name]
            result = None
            for arg in args:
                if isinstance(arg, list):
                    result = scope_system.evaluate(arg)
                else:
                    result = arg
            return result

        ops = {
            Symbol("and"): _and,
            Symbol("or"): _or,
            Symbol("not"): _not,
            Symbol("in"): _in,
            Symbol("count"): _count,
            Symbol("near"): _near,
            Symbol("seq"): _seq,
            Symbol("re"): _re,
            Symbol("lines"): _lines,
            Symbol("before"): _before,
            Symbol("after"): _after,
            Symbol("context"): _context,
            Symbol("scope"): _scope,
        }

        self._system = PltgSystem(initial_env=ops, docs={}, strict_derive=False)
        self._resolve = _resolve
        # Register self as a scope for recursive composition
        self._scopes["self"] = self._system
        self._system.interpret('(defterm self :origin "search system self-reference")')

    def evaluate(self, query_str: str) -> dict[tuple[str, int], dict]:
        """Parse and evaluate an S-expression query. Returns posting set."""
        from parseltongue.core.atoms import read_tokens, tokenize

        tokens = tokenize(query_str)
        expr = read_tokens(tokens)

        # Parenthesized string literal like ("test") → treat as plain search
        if isinstance(expr, str):
            return self._to_posting(expr)
        if isinstance(expr, list) and len(expr) == 1 and isinstance(expr[0], str):
            return self._to_posting(expr[0])

        result = self._system.evaluate(expr)

        if isinstance(result, (int, float)):
            return {
                ("__result__", 0): {
                    "document": "__result__",
                    "line": 0,
                    "column": 1,
                    "context": str(result),
                    "callers": [],
                    "total_callers": 0,
                }
            }

        if isinstance(result, str):
            return self._to_posting(result)

        if isinstance(result, list):
            merged: dict[tuple[str, int], dict] = {}
            for item in result:
                resolved = self._resolve(item) if isinstance(item, str) else item
                if isinstance(resolved, dict):
                    merged.update(resolved)
            return merged

        return self._resolve(result)

    def register_scope(self, name: str, system: System):
        """Register a scope. Defines a defterm so ``(scope name ...)`` works."""
        self._scopes[name] = system
        self._system.interpret(f'(defterm {name} :origin "scope {name}")')

    def unregister_scope(self, name: str):
        """Unregister a scope. Retracts the term."""
        self._scopes.pop(name, None)
        self._system.retract(name)

    def _to_posting(self, text: str) -> dict[tuple[str, int], dict]:
        lines, _ = self._collect(text, 100_000, 50)
        return {(ln["document"], ln["line"]): ln for ln in lines}


class Search:
    """Full-text search composed with quote provenance.

    Owns its index independently from the quote verifier. Optionally
    backed by a Store for Merkle-cached incremental reindexing.
    Query evaluation is delegated to a SearchSystem.
    """

    def __init__(self, store: SearchStore):
        self._index = store.load_index()
        self._store = store
        self._system = SearchSystem(self._index, self._collect)

    def register_scope(self, name: str, system: System):
        """Register a named scope in the query system."""
        self._system.register_scope(name, system)

    def unregister_scope(self, name: str):
        """Unregister a named scope."""
        self._system.unregister_scope(name)

    def index_dir(
        self,
        directory: str,
        extensions: list[str] | None = None,
        exclude: list[str] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        self._index, count = self._store.index_incremental(self._index, directory, extensions, exclude, on_progress)
        self._system._index = self._index
        return count

    def reindex(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        """Re-read known files, update stale entries, remove deleted."""
        self._index, count = self._store.reindex(self._index, on_progress)
        self._system._index = self._index
        return count

    def query(
        self,
        text: str,
        max_lines: int = 20,
        max_callers: int = 5,
        offset: int = 0,
        rank: Ranking | str = Ranking.CALLERS,
    ) -> dict:
        """Search for text across all documents.

        Returns::

            {
                "total_lines": int,
                "total_callers": int,
                "offset": int,
                "lines": [...]
            }

        Each line: {document, line, column, context, callers, total_callers}.
        ``callers`` is a list of {name, overlap}, capped at max_callers.
        """
        rank = Ranking(rank)

        stripped = text.strip()
        if stripped.startswith("("):
            posting = self._system.evaluate(stripped)
            all_lines = list(posting.values())
            all_callers: set[str] = set()
            for ln in all_lines:
                for c in ln.get("callers", []):
                    all_callers.add(c["name"])
        else:
            all_lines, all_callers = self._collect(text, max_lines + offset, max_callers)

        ranked = self._rank(all_lines, rank)[offset : offset + max_lines]

        return {
            "total_lines": len(all_lines),
            "total_callers": len(all_callers),
            "offset": offset,
            "lines": ranked,
        }

    def _collect(self, text: str, max_lines: int, max_callers: int):
        """Collect all matching lines with their callers."""
        idx = self._index

        doc_hits = idx.search(text)
        traced = idx.trace(text)

        callers_by_line: dict[tuple[str, int], dict[str, dict]] = {}
        all_callers: set[str] = set()
        for r in traced:
            key = (r["document"], r["line"])
            name = r["caller"]
            all_callers.add(name)
            by_name = callers_by_line.setdefault(key, {})
            if name not in by_name or r["overlap"] > by_name[name]["overlap"]:
                by_name[name] = {"name": name, "overlap": r["overlap"]}

        seen: set[tuple[str, int]] = set()
        lines = []

        for r in traced:
            key = (r["document"], r["line"])
            if key in seen:
                continue
            seen.add(key)
            callers = sorted(callers_by_line[key].values(), key=lambda c: -c["overlap"])
            lines.append(
                {
                    "document": r["document"],
                    "line": r["line"],
                    "column": r.get("column", 1),
                    "context": r["context"],
                    "callers": callers,
                    "total_callers": len(callers),
                }
            )

        for hit in doc_hits:
            key = (hit["document"], hit["line"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                {
                    "document": hit["document"],
                    "line": hit["line"],
                    "column": hit.get("column", 1),
                    "context": hit["context"],
                    "callers": [],
                    "total_callers": 0,
                }
            )

        return lines, all_callers

    def _rank(self, lines: list[dict], rank: Ranking) -> list[dict]:
        if rank == Ranking.CALLERS:
            return self._rank_by_callers(lines)
        elif rank == Ranking.COVERAGE:
            return self._rank_by_coverage(lines)
        elif rank == Ranking.DOCUMENT:
            return self._rank_by_document(lines)
        return lines

    def _rank_by_callers(self, lines: list[dict]) -> list[dict]:
        traced = [ln for ln in lines if ln["callers"]]
        untraced = [ln for ln in lines if not ln["callers"]]
        traced.sort(key=lambda ln: (-ln["total_callers"], -ln["callers"][0]["overlap"]))
        return traced + untraced

    def _rank_by_coverage(self, lines: list[dict]) -> list[dict]:
        traced = [ln for ln in lines if ln["callers"]]
        untraced = [ln for ln in lines if not ln["callers"]]
        traced.sort(key=lambda ln: (-ln["callers"][0]["overlap"], -ln["total_callers"]))
        return traced + untraced

    def _rank_by_document(self, lines: list[dict]) -> list[dict]:
        by_doc: dict[str, list[dict]] = {}
        for ln in lines:
            by_doc.setdefault(ln["document"], []).append(ln)
        doc_order = sorted(by_doc.keys(), key=lambda d: -len(by_doc[d]))
        result = []
        for doc in doc_order:
            doc_lines = sorted(by_doc[doc], key=lambda ln: (-ln["total_callers"], ln["line"]))
            result.extend(doc_lines)
        return result
