"""Tests for Parseltongue file loader (loader.py)."""

import os
import shutil
import tempfile
import unittest

from ..loader import PltgError, load_pltg


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
        with self.assertRaises(PltgError) as cm:
            load_pltg(path)
        self.assertIn("Circular import", str(cm.exception))
        self.assertIsInstance(cm.exception.__cause__, ImportError)

    def test_import_not_found(self):
        path = self._write("main.pltg", '(import (quote nonexistent))')
        with self.assertRaises(PltgError) as cm:
            load_pltg(path)
        self.assertIsInstance(cm.exception.__cause__, FileNotFoundError)

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


class TestModuleAliasPatch(_TmpDirMixin, unittest.TestCase):
    """Tests that module aliases (e.g. pass1 → sources.pass1) are resolved
    correctly when the same file is imported under two different names."""

    def test_sibling_alias_resolves(self):
        """Entry imports sources/pass1. Sibling pass2 imports pass1.
        pass2's refs to pass1.X should resolve to sources.pass1.X."""
        self._write(
            "sources/pass1.pltg",
            '(fact val 42 :origin "pass1")',
        )
        self._write(
            "sources/pass2.pltg",
            '''
            (import (quote pass1))
            (fact derived pass1.val :origin "pass2")
        ''',
        )
        path = self._write(
            "main.pltg",
            '''
            (import (quote sources.pass1))
            (import (quote sources.pass2))
        ''',
        )
        system = load_pltg(path)
        self.assertIn("sources.pass1.val", system.facts)
        self.assertIn("sources.pass2.derived", system.facts)
        # The wff should reference the namespaced version
        wff = system.facts["sources.pass2.derived"].wff
        self.assertEqual(str(wff), "sources.pass1.val")

    def test_alias_in_derive_using(self):
        """Derive :using refs with aliases resolve correctly."""
        self._write(
            "sources/base.pltg",
            '''
            (fact base-val 10 :origin "base")
            (axiom base-rule (implies (> ?x 0) (= ?x ?x)) :origin "base")
        ''',
        )
        self._write(
            "sources/derived.pltg",
            '''
            (import (quote base))
            (derive my-theorem base.base-rule
                :bind ((?x base.base-val))
                :using (base.base-rule base.base-val))
        ''',
        )
        path = self._write(
            "main.pltg",
            '''
            (import (quote sources.base))
            (import (quote sources.derived))
        ''',
        )
        system = load_pltg(path)
        self.assertIn("sources.derived.my-theorem", system.theorems)

    def test_triple_alias_chain(self):
        """Three levels: entry → sources.lib, mid → lib (alias), leaf uses lib.X."""
        self._write("sources/lib.pltg", '(fact lib-val 1 :origin "lib")')
        self._write(
            "sources/mid.pltg",
            '''
            (import (quote lib))
            (fact mid-ref lib.lib-val :origin "mid")
        ''',
        )
        path = self._write(
            "main.pltg",
            '''
            (import (quote sources.lib))
            (import (quote sources.mid))
        ''',
        )
        system = load_pltg(path)
        self.assertIn("sources.lib.lib-val", system.facts)
        self.assertIn("sources.mid.mid-ref", system.facts)
        wff = system.facts["sources.mid.mid-ref"].wff
        self.assertEqual(str(wff), "sources.lib.lib-val")


