"""Simple confirmation modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmModal(ModalScreen[bool]):
    """Yes/No confirmation dialog. Returns True on confirm, False on cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }

    ConfirmModal #confirm-box {
        width: 50;
        height: auto;
        border: heavy $warning;
        background: $surface;
        padding: 1 2;
    }

    ConfirmModal #confirm-message {
        margin-bottom: 1;
    }

    ConfirmModal #confirm-buttons {
        height: auto;
        align: center middle;
    }

    ConfirmModal #confirm-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self._message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", id="yes-btn", variant="warning")
                yield Button("No", id="no-btn", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")

    def action_cancel(self) -> None:
        self.dismiss(False)
