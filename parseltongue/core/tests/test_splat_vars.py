"""Tests for ?... splat pattern variables — variadic matching, substitution, and rewriting."""

import unittest
from unittest.mock import patch

from .. import System
from ..atoms import Symbol
from ..engine import load_source
from ..lang import free_vars, match, substitute


def make_system(**kwargs):
    with patch("builtins.print"):
        return System(**kwargs)


# ==============================================================
# match() with ?... splat
# ==============================================================


class TestMatchSplat(unittest.TestCase):
    """?... splat patterns in match()."""

    def test_splat_matches_remaining(self):
        pat = [Symbol("f"), Symbol("?x"), Symbol("?...rest")]
        expr = [Symbol("f"), 1, 2, 3, 4]
        result = match(pat, expr)
        self.assertEqual(result, {Symbol("?x"): 1, Symbol("?...rest"): [2, 3, 4]})

    def test_splat_matches_empty(self):
        """Splat with zero remaining elements binds to empty list."""
        pat = [Symbol("f"), Symbol("?x"), Symbol("?...rest")]
        expr = [Symbol("f"), 1]
        result = match(pat, expr)
        self.assertEqual(result, {Symbol("?x"): 1, Symbol("?...rest"): []})

    def test_splat_all_elements(self):
        """Splat as only pattern element captures all."""
        pat = [Symbol("f"), Symbol("?...args")]
        expr = [Symbol("f"), 1, 2, 3]
        result = match(pat, expr)
        self.assertEqual(result, {Symbol("?...args"): [1, 2, 3]})

    def test_splat_empty_args(self):
        """Splat captures empty list when no args."""
        pat = [Symbol("f"), Symbol("?...args")]
        expr = [Symbol("f")]
        result = match(pat, expr)
        self.assertEqual(result, {Symbol("?...args"): []})

    def test_splat_too_few_for_fixed(self):
        """Fails when expr doesn't have enough elements for fixed patterns."""
        pat = [Symbol("f"), Symbol("?x"), Symbol("?y"), Symbol("?...rest")]
        expr = [Symbol("f"), 1]
        self.assertIsNone(match(pat, expr))

    def test_splat_consistency(self):
        """Same splat var appearing again must bind to same value."""
        pat = [Symbol("f"), Symbol("?...args")]
        result = match(pat, [Symbol("f"), 1, 2])
        self.assertIsNotNone(result)
        # Match again with existing bindings — same value should succeed
        pat2 = [Symbol("g"), Symbol("?...args")]
        result2 = match(pat2, [Symbol("g"), 1, 2], result)
        self.assertIsNotNone(result2)

    def test_splat_consistency_fails(self):
        """Same splat var binding to different list must fail."""
        pat = [Symbol("f"), Symbol("?...args")]
        result = match(pat, [Symbol("f"), 1, 2])
        pat2 = [Symbol("g"), Symbol("?...args")]
        result2 = match(pat2, [Symbol("g"), 3, 4], result)
        self.assertIsNone(result2)

    def test_splat_with_nested_exprs(self):
        """Splat captures nested sub-expressions as list elements."""
        pat = [Symbol("f"), Symbol("?...args")]
        expr = [Symbol("f"), [Symbol("+"), 1, 2], [Symbol("*"), 3, 4]]
        result = match(pat, expr)
        self.assertEqual(result[Symbol("?...args")], [[Symbol("+"), 1, 2], [Symbol("*"), 3, 4]])

    def test_fixed_head_literal_mismatch(self):
        """Fixed literal before splat must match exactly."""
        pat = [Symbol("f"), Symbol("x"), Symbol("?...rest")]
        expr = [Symbol("f"), Symbol("y"), 1, 2]
        self.assertIsNone(match(pat, expr))


# ==============================================================
# substitute() with ?... splat
# ==============================================================


