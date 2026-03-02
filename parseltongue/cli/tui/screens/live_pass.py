"""Live pass screen — shows pass execution with review/retry/skip."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)

if TYPE_CHECKING:
    from textual.timer import Timer

    from ...interactive import InteractivePipeline, PassResult

PASS_NAMES = {1: "Extract", 2: "Derive", 3: "Factcheck", 4: "Answer"}
_REF_RE = re.compile(r"\[\[(\w+):([^\]]+)\]\]")


class PassesComplete(Message):
    """All 4 passes are done."""

    pass


class LivePassScreen(Screen):
    """Live view of pass-by-pass pipeline execution.

    Left: tabbed DSL output log.  Right: live system state tree.
    Bottom: action buttons for retry/skip/continue.
    """

    BINDINGS = [
        ("escape", "interrupt", "Interrupt"),
        ("ctrl+n", "skip", "Skip pass"),
        ("ctrl+a", "copy_log", "Copy log"),
    ]

    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, pipeline: "InteractivePipeline", **kwargs) -> None:
        super().__init__(**kwargs)
        self._pipeline = pipeline
        self._current_pass = 0
        self._running = False
        self._spinner_idx = 0
        self._spinner_timer: Timer | None = None
        self._tab_counter = 0
        self._current_tab_id: str | None = None
        self._log_buffers: dict[str, list[str]] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="live-layout"):
            with Container(id="dsl-panel"):
                yield Label("Pipeline", id="pass-title")
                yield TabbedContent(id="dsl-tabs")
            with Container(id="state-panel"):
                yield Label("Parseltongue State", id="state-title")
                yield Tree("State", id="state-tree")
        with Container(id="live-controls"):
            yield Input(
                placeholder="Feedback (then press Enter to retry)...",
                id="feedback-input",
            )
            with Horizontal(id="live-buttons"):
                yield Button("Continue", id="continue-btn", variant="primary")
                yield Button("Retry", id="retry-btn", variant="warning", disabled=True)
                yield Button("Skip", id="skip-btn", variant="default")
            yield Static(
                "[b]Enter[/b] Retry w/ feedback  [b]Ctrl+N[/b] Skip  " "[b]Esc[/b] Interrupt  [b]Ctrl+A[/b] Copy log",
                id="live-hints",
            )

    def on_mount(self) -> None:
        self._run_next_pass()

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def _new_tab(self, label: str) -> None:
        """Create a new tab with a RichLog and activate it."""
        self._tab_counter += 1
        tab_id = f"run-{self._tab_counter}"
        self._current_tab_id = tab_id
        self._log_buffers[tab_id] = []
        tabs = self.query_one("#dsl-tabs", TabbedContent)
        pane = TabPane(label, RichLog(highlight=True, markup=True), id=tab_id)
        tabs.add_pane(pane)
        tabs.active = tab_id

    def _current_log(self) -> RichLog | None:
        """Get the RichLog in the current tab."""
        if not self._current_tab_id:
            return None
        try:
            pane = self.query_one(f"#{self._current_tab_id}", TabPane)
            return pane.query_one(RichLog)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Pass execution
    # ------------------------------------------------------------------

    def _run_next_pass(self) -> None:
        self._current_pass += 1
        if self._current_pass > 4:
            self.post_message(PassesComplete())
            return

        name = PASS_NAMES[self._current_pass]
        self._new_tab(f"P{self._current_pass}: {name}")

        title = self.query_one("#pass-title", Label)
        title.update(f"Pass {self._current_pass}: {name}")

        self._set_controls(running=True)
        self._start_spinner(name)
        self.run_worker(self._execute_current_pass(), exclusive=True)

    def _start_spinner(self, pass_name: str) -> None:
        self._spinner_idx = 0
        self._spinner_pass_name = pass_name
        self._spinner_timer = self.set_interval(0.1, self._tick_spinner)

    def _tick_spinner(self) -> None:
        frame = self._SPINNER[self._spinner_idx % len(self._SPINNER)]
        self._spinner_idx += 1
        title = self.query_one("#pass-title", Label)
        title.update(f"{frame} Pass {self._current_pass}: {self._spinner_pass_name} ...")

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    async def _execute_current_pass(self) -> None:
        result = await asyncio.to_thread(self._pipeline.run_pass, self._current_pass)
        self._on_pass_done(result)

    def _on_pass_done(self, result: "PassResult") -> None:
        if result.source:
            for line in result.source.splitlines():
                self._log(self._linkify(line), line)
            self._log("")

        if result.error:
            self._log(f"[red]Error: {result.error}[/red]", f"Error: {result.error}")
        elif result.interrupted:
            self._log("[yellow]Interrupted.[/yellow]", "Interrupted.")

        self._stop_spinner()
        name = PASS_NAMES.get(self._current_pass, "")
        title = self.query_one("#pass-title", Label)
        title.update(f"Pass {self._current_pass}: {name} — done")

        self._refresh_state_tree()
        self._set_controls(running=False)

    def _refresh_state_tree(self) -> None:
        from parseltongue.core.atoms import to_sexp

        tree = self.query_one("#state-tree", Tree)
        tree.clear()
        tree.root.expand()
        system = self._pipeline.system

        if system.terms:
            section = tree.root.add("[bold]Terms[/bold]", expand=True)
            for name, term in system.terms.items():
                defn = to_sexp(term.definition) if term.definition is not None else "(primitive)"
                color = self._origin_color(term.origin)
                node = section.add(f"[{color}]{rich_escape(name)}: {rich_escape(defn)}[/{color}]")
                self._add_origin_node(node, term.origin)

        if system.facts:
            section = tree.root.add("[bold]Facts[/bold]", expand=True)
            for name, data in system.facts.items():
                val = data.get("value", data) if isinstance(data, dict) else data
                origin = data.get("origin") if isinstance(data, dict) else None
                color = self._origin_color(origin)
                node = section.add(f"[{color}]{rich_escape(str(name))} = {rich_escape(str(val))}[/{color}]")
                if origin:
                    self._add_origin_node(node, origin)

        if system.axioms:
            section = tree.root.add("[bold]Axioms[/bold]", expand=True)
            for name, axiom in system.axioms.items():
                color = self._origin_color(axiom.origin)
                node = section.add(f"[{color}]{rich_escape(name)}: {rich_escape(to_sexp(axiom.wff))}[/{color}]")
                self._add_origin_node(node, axiom.origin)

        if system.theorems:
            section = tree.root.add("[bold]Theorems[/bold]", expand=True)
            for name, thm in system.theorems.items():
                color = self._origin_color(thm.origin)
                node = section.add(f"[{color}]{rich_escape(name)}: {rich_escape(to_sexp(thm.wff))}[/{color}]")
                if thm.derivation:
                    node.add_leaf(f"derived from: {', '.join(thm.derivation)}")
                self._add_origin_node(node, thm.origin)

        if system.diffs:
            section = tree.root.add("[bold]Diffs[/bold]", expand=True)
            for name, diff in system.diffs.items():
                section.add_leaf(f"{name}: replace {diff['replace']} with {diff['with']}")

    @staticmethod
    def _origin_color(origin) -> str:
        """Green = grounded, red = unverified/fabrication, yellow = no evidence."""
        from parseltongue.core.atoms import Evidence

        if isinstance(origin, Evidence):
            return "green" if origin.is_grounded else "red"
        if isinstance(origin, str) and "potential fabrication" in origin:
            return "red"
        if origin:
            return "yellow"
        return "white"

    @staticmethod
    def _add_origin_node(node, origin) -> None:
        from parseltongue.core.atoms import Evidence

        if isinstance(origin, Evidence):
            if origin.is_grounded:
                status_tag = "[green]grounded[/green]"
            else:
                status_tag = "[red]UNVERIFIED[/red]"
            origin_node = node.add(f"evidence: {origin.document} ({status_tag})")
            for q in origin.quotes:
                origin_node.add_leaf(f'"{q[:80]}{"..." if len(q) > 80 else ""}"')
            if origin.explanation:
                origin_node.add_leaf(f"explanation: {origin.explanation}")
        elif origin:
            if isinstance(origin, str) and "potential fabrication" in origin:
                node.add_leaf(f"[red]{origin}[/red]")
            else:
                node.add_leaf(f"[yellow]origin: {origin}[/yellow]")

    @staticmethod
    def _linkify(line: str) -> str:
        """Escape line but make [[type:name]] refs clickable."""
        parts = []
        last = 0
        for m in _REF_RE.finditer(line):
            parts.append(rich_escape(line[last : m.start()]))
            ref_type, ref_name = m.group(1), m.group(2)
            parts.append(
                f"[@click=show_ref('{ref_type}','{ref_name}')]" f"[bold cyan][[{ref_type}:{ref_name}]][/bold cyan][/]"
            )
            last = m.end()
        parts.append(rich_escape(line[last:]))
        return "".join(parts)

    def action_show_ref(self, ref_type: str, ref_name: str) -> None:
        """Highlight referenced item in the state tree."""
        tree = self.query_one("#state-tree", Tree)
        # Walk tree nodes and expand/highlight the matching one
        for node in tree.root.children:
            for child in node.children:
                label = str(child.label)
                if ref_name in label:
                    node.expand()
                    child.expand()
                    tree.select_node(child)
                    tree.scroll_to_node(child)
                    return
        self.notify(f"{ref_type}:{ref_name} not in state tree.", severity="warning")

    def _log(self, rich_text: str, plain_text: str | None = None) -> None:
        """Write to the current tab's RichLog and buffer for clipboard."""
        log = self._current_log()
        if log:
            log.write(rich_text)
        if self._current_tab_id:
            buf = self._log_buffers.get(self._current_tab_id, [])
            buf.append(plain_text if plain_text is not None else rich_text)

    def _set_controls(self, running: bool) -> None:
        self._running = running
        self.query_one("#continue-btn", Button).disabled = running
        self.query_one("#retry-btn", Button).disabled = running
        self.query_one("#skip-btn", Button).disabled = running
        self.query_one("#feedback-input", Input).disabled = running

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue-btn":
            self._run_next_pass()
        elif event.button.id == "retry-btn":
            self._do_retry()
        elif event.button.id == "skip-btn":
            self._do_skip()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in feedback field -> retry with that feedback."""
        self._do_retry()

    def action_interrupt(self) -> None:
        if self._running:
            self._pipeline.request_interrupt()

    def action_skip(self) -> None:
        if not self._running:
            self._do_skip()

    def action_copy_log(self) -> None:
        # Copy the active tab's log
        tabs = self.query_one("#dsl-tabs", TabbedContent)
        tab_id = tabs.active
        lines = self._log_buffers.get(tab_id, [])
        self.app.copy_to_clipboard("\n".join(lines))
        self.notify("Log copied to clipboard.")

    def _do_retry(self) -> None:
        if self._running:
            return
        feedback_input = self.query_one("#feedback-input", Input)
        feedback = feedback_input.value.strip()
        if not feedback:
            self.notify("Type feedback before retrying.", severity="warning")
            return

        feedback_input.value = ""
        name = PASS_NAMES[self._current_pass]
        self._new_tab(f"P{self._current_pass}: {name} (retry)")

        self._set_controls(running=True)
        self._start_spinner(name)
        self.run_worker(self._execute_retry(feedback), exclusive=True)

    async def _execute_retry(self, feedback: str) -> None:
        result = await asyncio.to_thread(self._pipeline.retry_pass, self._current_pass, feedback)
        self._on_pass_done(result)

    def _do_skip(self) -> None:
        if self._running:
            return
        self._log("[dim]Skipped.[/dim]", "Skipped.")
        self._pipeline.skip_pass(self._current_pass)
        self._refresh_state_tree()
        self._run_next_pass()
