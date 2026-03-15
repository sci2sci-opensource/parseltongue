"""LensSearchSystem — S-expression query language over a Lens provenance graph.

Builds a DocumentIndex from graph nodes (one "document" per node, containing
kind + value + inputs as text). Operators work on posting sets, compatible
with the main search system's scope mechanism.

Operators::

    (node "name")           — posting set for a single node
    (kind "fact")           — all nodes matching NodeKind (substring)
    (inputs "name")         — upstream: nodes that are inputs to name
    (downstream "name")     — nodes that depend on name
    (roots)                 — root nodes (depth 0, no inputs)
    (layer N)               — nodes at depth N
    (focus "ns.")           — namespace prefix filter
    (depth "name")          — returns depth as scalar
    (value "name")          — returns value as text
    (terms "kind")          — returns list of name strings matching kind
    (quotes "name")         — returns list of quote strings from atom evidence

``terms`` and ``quotes`` return lists (not posting sets) — designed for
cross-scope composition where the caller needs raw values to pattern-match
or delegate back through another system.

Registered as ``(scope lens ...)`` in the main search system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from parseltongue.core.atoms import Symbol
from parseltongue.core.system import System

from .bench_system import BenchSubsystem

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.index import DocumentIndex

    from ..probe_core_to_consequence import CoreToConsequenceStructure


def _node_text(node) -> str:
    """Render a node as searchable text: kind, value, inputs."""
    parts = [f"kind: {node.kind}"]
    if node.value is not None and node.value != "":
        parts.append(f"value: {node.value}")
    if node.inputs:
        parts.append(f"inputs: {', '.join(node.inputs)}")
    return "\n".join(parts)


class LensSearchSystem:
    """Parseltongue System with posting-set operators over a provenance graph.

    Each node becomes a document in a DocumentIndex. Operators filter/select
    nodes and return posting sets ``{(doc_name, line): hit_dict}``.
    """

    tag = Symbol("ln")

    def __init__(self, structure: CoreToConsequenceStructure):
        from parseltongue.core.quote_verifier.index import DocumentIndex

        self._structure = structure
        self._idx = DocumentIndex()

        # Build index: each node name → its text representation
        for name, node in structure.graph.items():
            if name == "__output__":
                continue
            self._idx.add(name, _node_text(node))

        # Reverse dependency index
        self._dependents: dict[str, list[str]] = {}
        for name, node in structure.graph.items():
            for inp in node.inputs:
                self._dependents.setdefault(inp, []).append(name)

        sys = self  # capture

        def _posting(name: str) -> dict:
            """Single-node posting set (line 1 of its document)."""
            doc = sys._idx.documents.get(name)
            if not doc:
                return {}
            return {
                (name, 1): {
                    "document": name,
                    "line": 1,
                    "column": 1,
                    "context": doc.original_text.splitlines()[0] if doc.original_text else "",
                    "callers": [],
                    "total_callers": 0,
                }
            }

        def _multi_posting(names) -> dict:
            """Posting set for multiple nodes."""
            result = {}
            for n in names:
                result.update(_posting(n))
            return result

        def _node(name):
            if name not in sys._structure.graph:
                return {}
            return _posting(name)

        def _kind(kind_pattern):
            matches = [n for n, node in sys._structure.graph.items() if n != "__output__" and kind_pattern in node.kind]
            return _multi_posting(matches)

        def _inputs(name):
            node = sys._structure.graph.get(name)
            if not node:
                return {}
            return _multi_posting(node.inputs)

        def _downstream(name):
            deps = sys._dependents.get(name, [])
            return _multi_posting(deps)

        def _roots():
            root_layer = sys._structure.roots
            if not root_layer:
                return {}
            return _multi_posting(c.name for c in root_layer.consumers)

        def _layer(n):
            n = int(n)
            names = [name for name, depth in sys._structure.depths.items() if depth == n and name != "__output__"]
            return _multi_posting(names)

        def _focus(prefix, posting=None):
            if posting is None:
                matches = [n for n in sys._structure.graph if n != "__output__" and n.startswith(prefix)]
                return _multi_posting(matches)
            prefix_ = {k: v for k, v in posting.items() if k[0].startswith(prefix)}
            return prefix_

        def _depth(name):
            return sys._structure.depths.get(name, -1)

        def _value(name):
            node = sys._structure.graph.get(name)
            if not node:
                return ""
            return str(node.value) if node.value is not None else ""

        def _terms(kind_pattern):
            """Return list of name strings matching kind (not a posting set)."""
            return [n for n, node in sys._structure.graph.items() if n != "__output__" and kind_pattern in node.kind]

        def _quotes(name):
            """Return list of quote strings from atom evidence."""
            node = sys._structure.graph.get(name)
            if not node or not node.atom:
                return []
            origin = getattr(node.atom, "origin", None)
            if origin is None:
                return []
            from parseltongue.core.atoms import Evidence

            if isinstance(origin, Evidence):
                return list(origin.quotes)
            return []

        ops = {
            Symbol("node"): _node,
            Symbol("kind"): _kind,
            Symbol("inputs"): _inputs,
            Symbol("downstream"): _downstream,
            Symbol("roots"): _roots,
            Symbol("layer"): _layer,
            Symbol("focus"): _focus,
            Symbol("depth"): _depth,
            Symbol("value"): _value,
            Symbol("terms"): _terms,
            Symbol("quotes"): _quotes,
        }
        self._system = System(initial_env=ops, docs={}, strict_derive=False, name="LensSearch")
        self.posting_morphism = self._LnPostingMorphism(structure)

        # Wrap evaluate: internal operators use posting sets,
        # but the system produces s-expressions at the boundary
        _raw_eval = self._system.evaluate
        _to_ln = self._posting_to_ln

        def _sexp_evaluate(expr):
            result = _raw_eval(expr)
            if isinstance(result, dict):
                return _to_ln(result)
            return result

        self._system.evaluate = _sexp_evaluate  # type: ignore[method-assign, assignment]

    @property
    def index(self) -> "DocumentIndex":
        return self._idx

    def find(self, pattern: str, max_results: int = 50) -> list[str]:
        """Regex search over node names via the index."""
        import re as _re

        rx = _re.compile(pattern)
        names = sorted(n for n in self._idx.documents if rx.search(n))
        return names[:max_results]

    def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        """Ranked substring search over node names via the index."""
        query_lower = query.lower()
        scored = []
        for name in self._idx.documents:
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

    def evaluate(self, expr, local_env=None):
        """Evaluate a query — string or s-expression."""
        if isinstance(expr, str):
            from parseltongue.core.lang import PGStringParser

            parsed = PGStringParser.translate(expr)
            if isinstance(parsed, str):
                results = self._idx.search(parsed)
                return {(r["document"], r["line"]): r for r in results}
            return self._system.evaluate(parsed)
        return self._system.evaluate(expr)

    class _LnPostingMorphism:
        """PostingMorphism: posting ↔ ln forms."""

        def __init__(self, structure):
            self._structure = structure

        def transform(self, posting: dict) -> list:
            from parseltongue.core.atoms import Symbol

            tag = Symbol("ln")
            result = []
            for name, _line in posting:
                node = self._structure.graph.get(name)
                if not node:
                    continue
                depth = self._structure.depths.get(name, 0)
                value = str(node.value) if node.value is not None else ""
                result.append([tag, name, node.kind, value, depth, list(node.inputs)])
            return result

        def inverse(self, forms: list) -> dict:
            from parseltongue.core.atoms import Symbol

            tag = Symbol("ln")
            posting: dict = {}
            for item in forms:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                if not (isinstance(item[0], Symbol) and BenchSubsystem.matches_tag(item[0], tag)):
                    continue
                name = str(item[1])
                kind = str(item[2]) if len(item) > 2 else ""
                value = str(item[3]) if len(item) > 3 else ""
                posting[(name, 1)] = {
                    "document": name,
                    "line": 1,
                    "column": 1,
                    "context": f"{kind}: {value}" if value else kind,
                    "callers": [],
                    "total_callers": 0,
                }
            return posting

    def _posting_to_ln(self, posting: dict) -> list:
        return self.posting_morphism.transform(posting)
