"""Tests for Parseltongue LazyLoader — fault-tolerant .pltg loading."""

import os
import shutil
import tempfile
import unittest

from ..loader import lazy_load_pltg


class _TmpDirMixin:
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


class TestLazyLoadBasic(_TmpDirMixin, unittest.TestCase):

    def test_clean_load(self):
        path = self._write(
            "main.pltg",
            '''
            (fact x 10 :origin "test")
            (fact y 20 :origin "test")
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertTrue(result.ok)
        self.assertFalse(result.partial)
        self.assertIn("x", result.system.facts)
        self.assertIn("y", result.system.facts)

    def test_loaded_tracks_nodes(self):
        path = self._write(
            "main.pltg",
            '''
            (fact a 1 :origin "test")
            (fact b 2 :origin "test")
        ''',
        )
        result = lazy_load_pltg(path)
        loaded_names = {n.name for n in result.loaded}
        self.assertIn("a", loaded_names)
        self.assertIn("b", loaded_names)


class TestLazyLoadFaultTolerance(_TmpDirMixin, unittest.TestCase):

    def test_bad_derive_doesnt_block_others(self):
        path = self._write(
            "main.pltg",
            '''
            (fact good 1 :origin "test")
            (derive bad-theorem nonexistent-axiom
                :bind ((?x 1))
                :using (nonexistent-axiom))
            (fact also-good 2 :origin "test")
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertFalse(result.ok)
        self.assertTrue(result.partial)
        self.assertIn("good", result.system.facts)
        self.assertIn("also-good", result.system.facts)
        error_names = {n.name for n in result.errors}
        self.assertIn("bad-theorem", error_names)

    def test_dependents_of_failure_are_skipped(self):
        path = self._write(
            "main.pltg",
            '''
            (fact good 1 :origin "test")
            (derive bad-derive nonexistent-axiom
                :bind ((?x 1))
                :using (nonexistent-axiom))
            (derive depends-on-bad (> bad-derive 0)
                :using (bad-derive))
            (diff also-depends :replace depends-on-bad :with good)
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertIn("good", result.system.facts)
        error_names = {n.name for n in result.errors}
        skipped_names = {n.name for n in result.skipped}
        self.assertIn("bad-derive", error_names)
        self.assertIn("depends-on-bad", skipped_names)
        self.assertIn("also-depends", skipped_names)

    def test_independent_branches_survive(self):
        path = self._write(
            "main.pltg",
            '''
            (fact a 1 :origin "test")
            (fact b 2 :origin "test")
            (derive bad nonexistent-axiom
                :bind ((?x 1))
                :using (nonexistent-axiom))
            (derive uses-bad (> bad 0) :using (bad))
            (derive good-derive (> a 0) :using (a))
            (diff good-diff :replace a :with b)
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertIn("good-derive", result.system.theorems)
        error_names = {n.name for n in result.errors}
        skipped_names = {n.name for n in result.skipped}
        self.assertIn("bad", error_names)
        self.assertIn("uses-bad", skipped_names)
        loaded_names = {n.name for n in result.loaded}
        self.assertIn("good-derive", loaded_names)
        self.assertIn("good-diff", loaded_names)

    def test_multiple_independent_failures(self):
        path = self._write(
            "main.pltg",
            '''
            (fact ok 1 :origin "test")
            (derive fail-1 nonexistent-1
                :bind ((?x 1))
                :using (nonexistent-1))
            (derive fail-2 nonexistent-2
                :bind ((?x 1))
                :using (nonexistent-2))
            (derive needs-1 (> fail-1 0) :using (fail-1))
            (derive needs-2 (> fail-2 0) :using (fail-2))
            (derive independent (> ok 0) :using (ok))
        ''',
        )
        result = lazy_load_pltg(path)
        error_names = {n.name for n in result.errors}
        skipped_names = {n.name for n in result.skipped}
        self.assertIn("fail-1", error_names)
        self.assertIn("fail-2", error_names)
        self.assertIn("needs-1", skipped_names)
        self.assertIn("needs-2", skipped_names)
        loaded_names = {n.name for n in result.loaded}
        self.assertIn("independent", loaded_names)


class TestLazyLoadErrorTree(_TmpDirMixin, unittest.TestCase):

    def test_root_cause_traces_to_error(self):
        path = self._write(
            "main.pltg",
            '''
            (derive root-fail nonexistent
                :bind ((?x 1))
                :using (nonexistent))
            (derive mid (> root-fail 0) :using (root-fail))
            (derive leaf (> mid 0) :using (mid))
        ''',
        )
        result = lazy_load_pltg(path)
        # Find the leaf node
        leaf_node = None
        for node in result.skipped:
            if node.name == "leaf":
                leaf_node = node
                break
        self.assertIsNotNone(leaf_node)
        root = result.root_cause(leaf_node)
        self.assertIsNotNone(root)
        self.assertEqual(root.name, "root-fail")

    def test_error_trees_groups_by_root(self):
        path = self._write(
            "main.pltg",
            '''
            (derive fail nonexistent
                :bind ((?x 1))
                :using (nonexistent))
            (derive child-a (> fail 0) :using (fail))
            (derive child-b (< fail 10) :using (fail))
        ''',
        )
        result = lazy_load_pltg(path)
        trees = result.error_trees()
        self.assertEqual(len(trees), 1)
        root_node = list(trees.keys())[0]
        self.assertEqual(root_node.name, "fail")
        cascade_names = {n.name for n in trees[root_node]}
        self.assertEqual(cascade_names, {"child-a", "child-b"})

    def test_summary_output(self):
        path = self._write(
            "main.pltg",
            '''
            (fact ok 1 :origin "test")
            (derive fail nonexistent
                :bind ((?x 1))
                :using (nonexistent))
            (derive skipped-child (> fail 0) :using (fail))
        ''',
        )
        result = lazy_load_pltg(path)
        summary = result.summary()
        self.assertIn("Loaded: ", summary)
        self.assertIn("ERROR", summary)
        self.assertIn("fail", summary)
        self.assertIn("SKIP", summary)
        self.assertIn("skipped-child", summary)


class TestLazyLoadWithImports(_TmpDirMixin, unittest.TestCase):

    def test_import_works(self):
        self._write("helpers.pltg", '(fact helper-val 42 :origin "helper")')
        path = self._write(
            "main.pltg",
            '''
            (import (quote helpers))
            (fact x 10 :origin "test")
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertTrue(result.ok)
        self.assertIn("helpers.helper-val", result.system.facts)

    def test_failure_in_main_doesnt_break_imports(self):
        self._write("helpers.pltg", '(fact helper-val 42 :origin "helper")')
        path = self._write(
            "main.pltg",
            '''
            (import (quote helpers))
            (fact good 1 :origin "test")
            (derive bad nonexistent
                :bind ((?x 1))
                :using (nonexistent))
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertIn("helpers.helper-val", result.system.facts)
        self.assertIn("good", result.system.facts)
        error_names = {n.name for n in result.errors}
        self.assertIn("bad", error_names)


class TestLazyLoadWithEffects(_TmpDirMixin, unittest.TestCase):

    def test_custom_effects(self):
        path = self._write(
            "main.pltg",
            '''
            (fact result (my-effect 5) :origin "test")
        ''',
        )
        result = lazy_load_pltg(
            path,
            effects={
                "my-effect": lambda _sys, val: val * 2,
            },
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.system.evaluate(result.system.facts["result"].wff), 10)

    def test_print_effects_run(self):
        """Effects like print execute even when named directives fail."""
        path = self._write(
            "main.pltg",
            '''
            (print "before")
            (fact ok 1 :origin "test")
            (derive fail nonexistent
                :bind ((?x 1))
                :using (nonexistent))
            (print "after")
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertIn("ok", result.system.facts)
        error_names = {n.name for n in result.errors}
        self.assertIn("fail", error_names)


class TestLazyLoadIntegration(_TmpDirMixin, unittest.TestCase):
    """Big integration test: multiple modules, errors at various levels,
    parse errors, import failures, and dependency cascades."""

    def test_multi_module_partial_failure(self):
        """
        Structure:
          main.pltg
            imports healthy.pltg     (all good)
            imports sick.pltg        (has a bad derive)
            imports missing_dep.pltg (imports nonexistent module)
            own facts, derives, diffs — some depend on sick, some don't

        Expected:
          - healthy facts load fine
          - sick facts load, sick's bad derive fails, its dependents skip
          - missing_dep import fails (effect error)
          - main's independent facts/derives load
          - main's derives depending on sick's failed derive are skipped
          - main's derives depending on healthy work fine
        """
        # healthy.pltg — fully correct module
        self._write(
            "healthy.pltg",
            '''
            (fact health-a 10 :origin "healthy")
            (fact health-b 20 :origin "healthy")
            (derive health-sum (+ health-a health-b) :using (health-a health-b))
        ''',
        )

        # sick.pltg — has one bad derive, rest is fine
        self._write(
            "sick.pltg",
            '''
            (fact sick-ok 1 :origin "sick")
            (fact sick-also-ok 2 :origin "sick")
            (derive sick-bad nonexistent-axiom
                :bind ((?x 1))
                :using (nonexistent-axiom))
            (derive sick-depends-on-bad (> sick-bad 0)
                :using (sick-bad))
            (derive sick-independent (> sick-ok 0)
                :using (sick-ok))
        ''',
        )

        # main.pltg — orchestrates everything
        path = self._write(
            "main.pltg",
            '''
            (import (quote healthy))
            (import (quote sick))
            (import (quote missing_dep))

            (fact main-own 100 :origin "main")

            ; depends on healthy — should work
            (derive main-uses-healthy (> healthy.health-sum 0)
                :using (healthy.health-sum))

            ; depends on sick's ok fact — should work
            (derive main-uses-sick-ok (> sick.sick-ok 0)
                :using (sick.sick-ok))

            ; depends on sick's failed derive — should be skipped
            (derive main-uses-sick-bad (> sick.sick-bad 0)
                :using (sick.sick-bad))

            ; depends on main-uses-sick-bad — cascading skip
            (diff main-cascade :replace main-uses-sick-bad :with main-own)

            ; fully independent — should work
            (derive main-independent (> main-own 0) :using (main-own))

            ; diff between two healthy things — should work
            (diff main-healthy-diff :replace healthy.health-a :with healthy.health-b)
        ''',
        )

        result = lazy_load_pltg(path)

        # --- healthy module loaded fully ---
        self.assertIn("healthy.health-a", result.system.facts)
        self.assertIn("healthy.health-b", result.system.facts)
        self.assertIn("healthy.health-sum", result.system.theorems)

        # --- sick module: facts loaded, bad derive failed ---
        self.assertIn("sick.sick-ok", result.system.facts)
        self.assertIn("sick.sick-also-ok", result.system.facts)
        self.assertIn("sick.sick-independent", result.system.theorems)

        error_names = {n.name for n in result.errors if n.name}
        skipped_names = {n.name for n in result.skipped}

        self.assertIn("sick.sick-bad", error_names)
        self.assertIn("sick.sick-depends-on-bad", skipped_names)

        # --- missing_dep import failed (effect error) ---
        effect_errors = [n for n in result.errors if n.kind == "effect"]
        self.assertTrue(len(effect_errors) > 0, "Expected import effect error for missing_dep")

        # --- main module: independent stuff works ---
        self.assertIn("main-own", result.system.facts)
        self.assertIn("main-independent", result.system.theorems)
        self.assertIn("main-uses-healthy", result.system.theorems)
        self.assertIn("main-uses-sick-ok", result.system.theorems)

        # --- main module: sick-dependent stuff skipped ---
        self.assertIn("main-uses-sick-bad", skipped_names)
        self.assertIn("main-cascade", skipped_names)

        # --- healthy diff works ---
        loaded_names = {n.name for n in result.loaded if n.name}
        self.assertIn("main-healthy-diff", loaded_names)

        # --- error tree traces back correctly ---
        for node in result.skipped:
            if node.name == "main-cascade":
                root = result.root_cause(node)
                self.assertIsNotNone(root)
                self.assertEqual(root.name, "sick.sick-bad")

        # --- summary is coherent ---
        summary = result.summary()
        self.assertIn("ERROR", summary)
        self.assertIn("SKIP", summary)
        self.assertIn("Loaded:", summary)

    def test_parse_error_doesnt_crash(self):
        """A syntax error in a .pltg file shouldn't crash the lazy loader."""
        path = self._write(
            "main.pltg",
            '''
            (fact before-error 1 :origin "test")
            (fact broken (
            (fact after-error 2 :origin "test")
        ''',
        )
        result = lazy_load_pltg(path)
        # The parse error should be recorded
        self.assertFalse(result.ok)
        # At least one of the valid facts should have loaded
        has_some = "before-error" in result.system.facts or "after-error" in result.system.facts
        self.assertTrue(has_some, "Expected at least some facts to survive a parse error")

    def test_parse_error_in_imported_module(self):
        """Parse error in imported module shouldn't crash main."""
        self._write(
            "broken.pltg",
            '''
            (fact imported-ok 1 :origin "test")
            (fact bad-syntax (
            (fact imported-after 2 :origin "test")
        ''',
        )
        path = self._write(
            "main.pltg",
            '''
            (import (quote broken))
            (fact main-ok 1 :origin "test")
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertIn("main-ok", result.system.facts)
        self.assertFalse(result.ok)

    def test_deep_cascade_chain(self):
        """Error at depth 0 cascades through a long chain."""
        self._write(
            "base.pltg",
            '''
            (fact base-ok 1 :origin "test")
            (derive base-fail nonexistent
                :bind ((?x 1))
                :using (nonexistent))
        ''',
        )
        self._write(
            "mid.pltg",
            '''
            (import (quote base))
            (fact mid-ok 1 :origin "test")
            (derive mid-uses-fail (> base.base-fail 0) :using (base.base-fail))
            (derive mid-independent (> mid-ok 0) :using (mid-ok))
        ''',
        )
        path = self._write(
            "main.pltg",
            '''
            (import (quote mid))
            (fact main-ok 1 :origin "test")
            (derive main-chain (> mid.mid-uses-fail 0) :using (mid.mid-uses-fail))
            (derive main-independent (> main-ok 0) :using (main-ok))
        ''',
        )
        result = lazy_load_pltg(path)

        # Independent branches survive at every level
        self.assertIn("base.base-ok", result.system.facts)
        self.assertIn("mid.mid-ok", result.system.facts)
        self.assertIn("mid.mid-independent", result.system.theorems)
        self.assertIn("main-ok", result.system.facts)
        self.assertIn("main-independent", result.system.theorems)

        # The cascade: base-fail -> mid-uses-fail -> main-chain
        error_names = {n.name for n in result.errors if n.name}
        skipped_names = {n.name for n in result.skipped}
        self.assertIn("base.base-fail", error_names)
        self.assertIn("mid.mid-uses-fail", skipped_names)
        self.assertIn("main-chain", skipped_names)

        # Root cause of main-chain traces to base.base-fail
        for node in result.skipped:
            if node.name == "main-chain":
                root = result.root_cause(node)
                self.assertIsNotNone(root)
                self.assertEqual(root.name, "base.base-fail")


class TestLazyLoaderModuleAliasPatch(_TmpDirMixin, unittest.TestCase):
    """Tests that LazyLoader resolves module aliases (e.g. pass1 → sources.pass1)
    when the same file is imported under two different names."""

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
        result = lazy_load_pltg(path)
        self.assertTrue(result.ok, f"Expected clean load, got errors: {result.summary()}")
        self.assertIn("sources.pass1.val", result.system.facts)
        self.assertIn("sources.pass2.derived", result.system.facts)
        wff = result.system.facts["sources.pass2.derived"].wff
        self.assertEqual(str(wff), "sources.pass1.val")

    def test_alias_in_derive_using(self):
        """Derive :using refs with aliases resolve correctly in lazy loader."""
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
        result = lazy_load_pltg(path)
        self.assertTrue(result.ok, f"Expected clean load, got errors: {result.summary()}")
        self.assertIn("sources.derived.my-theorem", result.system.theorems)

    def test_alias_failure_cascades_correctly(self):
        """When a fact in an aliased module fails, dependents using the alias are skipped."""
        self._write(
            "sources/base.pltg",
            '''
            (fact base-ok 1 :origin "base")
            (derive base-fail nonexistent
                :bind ((?x 1))
                :using (nonexistent))
        ''',
        )
        self._write(
            "sources/consumer.pltg",
            '''
            (import (quote base))
            (fact consumer-ok 1 :origin "consumer")
            (derive consumer-uses-fail (> base.base-fail 0) :using (base.base-fail))
            (derive consumer-independent (> consumer-ok 0) :using (consumer-ok))
        ''',
        )
        path = self._write(
            "main.pltg",
            '''
            (import (quote sources.base))
            (import (quote sources.consumer))
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertFalse(result.ok)
        # Independent stuff survives
        self.assertIn("sources.base.base-ok", result.system.facts)
        self.assertIn("sources.consumer.consumer-ok", result.system.facts)
        self.assertIn("sources.consumer.consumer-independent", result.system.theorems)
        # Failed and skipped
        error_names = {n.name for n in result.errors if n.name}
        skipped_names = {n.name for n in result.skipped}
        self.assertIn("sources.base.base-fail", error_names)
        self.assertIn("sources.consumer.consumer-uses-fail", skipped_names)


class TestLazyLoaderEffectOrdering(_TmpDirMixin, unittest.TestCase):
    """Tests that LazyLoader executes effects (load-document, import, etc.)
    BEFORE symbol patching, so documents and aliases are available."""

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
        result = lazy_load_pltg(path)
        self.assertTrue(result.ok, f"Expected clean load, got errors: {result.summary()}")
        self.assertIn("sources.analysis.revenue", result.system.facts)
        self.assertIn("report", result.system.documents)

    def test_effects_before_named_directives(self):
        """Effects like load-document execute before named directives (facts, derives)
        even when they appear interleaved in source."""
        self._write("data/doc.txt", "Important data.")
        path = self._write(
            "main.pltg",
            '''
            (fact before-doc 1 :origin "test")
            (load-document "doc" "data/doc.txt")
            (fact after-doc 2 :origin "test")
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertTrue(result.ok, f"Expected clean load, got errors: {result.summary()}")
        self.assertIn("before-doc", result.system.facts)
        self.assertIn("after-doc", result.system.facts)
        self.assertIn("doc", result.system.documents)

    def test_import_before_symbol_patch(self):
        """Import executes before symbol patching so that module aliases
        are available for _patch_symbols_from_names."""
        self._write(
            "sources/base.pltg",
            '(fact base-val 100 :origin "base")',
        )
        self._write(
            "sources/consumer.pltg",
            '''
            (import (quote base))
            (fact ref base.base-val :origin "consumer")
        ''',
        )
        path = self._write(
            "main.pltg",
            '''
            (import (quote sources.base))
            (import (quote sources.consumer))
        ''',
        )
        result = lazy_load_pltg(path)
        self.assertTrue(result.ok, f"Expected clean load, got errors: {result.summary()}")
        self.assertIn("sources.consumer.ref", result.system.facts)
        wff = result.system.facts["sources.consumer.ref"].wff
        self.assertEqual(str(wff), "sources.base.base-val")

    def test_multiple_documents_then_imports_with_evidence(self):
        """Multiple documents loaded, then imports — evidence verifiable in all modules."""
        self._write("data/doc1.txt", "First document content.")
        self._write("data/doc2.txt", "Second document content.")
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
        result = lazy_load_pltg(path)
        self.assertTrue(result.ok, f"Expected clean load, got errors: {result.summary()}")
        self.assertIn("sources.a.a-val", result.system.facts)
        self.assertIn("sources.b.b-val", result.system.facts)
        self.assertIn("doc1", result.system.documents)
        self.assertIn("doc2", result.system.documents)
