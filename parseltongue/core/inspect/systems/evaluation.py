"""EvaluationSearchSystem — S-expression query language over evaluation data.

Operators::

    (kind "diff")           — items matching directive kind (substring)
    (category "issue")      — items in a category
    (type "diverge")        — items matching issue/warning type (substring)
    (issues)                — shorthand for (category "issue")
    (warnings)              — shorthand for (category "warning")
    (danglings)             — shorthand for (category "dangling")
    (focus "engine.")       — namespace prefix filter
    (consistent)            — True if no issues
    (ns)                    — all top-level namespaces as text

Registered as ``(scope evaluation ...)`` in the main search system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from parseltongue.core.atoms import Symbol
from parseltongue.core.system import System

if TYPE_CHECKING:
    from ..evaluation import Evaluation, EvaluationItem


class EvaluationSearchSystem:
    """Parseltongue System with posting-set operators over evaluation data."""

    def __init__(self, dx: "Evaluation"):
        from parseltongue.core.quote_verifier.index import DocumentIndex

        self._idx = DocumentIndex()
        self._dx = dx

        # Group items by category → each category becomes a "document"
        by_cat: dict[str, list[str]] = {}
        for item in dx._items:
            kind_str = f"[{item.kind}] " if item.kind else ""
            detail_str = f": {item.detail}" if item.detail else ""
            line = f"{item.name} {kind_str}{item.type}{detail_str}"
            by_cat.setdefault(item.category, []).append(line)
        for cat, lines in by_cat.items():
            self._idx.add(cat, "\n".join(lines))

        # Build item lookup by (category_doc, line_number)
        self._item_index: dict[tuple[str, int], "EvaluationItem"] = {}
        for item in dx._items:
            cat = item.category
            cat_items = [i for i in dx._items if i.category == cat]
            line_num = cat_items.index(item) + 1
            self._item_index[(cat, line_num)] = item
        item_index = self._item_index

        idx = self._idx

        def _posting(key: tuple[str, int]) -> dict:
            doc = idx.documents.get(key[0])
            if not doc:
                return {}
            lines = doc.original_text.splitlines()
            if key[1] > len(lines):
                return {}
            return {
                "document": key[0],
                "line": key[1],
                "column": 1,
                "context": lines[key[1] - 1],
                "callers": [],
                "total_callers": 0,
            }

        def _kind(kind_pattern, posting=None):
            if posting is None:
                return {
                    k: _posting(k)
                    for k, it in item_index.items()
                    if it.kind and kind_pattern in it.kind and _posting(k)
                }
            return {
                k: v
                for k, v in posting.items()
                if k in item_index and item_index[k].kind is not None and kind_pattern in str(item_index[k].kind)
            }

        def _category(cat_name, posting=None):
            if posting is None:
                return {k: _posting(k) for k, it in item_index.items() if it.category == cat_name and _posting(k)}
            return {k: v for k, v in posting.items() if k in item_index and item_index[k].category == cat_name}

        def _type(type_pattern, posting=None):
            if posting is None:
                return {k: _posting(k) for k, it in item_index.items() if type_pattern in it.type and _posting(k)}
            return {k: v for k, v in posting.items() if k in item_index and type_pattern in item_index[k].type}

        def _issues():
            return _category("issue")

        def _warnings():
            return _category("warning")

        def _danglings():
            return _category("dangling")

        def _focus(prefix, posting=None):
            if posting is None:
                return {k: _posting(k) for k, it in item_index.items() if it.name.startswith(prefix) and _posting(k)}
            return {k: v for k, v in posting.items() if k in item_index and item_index[k].name.startswith(prefix)}

        def _consistent():
            return dx._consistent

        def _ns():
            return ", ".join(sorted(dx._all_namespaces))

        # Also build a name-keyed index for find/fuzzy
        self._name_idx = DocumentIndex()
        for item in dx._items:
            if item.name not in self._name_idx.documents:
                kind_str = f"[{item.kind}] " if item.kind else ""
                detail_str = f": {item.detail}" if item.detail else ""
                self._name_idx.add(item.name, f"{item.category} {kind_str}{item.type}{detail_str}")

        ops = {
            Symbol("kind"): _kind,
            Symbol("category"): _category,
            Symbol("type"): _type,
            Symbol("issues"): _issues,
            Symbol("warnings"): _warnings,
            Symbol("danglings"): _danglings,
            Symbol("focus"): _focus,
            Symbol("consistent"): _consistent,
            Symbol("ns"): _ns,
        }
        self._system = System(initial_env=ops)

        _raw_eval = self._system.evaluate
        _to_dx = self._posting_to_dx

        def _sexp_evaluate(expr):
            result = _raw_eval(expr)
            if isinstance(result, dict):
                return _to_dx(result)
            return result

        self._system.evaluate = _sexp_evaluate  # type: ignore[method-assign, assignment]

    def find(self, pattern: str, max_results: int = 50) -> list[str]:
        """Regex search over item names via the index."""
        import re as _re

        rx = _re.compile(pattern)
        return sorted(n for n in self._name_idx.documents if rx.search(n))[:max_results]

    def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        """Ranked substring search over item names via the index."""
        query_lower = query.lower()
        scored = []
        for name in self._name_idx.documents:
            name_lower = name.lower()
            if query_lower not in name_lower:
                continue
            if name_lower == query_lower:
                score = 0
            elif name_lower.endswith(query_lower):
                score = 1
            elif name_lower.startswith(query_lower):
                score = 2
            else:
                score = 3
            scored.append((score, len(name), name))
        scored.sort()
        return [name for _, _, name in scored[:max_results]]

    def evaluate(self, query_str: str):
        """Parse and evaluate an S-expression query. Returns raw pltg result."""
        from parseltongue.core.atoms import read_tokens, tokenize

        tokens = tokenize(query_str)
        expr = read_tokens(tokens)

        if isinstance(expr, str):
            results = self._idx.search(expr)
            return {(r["document"], r["line"]): r for r in results}

        return self._system.evaluate(expr)

    def _posting_to_dx(self, posting: dict) -> list:
        """Convert a posting set to a list of dx forms."""
        from parseltongue.core.atoms import Symbol

        tag = Symbol("dx")
        result = []
        for key in posting:
            item = self._item_index.get(key)
            if not item:
                continue
            result.append([tag, item.name, item.category, item.kind or "", item.type, item.detail or ""])
        return result
