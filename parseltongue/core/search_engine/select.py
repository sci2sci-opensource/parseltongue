"""File selection — one classification, explicit settings, no policy.

The single decision function for "which files belong to a corpus":
indexing (bench) and document loading (language) both parameterize it —
the bench conservatively from pg.toml plus its caching layers, the
language permissively from effect keywords. The settings space is the
whole policy surface; neither consumer carries hidden rules the other
cannot express.
"""

import fnmatch
from pathlib import Path

# Directories/files nobody ever wants swept up by default.
DEFAULT_IGNORE = [".git", ".hg", ".svn", "node_modules", ".*"]


def is_ignored(rel_path: str, patterns: "list[str] | tuple") -> bool:
    """Check if a relative path matches any pattern (gitignore-style).

    A leading ``/`` anchors the pattern at the root (gitignore semantics):
    ``/tmp`` matches ``tmp`` and ``tmp/...`` at the top level only, not
    ``a/tmp``. Unanchored patterns match at any depth.
    """
    parts = Path(rel_path).parts
    for pat in patterns:
        pat = str(pat)
        dir_only = pat.endswith("/")
        anchored = pat.startswith("/")
        p = pat.strip("/")
        if not p:
            continue
        # Full path match
        if fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(rel_path, p + "/*"):
            return True
        if anchored:
            # Root-relative only — no suffix or component matching.
            continue
        # Any suffix of the path (gitignore matches at any level)
        for i in range(len(parts)):
            sub = str(Path(*parts[i:]))
            if fnmatch.fnmatch(sub, p):
                return True
            if dir_only and fnmatch.fnmatch(sub, p + "/*"):
                return True
        # For directory patterns, check if any parent dir matches
        if dir_only:
            for i in range(len(parts) - 1):
                parent = str(Path(*parts[: i + 1]))
                if fnmatch.fnmatch(parent, p):
                    return True
                # Single-segment pattern matches any dir component
                if "/" not in p and fnmatch.fnmatch(parts[i], p):
                    return True
    return False


def classify_file(
    rel_path: str,
    size: int,
    *,
    ignore_patterns: "list[str] | tuple" = (),
    extensions: "list[str] | tuple | None" = None,
    max_bytes: "int | None" = None,
    allow_large: "list[str] | tuple" = (),
) -> str:
    """Classify one file: 'ok' | 'ignored' | 'extension' | 'oversized'.

    extensions=None admits every extension; max_bytes=None admits every
    size. Every skip has a name — nothing is dropped silently.
    """
    if is_ignored(rel_path, ignore_patterns):
        return "ignored"
    if extensions is not None and not any(rel_path.endswith(e) for e in extensions):
        return "extension"
    if max_bytes is not None and size > max_bytes:
        if not allow_large or not is_ignored(rel_path, allow_large):
            return "oversized"
    return "ok"


def select_files(
    root: "str | Path",
    pattern: str = "**/*",
    *,
    ignore_patterns: "list[str] | tuple" = (),
    ignore_file: "str | Path | None" = None,
    extensions: "list[str] | tuple | None" = None,
    max_bytes: "int | None" = None,
    allow_large: "list[str] | tuple" = (),
) -> "tuple[list[str], dict[str, str]]":
    """Select corpus files under root matching a glob pattern.

    Returns (selected, skipped) — selected as sorted root-relative posix
    paths, skipped as {rel_path: reason}. ignore_file contributes extra
    gitignore-style lines (comments and blanks dropped) on top of
    ignore_patterns.
    """
    base = Path(root)
    entries = [
        (path.relative_to(base).as_posix(), path.stat().st_size)
        for path in sorted(base.glob(pattern))
        if path.is_file()
    ]
    return select_entries(
        entries,
        ignore_patterns=ignore_patterns,
        ignore_lines=Path(ignore_file).read_text().splitlines() if ignore_file is not None else (),
        extensions=extensions,
        max_bytes=max_bytes,
        allow_large=allow_large,
    )


def select_entries(
    entries: "list[tuple[str, int]]",
    *,
    ignore_patterns: "list[str] | tuple" = (),
    ignore_lines: "list[str] | tuple" = (),
    extensions: "list[str] | tuple | None" = None,
    max_bytes: "int | None" = None,
    allow_large: "list[str] | tuple" = (),
) -> "tuple[list[str], dict[str, str]]":
    """Classify listed files: `entries` are (root-relative posix path, size)
    pairs from any listing. ignore_lines are the lines of an ignore file
    (comments and blanks dropped) added to ignore_patterns. Returns
    (selected, skipped) as select_files does.
    """
    patterns = list(ignore_patterns)
    for line in ignore_lines:
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)

    selected: list[str] = []
    skipped: dict[str, str] = {}
    for rel, size in entries:
        verdict = classify_file(
            rel,
            size,
            ignore_patterns=patterns,
            extensions=extensions,
            max_bytes=max_bytes,
            allow_large=allow_large,
        )
        if verdict == "ok":
            selected.append(rel)
        else:
            skipped[rel] = verdict
    return selected, skipped
