"""DiffView — toggleable unified/split diff widget for Textual.

Reads file content from disk using ``old_string`` to locate the change
region, then shows a proper diff with context, line numbers, and
token-level highlights.  Press ``t`` to toggle between merged and split.

Extends Static (not RichLog) so it can be safely embedded inside
VerticalScroll without causing nested-scrollable layout issues.
"""

from __future__ import annotations

from pathlib import Path

from textual.binding import Binding
from textual.widgets import Static

from .diff_table import build_split_diff_table, build_unified_diff_table


class DiffView(Static):
    """Diff viewer with merged/split toggle. Safe to embed in VerticalScroll."""

    DEFAULT_CSS = """
    DiffView {
        width: 1fr;
        height: auto;
        max-height: 30;
        overflow: hidden;
        border: solid $warning;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("t", "toggle_view", "Toggle split/merged", show=False),
    ]

    def __init__(
        self,
        filepath: str,
        old_string: str,
        new_string: str,
        *,
        context: int = 3,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._filepath = filepath
        self._old_string = old_string
        self._new_string = new_string
        self._diff_context = context
        self._split_mode = False
        self._before, self._after = self._build_context()

    def _build_context(self) -> tuple[str, str]:
        """Read the file and produce before/after texts around the edit."""
        try:
            content = Path(self._filepath).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return self._old_string, self._new_string

        if self._old_string and self._old_string in content:
            idx = content.index(self._old_string)
            prefix = content[:idx]
            suffix = content[idx + len(self._old_string) :]

            pre_lines = prefix.splitlines()
            ctx_before = pre_lines[-(self._diff_context + 5) :] if pre_lines else []
            post_lines = suffix.splitlines()
            ctx_after = post_lines[: self._diff_context + 5] if post_lines else []

            before_block = (
                "\n".join(ctx_before)
                + ("\n" if ctx_before else "")
                + self._old_string
                + ("\n" if ctx_after else "")
                + "\n".join(ctx_after)
            )
            after_block = (
                "\n".join(ctx_before)
                + ("\n" if ctx_before else "")
                + self._new_string
                + ("\n" if ctx_after else "")
                + "\n".join(ctx_after)
            )
            return before_block, after_block
        else:
            return self._old_string, self._new_string

    def on_mount(self) -> None:
        self._render_diff()

    def _render_diff(self) -> None:
        if self._split_mode:
            table = build_split_diff_table(
                self._before,
                self._after,
                filepath=self._filepath,
                context=self._diff_context,
            )
        else:
            table = build_unified_diff_table(
                self._before,
                self._after,
                filepath=self._filepath,
                context=self._diff_context,
            )
        self.update(table)

    def action_toggle_view(self) -> None:
        self._split_mode = not self._split_mode
        self._render_diff()
