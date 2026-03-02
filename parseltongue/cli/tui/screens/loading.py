"""Loading screen — shown while the pipeline is running."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Label, LoadingIndicator


class LoadingScreen(Screen):
    """Displays a spinner and status text while the pipeline runs."""

    def compose(self) -> ComposeResult:
        with Container(id="spinner-container"):
            yield LoadingIndicator()
            yield Label("Starting pipeline...", id="status-label")

    def update_status(self, message: str) -> None:
        label = self.query_one("#status-label", Label)
        label.update(message)
