"""Answer screen — main split-pane with markdown + provenance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen

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
        ("f11", "grow_right", "F11 Grow right"),
        ("f12", "grow_left", "F12 Grow left"),
    ]

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        with Container(id="markdown-panel"):
            yield ReferenceText(str(self._result.output))
        with Container(id="provenance-panel"):
            yield ProvenanceTree(id="provenance-tree")
        yield StatusBar(extra_hints=[("F11/F12", "Resize")])

    def on_reference_clicked(self, event: ReferenceClicked) -> None:
        """When a reference tag is clicked, show its full provenance."""
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
