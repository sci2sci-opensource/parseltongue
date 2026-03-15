"""SearchSystem v2 — backed by DocumentSearchIndex.

Same S-expression interface as SearchSystem, but uses the search package
(line-level indices, stemmer, n-grams, strategy cascade) instead of
DocumentIndex.trace() for the core lookup path.

Key differences from v1:
- _to_posting uses search_index.search() (strategy + enrich) instead of _collect
- _re uses pre-split SearchDocument.lines instead of splitlines() per call
- _context_lines uses SearchDocument.lines
- New (strategy ...) operator for explicit strategy selection
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from parseltongue import System

if TYPE_CHECKING:
    from parseltongue.core.inspect.search.index import DocumentSearchIndex


# ── sr: pltg-native search result form ──
# (sr doc line column context ((caller_name overlap) ...))


def _posting_to_sr(posting: dict) -> list:
    """Convert a posting set dict to a list of sr forms."""
    from parseltongue.core.atoms import Symbol

    tag = Symbol("sr")
    result = []
    for (_doc, _line), entry in posting.items():
        callers = [[c["name"], c.get("overlap", 1.0)] for c in entry.get("callers", [])]
        result.append([tag, entry["document"], entry["line"], entry.get("column", 1), entry["context"], callers])
    return result


def _sr_to_posting(sr_list: list) -> dict:
    """Convert a list of sr forms back to a posting set dict."""
    from parseltongue.core.atoms import Symbol

    sr_tag = Symbol("sr")
    posting = {}
    for item in sr_list:
        if not isinstance(item, list) or len(item) < 5:
            continue
        if not (isinstance(item[0], Symbol) and item[0] == sr_tag):
            continue
        doc = item[1]
        line = item[2]
        column = item[3]
        context = item[4]
        callers_raw = item[5] if len(item) > 5 else []
        callers = [
            {"name": c[0], "overlap": c[1]} if isinstance(c, list) else {"name": c, "overlap": 1.0} for c in callers_raw
        ]
        posting[(doc, line)] = {
            "document": doc,
            "line": line,
            "column": column,
            "context": context,
            "callers": callers,
            "total_callers": len(callers),
        }
    return posting


class SearchSystem2:
    """Parseltongue System wired with posting-set operators for search queries.

    Backed by DocumentSearchIndex — line-level indices with stemming,
    n-grams, and strategy cascade. Quote provenance via enrich().

    Operators work on posting sets (dicts keyed by (doc, line)) internally.
    ``results`` converts to pltg-native sr forms. ``evaluate`` returns
    raw pltg values — no wrapping, no formatting.
    """

    def __init__(self, search_index: "DocumentSearchIndex"):
        from parseltongue.core.atoms import Symbol
        from parseltongue.core.system import System as PltgSystem

        self._search_index = search_index
        self._scopes: dict[str, PltgSystem] = {}

        sys = self  # capture

        def _resolve(x):
            if isinstance(x, str):
                return sys._to_posting(x)
            return x

        def _as_posting(x):
            """Ensure x is a posting dict — convert sr lists back if needed."""
            val = _resolve(x)
            if isinstance(val, dict):
                return val
            if isinstance(val, list):
                return _sr_to_posting(val)
            return {}

        def _and(*args):
            sets = [_as_posting(a) for a in args]
            result = sets[0]
            for s in sets[1:]:
                result = {k: v for k, v in result.items() if k in s}
            return result

        def _or(*args):
            sets = [_as_posting(a) for a in args]
            result = dict(sets[0])
            for s in sets[1:]:
                result.update(s)
            return result

        def _not(*args):
            base = _as_posting(args[0])
            for a in args[1:]:
                exclude = _as_posting(a)
                base = {k: v for k, v in base.items() if k not in exclude}
            return base

        def _in(doc_pattern, query):
            import fnmatch

            posting = _as_posting(query)
            if "*" in doc_pattern or "?" in doc_pattern:
                return {k: v for k, v in posting.items() if fnmatch.fnmatch(k[0], doc_pattern)}
            return {k: v for k, v in posting.items() if k[0] == doc_pattern or k[0].endswith("/" + doc_pattern)}

        def _count(*args):
            v = _resolve(args[0])
            if isinstance(v, (list, dict)):
                return len(v)
            return 0

        def _near(a, b, distance=5):
            sa, sb = _as_posting(a), _as_posting(b)
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
            sa, sb = _as_posting(a), _as_posting(b)
            b_by_doc: dict[str, int] = {}
            for doc, line in sb:
                if doc not in b_by_doc or line > b_by_doc[doc]:
                    b_by_doc[doc] = line
            return {k: v for k, v in sa.items() if k[0] in b_by_doc and k[1] < b_by_doc[k[0]]}

        def _re(pattern):
            import re as _re_mod

            rx = _re_mod.compile(pattern)
            result = {}
            for doc_name, sdoc in sys._search_index.documents.items():
                for i, line_text in enumerate(sdoc.lines, 1):
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
            posting = _as_posting(query)
            s, e = int(start), int(end)
            return {k: v for k, v in posting.items() if s <= k[1] <= e}

        def _context_lines(n, query, before=True, after=True):
            """Expand matches to include surrounding lines."""
            posting = _as_posting(query)
            n = int(n)
            expanded = dict(posting)
            for (doc, line), _ in posting.items():
                sdoc = sys._search_index.documents.get(doc)
                if not sdoc:
                    continue
                start = max(0, line - 1 - (n if before else 0))
                end = min(len(sdoc.lines), line + (n if after else 0))
                for i in range(start, end):
                    key = (doc, i + 1)
                    if key not in expanded:
                        expanded[key] = {
                            "document": doc,
                            "line": i + 1,
                            "column": 1,
                            "context": sdoc.lines[i],
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

        def _strategy(name, query):
            """Explicit strategy selection: (strategy "stemmed" "query")."""
            posting = sys._search_index.search(str(query), strategy=str(name))
            return posting

        def _rank(strategy, query):
            posting = _as_posting(query)
            items = list(posting.values())
            strat = str(strategy)
            if strat == "callers":
                traced = [ln for ln in items if ln.get("callers")]
                untraced = [ln for ln in items if not ln.get("callers")]
                traced.sort(key=lambda ln: (-ln["total_callers"], -ln["callers"][0]["overlap"]))
                items = traced + untraced
            elif strat == "coverage":
                traced = [ln for ln in items if ln.get("callers")]
                untraced = [ln for ln in items if not ln.get("callers")]
                traced.sort(key=lambda ln: (-ln["callers"][0]["overlap"], -ln["total_callers"]))
                items = traced + untraced
            elif strat == "document":
                by_doc: dict[str, list[dict]] = {}
                for ln in items:
                    by_doc.setdefault(ln["document"], []).append(ln)
                doc_order = sorted(by_doc.keys(), key=lambda d: -len(by_doc[d]))
                items = []
                for doc in doc_order:
                    doc_lines = sorted(by_doc[doc], key=lambda ln: (-ln["total_callers"], ln["line"]))
                    items.extend(doc_lines)
            elif strat == "line":
                items.sort(key=lambda ln: (ln["document"], ln["line"]))
            return {(ln["document"], ln["line"]): ln for ln in items}

        def _results(query):
            """Convert a posting set to a list of sr forms."""
            posting = _as_posting(query)
            return _posting_to_sr(posting)

        def _limit(n, query):
            """Take first N entries from a posting set or sr list."""
            val = _resolve(query)
            n = int(n)
            if isinstance(val, (list, tuple)):
                return val[:n]
            if isinstance(val, dict):
                keys = list(val.keys())[:n]
                return {k: val[k] for k in keys}
            return val

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
            Symbol("strategy"): _strategy,
            Symbol("rank"): _rank,
            Symbol("results"): _results,
            Symbol("limit"): _limit,
        }

        self._pltg_system = PltgSystem(initial_env=ops, docs={}, strict_derive=False)
        self._resolve = _resolve

        # Wrap evaluate: internal operators use posting sets,
        # but the system produces s-expressions at the boundary
        _raw_eval = self._pltg_system.evaluate

        def _sexp_evaluate(expr):
            result = _raw_eval(expr)
            if isinstance(result, dict):
                return _posting_to_sr(result)
            return result

        self._pltg_system.evaluate = _sexp_evaluate  # type: ignore[method-assign, assignment]

        # Register self as a scope for recursive composition
        self._scopes["self"] = self._pltg_system

    def evaluate(self, query_str: str):
        """Parse and evaluate an S-expression query. Returns raw pltg result.

        No wrapping, no formatting. Returns whatever the system produces:
        sr list, integer, string, etc.
        """
        from parseltongue.core.atoms import read_tokens, tokenize

        tokens = tokenize(query_str)
        expr = read_tokens(tokens)

        # Plain string → search (cascade + enrich) → sr forms
        if isinstance(expr, str):
            return _posting_to_sr(self._to_posting(expr))
        # Parenthesized string literal like ("test") → plain search
        if isinstance(expr, list) and len(expr) == 1 and isinstance(expr[0], str):
            return _posting_to_sr(self._to_posting(expr[0]))

        return self._pltg_system.evaluate(expr)

    def register_scope(self, name: str, system: System):
        """Register a scope as a callable operator in the env."""
        from parseltongue.core.atoms import Symbol

        self._scopes[name] = system

        def _scope_fn(_name, *args):
            result = None
            for arg in args:
                if isinstance(arg, list):
                    result = system.evaluate(arg)
                else:
                    result = arg
            return result

        self._pltg_system.engine.env[Symbol(name)] = _scope_fn

    def unregister_scope(self, name: str):
        """Unregister a scope."""
        from parseltongue.core.atoms import Symbol

        self._scopes.pop(name, None)
        self._pltg_system.engine.env.pop(Symbol(name), None)

    def _to_posting(self, text: str) -> dict[tuple[str, int], dict]:
        """Default lookup: cascade strategy + quote enrichment."""
        return self._search_index.search(text)