class TestRelativeImport(_TmpDirMixin, unittest.TestCase):
    """Tests for Python-style relative imports with leading dots."""

    def test_single_dot_sibling_import(self):
        """(import (quote .sibling)) resolves to same directory."""
        self._write("pkg/sibling.pltg", '(fact sib-val 1 :origin "sib")')
        path = self._write(
            "pkg/main.pltg",
            """
            (import (quote .sibling))
            (fact x 10 :origin "test")
        """,
        )
        system = load_pltg(path)
        self.assertIn("sibling.sib-val", system.facts)

    def test_double_dot_parent_import(self):
        """(import (quote ..std.lib)) resolves to parent dir / std / lib.pltg."""
        self._write("std/lib.pltg", '(fact lib-val 42 :origin "lib")')
        path = self._write(
            "validation/main.pltg",
            """
            (import (quote ..std.lib))
            (fact x 10 :origin "test")
        """,
        )
        system = load_pltg(path)
        self.assertIn("std.lib.lib-val", system.facts)

    def test_relative_import_canonical_alias(self):
        """When importing ..std.counting (canonical: std.counting),
        references to counting.X should resolve to std.counting.X."""
        self._write(
            "std/counting.pltg",
            """
            (fact count-val 99 :origin "counting")
            (axiom count-rule (= (+ ?a ?b) (+ ?b ?a)) :origin "counting")
        """,
        )
        self._write(
            "validation/consumer.pltg",
            """
            (import (quote ..std.counting))
            (defterm my-count counting.count-val :origin "ref via short name")
        """,
        )
        path = self._write(
            "validation/main.pltg",
            """
            (import (quote .consumer))
        """,
        )
        system = load_pltg(path)
        # The fact is registered under canonical name
        self.assertIn("std.counting.count-val", system.facts)
        # The consumer's defterm should resolve counting.count-val → std.counting.count-val
        self.assertIn("consumer.my-count", system.terms)
        wff = system.terms["consumer.my-count"].definition
        self.assertEqual(str(wff), "std.counting.count-val")

    def test_relative_import_alias_in_using(self):
        """Short-name references in :using resolve via alias."""
        self._write(
            "std/counting.pltg",
            """
            (fact base-val 10 :origin "counting")
            (axiom base-rule (> ?x 0) :origin "counting")
        """,
        )
        self._write(
            "validation/consumer.pltg",
            """
            (import (quote ..std.counting))
            (derive my-thm counting.base-rule
                :bind ((?x counting.base-val))
                :using (counting.base-rule counting.base-val))
        """,
        )
        path = self._write(
            "validation/main.pltg",
            """
            (import (quote .consumer))
        """,
        )
        system = load_pltg(path)
        self.assertIn("consumer.my-thm", system.theorems)

    def test_relative_import_no_alias_collision(self):
        """If a short name is already registered as an alias, don't overwrite."""
        self._write("std/lib.pltg", '(fact lib-v1 1 :origin "v1")')
        self._write("other/lib.pltg", '(fact lib-v2 2 :origin "v2")')
        self._write(
            "validation/a.pltg",
            """
            (import (quote ..std.lib))
            (defterm ref-a lib.lib-v1 :origin "a")
        """,
        )
        self._write(
            "validation/b.pltg",
            """
            (import (quote ..other.lib))
            (fact b-val 3 :origin "b")
        """,
        )
        path = self._write(
            "validation/main.pltg",
            """
            (import (quote .a))
            (import (quote .b))
        """,
        )
        system = load_pltg(path)
        # First alias wins: lib → std.lib
        self.assertIn("std.lib.lib-v1", system.facts)
        self.assertIn("a.ref-a", system.terms)
        wff = system.terms["a.ref-a"].definition
        self.assertEqual(str(wff), "std.lib.lib-v1")


class TestEffectOrderingLoader(_TmpDirMixin, unittest.TestCase):
    """Tests that effects (load-document, import) execute in source order
    so that documents are available when imported modules reference them."""

    def test_load_document_before_import(self):
        """Document loaded in entry is available to imported module."""
        self._write("data/report.txt", "Revenue was $10M in Q3.")
        self._write(
            "sources/analysis.pltg",
            '''
            (fact revenue 10 :origin "report")
        ''',
        )
        path = self._write(
            "main.pltg",
            '''
            (load-document "report" "data/report.txt")
            (import (quote sources.analysis))
        ''',
        )
        system = load_pltg(path)
        self.assertIn("sources.analysis.revenue", system.facts)
        self.assertIn("report", system.documents)

    def test_load_document_after_import_still_works(self):
        """Document loaded after import is still in system."""
        self._write("data/notes.txt", "Some notes here.")
        self._write(
            "sources/mod.pltg",
            '(fact mod-val 1 :origin "mod")',
        )
        path = self._write(
            "main.pltg",
            '''
            (import (quote sources.mod))
            (load-document "notes" "data/notes.txt")
        ''',
        )
        system = load_pltg(path)
        self.assertIn("sources.mod.mod-val", system.facts)
        self.assertIn("notes", system.documents)

    def test_multiple_documents_then_imports(self):
        """Multiple documents loaded, then multiple imports — all available."""
        self._write("data/doc1.txt", "First document.")
        self._write("data/doc2.txt", "Second document.")
        self._write(
            "sources/a.pltg",
            '(fact a-val 1 :origin "doc1")',
        )
        self._write(
            "sources/b.pltg",
            '(fact b-val 2 :origin "doc2")',
        )
        path = self._write(
            "main.pltg",
            '''
            (load-document "doc1" "data/doc1.txt")
            (load-document "doc2" "data/doc2.txt")
            (import (quote sources.a))
            (import (quote sources.b))
        ''',
        )
        system = load_pltg(path)
        self.assertIn("sources.a.a-val", system.facts)
        self.assertIn("sources.b.b-val", system.facts)
        self.assertIn("doc1", system.documents)
        self.assertIn("doc2", system.documents)
