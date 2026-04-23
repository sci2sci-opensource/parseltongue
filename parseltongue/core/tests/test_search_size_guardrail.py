"""Size guardrail — files over max_file_size_bytes must be skipped
and surfaced, unless explicitly allowlisted via [index].allow_large.

Every indexed file must be classified: either ignored (.pgignore),
under the size threshold, or explicitly permitted. The guardrail
forbids silent indexing of oversized files.
"""

import logging
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from ..inspect.search import Search
from ..inspect.store import SearchStore, Store

TEST_DIR = "/tmp/search-size-guardrail-test"


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class SizeGuardrailTest(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DIR):
            shutil.rmtree(TEST_DIR)
        os.makedirs(TEST_DIR)

    def tearDown(self):
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def _write_pg_toml(self, max_bytes: int, allow_large: list[str] | None = None):
        allow = allow_large or []
        allow_repr = "[" + ", ".join(f'"{g}"' for g in allow) + "]"
        _write(
            os.path.join(TEST_DIR, "pg.toml"),
            "[detect]\nlanguages = [\"python\"]\n"
            "[index]\n"
            "extensions = [\".py\", \".md\", \".txt\"]\n"
            f"max_file_size_bytes = {max_bytes}\n"
            f"allow_large = {allow_repr}\n",
        )
        _write(os.path.join(TEST_DIR, ".pgignore"), "")

    def _make_search(self) -> Search:
        store = Store(os.path.join(TEST_DIR, ".bench"))
        return Search(SearchStore(store=store, path=TEST_DIR))

    def test_oversized_file_is_skipped_and_reported(self):
        self._write_pg_toml(max_bytes=1024)  # 1 KB threshold
        _write(os.path.join(TEST_DIR, "small.py"), "TINY = 1\n")
        _write(os.path.join(TEST_DIR, "big.py"), "X = '" + "z" * 4096 + "'\n")

        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            with self.assertLogs("parseltongue.store", level="ERROR") as cm:
                search.index_dir(TEST_DIR)

        # Small indexed, big skipped
        self.assertGreater(search.query("TINY")["total_lines"], 0)
        self.assertEqual(search.query("zzzzzzzz")["total_lines"], 0)

        # _skipped_large populated + actionable error logged
        self.assertIn("big.py", search._store._skipped_large)
        joined = "\n".join(cm.output)
        self.assertIn("Size guardrail", joined)
        self.assertIn("big.py", joined)
        self.assertIn("allow_large", joined)

    def test_allow_large_overrides_threshold(self):
        self._write_pg_toml(max_bytes=1024, allow_large=["big.py"])
        _write(os.path.join(TEST_DIR, "big.py"), "XYZZY_ALLOWED_MARKER_9931 = '" + "z" * 4096 + "'\n")

        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            # No error expected — allowlisted, so indexing proceeds silently.
            # assertLogs fails if nothing is logged at ERROR — so skip the assertion
            # context and just verify indexing worked.
            search.index_dir(TEST_DIR)

        self.assertGreater(search.query("XYZZY_ALLOWED_MARKER_9931")["total_lines"], 0)
        self.assertNotIn("big.py", search._store._skipped_large)

    def test_under_threshold_is_indexed_normally(self):
        self._write_pg_toml(max_bytes=1_048_576)  # 1 MB
        _write(os.path.join(TEST_DIR, "small.py"), "XYZZY_NORMAL_MARKER_5521 = 1\n")

        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._make_search()
            search.index_dir(TEST_DIR)

        self.assertGreater(search.query("XYZZY_NORMAL_MARKER_5521")["total_lines"], 0)
        self.assertEqual(search._store._skipped_large, {})

    def test_legacy_pg_toml_is_migrated_with_warning(self):
        """Pre-existing pg.toml without guardrail keys gets them appended and logged."""
        from ..inspect.config import DEFAULT_MAX_FILE_SIZE_BYTES, _migrated_dirs

        _write(
            os.path.join(TEST_DIR, "pg.toml"),
            '[detect]\nlanguages = ["python"]\n\n[index]\nextensions = [".py"]\n',
        )
        _write(os.path.join(TEST_DIR, ".pgignore"), "")
        _migrated_dirs.discard(Path(TEST_DIR))  # force a fresh migration check

        with patch("os.getcwd", return_value=TEST_DIR):
            with self.assertLogs("parseltongue.config", level="WARNING") as cm:
                # Any config-reading call triggers ensure_initialized → migration
                from ..inspect.config import load_max_file_size_bytes

                size = load_max_file_size_bytes()

        # Migration wrote defaults; subsequent load returns them.
        self.assertEqual(size, DEFAULT_MAX_FILE_SIZE_BYTES)
        toml_text = open(os.path.join(TEST_DIR, "pg.toml")).read()
        self.assertIn("max_file_size_bytes", toml_text)
        self.assertIn("allow_large", toml_text)
        self.assertIn("Migrated pg.toml", "\n".join(cm.output))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    unittest.main()
