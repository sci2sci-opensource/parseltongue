"""Performance and correctness tests for PGZ formats.

Compares JsonPGZ vs OrdinalPGZ vs LayeredTexts with synthetic payloads.
Random texts with repeated blocks simulate real source file caching.
"""

from __future__ import annotations

import json
import random
import string
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ..inspect.history import Diff, FileDiff, History, LayerInfo
from ..inspect.pgz import (
    LayeredTexts,
    json_pgz_read,
    json_pgz_write,
    ordinal_pgz_decode,
    ordinal_pgz_header_keys,
    ordinal_pgz_read,
    ordinal_pgz_write,
    pgz_read,
    pgz_write,
)


# ── Synthetic data generators ──


def _random_text(length: int, seed: int = 0) -> str:
    """Generate random text of given length."""
    rng = random.Random(seed)
    return "".join(rng.choices(string.ascii_letters + string.digits + " \n", k=length))


def _make_corpus(
    num_files: int = 400,
    min_size: int = 500,
    max_size: int = 20_000,
    shared_block_size: int = 200,
    num_shared_blocks: int = 10,
    seed: int = 42,
) -> dict[str, str]:
    """Generate a synthetic file corpus.

    Some blocks are shared across files (simulates common imports,
    boilerplate, repeated patterns in real codebases).
    """
    rng = random.Random(seed)
    # Pre-generate shared blocks
    shared = [_random_text(shared_block_size, seed=seed + i) for i in range(num_shared_blocks)]

    corpus: dict[str, str] = {}
    for i in range(num_files):
        size = rng.randint(min_size, max_size)
        parts = []
        remaining = size
        while remaining > 0:
            # 30% chance of inserting a shared block
            if rng.random() < 0.3 and remaining >= shared_block_size:
                parts.append(rng.choice(shared))
                remaining -= shared_block_size
            else:
                chunk = min(remaining, rng.randint(100, 500))
                parts.append(_random_text(chunk, seed=seed + i * 1000 + remaining))
                remaining -= chunk
        name = f"src/{'sub/' if i % 3 == 0 else ''}file_{i:04d}.py"
        corpus[name] = "".join(parts)

    return corpus


