"""Viewer screen — Jupyter-like .pgmd viewer with executable pltg blocks.

Split layout: tabbed notebooks on the left (one per .pgmd), provenance tree
on the right.  Prose renders as Markdown with footnote-style [[refs]] (same
as AnswerScreen).  Each tab has its own System/Loader.

Execution model:
- Start with empty ``.viewer.<name>.pltg``
- Clicking "Run block N" appends block N's content to the file (or replaces
  it in-place if already executed) and reloads through LazyLoader.
- Ctrl+R appends all remaining blocks and reloads.
- Each block is wrapped in marker comments so segments can be replaced.
"""

from __future__ import annotations

import io
import logging
import re
import sys
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Label, Markdown, Static, TabbedContent, TabPane

from parseltongue.core.companion import CompanionTracker
from parseltongue.core.companion_integrity import BlockStatus

from ..widgets.hints_bar import HintsBar
from ..widgets.pass_viewer import _safe_highlight, pv_escape
from ..widgets.provenance_tree import ProvenanceTree
from ..widgets.reference_text import FootnoteLabel, ReferenceClicked, ReferenceText, collect_footnotes
from ..widgets.resizable_split import ResizableSplitMixin

log = logging.getLogger("parseltongue")

# ── Markup templates ──


def _btn(action: str, label: str, style: str = "bold cyan") -> str:
    return f"[@click={action}][{style}]{label}[/{style}][/]"


def _badge(text: str, style: str = "dim") -> str:
    return f"[{style}]{text}[/{style}]"


def _title_toggle(wid: str, title: str, expanded: bool = False) -> str:
    """Title text (clickable to toggle) with [code ▾/▴] suffix."""
    arrow = "▴" if expanded else "▾"
    t = title if len(title) <= 80 else title[:77] + "..."
    return f"[@click=screen.toggle_block('{wid}')]" f"{pv_escape(t)} [dim cyan]\\[code {arrow}][/dim cyan][/]"


def _block_left(
    tab_id: str,
    block_num: int,
    wid: str,
    title: str,
    integrity=None,
    executed: bool = False,
    has_error: bool = False,
    expanded: bool = False,
) -> str:
    """Left side: `action` `status` `title [code ▾/▴]`."""
    t = _title_toggle(wid, title, expanded)
    status = integrity.status if integrity else None

    if status in (BlockStatus.INVALID, BlockStatus.STALE):
        tag = _badge("✗ INVALID", "bold red") if status == BlockStatus.INVALID else _badge("⚠ STALE", "bold yellow")
        return f"{tag} {t}"

    if executed:
        run = _btn(f"screen.run_block('{tab_id}',{block_num})", "↻ Re-run")
        ok = _badge("✗", "bold red") if has_error else _badge("✓", "bold green")
        return f"{run} {ok} {t}"

    run = _btn(f"screen.run_block('{tab_id}',{block_num})", "▶ Run")
    return f"{run} [dim]{t}[/dim]"


def _block_right(tab_id: str, block_num: int, block_hash: str, integrity=None, executed: bool = False) -> str:
    """Right side: `rollback/resolve` `integrity_icon` `hash`."""
    h = _badge(block_hash, "dim")
    status = integrity.status if integrity else None

    if status in (BlockStatus.INVALID, BlockStatus.STALE):
        src = _btn(f"screen.accept_source('{tab_id}',{block_num})", "⬆ Use source", "bold cyan")
        comp = _btn(f"screen.accept_companion('{tab_id}',{block_num})", "⬇ Use companion", "bold yellow")
        icon = _badge("✗", "bold red") if status == BlockStatus.INVALID else _badge("⚠", "bold yellow")
        return f"{icon} {h}\n{src} {comp}"

    if executed:
        rollback = _btn(f"screen.rollback_block('{tab_id}',{block_num})", "⏏ Rollback", "dim red")
        return f"{rollback} {_badge('✓', 'bold green')} {h}"

    return h


class _TabState:
    """Per-tab execution state, backed by CompanionTracker."""

    __slots__ = ("path", "source", "tracker", "system", "loader")

    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        self.source = source
        self.tracker = CompanionTracker(path)
        self.system = self.tracker.system
        self.loader = self.tracker.loader

    @property
    def companion(self) -> Path:
        return self.tracker.companion_path

    @property
    def executed_blocks(self) -> set[int]:
        return self.tracker.executed

    @property
    def chain_hashes(self) -> list[str]:
        return self.tracker.chain

    @property
    def integrity(self):
        return self.tracker.integrity.blocks


