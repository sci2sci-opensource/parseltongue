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

from typing import TYPE_CHECKING, Callable

from parseltongue.core.atoms import Symbol
from parseltongue.core.lang import Rewriter, Sentence, is_sentence

from .bench_system import BenchSubsystem, Posting
from .search import SearchPostingMorphism, _posting_to_sr, _SrOpsMorphism

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier import DocumentIndex

    from ...search_engine.index import DocumentSearchIndex


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

        from ...search_engine.engine import QueryEngine

        self.posting_morphism = SearchPostingMorphism()
        self.ops_morphism = _SrOpsMorphism()
        self._engine = QueryEngine(index, form_to_posting=self.posting_morphism.inverse)
        self._index = self._engine._index
        self._search_index = self._engine._search_index
        self._collect = collect  # kept for interface compat; unused internally
        self._scopes: dict[str, BenchSubsystem | Rewriter] = {}

        sys = self  # capture

        def _scope(name: str, *args: "str | Posting | Sentence") -> "Sentence | Posting | None":
            if name not in sys._scopes:
                raise KeyError(f"Unknown scope: {name!r}. Registered: {list(sys._scopes)}")
            scope_system = sys._scopes[name]
            result: Sentence | Posting | None = None
            for arg in args:
                if is_sentence(arg):
                    result = scope_system.evaluate(arg)
                else:
                    result = arg
            return result

        def _results(query: str | Posting | Sentence) -> Sentence:
            """Convert a posting set to a list of sr forms."""
            posting = sys._engine.as_posting(query)
            return _posting_to_sr(posting)

        # Corpus-generic operators live in the core QueryEngine; the bench
        # adds scope dispatch and sr-form conversion on top. (The old
        # _delegate_ops/_has_forms branch was documented dead and dropped.)
        ops = dict(self._engine.ops)
        ops[Symbol("scope")] = _scope
        ops[Symbol("results")] = _results

        self._pltg_system = PltgSystem(initial_env=ops, docs={}, strict_derive=False, name="SearchIndex2")
        self._resolve = self._engine.resolve

        # Wrap evaluate: internal operators use posting sets,
        # but the system produces s-expressions at the boundary
        _raw_eval = self._pltg_system.evaluate
        self._raw_evaluate = _raw_eval

        def _sexp_evaluate(expr):
            result = _raw_eval(expr)
            if isinstance(result, dict):
                return _posting_to_sr(result)
            return result

        self._pltg_system.evaluate = _sexp_evaluate  # type: ignore[method-assign, assignment]

        # Register self as a scope for recursive composition
        self._scopes["self"] = self._pltg_system

    def evaluate(self, expr, local_env=None, *, preserve_postings=False):
        """Evaluate a query — string or s-expression.

        No wrapping, no formatting. Returns whatever the system produces:
        sr list, integer, string, etc.
        """
        evaluate = self._raw_evaluate if preserve_postings else self._pltg_system.evaluate
        convert = (lambda posting: posting) if preserve_postings else _posting_to_sr
        if isinstance(expr, str):
            if not expr.strip():
                return evaluate([])
            from parseltongue.core.atoms import Symbol
            from parseltongue.core.lang import PGStringParser

            parsed = PGStringParser.translate(expr)
            if isinstance(parsed, str):
                return convert(self._to_posting(parsed))
            if isinstance(parsed, (list, tuple)) and len(parsed) == 1 and isinstance(parsed[0], str):
                return convert(self._to_posting(parsed[0]))
            # If first element is a known operator, evaluate as s-expression
            if isinstance(parsed, (list, tuple)) and parsed:
                head = parsed[0]
                if isinstance(head, Symbol) and head in self._pltg_system.engine.env:
                    return evaluate(parsed)
                # Unknown symbols = plain text query
                return convert(self._to_posting(expr))
            return evaluate(parsed)

        return evaluate(expr)

    def register_scope(self, name: str, system: BenchSubsystem):
        """Register a BenchSubsystem as a callable scope operator."""
        self._scopes[name] = system
        self.posting_morphism.register(system)

        def _scope_fn(_name, *args):
            result = None
            for arg in args:
                if is_sentence(arg):
                    result = system.evaluate(arg)
                else:
                    result = arg
            return result

        self._pltg_system.engine.env[Symbol(name)] = _scope_fn

        # Data tags from scope results must be self-quoting in the engine
        # so strict/eval doesn't choke on them as unresolved symbols.
        for tag in getattr(system, "data_tags", [system.tag]):
            if tag not in self._pltg_system.engine.env:
                self._pltg_system.engine.env[tag] = tag

    def unregister_scope(self, name: str):
        """Unregister a scope."""
        scope = self._scopes.pop(name, None)
        if scope is not None and hasattr(scope, "tag"):
            self.posting_morphism.unregister(scope.tag)
        self._pltg_system.engine.env.pop(Symbol(name), None)

    def refresh(self):
        """Sync search index with underlying DocumentIndex after new docs added."""
        import logging as _logging

        _log = _logging.getLogger("parseltongue.search_system2")
        _log.debug(
            "refresh: _index docs=%d, search_index qr=%d",
            len(self._index.documents),
            len(self._search_index._quote_ranges),
        )
        self._search_index.refresh(self._index)

    def _to_posting(self, text: str) -> Posting:
        """Default lookup: cascade strategy + quote enrichment."""
        return self._search_index.search(text)
