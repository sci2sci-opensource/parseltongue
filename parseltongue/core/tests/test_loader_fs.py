"""Tests for the loader's filesystem and built-in effect set (loader/fs.py, Loader args)."""

import fnmatch
import hashlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

import click

from ..inspect.bench import Bench
from ..inspect.bench_cli import _import_fs
from ..inspect.store import Store
from ..inspect.technician import Technician
from ..loader import LOADER_EFFECTS, LazyLoader, Loader, LoaderFS, PltgError
from ..system import System

#: Appended to by (dangerously-eval …) in the tests below; empty means the code never ran.
EVAL_MARKS: list[int] = []


class MemoryFS:
    """Files held in a dict, under paths that do not exist on disk."""

    def __init__(self, files: dict[str, str]):
        self.files = files

    def is_file(self, path: str) -> bool:
        return path in self.files

    def read_text(self, path: str) -> str:
        return self.files[path]

    def list_files(self, root: str, pattern: str) -> list[tuple[str, int]]:
        prefix = root.rstrip("/") + "/"
        found = []
        for path, text in sorted(self.files.items()):
            rel = path[len(prefix) :] if path.startswith(prefix) else None
            if rel is not None and fnmatch.fnmatch(rel, pattern.replace("**/", "*")):
                found.append((rel, len(text)))
        return found

    def digest(self, path: str) -> str:
        return hashlib.sha256(self.files[path].encode()).hexdigest() if path in self.files else ""


ROOT = "/virtual/circuit"


class TestVirtualFS(unittest.TestCase):

    def test_memory_fs_satisfies_protocol(self):
        self.assertIsInstance(MemoryFS({}), LoaderFS)

    def test_entry_imports_and_documents_come_from_the_fs(self):
        fs = MemoryFS(
            {
                f"{ROOT}/main.pltg": "(import (quote util))\n"
                '(load-document "memo" "docs/memo.txt")\n'
                '(load-documents "notes" "notes/**/*.txt")\n'
                "(fact x 1)\n",
                f"{ROOT}/util.pltg": "(fact y 2)\n",
                f"{ROOT}/docs/memo.txt": "revenue was flat",
                f"{ROOT}/notes/a.txt": "first note",
                f"{ROOT}/notes/b.txt": "second note",
            }
        )
        system = Loader(fs=fs).load_main(f"{ROOT}/main.pltg")
        self.assertIn("x", system.facts)
        self.assertIn("util.y", system.facts)
        documents = system.engine.documents
        self.assertEqual(documents["memo"], "revenue was flat")
        self.assertEqual(documents["notes/a.txt"], "first note")
        self.assertEqual(documents["notes/b.txt"], "second note")

    def test_missing_entry_is_reported_by_the_fs(self):
        with self.assertRaises(FileNotFoundError):
            Loader(fs=MemoryFS({})).load_main(f"{ROOT}/main.pltg")


class TestBuiltinEffects(unittest.TestCase):

    SOURCE = '(dangerously-eval "import parseltongue.core.tests.test_loader_fs as t; t.EVAL_MARKS.append(1)")\n'

    def setUp(self):
        EVAL_MARKS.clear()
        self.fs = MemoryFS({f"{ROOT}/main.pltg": self.SOURCE})

    def test_all_effects_by_default(self):
        Loader(fs=self.fs).load_main(f"{ROOT}/main.pltg")
        self.assertEqual(EVAL_MARKS, [1])

    def test_excluded_effect_never_runs(self):
        safe = [name for name in LOADER_EFFECTS if name != "dangerously-eval"]
        with self.assertRaises(PltgError):
            Loader(fs=self.fs, builtin_effects=safe).load_main(f"{ROOT}/main.pltg")
        self.assertEqual(EVAL_MARKS, [])

    def test_excluded_effect_never_runs_lazily(self):
        safe = [name for name in LOADER_EFFECTS if name != "dangerously-eval"]
        loader = LazyLoader(fs=self.fs, builtin_effects=safe)
        loader.load_main(f"{ROOT}/main.pltg")
        self.assertEqual(EVAL_MARKS, [])
        self.assertTrue(loader.last_result.errors)

    def test_unknown_effect_name_is_rejected(self):
        with self.assertRaises(ValueError):
            Loader(builtin_effects=["import", "no-such-effect"])


