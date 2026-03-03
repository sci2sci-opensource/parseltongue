"""Query input screen — multiline text area + document list."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Label, ListItem, ListView, TextArea

from ..widgets.hints_bar import HintsBar
from ..widgets.pass_viewer import PassViewer

# Map common extensions to Pygments lexer names
_EXT_LEXERS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".sh": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".xml": "xml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".tex": "latex",
}


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


class DocPreviewModal(ModalScreen):
    """Modal overlay showing a syntax-highlighted document preview."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, name: str, text: str, language: str = "text", **kwargs) -> None:
        super().__init__(**kwargs)
        self._doc_name = name
        self._doc_text = text
        self._language = language

    def compose(self) -> ComposeResult:
        with Container(id="doc-preview-container"):
            with Horizontal(id="doc-preview-header"):
                yield Label(self._doc_name, id="doc-preview-title")
                yield Button("Close", id="doc-preview-close", variant="default")
            yield PassViewer(self._doc_text, language=self._language)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "doc-preview-close":
            self.dismiss()


class QueryInput(Screen):
    """Multiline text area for the user's question, with document list."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("ctrl+d", "submit", "Submit"),
    ]

    def __init__(
        self,
        doc_count: int = 0,
        ingested: dict[str, str] | None = None,
        doc_paths: list[Path] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._doc_count = doc_count
        self._ingested = ingested or {}
        self._doc_paths = doc_paths or []
        # ordered list of (name, text, lexer)
        self._docs: list[tuple[str, str, str]] = []
        for i, (name, text) in enumerate(self._ingested.items()):
            ext = self._doc_paths[i].suffix.lower() if i < len(self._doc_paths) else ""
            lang = _EXT_LEXERS.get(ext, "markdown")
            self._docs.append((name, text, lang))

    def compose(self) -> ComposeResult:
        with Horizontal(id="query-layout"):
            with Container(id="query-panel"):
                yield Label("Query", id="query-label")
                yield _QueryTextArea(id="query-field")
                yield Button("Run Pipeline", id="submit-btn", variant="primary")
            if self._docs:
                with Container(id="docs-panel"):
                    yield Label(f"Documents ({len(self._docs)})", id="docs-label")
                    yield ListView(
                        *[ListItem(Label(name), id=f"doc-{i}") for i, (name, _, _) in enumerate(self._docs)],
                        id="docs-list",
                    )
        yield HintsBar(
            [
                ("Shift+Enter", "Send"),
                ("Ctrl+D", "Send"),
                ("Enter", "Newline / Preview"),
                ("Esc", "Back"),
            ]
        )

    def on_mount(self) -> None:
        self.query_one("#query-field", _QueryTextArea).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Open preview modal when a document is clicked."""
        item_id = event.item.id or ""
        if item_id.startswith("doc-"):
            idx = int(item_id.split("-", 1)[1])
            if 0 <= idx < len(self._docs):
                name, text, lang = self._docs[idx]
                self.app.push_screen(DocPreviewModal(name, text, lang))

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
