"""Background reindex must be cheap and serialized.

A no-change reindex pass must not touch the disk cache: the multi-hundred-MB
.idx.pgz was being decompressed and JSON-parsed twice per background tick
(once in SearchStore.reindex for old_hashes, once in _update_index to rebuild
an index that hadn't changed), producing a multi-GB RSS sawtooth and a pinned
core at the default 2s interval. These tests pin the warm path to zero disk
loads and the reindex lock to mutual exclusion.
"""

import os
import shutil
import threading
import unittest
from unittest.mock import patch

from ..inspect.search import Search
from ..inspect.store import SearchStore, Store

TEST_DIR = "/tmp/reindex-churn-test"


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class ReindexChurnBase(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DIR):
            shutil.rmtree(TEST_DIR)
        os.makedirs(TEST_DIR)
        _write(
            os.path.join(TEST_DIR, "pg.toml"),
            '[detect]\nlanguages = ["python"]\n[index]\nextensions = [".py"]\n',
        )
        _write(os.path.join(TEST_DIR, ".pgignore"), "")
        _write(os.path.join(TEST_DIR, "alpha.py"), "ALPHA = 1\n")
        _write(os.path.join(TEST_DIR, "beta.py"), "BETA = 2\n")

    def tearDown(self):
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def _make_search(self) -> Search:
        store = Store(os.path.join(TEST_DIR, ".bench"))
        return Search(SearchStore(store=store, path=TEST_DIR))


