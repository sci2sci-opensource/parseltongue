"""Consistency screen — tree-based consistency report."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Tree

from ..widgets.hints_bar import HintsBar
from ..widgets.tree_builders import (
    _add_definition_leaf,
    add_diff_result_node,
    add_origin_node,
    origin_color,
)

if TYPE_CHECKING:
    from parseltongue.core.engine import ConsistencyReport
    from parseltongue.llm import PipelineResult


# Display labels for issue types
_ISSUE_LABELS: dict[str, str] = {
    "unverified_evidence": "Unverified Evidence",
    "no_evidence": "No Evidence Provided",
    "potential_fabrication": "Potential Fabrication",
    "diff_divergence": "Diff Divergence",
    "diff_value_divergence": "Diff Value Divergence",
}

# Display labels for warning types
_WARNING_LABELS: dict[str, str] = {
    "manually_verified": "Manually Verified",
}


class ConsistencyScreen(Screen):
    """Displays the system consistency report as a color-coded tree."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        tree: Tree[str] = Tree("Consistency Report", id="consistency-tree")
        tree.root.expand()
        self._populate(tree)
        yield tree
        yield HintsBar(
            [
                ("F1", "Answer", "app.switch_screen('answer')"),
                ("F2", "Passes", "app.switch_screen('passes')"),
                ("F3", "System", "app.switch_screen('system_state')"),
                ("F4", "Consistency", "app.switch_screen('consistency')"),
                ("Esc", "Back", "screen.dismiss"),
            ]
        )

    def _populate(self, tree: Tree[str]) -> None:
        system = self._result.system
        if system is not None:
            report = system.consistency()
            self._build_report_tree(tree, report)
        elif hasattr(self._result, "output") and hasattr(self._result.output, "consistency"):
            text = self._result.output.consistency
            if text:
                tree.root.add_leaf(f"[dim]{rich_escape(text)}[/dim]")
            else:
                tree.root.add_leaf("[dim]No consistency data in history.[/dim]")
        else:
            tree.root.add_leaf("[dim]No live system available (history mode).[/dim]")

    def _build_report_tree(self, tree: Tree[str], report: ConsistencyReport) -> None:
        root = tree.root

        # Status node
        if report.consistent:
            root.add_leaf("[green]Status: Consistent[/green]")
        else:
            root.add_leaf("[red bold]Status: INCONSISTENT[/red bold]")

        # Issues section
        if report.issues:
            total = sum(len(i.items) for i in report.issues)
            issues_node = root.add(f"[red bold]Issues ({total})[/red bold]", expand=True)
            for issue in report.issues:
                self._add_issue_node(issues_node, issue)

        # Warnings section
        if report.warnings:
            total = sum(len(w.items) for w in report.warnings)
            warnings_node = root.add(f"[yellow bold]Warnings ({total})[/yellow bold]", expand=True)
            for warning in report.warnings:
                label = _WARNING_LABELS.get(warning.type, warning.type)
                w_node = warnings_node.add(f"[yellow]{rich_escape(label)}[/yellow]")
                system = self._result.system
                for item in warning.items:
                    item_node = w_node.add(rich_escape(str(item)))
                    _add_definition_leaf(item_node, str(item), system)

        # Contamination graph — trace affected items upward to tainted roots
        system = self._result.system
        if system is not None and report.issues:
            # Collect tainted source names
            tainted: set[str] = set()
            for issue in report.issues:
                if issue.type in ("unverified_evidence", "no_evidence"):
                    tainted.update(str(i) for i in issue.items)

            if tainted:
                terminals = self._find_terminals(tainted, system)
                if terminals:
                    graph_node = root.add(f"[red bold]Contamination ({len(terminals)} endpoints)[/red bold]")
                    for name in terminals:
                        self._add_upstream_trace(graph_node, name, tainted, system, seen=set())

        # All clear
        if not report.issues and not report.warnings:
            root.add_leaf("[green]All checks passed[/green]")

    def _add_issue_node(self, parent, issue) -> None:
        label = _ISSUE_LABELS.get(issue.type, issue.type)

        if issue.type in ("diff_divergence", "diff_value_divergence"):
            # Items are DiffResult objects — delegate to shared builder
            for diff_result in issue.items:
                add_diff_result_node(parent, diff_result, system=self._result.system)
        elif issue.type in ("no_evidence", "potential_fabrication"):
            # Show downstream dependents when expanded
            i_node = parent.add(f"[red]{rich_escape(label)}[/red]")
            system = self._result.system
            for item in issue.items:
                item_name = str(item)
                deps = self._find_downstreams(item_name, system) if system else []
                if deps:
                    item_node = i_node.add(f"[red]{rich_escape(item_name)}[/red]")
                    _add_definition_leaf(item_node, item_name, system)
                    dep_node = item_node.add(f"[dim]affected ({len(deps)})[/dim]")
                    for dep in deps:
                        dep_leaf = dep_node.add(f"[dim]{rich_escape(dep)}[/dim]")
                        _add_definition_leaf(dep_leaf, dep, system)
                else:
                    item_node = i_node.add(f"[red]{rich_escape(item_name)}[/red]")
                    _add_definition_leaf(item_node, item_name, system)
        else:
            # Items are plain strings (names)
            i_node = parent.add(f"[red]{rich_escape(label)}[/red]")
            system = self._result.system
            for item in issue.items:
                item_node = i_node.add(rich_escape(str(item)))
                _add_definition_leaf(item_node, str(item), system)

    @staticmethod
    def _find_downstreams(name: str, system) -> list[str]:
        """Find theorems and diffs that directly depend on *name*."""
        deps: list[str] = []
        for thm_name, thm in system.theorems.items():
            if name in thm.derivation:
                deps.append(thm_name)
        for diff_name, diff in system.diffs.items():
            if diff.get("replace") == name or diff.get("with") == name:
                deps.append(diff_name)
        return deps

    @staticmethod
    def _find_terminals(tainted: set[str], system) -> list[str]:
        """Find terminal affected nodes — nothing derives from them."""
        # BFS forward to find all affected names
        affected: set[str] = set()
        queue = list(tainted)
        while queue:
            name = queue.pop(0)
            for thm_name, thm in system.theorems.items():
                if thm_name not in affected and thm_name not in tainted and name in thm.derivation:
                    affected.add(thm_name)
                    queue.append(thm_name)
            for diff_name, diff in system.diffs.items():
                if (
                    diff_name not in affected
                    and diff_name not in tainted
                    and (diff.get("replace") == name or diff.get("with") == name)
                ):
                    affected.add(diff_name)
                    queue.append(diff_name)
        # Terminal = nothing in (affected | tainted) depends on it
        all_contaminated = affected | tainted
        has_dependents: set[str] = set()
        for name in all_contaminated:
            for thm_name, thm in system.theorems.items():
                if thm_name in all_contaminated and name in thm.derivation:
                    has_dependents.add(name)
            for diff_name, diff in system.diffs.items():
                if diff_name in all_contaminated and (diff.get("replace") == name or diff.get("with") == name):
                    has_dependents.add(name)
        terminals = [n for n in all_contaminated if n not in has_dependents]
        return sorted(terminals)

    @staticmethod
    def _item_color_and_origin(name: str, system) -> tuple[str, object]:
        """Get (origin_color, origin) for any system item by name."""
        for store in (system.terms, system.axioms, system.theorems):
            if name in store:
                origin = store[name].origin
                return origin_color(origin), origin
        if name in system.facts:
            origin = system.facts[name].origin
            return origin_color(origin), origin
        return "white", None

    def _add_upstream_trace(self, parent, name: str, tainted: set[str], system, seen: set[str]) -> None:
        """Recursively trace upward from an affected node to tainted roots."""
        if name in seen:
            parent.add_leaf(f"[dim]{rich_escape(name)} (cycle)[/dim]")
            return
        seen.add(name)

        if name in tainted:
            _, origin = self._item_color_and_origin(name, system)
            node = parent.add(f"[red bold]{rich_escape(name)}[/red bold] [dim](tainted)[/dim]")
            _add_definition_leaf(node, name, system)
            if origin is not None:
                add_origin_node(node, origin)
            return

        # Collect upstream sources
        sources: list[str] = []
        if name in system.theorems:
            sources.extend(system.theorems[name].derivation)
        if name in system.diffs:
            diff = system.diffs[name]
            for src in (diff.get("replace"), diff.get("with")):
                if src:
                    sources.append(src)

        if not sources:
            # Leaf node — show with origin details
            color, origin = self._item_color_and_origin(name, system)
            node = parent.add(f"[{color}]{rich_escape(name)}[/{color}]")
            _add_definition_leaf(node, name, system)
            if origin is not None:
                add_origin_node(node, origin)
            return

        node = parent.add(f"[red]{rich_escape(name)}[/red]")
        _add_definition_leaf(node, name, system)
        for src in sources:
            self._add_upstream_trace(node, src, tainted, system, seen)
