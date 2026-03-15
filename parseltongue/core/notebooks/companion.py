"""Stateful companion file tracker for pgmd notebooks.

Manages the lifecycle of a companion file (``.<name>.pltg``, e.g.
``.analysis.pgmd.pltg`` for ``analysis.pgmd``) for a single pgmd
source file.  Handles all file I/O: creation, reading, writing,
and integrity checking.

Uses :mod:`companion_integrity` for pure cryptographic verification
and :mod:`merkle` for structural integrity within blocks.

Separation of Concerns
----------------------

:mod:`companion_integrity`
    Pure functions.  Takes strings, returns integrity results.
    No I/O, no state, no filesystem.

:mod:`merkle`
    Pure functions.  Builds Merkle trees over S-expressions.
    No I/O, no state, no filesystem.

:mod:`companion` (this module)
    Stateful.  Owns the filesystem path, reads/writes the companion
    file, tracks which blocks are executed, delegates integrity
    checks to the pure modules.

Usage
-----

::

    from parseltongue.core.notebooks.companion import CompanionTracker, companion_path_for

    tracker = CompanionTracker(pgmd_path, companion_path_for(pgmd_path))

    # Check current state
    for bn, bi in tracker.integrity.blocks.items():
        print(bn, bi.status.name, tracker.chain[bn][:8])

    # Execute a block (writes to companion file)
    tracker.execute(0, block_content)

    # Rollback a block (removes from companion, re-checks integrity)
    tracker.rollback(2)

    # Source file changed externally
    tracker.reload_source()

    # Get the LazyLoader system after execution
    system = tracker.system
"""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

from .companion_integrity import (
    IntegrityResult,
    check_integrity,
    clear_block,
    insert_block,
    replace_block,
)

log = logging.getLogger("parseltongue")


def companion_path_for(pgmd_path: Path) -> Path:
    """Return the companion file path for a given pgmd file."""
    resolved = pgmd_path.resolve()
    return resolved.parent / f".{resolved.name}.pltg"


class CompanionTracker:
    """Manages a companion file for one pgmd source.

    Parameters
    ----------
    pgmd_path : Path
        Path to the pgmd source file.
    companion_name : str, optional
        Template for companion filename.  ``{name}`` is the full
        filename (e.g. ``analysis.pgmd``), ``{stem}`` is without
        extension.  Defaults to ``.{name}.pltg``.
    """

    def __init__(
        self,
        pgmd_path: Path,
        companion_path: Path,
    ) -> None:
        self._pgmd_path = pgmd_path.resolve()
        self._companion_path = companion_path.resolve()
        self._source: str = self._pgmd_path.read_text()
        self._companion_text: str = self._companion_path.read_text() if self._companion_path.exists() else ""
        self._executed: set[int] = set()
        self._integrity: IntegrityResult | None = None
        self._system: object = None
        self._loader: object = None

        # Initial integrity check
        self._recheck()
        # If valid blocks exist, load them
        if self._executed:
            self._reload_quietly()

    # ── Properties ──

    @property
    def pgmd_path(self) -> Path:
        return self._pgmd_path

    @property
    def companion_path(self) -> Path:
        return self._companion_path

    @property
    def source(self) -> str:
        return self._source

    @property
    def companion_text(self) -> str:
        return self._companion_text

    @property
    def integrity(self) -> IntegrityResult:
        """Current integrity result.  Re-checked on every mutation."""
        if self._integrity is None:
            self._recheck()
        assert self._integrity is not None
        return self._integrity

    @property
    def chain(self) -> list[str]:
        """Expected hash chain from current source."""
        return self.integrity.chain

    @property
    def executed(self) -> set[int]:
        """Set of block numbers that are valid in the companion."""
        return set(self._executed)

    @property
    def system(self):
        """The parseltongue System after loading the companion, or None."""
        return self._system

    @property
    def loader(self):
        """The LazyLoader after loading the companion, or None."""
        return self._loader

    # ── Mutations ──

    def execute(self, block_num: int, content: str) -> None:
        """Write a block to the companion file and re-check integrity.

        If the block was already executed, it is replaced in-place.
        Otherwise it is appended.
        """
        if block_num in self._executed:
            self._companion_text = replace_block(self._companion_text, block_num, content, self.chain)
        else:
            self._companion_text = insert_block(self._companion_text, block_num, content, self.chain)
        self._write_companion()
        self._executed.add(block_num)
        self._recheck()

    def rollback(self, block_num: int) -> None:
        """Clear a block's content in the companion file and re-check integrity.

        The block markers are kept but content is emptied, which
        naturally hash-mismatches on integrity check and breaks
        the chain for subsequent blocks.
        """
        self._companion_text = clear_block(self._companion_text, block_num)
        self._write_companion()
        self._recheck()

    def reload_source(self) -> bool:
        """Re-read the pgmd source from disk.  Returns True if it changed.

        After reloading, integrity is re-checked.  Blocks whose content
        changed will show as INVALID; subsequent blocks become STALE.
        """
        try:
            new_source = self._pgmd_path.read_text()
        except Exception:
            return False
        if new_source == self._source:
            return False
        self._source = new_source
        self._recheck()
        return True

    def reload_companion(self) -> bool:
        """Re-read the companion file from disk.  Returns True if it changed.

        Detects external modifications to the companion (e.g. another
        process, manual edit).  After reloading, integrity is re-checked.
        """
        try:
            new_text = self._companion_path.read_text() if self._companion_path.exists() else ""
        except Exception:
            return False
        if new_text == self._companion_text:
            return False
        self._companion_text = new_text
        self._recheck()
        return True

    def reset(self) -> None:
        """Clear the companion file and all state.  Fresh start."""
        self._companion_text = ""
        self._write_companion()
        self._executed.clear()
        self._system = None
        self._loader = None
        self._recheck()

    # ── Internal ──

    def _recheck(self) -> None:
        """Run integrity check and sync executed set from results."""
        self._integrity = check_integrity(self._source, self._companion_text)
        self._executed = set(self._integrity.valid)

    def _write_companion(self) -> None:
        """Flush companion text to disk."""
        self._companion_path.write_text(self._companion_text)

    def _reload_quietly(self) -> None:
        """Load the companion through LazyLoader silently (no UI output)."""
        from ..loader import LazyLoader

        if not self._companion_text.strip():
            return

        loader = LazyLoader()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            loader.load_main(str(self._companion_path))
        except Exception:
            log.debug("CompanionTracker: load failed", exc_info=True)
        finally:
            sys.stdout = old_out
            sys.stderr = old_err

        self._system = loader.last_result.system if loader.last_result else None
        self._loader = loader