class TestNoChangeReindexTouchesNoDisk(ReindexChurnBase):
    def test_warm_no_change_pass_never_loads_cache(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            store = search._store._store
            with (
                patch.object(store, "load_index", wraps=store.load_index) as load_index,
                patch.object(store, "load_texts", wraps=store.load_texts) as load_texts,
            ):
                count = search.reindex()
        self.assertEqual(count, 0)
        load_index.assert_not_called()
        load_texts.assert_not_called()

    def test_no_change_pass_keeps_live_index_object(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            live_index = search._index
            search.reindex()
        self.assertIs(search._index, live_index)

    def test_changed_file_is_still_picked_up(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            self.assertEqual(search.query("GAMMA")["total_lines"], 0)
            _write(os.path.join(TEST_DIR, "alpha.py"), "ALPHA = 1\nGAMMA = 3\n")
            count = search.reindex()
            self.assertEqual(count, 1)
            self.assertGreater(search.query("GAMMA")["total_lines"], 0)

    def test_changed_pass_never_parses_main_cache(self):
        # A 1-file edit must mutate the live index, not rebuild it from the
        # disk cache (historically: LayeredTexts merge + full .idx.pgz parse
        # in _update_index, plus a second parse + rewrite in
        # save_search_index).
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            _write(os.path.join(TEST_DIR, "alpha.py"), "ALPHA = 1\nGAMMA = 3\n")
            store = search._store._store
            with (
                patch.object(store, "load_index", wraps=store.load_index) as load_index,
                patch.object(store, "load_texts", wraps=store.load_texts) as load_texts,
            ):
                count = search.reindex()
        self.assertEqual(count, 1)
        load_index.assert_not_called()
        load_texts.assert_not_called()

    def test_new_and_deleted_files_are_still_picked_up(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            _write(os.path.join(TEST_DIR, "gamma.py"), "DELTA = 4\n")
            os.unlink(os.path.join(TEST_DIR, "beta.py"))
            search.reindex()
            self.assertGreater(search.query("DELTA")["total_lines"], 0)
            self.assertEqual(search.query("BETA")["total_lines"], 0)

    def test_changes_searchable_before_cache_save(self):
        # _sync must run before the heavy disk save — search freshness must
        # never wait minutes on cache durability.
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            _write(os.path.join(TEST_DIR, "alpha.py"), "ALPHA = 1\nGAMMA = 3\n")

            hits_at_save = {}
            orig_save = search._store._save_cache

            def spying_save(*args, **kwargs):
                hits_at_save["gamma"] = search.query("GAMMA")["total_lines"]
                return orig_save(*args, **kwargs)

            with patch.object(search._store, "_save_cache", side_effect=spying_save):
                search.reindex()
        self.assertGreater(hits_at_save.get("gamma", 0), 0)

    def test_cold_reindex_after_restart_falls_back_to_cache(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            # Fresh Search over the same store dir — simulates daemon restart;
            # load_index repopulates hashes, so reindex sees no changes.
            reborn = self._make_search()
            self.assertEqual(reborn.reindex(), 0)
            self.assertGreater(reborn.query("ALPHA")["total_lines"], 0)


class TestSearchIndexSplitCache(ReindexChurnBase):
    def test_search_index_saved_to_own_file(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            store = search._store._store
        self.assertTrue(store._search_index_cache_path(TEST_DIR).exists())
        # The main cache no longer carries the inline copy
        self.assertNotIn("search_index", store.load_index(TEST_DIR))

    def test_restart_restores_search_index_from_six_file(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            reborn = self._make_search()
        self.assertGreater(reborn.query("ALPHA")["total_lines"], 0)

    def test_legacy_inline_search_index_still_loads(self):
        from ..inspect.pgz import json_pgz_write

        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            store = search._store._store
            # Rewrite the caches into the pre-split layout: search_index
            # inline in .idx.pgz, no .six.pgz.
            sidx_data = store.load_search_index_data(TEST_DIR)
            self.assertIsNotNone(sidx_data)
            cached = store.load_index(TEST_DIR)
            cached["search_index"] = sidx_data
            json_pgz_write(store._index_cache_path(TEST_DIR), cached)
            store._search_index_cache_path(TEST_DIR).unlink()

            reborn_store = SearchStore(store=Store(os.path.join(TEST_DIR, ".bench")), path=TEST_DIR)
            doc_index = reborn_store.load_index()
            self.assertIsNotNone(reborn_store.load_search_index(doc_index))


class TestDeferredSave(ReindexChurnBase):
    def test_defer_save_skips_disk_until_flush(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            store = search._store._store
            _write(os.path.join(TEST_DIR, "alpha.py"), "ALPHA = 1\nGAMMA = 3\n")
            idx_mtime = store._index_cache_path(TEST_DIR).stat().st_mtime_ns

            count = search.reindex(defer_save=True)
            self.assertEqual(count, 1)
            # Searchable immediately, but nothing written yet
            self.assertGreater(search.query("GAMMA")["total_lines"], 0)
            self.assertTrue(search.save_pending())
            self.assertEqual(store._index_cache_path(TEST_DIR).stat().st_mtime_ns, idx_mtime)

            search.flush_saves()
            self.assertFalse(search.save_pending())
            self.assertGreater(store._index_cache_path(TEST_DIR).stat().st_mtime_ns, idx_mtime)

    def test_deferred_passes_accumulate_into_one_flush(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            _write(os.path.join(TEST_DIR, "alpha.py"), "ALPHA = 1\nGAMMA = 3\n")
            self.assertEqual(search.reindex(defer_save=True), 1)
            _write(os.path.join(TEST_DIR, "beta.py"), "BETA = 2\nDELTA = 4\n")
            self.assertEqual(search.reindex(defer_save=True), 1)
            search.flush_saves()
            # Both batches survive a restart — History got both texts
            reborn = self._make_search()
            self.assertGreater(reborn.query("GAMMA")["total_lines"], 0)
            self.assertGreater(reborn.query("DELTA")["total_lines"], 0)

    def test_deferred_delete_then_flush_survives_restart(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)
            os.unlink(os.path.join(TEST_DIR, "beta.py"))
            search.reindex(defer_save=True)
            self.assertEqual(search.query("BETA")["total_lines"], 0)
            search.flush_saves()
            reborn = self._make_search()
            self.assertEqual(reborn.query("BETA")["total_lines"], 0)
            self.assertGreater(reborn.query("ALPHA")["total_lines"], 0)


class TestReindexLock(ReindexChurnBase):
    def test_reindex_busy_while_pass_runs(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)

            entered = threading.Event()
            release = threading.Event()
            original = search._store.reindex

            def slow_reindex(*args, **kwargs):
                entered.set()
                release.wait(timeout=5)
                return original(*args, **kwargs)

            self.assertFalse(search.reindex_busy())
            with patch.object(search._store, "reindex", side_effect=slow_reindex):
                t = threading.Thread(target=search.reindex, daemon=True)
                t.start()
                self.assertTrue(entered.wait(timeout=5))
                self.assertTrue(search.reindex_busy())
                release.set()
                t.join(timeout=5)
            self.assertFalse(search.reindex_busy())

    def test_concurrent_reindexes_serialize(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)

            active = 0
            max_active = 0
            guard = threading.Lock()
            original = search._store.reindex

            def tracking_reindex(*args, **kwargs):
                nonlocal active, max_active
                with guard:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    return original(*args, **kwargs)
                finally:
                    with guard:
                        active -= 1

            with patch.object(search._store, "reindex", side_effect=tracking_reindex):
                threads = [threading.Thread(target=search.reindex, daemon=True) for _ in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=10)
        self.assertEqual(max_active, 1)


if __name__ == "__main__":
    unittest.main()
