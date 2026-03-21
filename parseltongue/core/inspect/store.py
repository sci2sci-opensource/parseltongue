"""Store — disk cache for the Bench.

Merkle trees, file hashing, serialization. Pure storage —
knows nothing about loaders, probing, or status. The Technician
reads from and writes to the Store; the Bench never touches disk.

Cache files use the .pgz format: zlib-compressed JSON with a
SHA-256 integrity header.

.pgz layout::

    [4 bytes]  magic   "PGZ\\x01"
    [32 bytes] SHA-256 of uncompressed payload
    [4 bytes]  uncompressed size (uint32 LE)
    [rest]     zlib-compressed payload (JSON bytes)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
import zlib
from pathlib import Path
from typing import Callable

from ..ast import DirectiveNode
from ..integrity.merkle import MerkleNode, _sha256, merkle_combine
from ..loader.lazy_loader import LazyLoader, LazyLoadResult
from ..quote_verifier import DocumentIndex
from ..system import System
from .evaluation import Evaluation
from .probe_core_to_consequence import CoreToConsequenceStructure
from .serialization import deserialize_structure, serialize_structure

log = logging.getLogger("parseltongue.store")

BENCH_DIR = ".parseltongue-bench"

# ── .pgz format ──

_PGZ_MAGIC = b"PGZ\x01"
_PGZ_HEADER = struct.Struct("<4s32sI")  # magic + sha256 + size


def _pgz_write(path: Path, data: bytes):
    """Write data to a .pgz file."""
    digest = hashlib.sha256(data).digest()
    compressed = zlib.compress(data, level=6)
    header = _PGZ_HEADER.pack(_PGZ_MAGIC, digest, len(data))
    path.write_bytes(header + compressed)


def _pgz_read(path: Path) -> bytes:
    """Read and verify a .pgz file. Raises on corruption."""
    raw = path.read_bytes()
    if len(raw) < _PGZ_HEADER.size:
        raise ValueError("File too small for .pgz header")
    magic, expected_digest, size = _PGZ_HEADER.unpack_from(raw)
    if magic != _PGZ_MAGIC:
        raise ValueError(f"Bad magic: {magic!r}")
    compressed = raw[_PGZ_HEADER.size :]
    data = zlib.decompress(compressed)
    if len(data) != size:
        raise ValueError(f"Size mismatch: expected {size}, got {len(data)}")
    actual_digest = hashlib.sha256(data).digest()
    if actual_digest != expected_digest:
        raise ValueError("SHA-256 integrity check failed")
    return data


def _collect_tree_leaves(node: MerkleNode) -> dict[str, str]:
    """Collect {content: hash} for all leaves in a Merkle tree."""
    if node.is_leaf:
        return {node.content: node.hash} if node.content else {}
    result = {}
    for child in node.children or []:
        result.update(_collect_tree_leaves(child))
    return result


def _load_pgignore(directory: str) -> list[str]:
    """Load .pgignore patterns from directory (gitignore-style). Returns pattern list."""
    pgignore = Path(directory) / ".pgignore"
    if not pgignore.exists():
        return []
    patterns = []
    for line in pgignore.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any .pgignore pattern (gitignore-style)."""
    import fnmatch

    parts = Path(rel_path).parts
    for pat in patterns:
        dir_only = pat.endswith("/")
        p = pat.rstrip("/")
        # Full path match
        if fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(rel_path, p + "/*"):
            return True
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


