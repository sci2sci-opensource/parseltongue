"""File type mappings for Parseltongue.

Two families:
  - parseltongue scripts: .pg, .pltg
  - pgmd (prose + truth): .pgmd, .pg.md, .md (compatible)
"""

# ── Type constants ──

PARSELTONGUE_SCRIPT = "parseltongue"  # .pg, .pltg — executable scripts
PGMD = "pgmd"  # .pgmd, .pg.md — prose notebooks wired with truth
MARKDOWN = "markdown"  # .md — plain markdown, compatible with pgmd rendering

# ── Extension → type ──

EXT_TYPE = {
    ".pg": PARSELTONGUE_SCRIPT,
    ".pltg": PARSELTONGUE_SCRIPT,
    ".pgmd": PGMD,
    ".pg.md": PGMD,  # compound extension — checked first
    ".md": MARKDOWN,
}

# pgmd-compatible: can all be rendered the same way
PGMD_COMPATIBLE = {PGMD, MARKDOWN}


# ── Helpers ──


def file_type(path_or_name: str) -> str | None:
    """Return the canonical type for a file, or None if unknown."""
    name = path_or_name.lower()
    # Compound extensions first
    if name.endswith(".pg.md"):
        return PGMD
    # Simple extension
    dot = name.rfind(".")
    if dot >= 0:
        return EXT_TYPE.get(name[dot:])
    return None


def is_renderable(path_or_name: str) -> bool:
    """True if the file can be rendered as a pgmd-style notebook."""
    return file_type(path_or_name) in PGMD_COMPATIBLE
