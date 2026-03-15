"""Tests for bench_pg ops via :bind — or-forms, and-forms, not-forms, count-forms, limit-forms."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ..inspect.bench import Bench

_BG_RELOAD = "parseltongue.core.inspect.technician.Technician._background_reload"

DOC_TEXT = "Engine handles evaluation. Facts are stored. Axioms define rules. Terms are names."


def _pltg(body: str) -> str:
    return f'(load-document "doc.txt" "doc.txt")\n{body}'


FACTS = """
(fact engine.a true :evidence (evidence "doc.txt" :quotes ("Engine handles") :explanation "x"))
(fact engine.b true :evidence (evidence "doc.txt" :quotes ("Facts are stored") :explanation "x"))
(fact engine.c true :evidence (evidence "doc.txt" :quotes ("Axioms define") :explanation "x"))
"""


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bench_ops_")
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

    def _bench(self, source: str = FACTS) -> Bench:
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


class TestOrForms(_Base):
    """or-forms via :bind merges two scope results."""

    def test_two_lens_queries(self):
        b = self._bench()
        facts = b.eval('(scope lens (kind "fact"))')
        axioms = b.eval('(scope lens (kind "axiom"))')
        combined = b.eval('(scope ops (or-forms (scope lens (kind "fact")) (scope lens (kind "axiom"))))')
        self.assertIsInstance(combined, list)
        self.assertEqual(len(combined), len(facts) + len(axioms))

    def test_lens_and_evaluation(self):
        b = self._bench()
        lens_r = b.eval('(scope lens (kind "fact"))')
        eval_r = b.eval('(scope evaluation (issues))')
        combined = b.eval('(scope ops (or-forms (scope lens (kind "fact")) (scope evaluation (issues))))')
        self.assertIsInstance(combined, list)
        self.assertEqual(len(combined), len(lens_r) + len(eval_r))

    def test_preserves_tags(self):
        b = self._bench()
        combined = b.eval('(scope ops (or-forms (scope lens (kind "fact")) (scope evaluation (issues))))')
        if not combined:
            return
        tags = {str(item[0]) for item in combined if isinstance(item, (list, tuple)) and item}
        self.assertTrue(any("ln" in t for t in tags), f"Expected ln tags in {tags}")

    def test_empty_second(self):
        b = self._bench()
        facts = b.eval('(scope lens (kind "fact"))')
        combined = b.eval('(scope ops (or-forms (scope lens (kind "fact")) (scope evaluation (warnings))))')
        self.assertIsInstance(combined, list)
        self.assertGreaterEqual(len(combined), len(facts))


class TestAndForms(_Base):
    """and-forms via :bind intersects two scope results by key."""

    def test_same_query_identity(self):
        """Intersecting a query with itself returns the same results."""
        b = self._bench()
        facts = b.eval('(scope lens (kind "fact"))')
        intersected = b.eval('(scope ops (and-forms (scope lens (kind "fact")) (scope lens (kind "fact"))))')
        self.assertIsInstance(intersected, list)
        self.assertEqual(len(intersected), len(facts))

    def test_disjoint_empty(self):
        """Intersecting disjoint sets returns empty."""
        b = self._bench()
        result = b.eval('(scope ops (and-forms (scope lens (kind "fact")) (scope lens (kind "diff"))))')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_subset(self):
        """Intersection with a superset (union of facts+axioms) returns the subset."""
        b = self._bench()
        facts = b.eval('(scope lens (kind "fact"))')
        # Use or-forms within same ops scope to build superset
        intersected = b.eval(
            '(scope ops (and-forms (scope lens (kind "fact"))'
            ' (or-forms (scope lens (kind "fact")) (scope lens (kind "axiom")))))'
        )
        self.assertIsInstance(intersected, list)
        self.assertEqual(len(intersected), len(facts))


class TestNotForms(_Base):
    """not-forms via :bind subtracts second set from first by key."""

    def test_subtract_self_empty(self):
        """Subtracting a set from itself gives empty."""
        b = self._bench()
        result = b.eval('(scope ops (not-forms (scope lens (kind "fact")) (scope lens (kind "fact"))))')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_subtract_disjoint_identity(self):
        """Subtracting disjoint set returns original."""
        b = self._bench()
        facts = b.eval('(scope lens (kind "fact"))')
        result = b.eval('(scope ops (not-forms (scope lens (kind "fact")) (scope lens (kind "diff"))))')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), len(facts))

    def test_subtract_subset(self):
        """Subtracting facts from (facts+axioms) gives only axioms."""
        b = self._bench()
        facts = b.eval('(scope lens (kind "fact"))')
        axioms = b.eval('(scope lens (kind "axiom"))')
        result = b.eval(
            '(scope ops (not-forms'
            ' (or-forms (scope lens (kind "fact")) (scope lens (kind "axiom")))'
            ' (scope lens (kind "fact"))))'
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), len(axioms))


class TestCountForms(_Base):
    """count-forms via :bind counts scope results."""

    def test_count_lens_facts(self):
        b = self._bench()
        facts = b.eval('(scope lens (kind "fact"))')
        count = b.eval('(scope ops (count-forms (scope lens (kind "fact"))))')
        self.assertEqual(count, len(facts))

    def test_count_facts_equals_three(self):
        """count-forms returns correct count independently."""
        b = self._bench()
        count = b.eval('(scope ops (count-forms (scope lens (kind "fact"))))')
        self.assertEqual(count, 3)


class TestLimitForms(_Base):
    """limit-forms via :bind takes first N from scope results."""

    def test_limit_zero(self):
        b = self._bench()
        result = b.eval('(scope ops (limit-forms 0 (scope lens (kind "fact"))))')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_limit_two(self):
        b = self._bench()
        result = b.eval('(scope ops (limit-forms 2 (scope lens (kind "fact"))))')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_limit_exceeds(self):
        """Limiting beyond list length returns entire list."""
        b = self._bench()
        facts = b.eval('(scope lens (kind "fact"))')
        result = b.eval(f'(scope ops (limit-forms {len(facts) + 10} (scope lens (kind "fact"))))')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), len(facts))


if __name__ == "__main__":
    unittest.main()
