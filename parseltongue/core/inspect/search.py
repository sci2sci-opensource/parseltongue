"""Search — full-text search across loaded documents with pltg provenance tracing.

Supports pltg S-expression queries over the inverted index::

    "raise ValueError"                       — literal phrase lookup
    (or "raise ValueError" "raise Syntax")   — union of posting sets
    (and "def derive" "using")               — intersection (same line)
    (not "raise" "test")                     — difference (first minus second)
    (in "engine.py" "raise")                 — restrict to document

Queries starting with ``(`` are parsed as S-expressions and evaluated
by a dedicated search System whose operators work on posting sets.
Plain strings are literal phrase lookups (backwards compatible).

Ranking strategies:
    callers   — lines with most pltg nodes quoting them first (default)
    coverage  — lines where query best overlaps a quote range first
    document  — group by document, most hits per document first
"""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

from .store import SearchStore


class Ranking(StrEnum):
    CALLERS = "callers"
    COVERAGE = "coverage"
    DOCUMENT = "document"


class Search:
    """Full-text search composed with quote provenance.

    Owns its index independently from the quote verifier. Optionally
    backed by a Store for Merkle-cached incremental reindexing.
    """

    def __init__(self, store: SearchStore):
        self._index = store.load_index()
        self._store = store

    def index_dir(
        self,
        directory: str,
        extensions: list[str] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        self._index, count = self._store.index_incremental(self._index, directory, extensions, on_progress)
        return count

    def reindex(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> int:
        """Re-read known files, update stale entries, remove deleted."""
        self._index, count = self._store.reindex(self._index, on_progress)
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

        Ranking:
            callers  — most pltg callers first, then untraced
            coverage — best quote overlap first, then untraced
            document — grouped by document (most total hits first), lines in order
        """
        rank = Ranking(rank)

        # S-expression query: parse and evaluate over posting sets
        stripped = text.strip()
        if stripped.startswith("("):
            posting = self._eval_query(stripped)
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

        # Group callers by (document, line)
        callers_by_line: dict[tuple[str, int], dict[str, dict]] = {}
        all_callers: set[str] = set()
        for r in traced:
            key = (r["document"], r["line"])
            name = r["caller"]
            all_callers.add(name)
            by_name = callers_by_line.setdefault(key, {})
            if name not in by_name or r["overlap"] > by_name[name]["overlap"]:
                by_name[name] = {"name": name, "overlap": r["overlap"]}

        # Build unified line list
        seen: set[tuple[str, int]] = set()
        lines = []

        # Traced lines
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

        # Untraced doc hits
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
        """Most pltg callers first, then untraced lines."""
        traced = [ln for ln in lines if ln["callers"]]
        untraced = [ln for ln in lines if not ln["callers"]]
        traced.sort(key=lambda ln: (-ln["total_callers"], -ln["callers"][0]["overlap"]))
        return traced + untraced

    def _rank_by_coverage(self, lines: list[dict]) -> list[dict]:
        """Best quote overlap first, then untraced lines."""
        traced = [ln for ln in lines if ln["callers"]]
        untraced = [ln for ln in lines if not ln["callers"]]
        traced.sort(key=lambda ln: (-ln["callers"][0]["overlap"], -ln["total_callers"]))
        return traced + untraced

    def _rank_by_document(self, lines: list[dict]) -> list[dict]:
        """Group by document, most hits per document first, lines in order within."""
        by_doc: dict[str, list[dict]] = {}
        for ln in lines:
            by_doc.setdefault(ln["document"], []).append(ln)
        # Sort documents by total hits descending
        doc_order = sorted(by_doc.keys(), key=lambda d: -len(by_doc[d]))
        result = []
        for doc in doc_order:
            # Within document: traced first, then by line number
            doc_lines = sorted(by_doc[doc], key=lambda ln: (-ln["total_callers"], ln["line"]))
            result.extend(doc_lines)
        return result

    # ── S-expression query evaluation ──

    def _to_posting(self, text: str) -> dict[tuple[str, int], dict]:
        """Literal string → posting set via index lookup."""
        lines, _ = self._collect(text, 100_000, 50)
        return {(ln["document"], ln["line"]): ln for ln in lines}

    def _eval_query(self, query_str: str) -> dict[tuple[str, int], dict]:
        """Parse an S-expression query and evaluate it over the index.

        Builds a System with posting-set operators, parses the query,
        and evaluates it.  String literals become index lookups.
        """
        from parseltongue.core.atoms import Symbol, read_tokens, tokenize
        from parseltongue.core.system import System

        search = self  # capture for closures

        # ── Posting-set operators ──

        def _resolve(x):
            """Coerce arg to posting set: strings are looked up, sets pass through."""
            if isinstance(x, str):
                return search._to_posting(x)
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
            """Restrict results to documents matching pattern.

            Matches if doc name equals the pattern, ends with /pattern,
            or matches as a glob (when pattern contains * or ?).
            """
            import fnmatch

            posting = _resolve(query)
            if "*" in doc_pattern or "?" in doc_pattern:
                return {k: v for k, v in posting.items() if fnmatch.fnmatch(k[0], doc_pattern)}
            return {k: v for k, v in posting.items() if k[0] == doc_pattern or k[0].endswith("/" + doc_pattern)}

        def _count(*args):
            """Return the size of a posting set."""
            return len(_resolve(args[0]))

        def _near(a, b, distance=5):
            """Lines from a that have a line from b within N lines in the same doc."""
            sa, sb = _resolve(a), _resolve(b)
            n = int(distance) if not isinstance(distance, dict) else 5
            # Group b by document for fast lookup
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
            """Lines from a where b appears later in the same document."""
            sa, sb = _resolve(a), _resolve(b)
            b_by_doc: dict[str, int] = {}
            for doc, line in sb:
                if doc not in b_by_doc or line > b_by_doc[doc]:
                    b_by_doc[doc] = line
            return {k: v for k, v in sa.items() if k[0] in b_by_doc and k[1] < b_by_doc[k[0]]}

        def _re(pattern):
            """Regex search across all documents."""
            import re as _re_mod

            rx = _re_mod.compile(pattern)
            result = {}
            for doc_name, doc in search._index.documents.items():
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
            """Restrict to line range [start, end]."""
            posting = _resolve(query)
            s, e = int(start), int(end)
            return {k: v for k, v in posting.items() if s <= k[1] <= e}

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
        }

        system = System(initial_env=ops, docs={})
        tokens = tokenize(query_str)
        expr = read_tokens(tokens)
        result = system.evaluate(expr)

        # If result is a count (int), wrap it
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

        return _resolve(result)
