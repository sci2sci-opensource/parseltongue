from typing import Callable

from parseltongue.core.atoms import Symbol
from parseltongue.core.quote_verifier import DocumentIndex

from .bench_system import BenchSubsystem, Posting

# ── sr: pltg-native search result form ──
# (sr doc line column context ((caller_name overlap) ...))
# Defined as rewrite axioms in SearchSystem.__init__.


class SearchPostingMorphism:
    """PostingMorphism for SearchSystem — dispatches by head symbol.

    Maintains a tag → morphism table from registered scope subsystems.
    transform: posting → sr forms (search-native).
    inverse:   walks a list of tagged forms, dispatches each item's
               head symbol to the correct scope morphism, merges postings.
    """

    def __init__(self):
        self._dispatch: dict[Symbol, "BenchSubsystem"] = {}

    def register(self, subsystem: BenchSubsystem):
        self._dispatch[subsystem.tag] = subsystem

    def unregister(self, tag: Symbol):
        self._dispatch.pop(tag, None)

    def transform(self, posting: Posting) -> list:
        return _posting_to_sr(posting)

    def inverse(self, forms: list) -> Posting:
        posting: Posting = {}
        # Group items by head tag, dispatch to correct morphism
        by_tag: dict[Symbol, list] = {}
        for item in forms:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], Symbol):
                by_tag.setdefault(item[0], []).append(item)
            # Non-tagged items ignored
        # sr forms handled directly
        sr_tag = Symbol("sr")
        if sr_tag in by_tag:
            posting.update(_sr_to_posting(by_tag[sr_tag]))
        # Scope forms dispatched to registered morphisms
        for tag, items in by_tag.items():
            if tag == sr_tag:
                continue
            subsystem = self._dispatch.get(tag)
            if subsystem is not None:
                posting.update(subsystem.posting_morphism.inverse(items))
        return posting


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


class SearchSystem:
    """Parseltongue System wired with posting-set operators for search queries.

    Implements BenchSubsystem: tag=sr, posting_morphism dispatches by
    head symbol to registered scope morphisms for mixed-form results.

    Operators work on posting sets (dicts keyed by (doc, line)) internally.
    ``results`` converts to pltg-native sr forms. ``evaluate`` returns
    raw pltg values — no wrapping, no formatting.
    """

    tag = Symbol("sr")

    def __init__(self, index: DocumentIndex, collect: Callable):
        from parseltongue.core.system import System as PltgSystem

        self._index = index
        self._collect = collect
        self._scopes: dict[str, BenchSubsystem] = {}
        self.posting_morphism = SearchPostingMorphism()

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
            v = _resolve(args[0])
            if isinstance(v, list):
                return len(v)
            if isinstance(v, dict):
                return len(v)
            return 0

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
                if isinstance(arg, (list, tuple)):
                    result = scope_system.evaluate(arg)
                else:
                    result = arg
            return result

        def _rank(strategy, query):
            posting = _resolve(query)
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
            posting = _resolve(query)
            return _posting_to_sr(posting)

        def _limit(n, query):
            """Take first N entries from a posting set or sr list."""
            val = _resolve(query)
            n = int(n)
            if isinstance(val, list):
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
            Symbol("rank"): _rank,
            Symbol("results"): _results,
            Symbol("limit"): _limit,
        }

        self._pltg_system = PltgSystem(initial_env=ops, docs={}, strict_derive=False, name="SearchIndex")
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
            from parseltongue.core.lang import PGStringParser

            parsed = PGStringParser.translate(expr)
            if isinstance(parsed, str):
                return _posting_to_sr(self._to_posting(parsed))
            if isinstance(parsed, (list, tuple)) and len(parsed) == 1 and isinstance(parsed[0], str):
                return _posting_to_sr(self._to_posting(parsed[0]))
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
        if scope is not None:
            self.posting_morphism.unregister(scope.tag)
        self._pltg_system.engine.env.pop(Symbol(name), None)

    def _to_posting(self, text: str) -> dict[tuple[str, int], dict]:
        lines, _ = self._collect(text, 100_000, 50)
        return {(ln["document"], ln["line"]): ln for ln in lines}