class Store:
    """Disk cache for bench state.

    Handles:
    - File hashing and Merkle tree construction
    - Reading/writing cached data to .pgz files
    - Deserializing cached data back into structures + loaders
    - Evaluation cache (separate .dx.pgz files)
    """

    def __init__(self, bench_dir: str | Path | None = None):
        self._dir = Path(bench_dir or BENCH_DIR)

    # ── File hashing ──

    def hash_files(self, files: list[str]) -> dict[str, str]:
        """Hash each file's content. Returns {path: sha256}."""
        hashes = {}
        for f in files:
            try:
                hashes[f] = _sha256(Path(f).read_text())
            except OSError:
                hashes[f] = ""
        return hashes

    def build_file_tree(self, files: list[str], hashes: dict[str, str]) -> MerkleNode:
        """Build Merkle tree where each file is a leaf."""
        leaves = []
        for f in files:
            h = hashes.get(f, _sha256(""))
            leaves.append(MerkleNode(hash=h, content=f))
        if not leaves:
            return MerkleNode(hash=_sha256(""))
        return merkle_combine(leaves)

    def diff_file_hashes(self, old: dict[str, str], new: dict[str, str]) -> set[str]:
        """Find files whose hashes differ between old and new."""
        changed = set()
        for f in set(old) | set(new):
            if old.get(f) != new.get(f):
                changed.add(f)
        return changed

    # ── Read / write cache ──

    def read_raw(self, path: str) -> dict | None:
        """Read raw cache data from disk, or None."""
        cache_file = self._cache_path(path)
        if not cache_file.exists():
            # Migration: try legacy .json
            legacy = self._legacy_cache_path(path)
            if legacy.exists():
                return self._read_legacy(legacy)
            return None
        try:
            data = _pgz_read(cache_file)
            return json.loads(data)
        except Exception as e:
            log.warning("Failed to read cache for %s: %s", path, e)
            cache_file.unlink(missing_ok=True)
            return None

    def save(
        self,
        path: str,
        tree: MerkleNode,
        structure: CoreToConsequenceStructure,
        loader: LazyLoader,
        file_lists: list[str],
        file_hashes: dict[str, str],
    ):
        """Save bench state to disk as .pgz."""
        self._ensure_dir()
        result = loader.last_result
        assert result is not None
        node_index = {}
        for node in result._all_nodes:
            if node.name:
                node_index[node.name] = {
                    "source_file": node.source_file,
                    "source_line": node.source_line,
                    "kind": node.kind,
                }
        data = {
            "merkle_root": tree.hash,
            "merkle_tree": tree.to_dict(),
            "structure": serialize_structure(structure),
            "node_index": node_index,
            "source_files": file_lists,
            "file_hashes": file_hashes,
            "system": result.system.to_dict(),
        }
        try:
            payload = json.dumps(data, separators=(",", ":")).encode()
            _pgz_write(self._cache_path(path), payload)
            # Clean up legacy .json if it exists
            self._legacy_cache_path(path).unlink(missing_ok=True)
        except Exception as e:
            log.warning("Failed to save cache for %s: %s", path, e)

    def deserialize(self, data: dict) -> tuple[CoreToConsequenceStructure, LazyLoader]:
        """Deserialize structure + full system from cache data."""
        structure = deserialize_structure(data["structure"])

        if "system" in data:
            system = System.from_dict(data["system"])
        else:
            system = System()
        engine = system.engine
        for name, node in structure.graph.items():
            if name in engine.facts:
                node.atom = engine.facts[name]
            elif name in engine.axioms:
                node.atom = engine.axioms[name]
            elif name in engine.theorems:
                node.atom = engine.theorems[name]
            elif name in engine.terms:
                node.atom = engine.terms[name]
        loader = LazyLoader()
        loader._result = LazyLoadResult(system=system)
        nodes = []
        for name, info in data.get("node_index", {}).items():
            node = DirectiveNode(
                name=name,
                expr=[],
                dep_names=set(),
                kind=info.get("kind", ""),
                source_file=info.get("source_file"),
                source_order=0,
                source_line=info.get("source_line", 0),
            )
            nodes.append(node)
        loader._all_nodes = nodes
        loader._result._all_nodes = nodes
        return structure, loader

    # ── Evaluation cache ──

    def save_diagnosis(self, path: str, merkle_root: str, dx: Evaluation):
        """Save evaluation to disk as .pgz."""
        self._ensure_dir()
        data = {"merkle_root": merkle_root, "diagnosis": dx.to_dict()}
        try:
            payload = json.dumps(data, separators=(",", ":")).encode()
            _pgz_write(self._diagnosis_cache_path(path), payload)
            self._legacy_diagnosis_cache_path(path).unlink(missing_ok=True)
        except Exception as e:
            log.warning("Failed to save evaluation for %s: %s", path, e)

    def load_diagnosis(self, path: str, expected_merkle_root: str) -> Evaluation | None:
        """Load evaluation from disk if Merkle root matches."""
        data = self._read_diagnosis_raw(path)
        if data is None:
            return None
        if data.get("merkle_root") != expected_merkle_root:
            return None
        try:
            return Evaluation.from_dict(data["diagnosis"])
        except Exception:
            self._diagnosis_cache_path(path).unlink(missing_ok=True)
            return None

    def load_stale_diagnosis(self, path: str) -> Evaluation | None:
        """Load evaluation from disk regardless of Merkle root match."""
        data = self._read_diagnosis_raw(path)
        if data is None:
            return None
        try:
            return Evaluation.from_dict(data["diagnosis"])
        except Exception:
            self._diagnosis_cache_path(path).unlink(missing_ok=True)
            return None

    # ── Index cache ──

    def _index_cache_path(self, directory: str) -> Path:
        return self._dir / f"{self._cache_key(directory)}.idx.pgz"

    def save_index(
        self,
        key: str,
        directory: str,
        file_hashes: dict[str, str],
        index_data: dict,
        indexed_dirs: dict[str, list[str]] | None = None,
        file_stats: dict[str, list] | None = None,
        dir_mtimes: dict[str, int] | None = None,
        file_texts: dict[str, str] | None = None,
    ):
        """Save search index to disk as .idx.pgz. Key is the cache lookup key, directory is stored inside."""
        self._ensure_dir()
        data: dict = {"directory": directory, "file_hashes": file_hashes, "index": index_data}
        if indexed_dirs:
            data["indexed_dirs"] = indexed_dirs
        if file_stats:
            data["file_stats"] = file_stats
        if dir_mtimes:
            data["dir_mtimes"] = dir_mtimes
        if file_texts:
            data["file_texts"] = file_texts
        try:
            payload = json.dumps(data, separators=(",", ":")).encode()
            _pgz_write(self._index_cache_path(key), payload)
        except Exception as e:
            log.warning("Failed to save index for %s: %s", key, e)

    def load_index(self, key: str) -> dict | None:
        """Load cached index data, or None if not cached."""
        cache_file = self._index_cache_path(key)
        if not cache_file.exists():
            return None
        try:
            data = _pgz_read(cache_file)
            return json.loads(data)
        except Exception as e:
            log.warning("Failed to read index cache for %s: %s", key, e)
            cache_file.unlink(missing_ok=True)
            return None

    # ── Invalidation ──

    def remove(self, path: str):
        """Remove cache files for a specific path — includes viz cache."""
        self._cache_path(path).unlink(missing_ok=True)
        self._diagnosis_cache_path(path).unlink(missing_ok=True)
        self._index_cache_path(path).unlink(missing_ok=True)
        # Clean up legacy too
        self._legacy_cache_path(path).unlink(missing_ok=True)
        self._legacy_diagnosis_cache_path(path).unlink(missing_ok=True)
        # Viz cache depends on all other caches — clear on any invalidation
        if self._dir.exists():
            for f in self._dir.glob("*.viz.pgz"):
                f.unlink(missing_ok=True)

    def remove_all(self):
        """Remove all cache files."""
        if self._dir.exists():
            for f in self._dir.glob("*.pgz"):
                f.unlink()
            for f in self._dir.glob("*.json"):
                f.unlink()

    # ── Viz cache ──

    def _viz_cache_path(self, merkle_root: str, key: str) -> Path:
        tag = hashlib.sha256(f"{merkle_root}:{key}".encode()).hexdigest()[:16]
        return self._dir / f"{tag}.viz.pgz"

    def save_viz(self, merkle_root: str, key: str, html: str):
        """Cache rendered viz HTML keyed by Merkle root + view key."""
        self._ensure_dir()
        data = json.dumps({"merkle_root": merkle_root, "key": key, "html": html}, separators=(",", ":"))
        try:
            _pgz_write(self._viz_cache_path(merkle_root, key), data.encode())
        except Exception as e:
            log.warning("Failed to save viz cache %s/%s: %s", merkle_root[:8], key, e)

    def load_viz(self, merkle_root: str, key: str) -> str | None:
        """Load cached viz HTML if Merkle root matches."""
        path = self._viz_cache_path(merkle_root, key)
        if not path.exists():
            return None
        try:
            data = json.loads(_pgz_read(path))
            if data.get("merkle_root") != merkle_root:
                path.unlink(missing_ok=True)
                return None
            return data.get("html")
        except Exception:
            path.unlink(missing_ok=True)
            return None

    # ── Internals ──

    def _ensure_dir(self):
        self._dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, path: str) -> str:
        return hashlib.sha256(path.encode()).hexdigest()[:16]

    def _cache_path(self, path: str) -> Path:
        return self._dir / f"{self._cache_key(path)}.pgz"

    def _diagnosis_cache_path(self, path: str) -> Path:
        return self._dir / f"{self._cache_key(path)}.dx.pgz"

    def _legacy_cache_path(self, path: str) -> Path:
        return self._dir / f"{self._cache_key(path)}.json"

    def _legacy_diagnosis_cache_path(self, path: str) -> Path:
        return self._dir / f"{self._cache_key(path)}.dx.json"

    def _read_legacy(self, legacy_path: Path) -> dict | None:
        """Read a legacy .json cache file."""
        try:
            with open(legacy_path) as f:
                return json.load(f)
        except Exception as e:
            log.warning("Failed to read legacy cache %s: %s", legacy_path, e)
            legacy_path.unlink(missing_ok=True)
            return None

    def _read_diagnosis_raw(self, path: str) -> dict | None:
        """Read raw diagnosis data from .pgz or legacy .json."""
        cache_file = self._diagnosis_cache_path(path)
        if cache_file.exists():
            try:
                return json.loads(_pgz_read(cache_file))
            except Exception:
                cache_file.unlink(missing_ok=True)
        # Try legacy
        legacy = self._legacy_diagnosis_cache_path(path)
        if legacy.exists():
            return self._read_legacy(legacy)
        return None


