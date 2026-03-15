"""Tests for ?-variable pattern matching in match(), substitute(), free_vars()."""

import unittest
from unittest.mock import patch

from .. import System
from ..atoms import Symbol
from ..engine import load_source
from ..lang import free_vars, match, substitute


def make_system(**kwargs):
    with patch("builtins.print"):
        return System(**kwargs)


class TestMatchVar(unittest.TestCase):
    """? pattern variables — single-element matching."""

    def test_single_var(self):
        pat = [Symbol("="), Symbol("?x"), 0]
        expr = [Symbol("="), 42, 0]
        result = match(pat, expr)
        self.assertEqual(result, {Symbol("?x"): 42})

    def test_multiple_vars(self):
        pat = [Symbol("+"), Symbol("?a"), Symbol("?b")]
        expr = [Symbol("+"), 3, 7]
        result = match(pat, expr)
        self.assertEqual(result, {Symbol("?a"): 3, Symbol("?b"): 7})

    def test_nested_expr(self):
        pat = [Symbol("="), [Symbol("+"), Symbol("?n"), Symbol("zero")], Symbol("?n")]
        expr = [Symbol("="), [Symbol("+"), 5, Symbol("zero")], 5]
        result = match(pat, expr)
        self.assertEqual(result, {Symbol("?n"): 5})

    def test_var_consistency(self):
        """Same ?-var appearing twice must bind to same value."""
        pat = [Symbol("="), Symbol("?x"), Symbol("?x")]
        expr = [Symbol("="), 5, 5]
        self.assertIsNotNone(match(pat, expr))

    def test_var_inconsistency_fails(self):
        """Same ?-var binding to different values must fail."""
        pat = [Symbol("="), Symbol("?x"), Symbol("?x")]
        expr = [Symbol("="), 5, 7]
        self.assertIsNone(match(pat, expr))

    def test_no_match_different_lengths(self):
        pat = [Symbol("+"), Symbol("?a"), Symbol("?b")]
        expr = [Symbol("+"), 1]
        self.assertIsNone(match(pat, expr))

    def test_no_match_different_literal(self):
        pat = [Symbol("+"), Symbol("?a"), 0]
        expr = [Symbol("+"), 1, 1]
        self.assertIsNone(match(pat, expr))

    def test_non_list_no_match(self):
        pat = [Symbol("?x")]
        self.assertIsNone(match(pat, 42))

    def test_var_binds_to_list(self):
        """A ?-var can bind to an entire sub-expression."""
        pat = [Symbol("f"), Symbol("?body")]
        expr = [Symbol("f"), [Symbol("+"), 1, 2]]
        result = match(pat, expr)
        self.assertEqual(result, {Symbol("?body"): [Symbol("+"), 1, 2]})


class TestSubstituteVar(unittest.TestCase):
    """? pattern variable substitution."""

    def test_simple(self):
        expr = [Symbol("="), Symbol("?n"), 0]
        result = substitute(expr, {Symbol("?n"): 5})
        self.assertEqual(result, [Symbol("="), 5, 0])

    def test_nested(self):
        expr = [Symbol("+"), [Symbol("*"), Symbol("?a"), 2], Symbol("?b")]
        result = substitute(expr, {Symbol("?a"): 3, Symbol("?b"): 7})
        self.assertEqual(result, [Symbol("+"), [Symbol("*"), 3, 2], 7])

    def test_unbound_vars_stay(self):
        expr = [Symbol("+"), Symbol("?x"), Symbol("?y")]
        result = substitute(expr, {Symbol("?x"): 10})
        self.assertEqual(result, [Symbol("+"), 10, Symbol("?y")])


class TestFreeVarsVar(unittest.TestCase):
    """free_vars() with ? pattern variables."""

    def test_single(self):
        expr = [Symbol("="), Symbol("?x"), 0]
        self.assertEqual(free_vars(expr), {Symbol("?x")})

    def test_multiple(self):
        expr = [Symbol("+"), Symbol("?a"), Symbol("?b")]
        self.assertEqual(free_vars(expr), {Symbol("?a"), Symbol("?b")})

    def test_nested(self):
        expr = [Symbol("="), [Symbol("+"), Symbol("?n"), Symbol("zero")], Symbol("?n")]
        self.assertEqual(free_vars(expr), {Symbol("?n")})

    def test_no_vars(self):
        expr = [Symbol("+"), 1, 2]
        self.assertEqual(free_vars(expr), set())

    def test_non_list(self):
        self.assertEqual(free_vars(Symbol("?x")), {Symbol("?x")})
        self.assertEqual(free_vars(42), set())


# ==============================================================
# Syntactic tests — parsed from .pltg source
# ==============================================================


class TestPatternVarsSyntactic(unittest.TestCase):
    """? pattern variables loaded via .pltg syntax."""

    def test_axiom_with_var_parses(self):
        s = make_system()
        load_source(
            s.engine,
            '''
            (defterm double :origin "primitive")
            (axiom double-rule (= (double ?x) (+ ?x ?x)) :origin "definition")
        ''',
        )
        self.assertIn("double-rule", s.engine.axioms)
        self.assertEqual(free_vars(s.engine.axioms["double-rule"].wff), {Symbol("?x")})

    def test_axiom_rewrite_via_syntax(self):
        s = make_system()
        load_source(
            s.engine,
            '''
            (defterm double :origin "primitive")
            (axiom double-rule (= (double ?x) (+ ?x ?x)) :origin "definition")
            (fact n 5 :origin "test")
        ''',
        )
        result = s.evaluate([Symbol("double"), Symbol("n")])
        self.assertEqual(result, 10)

    def test_derive_with_var_axiom(self):
        s = make_system()
        load_source(
            s.engine,
            '''
            (defterm double :origin "primitive")
            (axiom double-rule (= (double ?x) (+ ?x ?x)) :origin "definition")
            (fact n 7 :origin "test")
            (derive double-7 (= (double n) 14) :using (double-rule n))
        ''',
        )
        self.assertIn("double-7", s.engine.theorems)
        self.assertTrue(s.evaluate(s.engine.theorems["double-7"].wff))

    def test_nested_var_axiom(self):
        s = make_system()
        load_source(
            s.engine,
            '''
            (defterm add-zero :origin "primitive")
            (fact zero 0 :origin "definition")
            (axiom add-zero-rule (= (add-zero (+ ?n zero)) ?n) :origin "identity")
        ''',
        )
        ax = s.engine.axioms["add-zero-rule"]
        self.assertEqual(free_vars(ax.wff), {Symbol("?n")})

    def test_multi_var_axiom(self):
        s = make_system()
        load_source(
            s.engine,
            '''
            (defterm swap :origin "primitive")
            (axiom swap-rule (= (swap ?a ?b) (swap ?b ?a)) :origin "commutativity")
        ''',
        )
        ax = s.engine.axioms["swap-rule"]
        self.assertEqual(free_vars(ax.wff), {Symbol("?a"), Symbol("?b")})

    def test_defterm_using_var_axiom(self):
        s = make_system()
        load_source(
            s.engine,
            '''
            (defterm double :origin "primitive")
            (axiom double-rule (= (double ?x) (+ ?x ?x)) :origin "definition")
            (fact val 3 :origin "test")
            (defterm doubled-val (double val) :origin "computed")
        ''',
        )
        result = s.evaluate(Symbol("doubled-val"))
        self.assertEqual(result, 6)


if __name__ == "__main__":
    unittest.main()
