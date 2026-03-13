"""Tests for std library loading via bench lib_paths.

Any .pltg file loaded through bench can import std modules without
being inside the parseltongue tree. The bench sets lib_paths to
include parseltongue/core/ so (import (quote std.counting)) resolves
to parseltongue/core/std/counting.pltg.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ..inspect.bench import Bench

_BG_RELOAD = "parseltongue.core.inspect.technician.Technician._background_reload"

DOC_TEXT = "Alpha scored 90. Beta scored 45. Gamma scored 80. Delta scored 30."


def _pltg(body: str) -> str:
    """Wrap body with document loading."""
    return f'(load-document "doc.txt" "doc.txt")\n{body}'


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bench_std_")
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
        return bench


class TestStdCounting(_Base):
    """std.counting — count-exists and sum-values via splats."""

    def test_count_exists_all_true(self):
        b = self._bench(
            """
(import (quote std.counting))
(fact a true :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(fact b true :evidence (evidence "doc.txt" :quotes ("Beta scored 45") :explanation "x"))
(fact c true :evidence (evidence "doc.txt" :quotes ("Gamma scored 80") :explanation "x"))
(derive result (counting.count-exists a b c) :using (counting.count-exists a b c))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["result"].wff)
        self.assertEqual(result, 3)

    def test_count_exists_mixed(self):
        b = self._bench(
            """
(import (quote std.counting))
(fact a true :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(fact b false :evidence (evidence "doc.txt" :quotes ("Beta scored 45") :explanation "x"))
(fact c true :evidence (evidence "doc.txt" :quotes ("Gamma scored 80") :explanation "x"))
(derive result (counting.count-exists a b c) :using (counting.count-exists a b c))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["result"].wff)
        self.assertEqual(result, 2)

    def test_count_exists_single(self):
        b = self._bench(
            """
(import (quote std.counting))
(fact a true :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(derive result (counting.count-exists a) :using (counting.count-exists a))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["result"].wff)
        self.assertEqual(result, 1)

    def test_sum_values(self):
        b = self._bench(
            """
(import (quote std.counting))
(fact x 10 :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(fact y 20 :evidence (evidence "doc.txt" :quotes ("Beta scored 45") :explanation "x"))
(fact z 30 :evidence (evidence "doc.txt" :quotes ("Gamma scored 80") :explanation "x"))
(derive result (counting.sum-values x y z) :using (counting.sum-values x y z))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["result"].wff)
        self.assertEqual(result, 60)


class TestStdUtil(_Base):
    """std.util — export and stub."""

    def test_export_identity(self):
        b = self._bench(
            """
(import (quote std.util))
(fact val 42 :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(derive exported (util.export val) :using (util.export val))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["exported"].wff)
        self.assertEqual(result, 42)

    def test_stub_diverges(self):
        """Stub should diverge against any real value in a diff."""
        b = self._bench(
            """
(import (quote std.util))
(fact real-val 42 :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(diff stub-check :replace real-val :with util.stub)
"""
        )
        dx = b.evaluate()
        issues = [i for i in dx.issues() if "stub-check" in i.name]
        self.assertGreater(len(issues), 0)


class TestStdEpistemics(_Base):
    """std.epistemics — witness, joint-status, superpose, collapse."""

    def test_witness_exemplifiable(self):
        b = self._bench(
            """
(import (quote std.epistemics))
(derive status (epistemics.witness epistemics.exemplifiable)
    :using (epistemics.witness epistemics.exemplifiable))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["status"].wff)
        self.assertEqual(str(result), "std.epistemics.exemplifiable")

    def test_joint_status_contagious(self):
        """Hallucinated is contagious — any hallucinated input poisons the group."""
        b = self._bench(
            """
(import (quote std.epistemics))
(derive status
    (epistemics.joint-status epistemics.exemplifiable epistemics.hallucinated epistemics.exemplifiable)
    :using (epistemics.joint-status epistemics.exemplifiable epistemics.hallucinated))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["status"].wff)
        self.assertEqual(str(result), "std.epistemics.hallucinated")

    def test_joint_status_all_exemplifiable(self):
        b = self._bench(
            """
(import (quote std.epistemics))
(derive status
    (epistemics.joint-status epistemics.exemplifiable epistemics.exemplifiable)
    :using (epistemics.joint-status epistemics.exemplifiable))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["status"].wff)
        self.assertEqual(str(result), "std.epistemics.exemplifiable")

    def test_collapse_witnessed(self):
        b = self._bench(
            """
(import (quote std.epistemics))
(derive status
    (epistemics.collapse
        (epistemics.superpose epistemics.hallucinated epistemics.unknown epistemics.exemplifiable)
        epistemics.witnessed)
    :using (epistemics.collapse epistemics.superpose
            epistemics.hallucinated epistemics.unknown epistemics.exemplifiable epistemics.witnessed))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["status"].wff)
        self.assertEqual(str(result), "std.epistemics.exemplifiable")

    def test_collapse_refuted(self):
        b = self._bench(
            """
(import (quote std.epistemics))
(derive status
    (epistemics.collapse
        (epistemics.superpose epistemics.hallucinated epistemics.exemplifiable)
        epistemics.refuted)
    :using (epistemics.collapse epistemics.superpose
            epistemics.hallucinated epistemics.exemplifiable epistemics.refuted))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["status"].wff)
        self.assertEqual(str(result), "std.epistemics.hallucinated")

    def test_count_hallucinated(self):
        b = self._bench(
            """
(import (quote std.epistemics))
(derive count
    (epistemics.count-hallucinated
        epistemics.hallucinated epistemics.exemplifiable epistemics.hallucinated)
    :using (epistemics.count-hallucinated
            epistemics.hallucinated epistemics.exemplifiable))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["count"].wff)
        self.assertEqual(result, 2)


class TestStdLists(_Base):
    """std.lists — cons, concat, filter."""

    def test_cons_single(self):
        b = self._bench(
            """
(import (quote std.lists))
(fact a 42 :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(derive result (lists.cons a) :using (lists.cons a))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["result"].wff)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [42])

    def test_cons_multiple(self):
        b = self._bench(
            """
(import (quote std.lists))
(fact a 1 :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(fact b 2 :evidence (evidence "doc.txt" :quotes ("Beta scored 45") :explanation "x"))
(fact c 3 :evidence (evidence "doc.txt" :quotes ("Gamma scored 80") :explanation "x"))
(derive result (lists.cons a b c) :using (lists.cons lists.cons-prepend a b c))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["result"].wff)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [1, 2, 3])

    def test_concat_two(self):
        b = self._bench(
            """
(import (quote std.lists))
(derive result
    (lists.concat (quote (1 2)) (quote (3 4)))
    :using (lists.concat))
"""
        )
        result = b.engine.evaluate(b.engine.theorems["result"].wff)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [1, 2, 3, 4])


class TestStdFullImport(_Base):
    """(import (quote std.std)) — loads all std modules at once."""

    def test_full_std_import(self):
        """All std modules available after importing std.std."""
        b = self._bench(
            """
(import (quote std.std))

(fact a true :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(fact b false :evidence (evidence "doc.txt" :quotes ("Beta scored 45") :explanation "x"))

(derive count (counting.count-exists a b) :using (counting.count-exists a b))
(derive exported (util.export count) :using (util.export count))
"""
        )
        count = b.engine.evaluate(b.engine.theorems["count"].wff)
        self.assertEqual(count, 1)
        exported = b.engine.evaluate(b.engine.theorems["exported"].wff)
        self.assertEqual(exported, 1)

    def test_std_with_eval(self):
        """Use bench.eval() with std-imported axioms."""
        b = self._bench(
            """
(import (quote std.counting))
(fact x 10 :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(fact y 20 :evidence (evidence "doc.txt" :quotes ("Beta scored 45") :explanation "x"))
"""
        )
        result = b.eval("(counting.sum-values x y)")
        self.assertEqual(result, 30)

    def test_std_in_lens(self):
        """Std axioms appear in lens graph."""
        b = self._bench(
            """
(import (quote std.counting))
(fact a true :evidence (evidence "doc.txt" :quotes ("Alpha scored 90") :explanation "x"))
(derive count (counting.count-exists a) :using (counting.count-exists a))
"""
        )
        lens = b.lens()
        names = lens.find("count")
        self.assertTrue(any("count" in n for n in names))


class TestLibPathsDisabled(_Base):
    """lib_paths=[] disables std resolution."""

    def test_no_lib_paths_fails(self):
        """Without lib_paths, importing std from outside tree fails."""
        path = self._write("fail.pltg", _pltg('(import (quote std.counting))'))
        bench = Bench(bench_dir=self.bench_dir, lib_paths=[])
        bench.prepare(path)
        # Import was swallowed as warning — counting axioms should be absent
        self.assertNotIn("std.counting.count-exists", bench.engine.terms)
