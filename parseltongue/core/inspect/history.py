"""History — append-only timeline of indexed filesystem states.

Built on LayeredTexts (OrdinalPGZ layers). Each layer is an immutable
snapshot of what changed. History provides time travel, diffing, and
restore — both whole-state and per-file.

Layer 0 is the oldest known state (base). Layer N is the latest delta.
Tombstones mark deletions. Trim squashes old layers to bound storage.

Metadata is stored in a separate OrdinalPGZ file ({prefix}.meta.pgz)
with string keys/values. Updated on every commit/trim. Provides instant
layer inspection without scanning layer files.

    history = History(cache_dir, "myproject", max_layers=42)
    history.commit(changed={"a.py": "new"}, deleted={"old.py"})
    history.current()           → merged latest state
    history.at(5)               → state at layer 5
    history.file_at("a.py", 5)  → single file at layer 5
    history.diff(3, 7)          → what changed between layers 3 and 7
    history.diff_file("a.py", 3, 7)  → single file diff
    history.restore(5)          → reverse delta to layer 5 state
    history.restore_file("a.py", 5)  → restore just one file
    history.layers()            → layer metadata (from meta file, instant)
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from pathlib import Path

from .pgz import (
    LayeredTexts,
    _TOMBSTONE,
    ordinal_pgz_header_keys,
    ordinal_pgz_read,
    ordinal_pgz_write,
)


@dataclass(frozen=True)
class LayerInfo:
    """Metadata for a single layer."""

    index: int
    timestamp: float = 0.0
    file_count: int = 0
    disk_bytes: int = 0
    keys_added: int = 0
    keys_modified: int = 0
    keys_deleted: int = 0


@dataclass(frozen=True)
class FileDiff:
    """Diff result for a single file between two layers."""

    name: str
    status: str  # "added", "modified", "deleted", "unchanged"
    old_text: str | None = None
    new_text: str | None = None


@dataclass(frozen=True)
class Diff:
    """Diff result between two layer states."""

    from_layer: int
    to_layer: int
    added: dict[str, str] = field(default_factory=dict)
    modified: dict[str, tuple[str, str]] = field(default_factory=dict)  # {name: (old, new)}
    deleted: dict[str, str] = field(default_factory=dict)  # {name: old_text}

    @property
    def changed_count(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)

    @property
    def changed_files(self) -> set[str]:
        return set(self.added) | set(self.modified) | set(self.deleted)


# ── Metadata persistence ──


def _meta_to_entries(
    layers_info: list[LayerInfo],
    total_commits: int,
    created: float,
) -> dict[str, str]:
    """Serialize metadata to OrdinalPGZ entries {key: str_value}."""
    entries: dict[str, str] = {
        "_total_commits": str(total_commits),
        "_created": str(created),
        "_layer_count": str(len(layers_info)),
    }
    for li in layers_info:
        p = str(li.index)
        entries[f"{p}.timestamp"] = str(li.timestamp)
        entries[f"{p}.file_count"] = str(li.file_count)
        entries[f"{p}.disk_bytes"] = str(li.disk_bytes)
        entries[f"{p}.keys_added"] = str(li.keys_added)
        entries[f"{p}.keys_modified"] = str(li.keys_modified)
        entries[f"{p}.keys_deleted"] = str(li.keys_deleted)
    return entries


def _entries_to_meta(entries: dict[str, str]) -> tuple[list[LayerInfo], int, float]:
    """Deserialize OrdinalPGZ entries → (layers_info, total_commits, created)."""
    total_commits = int(entries.get("_total_commits", "0"))
    created = float(entries.get("_created", "0"))
    layer_count = int(entries.get("_layer_count", "0"))
    layers_info: list[LayerInfo] = []
    for i in range(layer_count):
        p = str(i)
        layers_info.append(LayerInfo(
            index=i,
            timestamp=float(entries.get(f"{p}.timestamp", "0")),
            file_count=int(entries.get(f"{p}.file_count", "0")),
            disk_bytes=int(entries.get(f"{p}.disk_bytes", "0")),
            keys_added=int(entries.get(f"{p}.keys_added", "0")),
            keys_modified=int(entries.get(f"{p}.keys_modified", "0")),
            keys_deleted=int(entries.get(f"{p}.keys_deleted", "0")),
        ))
    return layers_info, total_commits, created


class History:
    """Append-only timeline of indexed filesystem states.

    Each commit appends an immutable delta layer. Time travel reads
    layers up to a given point. Restore writes a reverse delta — history
    stays append-only. Trim squashes old layers to bound storage.

    Metadata is persisted in {prefix}.meta.pgz (OrdinalPGZ) and updated
    on every commit/trim. layers() reads metadata instantly without
    scanning layer files.
    """

    def __init__(self, directory: Path, prefix: str, max_layers: int = 42):
        self._layers = LayeredTexts(directory, prefix, max_layers=max_layers)
        self._dir = directory
        self._prefix = prefix
        self._max_layers = max_layers
        # Cached metadata — loaded lazily
        self._meta_loaded = False
        self._layers_info: list[LayerInfo] = []
        self._total_commits: int = 0
        self._created: float = 0.0

    @property
    def _meta_path(self) -> Path:
        return self._dir / f"{self._prefix}.meta.pgz"

    # ── Metadata persistence ──

    def _load_meta(self):
        """Load metadata from disk if not already cached."""
        if self._meta_loaded:
            return
        self._meta_loaded = True
        if not self._meta_path.exists():
            return
        try:
            entries = ordinal_pgz_read(self._meta_path)
            self._layers_info, self._total_commits, self._created = _entries_to_meta(entries)
        except Exception:
            # Corrupted meta — will be rebuilt on next commit
            self._meta_path.unlink(missing_ok=True)

    def _save_meta(self):
        """Persist current metadata to disk."""
        self._dir.mkdir(parents=True, exist_ok=True)
        entries = _meta_to_entries(self._layers_info, self._total_commits, self._created)
        ordinal_pgz_write(self._meta_path, entries)

    def _record_layer(self, layer_index: int, keys_added: int, keys_modified: int,
                      keys_deleted: int, file_count: int):
        """Record metadata for a newly written layer."""
        path = self._layers._layer_path(layer_index)
        disk_bytes = path.stat().st_size if path.exists() else 0
        info = LayerInfo(
            index=layer_index,
            timestamp=_time.time(),
            file_count=file_count,
            disk_bytes=disk_bytes,
            keys_added=keys_added,
            keys_modified=keys_modified,
            keys_deleted=keys_deleted,
        )
        # Ensure list is long enough
        while len(self._layers_info) <= layer_index:
            self._layers_info.append(None)  # type: ignore[arg-type]
        self._layers_info[layer_index] = info
        self._total_commits += 1
        self._save_meta()

    # ── Write ──

    def commit(self, changed: dict[str, str], deleted: set[str] | None = None):
        """Append a new delta layer. Like a git commit — immutable once written.

        Updates metadata with add/modify/delete counts.
        """
        if not changed and not deleted:
            return
        self._load_meta()

        layer_index = self._layers.layer_count()

        # Classify changes against current state
        current_keys = set()
        if layer_index > 0:
            # Fast: read headers of all layers to get current key set
            for path in self._layers.layer_paths():
                layer_keys = ordinal_pgz_header_keys(path)
                current_keys |= layer_keys
            # Remove tombstoned keys from current
            # (header_keys includes tombstones — check meta for accuracy)
            # Simpler: just use the key set from current()
            # But that's expensive. For metadata accuracy, approximate:
            # keys in changed that are also in current = modified, rest = added
            pass

        deleted_set = deleted or set()
        keys_added = len({k for k in changed if k not in current_keys})
        keys_modified = len({k for k in changed if k in current_keys})
        keys_deleted = len(deleted_set & current_keys)
        file_count = len(changed) + len(deleted_set)

        # Write the delta
        self._layers.write_delta(changed, deleted)

        # If auto-trim happened, rebuild metadata from disk
        actual_count = self._layers.layer_count()
        if actual_count < layer_index + 1:
            # Trim occurred — rebuild meta
            self._rebuild_meta()
        else:
            self._record_layer(layer_index, keys_added, keys_modified, keys_deleted, file_count)

    def commit_base(self, entries: dict[str, str]):
        """Write a full base layer (layer 0). Clears all history."""
        self._layers.write_base(entries)
        self._meta_loaded = True
        self._created = _time.time()
        self._layers_info = []
        # _record_layer increments _total_commits
        self._record_layer(0, keys_added=len(entries), keys_modified=0,
                           keys_deleted=0, file_count=len(entries))

    # ── Read: current state ──

    def current(self) -> dict[str, str]:
        """Merged latest state across all layers."""
        return self._layers.read()

    # ── Read: time travel ──

    def at(self, layer: int) -> dict[str, str]:
        """State at a given layer — merge layers 0..layer (inclusive).

        layer=0 is the base. layer=N is the state after N deltas.
        """
        paths = self._layers.layer_paths()
        if not paths or layer < 0:
            return {}
        end = min(layer + 1, len(paths))
        result: dict[str, str] = {}
        seen: set[str] = set()
        for path in reversed(paths[:end]):
            layer_data = ordinal_pgz_read(path)
            for name, text in layer_data.items():
                if name not in seen:
                    seen.add(name)
                    if text:
                        result[name] = text
        return result

    def file_at(self, name: str, layer: int) -> str | None:
        """Single file's content at a given layer. None if not present."""
        paths = self._layers.layer_paths()
        if not paths or layer < 0:
            return None
        end = min(layer + 1, len(paths))
        for path in reversed(paths[:end]):
            layer_data = ordinal_pgz_read(path)
            if name in layer_data:
                text = layer_data[name]
                return text if text else None
        return None

    # ── Diff ──

    def diff(self, from_layer: int, to_layer: int) -> Diff:
        """What changed between two layer states.

        Compares the full merged state at from_layer vs to_layer.
        """
        old_state = self.at(from_layer)
        new_state = self.at(to_layer)

        added: dict[str, str] = {}
        modified: dict[str, tuple[str, str]] = {}
        deleted: dict[str, str] = {}

        all_keys = set(old_state) | set(new_state)
        for key in all_keys:
            in_old = key in old_state
            in_new = key in new_state
            if in_new and not in_old:
                added[key] = new_state[key]
            elif in_old and not in_new:
                deleted[key] = old_state[key]
            elif old_state[key] != new_state[key]:
                modified[key] = (old_state[key], new_state[key])

        return Diff(
            from_layer=from_layer,
            to_layer=to_layer,
            added=added,
            modified=modified,
            deleted=deleted,
        )

    def diff_file(self, name: str, from_layer: int, to_layer: int) -> FileDiff:
        """Diff a single file between two layer states."""
        old_text = self.file_at(name, from_layer)
        new_text = self.file_at(name, to_layer)

        if old_text is None and new_text is None:
            return FileDiff(name=name, status="unchanged")
        if old_text is None:
            return FileDiff(name=name, status="added", new_text=new_text)
        if new_text is None:
            return FileDiff(name=name, status="deleted", old_text=old_text)
        if old_text != new_text:
            return FileDiff(name=name, status="modified", old_text=old_text, new_text=new_text)
        return FileDiff(name=name, status="unchanged", old_text=old_text, new_text=new_text)

    # ── Restore ──

    def restore(self, layer: int):
        """Restore full state to a given layer.

        Non-destructive: computes a reverse delta between current and
        the target layer, then appends it as a new commit. History
        stays append-only — you can undo a restore by restoring again.
        """
        target = self.at(layer)
        now = self.current()

        changed: dict[str, str] = {}
        deleted: set[str] = set()

        all_keys = set(target) | set(now)
        for key in all_keys:
            in_target = key in target
            in_now = key in now
            if in_target and not in_now:
                changed[key] = target[key]
            elif in_now and not in_target:
                deleted.add(key)
            elif target[key] != now[key]:
                changed[key] = target[key]

        if changed or deleted:
            self.commit(changed, deleted)

    def restore_file(self, name: str, layer: int):
        """Restore a single file to its state at a given layer.

        If the file existed at that layer, writes its old content.
        If it didn't exist, tombstones it (deletes from current state).
        """
        target_text = self.file_at(name, layer)
        if target_text is not None:
            self.commit({name: target_text})
        else:
            self.commit({}, deleted={name})

    # ── Layer inspection ──

    def layers(self) -> list[LayerInfo]:
        """Layer metadata from persisted meta file. Instant — no layer scanning."""
        self._load_meta()
        return list(self._layers_info)

    @property
    def total_commits(self) -> int:
        """Total commits ever made (monotonic, survives trims)."""
        self._load_meta()
        return self._total_commits

    @property
    def created(self) -> float:
        """Timestamp when history was first created."""
        self._load_meta()
        return self._created

    def layer_count(self) -> int:
        return self._layers.layer_count()

    # ── Maintenance ──

    def trim(self, max_layers: int | None = None):
        """Squash oldest layers to keep count within limit.

        Rebuilds metadata after trim to reflect the new layer numbering.
        """
        target = max_layers or self._max_layers
        self._layers.trim(target)
        self._rebuild_meta()

    def compact(self):
        """Flatten all layers into a single base."""
        self._layers.compact()
        self._rebuild_meta()

    def remove_all(self):
        """Delete all history including metadata."""
        self._layers.remove_all()
        self._meta_path.unlink(missing_ok=True)
        self._meta_loaded = True
        self._layers_info = []
        self._total_commits = 0
        self._created = 0.0

    def _rebuild_meta(self):
        """Rebuild metadata by scanning layer files on disk.

        Called after trim/compact when layer numbering changes.
        Preserves total_commits and created from existing meta.
        """
        self._load_meta()
        old_total = self._total_commits
        old_created = self._created or _time.time()

        paths = self._layers.layer_paths()
        infos: list[LayerInfo] = []
        prev_keys: set[str] = set()

        for i, path in enumerate(paths):
            stat = path.stat()
            layer_data = ordinal_pgz_read(path)
            tombstones = {k for k, v in layer_data.items() if not v}
            live_keys = set(layer_data.keys()) - tombstones

            if i == 0:
                added = len(live_keys)
                modified = 0
                deleted = 0
            else:
                added = len(live_keys - prev_keys)
                modified = len(live_keys & prev_keys)
                deleted = len(tombstones & prev_keys)

            infos.append(LayerInfo(
                index=i,
                timestamp=stat.st_mtime,
                file_count=len(layer_data),
                disk_bytes=stat.st_size,
                keys_added=added,
                keys_modified=modified,
                keys_deleted=deleted,
            ))

            # Accumulate live keys
            for k, v in layer_data.items():
                if v:
                    prev_keys.add(k)
                else:
                    prev_keys.discard(k)

        self._layers_info = infos
        self._total_commits = old_total
        self._created = old_created
        self._meta_loaded = True
        self._save_meta()
