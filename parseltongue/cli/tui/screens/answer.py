"""Answer screen — main split-pane with markdown + provenance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Label

from ..widgets.provenance_tree import ProvenanceTree
from ..widgets.reference_text import ReferenceClicked, ReferenceText
from ..widgets.resizable_split import ResizableSplitMixin
from ..widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from parseltongue.llm import PipelineResult


class AnswerScreen(ResizableSplitMixin, Screen):
    """Main answer view: markdown on the left, provenance on the right."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("ctrl+a", "copy_answer", "Copy answer"),
        ("shift+f11", "grow_right", "Shift+F11 Grow right"),
        ("shift+f12", "grow_left", "Shift+F12 Grow left"),
    ]

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        with Container(id="markdown-panel"):
            yield Label("Report", id="report-title")
            yield ReferenceText(str(self._result.output))
        with Container(id="provenance-panel"):
            yield Label("Parseltongue Provenance", id="provenance-title")
            yield ProvenanceTree(id="provenance-tree")
        yield StatusBar(extra_hints=[("Shift+F11/F12", "Resize")])

    def on_reference_clicked(self, event: ReferenceClicked) -> None:
        """When a reference tag is clicked, show its full provenance."""
        ref_text = self.query_one(ReferenceText)
        ref_text.highlight_ref(event.ref_type, event.ref_name)

        tree = self.query_one("#provenance-tree", ProvenanceTree)
        system = self._result.system

        # Prefer live system lookup for full provenance depth
        if system is not None:
            tree.show_system_item(event.ref_type, event.ref_name, system)
            return

        # Fallback for history mode: use resolved reference data
        ref = self._find_reference(event.ref_type, event.ref_name)
        if ref:
            tree.show_reference(
                ref.type,
                ref.name,
                value=ref.value,
                provenance=ref.provenance,
                error=ref.error,
            )
        else:
            tree.show_reference(event.ref_type, event.ref_name, error="Not found")

    def action_copy_answer(self) -> None:
        text = str(self._result.output) if self._result.output else ""
        self.app.copy_to_clipboard(text)
        self.notify("Answer copied to clipboard.")

    def _find_reference(self, ref_type: str, ref_name: str):
        """Find a resolved reference by type and name."""
        for ref in self._result.output.references:
            if ref.type == ref_type and ref.name == ref_name:
                return ref
        return None
