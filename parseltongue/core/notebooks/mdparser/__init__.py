"""Markdown parser for pgmd notebooks.

Based on mistune 3.2.0 — see ACKNOWLEDGEMENT.md.
"""

from .block_parser import BlockParser
from .core import BaseRenderer, BlockState, InlineState
from .inline_parser import InlineParser
from .markdown import Markdown
from .plugins.pgmd_ref import pgmd_ref as pgmd_ref_plugin
from .plugins.table import table as table_plugin
from .util import escape


def create_markdown(renderer=None, plugins=None):
    """Create a Markdown instance. renderer=None for AST mode."""
    inline = InlineParser()
    md = Markdown(renderer=renderer, inline=inline)
    # Always enable table + pgmd ref support
    pgmd_ref_plugin(md)
    table_plugin(md)
    if plugins:
        for plugin in plugins:
            plugin(md)
    return md


def parse_md_ast(text: str) -> list[dict]:
    """Parse markdown text into an AST (list of token dicts)."""
    md = create_markdown()
    tokens, _state = md.parse(text)
    return tokens


__all__ = [
    "Markdown",
    "BlockParser",
    "InlineParser",
    "BaseRenderer",
    "BlockState",
    "InlineState",
    "create_markdown",
    "parse_md_ast",
    "escape",
]