SAFE_EFFECTS = [name for name in LOADER_EFFECTS if name != "dangerously-eval"]


class TestBenchFS(unittest.TestCase):

    def setUp(self):
        EVAL_MARKS.clear()
        self.bench_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.bench_dir)

    def test_bench_loads_through_its_fs_and_effect_set(self):
        path = f"{ROOT}/main.pltg"
        fs = MemoryFS({path: TestBuiltinEffects.SOURCE + "(fact x 1)\n"})
        bench = Bench(bench_dir=self.bench_dir, fs=fs, builtin_effects=SAFE_EFFECTS)
        bench.prepare(path)
        system = bench._mem[path][3].last_result.system
        self.assertIn("x", system.facts)
        self.assertEqual(EVAL_MARKS, [])

    def _prepare(self, fs, builtin_effects=None) -> int:
        """Prepare ROOT/main.pltg on a fresh Bench over the shared bench dir; returns the number of cold loads."""
        with patch.object(Technician, "_cold_load", autospec=True, side_effect=Technician._cold_load) as cold:
            bench = Bench(bench_dir=self.bench_dir, fs=fs, builtin_effects=builtin_effects)
            bench.prepare(f"{ROOT}/main.pltg")
            # A cache hit starts a background reload (and a screen refresh) that
            # write into the bench dir; let them finish before the dir goes away.
            technician = bench._technician
            for thread in [*technician._bg_reload.values(), *technician._screen_refresh.values()]:
                thread.join(timeout=60)
        return cold.call_count

    def test_cache_is_served_when_the_effects_it_ran_are_unchanged(self):
        fs = MemoryFS({f"{ROOT}/main.pltg": "(fact x 1)\n(print \"hello\")\n"})
        self.assertEqual(self._prepare(fs), 1)
        # Narrowing the set removes dangerously-eval, which this source never ran.
        self.assertEqual(self._prepare(fs, builtin_effects=SAFE_EFFECTS), 0)

    def test_cache_that_ran_a_removed_effect_is_not_served(self):
        fs = MemoryFS({f"{ROOT}/main.pltg": TestBuiltinEffects.SOURCE + "(fact x 1)\n"})
        self.assertEqual(self._prepare(fs), 1)
        self.assertEqual(EVAL_MARKS, [1])
        self.assertEqual(self._prepare(fs, builtin_effects=SAFE_EFFECTS), 1)
        self.assertEqual(EVAL_MARKS, [1])

    def test_unknown_effect_record_is_not_served(self):
        technician = Technician(Store(self.bench_dir), lambda *a: None)
        system = System.from_dict({})
        self.assertIsNone(system.effects_used)
        self.assertFalse(technician._ran_as_now(f"{ROOT}/main.pltg", system))


class TestEffectsUsed(unittest.TestCase):

    def test_system_records_the_effects_it_ran(self):
        fs = MemoryFS({f"{ROOT}/main.pltg": '(load-document "m" "memo.txt")\n(fact x 1)\n', f"{ROOT}/memo.txt": "memo"})
        system = Loader(fs=fs).load_main(f"{ROOT}/main.pltg")
        self.assertEqual(set(system.effects_used), {"load-document"})
        self.assertIn("load_document_effect", system.effects_used["load-document"])

    def test_record_survives_serialization(self):
        fs = MemoryFS({f"{ROOT}/main.pltg": '(print "hi")\n'})
        system = Loader(fs=fs).load_main(f"{ROOT}/main.pltg")
        self.assertEqual(System.from_dict(system.to_dict()).effects_used, system.effects_used)


def memory_fs_factory(entry_path: str) -> MemoryFS:
    return MemoryFS({entry_path: "(fact x 1)\n"})


def not_an_fs(entry_path: str) -> dict:
    return {}


class TestFSSpec(unittest.TestCase):

    def test_spec_builds_the_fs_for_the_entry(self):
        fs = _import_fs("parseltongue.core.tests.test_loader_fs:memory_fs_factory", f"{ROOT}/main.pltg")
        self.assertTrue(fs.is_file(f"{ROOT}/main.pltg"))

    def test_spec_must_build_a_loader_fs(self):
        with self.assertRaises(click.BadParameter):
            _import_fs("parseltongue.core.tests.test_loader_fs:not_an_fs", f"{ROOT}/main.pltg")


if __name__ == "__main__":
    unittest.main()
