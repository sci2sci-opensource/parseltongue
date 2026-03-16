"""Bench screen — interactive inspection of a running pg-bench daemon.

Provides tabbed access to the bench's core features:
- Search: full-text search with S-expression queries
- Lens: structural navigation (find, view, subgraph)
- Evaluation: consistency diagnosis
- Eval: S-expression evaluation
"""

from __future__ import annotations

from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Label, Static, TabbedContent, TabPane, Tree

from rich.markup import escape as rich_escape

from ..bench_client import BenchClient, BenchClientError
from ..pltg_highlight import PygmentsTextArea
from ..widgets import FocusedTree
from ..widgets.highlighted_log import HighlightedLog
from ..widgets.hints_bar import HintsBar

# ── Query input: scheme-highlighted, single-line, Enter submits ──


class _QuerySubmitted(Message):
    """Posted when user presses Enter in a query box."""

    def __init__(self, query_id: str, value: str) -> None:
        super().__init__()
        self.query_id = query_id
        self.value = value


class QueryBox(PygmentsTextArea):
    """Single-line scheme-highlighted input. Enter submits, no newlines."""

    DEFAULT_CSS = """
    QueryBox {
        height: 3;
        margin: 0 0 1 0;
        border-title-color: $text-muted;
    }
    """

    def __init__(self, placeholder: str = "", query_id: str = "", **kwargs) -> None:
        super().__init__("", pygments_lexer="scheme", **kwargs)
        self._query_id = query_id
        self._placeholder = placeholder

    def on_mount(self) -> None:
        self.border_title = f"[dim]{self._placeholder}[/dim]"

    def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.document.text.strip()
            self.post_message(_QuerySubmitted(self._query_id, text))
            return
        super()._on_key(event)