class TestSubstituteSplat(unittest.TestCase):
    """?... splat substitution — splice into parent list."""

    def test_splice_into_list(self):
        expr = [Symbol("f"), Symbol("?...args")]
        result = substitute(expr, {Symbol("?...args"): [1, 2, 3]})
        self.assertEqual(result, [Symbol("f"), 1, 2, 3])

    def test_splice_empty(self):
        expr = [Symbol("f"), Symbol("?...args")]
        result = substitute(expr, {Symbol("?...args"): []})
        self.assertEqual(result, [Symbol("f")])

    def test_splice_with_fixed(self):
        expr = [Symbol("f"), Symbol("?x"), Symbol("?...rest")]
        result = substitute(expr, {Symbol("?x"): 0, Symbol("?...rest"): [1, 2]})
        self.assertEqual(result, [Symbol("f"), 0, 1, 2])

    def test_splice_nested_exprs(self):
        expr = [Symbol("g"), Symbol("?...args")]
        args = [[Symbol("+"), 1, 2], [Symbol("*"), 3, 4]]
        result = substitute(expr, {Symbol("?...args"): args})
        self.assertEqual(result, [Symbol("g"), [Symbol("+"), 1, 2], [Symbol("*"), 3, 4]])

    def test_unbound_splat_stays(self):
        expr = [Symbol("f"), Symbol("?...args")]
        result = substitute(expr, {})
        self.assertEqual(result, [Symbol("f"), Symbol("?...args")])

    def test_non_list_binding(self):
        """Non-list binding for splat is appended (not spliced)."""
        expr = [Symbol("f"), Symbol("?...x")]
        result = substitute(expr, {Symbol("?...x"): 42})
        self.assertEqual(result, [Symbol("f"), 42])


# ==============================================================
# free_vars() with ?... splat
# ==============================================================


class TestFreeVarsSplat(unittest.TestCase):
    def test_splat_is_free_var(self):
        expr = [Symbol("f"), Symbol("?x"), Symbol("?...rest")]
        self.assertEqual(free_vars(expr), {Symbol("?x"), Symbol("?...rest")})

    def test_splat_alone(self):
        self.assertEqual(free_vars(Symbol("?...x")), {Symbol("?...x")})


# ==============================================================
# Engine integration — axiom rewriting with ?... splat
# ==============================================================


