"""pgmd inline reference plugin.

Adds support for ``[[type:name]]`` references in markdown text.
These are parsed into structured tokens BEFORE markdown link parsing,
so ``|[[fact:x]]|`` in a table cell is correctly handled as a table
cell containing a ref, not as a ref with ``|`` prefix/suffix.

Supported syntax::

    [[fact:revenue]]          # inline value + footnote
    [[term:growth]]           # derived value + footnote
    [[~term:margin-check]]    # silent (footnote only, no inline value)
    $[[fact:revenue]]         # prefix ($2.4M)
    [[fact:nrr]]%             # suffix (80%)
    [[term:ratio]]x           # suffix (4.91x)

Token structure::

    {
        "type": "pgmd_ref",
        "raw": "$[[fact:revenue]]",
        "attrs": {
            "prefix": "$",
            "suffix": "",
            "silent": False,
            "ref_type": "fact",
            "ref_name": "revenue",
        }
    }
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Match

if TYPE_CHECKING:
    from ..core import InlineState
    from ..markdown import Markdown

__all__ = ["pgmd_ref"]

# Prefix: 0+ non-whitespace chars that are NOT markdown structural or brackets
# Suffix: 0+ non-whitespace chars that are NOT markdown structural or brackets
_PREFIX_CHARS = r"[^\s\[\]|*_>`#\-]*?"
_SUFFIX_CHARS = r"[^\s\[\]|*_>`#\-]*"

# Pattern uses non-capturing groups — the scanner wraps it in (?P<pgmd_ref>...).
# We re-parse m.group(0) with _PARSE_RE to extract the parts.
PGMD_REF_PATTERN = _PREFIX_CHARS + r"\[\[~?\w+:[^\]]+\]\]" + _SUFFIX_CHARS

_PARSE_RE = re.compile(
    r"^(" + _PREFIX_CHARS + r")" r"\[\[" r"(~?)" r"(\w+)" r":" r"([^\]]+)" r"\]\]" r"(" + _SUFFIX_CHARS + r")$"
)


def parse_pgmd_ref(inline: Any, m: Match[str], state: "InlineState") -> int:
    full = m.group(0)
    pm = _PARSE_RE.match(full)
    if not pm:
        state.append_token({"type": "text", "raw": full})
        return m.end()

    state.append_token(
        {
            "type": "pgmd_ref",
            "raw": full,
            "attrs": {
                "prefix": pm.group(1) or "",
                "suffix": pm.group(5) or "",
                "silent": bool(pm.group(2)),
                "ref_type": pm.group(3),
                "ref_name": pm.group(4),
            },
        }
    )
    return m.end()


def pgmd_ref(md: "Markdown") -> None:
    """Register the pgmd_ref inline rule. Must fire before 'link'."""
    md.inline.register(
        "pgmd_ref",
        PGMD_REF_PATTERN,
        parse_pgmd_ref,
        before="link",
    )
