"""SearchSystem v2 — backed by DocumentSearchIndex.

Same BenchSubsystem interface as SearchSystem, but uses the search package
(line-level indices, stemmer, n-grams, strategy cascade) instead of
DocumentIndex.trace() for the core lookup path.

Key differences from v1:
- _to_posting uses DocumentSearchIndex.search() (lookup + enrich) instead of _collect
- _re uses pre-split SearchDocument.lines instead of splitlines() per call
- _context_lines uses SearchDocument.lines
- New (strategy ...) operator for explicit strategy selection
- _as_posting routes through posting_morphism.inverse for cross-scope forms
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from parseltongue.core.atoms import Symbol
from parseltongue.core.lang import Rewriter

from .bench_system import BenchSubsystem, Posting
from .search import SearchPostingMorphism, _posting_to_sr

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier import DocumentIndex

    from ..search_s.index import DocumentSearchIndex


class SearchSystem2:
    """Parseltongue System wired with posting-set operators for search queries.

    Implements BenchSubsystem: tag=sr, posting_morphism dispatches by
    head symbol to registered scope morphisms for mixed-form results.

    Backed by DocumentSearchIndex — line-level indices with stemming,
    n-grams, and strategy cascade. Quote provenance via enrich().
    """

    tag = Symbol("sr")

    def __init__(self, index: "DocumentIndex | DocumentSearchIndex", collect: "Callable | None" = None):
        from parseltongue.core.system import System as PltgSystem

        from ..search_s.index import DocumentSearchIndex

        if isinstance(index, DocumentSearchIndex):
            self._index = index._doc_index
            self._search_index = index
        else:
            self._index = index
            self._search_index = DocumentSearchIndex(index)
        self._collect = collect  # kept for interface compat; unused internally
        self._scopes: dict[str, BenchSubsystem | Rewriter] = {}
        self.posting_morphism = SearchPostingMorphism()

        sys = self  # capture

        def _resolve(x):
            if isinstance(x, str):
                return sys._to_posting(x)
            return x

        def _as_posting(x):
            """Ensure x is a posting dict — convert tagged forms via morphism."""
            val = _resolve(x)
            if isinstance(val, dict):
                return val
            if isinstance(val, list):
                return sys.posting_morphism.inverse(val)
            return {}

        def _delegate_ops(op, resolved):
            """Delegate to ops scope when args are tagged form lists."""
            ops = sys._scopes.get("ops")
            if ops is None:
                raise TypeError(f"Cannot {op} tagged forms — no ops scope registered")
            return ops.evaluate([Symbol(op + "-forms")] + resolved)

        def _has_forms(resolved):
            for r in resolved:
                if isinstance(r, list) and r and isinstance(r[0], (list, tuple)):
                    return True
            return False

        def _and(*args):
            sets = [_as_posting(a) for a in args]
            if _has_forms(sets):
                return _delegate_ops("and", sets)
            result = sets[0]
            for s in sets[1:]:
                result = {k: v for k, v in result.items() if k in s}
            return result

        def _or(*args):
            sets = [_as_posting(a) for a in args]
            if _has_forms(sets):
                return _delegate_ops("or", sets)
            result = dict(sets[0])
            for s in sets[1:]:
                result.update(s)
            return result

        def _not(*args):
            resolved = [_as_posting(a) for a in args]
            if _has_forms(resolved):
                return _delegate_ops("not", resolved)
            base = resolved[0]
            for a in resolved[1:]:
                base = {k: v for k, v in base.items() if k not in a}
            return base

        def _match_doc(doc_name, pattern):
            import fnmatch

            d, p = str(doc_name), str(pattern)
            if "*" in p or "?" in p:
                return fnmatch.fnmatch(d, p) or fnmatch.fnmatch(d, "*/" + p)
            return d == p or d.endswith("/" + p) or d.endswith(p)

        def _in(doc_pattern, query):
            posting = _as_posting(query)
            return {k: v for k, v in posting.items() if _match_doc(k[0], doc_pattern)}

        def _not_in(doc_pattern, query):
            posting = _as_posting(query)
            return {k: v for k, v in posting.items() if not _match_doc(k[0], doc_pattern)}

        def _count(*args):
            v = _resolve(args[0])
            if isinstance(v, list):
                return len(v)
            if isinstance(v, dict):
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
                if isinstance(arg, (list, tuple)):
                    result = scope_system.evaluate(arg)
                else:
                    result = arg
            return result

        def _strategy(name, query):
            """Explicit strategy selection: (strategy "stemmed" "query")."""
            return sys._search_index.search(str(query), strategy=str(name))

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
            if isinstance(val, list | tuple):
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
            Symbol("not-in"): _not_in,
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

        self._pltg_system = PltgSystem(initial_env=ops, docs={}, strict_derive=False, name="SearchIndex2")
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

    def evaluate(self, expr, local_env=None):
        """Evaluate a query — string or s-expression.

        No wrapping, no formatting. Returns whatever the system produces:
        sr list, integer, string, etc.
        """
        if isinstance(expr, str):
            from parseltongue.core.atoms import Symbol
            from parseltongue.core.lang import PGStringParser

            parsed = PGStringParser.translate(expr)
            if isinstance(parsed, str):
                return _posting_to_sr(self._to_posting(parsed))
            if isinstance(parsed, (list, tuple)) and len(parsed) == 1 and isinstance(parsed[0], str):
                return _posting_to_sr(self._to_posting(parsed[0]))
            # If first element is a known operator, evaluate as s-expression
            if isinstance(parsed, (list, tuple)) and parsed:
                head = parsed[0]
                if isinstance(head, Symbol) and head in self._pltg_system.engine.env:
                    return self._pltg_system.evaluate(parsed)
                # Unknown symbols = plain text query
                return _posting_to_sr(self._to_posting(expr))
            return self._pltg_system.evaluate(parsed)

        return self._pltg_system.evaluate(expr)

    def register_scope(self, name: str, system: BenchSubsystem):
        """Register a BenchSubsystem as a callable scope operator."""
        self._scopes[name] = system
        self.posting_morphism.register(system)

        def _scope_fn(_name, *args):
            result = None
            for arg in args:
                if isinstance(arg, (list, tuple)):
                    result = system.evaluate(arg)
                else:
                    result = arg
            return result

        self._pltg_system.engine.env[Symbol(name)] = _scope_fn

    def unregister_scope(self, name: str):
        """Unregister a scope."""
        scope = self._scopes.pop(name, None)
        if scope is not None and hasattr(scope, "tag"):
            self.posting_morphism.unregister(scope.tag)
        self._pltg_system.engine.env.pop(Symbol(name), None)

    def refresh(self):
        """Sync search index with underlying DocumentIndex after new docs added."""
        self._search_index.refresh()

    def _to_posting(self, text: str) -> Posting:
        """Default lookup: cascade strategy + quote enrichment."""
        return self._search_index.search(text)
