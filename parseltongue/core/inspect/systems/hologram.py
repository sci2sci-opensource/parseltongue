"""HologramSearchSystem — S-expression query language over a Hologram (N lenses).

Wraps N LensSearchSystems. Operators select, filter, and compare across lenses.

Operators::

    (left ...)              — evaluate in the first lens
    (right ...)             — evaluate in the last lens
    (lens N ...)            — evaluate in the Nth lens (0-based)
    (divergent)             — nodes present in some lenses but not all
    (common)                — nodes present in all lenses
    (only N)                — nodes only in lens N

Registered as ``(scope hologram ...)`` in the main search system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from parseltongue.core.atoms import Symbol
from parseltongue.core.system import System

from .lens import LensSearchSystem

if TYPE_CHECKING:
    from ..optics.hologram import Hologram


class HologramSearchSystem:
    """Parseltongue System with operators over N lenses combined."""

    def __init__(self, hologram: "Hologram"):
        self._hologram = hologram
        self._lens_systems: list[LensSearchSystem] = []

        for lens in hologram._lenses:
            self._lens_systems.append(LensSearchSystem(lens._structure))

        # Collect all names across lenses (excluding __output__)
        self._all_names: set[str] = set()
        self._names_per_lens: list[set[str]] = []
        for ls in self._lens_systems:
            names = set(ls._structure.graph.keys()) - {"__output__"}
            self._names_per_lens.append(names)
            self._all_names |= names

        sys = self  # capture

        def _posting_from_lens(lens_idx: int, names):
            """Build posting set from a specific lens's index."""
            ls = sys._lens_systems[lens_idx]
            result = {}
            for n in names:
                doc = ls._idx.documents.get(n)
                if doc:
                    result[(n, 1)] = {
                        "document": n,
                        "line": 1,
                        "column": 1,
                        "context": doc.original_text.splitlines()[0] if doc.original_text else "",
                        "callers": [],
                        "total_callers": 0,
                    }
            return result

        def _left(*args):
            if args:
                result = sys._lens_systems[0]._system.evaluate(args[0] if len(args) == 1 else list(args))
                return result
            return _posting_from_lens(0, sys._names_per_lens[0])

        def _right(*args):
            last = len(sys._lens_systems) - 1
            if args:
                result = sys._lens_systems[last]._system.evaluate(args[0] if len(args) == 1 else list(args))
                return result
            return _posting_from_lens(last, sys._names_per_lens[last])

        def _lens(n, *args):
            n = int(n)
            if n < 0 or n >= len(sys._lens_systems):
                raise IndexError(f"Lens index {n} out of range (0-{len(sys._lens_systems) - 1})")
            if args:
                result = sys._lens_systems[n]._system.evaluate(args[0] if len(args) == 1 else list(args))
                return result
            return _posting_from_lens(n, sys._names_per_lens[n])

        def _divergent():
            """Nodes not present in all lenses."""
            shared = set.intersection(*sys._names_per_lens) if sys._names_per_lens else set()
            diff = sys._all_names - shared
            # Use first lens that has each name
            result = {}
            for n in diff:
                for i, names in enumerate(sys._names_per_lens):
                    if n in names:
                        result.update(_posting_from_lens(i, [n]))
                        break
            return result

        def _common():
            """Nodes present in all lenses."""
            if not sys._names_per_lens:
                return {}
            shared = set.intersection(*sys._names_per_lens)
            return _posting_from_lens(0, shared)

        def _only(n):
            """Nodes only in lens N."""
            n = int(n)
            if n < 0 or n >= len(sys._names_per_lens):
                raise IndexError(f"Lens index {n} out of range")
            exclusive = sys._names_per_lens[n] - set.union(*(s for i, s in enumerate(sys._names_per_lens) if i != n))
            return _posting_from_lens(n, exclusive)

        ops = {
            Symbol("left"): _left,
            Symbol("right"): _right,
            Symbol("lens"): _lens,
            Symbol("divergent"): _divergent,
            Symbol("common"): _common,
            Symbol("only"): _only,
        }
        self._system = System(initial_env=ops, docs={}, strict_derive=False)

    def find(self, pattern: str, max_results: int = 50) -> list[str]:
        """Regex search over node names across all lenses."""
        import re as _re

        rx = _re.compile(pattern)
        seen: set[str] = set()
        for ls in self._lens_systems:
            for name in ls.index.documents:
                if name not in seen and rx.search(name):
                    seen.add(name)
        return sorted(seen)[:max_results]

    def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        """Ranked substring search across all lenses."""
        query_lower = query.lower()
        scored = []
        seen: set[str] = set()
        for ls in self._lens_systems:
            for name in ls.index.documents:
                if name in seen:
                    continue
                seen.add(name)
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

    def evaluate(self, query_str: str) -> dict:
        """Parse and evaluate an S-expression query. Returns posting set."""
        from parseltongue.core.atoms import read_tokens, tokenize

        tokens = tokenize(query_str)
        expr = read_tokens(tokens)

        if isinstance(expr, str):
            # Plain text: search across all lens indexes
            merged: dict = {}
            for ls in self._lens_systems:
                results = ls.index.search(expr)
                for r in results:
                    key = (r["document"], r["line"])
                    if key not in merged:
                        merged[key] = r
            return merged

        result = self._system.evaluate(expr)
        if isinstance(result, dict):
            return result
        return {}
