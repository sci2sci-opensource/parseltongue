"""Evaluation — consistency view with focus and filtering.

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

Search is handled by EvaluationSearchSystem — register as a scope
in the main search system, or use ``(scope evaluation ...)`` queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


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

    Wraps a LocatedConsistencyReport into a focusable, filterable object.
    """

    def __init__(self, items: list[EvaluationItem], consistent: bool):
        self._items = items
        self._consistent = consistent
        self._search: "EvaluationSearchSystem | None" = None

    @property
    def search_system(self) -> "EvaluationSearchSystem":
        """Lazy-init search system."""
        if self._search is None:
            from .systems.evaluation import EvaluationSearchSystem

            self._search = EvaluationSearchSystem(self)
        return self._search

    def find(self, pattern: str, max_results: int = 50) -> list[str]:
        """Regex search over item names via the search index."""
        return self.search_system.find(pattern, max_results)

    def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        """Ranked substring search over item names via the search index."""
        return self.search_system.fuzzy(query, max_results)

    def search(self, query: str) -> dict:
        """S-expression query against the evaluation search system."""
        return self.search_system.evaluate(query)

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


# EvaluationSearchSystem moved to systems/evaluation.py
# Re-export for backwards compatibility
from .systems.evaluation import EvaluationSearchSystem  # noqa: F401, E402
