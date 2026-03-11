"""Bench — workstation for observing .pltg specimens.

Prepare a specimen, then observe: ``lens()`` for structure,
``diagnose()`` for health. Backed by Merkle tree caching.

Usage::

    from parseltongue.core.inspect.bench import Bench

    bench = Bench()
    bench.prepare("parseltongue/core/validation/core_clean.pltg")

    lens = bench.lens()          # structural observation
    dx   = bench.diagnose()      # consistency observation

    dx.summary()
    dx.focus("readme.").issues()
    dx.find("count")
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

from ..atoms import parse_all
from ..engine import _execute_directive
from ..integrity.merkle import MerkleNode, _sha256, merkle_combine
from ..loader.lazy_loader import LazyLoader, LazyLoadResult
from ..system import System
from .diagnosis import Diagnosis
from .lens import Lens
from .perspectives.md_debugger import MDebuggerPerspective
from .probe_core_to_consequence import CoreToConsequenceStructure, probe, probe_all
from .serialization import deserialize_structure, serialize_structure

log = logging.getLogger("parseltongue.bench")

BENCH_DIR = ".parseltongue-bench"


def _directive_name(sexp_text: str) -> str | None:
    """Extract directive name from a serialized S-expression."""
    try:
        exprs = parse_all(sexp_text)
        if exprs and isinstance(exprs[0], list) and len(exprs[0]) >= 2:
            return str(exprs[0][1])
    except Exception:
        pass
    return None


def _collect_tree_leaves(node: MerkleNode) -> dict[str, str]:
    """Collect {content: hash} for all leaves in a Merkle tree."""
    if node.is_leaf:
        return {node.content: node.hash} if node.content else {}
    result = {}
    for child in node.children or []:
        result.update(_collect_tree_leaves(child))
    return result


class Bench:
    """Workstation for .pltg specimens.

    ``prepare(path)`` loads the file (cached via Merkle trees).
    ``lens()`` returns structural observation.
    ``diagnose()`` returns consistency observation.
    Both are first-class objects with focus, search, and filtering.
    """

    class Integrity:
        """Integrity state of a prepared specimen.

        - verified:  full load completed, or hot-patch confirmed by background reload
        - unknown:   hot-patched but not yet verified by background reload
        - corrupted: change detected, not yet patched
        """

        VERIFIED = "verified"
        UNKNOWN = "unknown"
        CORRUPTED = "corrupted"

        def __init__(self):
            self._state: dict[str, str] = {}

        def __getitem__(self, path: str) -> str:
            return self._state.get(path, self.CORRUPTED)

        def __repr__(self) -> str:
            if not self._state:
                return "Integrity(empty)"
            parts = [f"{Path(p).name}: {s}" for p, s in self._state.items()]
            return f"Integrity({', '.join(parts)})"

    class Status:
        """Lifecycle status of a prepared specimen.

        - initialized: bench created, no specimen loaded yet
        - loading:     background reload in progress (hot-patched system available)
        - live:        full loader completed, fully operational
        """

        INITIALIZED = "initialized"
        LOADING = "loading"
        LIVE = "live"

        def __init__(self):
            self._state: dict[str, str] = {}

        def __getitem__(self, path: str) -> str:
            return self._state.get(path, self.INITIALIZED)

        def __repr__(self) -> str:
            if not self._state:
                return "Status(initialized)"
            parts = [f"{Path(p).name}: {s}" for p, s in self._state.items()]
            return f"Status({', '.join(parts)})"

    def __init__(self, bench_dir: str | Path | None = None):
        self._bench_dir = Path(bench_dir or BENCH_DIR)
        self._mem: dict[str, tuple[str, MerkleNode, CoreToConsequenceStructure, LazyLoader]] = {}
        self._diagnosis_mem: dict[str, Diagnosis] = {}
        self._affected: dict[str, set[str]] = {}  # path → affected names from last prepare
        self._file_lists: dict[str, list[str]] = {}  # path → source files for tree building
        self._file_hashes: dict[str, dict[str, str]] = {}  # path → {file: hash} for quick diff
        self._current_path: str | None = None
        self._bg_reload: dict[str, threading.Thread] = {}  # path → background reload thread
        self.integrity = self.Integrity()
        self.status = self.Status()

    # ── Prepare ──

    def prepare(self, path: str) -> "Bench":
        """Prepare a .pltg file for observation. Returns self for chaining."""
        path = str(Path(path).resolve())
        self._current_path = path
        self._prepare_internal(path)
        return self

    def _require_current(self) -> str:
        if self._current_path is None:
            raise RuntimeError("No specimen prepared. Call bench.prepare(path) first.")
        return self._current_path

    # ── Observe: structure ──

    def lens(self, path: str | None = None) -> Lens:
        """Structural observation — a Lens with MDebuggerPerspective."""
        path = str(Path(path).resolve()) if path else self._require_current()
        if path not in self._mem:
            self.prepare(path)
        _, _, structure, loader = self._mem[path]
        return Lens(structure, [MDebuggerPerspective(loader)])

    # ── Observe: health ──

    def diagnose(self, path: str | None = None) -> Diagnosis:
        """Consistency observation — a Diagnosis with focus, search, filtering.

        Cached in memory and on disk. Same Merkle root = same diagnosis.
        Incremental: when only some nodes changed, patches only affected diffs.
        """
        path = str(Path(path).resolve()) if path else self._require_current()

        # Memory cache
        if path in self._diagnosis_mem:
            return self._diagnosis_mem[path]

        # Disk cache — exact Merkle match
        disk_dx = self._load_diagnosis_disk(path)
        if disk_dx is not None:
            self._diagnosis_mem[path] = disk_dx
            return disk_dx

        # Incremental: stale diagnosis + known affected set from prepare
        affected = self._affected.get(path)
        if affected is not None:
            old_dx = self._load_stale_diagnosis_disk(path)
            if old_dx is not None:
                result = self._ensure_live_result(path)
                engine = result.system.engine

                # Find diffs touched by affected names via inverted index
                diffs_to_patch = set()
                for name in affected:
                    diffs_to_patch |= engine.diff_refs.get(name, set())

                if diffs_to_patch:
                    log.info("Incremental diagnose: %d/%d diffs", len(diffs_to_patch), len(engine.diffs))
                    lc = result.consistency_incremental(diffs_to_patch)
                    dx = old_dx.incremental(diffs_to_patch, lc)
                    self._diagnosis_mem[path] = dx
                    self._save_diagnosis(path, dx)
                    self._affected.pop(path, None)
                    return dx

        # Cold — full consistency
        result = self._ensure_live_result(path)
        lc = result.consistency()
        dx = Diagnosis.from_report(lc, result)
        self._diagnosis_mem[path] = dx
        self._save_diagnosis(path, dx)
        return dx

    # ── Search ──

    def search(
        self, query: str, max_lines: int = 20, max_callers: int = 5, offset: int = 0, rank: str = "callers"
    ) -> dict:
        """Full-text search across all loaded documents with pltg provenance.

        rank: "callers" (most pltg nodes first), "coverage" (best overlap first),
              "document" (grouped by document, most hits first).
        """
        path = self._require_current()
        if path not in self._mem:
            self.prepare(path)
        return self._search_engine(path).query(
            query, max_lines=max_lines, max_callers=max_callers, offset=offset, rank=rank
        )

    def _search_engine(self, path: str):
        from .search import Search

        _, _, _, loader = self._mem[path]
        return Search(loader.last_result.system.engine._verifier.index)  # type: ignore[union-attr]

    # ── Access ──

    def result(self, path: str | None = None) -> LazyLoadResult:
        """The LazyLoadResult for the specimen. Triggers full load if needed."""
        path = str(Path(path).resolve()) if path else self._require_current()
        return self._ensure_live_result(path)

    @property
    def engine(self):
        """The engine of the current specimen."""
        return self.result().system.engine

    # ── Cache management ──

    def invalidate(self, path: str | None = None):
        """Clear cache for a path, or all if None."""
        if path is None:
            self._mem.clear()
            self._diagnosis_mem.clear()
            self._file_lists.clear()
            self._file_hashes.clear()
            if self._bench_dir.exists():
                for f in self._bench_dir.glob("*.json"):
                    f.unlink()
        else:
            path = str(Path(path).resolve())
            self._mem.pop(path, None)
            self._diagnosis_mem.pop(path, None)
            self._file_lists.pop(path, None)
            self._file_hashes.pop(path, None)
            self._cache_path(path).unlink(missing_ok=True)
            self._diagnosis_cache_path(path).unlink(missing_ok=True)

    # ── Internal: prepare ──

    def _prepare_internal(self, path: str):
        """Ensure the specimen at path is loaded and cached.

        Flow:
        1. If we have a file list (memory or disk), hash files to build tree
        2. If tree matches cached → return (nothing changed)
        3. If tree differs → find changed files → hot-patch system → re-probe affected
        4. If no cache at all → cold load
        5. Background: full reload to reach full integrity
        """
        cached = self._mem.get(path)
        file_list: list[str] | None = self._file_lists.get(path)
        disk_raw = None

        # Try to get file list from disk if not in memory
        if not file_list:
            disk_raw = self._read_disk_raw(path)
            if disk_raw and "source_files" in disk_raw:
                file_list = list(disk_raw["source_files"])
                self._file_lists[path] = file_list

        if file_list:
            new_hashes = self._hash_files(file_list)
            new_tree = self._build_file_tree(file_list, new_hashes)

            # Memory cache — exact match
            if cached and cached[1].hash == new_tree.hash:
                return  # integrity unchanged

            self.integrity._state[path] = self.Integrity.CORRUPTED

            # Disk cache — exact match
            if disk_raw is None:
                disk_raw = self._read_disk_raw(path)
            if disk_raw and disk_raw.get("merkle_root") == new_tree.hash:
                structure, loader = self._deserialize_cache(disk_raw)
                self._mem[path] = (path, new_tree, structure, loader)
                self._file_hashes[path] = new_hashes
                self.integrity._state[path] = self.Integrity.VERIFIED
                self.status._state[path] = self.Status.LOADING
                # Deserialized system is functional but not backed by a live loader.
                # Background reload produces the real loader for eventual LIVE status.
                self._background_reload(path)
                return

            # Tree differs — hot-patch if we have a cached system
            if disk_raw and "system" in disk_raw and "merkle_tree" in disk_raw:
                old_hashes = self._file_hashes.get(path)
                if old_hashes is None and disk_raw.get("file_hashes"):
                    old_hashes = disk_raw["file_hashes"]

                if old_hashes:
                    changed_files = self._diff_file_hashes(old_hashes, new_hashes)
                    if changed_files:
                        patch_result = self._hot_patch(path, disk_raw, changed_files)
                        if patch_result is not None:
                            structure, loader, affected = patch_result
                            new_tree = self._build_file_tree(file_list, new_hashes)
                            self._mem[path] = (path, new_tree, structure, loader)
                            self._file_hashes[path] = new_hashes
                            self._affected[path] = affected
                            self._diagnosis_mem.pop(path, None)
                            self.integrity._state[path] = self.Integrity.UNKNOWN
                            self.status._state[path] = self.Status.LOADING
                            # Background: full reload for eventual consistency
                            self._background_reload(path)
                            return

        # Cold — full reload
        self._diagnosis_mem.pop(path, None)
        loader = LazyLoader()
        loader.load_main(path)
        load_result = loader.last_result
        assert load_result is not None
        file_list = self._collect_source_files(loader)
        new_hashes = self._hash_files(file_list)
        new_tree = self._build_file_tree(file_list, new_hashes)
        self._file_lists[path] = file_list
        self._file_hashes[path] = new_hashes
        structure = probe_all(load_result)

        self._mem[path] = (path, new_tree, structure, loader)
        self.integrity._state[path] = self.Integrity.VERIFIED
        self.status._state[path] = self.Status.LIVE
        self._save(path, new_tree, structure, loader, new_hashes)

    def _hot_patch(
        self, path: str, disk_raw: dict, changed_files: set[str]
    ) -> tuple[CoreToConsequenceStructure, LazyLoader, set[str]] | None:
        """Hot-patch a cached system from changed files.

        1. Deserialize cached system
        2. Find names from changed files (via node_index)
        3. Retract old names from engine
        4. Re-parse changed .pltg files and execute on engine
        5. Re-probe affected names
        6. Return (structure, loader, affected_names)
        """
        try:
            structure, loader = self._deserialize_cache(disk_raw)
        except Exception:
            log.warning("Failed to deserialize cache for hot-patch")
            return None

        engine = loader.last_result.system.engine  # type: ignore[union-attr]
        node_index = disk_raw.get("node_index", {})

        # Find names defined in changed files
        changed_names = set()
        for name, info in node_index.items():
            sf = info.get("source_file", "")
            if sf in changed_files:
                changed_names.add(name)

        if not changed_names:
            return None

        log.info("Hot-patch: %d names from %d changed files", len(changed_names), len(changed_files))

        # Retract old definitions
        for name in changed_names:
            try:
                engine.retract(name)
            except KeyError:
                pass

        # Re-parse changed .pltg files and execute on engine
        # We need to handle namespacing: names in submodules have module prefixes
        # The node_index tells us the original module for each name
        for f in changed_files:
            if not f.endswith(".pltg"):
                # Document file changed — reload it
                try:
                    content = Path(f).read_text()
                    # Find document name for this path
                    for doc_name, doc_content in list(engine.documents.items()):
                        # Match by checking if path ends with the doc name
                        if f.endswith(doc_name) or Path(f).stem == doc_name:
                            engine.register_document(doc_name, content)
                            break
                except OSError:
                    pass
                continue

            try:
                content = Path(f).read_text()
            except OSError:
                continue

            # Figure out the module prefix for this file
            prefix = ""
            for name, info in node_index.items():
                if info.get("source_file") == f and "." in name:
                    # e.g. "std.epistemics.hallucinated" from file epistemics.pltg
                    # prefix = "std.epistemics."
                    prefix = name.rsplit(".", 1)[0] + "."
                    break

            # Parse and execute each directive, adding prefix
            try:
                exprs = parse_all(content)
            except Exception:
                log.warning("Failed to parse %s for hot-patch", f)
                continue

            from ..atoms import Symbol
            from ..lang import DSL_KEYWORDS, SPECIAL_FORMS

            for expr in exprs:
                if not isinstance(expr, list) or not expr:
                    continue
                head = str(expr[0]) if expr else ""
                if head in DSL_KEYWORDS or head in SPECIAL_FORMS:
                    if prefix and len(expr) >= 2:
                        expr[1] = Symbol(prefix + str(expr[1]))
                    try:
                        _execute_directive(engine, expr)
                    except Exception as e:
                        log.warning("Hot-patch directive failed: %s", e)

        # Trace affected names through probe graph
        dependents: dict[str, set[str]] = {}
        for name, node in structure.graph.items():
            for inp in node.inputs:
                dependents.setdefault(inp, set()).add(name)

        affected = set(changed_names)
        queue = list(changed_names)
        while queue:
            current = queue.pop()
            for dep in dependents.get(current, set()):
                if dep not in affected:
                    affected.add(dep)
                    queue.append(dep)

        # Re-probe affected
        if affected and len(affected) < len(structure.graph) // 2:
            log.info("Hot-patch re-probe: %d/%d affected", len(affected), len(structure.graph))
            new_sub = probe(list(affected), engine)
            merged_graph = dict(structure.graph)
            merged_graph.update(new_sub.graph)
            merged_depths = dict(structure.depths)
            merged_depths.update(new_sub.depths)
            structure = CoreToConsequenceStructure(
                layers=new_sub.layers,
                graph=merged_graph,
                depths=merged_depths,
                max_depth=max(merged_depths.values()) if merged_depths else 0,
            )

        # Reconnect atoms
        for name, node in structure.graph.items():
            if name in engine.facts:
                node.atom = engine.facts[name]
            elif name in engine.axioms:
                node.atom = engine.axioms[name]
            elif name in engine.theorems:
                node.atom = engine.theorems[name]
            elif name in engine.terms:
                node.atom = engine.terms[name]

        return structure, loader, affected

    def _background_reload(self, path: str):
        """Start a background thread to do a full reload for eventual consistency.

        When the reload finishes, validates integrity by comparing the full
        system's Merkle tree against the hot-patched tree. If they match,
        the hot-patch was correct — swap silently. If they differ, log
        divergent nodes and swap in the authoritative full result.
        """
        if path in self._bg_reload and self._bg_reload[path].is_alive():
            return  # already reloading

        def _reload():
            try:
                loader = LazyLoader()
                loader.load_main(path)
                file_list = self._collect_source_files(loader)
                new_hashes = self._hash_files(file_list)
                new_tree = self._build_file_tree(file_list, new_hashes)
                bg_result = loader.last_result
                assert bg_result is not None
                structure = probe_all(bg_result)

                # Validate integrity against hot-patched state
                cached = self._mem.get(path)
                if cached:
                    hot_tree = cached[1]
                    if hot_tree.hash == new_tree.hash:
                        log.info("Background reload: integrity OK — hot-patch matched full load")
                    else:
                        # Diff to find what the hot-patch got wrong
                        hot_leaves = _collect_tree_leaves(hot_tree)
                        full_leaves = _collect_tree_leaves(new_tree)
                        diverged = []
                        all_paths = set(hot_leaves) | set(full_leaves)
                        for leaf_path in all_paths:
                            h_hash = hot_leaves.get(leaf_path, "")
                            f_hash = full_leaves.get(leaf_path, "")
                            if h_hash != f_hash:
                                diverged.append(leaf_path)
                        log.warning(
                            "Background reload: integrity DIVERGED — %d/%d files differ: %s",
                            len(diverged),
                            len(all_paths),
                            ", ".join(str(p) for p in diverged[:5]),
                        )
                        # Invalidate diagnosis — hot-patched diagnosis may be wrong
                        self._diagnosis_mem.pop(path, None)

                # Always swap in the full result — it's authoritative
                self._mem[path] = (path, new_tree, structure, loader)
                self._file_lists[path] = file_list
                self._file_hashes[path] = new_hashes
                self.integrity._state[path] = self.Integrity.VERIFIED
                self.status._state[path] = self.Status.LIVE
                self._save(path, new_tree, structure, loader, new_hashes)
                log.info("Background reload complete for %s", path)
            except Exception as e:
                log.warning("Background reload failed for %s: %s", path, e)

        t = threading.Thread(target=_reload, daemon=True)
        self._bg_reload[path] = t
        t.start()

    def _ensure_live_result(self, path: str) -> LazyLoadResult:
        """Get a live LazyLoadResult (with engine)."""
        if path not in self._mem:
            self.prepare(path)
        cached = self._mem[path]
        result: LazyLoadResult | None = cached[3].last_result
        # If system is empty (no cache data at all), reload
        if result is None or (not result.system.engine.facts and not result.system.engine.axioms):
            loader = LazyLoader()
            loader.load_main(path)
            file_list = self._collect_source_files(loader)
            new_hashes = self._hash_files(file_list)
            new_tree = self._build_file_tree(file_list, new_hashes)
            lr = loader.last_result
            assert lr is not None
            structure = probe_all(lr)
            self._mem[path] = (path, new_tree, structure, loader)
            self._file_lists[path] = file_list
            self._file_hashes[path] = new_hashes
            result = lr
        return result

    # ── Internal: file hashing ──

    def _hash_files(self, files: list[str]) -> dict[str, str]:
        """Hash each file's content. Returns {path: sha256}."""
        hashes = {}
        for f in files:
            try:
                hashes[f] = _sha256(Path(f).read_text())
            except OSError:
                hashes[f] = ""
        return hashes

    def _build_file_tree(self, files: list[str], hashes: dict[str, str]) -> MerkleNode:
        """Build Merkle tree where each file is a leaf.

        Leaf hash = sha256(file content), leaf content = file path.
        """
        leaves = []
        for f in files:
            h = hashes.get(f, _sha256(""))
            leaves.append(MerkleNode(hash=h, content=f))
        if not leaves:
            return MerkleNode(hash=_sha256(""))
        return merkle_combine(leaves)

    def _diff_file_hashes(self, old: dict[str, str], new: dict[str, str]) -> set[str]:
        """Find files whose hashes differ between old and new."""
        changed = set()
        all_files = set(old) | set(new)
        for f in all_files:
            if old.get(f) != new.get(f):
                changed.add(f)
        return changed

    def _collect_source_files(self, loader: LazyLoader) -> list[str]:
        """Collect all files the loader touched: .pltg source files + document paths."""
        files = []
        seen = set()
        for node in loader._all_nodes:
            if node.source_file and node.source_file not in seen:
                seen.add(node.source_file)
                files.append(node.source_file)
        result = loader.last_result
        if result and result.system and result.system.engine:
            for name in sorted(result.system.engine.documents):
                doc_content = result.system.engine.documents[name]
                for ctx in loader.modules_contexts.values():
                    candidate = Path(ctx.current_dir) / name
                    if candidate.exists() and candidate.read_text() == doc_content:
                        p = str(candidate)
                        if p not in seen:
                            seen.add(p)
                            files.append(p)
                        break
        return sorted(files)

    # ── Internal: cache ──

    def _ensure_dir(self):
        self._bench_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, path: str) -> str:
        return hashlib.sha256(path.encode()).hexdigest()[:16]

    def _cache_path(self, path: str) -> Path:
        return self._bench_dir / f"{self._cache_key(path)}.json"

    def _diagnosis_cache_path(self, path: str) -> Path:
        return self._bench_dir / f"{self._cache_key(path)}.dx.json"

    def _save(
        self,
        path: str,
        tree: MerkleNode,
        structure: CoreToConsequenceStructure,
        loader: LazyLoader,
        file_hashes: dict[str, str] | None = None,
    ):
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
            "source_files": self._file_lists.get(path, []),
            "file_hashes": file_hashes or self._file_hashes.get(path, {}),
            "system": result.system.to_dict(),
        }
        cache_file = self._cache_path(path)
        try:
            with open(cache_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            log.warning("Failed to save bench cache for %s: %s", path, e)

    def _read_disk_raw(self, path: str) -> dict | None:
        """Read raw cache JSON from disk, or None."""
        cache_file = self._cache_path(path)
        if not cache_file.exists():
            return None
        try:
            with open(cache_file) as f:
                return json.load(f)
        except Exception as e:
            log.warning("Failed to read bench cache for %s: %s", path, e)
            cache_file.unlink(missing_ok=True)
            return None

    def _deserialize_cache(self, data: dict) -> tuple[CoreToConsequenceStructure, LazyLoader]:
        """Deserialize structure + full system from cache data."""
        structure = deserialize_structure(data["structure"])
        from ..ast import DirectiveNode

        if "system" in data:
            system = System.from_dict(data["system"])
        else:
            system = System()
        # Reconnect atoms in the probe graph from the live engine
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

    def _save_diagnosis(self, path: str, dx: Diagnosis):
        self._ensure_dir()
        cached = self._mem.get(path)
        merkle_root = cached[1].hash if cached else ""
        data = {"merkle_root": merkle_root, "diagnosis": dx.to_dict()}
        try:
            with open(self._diagnosis_cache_path(path), "w") as f:
                json.dump(data, f)
        except Exception as e:
            log.warning("Failed to save diagnosis cache for %s: %s", path, e)

    def _load_diagnosis_disk(self, path: str) -> Diagnosis | None:
        cache_file = self._diagnosis_cache_path(path)
        if not cache_file.exists():
            return None
        cached = self._mem.get(path)
        if not cached:
            return None
        try:
            with open(cache_file) as f:
                data = json.load(f)
        except Exception:
            cache_file.unlink(missing_ok=True)
            return None
        if data.get("merkle_root") != cached[1].hash:
            return None
        try:
            return Diagnosis.from_dict(data["diagnosis"])
        except Exception:
            cache_file.unlink(missing_ok=True)
            return None

    def _load_stale_diagnosis_disk(self, path: str) -> Diagnosis | None:
        """Load diagnosis from disk regardless of Merkle root match."""
        cache_file = self._diagnosis_cache_path(path)
        if not cache_file.exists():
            return None
        try:
            with open(cache_file) as f:
                data = json.load(f)
        except Exception:
            cache_file.unlink(missing_ok=True)
            return None
        try:
            return Diagnosis.from_dict(data["diagnosis"])
        except Exception:
            cache_file.unlink(missing_ok=True)
            return None
