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
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..search_engine.index import DocumentSearchIndex

from ..ast import DirectiveNode
from ..integrity.merkle import MerkleNode, _sha256, _sha256_bytes, merkle_combine
from ..loader.lazy_loader import LazyLoader, LazyLoadResult
from ..quote_verifier import DocumentIndex
from ..system import System
from .config import load_allow_large_globs as _load_allow_large_globs
from .config import load_extensions as _load_extensions
from .config import load_ignore_patterns as _load_pgignore
from .config import load_max_file_size_bytes as _load_max_file_size_bytes
from .history import History
from .pgz import json_pgz_read, json_pgz_write, pgz_read, pgz_write
from .probe_core_to_consequence import CoreToConsequenceStructure
from .screen import Screen
from .serialization import deserialize_structure, serialize_structure

log = logging.getLogger("parseltongue.store")

BENCH_DIR = ".parseltongue-bench"
_HOME_BENCH_DIR = Path.home() / ".parseltongue" / "pg-bench"

# Back-compat aliases for any external callers
_pgz_write = pgz_write
_pgz_read = pgz_read

_EMPTY_SHA256 = _sha256_bytes(b"")


def _hash_file(path: str) -> str:
    """Hash a file's bytes with SHA-256.

    Returns hex digest, or "" on OSError. Empty files short-circuit
    to the well-known empty digest without opening the file. Larger
    files stream via ``hashlib.file_digest`` to bound peak memory.
    """
    try:
        if os.stat(path).st_size == 0:
            return _EMPTY_SHA256
        with open(path, "rb") as fp:
            return hashlib.file_digest(fp, "sha256").hexdigest()
    except OSError:
        return ""


def _collect_tree_leaves(node: MerkleNode) -> dict[str, str]:
    """Collect {content: hash} for all leaves in a Merkle tree."""
    if node.is_leaf:
        return {node.content: node.hash} if node.content else {}
    result = {}
    for child in node.children or []:
        result.update(_collect_tree_leaves(child))
    return result


# Selection is core machinery (one classification for indexing,
# load-documents, and corpus evidence); the alias keeps existing callers.
from ..search_engine.select import classify_file  # noqa: E402
from ..search_engine.select import is_ignored as _is_ignored  # noqa: E402


