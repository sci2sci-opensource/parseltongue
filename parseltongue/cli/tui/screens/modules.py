"""Modules screen — tabbed view of loaded modules with per-module state tree.

Same layout as PassesScreen but tabs correspond to loaded .pltg modules
(from Loader.modules_contexts) instead of pipeline passes.
"""

from __future__ import annotations

import re
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Label, Static, TabbedContent, TabPane

from ..widgets import FocusedTree
from ..widgets.hints_bar import HintsBar
from ..widgets.pass_viewer import PassViewer
from ..widgets.resizable_split import ResizableSplitMixin
from ..widgets.tree_builders import populate_system_tree


class ModulesScreen(ResizableSplitMixin, Screen):
    """Tabbed view of loaded modules with per-module state tree."""

    _split_grid_id = "modules-layout"

    BINDINGS = [
        ("f1", "app.switch_screen('editor')", "Editor"),
        ("f2", "app.switch_screen('viewer')", "Viewer"),
        ("f3", "app.switch_screen('modules')", "Modules"),
        ("f4", "app.switch_screen('system_state')", "System"),
        ("f5", "app.switch_screen('consistency')", "Consistency"),
        ("f6", "app.switch_screen('project_files')", "Files"),
        ("f7", "app.main_menu", "Menu"),
        ("escape", "app.project_selector", "Projects"),
        ("ctrl+y", "copy_module", "Copy module"),
        ("f9", "grow_right", "F9 Grow right"),
        ("f10", "grow_left", "F10 Grow left"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._system = None
        self._loader = None
        self._module_sources: dict[str, str] = {}  # module_name → source
        self._tab_to_module: dict[str, str] = {}  # tab_id → module_name
        self._pending_update: tuple | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="modules-layout"):
            with Container(id="modules-dsl-panel"):
                with Horizontal(id="modules-header"):
                    yield Label("Modules", id="modules-title")
                    yield Static(
                        "[@click=screen.copy_module]Copy[/]",
                        id="modules-copy-btn",
                    )
                yield TabbedContent(id="modules-tabs")
            with Container(id="modules-state-panel"):
                yield Label("Module State", id="modules-state-title")
                yield FocusedTree("State", id="modules-state-tree")
        hints: list[tuple[str, ...]] = [
            ("F1", "Editor", "app.switch_screen('editor')"),
            ("F2", "Viewer", "app.switch_screen('viewer')"),
            ("F3", "Modules", "app.switch_screen('modules')"),
            ("F4", "System", "app.switch_screen('system_state')"),
            ("F5", "Consistency", "app.switch_screen('consistency')"),
            ("F6", "Files", "app.switch_screen('project_files')"),
        ]
        hints.extend(
            [
                ("Ctrl+Y", "Copy", "screen.copy_module"),
                ("F9/F10", "Resize"),
                ("Esc", "Projects", "app.project_selector"),
            ]
        )
        yield HintsBar(hints)

    def on_mount(self) -> None:
        if self._pending_update:
            system, loader = self._pending_update
            self._pending_update = None
            self.call_after_refresh(self.update, system, loader)

    def update(self, system, loader) -> None:
        """Populate tabs from a completed Loader run."""
        if not self.is_mounted:
            self._pending_update = (system, loader)
            return

        self._system = system
        self._loader = loader
        self._module_sources.clear()
        self._tab_to_module.clear()

        tabs = self.query_one("#modules-tabs", TabbedContent)

        if loader is None:
            return

        # Compute error/unreachable names per module from the AST
        from ..pltg_highlight import _analyze_source

        # Track which tab IDs are current
        current_tab_ids: set[str] = set()

        # Add or update a tab per loaded module
        for idx, (module_name, ctx) in enumerate(loader.modules_contexts.items()):
            try:
                source = Path(ctx.current_file).read_text()
            except Exception:
                source = f"; Could not read {ctx.current_file}"

            self._module_sources[module_name] = source
            tab_id = f"mod-{re.sub(r'[^a-zA-Z0-9_-]', '-', module_name)}-{idx}"
            self._tab_to_module[tab_id] = module_name
            current_tab_ids.add(tab_id)

            ns = None if ctx.is_main else module_name
            analysis = _analyze_source(source, system, module_name=ns)

            # Update existing pane or create new one
            try:
                pane = self.query_one(f"#{tab_id}", TabPane)
                viewer = pane.query_one(PassViewer)
                viewer.set_source(
                    source,
                    error_names=analysis.error_names,
                    unreachable_names=analysis.unreachable_names,
                )
            except Exception:
                label = f"{'★ ' if ctx.is_main else ''}{module_name}"
                pane = TabPane(
                    label,
                    PassViewer(
                        source,
                        language="scheme",
                        error_names=analysis.error_names,
                        unreachable_names=analysis.unreachable_names,
                    ),
                    id=tab_id,
                )
                tabs.add_pane(pane)

        # Remove tabs that no longer exist
        for pane_id in list(tabs._tab_content):
            if pane_id not in current_tab_ids:
                try:
                    tabs.remove_pane(str(pane_id))
                except Exception:
                    pass

        # Show state for first module
        if loader.modules_contexts:
            self._refresh_state_tree(next(iter(loader.modules_contexts)))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Switch state tree when tab changes."""
        pane_id = event.pane.id or ""
        module_name = self._tab_to_module.get(pane_id)
        if module_name:
            self._refresh_state_tree(module_name)

    def _refresh_state_tree(self, module_name: str) -> None:
        """Show the system state filtered to this module's definitions."""
        tree = self.query_one("#modules-state-tree", FocusedTree)
        tree.clear()
        tree.root.expand()

        if self._system is None:
            tree.root.add_leaf("[dim]No system loaded[/dim]")
            return

        # Collect names defined in this module
        module_names: set[str] | None = None
        if self._loader:
            n2m = self._loader.names_to_modules
            ctx = self._loader.modules_contexts.get(module_name)
            is_main = ctx.is_main if ctx else False

            if is_main:
                # Main module owns all names NOT claimed by other modules
                claimed = set(n2m.keys())
                all_names = set()
                for d in (
                    self._system.facts,
                    self._system.terms,
                    self._system.axioms,
                    self._system.theorems,
                    self._system.diffs,
                ):
                    if d:
                        all_names.update(d.keys())
                module_names = all_names - claimed
            else:
                module_names = {name for name, mod in n2m.items() if mod == module_name}

        populate_system_tree(tree.root, self._system, names=module_names)

        # Add error/unreachable sections from AST analysis
        source = self._module_sources.get(module_name, "")
        if source and self._system:
            from ..pltg_highlight import _analyze_source

            ctx = self._loader.modules_contexts.get(module_name) if self._loader else None
            ns = None if (ctx and ctx.is_main) else module_name
            analysis = _analyze_source(source, self._system, module_name=ns)
            if analysis.errors:
                err_branch = tree.root.add(f"[bold red]Errors ({len(analysis.errors)})[/bold red]")
                for name in sorted(analysis.errors):
                    ast_node = analysis.errors[name]
                    node = err_branch.add(f"[red]{name}[/red]  [dim]({ast_node.kind})[/dim]")
                    # Show unresolved deps (the reason this failed)
                    for dep in analysis.unresolved_deps(name):
                        node.add_leaf(f"[dim red]missing: {dep}[/dim red]")
                    # Show what this error breaks
                    affected = analysis.affected_by(name)
                    if affected:
                        cascade = node.add(f"[dim]breaks {len(affected)} dependent(s)[/dim]")
                        for dep_node in sorted(affected, key=lambda n: n.name or ""):
                            cascade.add_leaf(f"[dim]{dep_node.name}[/dim]  [dim]({dep_node.kind})[/dim]")
                err_branch.expand()
            if analysis.unreachable:
                skip_branch = tree.root.add(f"[dim yellow]Unreachable ({len(analysis.unreachable)})[/dim yellow]")
                for name in sorted(analysis.unreachable):
                    ast_node = analysis.unreachable[name]
                    node = skip_branch.add(f"[dim yellow]{name}[/dim yellow]  [dim]({ast_node.kind})[/dim]")
                    # Show missing deps
                    missing_deps = [d for d in ast_node.dep_names if d in analysis.missing]
                    for dep in missing_deps:
                        node.add_leaf(f"[dim red]needs: {dep}[/dim red]")
                    # Trace root cause
                    root = analysis.root_cause(name)
                    if root:
                        node.add_leaf(f"[red]root cause: {root.name}[/red]  [dim]({root.kind})[/dim]")
                skip_branch.expand()

    def action_copy_module(self) -> None:
        """Copy the active tab's module source to clipboard."""
        import subprocess

        tabs = self.query_one("#modules-tabs", TabbedContent)
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
        self.notify("Module source copied to clipboard.")

    def action_ref_clicked(self, ref_type: str, ref_name: str) -> None:
        """Handle @click from PassViewer refs."""
        tree = self.query_one("#modules-state-tree", FocusedTree)
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
        self.notify(f"{ref_type}:{ref_name} not in state tree.", severity="warning")
