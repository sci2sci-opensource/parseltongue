"""File selection: gitignore-style anchoring and per-repository gitignore.

Two rules that keep local-only files out of a corpus whose caches travel
with the workspace:

- A leading ``/`` in .pgignore anchors the pattern at the root, as in
  gitignore. ``/tmp`` used to match nothing, so a root-level scratch dir
  full of notes was indexed despite being listed.
- A file that its own git repository ignores is never indexed — judged by
  the nearest repository above the file, so a workspace that ignores its
  child checkouts at the top level does not blank out the children.
"""

import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from ..inspect.search import Search
from ..inspect.store import SearchStore, Store
from ..search_engine.select import is_ignored

TEST_DIR = "/tmp/select-ignore-test"


class TestAnchoredPatterns(unittest.TestCase):
    def test_leading_slash_anchors_at_root(self):
        self.assertTrue(is_ignored("tmp/notes.md", ["/tmp"]))
        self.assertTrue(is_ignored("tmp/deep/notes.md", ["/tmp"]))
        self.assertTrue(is_ignored("tmp", ["/tmp"]))
        self.assertFalse(is_ignored("pkg/tmp/notes.md", ["/tmp"]))
        self.assertFalse(is_ignored("tmpfile.md", ["/tmp"]))

    def test_anchored_file_pattern(self):
        self.assertTrue(is_ignored("settings/overrides.py", ["/settings/overrides.py"]))
        self.assertFalse(is_ignored("app/settings/overrides.py", ["/settings/overrides.py"]))

    def test_unanchored_matches_at_any_depth(self):
        self.assertTrue(is_ignored("a/b/tmp/x.md", ["tmp/"]))
        self.assertTrue(is_ignored("a/settings/overrides.py", ["settings/overrides.py"]))
        self.assertFalse(is_ignored("a/settings/overrides.pyc", ["settings/overrides.py"]))

    def test_blank_and_slash_only_patterns_are_inert(self):
        self.assertFalse(is_ignored("anything.py", ["/", ""]))


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _git(cwd: str, *args: str):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class TestChildRepoGitignore(unittest.TestCase):
    """Workspace (a git repo ignoring its child checkout) → child repo with
    its own .gitignore. Only the child's rules apply to the child's files."""

    def setUp(self):
        shutil.rmtree(TEST_DIR, ignore_errors=True)
        os.makedirs(TEST_DIR)
        _write(os.path.join(TEST_DIR, "pg.toml"), '[detect]\nlanguages = ["python"]\n[index]\nextensions = [".py"]\n')
        _write(os.path.join(TEST_DIR, ".pgignore"), "")
        # Workspace repo: ignores the child placement and a scratch dir.
        _git(TEST_DIR, "init", "-q")
        _write(os.path.join(TEST_DIR, ".gitignore"), "child/\nscratch/\n")
        _write(os.path.join(TEST_DIR, "top.py"), "TOP = 1\n")
        _write(os.path.join(TEST_DIR, "scratch", "note.py"), "SCRATCH_SECRET = 1\n")
        # Child repo: ignores its local settings.
        child = os.path.join(TEST_DIR, "child")
        os.makedirs(child)
        _git(child, "init", "-q")
        _write(os.path.join(child, ".gitignore"), "settings/overrides.py\n")
        _write(os.path.join(child, "app.py"), "APP = 1\n")
        _write(os.path.join(child, "settings", "base.py"), "BASE = 1\n")
        _write(os.path.join(child, "settings", "overrides.py"), "OVERRIDE_SECRET = 1\n")
        self._cwd = os.getcwd()
        os.chdir(TEST_DIR)

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def _search(self) -> Search:
        return Search(SearchStore(store=Store(os.path.join(TEST_DIR, ".bench")), path=TEST_DIR))

    def test_gitignored_files_never_enter_the_index(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._search()
            search.index_dir(TEST_DIR)
        names = set(search._index.documents)
        self.assertIn("top.py", names)
        self.assertIn("child/app.py", names)
        self.assertIn("child/settings/base.py", names)  # child ignores only overrides.py
        self.assertNotIn("child/settings/overrides.py", names)
        self.assertNotIn("scratch/note.py", names)
        self.assertEqual(search.query("SCRATCH_SECRET")["total_lines"], 0)
        self.assertEqual(search.query("OVERRIDE_SECRET")["total_lines"], 0)

    def test_a_rule_added_later_evicts_on_the_next_pass(self):
        with patch("os.getcwd", return_value=TEST_DIR):
            search = self._search()
            search.index_dir(TEST_DIR)
            self.assertIn("child/settings/base.py", set(search._index.documents))
            # Operator later gitignores base.py in the child; nothing else changes.
            _write(os.path.join(TEST_DIR, "child", ".gitignore"), "settings/\n")
            search.reindex()
        self.assertNotIn("child/settings/base.py", set(search._index.documents))
        self.assertEqual(search.query("BASE")["total_lines"], 0)


if __name__ == "__main__":
    unittest.main()
