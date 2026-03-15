"""Bench screen — interactive inspection of a running pg-bench daemon.

Provides tabbed access to the bench's core features:
- Search: full-text search with S-expression queries
- Lens: structural navigation (find, view, subgraph)
- Evaluation: consistency diagnosis
- Eval: S-expression evaluation
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.widgets.option_list import Option

from ..bench_client import BenchClient, BenchClientError


class BenchScreen(Screen):
    """Main bench inspection screen with tabbed interface."""

    BINDINGS = [
        Binding("ctrl+s", "focus_tab('search')", "Search", show=False),
        Binding("ctrl+l", "focus_tab('lens')", "Lens", show=False),
        Binding("ctrl+d", "focus_tab('diagnosis')", "Diagnosis", show=False),
        Binding("ctrl+e", "focus_tab('eval')", "Eval", show=False),
        Binding("ctrl+r", "reload", "Reload"),
        Binding("escape", "dismiss", "Back"),
    ]

    DEFAULT_CSS = """
    BenchScreen {
        layout: vertical;
    }
    #bench-status {
        dock: top;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    #bench-status.connected {
        background: $success-darken-2;
    }
    #bench-status.error {
        background: $error-darken-2;
    }
    .query-input {
        dock: top;
        height: 3;
        margin: 0 0 1 0;
    }
    .result-area {
        height: 1fr;
    }
    .result-area TextArea {
        height: 1fr;
    }
    .result-list {
        height: 1fr;
    }
    .side-panel {
        width: 30;
        border-left: solid $primary;
    }
    .side-panel OptionList {
        height: 1fr;
    }
    """

    def __init__(self, client: BenchClient | None = None) -> None:
        super().__init__()
        self._client = client or BenchClient()
        self._search_offset = 0
        self._search_query = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("bench: connecting...", id="bench-status")
        with TabbedContent(id="bench-tabs"):
            with TabPane("Search", id="search"):
                yield Input(
                    placeholder='search query — "text" or (in "file" "term")', id="search-input", classes="query-input"
                )
                with Horizontal():
                    yield TextArea(id="search-results", classes="result-area", read_only=True, language="markdown")
                    with Vertical(classes="side-panel"):
                        yield Label("[b]Names[/b]")
                        yield OptionList(id="search-names")
            with TabPane("Lens", id="lens"):
                yield Input(
                    placeholder="find/fuzzy/view — enter a name or pattern", id="lens-input", classes="query-input"
                )
                with Horizontal():
                    yield TextArea(id="lens-results", classes="result-area", read_only=True, language="markdown")
                    with Vertical(classes="side-panel"):
                        yield Label("[b]Graph[/b]")
                        yield OptionList(id="lens-names")
            with TabPane("Diagnosis", id="diagnosis"):
                yield Input(
                    placeholder="focus namespace (optional) — e.g. engine.", id="dx-input", classes="query-input"
                )
                yield TextArea(id="dx-results", classes="result-area", read_only=True, language="markdown")
            with TabPane("Eval", id="eval"):
                yield Input(
                    placeholder="S-expression — (+ 1 2), (counting.sum-values x y)",
                    id="eval-input",
                    classes="query-input",
                )
                yield TextArea(id="eval-results", classes="result-area", read_only=True, language="markdown")
        yield Footer()

    def on_mount(self) -> None:
        self._check_connection()

    # ── Connection ──

    @work(exclusive=True, group="status")
    async def _check_connection(self) -> None:
        status_bar = self.query_one("#bench-status", Static)
        try:
            text = await self._client.ping()
            if text == "pong":
                status_bar.update("bench: connected")
                status_bar.set_classes("connected")
                self._load_initial()
            else:
                status_bar.update(f"bench: {text}")
        except BenchClientError as e:
            status_bar.update(f"bench: {e}")
            status_bar.set_classes("error")

    @work(exclusive=True, group="initial")
    async def _load_initial(self) -> None:
        """Load initial data into panels."""
        try:
            # Populate lens names
            names = await self._client.find("", max_results=200)
            name_list = self.query_one("#lens-names", OptionList)
            name_list.clear_options()
            for name in names:
                name_list.add_option(Option(name, id=name))

            # Load diagnosis summary
            dx_text = await self._client.diagnose()
            self.query_one("#dx-results", TextArea).load_text(dx_text)

            # Load kinds overview into lens
            kinds_text = await self._client.view_kinds()
            self.query_one("#lens-results", TextArea).load_text(kinds_text)
        except BenchClientError:
            pass

    # ── Input handlers ──

    def on_input_submitted(self, event: Input.Submitted) -> None:
        input_id = event.input.id
        query = event.value.strip()
        if not query and input_id != "dx-input":
            return
        if input_id == "search-input":
            self._do_search(query)
        elif input_id == "lens-input":
            self._do_lens(query)
        elif input_id == "dx-input":
            self._do_diagnose(query)
        elif input_id == "eval-input":
            self._do_eval(query)

    # ── Search ──

    @work(exclusive=True, group="search")
    async def _do_search(self, query: str) -> None:
        results_area = self.query_one("#search-results", TextArea)
        names_list = self.query_one("#search-names", OptionList)
        results_area.load_text("Searching...")
        try:
            self._search_query = query
            self._search_offset = 0
            lines = await self._client.search(query)
            results_area.load_text("\n".join(lines) if lines else "No results.")
            # Extract names from callers [name1, name2] in results
            names_list.clear_options()
            seen: set[str] = set()
            for line in lines:
                if "[" in line and "]" in line:
                    bracket = line[line.index("[") + 1 : line.index("]")]
                    for name in bracket.split(", "):
                        name = name.strip()
                        if name and name not in seen:
                            seen.add(name)
                            names_list.add_option(Option(name, id=name))
        except BenchClientError as e:
            results_area.load_text(f"Error: {e}")

    # ── Lens ──

    @work(exclusive=True, group="lens")
    async def _do_lens(self, query: str) -> None:
        results_area = self.query_one("#lens-results", TextArea)
        results_area.load_text("Loading...")
        try:
            # Decide what to do based on query shape
            if query.startswith("/find ") or query.startswith("find "):
                pattern = query.split(None, 1)[1] if " " in query else ""
                names = await self._client.find(pattern)
                results_area.load_text("\n".join(names) if names else "No matches.")
            elif query.startswith("/fuzzy ") or query.startswith("fuzzy "):
                q = query.split(None, 1)[1] if " " in query else ""
                names = await self._client.fuzzy(q)
                results_area.load_text("\n".join(names) if names else "No matches.")
            elif query.startswith("/consumer ") or query.startswith("consumer "):
                name = query.split(None, 1)[1].strip()
                text = await self._client.view_consumer(name)
                results_area.load_text(text)
            elif query.startswith("/inputs ") or query.startswith("inputs "):
                name = query.split(None, 1)[1].strip()
                text = await self._client.view_inputs(name)
                results_area.load_text(text)
            elif query.startswith("/subgraph ") or query.startswith("subgraph "):
                parts = query.split()
                name = parts[1] if len(parts) > 1 else ""
                direction = parts[2] if len(parts) > 2 else "upstream"
                text = await self._client.view_subgraph(name, direction)
                results_area.load_text(text)
            elif query.startswith("/focus ") or query.startswith("focus "):
                name = query.split(None, 1)[1].strip()
                text = await self._client.focus(name)
                results_area.load_text(text)
            elif query == "kinds":
                text = await self._client.view_kinds()
                results_area.load_text(text)
            elif query == "roots":
                text = await self._client.view_roots()
                results_area.load_text(text)
            else:
                # Default: view node
                text = await self._client.view(query)
                results_area.load_text(text)
        except BenchClientError as e:
            results_area.load_text(f"Error: {e}")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Click a name in a side panel to view it."""
        name = str(event.option.id)
        if event.option_list.id == "search-names":
            # View the selected name in lens
            tabs = self.query_one("#bench-tabs", TabbedContent)
            tabs.active = "lens"
            self.query_one("#lens-input", Input).value = name
            self._do_lens(name)
        elif event.option_list.id == "lens-names":
            self.query_one("#lens-input", Input).value = name
            self._do_lens(name)

    # ── Diagnosis ──

    @work(exclusive=True, group="diagnosis")
    async def _do_diagnose(self, focus: str) -> None:
        results_area = self.query_one("#dx-results", TextArea)
        results_area.load_text("Diagnosing...")
        try:
            text = await self._client.diagnose(focus=focus if focus else None)
            results_area.load_text(text)
        except BenchClientError as e:
            results_area.load_text(f"Error: {e}")

    # ── Eval ──

    @work(exclusive=True, group="eval")
    async def _do_eval(self, expression: str) -> None:
        results_area = self.query_one("#eval-results", TextArea)
        results_area.load_text("Evaluating...")
        try:
            text = await self._client.eval(expression)
            results_area.load_text(text)
        except BenchClientError as e:
            results_area.load_text(f"Error: {e}")

    # ── Actions ──

    def action_focus_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#bench-tabs", TabbedContent)
        tabs.active = tab_id

    @work(exclusive=True, group="reload")
    async def action_reload(self) -> None:
        status_bar = self.query_one("#bench-status", Static)
        status_bar.update("bench: reloading...")
        try:
            text = await self._client.reload()
            status_bar.update(f"bench: {text}")
            status_bar.set_classes("connected")
            self._load_initial()
        except BenchClientError as e:
            status_bar.update(f"bench: {e}")
            status_bar.set_classes("error")
