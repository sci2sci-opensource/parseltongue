"""Modal alert shown when history consistency differs from live recomputation."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from ..widgets.diff_table import build_diff_table


class ConsistencyAlert(ModalScreen[bool]):
    """Shows cached vs fresh consistency side-by-side with diff highlights.

    Returns True if user chooses to replace, False to keep cached.
    """

    BINDINGS = [
        ("escape", "keep", "Keep"),
        ("left", "select_replace", "Use Current"),
        ("right", "select_keep", "Keep Cached"),
    ]

    DEFAULT_CSS = """
    ConsistencyAlert {
        align: center middle;
    }

    ConsistencyAlert #alert-box {
        width: 90%;
        height: 80%;
        border: heavy $error;
        background: $surface;
        padding: 1 2;
    }

    ConsistencyAlert #alert-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    ConsistencyAlert #diff-scroll {
        height: 1fr;
    }

    ConsistencyAlert #diff-content {
        width: 1fr;
    }

    ConsistencyAlert #alert-buttons {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    ConsistencyAlert #alert-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, cached: str, fresh: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cached = cached
        self._fresh = fresh

    def compose(self) -> ComposeResult:
        with Vertical(id="alert-box"):
            yield Label("Consistency has changed since this run was saved", id="alert-title")
            with VerticalScroll(id="diff-scroll"):
                yield Static(id="diff-content")
            with Horizontal(id="alert-buttons"):
                yield Button("Use Current", id="replace-btn", variant="warning")
                yield Button("Keep Cached", id="keep-btn", variant="default")

    def on_mount(self) -> None:
        self.query_one("#diff-scroll").can_focus = False
        content = self.query_one("#diff-content", Static)
        content.can_focus = False
        content.update(
            build_diff_table(
                self._cached,
                self._fresh,
                col_a="Cached (original)",
                col_b="Current (recomputed)",
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "replace-btn":
            self.dismiss(True)
        elif event.button.id == "keep-btn":
            self.dismiss(False)

    def action_keep(self) -> None:
        self.dismiss(False)

    def action_select_keep(self) -> None:
        self.query_one("#keep-btn", Button).focus()

    def action_select_replace(self) -> None:
        self.query_one("#replace-btn", Button).focus()
