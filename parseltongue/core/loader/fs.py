"""Filesystem access for the loader.

The loader reads sources and documents only through a ``LoaderFS``: the
entry file, lib entry points, imports, ``load-document`` and
``load-documents``. ``LocalFS`` is the local disk. Another implementation
can serve the same paths from anywhere: memory, a git object store, a
document service.

Paths are absolute, in the form ``os.path`` produces for the host.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@runtime_checkable
class LoaderFS(Protocol):
    def is_file(self, path: str) -> bool:
        """Whether `path` names a readable file."""
        ...

    def read_text(self, path: str) -> str:
        """The text of the file at `path`; FileNotFoundError when there is none."""
        ...

    def list_files(self, root: str, pattern: str) -> list[tuple[str, int]]:
        """Files under `root` matching the glob `pattern`, as sorted
        (root-relative posix path, size in bytes) pairs."""
        ...

    def digest(self, path: str) -> str:
        """sha256 hex digest of the file's bytes; "" when it cannot be read."""
        ...


class LocalFS:
    """The local disk."""

    def is_file(self, path: str) -> bool:
        return Path(path).is_file()

    def read_text(self, path: str) -> str:
        return Path(path).read_text()

    def digest(self, path: str) -> str:
        # Empty files short-circuit without opening; larger ones stream so
        # peak memory stays bounded whatever the file size.
        try:
            if os.stat(path).st_size == 0:
                return _EMPTY_SHA256
            with open(path, "rb") as fp:
                return hashlib.file_digest(fp, "sha256").hexdigest()
        except OSError:
            return ""

    def list_files(self, root: str, pattern: str) -> list[tuple[str, int]]:
        base = Path(root)
        return [
            (path.relative_to(base).as_posix(), path.stat().st_size)
            for path in sorted(base.glob(pattern))
            if path.is_file()
        ]
