"""Query input screen — multiline text area for the user's question."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.events import Key
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Label, TextArea

from ..widgets.hints_bar import HintsBar


class QuerySubmitted(Message):
    """Posted when user submits their query."""

    def __init__(self, query: str) -> None:
        super().__init__()
        self.query = query


class _QueryTextArea(TextArea):
    """TextArea where Shift+Enter submits. Enter stays as newline (default)."""

    class Submitted(Message):
        pass

    async def _on_key(self, event: Key) -> None:
        if event.key in ("shift+enter", "ctrl+d"):
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted())
        else:
            await super()._on_key(event)


class QueryInput(Screen):
    """Multiline text area for the user's question."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("ctrl+d", "submit", "Submit"),
    ]

    def __init__(self, doc_count: int = 0, **kwargs) -> None:
        super().__init__(**kwargs)
        self._doc_count = doc_count

    def compose(self) -> ComposeResult:
        yield Label(
            f"{self._doc_count} document(s) selected.  Type your question below:",
            id="query-label",
        )
        yield _QueryTextArea(id="query-field")
        yield Button("Run Pipeline", id="submit-btn", variant="primary")
        yield HintsBar(
            [
                ("Shift+Enter", "Send"),
                ("Ctrl+D", "Send"),
                ("Enter", "Newline"),
                ("Esc", "Back"),
            ]
        )

    def on_mount(self) -> None:
        self.query_one("#query-field", _QueryTextArea).focus()

    def on__query_text_area_submitted(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            self._submit()

    def action_submit(self) -> None:
        self._submit()

    def _submit(self) -> None:
        field = self.query_one("#query-field", _QueryTextArea)
        query = field.text.strip()
        if not query:
            self.notify("Enter a question.", severity="warning")
            return
        self.post_message(QuerySubmitted(query))
