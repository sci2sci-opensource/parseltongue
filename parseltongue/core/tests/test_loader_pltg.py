"""Tests for Parseltongue file loader (loader.py)."""

import os
import shutil
import tempfile
import unittest

from ..loader import load_pltg


class _TmpDirMixin:
    """Mixin providing a temp directory and file writer."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path


# class TestLoaderContext(unittest.TestCase):
#
#     def test_defaults(self):
#         ctx = LoaderContext()
#         self.assertEqual(ctx.current_file, "")
#         self.assertTrue(ctx.is_main)
#         self.assertEqual(ctx.file_stack, [])
#         self.assertEqual(ctx.imported, set())


class TestLoadPltgBasic(_TmpDirMixin, unittest.TestCase):

    def test_load_simple_facts(self):
        path = self._write(
            "main.pltg",
            '''
            (fact x 10 :origin "test")
            (fact y 20 :origin "test")
        ''',
        )
        system = load_pltg(path)
        self.assertIn("x", system.facts)
        self.assertIn("y", system.facts)
        self.assertEqual(system.facts["x"].wff, 10)
        self.assertEqual(system.facts["y"].wff, 20)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_pltg("/nonexistent/path.pltg")

    def test_system_kwargs_passthrough(self):
        path = self._write("main.pltg", '(fact x 10 :origin "test")')
        system = load_pltg(path, overridable=True)
        self.assertTrue(system.engine.overridable)

    def test_custom_effects_alongside_loader(self):
        path = self._write(
            "main.pltg",
            '''
            (fact result (my-effect 5) :origin "test")
        ''',
        )

        def my_effect(system, val):
            return val * 2

        system = load_pltg(path, effects={"my-effect": my_effect})
        self.assertEqual(system.evaluate(system.facts["result"].wff), 10)


class TestImport(_TmpDirMixin, unittest.TestCase):

    def test_simple_import(self):
        self._write("helpers.pltg", '(fact helper-val 42 :origin "helper")')
        path = self._write(
            "main.pltg",
            '''
            (import (quote helpers))
            (fact x 10 :origin "test")
        ''',
        )
        system = load_pltg(path)
        self.assertIn("helpers.helper-val", system.facts)
        self.assertIn("x", system.facts)

    def test_dotted_import(self):
        self._write("utils/math.pltg", '(fact pi 3 :origin "approx")')
        path = self._write("main.pltg", '(import (quote utils.math))')
        system = load_pltg(path)
        self.assertIn("utils.math.pi", system.facts)

    def test_duplicate_import_skipped(self):
        self._write("helpers.pltg", '(fact counter 1 :origin "test")')
        path = self._write(
            "main.pltg",
            '''
            (import (quote helpers))
            (import (quote helpers))
        ''',
        )
        system = load_pltg(path)
        self.assertIn("helpers.counter", system.facts)

    def test_circular_import_detected(self):
        self._write("a.pltg", '(import (quote b))')
        self._write("b.pltg", '(import (quote a))')
        path = os.path.join(self.tmpdir, "a.pltg")
        with self.assertRaises(ImportError) as cm:
            load_pltg(path)
        self.assertIn("Circular import", str(cm.exception))

    def test_import_not_found(self):
        path = self._write("main.pltg", '(import (quote nonexistent))')
        with self.assertRaises(FileNotFoundError):
            load_pltg(path)

    def test_transitive_import(self):
        self._write("base.pltg", '(fact base-val 1 :origin "base")')
        self._write(
            "mid.pltg",
            '''
            (import (quote base))
            (fact mid-val 2 :origin "mid")
        ''',
        )
        path = self._write("main.pltg", '(import (quote mid))')
        system = load_pltg(path)
        self.assertIn("base.base-val", system.facts)
        self.assertIn("mid.mid-val", system.facts)

    def test_diamond_import(self):
        """A imports B and C; both B and C import D. D loads only once."""
        self._write("d.pltg", '(fact d-val 99 :origin "d")')
        self._write("b.pltg", '(import (quote d))\n(fact b-val 2 :origin "b")')
        self._write("c.pltg", '(import (quote d))\n(fact c-val 3 :origin "c")')
        path = self._write("main.pltg", '(import (quote b))\n(import (quote c))')
        system = load_pltg(path)
        self.assertIn("d.d-val", system.facts)
        self.assertIn("b.b-val", system.facts)
        self.assertIn("c.c-val", system.facts)


class TestRunOnEntry(_TmpDirMixin, unittest.TestCase):

    def test_executes_when_main(self):
        path = self._write(
            "main.pltg",
            '''
            (fact always 1 :origin "test")
            (run-on-entry (quote (fact only-main 2 :origin "test")))
        ''',
        )
        system = load_pltg(path)
        self.assertIn("always", system.facts)
        self.assertIn("only-main", system.facts)

    def test_skipped_when_imported(self):
        self._write(
            "lib.pltg",
            '''
            (fact lib-val 1 :origin "lib")
            (run-on-entry (quote (fact should-not-exist 999 :origin "standalone")))
        ''',
        )
        path = self._write("main.pltg", '(import (quote lib))')
        system = load_pltg(path)
        self.assertIn("lib.lib-val", system.facts)
        self.assertNotIn("should-not-exist", system.facts)

    def test_multiple_quoted_directives(self):
        path = self._write(
            "main.pltg",
            '''
            (run-on-entry
                (quote (fact a 1 :origin "test"))
                (quote (fact b 2 :origin "test"))
                (quote (fact c 3 :origin "test")))
        ''',
        )
        system = load_pltg(path)
        self.assertIn("a", system.facts)
        self.assertIn("b", system.facts)
        self.assertIn("c", system.facts)


class TestLoadDocument(_TmpDirMixin, unittest.TestCase):

    def test_relative_path(self):
        self._write("data/report.txt", "Q3 revenue was $15M.")
        path = self._write("main.pltg", '(load-document "report" "data/report.txt")')
        system = load_pltg(path)
        self.assertIn("report", system.documents)
        self.assertIn("Q3 revenue was $15M.", system.documents["report"])

    def test_from_imported_module(self):
        """Document path resolves relative to the imported file's directory."""
        self._write("libs/data.txt", "Important data here.")
        self._write("libs/loader.pltg", '(load-document "data" "data.txt")')
        path = self._write("main.pltg", '(import (quote libs.loader))')
        system = load_pltg(path)
        self.assertIn("data", system.documents)


