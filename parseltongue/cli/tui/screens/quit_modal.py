"""Quit confirmation modal — Ctrl+Q or Esc on main menu."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class QuitModal(ModalScreen[bool]):
    """Exit confirmation. Quit button is focused so Enter confirms.

    Second Ctrl+Q while modal is open also confirms exit.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+q", "confirm", "Quit"),
    ]

    DEFAULT_CSS = """
    QuitModal {
        align: center middle;
    }

    QuitModal #quit-box {
        width: 45;
        height: auto;
        border: heavy $error;
        background: $surface;
        padding: 1 2;
    }

    QuitModal #quit-message {
        margin-bottom: 1;
    }

    QuitModal #quit-buttons {
        height: auto;
        align: center middle;
    }

    QuitModal #quit-buttons Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-box"):
            yield Label("Exit Parseltongue?", id="quit-message")
            with Horizontal(id="quit-buttons"):
                yield Button("Quit", id="quit-yes", variant="error")
                yield Button("Cancel", id="quit-no", variant="default")

    def on_mount(self) -> None:
        self.query_one("#quit-yes", Button).focus()

    def on_key(self, event: Key) -> None:
        if event.key in ("left", "right"):
            event.prevent_default()
            event.stop()
            buttons = list(self.query(Button))
            focused = self.focused
            if focused is not None and focused in buttons:
                idx = buttons.index(focused)  # type: ignore[arg-type]
                nxt = (idx + (1 if event.key == "right" else -1)) % len(buttons)
                buttons[nxt].focus()
            elif buttons:
                buttons[0].focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "quit-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)