class TestSplatAxiomRewrite(unittest.TestCase):
    """End-to-end: variadic axioms using ?... in the engine."""

    def test_count_true_recursive(self):
        """count-true via base (1 arg) + step (2+ args) axioms."""
        s = make_system()
        e = s.engine
        S = Symbol

        e.introduce_term("count-true", None, origin="primitive")
        # Base case: single arg
        e.introduce_axiom(
            "count-base",
            [S("="), [S("count-true"), S("?x")], [S("+"), [S("if"), S("?x"), 1, 0], 0]],
            origin="count base case",
        )
        # Recursive step: peel off first arg, 2+ args via splat
        e.introduce_axiom(
            "count-step",
            [
                S("="),
                [S("count-true"), S("?x"), S("?y"), S("?...rest")],
                [S("+"), [S("if"), S("?x"), 1, 0], [S("count-true"), S("?y"), S("?...rest")]],
            ],
            origin="count recursive step",
        )

        # Add some facts
        e.set_fact("a", True, origin="test")
        e.set_fact("b", False, origin="test")
        e.set_fact("c", True, origin="test")

        # Evaluate count-true with 3 args
        result = e.evaluate([S("count-true"), S("a"), S("b"), S("c")])
        self.assertEqual(result, 2)

    def test_count_true_single(self):
        s = make_system()
        e = s.engine
        S = Symbol

        e.introduce_term("count-true", None, origin="primitive")
        e.introduce_axiom(
            "count-base", [S("="), [S("count-true"), S("?x")], [S("+"), [S("if"), S("?x"), 1, 0], 0]], origin="base"
        )
        e.introduce_axiom(
            "count-step",
            [
                S("="),
                [S("count-true"), S("?x"), S("?y"), S("?...rest")],
                [S("+"), [S("if"), S("?x"), 1, 0], [S("count-true"), S("?y"), S("?...rest")]],
            ],
            origin="step",
        )

        e.set_fact("x", True, origin="test")
        result = e.evaluate([S("count-true"), S("x")])
        self.assertEqual(result, 1)

    def test_count_true_all_true(self):
        s = make_system()
        e = s.engine
        S = Symbol

        e.introduce_term("count-true", None, origin="primitive")
        e.introduce_axiom(
            "count-base", [S("="), [S("count-true"), S("?x")], [S("+"), [S("if"), S("?x"), 1, 0], 0]], origin="base"
        )
        e.introduce_axiom(
            "count-step",
            [
                S("="),
                [S("count-true"), S("?x"), S("?y"), S("?...rest")],
                [S("+"), [S("if"), S("?x"), 1, 0], [S("count-true"), S("?y"), S("?...rest")]],
            ],
            origin="step",
        )

        e.set_fact("a", True, origin="t")
        e.set_fact("b", True, origin="t")
        e.set_fact("c", True, origin="t")
        e.set_fact("d", True, origin="t")
        e.set_fact("e", True, origin="t")

        result = e.evaluate([S("count-true"), S("a"), S("b"), S("c"), S("d"), S("e")])
        self.assertEqual(result, 5)

    def test_splat_in_derive(self):
        """Derive using an axiom that has splat patterns."""
        s = make_system()
        e = s.engine
        S = Symbol

        e.introduce_term("sum-all", None, origin="primitive")
        e.introduce_axiom("sum-base", [S("="), [S("sum-all"), S("?x")], S("?x")], origin="base")
        e.introduce_axiom(
            "sum-step",
            [
                S("="),
                [S("sum-all"), S("?x"), S("?y"), S("?...rest")],
                [S("+"), S("?x"), [S("sum-all"), S("?y"), S("?...rest")]],
            ],
            origin="step",
        )

        e.set_fact("a", 10, origin="t")
        e.set_fact("b", 20, origin="t")
        e.set_fact("c", 30, origin="t")

        thm = e.derive(
            "total", [S("="), [S("sum-all"), S("a"), S("b"), S("c")], 60], using=["a", "b", "c", "sum-base", "sum-step"]
        )
        self.assertTrue(e.evaluate(thm.wff))

    def test_splat_in_defterm(self):
        """Defterm body using a splat-axiom-based function."""
        s = make_system()
        e = s.engine
        S = Symbol

        e.introduce_term("count-true", None, origin="primitive")
        e.introduce_axiom(
            "count-base", [S("="), [S("count-true"), S("?x")], [S("+"), [S("if"), S("?x"), 1, 0], 0]], origin="base"
        )
        e.introduce_axiom(
            "count-step",
            [
                S("="),
                [S("count-true"), S("?x"), S("?y"), S("?...rest")],
                [S("+"), [S("if"), S("?x"), 1, 0], [S("count-true"), S("?y"), S("?...rest")]],
            ],
            origin="step",
        )

        e.set_fact("p", True, origin="t")
        e.set_fact("q", False, origin="t")
        e.set_fact("r", True, origin="t")

        e.introduce_term("total-count", [S("count-true"), S("p"), S("q"), S("r")], origin="computed")

        result = e.evaluate(S("total-count"))
        self.assertEqual(result, 2)


# ==============================================================
# Syntactic tests — parsed from .pltg source
# ==============================================================

COUNT_TRUE_SOURCE = '''
    (defterm count-true :origin "primitive")
    (axiom count-base (= (count-true ?x) (+ (if ?x 1 0) 0)) :origin "base")
    (axiom count-step
        (= (count-true ?x ?y ?...rest)
           (+ (if ?x 1 0) (count-true ?y ?...rest)))
        :origin "step")
'''

SUM_ALL_SOURCE = '''
    (defterm sum-all :origin "primitive")
    (axiom sum-base (= (sum-all ?x) ?x) :origin "base")
    (axiom sum-step
        (= (sum-all ?x ?y ?...rest)
           (+ ?x (sum-all ?y ?...rest)))
        :origin "step")
'''