class BenchScreen(Screen):
    """Main bench inspection screen with tabbed interface."""

    BINDINGS = [
        Binding("ctrl+s", "focus_tab('search')", "Search", show=False),
        Binding("ctrl+l", "focus_tab('lens')", "Lens", show=False),
        Binding("ctrl+d", "focus_tab('diagnosis')", "Diagnosis", show=False),
        Binding("ctrl+e", "focus_tab('eval')", "Eval", show=False),
        Binding("ctrl+r", "reload", "Reload"),
        Binding("left", "search_prev", "Prev", show=False),
        Binding("right", "search_next", "Next", show=False),
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
    .side-panel {
        width: 30;
        border-left: solid $primary;
    }
    """

    SEARCH_PAGE_SIZE = 20

    def __init__(self, client: BenchClient | None = None) -> None:
        super().__init__()
        self._client = client or BenchClient()
        self._search_offset = 0
        self._search_query = ""

    def compose(self) -> ComposeResult:
        yield Static("bench: connecting...", id="bench-status")
        with TabbedContent(id="bench-tabs"):
            with TabPane("Search", id="search"):
                yield QueryBox(
                    placeholder='search — "text" or (in "file" "term")',
                    query_id="search",
                    id="search-input",
                )
                with Horizontal():
                    yield HighlightedLog(id="search-results", language="markdown")
                    with Vertical(classes="side-panel"):
                        yield Label("[b]Names[/b]")
                        yield FocusedTree("Names", id="search-names", require_focus=False)
            with TabPane("Lens", id="lens"):
                yield QueryBox(
                    placeholder="find/fuzzy/view — name or pattern",
                    query_id="lens",
                    id="lens-input",
                )
                with Horizontal():
                    yield HighlightedLog(id="lens-results", language="markdown")
                    with Vertical(classes="side-panel"):
                        yield Label("[b]Graph[/b]")
                        yield FocusedTree("Graph", id="lens-names", require_focus=False)
            with TabPane("Diagnosis", id="diagnosis"):
                yield QueryBox(
                    placeholder="focus namespace (optional) — e.g. engine.",
                    query_id="diagnosis",
                    id="dx-input",
                )
                yield HighlightedLog(id="dx-results", language="markdown")
            with TabPane("Eval", id="eval"):
                yield QueryBox(
                    placeholder="S-expression — (+ 1 2), (counting.sum-values x y)",
                    query_id="eval",
                    id="eval-input",
                )
                yield HighlightedLog(id="eval-results", language="markdown")
        yield HintsBar(
            [
                ("Ctrl+S", "Search", "screen.focus_tab('search')"),
                ("Ctrl+L", "Lens", "screen.focus_tab('lens')"),
                ("Ctrl+D", "Diagnosis", "screen.focus_tab('diagnosis')"),
                ("Ctrl+E", "Eval", "screen.focus_tab('eval')"),
                ("Left/Right", "Page"),
                ("Ctrl+R", "Reload", "screen.reload"),
                ("Esc", "Back", "screen.dismiss"),
            ]
        )

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
            names = await self._client.find("", max_results=200)
            self._populate_name_tree(self.query_one("#lens-names", FocusedTree), names)

            dx_text = await self._client.diagnose()
            self.query_one("#dx-results", HighlightedLog).set_content(dx_text)

            kinds_text = await self._client.view_kinds()
            self.query_one("#lens-results", HighlightedLog).set_content(kinds_text)
        except BenchClientError:
            pass

    # ── Tree helpers ──

    @staticmethod
    def _populate_name_tree(tree: FocusedTree, names: list[str]) -> None:
        """Group names by dotted namespace prefix into expandable branches."""
        tree.clear()
        tree.root.expand()
        if not names:
            tree.root.add_leaf("[dim]empty[/dim]")
            return

        # Group by namespace (first dotted component)
        groups: dict[str, list[str]] = {}
        for name in names:
            if "." in name:
                ns, leaf = name.rsplit(".", 1)
            else:
                ns, leaf = "", name
            groups.setdefault(ns, []).append(name)

        if len(groups) == 1:
            # Single namespace — flat list
            for name in names:
                tree.root.add_leaf(rich_escape(name))
        else:
            # Multiple namespaces — grouped branches
            for ns in sorted(groups):
                if ns:
                    branch = tree.root.add(f"[bold]{rich_escape(ns)}[/bold] [dim]({len(groups[ns])})[/dim]")
                else:
                    branch = tree.root.add(f"[bold](root)[/bold] [dim]({len(groups[ns])})[/dim]")
                for name in sorted(groups[ns]):
                    branch.add_leaf(rich_escape(name))
                branch.expand()

    # ── Input handlers ──

    def on__query_submitted(self, event: _QuerySubmitted) -> None:
        query = event.value
        if not query and event.query_id != "diagnosis":
            return
        if event.query_id == "search":
            self._do_search(query)
        elif event.query_id == "lens":
            self._do_lens(query)
        elif event.query_id == "diagnosis":
            self._do_diagnose(query)
        elif event.query_id == "eval":
            self._do_eval(query)

    # ── Tree clicks ──

    @staticmethod
    def _tree_node_name(node) -> str | None:
        """Extract the plain name from a tree node, ignoring branches."""
        if node.children:
            return None  # branch node — don't navigate
        import re
        plain = re.sub(r"\[/?[^\]]*\]", "", str(node.label)).strip()
        return plain if plain and plain != "empty" else None

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Click a name in a tree panel to view it in the lens."""
        name = self._tree_node_name(event.node)
        if not name:
            return
        tree_id = event.node.tree.id
        if tree_id == "search-names":
            tabs = self.query_one("#bench-tabs", TabbedContent)
            tabs.active = "lens"
            self.query_one("#lens-input", QueryBox).load_text(name)
            self._do_lens(name)
        elif tree_id == "lens-names":
            self.query_one("#lens-input", QueryBox).load_text(name)
            self._do_lens(name)

    # ── Search ──

    @work(exclusive=True, group="search")
    async def _do_search(self, query: str, offset: int = 0) -> None:
        out = self.query_one("#search-results", HighlightedLog)
        names_tree = self.query_one("#search-names", FocusedTree)
        out.set_info("Searching...")
        try:
            self._search_query = query
            self._search_offset = offset
            lines = await self._client.search(query, limit=self.SEARCH_PAGE_SIZE, offset=offset)
            if lines:
                page = offset // self.SEARCH_PAGE_SIZE + 1
                header = f"[dim]── page {page} (offset {offset}) ──[/dim]"
                out.clear()
                out.write(header)
                out.write("\n".join(lines))
            else:
                out.set_info("No results.")
            # Populate names tree from [name1, name2] in results
            seen: set[str] = set()
            extracted: list[str] = []
            for line in lines:
                if "[" in line and "]" in line:
                    bracket = line[line.index("[") + 1 : line.index("]")]
                    for name in bracket.split(", "):
                        name = name.strip()
                        if name and name not in seen:
                            seen.add(name)
                            extracted.append(name)
            self._populate_name_tree(names_tree, extracted)
        except BenchClientError as e:
            out.set_error(str(e))

    def action_search_next(self) -> None:
        if not self._search_query:
            return
        self._do_search(self._search_query, self._search_offset + self.SEARCH_PAGE_SIZE)

    def action_search_prev(self) -> None:
        if not self._search_query or self._search_offset <= 0:
            return
        self._do_search(self._search_query, max(0, self._search_offset - self.SEARCH_PAGE_SIZE))

    # ── Lens ──

    @work(exclusive=True, group="lens")
    async def _do_lens(self, query: str) -> None:
        out = self.query_one("#lens-results", HighlightedLog)
        out.set_info("Loading...")
        try:
            if query.startswith("/find ") or query.startswith("find "):
                pattern = query.split(None, 1)[1] if " " in query else ""
                names = await self._client.find(pattern)
                out.set_content("\n".join(names) if names else "No matches.", language=None)
            elif query.startswith("/fuzzy ") or query.startswith("fuzzy "):
                q = query.split(None, 1)[1] if " " in query else ""
                names = await self._client.fuzzy(q)
                out.set_content("\n".join(names) if names else "No matches.", language=None)
            elif query.startswith("/consumer ") or query.startswith("consumer "):
                name = query.split(None, 1)[1].strip()
                text = await self._client.view_consumer(name)
                out.set_content(text)
            elif query.startswith("/inputs ") or query.startswith("inputs "):
                name = query.split(None, 1)[1].strip()
                text = await self._client.view_inputs(name)
                out.set_content(text)
            elif query.startswith("/subgraph ") or query.startswith("subgraph "):
                parts = query.split()
                name = parts[1] if len(parts) > 1 else ""
                direction = parts[2] if len(parts) > 2 else "upstream"
                text = await self._client.view_subgraph(name, direction)
                out.set_content(text)
            elif query.startswith("/focus ") or query.startswith("focus "):
                name = query.split(None, 1)[1].strip()
                text = await self._client.focus(name)
                out.set_content(text)
            elif query == "kinds":
                text = await self._client.view_kinds()
                out.set_content(text)
            elif query == "roots":
                text = await self._client.view_roots()
                out.set_content(text)
            else:
                text = await self._client.view(query)
                out.set_content(text)
        except BenchClientError as e:
            out.set_error(str(e))

    # ── Diagnosis ──

    @work(exclusive=True, group="diagnosis")
    async def _do_diagnose(self, focus: str) -> None:
        out = self.query_one("#dx-results", HighlightedLog)
        out.set_info("Diagnosing...")
        try:
            text = await self._client.diagnose(focus=focus if focus else None)
            out.set_content(text)
        except BenchClientError as e:
            out.set_error(str(e))

    # ── Eval ──

    @work(exclusive=True, group="eval")
    async def _do_eval(self, expression: str) -> None:
        out = self.query_one("#eval-results", HighlightedLog)
        out.set_info("Evaluating...")
        try:
            text = await self._client.eval(expression)
            out.set_content(text)
        except BenchClientError as e:
            out.set_error(str(e))

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
