"""Consistency screen — color-coded consistency report."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Markdown

from ..widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from parseltongue.llm import PipelineResult


class ConsistencyScreen(Screen):
    """Displays the system consistency report with color coding."""

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        report = self._result.system.consistency()
        md = self._render_report(report)
        yield Markdown(md)
        yield StatusBar()

    def _render_report(self, report) -> str:
        """Convert ConsistencyReport to styled markdown."""
        lines = ["# Consistency Report\n"]

        if report.consistent:
            lines.append("**Status: Consistent**\n")
        else:
            lines.append("**Status: INCONSISTENT**\n")

        if report.issues:
            lines.append("## Issues\n")
            for issue in report.issues:
                lines.append(f"### {issue.type}\n")
                for item in issue.items:
                    lines.append(f"- {item}\n")

        if report.warnings:
            lines.append("## Warnings\n")
            for warning in report.warnings:
                lines.append(f"### {warning.type}\n")
                for item in warning.items:
                    lines.append(f"- {item}\n")

        if not report.issues and not report.warnings:
            lines.append("No issues or warnings found.\n")

        return "\n".join(lines)
