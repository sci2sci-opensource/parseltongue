"""Technician — load orchestration for the Bench.

Uses the loader to load/reload .pltg files, the Store to check cache
and persist results. Updates Bench status via a private callback.

The Technician decides *how* to load (cold, cache hit, hot-patch,
background reload). Owns scope registration, evaluation computation,
and search engine lifecycle. The Bench decides *what* to observe.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .systems.operations import OperationsSystem

from ..integrity.merkle import MerkleNode
from ..loader.lazy_loader import LazyLoader, LazyLoadResult
from .probe_core_to_consequence import CoreToConsequenceStructure, probe, probe_all
from .store import Store, _collect_tree_leaves

log = logging.getLogger("parseltongue.technician")

# Type for the (path, structure, loader) tuple stored by the Bench
Sample = tuple[str, MerkleNode, CoreToConsequenceStructure, LazyLoader]

# Callback signature: (path, integrity, status) → None
StatusCallback = Callable[[str, str, str], None]


class Technician:
    """Lab technician — prepares samples for the Bench.

    Coordinates between the loader and the Store. Reports state
    transitions via a callback provided by the Bench. Owns scope
    registration, evaluation computation, and search engine.
    """

    # Integrity values (mirrors Bench.Integrity for the callback)
    VERIFIED = "verified"
    UNKNOWN = "unknown"
    CORRUPTED = "corrupted"

    # Status values (mirrors Bench.Status for the callback)
    INITIALIZED = "initialized"
    LOADING = "loading"
    LIVE = "live"

    def __init__(
        self,
        store: Store,
        on_status: StatusCallback,
        lib_paths: list[str] | None = None,
        bench_pg: str | None = None,
    ):
        self._store = store
        self._on_status = on_status
        self._file_lists: dict[str, list[str]] = {}
        self._file_hashes: dict[str, dict[str, str]] = {}
        self._bg_reload: dict[str, threading.Thread] = {}
        self._bg_result: tuple[str, Sample] | None = None
        self._lib_paths: list[str] = lib_paths or []
        self._bench_pg = bench_pg
        self._frozen = None  # FrozenBench, created lazily on first prepare
        self._live: dict = {}  # path → LiveBench
        self._evaluation_mem: dict = {}  # path → Evaluation
        self._affected: dict[str, set[str]] = {}
        self._search_mem: dict = {}  # path → Search
        self._ops: "OperationsSystem | None" = None  # shared, stateless

    @property
    def file_lists(self) -> dict[str, list[str]]:
        return self._file_lists

    @property
    def file_hashes(self) -> dict[str, dict[str, str]]:
        return self._file_hashes

    @property
    def bg_reload(self) -> dict[str, threading.Thread]:
        return self._bg_reload

    # ── Frozen / Live systems ──

    def _ensure_ops(self):
        """Create OperationsSystem lazily — shared across all scopes."""
        if self._ops is None:
            from .systems.operations import OperationsSystem

            self._ops = OperationsSystem(lib_paths=self._lib_paths)
        return self._ops

    def _ensure_frozen(self):
        """Create FrozenBench lazily on first prepare."""
        if self._frozen is None and self._bench_pg:
            from .systems.frozen_bench import FrozenBench

            self._frozen = FrozenBench(self._bench_pg, self._lib_paths)  # type: ignore[assignment]
            if self._frozen is not None:
                self._frozen.register_scope("ops", self._ensure_ops())
        return self._frozen

    # ── Search engine ──

    def search_engine(self, path: str):
        """Get or create the Search engine for a path."""
        if path not in self._search_mem:
            from .search import Search
            from .store import SearchStore

            search_store = SearchStore(self._store, path)
            self._search_mem[path] = Search(store=search_store)
        return self._search_mem[path]

    # ── Scope registration ──

    def _register_scopes(self, path: str, sample: Sample):
        """Register all scopes — lens and evaluation. Called on both prepare and live."""
        from .optics import Lens
        from .perspectives.md_debugger import MDebuggerPerspective

        _, _, structure, loader = sample
        search = self.search_engine(path)

        # Lens scope — always available from structure
        lens = Lens(structure, [MDebuggerPerspective(loader)])
        search.register_scope("lens", lens.search_system)

        # Evaluation scope — from cache if available
        dx = self._load_evaluate(path, sample)
        if dx is not None:
            search.register_scope("evaluation", dx.search_system)

        # Operations scope — generic composition over tagged forms
        ops = self._ensure_ops()
        ops.register_scope("lens", lens.search_system)
        if dx is not None:
            ops.register_scope("evaluation", dx.search_system)
        ops.register_scope("search", search._system)
        search.register_scope("ops", ops)

        # Populate search docs if live
        result = sample[3].last_result
        if result is not None and hasattr(result.system, "engine") and result.system.engine.facts:
            from .systems.live_bench import LiveBench

            self._live[path] = LiveBench(result, self._bench_pg, self._lib_paths)  # type: ignore[arg-type]
            self._live[path].register_scope("ops", ops)
            for doc_name, doc_text in result.system.engine.documents.items():
                if doc_name not in search._index.documents:
                    search._index.add(doc_name, doc_text)

    # ── Evaluation ──

    def _load_evaluate(self, path: str, sample: Sample | None):
        """Evaluate consistency — cached, incremental, or cold."""
        from .evaluation import Evaluation

        # Memory cache
        if path in self._evaluation_mem:
            return self._evaluation_mem[path]

        # Disk cache — exact Merkle match
        if sample:
            merkle_root = sample[1].hash
            disk_dx = self._store.load_diagnosis(path, merkle_root)
            if disk_dx is not None:
                self._evaluation_mem[path] = disk_dx
                return disk_dx

        # Incremental: stale evaluation + known affected set
        affected = self._affected.get(path)
        if affected is not None:
            old_dx = self._store.load_stale_diagnosis(path)
            if old_dx is not None:
                result, sample = self.ensure_live(path, sample)
                engine = result.system.engine

                diffs_to_patch: set[str] = set()
                for name in affected:
                    diffs_to_patch |= engine.diff_refs.get(name, set())

                if diffs_to_patch:
                    log.info(
                        "Incremental evaluate: %d/%d diffs",
                        len(diffs_to_patch),
                        len(engine.diffs),
                    )
                    lc = result.consistency_incremental(diffs_to_patch)
                    dx = old_dx.incremental(diffs_to_patch, lc)
                    self._evaluation_mem[path] = dx
                    self._save_evaluation(path, dx, sample)
                    self._affected.pop(path, None)
                    return dx

        # Cold — full consistency
        result, sample = self.ensure_live(path, sample)
        lc = result.consistency()
        dx = Evaluation.from_report(lc, result)
        self._evaluation_mem[path] = dx
        self._save_evaluation(path, dx, sample)
        return dx

    def _save_evaluation(self, path: str, dx, sample: Sample | None):
        merkle_root = sample[1].hash if sample else ""
        self._store.save_diagnosis(path, merkle_root, dx)

    # ── Prepare ──

    def prepare(
        self,
        path: str,
        cached: Sample | None,
    ) -> tuple[Sample, set[str] | None]:
        """Prepare a sample at path.

        Returns (sample, affected_names).
        affected_names is None for cold/cache-hit, a set for hot-patch.
        """
        file_list: list[str] | None = self._file_lists.get(path)
        disk_raw = None

        # Try to get file list from disk if not in memory
        if not file_list:
            disk_raw = self._store.read_raw(path)
            if disk_raw and "source_files" in disk_raw:
                file_list = list(disk_raw["source_files"])
                self._file_lists[path] = file_list

        if file_list:
            new_hashes = self._store.hash_files(file_list)
            new_tree = self._store.build_file_tree(file_list, new_hashes)

            # Memory cache — exact match
            if cached and cached[1].hash == new_tree.hash:
                return cached, None  # integrity unchanged

            self._on_status(path, self.CORRUPTED, "")

            # Disk cache — exact match
            if disk_raw is None:
                disk_raw = self._store.read_raw(path)
            if disk_raw and disk_raw.get("merkle_root") == new_tree.hash:
                structure, loader = self._store.deserialize(disk_raw)
                sample = (path, new_tree, structure, loader)
                self._file_hashes[path] = new_hashes
                self._on_status(path, self.VERIFIED, self.LOADING)
                self._background_reload(path, sample)
                self._ensure_frozen()
                self._register_scopes(path, sample)
                return sample, None

            # Tree differs — hot-patch if we have a cached system
            if disk_raw and "system" in disk_raw and "merkle_tree" in disk_raw:
                old_hashes = self._file_hashes.get(path)
                if old_hashes is None and disk_raw.get("file_hashes"):
                    old_hashes = disk_raw["file_hashes"]

                if old_hashes:
                    changed_files = self._store.diff_file_hashes(old_hashes, new_hashes)
                    if changed_files:
                        patch_result = self._hot_patch(disk_raw, changed_files)
                        if patch_result is not None:
                            structure, loader, affected = patch_result
                            new_tree = self._store.build_file_tree(file_list, new_hashes)
                            sample = (path, new_tree, structure, loader)
                            self._file_hashes[path] = new_hashes
                            self._on_status(path, self.UNKNOWN, self.LOADING)
                            self._background_reload(path, sample)
                            self._affected[path] = affected
                            self._evaluation_mem.pop(path, None)
                            self._ensure_frozen()
                            self._register_scopes(path, sample)
                            return sample, affected

        # Cold — full reload (_cold_load registers live scopes)
        sample = self._cold_load(path)
        self._ensure_frozen()
        return sample, None

    def ensure_live(
        self,
        path: str,
        cached: Sample | None,
    ) -> tuple[LazyLoadResult, Sample]:
        """Get a live LazyLoadResult (with engine). Reloads if needed."""
        if cached:
            result: LazyLoadResult | None = cached[3].last_result
            if result is not None:
                return result, cached

        # System is empty or missing — cold load
        sample = self._cold_load(path)
        return sample[3].last_result, sample  # type: ignore[return-value]

    def collect_source_files(self, loader: LazyLoader) -> list[str]:
        """Collect all files the loader touched: .pltg source files + document paths."""
        files = []
        seen: set[str] = set()
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

    def invalidate(self, path: str | None = None):
        """Clear technician-side caches for a path, or all."""
        if path is None:
            self._file_lists.clear()
            self._file_hashes.clear()
            self._store.remove_all()
            self._evaluation_mem.clear()
            self._affected.clear()
            self._search_mem.clear()
            self._live.clear()
        else:
            self._file_lists.pop(path, None)
            self._file_hashes.pop(path, None)
            self._store.remove(path)
            self._evaluation_mem.pop(path, None)
            self._affected.pop(path, None)
            self._search_mem.pop(path, None)
            self._live.pop(path, None)

    # ── Internal ──

    def _cold_load(self, path: str) -> Sample:
        """Full reload from scratch."""
        loader = LazyLoader(lib_paths=self._lib_paths)
        loader.load_main(path, name="Technician.cold")
        load_result = loader.last_result
        assert load_result is not None
        file_list = self.collect_source_files(loader)
        new_hashes = self._store.hash_files(file_list)
        new_tree = self._store.build_file_tree(file_list, new_hashes)
        self._file_lists[path] = file_list
        self._file_hashes[path] = new_hashes
        structure = probe_all(load_result)

        sample: Sample = (path, new_tree, structure, loader)
        self._on_status(path, self.VERIFIED, self.LIVE)
        self._store.save(path, new_tree, structure, loader, file_list, new_hashes)
        self._register_scopes(path, sample)
        return sample

    def _hot_patch(
        self, disk_raw: dict, changed_files: set[str]
    ) -> tuple[CoreToConsequenceStructure, LazyLoader, set[str]] | None:
        """Hot-patch a cached system from changed files.

        Delegates all parsing/patching/execution to the loader — the
        technician only orchestrates deserialization and re-probing.
        """
        try:
            structure, loader = self._store.deserialize(disk_raw)
        except Exception:
            log.warning("Failed to deserialize cache for hot-patch")
            return None

        node_index = disk_raw.get("node_index", {})
        changed_names = loader.hot_patch(changed_files, node_index)

        if not changed_names:
            return None

        engine = loader.last_result.system.engine  # type: ignore[union-attr]
        log.info("Hot-patch: %d names from %d changed files", len(changed_names), len(changed_files))

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

    def _background_reload(self, path: str, current_sample: Sample):
        """Start a background thread to do a full reload for eventual consistency."""
        if path in self._bg_reload and self._bg_reload[path].is_alive():
            return

        # Capture references needed by the closure
        store = self._store
        on_status = self._on_status
        file_lists = self._file_lists
        file_hashes = self._file_hashes
        technician = self

        def _reload():
            try:
                loader = LazyLoader(lib_paths=technician._lib_paths)
                loader.load_main(path, name="Technician.bg_reload")
                file_list = technician.collect_source_files(loader)
                new_hashes = store.hash_files(file_list)
                new_tree = store.build_file_tree(file_list, new_hashes)
                bg_result = loader.last_result
                assert bg_result is not None
                structure = probe_all(bg_result)

                # Validate integrity against hot-patched state
                hot_tree = current_sample[1]
                if hot_tree.hash == new_tree.hash:
                    log.info("Background reload: integrity OK — hot-patch matched full load")
                else:
                    hot_leaves = _collect_tree_leaves(hot_tree)
                    full_leaves = _collect_tree_leaves(new_tree)
                    diverged = []
                    for leaf_path in set(hot_leaves) | set(full_leaves):
                        if hot_leaves.get(leaf_path, "") != full_leaves.get(leaf_path, ""):
                            diverged.append(leaf_path)
                    log.warning(
                        "Background reload: integrity DIVERGED — %d files differ: %s",
                        len(diverged),
                        ", ".join(str(p) for p in diverged[:5]),
                    )

                # Report completion — Bench will swap in the result
                file_lists[path] = file_list
                file_hashes[path] = new_hashes
                new_sample: Sample = (path, new_tree, structure, loader)
                technician._bg_result = (path, new_sample)
                on_status(path, Technician.VERIFIED, Technician.LIVE)
                # Register live scopes with the fresh sample
                technician._register_scopes(path, new_sample)
                store.save(path, new_tree, structure, loader, file_list, new_hashes)
                log.info("Background reload complete for %s", path)
            except Exception as e:
                log.warning("Background reload failed for %s: %s", path, e)

        t = threading.Thread(target=_reload, daemon=True)
        self._bg_reload[path] = t
        t.start()
