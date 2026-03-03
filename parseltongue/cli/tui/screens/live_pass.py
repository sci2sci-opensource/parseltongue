"""Live pass screen — shows pass execution with review/retry/skip."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)

from ..widgets.hints_bar import HintsBar
from ..widgets.pass_viewer import PassViewer
from ..widgets.resizable_split import ResizableSplitMixin

if TYPE_CHECKING:
    from textual.timer import Timer

    from ...interactive import InteractivePipeline, PassResult

PASS_NAMES = {1: "Extract", 2: "Derive", 3: "Factcheck", 4: "Answer"}


class PassesComplete(Message):
    """All 4 passes are done."""

    pass


class LivePassScreen(ResizableSplitMixin, Screen):
    """Live view of pass-by-pass pipeline execution.

    Left: tabbed DSL output log.  Right: live system state tree.
    Bottom: action buttons for retry/skip/continue.
    """

    _split_grid_id = "live-layout"

    BINDINGS = [
        Binding("escape", "interrupt", "Interrupt", priority=True),
        ("ctrl+n", "skip", "Skip pass"),
        ("ctrl+y", "copy_log", "Copy log"),
        ("f9", "grow_right", "F9 Grow right"),
        ("f10", "grow_left", "F10 Grow left"),
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
        self._awaiting_factcheck = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="live-layout"):
            with Container(id="dsl-panel"):
                with Horizontal(id="pass-header"):
                    yield Label("Pipeline", id="pass-title")
                    yield Static("[@click=screen.copy_log]Copy[/]", id="pass-copy-btn")
                yield TabbedContent(id="dsl-tabs")
            with Container(id="state-panel"):
                yield Label("Parseltongue State", id="state-title")
                yield Tree("State", id="state-tree")
        with Container(id="live-controls"):
            yield Input(
                placeholder="Feedback to retry, or Enter to continue...",
                id="feedback-input",
            )
            with Horizontal(id="live-buttons"):
                yield Button("Continue", id="continue-btn", variant="primary")
                yield Button("Retry", id="retry-btn", variant="warning", disabled=True)
                yield Button("Skip", id="skip-btn", variant="default")
            yield HintsBar(
                [
                    ("Enter", "Continue/Retry"),
                    ("Ctrl+N", "Skip", "screen.skip"),
                    ("Ctrl+Y", "Copy", "screen.copy_log"),
                    ("F9", "Grow right", "screen.grow_right"),
                    ("F10", "Grow left", "screen.grow_left"),
                    ("Esc", "Interrupt", "screen.interrupt"),
                ]
            )

    def on_mount(self) -> None:
        self._run_next_pass()

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def _new_tab(self, label: str) -> None:
        """Create a new tab with a PassViewer and activate it."""
        self._tab_counter += 1
        tab_id = f"run-{self._tab_counter}"
        self._current_tab_id = tab_id
        language = "markdown" if self._current_pass == 4 else "scheme"
        tabs = self.query_one("#dsl-tabs", TabbedContent)
        pane = TabPane(label, PassViewer(language=language), id=tab_id)
        tabs.add_pane(pane)
        tabs.active = tab_id

    def _current_viewer(self) -> PassViewer | None:
        """Get the PassViewer in the current tab."""
        if not self._current_tab_id:
            return None
        try:
            pane = self.query_one(f"#{self._current_tab_id}", TabPane)
            return pane.query_one(PassViewer)
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

        # Factcheck is optional — confirm before running
        if self._current_pass == 3:
            self._awaiting_factcheck = True
            self._set_controls(running=False)
            viewer = self._current_viewer()
            if viewer:
                viewer.append_info("Factcheck is optional. Press Enter to run, or Ctrl+N / Skip to skip.")
            self.query_one("#feedback-input", Input).focus()
            return

        self._start_pass()

    def _start_pass(self) -> None:
        """Actually start executing the current pass."""
        self._awaiting_factcheck = False
        name = PASS_NAMES[self._current_pass]
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
        viewer = self._current_viewer()
        if viewer and result.source:
            viewer.set_source(result.source)

        if result.error:
            if viewer:
                viewer.append_error(f"Error: {result.error}")
        elif result.interrupted:
            if viewer:
                viewer.append_info("Interrupted.")

        self._stop_spinner()
        name = PASS_NAMES.get(self._current_pass, "")
        title = self.query_one("#pass-title", Label)
        title.update(f"Pass {self._current_pass}: {name} — done")

        self._refresh_state_tree()
        self._set_controls(running=False)
        self.query_one("#feedback-input", Input).focus()

    def _refresh_state_tree(self) -> None:
        from ..widgets.tree_builders import populate_system_tree

        tree = self.query_one("#state-tree", Tree)
        tree.clear()
        tree.root.expand()
        populate_system_tree(tree.root, self._pipeline.system)

    def action_ref_clicked(self, ref_type: str, ref_name: str) -> None:
        """Handle @click from PassViewer refs — highlight in state tree."""
        tree = self.query_one("#state-tree", Tree)
        tree.root.expand()
        for node in tree.root.children:
            node.expand()
            for child in node.children:
                plain = re.sub(r"\[/?[^\]]*\]", "", str(child.label))
                if plain.startswith(ref_name + ":") or plain.startswith(ref_name + " ="):
                    child.toggle()
                    tree.move_cursor(child)
                    tree.focus()
                    return
        self.notify(
            f"{ref_type}:{ref_name} not in state tree.",
            severity="warning",
        )

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
            if getattr(self, "_awaiting_factcheck", False):
                self._start_pass()
            else:
                self._run_next_pass()
        elif event.button.id == "retry-btn":
            self._do_retry()
        elif event.button.id == "skip-btn":
            self._do_skip()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in feedback field -> retry with feedback, or continue if empty."""
        if event.value.strip():
            self._do_retry()
        elif getattr(self, "_awaiting_factcheck", False):
            self._start_pass()
        elif not self._running:
            self._run_next_pass()

    def action_interrupt(self) -> None:
        if self._running:
            self._pipeline.request_interrupt()
        else:
            self.dismiss()

    def action_skip(self) -> None:
        if not self._running:
            self._do_skip()

    def action_copy_log(self) -> None:
        import subprocess

        tabs = self.query_one("#dsl-tabs", TabbedContent)
        tab_id = tabs.active
        try:
            pane = self.query_one(f"#{tab_id}", TabPane)
            viewer = pane.query_one(PassViewer)
            text = viewer.plain_text
        except Exception:
            text = ""
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        except Exception:
            self.app.copy_to_clipboard(text)
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
        viewer = self._current_viewer()
        if viewer:
            viewer.append_info("Skipped.")
        self._pipeline.skip_pass(self._current_pass)
        self._refresh_state_tree()
        self._run_next_pass()
