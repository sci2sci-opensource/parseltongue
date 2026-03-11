"""Simple text input modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class InputModal(ModalScreen[str | None]):
    """Prompt for a single text value. Returns the string or None on cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    InputModal {
        align: center middle;
    }
    InputModal #input-box {
        width: 60;
        height: auto;
        border: heavy $primary;
        background: $surface;
        padding: 1 2;
    }
    InputModal #input-label {
        margin-bottom: 1;
    }
    InputModal #input-field {
        margin-bottom: 1;
    }
    """

    def __init__(self, prompt: str, default: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._prompt = prompt
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="input-box"):
            yield Label(self._prompt, id="input-label")
            yield Input(value=self._default, id="input-field")
            yield Button("OK", id="ok-btn", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#input-field", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.query_one("#input-field", Input).value)

    def action_cancel(self) -> None:
        self.dismiss(None)
