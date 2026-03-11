"""Pygments-based syntax highlighting for Textual's TextArea.

Uses the same Pygments tokenization + color mapping as PassViewer so that
the editor colors match the read-only viewer exactly.  Works with any
Pygments lexer — file extension → lexer name mapping in EXTENSION_LEXERS.

Supports live error/unreachable highlighting: call ``set_system()`` with the
current System to cross-reference AST definitions against loaded state.
Definitions that failed show as "error", those with failed deps as "unreachable".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pygments import lex
from pygments.lexers import get_lexer_by_name
from textual.widgets import TextArea

from .widgets.colors import PLTG_THEME, token_highlight_name

log = logging.getLogger("parseltongue.cli")

# File extension → Pygments lexer name
EXTENSION_LEXERS: dict[str, str] = {
    ".pltg": "scheme",
    ".pgmd": "markdown",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".txt": "text",
    ".html": "html",
    ".css": "css",
    ".xml": "xml",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".lua": "lua",
    ".sql": "sql",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".java": "java",
}


@dataclass
class SourceAnalysis:
    """Result of analyzing source against the system.

    Nodes are the actual DirectiveNode objects from the AST — they carry
    the full dependency graph (children, dependents, walk_dependents).
    """

    errors: dict[str, Any]  # name → DirectiveNode (not in system, deps ok)
    unreachable: dict[str, Any]  # name → DirectiveNode (has missing deps)
    missing: set[str]  # all names not in system (local file)
    node_index: dict[str, Any]  # name → DirectiveNode for all named nodes
    system_names: set[str]  # all names present in the system
    module_name: str | None  # module namespace (for qualifying names)

    @property
    def error_names(self) -> set[str]:
        return set(self.errors)

    @property
    def unreachable_names(self) -> set[str]:
        return set(self.unreachable)

    def root_cause(self, name: str) -> Any | None:
        """Trace an unreachable node back to the root error.

        Follows missing deps recursively until finding a node
        whose own deps are all present — that's the direct error.
        """
        seen: set[str] = set()
        current = name
        while current in self.unreachable and current not in seen:
            seen.add(current)
            node = self.unreachable[current]
            # Find the first dep that's also missing
            for dep in node.dep_names:
                if dep in self.missing:
                    current = dep
                    break
            else:
                break
        if current in self.errors:
            return self.errors[current]
        return None

    def affected_by(self, name: str) -> list[Any]:
        """All nodes transitively affected by a failed definition."""
        node = self.node_index.get(name)
        if node is None:
            return []
        return node.walk_dependents()

    def unresolved_deps(self, name: str) -> list[str]:
        """Deps of a node that aren't found anywhere in the system.

        Checks both qualified (module_name.dep) and bare dep names
        against system_names. Returns the bare dep names that can't
        be resolved.
        """
        node = self.node_index.get(name)
        if node is None:
            return []
        result = []
        for dep in node.dep_names:
            # Check bare name
            if dep in self.system_names:
                continue
            # Check qualified with this module's namespace
            if self.module_name and f"{self.module_name}.{dep}" in self.system_names:
                continue
            result.append(dep)
        return result


def _analyze_source(
    source: str,
    system,
    module_name: str | None = None,
) -> SourceAnalysis:
    """Parse source into AST, cross-reference with system.

    Args:
        source: The pltg source text.
        system: The System to check names against.
        module_name: If set, names are looked up as ``module_name.name``
            in the system (non-main modules are namespaced by the loader).
            The returned names are BARE (as they appear in source).

    Returns a SourceAnalysis with error and unreachable dicts.
    """
    from parseltongue.core.ast import parse_directive, resolve_graph
    from parseltongue.core.atoms import read_tokens, tokenize

    empty = SourceAnalysis(
        errors={},
        unreachable={},
        missing=set(),
        node_index={},
        system_names=set(),
        module_name=module_name,
    )

    if not system:
        return empty

    try:
        tokens = tokenize(source)
    except Exception:
        return empty

    nodes = []
    order = 0
    while tokens:
        try:
            expr = read_tokens(tokens)
        except Exception:
            order += 1
            continue
        node = parse_directive(expr, order)
        nodes.append(node)
        order += 1

    resolve_graph(nodes)

    # All names known to the system (definitions + env builtins)
    system_names: set[str] = set()
    for store in (system.facts, system.terms, system.axioms, system.theorems, system.diffs):
        if store:
            system_names.update(store.keys())
    # Include engine env (builtins like =, implies, and, or, +, -, *, /)
    if hasattr(system, "engine") and hasattr(system.engine, "env"):
        system_names.update(str(k) for k in system.engine.env)

    def _qualified(name: str) -> str:
        if module_name:
            return f"{module_name}.{name}"
        return name

    # Build name → node index, find missing
    node_index: dict[str, Any] = {}
    missing: set[str] = set()
    for node in nodes:
        if node.name:
            node_index[node.name] = node
            if _qualified(node.name) not in system_names:
                missing.add(node.name)

    errors: dict[str, Any] = {}
    unreachable: dict[str, Any] = {}

    for name in missing:
        node = node_index[name]
        has_missing_dep = any(d in missing for d in node.dep_names)
        if has_missing_dep:
            unreachable[name] = node
        else:
            errors[name] = node

    return SourceAnalysis(
        errors=errors,
        unreachable=unreachable,
        missing=missing,
        node_index=node_index,
        system_names=system_names,
        module_name=module_name,
    )


class PygmentsTextArea(TextArea):
    """TextArea with Pygments-based syntax highlighting.

    Pass ``pygments_lexer`` to set the lexer name (e.g. "scheme", "python").
    Colors are driven by PLTG_THEME built from the shared PALETTE.

    Call ``set_system(system)`` to enable error/unreachable highlighting
    based on which definitions are present in the system.
    """

    def __init__(self, *args, pygments_lexer: str = "scheme", **kwargs) -> None:
        # Set lexer BEFORE super().__init__ because it calls _build_highlight_map
        try:
            self._pygments_lexer = get_lexer_by_name(pygments_lexer)
        except Exception:
            self._pygments_lexer = get_lexer_by_name("text")
        self._system = None
        self._module_name: str | None = None
        self._error_names: set[str] = set()
        self._unreachable_names: set[str] = set()
        super().__init__(*args, **kwargs)
        self._force_pltg_theme()

    def _force_pltg_theme(self) -> None:
        """Force the pltg theme — bypasses reactive watcher races."""
        import dataclasses

        self._themes["pltg"] = PLTG_THEME
        self._theme = dataclasses.replace(PLTG_THEME)
        # Set reactive without triggering watcher (already applied above)
        self.set_reactive(TextArea.theme, "pltg")

    def _on_mount(self, event) -> None:
        super()._on_mount(event)
        self._force_pltg_theme()
        self._build_highlight_map()

    def set_system(self, system, module_name: str | None = None) -> None:
        """Set the system for error/unreachable analysis and re-highlight."""
        self._system = system
        if module_name is not None:
            self._module_name = module_name
        self._reanalyze()
        self._build_highlight_map()

    def _reanalyze(self) -> None:
        """Re-parse source against current system state."""
        text = self.document.text if hasattr(self, "document") and self.document else ""
        if not text or not self._system:
            self._error_names = set()
            self._unreachable_names = set()
            return
        try:
            analysis = _analyze_source(
                text,
                self._system,
                module_name=self._module_name,
            )
            self._error_names = analysis.error_names
            self._unreachable_names = analysis.unreachable_names
        except Exception:
            log.debug("Source analysis failed", exc_info=True)
            self._error_names = set()
            self._unreachable_names = set()

    def _build_highlight_map(self) -> None:
        """Tokenize with Pygments and populate _highlights for the renderer."""
        self._line_cache.clear()
        highlights = self._highlights
        highlights.clear()

        text = self.document.text
        if not text:
            return

        # Re-analyze for error/unreachable on each rebuild
        if self._system:
            self._reanalyze()

        line_index = 0
        col_byte = 0

        for tok_type, tok_val in lex(text, self._pygments_lexer):
            if not tok_val:
                continue

            highlight_name = token_highlight_name(tok_type, tok_val)

            # Override with error/unreachable if token matches a flagged name
            stripped = tok_val.strip()
            if stripped in self._error_names:
                highlight_name = "error"
            elif stripped in self._unreachable_names:
                highlight_name = "unreachable"

            parts = tok_val.split("\n")

            for pi, part in enumerate(parts):
                if pi > 0:
                    line_index += 1
                    col_byte = 0
                part_bytes = len(part.encode("utf-8"))
                if part and highlight_name:
                    highlights[line_index].append((col_byte, col_byte + part_bytes, highlight_name))
                col_byte += part_bytes


# Convenience alias
PltgTextArea = PygmentsTextArea
