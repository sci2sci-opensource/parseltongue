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
from .diagnosis import Diagnosis
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


class Store:
    """Disk cache for bench state.

    Handles:
    - File hashing and Merkle tree construction
    - Reading/writing cached data to .pgz files
    - Deserializing cached data back into structures + loaders
    - Diagnosis cache (separate .dx.pgz files)
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

    # ── Diagnosis cache ──

    def save_diagnosis(self, path: str, merkle_root: str, dx: Diagnosis):
        """Save diagnosis to disk as .pgz."""
        self._ensure_dir()
        data = {"merkle_root": merkle_root, "diagnosis": dx.to_dict()}
        try:
            payload = json.dumps(data, separators=(",", ":")).encode()
            _pgz_write(self._diagnosis_cache_path(path), payload)
            self._legacy_diagnosis_cache_path(path).unlink(missing_ok=True)
        except Exception as e:
            log.warning("Failed to save diagnosis for %s: %s", path, e)

    def load_diagnosis(self, path: str, expected_merkle_root: str) -> Diagnosis | None:
        """Load diagnosis from disk if Merkle root matches."""
        data = self._read_diagnosis_raw(path)
        if data is None:
            return None
        if data.get("merkle_root") != expected_merkle_root:
            return None
        try:
            return Diagnosis.from_dict(data["diagnosis"])
        except Exception:
            self._diagnosis_cache_path(path).unlink(missing_ok=True)
            return None

    def load_stale_diagnosis(self, path: str) -> Diagnosis | None:
        """Load diagnosis from disk regardless of Merkle root match."""
        data = self._read_diagnosis_raw(path)
        if data is None:
            return None
        try:
            return Diagnosis.from_dict(data["diagnosis"])
        except Exception:
            self._diagnosis_cache_path(path).unlink(missing_ok=True)
            return None

    # ── Index cache ──

    def _index_cache_path(self, directory: str) -> Path:
        return self._dir / f"{self._cache_key(directory)}.idx.pgz"

    def save_index(self, key: str, directory: str, file_hashes: dict[str, str], index_data: dict):
        """Save search index to disk as .idx.pgz. Key is the cache lookup key, directory is stored inside."""
        self._ensure_dir()
        data = {"directory": directory, "file_hashes": file_hashes, "index": index_data}
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
        """Remove cache files for a specific path."""
        self._cache_path(path).unlink(missing_ok=True)
        self._diagnosis_cache_path(path).unlink(missing_ok=True)
        self._index_cache_path(path).unlink(missing_ok=True)
        # Clean up legacy too
        self._legacy_cache_path(path).unlink(missing_ok=True)
        self._legacy_diagnosis_cache_path(path).unlink(missing_ok=True)

    def remove_all(self):
        """Remove all cache files."""
        if self._dir.exists():
            for f in self._dir.glob("*.pgz"):
                f.unlink()
            for f in self._dir.glob("*.json"):
                f.unlink()

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


class SearchStore:

    def __init__(self, store: Store | None = None, path: str = "", index: DocumentIndex | None = None):
        self._store = store
        self._path = path
        self._dir_hashes: dict[str, dict[str, str]] = {}
        self._preloaded = index

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
        # Re-read files from disk to restore full text
        base = Path(directory)
        paths = [(base / rel, rel) for rel in file_hashes]
        file_texts, _ = self._read_and_hash(paths)
        self._dir_hashes[self._path] = file_hashes
        idx_data = cached.get("index", {})
        original_texts = {rel: file_texts.get(rel, "") for rel in idx_data.get("documents", {})}
        return DocumentIndex.from_dict(idx_data, original_texts)

    def _read_and_hash(self, paths: list[tuple[Path, str]]) -> tuple[dict[str, str], dict[str, str]]:
        """Read files and compute hashes. Returns (file_texts, new_hashes).

        Each entry is (absolute_path, key) where key is used in the index and cache.
        """
        from parseltongue.core.integrity.merkle import _sha256

        new_hashes: dict[str, str] = {}
        file_texts: dict[str, str] = {}
        for fpath, key in paths:
            try:
                text = fpath.read_text(errors="replace")
            except Exception:
                continue
            new_hashes[key] = _sha256(text)
            file_texts[key] = text
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
        """Diff hashes, update index for changed files, remove deleted. Save cache."""
        changed = {f for f in set(old_hashes) | set(new_hashes) if old_hashes.get(f) != new_hashes.get(f)}

        if not changed and old_hashes:
            # Nothing changed — restore from cache
            if self._store:
                cached = self._store.load_index(self._path)
                if cached:
                    idx_data = cached.get("index", {})
                    original_texts = {k: file_texts.get(k, "") for k in idx_data.get("documents", {})}
                    _index = DocumentIndex.from_dict(idx_data, original_texts)
            self._dir_hashes[self._path] = new_hashes
            return _index, 0

        if old_hashes and self._store:
            # Partial reindex: restore unchanged from cache, reindex changed
            cached = self._store.load_index(self._path)
            if cached:
                idx_data = cached.get("index", {})
                unchanged_texts = {k: file_texts[k] for k in file_texts if k not in changed}
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
        for key in old_hashes:
            if key not in new_hashes and key in _index.documents:
                del _index.documents[key]

        # Save
        if self._store:
            self._store.save_index(self._path, directory, new_hashes, _index.to_dict())
        self._dir_hashes[self._path] = new_hashes
        return _index, total_changed

    def index_incremental(
        self,
        _index: DocumentIndex,
        directory: str,
        extensions: list[str] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[DocumentIndex, int]:
        """Walk *directory*, index every file matching *extensions*.

        Uses Merkle-based caching: only changed files are re-indexed.
        Deleted files are removed from the index.
        """
        extensions = extensions or [".py", ".pltg", ".md", ".txt"]
        ext_set = set(extensions)
        directory = str(Path(directory).resolve())

        # Collect files as (absolute, relative_key)
        paths: list[tuple[Path, str]] = []
        for root, _, fnames in os.walk(directory):
            for fname in fnames:
                if any(fname.endswith(e) for e in ext_set):
                    fpath = Path(root) / fname
                    rel = str(fpath.relative_to(directory))
                    paths.append((fpath, rel))

        file_texts, new_hashes = self._read_and_hash(paths)

        # Old hashes from cache
        old_hashes: dict[str, str] = {}
        if self._store:
            cached = self._store.load_index(self._path)
            if cached:
                old_hashes = cached.get("file_hashes", {})

        return self._update_index(_index, file_texts, new_hashes, old_hashes, directory, on_progress)

    def reindex(
        self,
        _index: DocumentIndex,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[DocumentIndex, int]:
        """Re-read and re-hash all previously indexed files. Update stale entries."""
        if not self._store:
            return _index, 0

        cached = self._store.load_index(self._path)
        if not cached:
            return _index, 0

        old_hashes: dict[str, str] = cached.get("file_hashes", {})
        directory = cached.get("directory", "")
        if not old_hashes or not directory:
            return _index, 0

        # Reconstruct (absolute_path, relative_key) from cached keys
        base = Path(directory)
        paths = [(base / rel, rel) for rel in old_hashes]
        file_texts, new_hashes = self._read_and_hash(paths)

        return self._update_index(_index, file_texts, new_hashes, old_hashes, directory, on_progress)
