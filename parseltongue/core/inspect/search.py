"""Search — full-text search across loaded documents with pltg provenance tracing.

Supports pltg S-expression queries over the inverted index::

    Set operators (work on posting sets internally):

    "raise ValueError"                          — literal phrase lookup
    (and "def derive" "using")                  — intersection (same line must match both)
    (or "raise ValueError" "raise Syntax")      — union of posting sets
    (not "raise" "test")                        — difference (first minus second)
    (in "engine.py" "raise")                    — restrict to document (exact, suffix, or glob)
    (near "raise" "ValueError" 3)               — proximity within N lines
    (seq "def derive" "raise")                  — a before b in same document
    (re "raise (ValueError|NameError)")         — regex over all indexed lines
    (lines 400 500 (in "engine.py" (re ".")))   — restrict to line range

    Context expansion (add surrounding lines to matches):

    (context 3 "raise")                         — N lines before and after each match
    (before 3 "raise")                          — N lines before each match only
    (after 3 "raise")                           — N lines after each match only

    Ranking:

    (rank "callers" query)                      — rank by caller count + overlap
    (rank "coverage" query)                     — rank by overlap + caller count
    (rank "document" query)                     — group by doc, most-traced first
    (rank "line" query)                         — sort by document then line

    Output:

    (count query)                               — integer count of matches
    (results query)                             — convert posting set to sr forms
    (limit N query)                             — take first N entries

    Composition:

    (scope name expr)                           — evaluate expr in a registered scope

Search results as pltg data::

    (sr "engine.py" 10 1 "def derive(self):" (("engine.derive" 0.85)))

Accessors: ``sr-doc``, ``sr-line``, ``sr-column``, ``sr-context``, ``sr-callers``.

Queries starting with ``(`` are parsed as S-expressions and evaluated
by a SearchSystem whose operators work on posting sets.
Plain strings are literal phrase lookups (backwards compatible).

Scopes: external Systems registered via ``register_scope(name, system)``
define a defterm in the SearchSystem. ``(scope name expr)`` evaluates
``expr`` in that System.  ``unregister_scope(name)`` retracts the term.
"""

from __future__ import annotations

from typing import Callable

from .store import SearchStore
from .systems.bench_system import BenchSubsystem
from .systems.search import SearchSystem


class Search:
    """View layer over SearchSystem.

    ``evaluate(expr)`` — raw pltg result from the search system.
    ``query(text)`` — formatted display structure with ranking and pagination.

    All logic (set ops, ranking, limiting) lives in SearchSystem as pltg
    operators. Search just formats the output.
    """

    def __init__(self, store: SearchStore):
        self._index = store.load_index()
        self._store = store
        self._system = SearchSystem(self._index, self._collect)

    def register_scope(self, name: str, system: BenchSubsystem):
        """Register a BenchSubsystem as a named scope."""
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

    def evaluate(self, expression: str):
        """Evaluate an S-expression in the search system, return raw result.

        Returns whatever pltg produces — posting set, sr list, int, etc.
        """
        return self._system.evaluate(expression)

    def query(
        self,
        text: str,
        max_lines: int = 20,
        max_callers: int = 5,
        offset: int = 0,
        rank: str = "callers",
    ) -> dict:
        """Search and format results for display.

        Evaluates the query, ranks, paginates, and returns::

            {
                "total_lines": int,
                "total_callers": int,
                "offset": int,
                "lines": [...]
            }

        Each line: {document, line, column, context, callers, total_callers}.
        """
        result = self._system.evaluate(text.strip()) if text.strip().startswith("(") else None

        if result is not None:
            # S-expression result — could be posting set, sr list, or scalar
            posting = self._to_display_posting(result)
        else:
            # Plain text — collect with provenance
            lines, _ = self._collect(text, max_lines + offset, max_callers)
            posting = {(ln["document"], ln["line"]): ln for ln in lines}

        # Context/before/after queries need line-order ranking to keep
        # surrounding lines grouped with their matches.
        import re as _re_mod

        if _re_mod.search(r'\(\s*(context|before|after)\b', text):
            rank = "line"

        # Rank via the search system operator
        from parseltongue.core.atoms import Symbol

        rank_fn = self._system._pltg_system.engine.env[Symbol("rank")]
        ranked = rank_fn(rank, posting)

        # Paginate
        all_values = list(ranked.values())
        page = all_values[offset : offset + max_lines]

        all_callers: set[str] = set()
        for ln in all_values:
            for c in ln.get("callers", []):
                all_callers.add(c["name"])

        return {
            "total_lines": len(all_values),
            "total_callers": len(all_callers),
            "offset": offset,
            "lines": page,
        }

    def _to_display_posting(self, result) -> dict:
        """Convert any search system result to a posting set for display.

        Uses the SearchSystem's posting_morphism to dispatch tagged forms
        (sr, ln, dx, hn) back to posting dicts by head symbol.
        """
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return self._system.posting_morphism.inverse(result)
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
        return {}

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
