"""Evaluation — consistency view with focus, search, and filtering.

Like Lens is for structure, Evaluation is for health. Prepare a sample
on the bench, then evaluate it.

Usage::

    bench = Bench()
    bench.prepare("core_clean.pltg")
    dx = bench.evaluate()

    dx.summary()                       # overview with counts by category
    dx.issues()                        # all issues
    dx.issues(kind="diff")             # only diff issues
    dx.warnings(namespace="engine.")   # engine warnings
    dx.danglings(kind="derive")        # unused derives
    dx.focus("readme.")                # narrow to namespace → new Evaluation
    dx.find("count")                   # regex over all names in the report
    dx.fuzzy("special")               # substring match
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from parseltongue import System

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.index import DocumentIndex


@dataclass
class EvaluationItem:
    """A single item in the evaluation — issue, warning, or dangling."""

    name: str
    category: str  # "issue", "warning", "dangling", "loader"
    type: str  # IssueType/WarningType value or "dangling"
    kind: str | None  # directive kind: fact, axiom, derive, diff, ...
    loc: str  # file:line
    detail: Any = None  # original item for drill-down

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "type": self.type,
            "kind": self.kind,
            "loc": self.loc,
            "detail": str(self.detail) if self.detail else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvaluationItem":
        return cls(
            name=d["name"],
            category=d["category"],
            type=d["type"],
            kind=d.get("kind"),
            loc=d["loc"],
            detail=d.get("detail"),
        )


class Evaluation:
    """Consistency view — the health side of observation.

    Wraps a LocatedConsistencyReport into a searchable, focusable object.
    """

    def __init__(self, items: list[EvaluationItem], consistent: bool):
        self._items = items
        self._consistent = consistent
        self._names: set[str] = {item.name for item in items}

    @classmethod
    def from_report(cls, lc, result=None) -> "Evaluation":
        """Build from a LocatedConsistencyReport + LazyLoadResult."""
        items: list[EvaluationItem] = []

        if result is not None:
            # Loader errors (failed directives)
            for node, exc in result.errors.items():
                loc = f"{node.source_file}:{node.source_line}" if node.source_file else "?"
                items.append(
                    EvaluationItem(
                        name=node.name or str(exc)[:60],
                        category="loader",
                        type="error",
                        kind=node.kind if node.name else "effect",
                        loc=loc,
                        detail=exc,
                    )
                )

            # Loader skips (cascading from errors)
            for node, cause in result.skipped.items():
                loc = f"{node.source_file}:{node.source_line}" if node.source_file else "?"
                items.append(
                    EvaluationItem(
                        name=node.name or "?",
                        category="loader",
                        type="skipped",
                        kind=node.kind,
                        loc=loc,
                        detail=f"dependency '{cause.name}' failed",
                    )
                )

            # Loader warnings (duplicates, etc.)
            for msg, source_file, source_line in result.loader_warnings:
                loc = f"{source_file}:{source_line}" if source_file else "?"
                items.append(
                    EvaluationItem(
                        name=msg,
                        category="loader",
                        type="warning",
                        kind=None,
                        loc=loc,
                        detail=msg,
                    )
                )

        for issue, located in lc.located_issues():
            for li in located:
                items.append(
                    EvaluationItem(
                        name=li.name,
                        category="issue",
                        type=issue.type.value,
                        kind=li.kind,
                        loc=li.loc,
                        detail=li.item,
                    )
                )

        for warning, located in lc.located_warnings():
            for li in located:
                items.append(
                    EvaluationItem(
                        name=li.name,
                        category="warning",
                        type=warning.type.value,
                        kind=li.kind,
                        loc=li.loc,
                        detail=li.item,
                    )
                )

        for d in lc.danglings():
            items.append(
                EvaluationItem(
                    name=d.name,
                    category="dangling",
                    type="dangling",
                    kind=d.kind,
                    loc=d.loc,
                    detail=d.item,
                )
            )

        return cls(items, lc.consistent)

    # ── Filter ──

    @property
    def _all_kinds(self) -> set[str]:
        return {i.kind for i in self._items if i.kind}

    @property
    def _all_types(self) -> set[str]:
        return {i.type for i in self._items}

    @property
    def _all_namespaces(self) -> set[str]:
        return {i.name.split(".")[0] for i in self._items if "." in i.name}

    def _suggest_kind(self, kind: str) -> str:
        available = sorted(self._all_kinds)
        return f"No items with kind={kind!r}. Available kinds: {', '.join(available)}"

    def _suggest_type(self, typ: str) -> str:
        available = sorted(self._all_types)
        return f"No items with type={typ!r}. Available types: {', '.join(available)}"

    def _suggest_namespace(self, namespace: str) -> str:
        available = sorted(self._all_namespaces)
        prefix = namespace.rstrip(".")
        close = [ns for ns in available if prefix[:3] in ns or ns[:3] in prefix]
        if close:
            return f"No items in namespace {namespace!r}. Similar: {', '.join(close)}"
        return f"No items in namespace {namespace!r}. Available: {', '.join(available)}"

    def _filter(
        self,
        category: str | None = None,
        kind: str | None = None,
        type: str | None = None,
        namespace: str | None = None,
    ) -> list[EvaluationItem]:
        result = self._items
        if category:
            result = [i for i in result if i.category == category]
        if kind:
            filtered = [i for i in result if i.kind == kind]
            if not filtered and kind not in self._all_kinds:
                raise ValueError(self._suggest_kind(kind))
            result = filtered
        if type:
            filtered = [i for i in result if i.type == type]
            if not filtered and type not in self._all_types:
                raise ValueError(self._suggest_type(type))
            result = filtered
        if namespace:
            filtered = [i for i in result if i.name.startswith(namespace)]
            if not filtered and not any(i.name.startswith(namespace) for i in self._items):
                raise ValueError(self._suggest_namespace(namespace))
            result = filtered
        return result

    def issues(
        self, kind: str | None = None, type: str | None = None, namespace: str | None = None
    ) -> list[EvaluationItem]:
        """All issues, optionally filtered."""
        return self._filter(category="issue", kind=kind, type=type, namespace=namespace)

    def warnings(
        self, kind: str | None = None, type: str | None = None, namespace: str | None = None
    ) -> list[EvaluationItem]:
        """All warnings, optionally filtered."""
        return self._filter(category="warning", kind=kind, type=type, namespace=namespace)

    def danglings(self, kind: str | None = None, namespace: str | None = None) -> list[EvaluationItem]:
        """Dangling definitions (consumed by nothing)."""
        return self._filter(category="dangling", kind=kind, namespace=namespace)

    def loader(self) -> list[EvaluationItem]:
        """Loader warnings (duplicates, failed effects, etc.)."""
        return self._filter(category="loader")

    @property
    def consistent(self) -> bool:
        return self._consistent

    # ── Focus ──

    def focus(self, namespace: str) -> "Evaluation":
        """Narrow to a namespace prefix — returns a new Evaluation."""
        filtered = [i for i in self._items if i.name.startswith(namespace)]
        has_issues = any(i.category == "issue" for i in filtered)
        return Evaluation(filtered, consistent=not has_issues)

    # ── Search ──

    def find(self, pattern: str, max_results: int = 50) -> list[str]:
        """Regex search over all names in the evaluation."""
        rx = re.compile(pattern)
        return sorted(name for name in self._names if rx.search(name))[:max_results]

    def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        """Substring match, ranked by relevance."""
        query_lower = query.lower()
        scored = []
        for name in self._names:
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

    # ── Statistics ──

    def stats(self) -> dict[str, dict[str, int]]:
        """Counts broken down by multiple dimensions.

        Returns dict with keys:
        - ``"by_category"``: issue/warning/dangling → count
        - ``"by_type"``: issue_type/warning_type → count
        - ``"by_kind"``: directive kind → count
        - ``"by_namespace"``: top-level namespace → count
        - ``"by_file"``: source file → count
        """
        by_category: dict[str, int] = {}
        by_type: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        by_namespace: dict[str, int] = {}
        by_file: dict[str, int] = {}

        for item in self._items:
            by_category[item.category] = by_category.get(item.category, 0) + 1
            by_type[item.type] = by_type.get(item.type, 0) + 1
            k = item.kind or "?"
            by_kind[k] = by_kind.get(k, 0) + 1
            ns = item.name.split(".")[0] if "." in item.name else "_root"
            by_namespace[ns] = by_namespace.get(ns, 0) + 1
            f = item.loc.rsplit(":", 1)[0] if ":" in item.loc else item.loc
            by_file[f] = by_file.get(f, 0) + 1

        return {
            "by_category": dict(sorted(by_category.items())),
            "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
            "by_kind": dict(sorted(by_kind.items(), key=lambda x: -x[1])),
            "by_namespace": dict(sorted(by_namespace.items(), key=lambda x: -x[1])),
            "by_file": dict(sorted(by_file.items(), key=lambda x: -x[1])),
        }

    # ── View ──

    def summary(self) -> str:
        """Counts by category and type, grouped by directive kind."""
        if self._consistent and not self._items:
            return "Clean. No issues, no warnings, no danglings."

        lines = []

        # Counts
        n_issues = len(self.issues())
        n_warnings = len(self.warnings())
        n_danglings = len(self.danglings())
        parts = []
        if n_issues:
            parts.append(f"{n_issues} issue(s)")
        if n_warnings:
            parts.append(f"{n_warnings} warning(s)")
        if n_danglings:
            parts.append(f"{n_danglings} dangling(s)")
        if not parts:
            return "Clean."
        lines.append(", ".join(parts))
        lines.append("")

        # Group by (category, type)
        groups: dict[tuple[str, str], list[EvaluationItem]] = {}
        for item in self._items:
            groups.setdefault((item.category, item.type), []).append(item)

        for (cat, typ), group in sorted(groups.items()):
            lines.append(f"[{cat}] {typ} ({len(group)}):")
            by_kind: dict[str, list[EvaluationItem]] = {}
            for item in group:
                by_kind.setdefault(item.kind or "?", []).append(item)
            for k, items in sorted(by_kind.items()):
                if len(by_kind) > 1:
                    lines.append(f"  {k}:")
                    for item in items:
                        lines.append(f"    {item.name} @ {item.loc}")
                else:
                    for item in items:
                        lines.append(f"  {item.name} @ {item.loc}")

        return "\n".join(lines)

    # ── Incremental ──

    # Categories that are fully recomputed by _check_evidence
    _EVIDENCE_TYPES = frozenset(
        {
            "unverified_evidence",
            "no_evidence",
            "manually_verified",
            "potential_fabrication",
        }
    )

    def incremental(self, diffs_to_patch: set[str], lc) -> "Evaluation":
        """Return new Evaluation patching only specific diffs.

        Keeps items from self except:
        - items whose name is in diffs_to_patch (re-evaluated)
        - evidence/fabrication items (fully recomputed in lc)

        Fresh items come from the partial LocatedConsistencyReport.
        Loader items (errors, skips, warnings) are kept from self.
        """
        kept = [i for i in self._items if i.name not in diffs_to_patch and i.type not in self._EVIDENCE_TYPES]
        fresh = Evaluation.from_report(lc)
        merged = kept + fresh._items
        has_issues = any(i.category == "issue" for i in merged)
        return Evaluation(merged, consistent=not has_issues)

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {"items": [i.to_dict() for i in self._items], "consistent": self._consistent}

    @classmethod
    def from_dict(cls, d: dict) -> "Evaluation":
        items = [EvaluationItem.from_dict(i) for i in d["items"]]
        return cls(items, d["consistent"])

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return len(self._items) > 0

    def __repr__(self) -> str:
        parts = []
        n = len(self.loader())
        if n:
            parts.append(f"{n} loader")
        parts.append(f"{len(self.issues())} issues")
        parts.append(f"{len(self.warnings())} warnings")
        parts.append(f"{len(self.danglings())} danglings")
        return f"Evaluation({', '.join(parts)})"

    def to_search_scope(self) -> tuple["DocumentIndex", System]:
        """Build a EvaluationSearchSystem. Returns (index, system) for scope registration."""
        ds = EvaluationSearchSystem(self)
        return ds._idx, ds._system


class EvaluationSearchSystem:
    """Parseltongue System with posting-set operators over evaluation data.

    Operators:
        (kind "diff")      — items matching directive kind
        (category "issue") — items in a category
        (type "diverge")   — items matching issue/warning type (substring)
    """

    def __init__(self, dx: Evaluation):
        from parseltongue.core.atoms import Symbol
        from parseltongue.core.quote_verifier.index import DocumentIndex

        self._idx = DocumentIndex()

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
        item_index: dict[tuple[str, int], EvaluationItem] = {}
        for item in dx._items:
            cat = item.category
            cat_items = [i for i in dx._items if i.category == cat]
            line_num = cat_items.index(item) + 1
            item_index[(cat, line_num)] = item

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

        def _kind(kind_pattern):
            def _filter(posting=None):
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

            return _filter

        def _category(cat_name):
            def _filter(posting=None):
                if posting is None:
                    return {k: _posting(k) for k, it in item_index.items() if it.category == cat_name and _posting(k)}
                return {k: v for k, v in posting.items() if k in item_index and item_index[k].category == cat_name}

            return _filter

        def _type(type_pattern):
            def _filter(posting=None):
                if posting is None:
                    return {k: _posting(k) for k, it in item_index.items() if type_pattern in it.type and _posting(k)}
                return {k: v for k, v in posting.items() if k in item_index and type_pattern in item_index[k].type}

            return _filter

        ops = {
            Symbol("kind"): _kind,
            Symbol("category"): _category,
            Symbol("type"): _type,
        }
        self._system = System(initial_env=ops)