class ViewerScreen(ResizableSplitMixin, Screen):
    """Jupyter-like pgmd viewer with tabs, executable blocks, and provenance."""

    _split_grid_id = "viewer-layout"

    BINDINGS = [
        ("f1", "app.switch_screen('editor')", "Editor"),
        ("f2", "app.switch_screen('viewer')", "Viewer"),
        ("f3", "app.switch_screen('modules')", "Modules"),
        ("f4", "app.switch_screen('system_state')", "System"),
        ("f5", "app.switch_screen('consistency')", "Consistency"),
        ("f6", "app.switch_screen('project_files')", "Files"),
        ("f7", "app.main_menu", "Menu"),
        ("escape", "app.project_selector", "Projects"),
        ("ctrl+r", "run_all", "Run all"),
        ("ctrl+l", "reload_changed", "Reload"),
        ("f9", "grow_right", "F9 Grow right"),
        ("f10", "grow_left", "F10 Grow left"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tabs: dict[str, _TabState] = {}
        self._pending_update = False
        self._repair_modal_open = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="viewer-layout"):
            with Container(id="viewer-notebook-panel"):
                with Horizontal(id="viewer-header"):
                    yield Label("Viewer", id="viewer-title")
                    yield Static(
                        "[@click=screen.run_all]Run All[/]",
                        id="viewer-run-btn",
                    )
                yield TabbedContent(id="viewer-tabs")
            with Container(id="viewer-provenance-panel"):
                yield Label("Provenance", id="viewer-provenance-title")
                yield ProvenanceTree(id="viewer-provenance-tree")
        hints = [
            ("F1", "Editor", "app.switch_screen('editor')"),
            ("F2", "Viewer", "app.switch_screen('viewer')"),
            ("F3", "Modules", "app.switch_screen('modules')"),
            ("F4", "System", "app.switch_screen('system_state')"),
            ("F5", "Consistency", "app.switch_screen('consistency')"),
            ("F6", "Files", "app.switch_screen('project_files')"),
            ("Ctrl+R", "Run all", "screen.run_all"),
            ("Ctrl+L", "Reload", "screen.reload_changed"),
            ("F9/F10", "Resize"),
            ("Esc", "Projects", "app.project_selector"),
        ]
        yield HintsBar(hints)

    def update(self, pgmd_files: dict[str, tuple[Path, str]]) -> None:
        """Update with pgmd files.  name → (path, source)."""
        log.info("Viewer: update called with %d pgmd files", len(pgmd_files))
        self._tabs.clear()
        for name, (path, source) in pgmd_files.items():
            tab_id = f"vt-{re.sub(r'[^a-zA-Z0-9_-]', '-', name)}"
            state = _TabState(path, source)
            # CompanionTracker.__init__ already checks integrity and loads valid blocks
            self._tabs[tab_id] = state
            integrity_summary = {n: bi.status.name for n, bi in state.integrity.items()}
            log.info(
                "Viewer: tab '%s' → %s (companion: %s, valid: %s, integrity: %s)",
                tab_id,
                path,
                state.companion,
                sorted(state.executed_blocks),
                integrity_summary,
            )

        if not self.is_mounted:
            self._pending_update = True
            return

        self.app.call_later(self._rebuild_tabs)

    def on_mount(self) -> None:
        if self._pending_update:
            self._pending_update = False
            self.app.call_later(self._rebuild_tabs)

    def on_screen_resume(self) -> None:
        """Re-check companion integrity when returning to this screen."""
        self.check_companion_integrity()

    def check_companion_integrity(self) -> None:
        """Re-check integrity for all tabs and update block headers if changed.

        Called by the app-level file watcher when companion files change,
        and on screen resume.  Detects external modifications to either
        the pgmd source or the companion file.

        Structural issues are detected and reported:
        - Misordered blocks
        - Duplicate block numbers
        All repairs require user confirmation.
        """
        for tab_id, state in self._tabs.items():
            old_valid = set(state.executed_blocks)
            old_statuses = {n: bi.status for n, bi in state.integrity.items()}

            # Reload both source and companion from disk
            state.tracker.reload_source()
            state.tracker.reload_companion()
            state.source = state.tracker.source
            state.system = state.tracker.system
            state.loader = state.tracker.loader

            ir = state.tracker.integrity

            # Structural issues → push repair modal (once)
            if (ir.misordered or ir.duplicates) and not self._repair_modal_open:
                self._show_repair_modal(tab_id, state)

            new_statuses = {n: bi.status for n, bi in state.integrity.items()}
            if new_statuses == old_statuses and state.executed_blocks == old_valid:
                continue

            # Integrity changed — update block headers and code content
            pltg_blocks = self._pltg_blocks(state)
            for bn, (block_i, block) in enumerate(pltg_blocks):
                wid = f"{tab_id}-b{block_i}"
                bh = state.chain_hashes[bn][:8] if bn < len(state.chain_hashes) else "????????"
                title = self._block_summary(block)
                integrity = state.integrity.get(bn)
                executed = bn in state.executed_blocks
                try:
                    self.query_one(f"#{wid}-run", Static).update(
                        _block_left(tab_id, bn, wid, title, integrity, executed)
                    )
                    self.query_one(f"#{wid}-status", Static).update(_block_right(tab_id, bn, bh, integrity, executed))
                except Exception:
                    pass
                # Update code content (diff vs syntax highlight)
                try:
                    code_widget = self.query_one(f"#{wid}-code", Static)
                    if integrity and integrity.status == BlockStatus.INVALID:
                        expected_h = state.chain_hashes[bn] if bn < len(state.chain_hashes) else ""
                        code_widget.update(
                            self._render_block_diff(
                                integrity.source_content,
                                integrity.companion_content,
                                expected_hash=expected_h,
                                stored_hash=integrity.stored_hash,
                            )
                        )
                    else:
                        code_widget.update(_safe_highlight(block.content, "scheme"))
                except Exception:
                    pass

    def _show_repair_modal(self, tab_id: str, state: _TabState) -> None:
        """Push the companion repair modal for structural issues."""
        from .companion_repair import CompanionRepairModal

        pltg_blocks = self._pltg_blocks(state)
        source_blocks = {bn: block.content for bn, (_, block) in enumerate(pltg_blocks)}

        self._repair_modal_open = True

        def _on_repair(new_text: str | None) -> None:
            self._repair_modal_open = False
            if new_text is None:
                return

            # Write the repaired text and re-check
            state.tracker._companion_text = new_text
            state.tracker._write_companion()
            state.tracker._recheck()
            state.system = state.tracker.system
            state.loader = state.tracker.loader

            self.notify(f"{state.path.name}: companion repaired")

            # Refresh headers
            for bn, (block_i, block) in enumerate(pltg_blocks):
                wid = f"{tab_id}-b{block_i}"
                bh = state.chain_hashes[bn][:8] if bn < len(state.chain_hashes) else "????????"
                title = self._block_summary(block)
                integrity_bi = state.integrity.get(bn)
                executed = bn in state.executed_blocks
                try:
                    self.query_one(f"#{wid}-run", Static).update(
                        _block_left(tab_id, bn, wid, title, integrity_bi, executed)
                    )
                    self.query_one(f"#{wid}-status", Static).update(
                        _block_right(tab_id, bn, bh, integrity_bi, executed)
                    )
                except Exception:
                    pass

        self.app.push_screen(
            CompanionRepairModal(
                filename=state.path.name,
                companion_text=state.tracker.companion_text,
                source_blocks=source_blocks,
            ),
            callback=_on_repair,
        )

    async def action_reload_changed(self) -> None:
        """Reload pgmd files that changed on disk — repopulate changed tabs only."""
        reloaded = []
        for tab_id, state in self._tabs.items():
            changed = state.tracker.reload_source()
            if changed:
                state.source = state.tracker.source
                state.system = state.tracker.system
                state.loader = state.tracker.loader
                reloaded.append(tab_id)
                try:
                    scroll = self.query_one(f"#{tab_id}-scroll", VerticalScroll)
                    await scroll.remove_children()
                    self._populate_tab(tab_id)
                except Exception:
                    pass
        if reloaded:
            self.notify(f"Reloaded: {', '.join(self._tabs[t].path.name for t in reloaded)}")
        else:
            self.notify("No changes detected.")

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    async def _rebuild_tabs(self) -> None:
        old_tabs = self.query_one("#viewer-tabs", TabbedContent)
        assert old_tabs.parent is not None
        parent: Any = old_tabs.parent

        # Save current state
        prev_active = old_tabs.active
        scroll_positions: dict[str, tuple[int, int]] = {}
        for tab_id in self._tabs:
            try:
                scroll = self.query_one(f"#{tab_id}-scroll", VerticalScroll)
                scroll_positions[tab_id] = (scroll.scroll_offset.x, scroll.scroll_offset.y)
            except Exception:
                pass

        # Remove old TabbedContent entirely
        await old_tabs.remove()

        # Mount a fresh one
        new_tabs = TabbedContent(id="viewer-tabs")
        await parent.mount(new_tabs)

        for tab_id, state in self._tabs.items():
            scroll = VerticalScroll(id=f"{tab_id}-scroll")
            pane = TabPane(state.path.name, scroll, id=tab_id)
            await new_tabs.add_pane(pane)
            self.call_after_refresh(self._populate_tab, tab_id)

        # Restore active tab
        if prev_active and prev_active in self._tabs:
            new_tabs.active = prev_active

        # Restore scroll positions after content is populated
        def _restore_scroll() -> None:
            for tab_id, (sx, sy) in scroll_positions.items():
                try:
                    scroll = self.query_one(f"#{tab_id}-scroll", VerticalScroll)
                    scroll.scroll_to(sx, sy, animate=False)
                except Exception:
                    pass

        self.call_after_refresh(_restore_scroll)

    def _pltg_blocks(self, state: _TabState) -> list[tuple[int, Any]]:
        """Return [(block_index, PgmdBlock), ...] for pltg blocks."""
        from parseltongue.core.pgmd import parse_pgmd

        blocks = parse_pgmd(state.source)
        return [(i, b) for i, b in enumerate(blocks) if b.kind == "pltg"]

    @staticmethod
    def _block_summary(block) -> str:
        """Return collapsed header text for a pltg block.

        If the block has a title (from ``;; pltg My Title``), use it.
        Otherwise take the first non-empty line, truncated to 100 chars.
        """
        if block.title:
            return block.title
        for line in block.content.splitlines():
            stripped = line.strip()
            if stripped:
                if len(stripped) > 100:
                    return stripped[:97] + "..."
                return stripped
        return "..."

    def _populate_tab(self, tab_id: str) -> None:
        from parseltongue.core.pgmd import parse_pgmd

        state = self._tabs.get(tab_id)
        if not state:
            return

        try:
            scroll = self.query_one(f"#{tab_id}-scroll", VerticalScroll)
        except Exception:
            return

        # Guard against double population
        if scroll.children:
            return

        blocks = parse_pgmd(state.source)
        if not blocks:
            scroll.mount(Static("[dim]Empty file.[/dim]"))
            return

        # Collect footnotes across all prose and code blocks for unified numbering
        ref_texts = [b.content.strip() for b in blocks if b.kind in ("prose", "code")]
        shared_fn = collect_footnotes(*ref_texts)

        # Build all widgets first, then mount in one batch
        widgets: list[Any] = []
        pltg_counter = 0
        for i, block in enumerate(blocks):
            wid = f"{tab_id}-b{i}"
            if block.kind == "prose":
                widgets.append(
                    ReferenceText(
                        block.content.strip(),
                        shared_footnotes=shared_fn,
                        show_footnotes=False,
                        id=f"{wid}-ref",
                    )
                )
            elif block.kind == "pltg":
                title = self._block_summary(block)
                bh = state.chain_hashes[pltg_counter][:8] if pltg_counter < len(state.chain_hashes) else "????????"
                integrity = state.integrity.get(pltg_counter)
                executed = pltg_counter in state.executed_blocks
                left = _block_left(tab_id, pltg_counter, wid, title, integrity, executed)
                right = _block_right(tab_id, pltg_counter, bh, integrity, executed)
                header = Horizontal(
                    Static(left, id=f"{wid}-run"),
                    Static(right, id=f"{wid}-status", classes="viewer-block-status"),
                    classes="viewer-block-header",
                )
                if integrity and integrity.status == BlockStatus.INVALID:
                    expected_h = state.chain_hashes[pltg_counter] if pltg_counter < len(state.chain_hashes) else ""
                    diff_markup = self._render_block_diff(
                        integrity.source_content,
                        integrity.companion_content,
                        expected_hash=expected_h,
                        stored_hash=integrity.stored_hash,
                    )
                    code = Static(diff_markup, id=f"{wid}-code", classes="viewer-block-code")
                else:
                    markup = _safe_highlight(block.content, "scheme")
                    code = Static(markup, id=f"{wid}-code", classes="viewer-block-code")
                container = Vertical(header, code, id=f"{wid}-block", classes="viewer-block collapsed")
                widgets.append(container)
                pltg_counter += 1
            elif block.kind == "code":
                if block.language:
                    # Language-tagged code block — syntax highlight
                    markup = _safe_highlight(block.content, block.language)
                    widgets.append(Static(markup, id=f"{wid}-code", classes="viewer-code viewer-display"))
                else:
                    # Unlanguaged fence — preformatted text with clickable refs
                    from ..widgets.reference_text import TAG_RE as _TAG_RE

                    # Split text around [[ref]] tags, escape non-ref parts
                    parts: list[str] = []
                    last = 0
                    for m in _TAG_RE.finditer(block.content):
                        before = block.content[last : m.start()]
                        if before:
                            parts.append(pv_escape(before))
                        ref_type, ref_name = m.group(1), m.group(2)
                        num = shared_fn.get((ref_type, ref_name), 0)
                        parts.append(
                            f"[@click=screen.ref_clicked('{ref_type}','{ref_name}')]"
                            f"[bold cyan]\\[{num}][/bold cyan]"
                            f"[/]"
                        )
                        last = m.end()
                    after = block.content[last:]
                    if after:
                        parts.append(pv_escape(after))
                    widgets.append(Static("".join(parts), id=f"{wid}-code", classes="viewer-code"))

        # Append unified footnote section at the end
        if shared_fn:
            widgets.append(Static("───", id=f"{tab_id}-fn-divider"))
            for (ref_type, ref_name), num in shared_fn.items():
                widgets.append(FootnoteLabel(ref_type, ref_name, num))

        scroll.mount_all(widgets)

    def action_rollback_block(self, tab_id: str, block_num: int) -> None:
        """Remove a block from the companion file and reload."""
        state = self._tabs.get(tab_id)
        if not state:
            return
        if block_num not in state.executed_blocks:
            self.notify("Block not executed yet.", severity="warning")
            return

        # Tracker handles removal, file write, and integrity re-check
        state.tracker.rollback(block_num)
        state.system = state.tracker.system
        state.loader = state.tracker.loader

        # Update display for all blocks (integrity may have changed)
        pltg_blocks = self._pltg_blocks(state)
        for bn, (block_i, block) in enumerate(pltg_blocks):
            wid = f"{tab_id}-b{block_i}"
            bh = state.chain_hashes[bn][:8] if bn < len(state.chain_hashes) else "????????"
            title = self._block_summary(block)
            integrity = state.integrity.get(bn)
            executed = bn in state.executed_blocks
            try:
                self.query_one(f"#{wid}-run", Static).update(_block_left(tab_id, bn, wid, title, integrity, executed))
                self.query_one(f"#{wid}-status", Static).update(_block_right(tab_id, bn, bh, integrity, executed))
            except Exception:
                pass
            # Remove output widget for rolled-back block
            if bn == block_num:
                try:
                    self.query_one(f"#{wid}-out", Static).remove()
                except Exception:
                    pass

        # Reload remaining blocks if any are still valid
        if state.executed_blocks:
            self._reload_and_display(tab_id, state)
        else:
            self.notify("Block rolled back.")

    def action_toggle_block(self, wid: str) -> None:
        """Toggle expand/collapse of a pltg block."""
        try:
            container = self.query_one(f"#{wid}-block", Vertical)
        except Exception:
            return
        container.toggle_class("collapsed")
        expanded = "collapsed" not in container.classes
        # Re-render header left to update ▾/▴ arrow
        try:
            run_static = self.query_one(f"#{wid}-run", Static)
            # Extract tab_id and block info from wid (format: "vt-xxx-bN")
            # Find which tab and block this belongs to
            for tab_id, state in self._tabs.items():
                if wid.startswith(tab_id):
                    pltg_blocks = self._pltg_blocks(state)
                    for bn, (block_i, block) in enumerate(pltg_blocks):
                        if f"{tab_id}-b{block_i}" == wid:
                            title = self._block_summary(block)
                            integrity = state.integrity.get(bn)
                            executed = bn in state.executed_blocks
                            run_static.update(
                                _block_left(tab_id, bn, wid, title, integrity, executed, expanded=expanded)
                            )
                            break
                    break
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Integrity diff / resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _render_block_diff(source: str, companion: str, expected_hash: str = "", stored_hash: str = ""):
        """Side-by-side diff table for an INVALID block."""
        from ..widgets.diff_table import build_diff_table

        col_a = f"Source ({expected_hash[:12]})" if expected_hash else "Source"
        col_b = f"Companion ({stored_hash[:12]})" if stored_hash else "Companion"
        return build_diff_table(source, companion, col_a=col_a, col_b=col_b)

    def action_accept_source(self, tab_id: str, block_num: int) -> None:
        """Resolve mismatch: overwrite companion block with current source."""
        state = self._tabs.get(tab_id)
        if not state:
            return

        pltg_blocks = self._pltg_blocks(state)
        if block_num >= len(pltg_blocks):
            return

        # Tracker writes source content into companion and re-checks integrity
        _, block = pltg_blocks[block_num]
        state.tracker.execute(block_num, block.content)
        state.system = state.tracker.system
        state.loader = state.tracker.loader

        self._reload_and_display(tab_id, state)
        self.notify(f"Block {block_num + 1}: source accepted → companion updated")

    def action_accept_companion(self, tab_id: str, block_num: int) -> None:
        """Resolve mismatch: overwrite pgmd source block with companion content."""
        state = self._tabs.get(tab_id)
        if not state:
            return

        integrity = state.integrity.get(block_num)
        if not integrity or not integrity.companion_content:
            self.notify("No companion content to restore.", severity="warning")
            return

        # Replace the block content in the pgmd source file
        from parseltongue.core.pgmd import parse_pgmd

        blocks = parse_pgmd(state.source)
        pltg_idx = 0
        target_block_i = None
        for i, b in enumerate(blocks):
            if b.kind == "pltg":
                if pltg_idx == block_num:
                    target_block_i = i
                    break
                pltg_idx += 1

        if target_block_i is None:
            self.notify("Block not found in source.", severity="error")
            return

        target_block = blocks[target_block_i]
        old_content = target_block.content
        new_content = integrity.companion_content

        # Replace in source text and write back
        new_source = state.source.replace(old_content, new_content, 1)
        state.path.write_text(new_source)
        state.source = new_source

        # Reload source in tracker so it recomputes chain and integrity
        state.tracker.reload_source()
        state.system = state.tracker.system
        state.loader = state.tracker.loader

        self._reload_and_display(tab_id, state)
        self.notify(f"Block {block_num + 1}: companion accepted → source updated")

    # ------------------------------------------------------------------
    # Companion file management
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _active_tab_id(self) -> str | None:
        tabs = self.query_one("#viewer-tabs", TabbedContent)
        active = tabs.active
        return active if active and active in self._tabs else None

    def action_run_block(self, tab_id: str, block_num: int) -> None:
        """Execute a single block: write/replace it in companion, reload."""
        log.info("Viewer: action_run_block tab=%s block=%d", tab_id, block_num)
        state = self._tabs.get(tab_id)
        if not state:
            log.warning("Viewer: tab '%s' not found in _tabs", tab_id)
            return

        pltg_blocks = self._pltg_blocks(state)
        log.info("Viewer: %d pltg blocks found", len(pltg_blocks))
        if block_num < 0 or block_num >= len(pltg_blocks):
            self.notify(f"Block {block_num + 1} not found.", severity="warning")
            return

        _, block = pltg_blocks[block_num]
        log.info("Viewer: writing block %d content (%d chars) to companion", block_num, len(block.content))
        state.tracker.execute(block_num, block.content)
        self._reload_and_display(tab_id, state)

    def action_run_all(self) -> None:
        """Append all unexecuted blocks and reload."""
        tab_id = self._active_tab_id()
        log.info("Viewer: action_run_all, active tab=%s", tab_id)
        if not tab_id:
            self.notify("No tab selected.", severity="warning")
            return

        state = self._tabs[tab_id]
        pltg_blocks = self._pltg_blocks(state)
        log.info("Viewer: %d pltg blocks to run", len(pltg_blocks))

        if not pltg_blocks:
            self.notify("No executable blocks.", severity="warning")
            return

        for block_num, (_, block) in enumerate(pltg_blocks):
            state.tracker.execute(block_num, block.content)

        self._reload_and_display(tab_id, state)

    def _reload_and_display(self, tab_id: str, state: _TabState) -> None:
        """Reload the companion file through LazyLoader and update outputs."""
        from parseltongue.core.loader import LazyLoader

        companion_content = state.companion.read_text() if state.companion.exists() else ""
        log.info("Viewer: _reload_and_display companion=%s (%d chars)", state.companion, len(companion_content))
        log.debug("Viewer: companion content:\n%s", companion_content)

        loader = LazyLoader()
        capture_out = io.StringIO()
        capture_err = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = capture_out
        sys.stderr = capture_err
        fatal_error = None
        try:
            loader.load_main(str(state.companion))
        except Exception as exc:
            import traceback

            log.error("Viewer: LazyLoader.load_main failed: %s", exc, exc_info=True)
            fatal_error = traceback.format_exc()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        printed_output = capture_out.getvalue().rstrip()
        stderr_output = capture_err.getvalue().rstrip()
        state.system = loader.last_result.system if loader.last_result else None
        state.loader = loader

        result = loader.last_result

        pltg_blocks = self._pltg_blocks(state)

        if fatal_error:
            # Show the full traceback on the last executed block
            executed_pltg = [(n, bi, b) for n, (bi, b) in enumerate(pltg_blocks) if n in state.executed_blocks]
            if executed_pltg:
                _, last_bi, _ = executed_pltg[-1]
                wid = f"{tab_id}-b{last_bi}"
                err_text = f"[red]{pv_escape(fatal_error)}[/red]"
                if stderr_output:
                    err_text = f"[red]{pv_escape(stderr_output)}[/red]\n{err_text}"
                self._set_block_output(wid, err_text)
            self.notify("Run failed — see error below", severity="error")
            if result is None:
                return

        if result is None:
            log.error("Viewer: no result from LazyLoader")
            return

        log.info(
            "Viewer: load result — loaded=%d, errors=%d, skipped=%d",
            len(result.loaded),
            len(result.errors),
            len(result.skipped),
        )
        if result.errors:
            for node, err in result.errors.items():
                log.warning("Viewer: error on '%s' (%s): %s", node.name, node.kind, err)
        if printed_output:
            log.info("Viewer: captured stdout (%d chars): %s", len(printed_output), printed_output[:200])

        # Log system contents
        sys_obj = result.system
        log.info(
            "Viewer: system has %d facts, %d terms, %d axioms, %d theorems",
            len(sys_obj.facts or {}),
            len(sys_obj.terms or {}),
            len(sys_obj.axioms or {}),
            len(sys_obj.theorems or {}),
        )

        if not result.ok:
            errors = len(result.errors)
            skipped = len(result.skipped)
            self.notify(f"Run: {errors} errors, {skipped} skipped", severity="warning")
        else:
            self.notify(f"Executed all {len(pltg_blocks)} blocks.")

        # Collect all error messages first
        error_parts = []
        if not result.ok:
            import traceback as tb_mod

            for node, err in result.errors.items():
                tb_str = "".join(tb_mod.format_exception(type(err), err, err.__traceback__))
                label = node.name or node.kind or "unknown"
                error_parts.append(f"── {label} ──\n{tb_str}")
            for node in result.skipped:
                label = node.name or node.kind or "unknown"
                error_parts.append(f"── {label} ──\nSkipped (dependency failed)")

        # Build combined output text
        output_parts = []
        if printed_output:
            output_parts.append(f"[dim]Output:[/dim]\n{pv_escape(printed_output)}")
        if stderr_output:
            output_parts.append(f"[red]{pv_escape(stderr_output)}[/red]")
        if error_parts:
            output_parts.append(f"[red]{pv_escape(chr(10).join(error_parts))}[/red]")
        if not output_parts:
            output_parts.append("[dim italic]no printable output[/dim italic]")

        # Show on the last executed block
        executed_pltg = [(n, bi, b) for n, (bi, b) in enumerate(pltg_blocks) if n in state.executed_blocks]
        if executed_pltg:
            _, last_bi, _ = executed_pltg[-1]
            wid = f"{tab_id}-b{last_bi}"
            self._set_block_output(wid, "\n".join(output_parts))

        # Update block headers via templates
        has_errors = bool(error_parts) or bool(fatal_error)
        last_executed = executed_pltg[-1][0] if executed_pltg else -1
        for block_num, (block_i, block) in enumerate(pltg_blocks):
            wid = f"{tab_id}-b{block_i}"
            title = self._block_summary(block)
            bh = state.chain_hashes[block_num][:8] if block_num < len(state.chain_hashes) else "????????"
            executed = block_num in state.executed_blocks
            block_error = has_errors and block_num == last_executed
            integrity = state.integrity.get(block_num)
            try:
                self.query_one(f"#{wid}-run", Static).update(
                    _block_left(tab_id, block_num, wid, title, integrity, executed, block_error)
                )
                self.query_one(f"#{wid}-status", Static).update(
                    _block_right(tab_id, block_num, bh, integrity, executed)
                )
            except Exception:
                pass

    def _set_block_output(self, wid: str, text: str) -> None:
        """Set the output widget for a block — update if exists, mount if not."""
        try:
            out = self.query_one(f"#{wid}-out", Static)
            out.update(text)
        except Exception:
            try:
                container = self.query_one(f"#{wid}-block", Vertical)
                out = Static(text, id=f"{wid}-out", classes="viewer-block-output")
                container.mount(out)
            except Exception:
                pass

    def _show_block_error(self, tab_id: str, pltg_blocks: list, name: str, message: str) -> None:
        for block_i, block in pltg_blocks:
            if name in block.content:
                wid = f"{tab_id}-b{block_i}"
                try:
                    container = self.query_one(f"#{wid}-block", Vertical)
                    # Append to existing output or create new
                    try:
                        out = self.query_one(f"#{wid}-out", Static)
                        current = str(getattr(out, "renderable", "")) or ""
                        text = (
                            f"{current}\n[red]{pv_escape(message)}[/red]"
                            if current
                            else f"[red]{pv_escape(message)}[/red]"
                        )
                        out.update(text)
                    except Exception:
                        out = Static(
                            f"[red]{pv_escape(message)}[/red]",
                            id=f"{wid}-out",
                            classes="viewer-block-output",
                        )
                        container.mount(out)
                except Exception:
                    pass
                return

    # ------------------------------------------------------------------
    # Ref clicks → provenance
    # ------------------------------------------------------------------

    def on_reference_clicked(self, event: ReferenceClicked) -> None:
        # Highlight the clicked ref in the ReferenceText that posted the event
        widget: Any = event._sender
        while widget is not None:
            if isinstance(widget, ReferenceText):
                widget.highlight_ref(event.ref_type, event.ref_name)
                break
            widget = getattr(widget, "parent", None)
        self._show_provenance(event.ref_type, event.ref_name)

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        href = event.href
        if "/" not in href and not href.startswith(("http", "mailto")) and ":" in href:
            ref_type, ref_name = href.split(":", 1)
            self._show_provenance(ref_type, ref_name)
        else:
            self.app.open_url(href)

    def action_ref_clicked(self, ref_type: str, ref_name: str) -> None:
        self._show_provenance(ref_type, ref_name)

    def _show_provenance(self, ref_type: str, ref_name: str) -> None:
        tree = self.query_one("#viewer-provenance-tree", ProvenanceTree)
        tab_id = self._active_tab_id()
        system = self._tabs[tab_id].system if tab_id and tab_id in self._tabs else None
        if system is not None:
            # Log what the system actually has so we can debug lookup failures
            found = (
                ref_name in (system.facts or {})
                or ref_name in (system.terms or {})
                or ref_name in (system.axioms or {})
                or ref_name in (system.theorems or {})
            )
            if not found:
                log.error(
                    "Viewer: ref click %s:%s not found in system. " "facts=%s, terms=%s, axioms=%s, theorems=%s",
                    ref_type,
                    ref_name,
                    list((system.facts or {}).keys()),
                    list((system.terms or {}).keys()),
                    list((system.axioms or {}).keys()),
                    list((system.theorems or {}).keys()),
                )
            tree.show_system_item(ref_type, ref_name, system)
        else:
            log.warning("Viewer: ref click %s:%s but no system loaded (tab=%s)", ref_type, ref_name, tab_id)
            tree.show_reference(ref_type, ref_name, error="Not executed yet — press Ctrl+R")