def _mutate_corpus(
    corpus: dict[str, str],
    num_modify: int = 20,
    num_add: int = 5,
    num_delete: int = 5,
    seed: int = 99,
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Mutate a corpus: modify, add, delete files.

    Returns (new_corpus, changed_entries, deleted_keys).
    changed_entries includes both modified and added files.
    """
    rng = random.Random(seed)
    new_corpus = dict(corpus)
    changed: dict[str, str] = {}
    deleted: set[str] = set()

    # Modify existing
    keys = list(corpus.keys())
    for key in rng.sample(keys, min(num_modify, len(keys))):
        old = corpus[key]
        # Modify ~10% of the content
        pos = rng.randint(0, max(0, len(old) - 100))
        patch = _random_text(100, seed=rng.randint(0, 100000))
        new_text = old[:pos] + patch + old[pos + 100:]
        new_corpus[key] = new_text
        changed[key] = new_text

    # Add new
    next_id = len(corpus)
    for i in range(num_add):
        name = f"src/new/added_{next_id + i:04d}.py"
        text = _random_text(rng.randint(500, 5000), seed=rng.randint(0, 100000))
        new_corpus[name] = text
        changed[name] = text

    # Delete
    deletable = [k for k in keys if k not in changed]
    for key in rng.sample(deletable, min(num_delete, len(deletable))):
        del new_corpus[key]
        deleted.add(key)

    return new_corpus, changed, deleted


# ── Correctness tests ──


class TestOrdinalPGZCorrectness(unittest.TestCase):
    """Verify OrdinalPGZ round-trips correctly."""

    def test_round_trip_empty(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "test.texts.pgz"
            ordinal_pgz_write(p, {})
            result = ordinal_pgz_read(p)
            self.assertEqual(result, {})

    def test_round_trip_single(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "test.texts.pgz"
            entries = {"hello.py": "print('hello world')\n"}
            ordinal_pgz_write(p, entries)
            result = ordinal_pgz_read(p)
            self.assertEqual(result, entries)

    def test_round_trip_corpus(self):
        """400 files with shared blocks round-trip exactly."""
        corpus = _make_corpus()
        with TemporaryDirectory() as d:
            p = Path(d) / "test.texts.pgz"
            ordinal_pgz_write(p, corpus)
            result = ordinal_pgz_read(p)
            self.assertEqual(set(result.keys()), set(corpus.keys()))
            for key in corpus:
                self.assertEqual(result[key], corpus[key], f"Mismatch for {key}")

    def test_sorted_order(self):
        """Entries are stored sorted by key."""
        entries = {"z.py": "z", "a.py": "a", "m.py": "m"}
        with TemporaryDirectory() as d:
            p = Path(d) / "test.texts.pgz"
            ordinal_pgz_write(p, entries)
            result = ordinal_pgz_read(p)
            self.assertEqual(list(result.keys()), ["a.py", "m.py", "z.py"])

    def test_header_keys(self):
        """header_keys returns filenames without reading text block."""
        entries = {"a.py": "aaa", "b.py": "bbb", "c.py": "ccc"}
        with TemporaryDirectory() as d:
            p = Path(d) / "test.texts.pgz"
            ordinal_pgz_write(p, entries)
            keys = ordinal_pgz_header_keys(p)
            self.assertEqual(keys, {"a.py", "b.py", "c.py"})

    def test_unicode_content(self):
        entries = {"uni.py": "# café résumé naïve 日本語 🎉\nprint('ok')\n"}
        with TemporaryDirectory() as d:
            p = Path(d) / "test.texts.pgz"
            ordinal_pgz_write(p, entries)
            result = ordinal_pgz_read(p)
            self.assertEqual(result, entries)


class TestLayeredTextsCorrectness(unittest.TestCase):
    """Verify LayeredTexts delta logic."""

    def _make_layers(self, d: str, max_layers: int = 5) -> LayeredTexts:
        return LayeredTexts(Path(d), "test", max_layers=max_layers)

    def test_write_base_and_read(self):
        with TemporaryDirectory() as d:
            lt = self._make_layers(d)
            corpus = {"a.py": "aaa", "b.py": "bbb"}
            lt.write_base(corpus)
            self.assertEqual(lt.layer_count(), 1)
            self.assertEqual(lt.read(), corpus)

    def test_delta_add_modify(self):
        with TemporaryDirectory() as d:
            lt = self._make_layers(d)
            lt.write_base({"a.py": "aaa", "b.py": "bbb"})
            lt.write_delta({"b.py": "BBB", "c.py": "ccc"})
            result = lt.read()
            self.assertEqual(result, {"a.py": "aaa", "b.py": "BBB", "c.py": "ccc"})
            self.assertEqual(lt.layer_count(), 2)

    def test_delta_delete(self):
        with TemporaryDirectory() as d:
            lt = self._make_layers(d)
            lt.write_base({"a.py": "aaa", "b.py": "bbb", "c.py": "ccc"})
            lt.write_delta({}, deleted={"b.py"})
            result = lt.read()
            self.assertEqual(result, {"a.py": "aaa", "c.py": "ccc"})

    def test_delete_then_recreate(self):
        with TemporaryDirectory() as d:
            lt = self._make_layers(d)
            lt.write_base({"a.py": "v1"})
            lt.write_delta({}, deleted={"a.py"})
            lt.write_delta({"a.py": "v2"})
            self.assertEqual(lt.read(), {"a.py": "v2"})

    def test_trim_merges_oldest(self):
        with TemporaryDirectory() as d:
            lt = self._make_layers(d, max_layers=100)
            lt.write_base({"a.py": "v0", "b.py": "v0"})
            lt.write_delta({"a.py": "v1"})
            lt.write_delta({"a.py": "v2", "c.py": "new"})
            lt.write_delta({}, deleted={"b.py"})
            lt.write_delta({"d.py": "ddd"})
            self.assertEqual(lt.layer_count(), 5)

            expected = lt.read()
            lt.trim(3)
            self.assertEqual(lt.layer_count(), 3)
            self.assertEqual(lt.read(), expected)

    def test_compact_to_one(self):
        with TemporaryDirectory() as d:
            lt = self._make_layers(d, max_layers=100)
            lt.write_base({"a.py": "v0"})
            for i in range(10):
                lt.write_delta({"a.py": f"v{i+1}", f"new_{i}.py": f"text_{i}"})
            expected = lt.read()
            lt.compact()
            self.assertEqual(lt.layer_count(), 1)
            self.assertEqual(lt.read(), expected)

    def test_auto_trim(self):
        """write_delta auto-trims when exceeding max_layers."""
        with TemporaryDirectory() as d:
            lt = self._make_layers(d, max_layers=3)
            lt.write_base({"a.py": "v0"})
            lt.write_delta({"a.py": "v1"})
            lt.write_delta({"a.py": "v2"})
            # This 4th write exceeds max_layers=3, triggers auto-trim
            lt.write_delta({"a.py": "v3"})
            self.assertLessEqual(lt.layer_count(), 3)
            self.assertEqual(lt.read()["a.py"], "v3")

    def test_trim_with_corpus(self):
        """Trim preserves correctness with realistic corpus mutations."""
        corpus = _make_corpus(num_files=100, max_size=2000, seed=7)
        with TemporaryDirectory() as d:
            lt = self._make_layers(d, max_layers=100)
            lt.write_base(corpus)

            current = dict(corpus)
            for i in range(8):
                current, changed, deleted = _mutate_corpus(current, num_modify=10, num_add=2, num_delete=2, seed=i * 77)
                lt.write_delta(changed, deleted)

            expected = lt.read()
            lt.trim(3)
            actual = lt.read()
            self.assertEqual(set(actual.keys()), set(expected.keys()))
            for k in expected:
                self.assertEqual(actual[k], expected[k], f"Mismatch for {k} after trim")

    def test_remove_all(self):
        with TemporaryDirectory() as d:
            lt = self._make_layers(d)
            lt.write_base({"a.py": "aaa"})
            lt.write_delta({"b.py": "bbb"})
            lt.remove_all()
            self.assertEqual(lt.layer_count(), 0)
            self.assertEqual(lt.read(), {})

    def test_write_base_clears_existing(self):
        with TemporaryDirectory() as d:
            lt = self._make_layers(d)
            lt.write_base({"a.py": "v1"})
            lt.write_delta({"b.py": "bbb"})
            self.assertEqual(lt.layer_count(), 2)
            lt.write_base({"x.py": "xxx"})
            self.assertEqual(lt.layer_count(), 1)
            self.assertEqual(lt.read(), {"x.py": "xxx"})


# ── History tests ──


class TestHistoryCorrectness(unittest.TestCase):
    """Verify History: metadata, time travel, diff, restore."""

    def _make(self, d: str, max_layers: int = 42) -> History:
        return History(Path(d), "test", max_layers=max_layers)

    def test_commit_base_and_metadata(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "aaa", "b.py": "bbb"})
            self.assertEqual(h.layer_count(), 1)
            self.assertEqual(h.total_commits, 1)
            self.assertGreater(h.created, 0)

            infos = h.layers()
            self.assertEqual(len(infos), 1)
            self.assertEqual(infos[0].index, 0)
            self.assertEqual(infos[0].keys_added, 2)
            self.assertEqual(infos[0].file_count, 2)
            self.assertGreater(infos[0].disk_bytes, 0)

    def test_commit_delta_metadata(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0", "b.py": "v0"})
            h.commit({"a.py": "v1", "c.py": "new"}, deleted={"b.py"})
            self.assertEqual(h.layer_count(), 2)
            self.assertEqual(h.total_commits, 2)

            infos = h.layers()
            self.assertEqual(len(infos), 2)
            self.assertEqual(infos[1].keys_added, 1)      # c.py
            self.assertEqual(infos[1].keys_modified, 1)    # a.py
            self.assertEqual(infos[1].keys_deleted, 1)     # b.py

    def test_metadata_persists_across_instances(self):
        """Metadata survives creating a new History instance."""
        with TemporaryDirectory() as d:
            h1 = self._make(d)
            h1.commit_base({"a.py": "aaa"})
            h1.commit({"b.py": "bbb"})
            total = h1.total_commits
            created = h1.created

            # New instance, same path
            h2 = self._make(d)
            self.assertEqual(h2.total_commits, total)
            self.assertEqual(h2.created, created)
            self.assertEqual(len(h2.layers()), 2)
            self.assertEqual(h2.current(), {"a.py": "aaa", "b.py": "bbb"})

    def test_total_commits_survives_trim(self):
        with TemporaryDirectory() as d:
            h = self._make(d, max_layers=100)
            h.commit_base({"a.py": "v0"})
            for i in range(5):
                h.commit({"a.py": f"v{i+1}"})
            self.assertEqual(h.total_commits, 6)
            h.trim(2)
            self.assertEqual(h.total_commits, 6)  # monotonic
            self.assertEqual(h.layer_count(), 2)

    def test_time_travel_at(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0", "b.py": "v0"})
            h.commit({"a.py": "v1"})
            h.commit({"a.py": "v2", "c.py": "new"})
            h.commit({}, deleted={"b.py"})

            s0 = h.at(0)
            self.assertEqual(s0, {"a.py": "v0", "b.py": "v0"})

            s1 = h.at(1)
            self.assertEqual(s1, {"a.py": "v1", "b.py": "v0"})

            s2 = h.at(2)
            self.assertEqual(s2, {"a.py": "v2", "b.py": "v0", "c.py": "new"})

            s3 = h.at(3)
            self.assertEqual(s3, {"a.py": "v2", "c.py": "new"})
            self.assertEqual(h.current(), s3)

    def test_file_at(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0"})
            h.commit({"a.py": "v1"})
            h.commit({"a.py": "v2"})

            self.assertEqual(h.file_at("a.py", 0), "v0")
            self.assertEqual(h.file_at("a.py", 1), "v1")
            self.assertEqual(h.file_at("a.py", 2), "v2")
            self.assertIsNone(h.file_at("nonexistent.py", 2))

    def test_file_at_with_deletion(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0"})
            h.commit({}, deleted={"a.py"})
            h.commit({"a.py": "v2"})

            self.assertEqual(h.file_at("a.py", 0), "v0")
            self.assertIsNone(h.file_at("a.py", 1))
            self.assertEqual(h.file_at("a.py", 2), "v2")

    def test_diff_whole_state(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0", "b.py": "v0"})
            h.commit({"a.py": "v1", "c.py": "new"}, deleted={"b.py"})

            d01 = h.diff(0, 1)
            self.assertEqual(d01.added, {"c.py": "new"})
            self.assertEqual(d01.modified, {"a.py": ("v0", "v1")})
            self.assertEqual(d01.deleted, {"b.py": "v0"})
            self.assertEqual(d01.changed_count, 3)
            self.assertEqual(d01.changed_files, {"a.py", "b.py", "c.py"})

    def test_diff_file(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0"})
            h.commit({"a.py": "v1"})

            fd = h.diff_file("a.py", 0, 1)
            self.assertEqual(fd.status, "modified")
            self.assertEqual(fd.old_text, "v0")
            self.assertEqual(fd.new_text, "v1")

    def test_diff_file_added(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({})
            h.commit({"a.py": "new"})

            fd = h.diff_file("a.py", 0, 1)
            self.assertEqual(fd.status, "added")
            self.assertEqual(fd.new_text, "new")

    def test_diff_file_deleted(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "old"})
            h.commit({}, deleted={"a.py"})

            fd = h.diff_file("a.py", 0, 1)
            self.assertEqual(fd.status, "deleted")
            self.assertEqual(fd.old_text, "old")

    def test_diff_file_unchanged(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "same"})
            h.commit({"b.py": "other"})

            fd = h.diff_file("a.py", 0, 1)
            self.assertEqual(fd.status, "unchanged")

    def test_restore_full_state(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0", "b.py": "v0"})
            h.commit({"a.py": "v1", "c.py": "new"}, deleted={"b.py"})
            h.commit({"a.py": "v2"})

            # Restore to layer 0
            h.restore(0)
            self.assertEqual(h.current(), {"a.py": "v0", "b.py": "v0"})

    def test_restore_is_nondestructive(self):
        """Restore appends a delta — history length increases."""
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0"})
            h.commit({"a.py": "v1"})
            count_before = h.layer_count()
            h.restore(0)
            self.assertEqual(h.layer_count(), count_before + 1)
            # Can still see the old states
            self.assertEqual(h.file_at("a.py", 0), "v0")
            self.assertEqual(h.file_at("a.py", 1), "v1")

    def test_restore_file_single(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0", "b.py": "v0"})
            h.commit({"a.py": "v1", "b.py": "v1"})

            h.restore_file("a.py", 0)
            cur = h.current()
            self.assertEqual(cur["a.py"], "v0")  # restored
            self.assertEqual(cur["b.py"], "v1")  # untouched

    def test_restore_file_deleted(self):
        """Restore a file that didn't exist at target layer → tombstone."""
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({})
            h.commit({"a.py": "new"})

            h.restore_file("a.py", 0)
            self.assertNotIn("a.py", h.current())

    def test_empty_commit_is_noop(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0"})
            count = h.layer_count()
            h.commit({})
            self.assertEqual(h.layer_count(), count)

    def test_remove_all_clears_metadata(self):
        with TemporaryDirectory() as d:
            h = self._make(d)
            h.commit_base({"a.py": "v0"})
            h.commit({"a.py": "v1"})
            h.remove_all()
            self.assertEqual(h.layer_count(), 0)
            self.assertEqual(h.total_commits, 0)
            self.assertEqual(h.layers(), [])

    def test_history_with_corpus(self):
        """Full lifecycle with synthetic corpus."""
        corpus = _make_corpus(num_files=50, max_size=2000, seed=11)
        with TemporaryDirectory() as d:
            h = self._make(d, max_layers=10)
            h.commit_base(corpus)

            states = [dict(corpus)]
            current = dict(corpus)
            for i in range(6):
                current, changed, deleted = _mutate_corpus(
                    current, num_modify=5, num_add=2, num_delete=1, seed=i * 13,
                )
                h.commit(changed, deleted)
                states.append(dict(current))

            # Verify all historical states
            for layer_idx, expected in enumerate(states):
                actual = h.at(layer_idx)
                self.assertEqual(set(actual.keys()), set(expected.keys()),
                                 f"Key mismatch at layer {layer_idx}")
                for k in expected:
                    self.assertEqual(actual[k], expected[k],
                                     f"Content mismatch for {k} at layer {layer_idx}")

            # Diff between first and last
            d_full = h.diff(0, len(states) - 1)
            self.assertGreater(d_full.changed_count, 0)

            # Trim and verify current still correct
            h.trim(3)
            self.assertEqual(h.current(), states[-1])
            self.assertGreater(h.total_commits, h.layer_count())


# ── Performance tests ──


class TestPGZPerformance(unittest.TestCase):
    """Synthetic benchmarks: JsonPGZ vs OrdinalPGZ vs LayeredTexts.

    Not strict timing assertions — prints results for human review.
    Asserts correctness; timing is informational.
    """

    @classmethod
    def setUpClass(cls):
        cls.corpus = _make_corpus(num_files=400, min_size=500, max_size=20_000, seed=42)
        cls.corpus_json = json.dumps(cls.corpus, separators=(",", ":")).encode()
        total_bytes = sum(len(v.encode()) for v in cls.corpus.values())
        print(f"\n--- PGZ Performance Test ---")
        print(f"Corpus: {len(cls.corpus)} files, {total_bytes:,} bytes uncompressed text")
        print(f"JSON payload: {len(cls.corpus_json):,} bytes")

    def test_01_json_pgz_write_read(self):
        """Baseline: JsonPGZ full write + full read."""
        with TemporaryDirectory() as d:
            p = Path(d) / "test.idx.pgz"
            data = {"file_texts": self.corpus, "other_stuff": {"key": "value"}}

            t0 = time.perf_counter()
            json_pgz_write(p, data)
            t_write = time.perf_counter() - t0

            t0 = time.perf_counter()
            result = json_pgz_read(p)
            t_read = time.perf_counter() - t0

            size = p.stat().st_size
            print(f"\nJsonPGZ:  write={t_write*1000:.1f}ms  read={t_read*1000:.1f}ms  disk={size:,}B")
            self.assertEqual(result["file_texts"], self.corpus)

    def test_02_ordinal_pgz_write_read(self):
        """OrdinalPGZ full write + full read."""
        with TemporaryDirectory() as d:
            p = Path(d) / "test.texts.pgz"

            t0 = time.perf_counter()
            ordinal_pgz_write(p, self.corpus)
            t_write = time.perf_counter() - t0

            t0 = time.perf_counter()
            result = ordinal_pgz_read(p)
            t_read = time.perf_counter() - t0

            size = p.stat().st_size
            print(f"\nOrdinalPGZ:  write={t_write*1000:.1f}ms  read={t_read*1000:.1f}ms  disk={size:,}B")
            self.assertEqual(result, self.corpus)

    def test_03_ordinal_header_only(self):
        """OrdinalPGZ header-only read (keys, no text)."""
        with TemporaryDirectory() as d:
            p = Path(d) / "test.texts.pgz"
            ordinal_pgz_write(p, self.corpus)

            t0 = time.perf_counter()
            keys = ordinal_pgz_header_keys(p)
            t_read = time.perf_counter() - t0

            print(f"\nOrdinalPGZ header-only:  read={t_read*1000:.1f}ms  keys={len(keys)}")
            self.assertEqual(keys, set(self.corpus.keys()))

    def test_04_layered_base_write_read(self):
        """LayeredTexts base layer write + read."""
        with TemporaryDirectory() as d:
            lt = LayeredTexts(Path(d), "bench", max_layers=10)

            t0 = time.perf_counter()
            lt.write_base(self.corpus)
            t_write = time.perf_counter() - t0

            t0 = time.perf_counter()
            result = lt.read()
            t_read = time.perf_counter() - t0

            size = lt._layer_path(0).stat().st_size
            print(f"\nLayered base:  write={t_write*1000:.1f}ms  read={t_read*1000:.1f}ms  disk={size:,}B")
            self.assertEqual(result, self.corpus)

    def test_05_layered_delta_writes(self):
        """LayeredTexts: base + 5 deltas, each modifying ~5% of files."""
        with TemporaryDirectory() as d:
            lt = LayeredTexts(Path(d), "bench", max_layers=10)
            lt.write_base(self.corpus)

            current = dict(self.corpus)
            delta_times = []
            for i in range(5):
                current, changed, deleted = _mutate_corpus(
                    current, num_modify=20, num_add=5, num_delete=3, seed=i * 31,
                )
                t0 = time.perf_counter()
                lt.write_delta(changed, deleted)
                delta_times.append(time.perf_counter() - t0)

            self.assertEqual(lt.layer_count(), 6)
            total_size = sum(p.stat().st_size for p in lt.layer_paths())
            avg_delta = sum(delta_times) / len(delta_times) * 1000

            t0 = time.perf_counter()
            result = lt.read()
            t_read = time.perf_counter() - t0

            print(f"\nLayered 1+5 deltas:")
            print(f"  delta avg={avg_delta:.1f}ms  read={t_read*1000:.1f}ms  total_disk={total_size:,}B")
            print(f"  layers={lt.layer_count()}")

            self.assertEqual(set(result.keys()), set(current.keys()))
            for k in current:
                self.assertEqual(result[k], current[k], f"Mismatch for {k}")

    def test_06_layered_trim(self):
        """LayeredTexts: 10 deltas then trim to 3."""
        with TemporaryDirectory() as d:
            lt = LayeredTexts(Path(d), "bench", max_layers=100)
            lt.write_base(self.corpus)

            current = dict(self.corpus)
            for i in range(10):
                current, changed, deleted = _mutate_corpus(
                    current, num_modify=15, num_add=3, num_delete=2, seed=i * 17,
                )
                lt.write_delta(changed, deleted)

            self.assertEqual(lt.layer_count(), 11)
            size_before = sum(p.stat().st_size for p in lt.layer_paths())

            t0 = time.perf_counter()
            lt.trim(3)
            t_trim = time.perf_counter() - t0

            size_after = sum(p.stat().st_size for p in lt.layer_paths())

            t0 = time.perf_counter()
            result = lt.read()
            t_read = time.perf_counter() - t0

            print(f"\nLayered trim 11→3:")
            print(f"  trim={t_trim*1000:.1f}ms  read_after={t_read*1000:.1f}ms")
            print(f"  disk: {size_before:,}B → {size_after:,}B")

            self.assertEqual(lt.layer_count(), 3)
            self.assertEqual(set(result.keys()), set(current.keys()))
            for k in current:
                self.assertEqual(result[k], current[k], f"Mismatch for {k}")

    def test_07_layered_compact(self):
        """LayeredTexts: 8 deltas then compact to 1."""
        with TemporaryDirectory() as d:
            lt = LayeredTexts(Path(d), "bench", max_layers=100)
            lt.write_base(self.corpus)

            current = dict(self.corpus)
            for i in range(8):
                current, changed, deleted = _mutate_corpus(
                    current, num_modify=10, num_add=2, num_delete=2, seed=i * 53,
                )
                lt.write_delta(changed, deleted)

            t0 = time.perf_counter()
            lt.compact()
            t_compact = time.perf_counter() - t0

            size = lt._layer_path(0).stat().st_size

            t0 = time.perf_counter()
            result = lt.read()
            t_read = time.perf_counter() - t0

            print(f"\nLayered compact 9→1:")
            print(f"  compact={t_compact*1000:.1f}ms  read={t_read*1000:.1f}ms  disk={size:,}B")

            self.assertEqual(lt.layer_count(), 1)
            self.assertEqual(set(result.keys()), set(current.keys()))

    def test_08_json_vs_ordinal_vs_layered_comparison(self):
        """Side-by-side: write base + 3 deltas + read-all for each approach."""
        mutations = []
        current = dict(self.corpus)
        for i in range(3):
            current, changed, deleted = _mutate_corpus(
                current, num_modify=20, num_add=5, num_delete=3, seed=i * 41,
            )
            mutations.append((changed, deleted))

        with TemporaryDirectory() as d:
            # JsonPGZ: rewrite everything each time
            jp = Path(d) / "json.idx.pgz"
            json_writes = []
            json_corpus = dict(self.corpus)
            for changed, deleted in mutations:
                json_corpus.update(changed)
                for k in deleted:
                    json_corpus.pop(k, None)
                t0 = time.perf_counter()
                json_pgz_write(jp, {"file_texts": json_corpus})
                json_writes.append(time.perf_counter() - t0)

            t0 = time.perf_counter()
            json_result = json_pgz_read(jp)["file_texts"]
            json_read = time.perf_counter() - t0
            json_size = jp.stat().st_size

            # OrdinalPGZ: rewrite everything each time
            op = Path(d) / "ordinal.texts.pgz"
            ord_writes = []
            ord_corpus = dict(self.corpus)
            for changed, deleted in mutations:
                ord_corpus.update(changed)
                for k in deleted:
                    ord_corpus.pop(k, None)
                t0 = time.perf_counter()
                ordinal_pgz_write(op, ord_corpus)
                ord_writes.append(time.perf_counter() - t0)

            t0 = time.perf_counter()
            ord_result = ordinal_pgz_read(op)
            ord_read = time.perf_counter() - t0
            ord_size = op.stat().st_size

            # LayeredTexts: base + deltas
            lt = LayeredTexts(Path(d), "layered", max_layers=10)
            lt.write_base(self.corpus)
            layer_writes = []
            for changed, deleted in mutations:
                t0 = time.perf_counter()
                lt.write_delta(changed, deleted)
                layer_writes.append(time.perf_counter() - t0)

            t0 = time.perf_counter()
            layer_result = lt.read()
            layer_read = time.perf_counter() - t0
            layer_size = sum(p.stat().st_size for p in lt.layer_paths())

            print(f"\n--- Comparison: base + 3 incremental updates ---")
            print(f"{'':20s} {'avg write':>12s} {'read':>10s} {'disk':>12s}")
            print(f"{'JsonPGZ':20s} {sum(json_writes)/3*1000:>10.1f}ms {json_read*1000:>8.1f}ms {json_size:>10,}B")
            print(f"{'OrdinalPGZ':20s} {sum(ord_writes)/3*1000:>10.1f}ms {ord_read*1000:>8.1f}ms {ord_size:>10,}B")
            print(f"{'LayeredTexts':20s} {sum(layer_writes)/3*1000:>10.1f}ms {layer_read*1000:>8.1f}ms {layer_size:>10,}B")

            # Correctness: all three must agree
            self.assertEqual(set(json_result.keys()), set(current.keys()))
            self.assertEqual(set(ord_result.keys()), set(current.keys()))
            self.assertEqual(set(layer_result.keys()), set(current.keys()))
            for k in current:
                self.assertEqual(json_result[k], current[k])
                self.assertEqual(ord_result[k], current[k])
                self.assertEqual(layer_result[k], current[k])


if __name__ == "__main__":
    unittest.main()