class Store:
    """Disk cache for bench state.

    Handles:
    - File hashing and Merkle tree construction
    - Reading/writing cached data to .pgz files
    - Deserializing cached data back into structures + loaders
    - Screen cache (separate .dx.pgz files)
    """

    def __init__(self, bench_dir: str | Path | None = None):
        self._dir = Path(bench_dir or BENCH_DIR)

    @property
    def project_root(self) -> Path:
        """The directory the bench serves — parent of the bench dir.

        File-index paths (and .pgignore / pg.toml) are relative to it.
        """
        return self._dir.resolve().parent

    # ── Logbook ──

    def log_session(self, entry: dict):
        """Append a session entry to the logbook (JSONL).

        Dual-write: project-local logbook + home-directory backup.
        The home copy includes `project` (cwd) so it doubles as a
        machine-level log across all projects.  Home write failures
        are logged but never propagated — local is authoritative.
        """
        line = json.dumps(entry) + "\n"

        # Local (authoritative)
        self._dir.mkdir(parents=True, exist_ok=True)
        logbook = self._dir / "logbook.jsonl"
        with open(logbook, "a") as f:
            f.write(line)
        log.info("Logbook entry written to %s", logbook)

        # Home backup (machine-level, survives project cache wipes)
        try:
            home_entry = {**entry, "project": str(Path.cwd())}
            _HOME_BENCH_DIR.mkdir(parents=True, exist_ok=True)
            home_logbook = _HOME_BENCH_DIR / "logbook.jsonl"
            with open(home_logbook, "a") as f:
                f.write(json.dumps(home_entry) + "\n")
        except OSError as exc:
            log.warning("Home logbook write failed: %s", exc)

    def read_logbook(self) -> list[dict]:
        """Read all session entries from the logbook.

        Reads local first.  If local is missing (e.g. after cache wipe),
        falls back to home backup filtered by current project.
        """
        logbook = self._dir / "logbook.jsonl"
        if logbook.exists():
            return self._parse_logbook(logbook)
        # Fallback: home backup, filtered to this project
        home_logbook = _HOME_BENCH_DIR / "logbook.jsonl"
        if home_logbook.exists():
            cwd = str(Path.cwd())
            entries = self._parse_logbook(home_logbook)
            recovered = [e for e in entries if e.get("project", "") == cwd]
            if recovered:
                log.info("Local logbook missing — recovered %d entries from home backup", len(recovered))
            return recovered
        return []

    @staticmethod
    def _parse_logbook(path: Path) -> list[dict]:
        """Parse a JSONL logbook file."""
        entries = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    # ── File hashing ──

    def hash_files(self, files: list[str]) -> dict[str, str]:
        """Hash each file's bytes. Returns {path: sha256}.

        Uses streaming via :func:`_hash_file` so peak memory stays
        bounded regardless of file size, and empty files short-circuit
        without I/O.
        """
        return {f: _hash_file(f) for f in files}

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
            json_pgz_write(self._cache_path(path), data)
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
        dir_nodes: list[DirectiveNode] = []
        for name, info in data.get("node_index", {}).items():
            dn = DirectiveNode(
                name=name,
                expr=[],
                dep_names=set(),
                kind=info.get("kind", ""),
                source_file=info.get("source_file"),
                source_order=0,
                source_line=info.get("source_line", 0),
            )
            dir_nodes.append(dn)
        loader._all_nodes = dir_nodes
        loader._result._all_nodes = dir_nodes
        loader._result.loaded = set(dir_nodes)
        return structure, loader

    # ── Screen cache ──

    def save_diagnosis(self, path: str, merkle_root: str, dx: Screen):
        """Save evaluation to disk as .pgz."""
        self._ensure_dir()
        data = {"merkle_root": merkle_root, "diagnosis": dx.to_dict()}
        try:
            json_pgz_write(self._diagnosis_cache_path(path), data)
            self._legacy_diagnosis_cache_path(path).unlink(missing_ok=True)
        except Exception as e:
            log.warning("Failed to save evaluation for %s: %s", path, e)

    def load_diagnosis(self, path: str, expected_merkle_root: str) -> Screen | None:
        """Load evaluation from disk if Merkle root matches."""
        data = self._read_diagnosis_raw(path)
        if data is None:
            return None
        if data.get("merkle_root") != expected_merkle_root:
            return None
        try:
            return Screen.from_dict(data["diagnosis"])
        except Exception:
            self._diagnosis_cache_path(path).unlink(missing_ok=True)
            return None

    def load_stale_diagnosis(self, path: str) -> Screen | None:
        """Load evaluation from disk regardless of Merkle root match."""
        data = self._read_diagnosis_raw(path)
        if data is None:
            return None
        try:
            return Screen.from_dict(data["diagnosis"])
        except Exception:
            self._diagnosis_cache_path(path).unlink(missing_ok=True)
            return None

    # ── Index cache ──

    def _index_cache_path(self, directory: str) -> Path:
        return self._dir / f"{self._cache_key(directory)}.idx.pgz"

    def _search_index_cache_path(self, directory: str) -> Path:
        return self._dir / f"{self._cache_key(directory)}.six.pgz"

    def save_search_index_data(self, key: str, data: dict):
        """Save serialized DocumentSearchIndex to its own .six.pgz.

        Kept out of the main .idx.pgz so persisting it never requires
        parsing and rewriting the (much larger) index cache."""
        self._ensure_dir()
        try:
            json_pgz_write(self._search_index_cache_path(key), data)
        except Exception as e:
            log.warning("Failed to save search index for %s: %s", key, e)

    def load_search_index_data(self, key: str) -> dict | None:
        """Load serialized DocumentSearchIndex from .six.pgz, or None."""
        cache_file = self._search_index_cache_path(key)
        if not cache_file.exists():
            return None
        try:
            return json_pgz_read(cache_file)
        except Exception as e:
            log.warning("Failed to read search index cache for %s: %s", key, e)
            cache_file.unlink(missing_ok=True)
            return None

    def history(self, key: str, max_layers: int = 42) -> History:
        """Get a History instance for a given cache key.

        History provides append-only layered text storage with time
        travel, diffing, and restore — both whole-state and per-file.
        """
        self._ensure_dir()
        prefix = self._cache_key(key)
        return History(self._dir, prefix, max_layers=max_layers)

    def save_texts(self, key: str, file_texts: dict[str, str]):
        """Save file texts as a base layer in History."""
        h = self.history(key)
        if h.layer_count() == 0:
            h.commit_base(file_texts)
        else:
            # Diff against current to write a delta
            current = h.current()
            changed: dict[str, str] = {}
            deleted: set[str] = set()
            for name, text in file_texts.items():
                if name not in current or current[name] != text:
                    changed[name] = text
            for name in current:
                if name not in file_texts:
                    deleted.add(name)
            if changed or deleted:
                h.commit(changed, deleted)

    def load_texts(self, key: str) -> dict[str, str] | None:
        """Load current file texts from History."""
        h = self.history(key)
        if h.layer_count() == 0:
            return None
        return h.current()

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
        """Save search index to disk as .idx.pgz + texts as .texts.pgz.

        file_texts are stored separately in OrdinalPGZ format — not in the
        main index cache. This keeps the index small and fast to read.
        """
        self._ensure_dir()
        data: dict = {"directory": directory, "file_hashes": file_hashes, "index": index_data}
        if indexed_dirs:
            data["indexed_dirs"] = indexed_dirs
        if file_stats:
            data["file_stats"] = file_stats
        if dir_mtimes:
            data["dir_mtimes"] = dir_mtimes
        # file_texts go to separate .texts.pgz — NOT in main index
        try:
            json_pgz_write(self._index_cache_path(key), data)
        except Exception as e:
            log.warning("Failed to save index for %s: %s", key, e)
        if file_texts:
            self.save_texts(key, file_texts)

    def load_index(self, key: str) -> dict | None:
        """Load cached index data (without file texts), or None if not cached.

        File texts live in a separate .texts.pgz — use load_texts() for those.
        """
        cache_file = self._index_cache_path(key)
        if not cache_file.exists():
            return None
        try:
            return json_pgz_read(cache_file)
        except Exception as e:
            log.warning("Failed to read index cache for %s: %s", key, e)
            cache_file.unlink(missing_ok=True)
            return None

    # ── Invalidation ──

    # Corpus caches — the indexed files, not derived analysis. A reload
    # re-observes the .pltg; the corpus survives it (claims re-ground
    # against the existing index). Only a purge wipes these.
    _CORPUS_SUFFIXES = (".idx.pgz", ".six.pgz", ".meta.pgz")

    @classmethod
    def _is_corpus_cache(cls, f: Path) -> bool:
        return f.name.endswith(cls._CORPUS_SUFFIXES) or ".texts." in f.name

    def remove(self, path: str, preserve_corpus: bool = False):
        """Remove cache files for a specific path — includes viz, history, texts."""
        self._cache_path(path).unlink(missing_ok=True)
        self._diagnosis_cache_path(path).unlink(missing_ok=True)
        if not preserve_corpus:
            self._index_cache_path(path).unlink(missing_ok=True)
            self._search_index_cache_path(path).unlink(missing_ok=True)
        # History layers + metadata
        self.history(path).remove_all()
        # Clean up legacy too
        self._legacy_cache_path(path).unlink(missing_ok=True)
        self._legacy_diagnosis_cache_path(path).unlink(missing_ok=True)
        # Viz cache depends on all other caches — clear on any invalidation
        if self._dir.exists():
            for f in self._dir.glob("*.viz.pgz"):
                f.unlink(missing_ok=True)

    def remove_all(self, preserve_corpus: bool = False):
        """Remove all cache files (optionally keeping the indexed corpus)."""
        if self._dir.exists():
            for f in self._dir.glob("*.pgz"):
                if preserve_corpus and self._is_corpus_cache(f):
                    continue
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
        self._pending_save: dict | None = None
        self._preloaded = index
        # Tracked directories: directory → extensions list
        self._indexed_dirs: dict[str, list[str]] = {}
        # Git-style stat cache: file_key → (ctime_ns, mtime_ns, dev, ino, mode, size)
        self._file_stats: dict[str, tuple] = {}
        # Directory mtime cache: abs_dir_path → mtime_ns
        self._dir_mtimes: dict[str, int] = {}
        # Size-guardrail skips: rel_path → size_bytes. Populated by
        # _walk_directory when a file exceeds max_file_size_bytes and is not
        # matched by [index].allow_large. Surfaced via log.error.
        self._skipped_large: dict[str, int] = {}

    def _history(self) -> History | None:
        """Get the History instance for this search store."""
        if not self._store:
            return None
        return self._store.history(self._path)

    def load_index(self) -> DocumentIndex:
        import time

        if self._preloaded is not None:
            return self._preloaded
        if not self._store:
            return DocumentIndex()
        log.info("SearchStore.load_index: start path=%s", self._path)
        t0 = time.perf_counter()
        cached = self._store.load_index(self._path)
        t_read = time.perf_counter() - t0
        log.info("SearchStore.load_index: cache read %.2fs (size=%s)", t_read, "hit" if cached else "miss")
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
            self._indexed_dirs[directory] = cached.get("extensions", _load_extensions())
        # Restore stat caches
        self._file_stats = {k: tuple(v) for k, v in cached.get("file_stats", {}).items()}
        self._dir_mtimes = cached.get("dir_mtimes", {})
        self._dir_hashes[self._path] = file_hashes
        idx_data = cached.get("index", {})
        n_docs = len(idx_data.get("documents", {}))
        # Load texts from History (separate layered OrdinalPGZ files)
        log.info(
            "SearchStore.load_index: load_texts start (docs=%d, hashes=%d)",
            n_docs,
            len(file_hashes),
        )
        t0 = time.perf_counter()
        file_texts = self._store.load_texts(self._path)
        t_texts = time.perf_counter() - t0
        log.info(
            "SearchStore.load_index: load_texts done in %.2fs (got %d texts)",
            t_texts,
            len(file_texts) if file_texts else 0,
        )
        # Migration: old format stored file_texts inside the main index
        if not file_texts:
            file_texts = cached.get("file_texts", {})
        if file_texts and len(file_texts) >= len(file_hashes):
            original_texts = {rel: file_texts.get(rel, "") for rel in idx_data.get("documents", {})}
            log.info("SearchStore.load_index: DocumentIndex.from_dict start (docs=%d)", n_docs)
            t0 = time.perf_counter()
            idx = DocumentIndex.from_dict(idx_data, original_texts)
            t_build = time.perf_counter() - t0
            log.info(
                "SearchStore.load_index: done docs=%d hashes=%d cache_read=%.2fs texts_load=%.2fs index_build=%.2fs",
                n_docs,
                len(file_hashes),
                t_read,
                t_texts,
                t_build,
            )
            return idx
        # Fallback: some texts are missing in History (e.g. tombstoned files still
        # listed in file_hashes). Only fetch the missing ones from disk and merge
        # with what we already have — no point re-reading thousands of files we
        # just decompressed. Pass old_hashes so the stat-fingerprint fast-path
        # skips I/O for anything that slipped through without changing on disk.
        missing = set(file_hashes) - set(file_texts)
        base = Path(directory)
        paths = [(base / rel, rel) for rel in missing]
        log.info(
            "SearchStore.load_index: fallback — %d texts missing from %d hashes, fetching from disk",
            len(missing),
            len(file_hashes),
        )
        t0 = time.perf_counter()
        disk_texts, _ = self._read_and_hash(paths, old_hashes=file_hashes)
        t_rehash = time.perf_counter() - t0
        merged_texts = dict(file_texts)
        merged_texts.update(disk_texts)
        original_texts = {rel: merged_texts.get(rel, "") for rel in idx_data.get("documents", {})}
        if disk_texts:
            # Backfill History so next load has complete texts and skips the fallback.
            self._store.save_texts(self._path, merged_texts)
        log.info("SearchStore.load_index: DocumentIndex.from_dict start (docs=%d)", n_docs)
        t0 = time.perf_counter()
        idx = DocumentIndex.from_dict(idx_data, original_texts)
        t_build = time.perf_counter() - t0
        log.info(
            "SearchStore.load_index [fallback]: docs=%d hashes=%d missing=%d "
            "cache_read=%.2fs texts_load=%.2fs rehash=%.2fs index_build=%.2fs",
            n_docs,
            len(file_hashes),
            len(missing),
            t_read,
            t_texts,
            t_rehash,
            t_build,
        )
        return idx

    def load_search_index(self, doc_index: DocumentIndex) -> "DocumentSearchIndex | None":
        """Load cached DocumentSearchIndex if available.

        Requires the already-loaded DocumentIndex (from load_index) for
        enrichment — avoids re-reading the cache file.
        """
        import time

        from ..search_engine.serialization import deserialize_search_index

        if not self._store:
            return None
        log.info("SearchStore.load_search_index: start path=%s", self._path)
        t0 = time.perf_counter()
        sidx = self._store.load_search_index_data(self._path)
        if sidx is None:
            # Legacy layout: search_index stored inline in the main .idx.pgz.
            # One expensive parse on the first boot after upgrade; the next
            # save writes the dedicated .six.pgz and this path goes away.
            cached = self._store.load_index(self._path)
            if not cached or "search_index" not in cached:
                return None
            sidx = cached["search_index"]
        t_read = time.perf_counter() - t0
        log.info("SearchStore.load_search_index: cache read %.2fs", t_read)
        sidx_keys = list(sidx.keys()) if isinstance(sidx, dict) else []
        log.info("SearchStore.load_search_index: deserialize start sections=%s", sidx_keys)
        try:
            t0 = time.perf_counter()
            result = deserialize_search_index(sidx, doc_index)
            t_build = time.perf_counter() - t0
            log.info(
                "SearchStore.load_search_index: done cache_read=%.2fs deserialize=%.2fs sections=%s",
                t_read,
                t_build,
                sidx_keys,
            )
            return result
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
    ) -> tuple[DocumentIndex, int, set[str]]:
        """Diff hashes, update index for changed files, remove deleted. Save cache.

        file_texts only contains files that were actually read (stat-changed or new).
        Unchanged files' texts are pulled from History.
        Returns (updated_index, change_count, deleted_keys).
        """
        changed = {f for f in set(old_hashes) | set(new_hashes) if old_hashes.get(f) != new_hashes.get(f)}
        deleted = set(old_hashes) - set(new_hashes)
        log.debug(
            "search _update_index: %d total, %d changed, %d deleted",
            len(new_hashes),
            len(changed),
            len(deleted),
        )

        if not changed and old_hashes:
            # Nothing changed — the live index is already current. Return it
            # untouched: rebuilding it from the disk cache here cost two full
            # cache parses + a DocumentIndex reconstruction per background
            # tick, and dropped any verifier docs merged in via refresh().
            self._dir_hashes[self._path] = new_hashes
            return _index, 0, set()

        # Mutate the live index in place: add() re-indexes changed docs
        # (COW-swapped, hash-guarded) and the deleted block below drops
        # removed ones. Rebuilding _index from the disk cache here — the
        # historical behavior — cost a full cache parse plus a LayeredTexts
        # merge per pass, and the live index is already authoritative.
        to_index = sorted(changed) if changed else sorted(file_texts.keys())
        total_changed = len(to_index)
        count = 0
        for key in to_index:
            if key in file_texts:
                _index.add(key, file_texts[key])
            count += 1
            if on_progress:
                on_progress(count, total_changed, key)

        # Remove deleted files — COW: build new dict to avoid mutating during iteration
        if deleted:
            new_docs = {k: v for k, v in _index.documents.items() if k not in deleted}
            _index.documents = new_docs

        # Defer the disk save: the full-index write takes minutes on large
        # corpora, and running it here would delay the caller's _sync — the
        # step that makes the changes searchable. The caller flushes after
        # syncing (flush_pending_save), so search freshness never waits on
        # cache durability. Pending payloads accumulate across passes so a
        # caller may also batch several passes into one flush (the
        # background loop flushes on the first quiet pass).
        prev = self._pending_save
        merged_texts = dict(prev["changed_texts"]) if prev else {}
        merged_texts.update(file_texts)
        merged_deleted = ((prev["deleted_keys"] if prev else set()) | deleted) - set(new_hashes)
        for key in merged_deleted:
            merged_texts.pop(key, None)
        self._pending_save = {
            "directory": directory,
            "file_hashes": new_hashes,
            "index": _index,
            "changed_texts": merged_texts,
            "deleted_keys": merged_deleted,
        }
        self._dir_hashes[self._path] = new_hashes
        return _index, total_changed, deleted

    def flush_pending_save(self):
        """Write the cache update queued by the last index/reindex pass."""
        info = self._pending_save
        self._pending_save = None
        if not info:
            return
        self._save_cache(
            info["directory"],
            info["file_hashes"],
            info["index"],
            changed_texts=info["changed_texts"],
            deleted_keys=info["deleted_keys"],
        )

    def _save_cache(
        self,
        directory: str,
        file_hashes: dict[str, str],
        doc_index: DocumentIndex,
        changed_texts: dict[str, str] | None = None,
        deleted_keys: set[str] | None = None,
    ):
        """Save DocumentIndex + tracked dirs + stat caches to disk.

        Text changes are committed to History as a delta layer — not
        stored in the main index cache.
        """
        if not self._store:
            return
        self._store.save_index(
            self._path,
            directory,
            file_hashes,
            doc_index.to_dict(),
            indexed_dirs=self._indexed_dirs,
            file_stats={k: list(v) for k, v in self._file_stats.items()},
            dir_mtimes=self._dir_mtimes,
        )
        # Commit text changes to History
        if changed_texts or deleted_keys:
            history = self._history()
            if history:
                if history.layer_count() == 0:
                    # First index — need full texts for base layer
                    all_texts = self._store.load_texts(self._path) or {}
                    all_texts.update(changed_texts or {})
                    for k in deleted_keys or ():
                        all_texts.pop(k, None)
                    history.commit_base(all_texts)
                else:
                    history.commit(changed_texts or {}, deleted_keys)

    def save_search_index(self, search_index: "DocumentSearchIndex"):
        """Persist DocumentSearchIndex data to its own .six.pgz cache file.

        Historically this parsed the whole .idx.pgz, attached a
        "search_index" key, and rewrote it — a full read + double write of
        the largest cache file on every changed reindex pass."""
        if not self._store:
            return
        from ..search_engine.serialization import serialize_search_index

        self._store.save_search_index_data(self._path, serialize_search_index(search_index))

    def _report_skipped_large(self, threshold_bytes: int) -> None:
        """Emit a single error-level log for files skipped by the size guardrail.

        Every oversized file must be explicitly resolved — either added to
        .pgignore or matched by a glob in [index].allow_large in pg.toml.
        Silence is not an option: the log fires on every index pass until
        the caller clears the skip set.
        """
        if not self._skipped_large:
            return
        items = sorted(self._skipped_large.items(), key=lambda kv: -kv[1])
        sample = items[:10]
        bullets = "\n".join(f"  - {p} ({size / 1024 / 1024:.1f} MB)" for p, size in sample)
        more = f"\n  ... and {len(items) - 10} more" if len(items) > 10 else ""
        log.error(
            "Size guardrail: %d file(s) exceed max_file_size_bytes (%.1f MB). "
            "These files were NOT indexed. Resolve each one by either adding "
            "it to .pgignore or listing a matching glob in [index].allow_large "
            "in pg.toml.\n%s%s",
            len(items),
            threshold_bytes / 1024 / 1024,
            bullets,
            more,
        )

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
        ignore_patterns = _load_pgignore()
        if exclude:
            ignore_patterns.extend(exclude)
        # Config lives at workspace root (CWD), matching _load_pgignore /
        # _load_extensions — not at the indexed directory.
        max_file_size = _load_max_file_size_bytes()
        allow_large = _load_allow_large_globs()

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
                            if any(key.endswith(e) for e in ext_set):
                                paths.append((fpath, key))
                    continue

            # Record this directory's mtime
            try:
                self._dir_mtimes[root] = os.stat(root).st_mtime_ns
            except OSError:
                pass

            for fname in fnames:
                if any(fname.endswith(e) for e in ext_set):  # fast-path: skip stat on non-corpus files
                    fpath = Path(root) / fname
                    rel = str(fpath.relative_to(directory))
                    try:
                        size = fpath.stat().st_size
                    except OSError:
                        continue
                    verdict = classify_file(
                        rel,
                        size,
                        ignore_patterns=ignore_patterns,
                        max_bytes=max_file_size,
                        allow_large=allow_large,
                    )
                    if verdict == "oversized":
                        self._skipped_large[rel] = size
                        continue
                    if verdict != "ok":
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
    ) -> tuple[DocumentIndex, int, set[str]]:
        """Walk *directory*, index every file matching *extensions*.

        Uses stat fingerprinting + Merkle hashing: unchanged files are skipped.
        Deleted files are removed from the index.
        Reads .pgignore from directory root (gitignore-style patterns).

        force=True ignores all stat/hash caches and re-reads every file.
        """
        extensions = extensions or _load_extensions()
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

        self._skipped_large.clear()
        paths = self._walk_directory(
            directory,
            extensions,
            exclude,
            old_hashes=None if force else old_hashes,
        )
        self._report_skipped_large(_load_max_file_size_bytes())
        file_texts, new_hashes = self._read_and_hash(
            paths,
            old_hashes=None if force else old_hashes,
        )

        log.info(
            "index_incremental: dir=%r exts=%s force=%s old_hashes=%d walk_paths=%d file_texts=%d new_hashes=%d _file_stats=%d _dir_mtimes=%d",
            directory,
            extensions,
            force,
            len(old_hashes),
            len(paths),
            len(file_texts),
            len(new_hashes),
            len(self._file_stats),
            len(self._dir_mtimes),
        )

        return self._update_index(_index, file_texts, new_hashes, old_hashes, directory, on_progress)

    def reindex(
        self,
        _index: DocumentIndex,
        on_progress: Callable[[int, int, str], None] | None = None,
        force: bool = False,
    ) -> tuple[DocumentIndex, int, set[str]]:
        """Re-walk all tracked directories, picking up new/changed/deleted files.

        force=True ignores stat/hash caches and re-reads every file.
        """
        if not self._store:
            return _index, 0, set()

        # Warm path: hashes and tracked dirs live in memory (populated by
        # load_index at startup and refreshed on every pass). Parsing the
        # multi-hundred-MB disk cache here on every background tick was the
        # dominant cost of a no-change reindex.
        old_hashes: dict[str, str] = {} if force else dict(self._dir_hashes.get(self._path) or {})
        directory = ""
        if (not old_hashes and not force) or not self._indexed_dirs:
            cached = self._store.load_index(self._path)
            if not cached:
                return _index, 0, set()
            if not force:
                old_hashes = cached.get("file_hashes", {})
            directory = cached.get("directory", "")
            # Restore tracked dirs from cache if not already loaded
            if not self._indexed_dirs:
                self._indexed_dirs = cached.get("indexed_dirs", {})
                if directory and not self._indexed_dirs:
                    self._indexed_dirs[directory] = cached.get("extensions", _load_extensions())

        if not self._indexed_dirs:
            return _index, 0, set()

        if force:
            self._file_stats.clear()
            self._dir_mtimes.clear()

        self._skipped_large.clear()
        # Walk ALL tracked directories — picks up new files
        all_paths: list[tuple[Path, str]] = []
        primary_dir = directory
        for dir_path, exts in self._indexed_dirs.items():
            all_paths.extend(
                self._walk_directory(
                    dir_path,
                    exts,
                    old_hashes=None if force else old_hashes,
                )
            )
            if not primary_dir:
                primary_dir = dir_path
        self._report_skipped_large(_load_max_file_size_bytes())

        file_texts, new_hashes = self._read_and_hash(
            all_paths,
            old_hashes=None if force else old_hashes,
        )

        return self._update_index(_index, file_texts, new_hashes, old_hashes, primary_dir, on_progress)