class TestContext(_TmpDirMixin, unittest.TestCase):

    def test_context_file(self):
        path = self._write(
            "main.pltg",
            '''
            (fact current-file (context :file) :origin "loader")
        ''',
        )
        system = load_pltg(path)
        self.assertEqual(system.evaluate(system.facts["current-file"].wff), os.path.abspath(path))

    def test_context_dir(self):
        path = self._write(
            "main.pltg",
            '''
            (fact current-dir (context :dir) :origin "loader")
        ''',
        )
        system = load_pltg(path)
        self.assertEqual(system.evaluate(system.facts["current-dir"].wff), os.path.dirname(os.path.abspath(path)))

    def test_context_name(self):
        path = self._write(
            "main.pltg",
            '''
            (fact current-name (context :name) :origin "loader")
        ''',
        )
        system = load_pltg(path)
        self.assertEqual(system.evaluate(system.facts["current-name"].wff), "main")

    def test_context_main_true_for_entry(self):
        path = self._write(
            "main.pltg",
            '''
            (fact am-i-main (context :main) :origin "loader")
        ''',
        )
        system = load_pltg(path)
        self.assertIs(system.evaluate(system.facts["am-i-main"].wff), True)

    def test_context_main_false_for_imported(self):
        self._write(
            "lib.pltg",
            '''
            (fact lib-is-main (context :main) :origin "loader")
        ''',
        )
        path = self._write("main.pltg", '(import (quote lib))')
        system = load_pltg(path)
        self.assertIs(system.evaluate(system.facts["lib.lib-is-main"].wff), False)