class TestSplatSyntactic(unittest.TestCase):
    """?... splat patterns loaded via .pltg syntax."""

    def test_splat_axiom_parses(self):
        s = make_system()
        load_source(s.engine, COUNT_TRUE_SOURCE)
        self.assertIn("count-step", s.engine.axioms)
        fv = free_vars(s.engine.axioms["count-step"].wff)
        self.assertIn(Symbol("?...rest"), fv)
        self.assertIn(Symbol("?x"), fv)
        self.assertIn(Symbol("?y"), fv)

    def test_count_true_recursive_syntax(self):
        s = make_system()
        load_source(
            s.engine,
            COUNT_TRUE_SOURCE + '''
            (fact a true :origin "t")
            (fact b false :origin "t")
            (fact c true :origin "t")
        ''',
        )
        result = s.evaluate([Symbol("count-true"), Symbol("a"), Symbol("b"), Symbol("c")])
        self.assertEqual(result, 2)

    def test_count_true_single_syntax(self):
        s = make_system()
        load_source(
            s.engine,
            COUNT_TRUE_SOURCE + '''
            (fact x true :origin "t")
        ''',
        )
        result = s.evaluate([Symbol("count-true"), Symbol("x")])
        self.assertEqual(result, 1)

    def test_count_true_all_true_syntax(self):
        s = make_system()
        load_source(
            s.engine,
            COUNT_TRUE_SOURCE + '''
            (fact a true :origin "t")
            (fact b true :origin "t")
            (fact c true :origin "t")
            (fact d true :origin "t")
            (fact e true :origin "t")
        ''',
        )
        result = s.evaluate([Symbol("count-true"), Symbol("a"), Symbol("b"), Symbol("c"), Symbol("d"), Symbol("e")])
        self.assertEqual(result, 5)

    def test_sum_all_syntax(self):
        s = make_system()
        load_source(
            s.engine,
            SUM_ALL_SOURCE + '''
            (fact a 10 :origin "t")
            (fact b 20 :origin "t")
            (fact c 30 :origin "t")
        ''',
        )
        result = s.evaluate([Symbol("sum-all"), Symbol("a"), Symbol("b"), Symbol("c")])
        self.assertEqual(result, 60)

    def test_derive_with_splat_syntax(self):
        s = make_system()
        load_source(
            s.engine,
            SUM_ALL_SOURCE + '''
            (fact a 10 :origin "t")
            (fact b 20 :origin "t")
            (fact c 30 :origin "t")
            (derive total (= (sum-all a b c) 60)
                :using (a b c sum-base sum-step))
        ''',
        )
        self.assertIn("total", s.engine.theorems)
        self.assertTrue(s.evaluate(s.engine.theorems["total"].wff))

    def test_defterm_with_splat_syntax(self):
        s = make_system()
        load_source(
            s.engine,
            COUNT_TRUE_SOURCE + '''
            (fact p true :origin "t")
            (fact q false :origin "t")
            (fact r true :origin "t")
            (defterm total-count (count-true p q r) :origin "computed")
        ''',
        )
        result = s.evaluate(Symbol("total-count"))
        self.assertEqual(result, 2)

    def test_sum_single_syntax(self):
        s = make_system()
        load_source(
            s.engine,
            SUM_ALL_SOURCE + '''
            (fact x 42 :origin "t")
        ''',
        )
        result = s.evaluate([Symbol("sum-all"), Symbol("x")])
        self.assertEqual(result, 42)

    def test_count_exists_paired_and_all_true(self):
        """count-exists with (and ...) args — both pairs true → 2."""
        s = make_system()
        load_source(
            s.engine,
            COUNT_TRUE_SOURCE + '''
            (fact doc-a true :origin "t")
            (fact impl-a true :origin "t")
            (fact doc-b true :origin "t")
            (fact impl-b true :origin "t")
            (derive paired
                (count-true (and doc-a impl-a) (and doc-b impl-b))
                :using (count-true doc-a impl-a doc-b impl-b))
        ''',
        )
        self.assertEqual(s.evaluate(s.theorems["paired"].wff), 2)

    def test_count_exists_paired_and_one_false(self):
        """count-exists with (and ...) args — one impl false → 1."""
        s = make_system()
        load_source(
            s.engine,
            COUNT_TRUE_SOURCE + '''
            (fact doc-a true :origin "t")
            (fact impl-a true :origin "t")
            (fact doc-b true :origin "t")
            (fact impl-b false :origin "t")
            (derive paired
                (count-true (and doc-a impl-a) (and doc-b impl-b))
                :using (count-true doc-a impl-a doc-b impl-b))
        ''',
        )
        self.assertEqual(s.evaluate(s.theorems["paired"].wff), 1)


if __name__ == "__main__":
    unittest.main()
