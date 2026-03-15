"""Tests for eval-time :bind via bench scopes — cross-scope composition."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ..inspect.bench import Bench

_BG_RELOAD = "parseltongue.core.inspect.technician.Technician._background_reload"

DOC_TEXT = "Engine handles evaluation. Facts are stored. Axioms define rules."


def _pltg(body: str) -> str:
    return f'(load-document "doc.txt" "doc.txt")\n{body}'


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bench_bind_")
        self.bench_dir = os.path.join(self.tmpdir, ".bench")
        self._bg_patcher = patch(_BG_RELOAD)
        self._bg_patcher.start()
        self._write("doc.txt", DOC_TEXT)

    def tearDown(self):
        self._bg_patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _bench(self, source: str) -> Bench:
        path = self._write("main.pltg", _pltg(source))
        bench = Bench(bench_dir=self.bench_dir)
        bench.prepare(path)
        self._stub_sample(bench)
        return bench

    @staticmethod
    def _stub_sample(bench):
        path = bench._require_current()
        live = bench._technician._live.get(path)
        if not live:
            return
        sample_engine = live.result.system.engine
        live_engine = live.system.engine
        live_engine.facts.update(sample_engine.facts)
        live_engine.terms.update(sample_engine.terms)
        live_engine.axioms.update(sample_engine.axioms)
        live_engine.theorems.update(sample_engine.theorems)
        live_engine.diffs.update(sample_engine.diffs)
        live_engine.documents.update(sample_engine.documents)
        for sym, val in sample_engine.env.items():
            if sym not in live_engine.env:
                live_engine.env[sym] = val


class TestEvalBindBench(_Base):
    """Bench-level tests for :bind with scopes."""

    def test_interpret_defterm(self):
        b = self._bench('(fact x 1 :origin "test")')
        result = b.interpret('(defterm my-val (+ 1 2))')
        self.assertIsNotNone(result)

    def test_interpret_then_eval(self):
        b = self._bench('(fact x 1 :origin "test")')
        b.interpret('(defterm my-val (+ 10 20))')
        result = b.eval('my-val')
        self.assertEqual(result, 30)

    def test_bind_direct(self):
        b = self._bench('(fact x 1 :origin "test")')
        b.interpret('(defterm tmpl (+ ?a ?b))')
        result = b.eval('(tmpl :bind ((?a 3) (?b 4)))')
        self.assertEqual(result, 7)

    def test_bind_via_axiom(self):
        b = self._bench('(fact x 1 :origin "test")')
        b.interpret('(defterm tmpl (+ ?a ?b))')
        b.interpret('(defterm add-call :origin "callable")')
        b.interpret('(axiom add-call-rule (= (add-call ?x ?y) (tmpl :bind ((?a ?x) (?b ?y)))))')
        result = b.eval('(add-call 100 200)')
        self.assertEqual(result, 300)

    def test_bind_with_scope_lens(self):
        b = self._bench("""
(fact engine.a true :evidence (evidence "doc.txt" :quotes ("Engine handles") :explanation "x"))
(fact engine.b true :evidence (evidence "doc.txt" :quotes ("Facts are stored") :explanation "x"))
""")
        result = b.eval('(count (scope lens (kind "fact")))')
        self.assertGreater(result, 0)

    def test_bind_with_concat_scopes(self):
        """The original use case: concat results from two scopes via :bind."""
        b = self._bench("""
(fact engine.a true :evidence (evidence "doc.txt" :quotes ("Engine handles") :explanation "x"))
(fact engine.b true :evidence (evidence "doc.txt" :quotes ("Facts are stored") :explanation "x"))
""")
        b.interpret('(defterm or-tmpl (std.std.lists.concat (strict ?a) (strict ?b)))')
        b.interpret('(defterm or-call :origin "callable")')
        b.interpret('(axiom or-call-rule (= (or-call ?x ?y) (or-tmpl :bind ((?a ?x) (?b ?y)))))')

        lens_count = b.eval('(count (scope lens (kind "fact")))')
        eval_count = b.eval('(count (scope evaluation (issues)))')

        result = b.eval('(or-call (scope lens (kind "fact")) (scope evaluation (issues)))')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), lens_count + eval_count)


class TestOrFormsBindBenchPg(_Base):
    """Tests for bench_pg or-forms-call using :bind pattern end-to-end."""

    def _bench_with_facts(self):
        return self._bench("""
(fact engine.a true :evidence (evidence "doc.txt" :quotes ("Engine handles") :explanation "x"))
(fact engine.b true :evidence (evidence "doc.txt" :quotes ("Facts are stored") :explanation "x"))
(fact engine.c true :evidence (evidence "doc.txt" :quotes ("Axioms define") :explanation "x"))
""")

    def test_or_forms_call_two_lens_queries(self):
        """or-forms-call merges two lens queries via :bind."""
        b = self._bench_with_facts()
        facts = b.eval('(scope lens (kind "fact"))')
        axioms = b.eval('(scope lens (kind "axiom"))')
        combined = b.eval('(scope ops (or-forms (scope lens (kind "fact")) (scope lens (kind "axiom"))))')
        self.assertIsInstance(combined, list)
        expected = len(facts) + len(axioms)
        self.assertEqual(len(combined), expected)

    def test_or_forms_call_lens_and_evaluation(self):
        """or-forms-call merges lens + evaluation results."""
        b = self._bench_with_facts()
        lens_results = b.eval('(scope lens (kind "fact"))')
        eval_results = b.eval('(scope evaluation (issues))')
        combined = b.eval('(scope ops (or-forms (scope lens (kind "fact")) (scope evaluation (issues))))')
        self.assertIsInstance(combined, list)
        self.assertEqual(len(combined), len(lens_results) + len(eval_results))

    def test_or_forms_call_preserves_tags(self):
        """Merged results keep their original tags (ln, dx)."""
        b = self._bench_with_facts()
        combined = b.eval('(scope ops (or-forms (scope lens (kind "fact")) (scope evaluation (issues))))')
        if not combined:
            return  # nothing to check
        tags = {str(item[0]) for item in combined if isinstance(item, (list, tuple)) and item}
        # Should have at least ln tags from lens results
        self.assertTrue(any("ln" in t for t in tags), f"Expected ln tags in {tags}")

    def test_or_forms_direct_bind_in_ops(self):
        """Direct :bind usage within ops scope."""
        b = self._bench_with_facts()
        result = b.eval(
            '(scope ops (general_ops.or-forms :bind '
            '((?a (scope lens (kind "fact"))) '
            '(?b (scope evaluation (issues))))))'
        )
        self.assertIsInstance(result, list)

    def test_or_forms_empty_second_arg(self):
        """or-forms with empty second scope returns first scope's results."""
        b = self._bench_with_facts()
        # evaluation warnings may be empty — that's fine, concat with empty list
        facts = b.eval('(scope lens (kind "fact"))')
        combined = b.eval('(scope ops (or-forms (scope lens (kind "fact")) (scope evaluation (warnings))))')
        self.assertIsInstance(combined, list)
        self.assertGreaterEqual(len(combined), len(facts))


if __name__ == "__main__":
    unittest.main()