def _stat_fingerprint(st: os.stat_result) -> tuple:
    """Git-style stat fingerprint: (ctime_ns, mtime_ns, dev, ino, mode, size)."""
    return (st.st_ctime_ns, st.st_mtime_ns, st.st_dev, st.st_ino, st.st_mode, st.st_size)


class SearchStore:

    def __init__(self, store: Store | None = None, path: str = "", index: DocumentIndex | None = None):
        self._store = store
        self._path = path
        self._dir_hashes: dict[str, dict[str, str]] = {}
        self._preloaded = index
        # Tracked directories: directory → extensions list
        self._indexed_dirs: dict[str, list[str]] = {}
        # Git-style stat cache: file_key → (ctime_ns, mtime_ns, dev, ino, mode, size)
        self._file_stats: dict[str, tuple] = {}
        # Directory mtime cache: abs_dir_path → mtime_ns
        self._dir_mtimes: dict[str, int] = {}

    def load_index(self) -> DocumentIndex:
        if self._preloaded is not None:
            return self._preloaded
        if not self._store:
            return DocumentIndex()
        cached = self._store.load_index(self._path)
        if not cached:
            return DocumentIndex()
        directory = cached.get("directory", "")
        file_hashes = cached.get("file_hashes", {})
        if not directory or not file_hashes:
            return DocumentIndex()
        # Restore tracked directories
        self._indexed_dirs = cached.get("indexed_dirs", {})
        if directory and not self._indexed_dirs:
            # Migrate: old format had single directory
            self._indexed_dirs[directory] = cached.get("extensions", [".py", ".pltg", ".md", ".txt"])
        # Restore stat caches
        self._file_stats = {k: tuple(v) for k, v in cached.get("file_stats", {}).items()}
        self._dir_mtimes = cached.get("dir_mtimes", {})
        self._dir_hashes[self._path] = file_hashes
        idx_data = cached.get("index", {})
        # Use cached file texts — zero disk reads on warm load
        file_texts = cached.get("file_texts", {})
        if file_texts:
            original_texts = {rel: file_texts.get(rel, "") for rel in idx_data.get("documents", {})}
            return DocumentIndex.from_dict(idx_data, original_texts)
        # Fallback: old cache format without file_texts — re-read from disk
        base = Path(directory)
        paths = [(base / rel, rel) for rel in file_hashes]
        disk_texts, _ = self._read_and_hash(paths)
        original_texts = {rel: disk_texts.get(rel, "") for rel in idx_data.get("documents", {})}
        return DocumentIndex.from_dict(idx_data, original_texts)

    def load_search_index(self, doc_index: DocumentIndex) -> "DocumentSearchIndex | None":
        """Load cached DocumentSearchIndex if available.

        Requires the already-loaded DocumentIndex (from load_index) for
        enrichment — avoids re-reading the cache file.
        """
        from .search_s.serialization import deserialize_search_index

        if not self._store:
            return None
        cached = self._store.load_index(self._path)
        if not cached or "search_index" not in cached:
            return None
        try:
            return deserialize_search_index(cached["search_index"], doc_index)
        except Exception as e:
            log.warning("Failed to restore search index: %s", e)
            return None

    def _read_and_hash(
        self,
        paths: list[tuple[Path, str]],
        old_hashes: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Read files and compute hashes. Returns (file_texts, new_hashes).

        Each entry is (absolute_path, key) where key is used in the index and cache.

        Uses git-style stat fingerprinting: files whose (ctime_ns, mtime_ns,
        dev, ino, mode, size) haven't changed reuse their cached hash without
        reading the file content. Only new or stat-changed files are read.
        """
        from parseltongue.core.integrity.merkle import _sha256

        new_hashes: dict[str, str] = {}
        file_texts: dict[str, str] = {}

        for fpath, key in paths:
            try:
                st = fpath.stat()
            except OSError:
                continue

            fp = _stat_fingerprint(st)

            # Fast path: stat unchanged AND hash known → skip read
            if old_hashes and key in old_hashes and self._file_stats.get(key) == fp:
                new_hashes[key] = old_hashes[key]
                continue

            # Slow path: read + hash
            try:
                text = fpath.read_text(errors="replace")
            except Exception:
                continue
            new_hashes[key] = _sha256(text)
            file_texts[key] = text
            self._file_stats[key] = fp

        return file_texts, new_hashes

    def _update_index(
        self,
        _index: DocumentIndex,
        file_texts: dict[str, str],
        new_hashes: dict[str, str],
        old_hashes: dict[str, str],
        directory: str = "",
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[DocumentIndex, int]:
        """Diff hashes, update index for changed files, remove deleted. Save cache.

        file_texts only contains files that were actually read (stat-changed or new).
        Unchanged files' texts are pulled from the cache.
        """
        changed = {f for f in set(old_hashes) | set(new_hashes) if old_hashes.get(f) != new_hashes.get(f)}
        deleted = set(old_hashes) - set(new_hashes)
        log.debug(
            "search _update_index: %d total, %d changed, %d deleted",
            len(new_hashes),
            len(changed),
            len(deleted),
        )

        # Load cached texts for unchanged files
        cached_texts: dict[str, str] = {}
        cached = self._store.load_index(self._path) if self._store else None
        if cached:
            cached_texts = cached.get("file_texts", {})

        # Merge: cached texts for unchanged, fresh texts for changed/new
        all_texts = dict(cached_texts)
        all_texts.update(file_texts)

        if not changed and old_hashes:
            # Nothing changed — restore from cache
            if cached:
                idx_data = cached.get("index", {})
                original_texts = {k: all_texts.get(k, "") for k in idx_data.get("documents", {})}
                _index = DocumentIndex.from_dict(idx_data, original_texts)
            self._dir_hashes[self._path] = new_hashes
            return _index, 0

        if old_hashes and cached:
            # Partial reindex: restore unchanged from cache, reindex changed
            idx_data = cached.get("index", {})
            unchanged_texts = {k: all_texts[k] for k in all_texts if k not in changed and k in idx_data.get("documents", {})}
            if unchanged_texts and idx_data:
                _index = DocumentIndex.from_dict(idx_data, unchanged_texts)

        # Index changed (or all if no cache)
        to_index = sorted(changed) if changed else sorted(file_texts.keys())
        total_changed = len(to_index)
        count = 0
        for key in to_index:
            if key in file_texts:
                _index.add(key, file_texts[key])
            count += 1
            if on_progress:
                on_progress(count, total_changed, key)

        # Remove deleted files
        for key in deleted:
            if key in _index.documents:
                del _index.documents[key]
            all_texts.pop(key, None)

        # Only keep texts for files still in the index
        save_texts = {k: v for k, v in all_texts.items() if k in new_hashes}

        # Save — includes file texts, tracked dirs, stat caches
        self._save_cache(directory, new_hashes, _index, file_texts=save_texts)
        self._dir_hashes[self._path] = new_hashes
        return _index, total_changed

    def _save_cache(
        self, directory: str, file_hashes: dict[str, str], doc_index: DocumentIndex,
        file_texts: dict[str, str] | None = None,
    ):
        """Save DocumentIndex + file texts + tracked dirs + stat caches to disk."""
        if not self._store:
            return
        self._store.save_index(
            self._path, directory, file_hashes, doc_index.to_dict(),
            indexed_dirs=self._indexed_dirs,
            file_stats={k: list(v) for k, v in self._file_stats.items()},
            dir_mtimes=self._dir_mtimes,
            file_texts=file_texts,
        )

    def save_search_index(self, search_index: "object"):
        """Persist DocumentSearchIndex data alongside the existing cache."""
        if not self._store:
            return
        cached = self._store.load_index(self._path)
        if not cached:
            return
        from .search_s.serialization import serialize_search_index
        cached["search_index"] = serialize_search_index(search_index)
        # Re-save the full cache
        try:
            payload = json.dumps(cached, separators=(",", ":")).encode()
            _pgz_write(self._store._index_cache_path(self._path), payload)
        except Exception as e:
            log.warning("Failed to save search index: %s", e)

    def _walk_directory(
        self,
        directory: str,
        extensions: list[str],
        exclude: list[str] | None = None,
        old_hashes: dict[str, str] | None = None,
    ) -> list[tuple[Path, str]]:
        """Walk a directory collecting files as (absolute_path, relative_key).

        Uses directory mtime pruning: if a directory's mtime_ns hasn't changed
        since last index, its entire subtree is skipped — the old file list is
        reused from old_hashes. Only directories with newer mtime are descended.
        """
        ext_set = set(extensions)
        ignore_patterns = _load_pgignore(directory)
        if exclude:
            ignore_patterns.extend(exclude)

        paths: list[tuple[Path, str]] = []
        for root, dirs, fnames in os.walk(directory):
            # Prune ignored directories
            if ignore_patterns:
                rel_root = str(Path(root).relative_to(directory))
                kept = []
                for d in dirs:
                    rel_dir = str(Path(rel_root) / d) if rel_root != "." else d
                    if not _is_ignored(rel_dir + "/placeholder", ignore_patterns):
                        kept.append(d)
                dirs[:] = kept

            # Directory mtime pruning: if dir mtime unchanged, skip file listing
            # and reuse known files from old_hashes. Each subdir still gets
            # its own turn in os.walk for its own mtime check.
            if old_hashes and self._dir_mtimes:
                try:
                    dir_mtime = os.stat(root).st_mtime_ns
                except OSError:
                    dir_mtime = 0
                cached_mtime = self._dir_mtimes.get(root)
                if cached_mtime is not None and dir_mtime == cached_mtime:
                    # Reuse old file entries for this directory level only
                    rel_root_str = str(Path(root).relative_to(directory))
                    for key in old_hashes:
                        key_dir = str(Path(key).parent)
                        if key_dir == rel_root_str or (rel_root_str == "." and "/" not in key and "\\" not in key):
                            fpath = Path(directory) / key
                            if fpath.suffix in ext_set:
                                paths.append((fpath, key))
                    continue

            # Record this directory's mtime
            try:
                self._dir_mtimes[root] = os.stat(root).st_mtime_ns
            except OSError:
                pass

            for fname in fnames:
                if any(fname.endswith(e) for e in ext_set):
                    fpath = Path(root) / fname
                    rel = str(fpath.relative_to(directory))
                    if ignore_patterns and _is_ignored(rel, ignore_patterns):
                        continue
                    paths.append((fpath, rel))
        return paths

    def index_incremental(
        self,
        _index: DocumentIndex,
        directory: str,
        extensions: list[str] | None = None,
        exclude: list[str] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        force: bool = False,
    ) -> tuple[DocumentIndex, int]:
        """Walk *directory*, index every file matching *extensions*.

        Uses stat fingerprinting + Merkle hashing: unchanged files are skipped.
        Deleted files are removed from the index.
        Reads .pgignore from directory root (gitignore-style patterns).

        force=True ignores all stat/hash caches and re-reads every file.
        """
        extensions = extensions or [".py", ".pltg", ".md", ".txt"]
        directory = str(Path(directory).resolve())

        # Track this directory for reindex
        self._indexed_dirs[directory] = extensions

        # Old hashes from cache
        old_hashes: dict[str, str] = {}
        if not force and self._store:
            cached = self._store.load_index(self._path)
            if cached:
                old_hashes = cached.get("file_hashes", {})

        if force:
            self._file_stats.clear()
            self._dir_mtimes.clear()

        paths = self._walk_directory(
            directory, extensions, exclude,
            old_hashes=None if force else old_hashes,
        )
        file_texts, new_hashes = self._read_and_hash(
            paths, old_hashes=None if force else old_hashes,
        )

        return self._update_index(_index, file_texts, new_hashes, old_hashes, directory, on_progress)

    def reindex(
        self,
        _index: DocumentIndex,
        on_progress: Callable[[int, int, str], None] | None = None,
        force: bool = False,
    ) -> tuple[DocumentIndex, int]:
        """Re-walk all tracked directories, picking up new/changed/deleted files.

        force=True ignores stat/hash caches and re-reads every file.
        """
        if not self._store:
            return _index, 0

        cached = self._store.load_index(self._path)
        if not cached:
            return _index, 0

        old_hashes: dict[str, str] = {} if force else cached.get("file_hashes", {})
        directory = cached.get("directory", "")

        # Restore tracked dirs from cache if not already loaded
        if not self._indexed_dirs:
            self._indexed_dirs = cached.get("indexed_dirs", {})
            if directory and not self._indexed_dirs:
                self._indexed_dirs[directory] = cached.get("extensions", [".py", ".pltg", ".md", ".txt"])

        if not self._indexed_dirs:
            return _index, 0

        if force:
            self._file_stats.clear()
            self._dir_mtimes.clear()

        # Walk ALL tracked directories — picks up new files
        all_paths: list[tuple[Path, str]] = []
        primary_dir = directory
        for dir_path, exts in self._indexed_dirs.items():
            all_paths.extend(self._walk_directory(
                dir_path, exts,
                old_hashes=None if force else old_hashes,
            ))
            if not primary_dir:
                primary_dir = dir_path

        file_texts, new_hashes = self._read_and_hash(
            all_paths, old_hashes=None if force else old_hashes,
        )

        return self._update_index(_index, file_texts, new_hashes, old_hashes, primary_dir, on_progress)
