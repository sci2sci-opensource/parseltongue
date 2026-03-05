"""Tests for Parseltongue runtime engine (engine.py)."""

import operator
import unittest
from unittest.mock import patch

from .. import (
    ADD,
    AND,
    ARITHMETIC_OPS,
    COMPARISON_OPS,
    DEFAULT_OPERATORS,
    DIV,
    ENGINE_DOCS,
    EQ,
    GE,
    GT,
    IMPLIES,
    LE,
    LOGIC_OPS,
    LT,
    MOD,
    MUL,
    NE,
    NOT,
    OR,
    SUB,
    Evidence,
    Symbol,
    System,
)

# Reusable sample document text for evidence verification tests.
SAMPLE_DOC = "Q3 revenue was $15M, up 15% year-over-year. Operating margin improved to 22%."


def make_system(**kwargs):
    """Create a System with print suppressed."""
    with patch("builtins.print"):
        return System(**kwargs)


def quiet(fn, *args, **kwargs):
    """Run a function with print suppressed."""
    with patch("builtins.print"):
        return fn(*args, **kwargs)


# ==============================================================
# Evaluation
# ==============================================================


class TestEvaluation(unittest.TestCase):
    def setUp(self):
        self.s = make_system()

    def test_add(self):
        self.assertEqual(self.s.evaluate([Symbol("+"), 2, 3]), 5)

    def test_sub(self):
        self.assertEqual(self.s.evaluate([Symbol("-"), 10, 4]), 6)

    def test_mul(self):
        self.assertEqual(self.s.evaluate([Symbol("*"), 3, 7]), 21)

    def test_div(self):
        self.assertEqual(self.s.evaluate([Symbol("/"), 10, 2]), 5.0)

    def test_mod(self):
        self.assertEqual(self.s.evaluate([Symbol("mod"), 10, 3]), 1)

    def test_gt(self):
        self.assertTrue(self.s.evaluate([Symbol(">"), 5, 3]))
        self.assertFalse(self.s.evaluate([Symbol(">"), 3, 5]))

    def test_lt(self):
        self.assertTrue(self.s.evaluate([Symbol("<"), 2, 8]))

    def test_ge(self):
        self.assertTrue(self.s.evaluate([Symbol(">="), 5, 5]))
        self.assertTrue(self.s.evaluate([Symbol(">="), 6, 5]))

    def test_le(self):
        self.assertTrue(self.s.evaluate([Symbol("<="), 5, 5]))

    def test_eq(self):
        self.assertTrue(self.s.evaluate([Symbol("="), 5, 5]))
        self.assertFalse(self.s.evaluate([Symbol("="), 5, 6]))

    def test_ne(self):
        self.assertTrue(self.s.evaluate([Symbol("!="), 5, 6]))

    def test_and(self):
        self.assertFalse(self.s.evaluate([Symbol("and"), True, False]))
        self.assertTrue(self.s.evaluate([Symbol("and"), True, True]))

    def test_and_variadic(self):
        self.assertTrue(self.s.evaluate([Symbol("and"), True, True, True]))
        self.assertFalse(self.s.evaluate([Symbol("and"), True, True, False]))
        self.assertTrue(self.s.evaluate([Symbol("and"), True, True, True, True, True]))
        self.assertFalse(self.s.evaluate([Symbol("and"), True, True, True, True, False]))

    def test_or(self):
        self.assertTrue(self.s.evaluate([Symbol("or"), False, True]))
        self.assertFalse(self.s.evaluate([Symbol("or"), False, False]))

    def test_or_variadic(self):
        self.assertFalse(self.s.evaluate([Symbol("or"), False, False, False]))
        self.assertTrue(self.s.evaluate([Symbol("or"), False, False, True]))
        self.assertTrue(self.s.evaluate([Symbol("or"), False, False, False, False, True]))

    def test_not(self):
        self.assertFalse(self.s.evaluate([Symbol("not"), True]))
        self.assertTrue(self.s.evaluate([Symbol("not"), False]))

    def test_implies(self):
        self.assertTrue(self.s.evaluate([Symbol("implies"), False, True]))
        self.assertTrue(self.s.evaluate([Symbol("implies"), True, True]))
        self.assertFalse(self.s.evaluate([Symbol("implies"), True, False]))

    def test_if_true(self):
        expr = [Symbol("if"), True, 42, 0]
        self.assertEqual(self.s.evaluate(expr), 42)

    def test_if_false(self):
        expr = [Symbol("if"), False, 42, 0]
        self.assertEqual(self.s.evaluate(expr), 0)

    def test_if_computed_condition(self):
        expr = [Symbol("if"), [Symbol(">"), 5, 3], 1, 0]
        self.assertEqual(self.s.evaluate(expr), 1)

    def test_if_nested(self):
        expr = [Symbol("if"), True, [Symbol("if"), False, 1, 2], 3]
        self.assertEqual(self.s.evaluate(expr), 2)

    def test_if_only_evaluates_taken_branch(self):
        """The branch not taken should not be evaluated."""
        # Symbol 'boom' doesn't exist — if evaluated it would raise NameError
        expr = [Symbol("if"), True, 42, Symbol("boom")]
        self.assertEqual(self.s.evaluate(expr), 42)
        expr = [Symbol("if"), False, Symbol("boom"), 99]
        self.assertEqual(self.s.evaluate(expr), 99)

    def test_if_with_expressions_in_branches(self):
        expr = [Symbol("if"), [Symbol("<"), 2, 8], [Symbol("+"), 10, 20], [Symbol("*"), 5, 5]]
        self.assertEqual(self.s.evaluate(expr), 30)

    def test_let(self):
        expr = [Symbol("let"), [[Symbol("x"), 10]], [Symbol("+"), Symbol("x"), 5]]
        self.assertEqual(self.s.evaluate(expr), 15)

    def test_let_multiple_bindings(self):
        expr = [Symbol("let"), [[Symbol("a"), 3], [Symbol("b"), 7]], [Symbol("+"), Symbol("a"), Symbol("b")]]
        self.assertEqual(self.s.evaluate(expr), 10)

    def test_let_sequential_bindings(self):
        """Later bindings can reference earlier ones."""
        expr = [Symbol("let"), [[Symbol("x"), 5], [Symbol("y"), [Symbol("+"), Symbol("x"), 1]]], Symbol("y")]
        self.assertEqual(self.s.evaluate(expr), 6)

    def test_let_shadows_outer(self):
        """Let bindings shadow the outer environment."""
        self.s.engine.env[Symbol("x")] = 100
        expr = [Symbol("let"), [[Symbol("x"), 1]], Symbol("x")]
        self.assertEqual(self.s.evaluate(expr), 1)
        # Outer env unchanged
        self.assertEqual(self.s.engine.env[Symbol("x")], 100)

    def test_let_nested(self):
        expr = [
            Symbol("let"),
            [[Symbol("x"), 2]],
            [Symbol("let"), [[Symbol("y"), 3]], [Symbol("*"), Symbol("x"), Symbol("y")]],
        ]
        self.assertEqual(self.s.evaluate(expr), 6)

    def test_let_computed_values(self):
        expr = [Symbol("let"), [[Symbol("x"), [Symbol("*"), 3, 4]]], [Symbol("+"), Symbol("x"), 1]]
        self.assertEqual(self.s.evaluate(expr), 13)

    def test_nested(self):
        expr = [Symbol("+"), [Symbol("*"), 2, 3], [Symbol("-"), 10, 4]]
        self.assertEqual(self.s.evaluate(expr), 12)

    def test_unresolved_symbol(self):
        with self.assertRaises(NameError):
            self.s.evaluate(Symbol("unknown"))

    def test_literal_passthrough(self):
        self.assertEqual(self.s.evaluate(42), 42)
        self.assertEqual(self.s.evaluate(3.14), 3.14)
        self.assertEqual(self.s.evaluate(True), True)

    def test_local_env(self):
        result = self.s.evaluate([Symbol("+"), Symbol("x"), 1], {Symbol("x"): 10})
        self.assertEqual(result, 11)


# ==============================================================
# Facts & Overridable Flag
# ==============================================================


class TestFacts(unittest.TestCase):
    def test_set_and_retrieve_fact(self):
        s = make_system()
        quiet(s.set_fact, "x", 42, "test")
        self.assertEqual(s.facts["x"].wff, 42)
        self.assertEqual(s.evaluate(Symbol("x")), 42)

    def test_duplicate_fact_strict_raises(self):
        s = make_system(overridable=False)
        quiet(s.set_fact, "x", 1, "first")
        with self.assertRaises(ValueError):
            quiet(s.set_fact, "x", 2, "second")

    def test_duplicate_fact_overridable(self):
        s = make_system(overridable=True)
        quiet(s.set_fact, "x", 1, "first")
        quiet(s.set_fact, "x", 2, "second")
        self.assertEqual(s.facts["x"].wff, 2)
        self.assertEqual(s.evaluate(Symbol("x")), 2)

    def test_fact_with_evidence(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Q3 revenue was $15M"])
        quiet(s.set_fact, "rev", 15.0, ev)
        self.assertTrue(ev.verified)

    def test_fact_with_bad_evidence(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["This quote does not exist at all"])
        quiet(s.set_fact, "bad", 999, ev)
        self.assertFalse(ev.verified)


# ==============================================================
# Axioms
# ==============================================================


class TestAxioms(unittest.TestCase):
    def test_introduce_axiom_string_origin(self):
        s = make_system()
        ax = quiet(s.introduce_axiom, "a1", [Symbol(">"), Symbol("?x"), 0], "manual")
        self.assertEqual(ax.name, "a1")
        self.assertEqual(ax.origin, "manual")
        self.assertIn("a1", s.axioms)

    def test_introduce_axiom_evidence_origin(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Q3 revenue was $15M"])
        ax = quiet(s.introduce_axiom, "a2", [Symbol(">"), Symbol("?r"), 0], ev)
        self.assertIsInstance(ax.origin, Evidence)

    def test_unknown_symbol_in_wff(self):
        s = make_system()
        # ?x is a valid pattern variable, but 'unknown' is not defined in the system.
        with self.assertRaises(NameError):
            quiet(s.introduce_axiom, "bad", [Symbol(">"), Symbol("?x"), Symbol("unknown")], "test")

    def test_axiom_with_if_in_wff(self):
        """Axioms can use special forms like 'if' in their WFF."""
        s = make_system()
        ax = quiet(
            s.introduce_axiom,
            "a3",
            [Symbol("="), [Symbol("if"), [Symbol(">"), Symbol("?x"), 0], Symbol("?y"), 0], Symbol("?y")],
            "test",
        )
        self.assertIn("a3", s.axioms)

    def test_axiom_with_let_in_wff(self):
        """Axioms can use 'let' in their WFF."""
        s = make_system()
        ax = quiet(
            s.introduce_axiom,
            "a4",
            [Symbol("="), [Symbol("let"), [[Symbol("z"), Symbol("?x")]], [Symbol("+"), Symbol("z"), 1]], 6],
            "test",
        )
        self.assertIn("a4", s.axioms)

    def test_axiom_rejects_ground_wff(self):
        """Ground axioms (no ?-variables) must be rejected with ValueError."""
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        with self.assertRaises(ValueError) as ctx:
            quiet(s.introduce_axiom, "bad", [Symbol(">"), Symbol("x"), 0], "test")
        self.assertIn("no ?-variables", str(ctx.exception))


# ==============================================================
# Terms
# ==============================================================


class TestTerms(unittest.TestCase):
    def test_introduce_term(self):
        s = make_system()
        quiet(s.set_fact, "x", 10, "test")
        quiet(s.set_fact, "y", 20, "test")
        quiet(s.introduce_term, "total", [Symbol("+"), Symbol("x"), Symbol("y")], "test")
        self.assertIn("total", s.terms)
        result = s.evaluate(s.terms["total"].definition)
        self.assertEqual(result, 30)

    def test_term_resolves_as_symbol(self):
        """Terms auto-resolve when referenced as bare symbols."""
        s = make_system()
        quiet(s.set_fact, "a", 3, "test")
        quiet(s.set_fact, "b", 4, "test")
        quiet(s.introduce_term, "sum_ab", [Symbol("+"), Symbol("a"), Symbol("b")], "test")
        # Term should auto-resolve in evaluation
        result = s.evaluate(Symbol("sum_ab"))
        self.assertEqual(result, 7)


# ==============================================================
# Derivation & Fabrication Propagation
# ==============================================================


class TestDerivation(unittest.TestCase):
    def test_derive_grounded(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Q3 revenue was $15M"])
        quiet(s.set_fact, "rev", 15.0, ev)
        thm = quiet(s.derive, "d1", [Symbol(">"), Symbol("rev"), 0], ["rev"])
        self.assertEqual(thm.origin, "derived")
        self.assertEqual(thm.derivation, ["rev"])

    def test_derive_unverified_is_fabrication(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Nonexistent quote xyz"])
        quiet(s.set_fact, "bad", 999, ev)
        thm = quiet(s.derive, "d2", [Symbol(">"), Symbol("bad"), 0], ["bad"])
        self.assertIn("potential fabrication", thm.origin)
        self.assertIn("bad", thm.origin)

    def test_derive_false_is_fabrication(self):
        """A derivation that evaluates to False is accepted but marked as fabrication."""
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        thm = quiet(s.derive, "bad_d", [Symbol("<"), Symbol("x"), 0], ["x"])
        self.assertIn("potential fabrication", thm.origin)
        self.assertIn("does not hold", thm.origin)

    def test_fabrication_chain(self):
        """Deriving from an already-fabricated theorem propagates fabrication."""
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Nonexistent quote xyz"])
        quiet(s.set_fact, "bad", 999, ev)
        quiet(s.derive, "tainted", [Symbol(">"), Symbol("bad"), 0], ["bad"])
        # Now derive from tainted — WFF still references bad so it must be in :using
        thm2 = quiet(s.derive, "double_tainted", [Symbol(">"), Symbol("bad"), 0], ["tainted", "bad"])
        self.assertIn("potential fabrication", thm2.origin)

    def test_derive_unknown_source_raises(self):
        s = make_system()
        with self.assertRaises(ValueError):
            quiet(s.derive, "d", [Symbol(">"), 1, 0], ["nonexistent"])


# ==============================================================
# Restricted vs Unrestricted Derive (strict_derive flag)
# ==============================================================


class TestRestrictedDerive(unittest.TestCase):
    """Tests that derive enforces :using in strict mode and bypasses in lax mode."""

    def test_strict_rejects_symbol_not_in_using(self):
        """Strict mode (default): WFF references a fact not listed in :using → NameError."""
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        # WFF uses both a and b, but :using only lists a
        with self.assertRaises(NameError):
            quiet(s.derive, "bad", [Symbol(">"), Symbol("b"), Symbol("a")], ["a"])

    def test_lax_allows_symbol_not_in_using(self):
        """Lax mode: same derivation passes because global env is used."""
        s = make_system(strict_derive=False)
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        thm = quiet(s.derive, "ok", [Symbol(">"), Symbol("b"), Symbol("a")], ["a"])
        self.assertEqual(thm.origin, "derived")

    def test_strict_rejects_term_not_in_using(self):
        """Strict mode (default): WFF references a term not in :using → NameError."""
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.introduce_term, "double_x", [Symbol("*"), Symbol("x"), 2], "test")
        # double_x is defined but not in :using
        with self.assertRaises(NameError):
            quiet(s.derive, "bad", [Symbol(">"), Symbol("double_x"), 0], ["x"])

    def test_strict_allows_term_in_using(self):
        """Strict mode (default): term listed in :using resolves fine."""
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.introduce_term, "double_x", [Symbol("*"), Symbol("x"), 2], "test")
        thm = quiet(s.derive, "ok", [Symbol(">"), Symbol("double_x"), 0], ["x", "double_x"])
        self.assertEqual(thm.origin, "derived")

    def test_strict_scopes_axiom_rewrite(self):
        """Strict mode (default): axiom rewrite rules only apply if axiom is in :using."""
        s = make_system()
        quiet(s.set_fact, "p", 3, "test")
        quiet(s.set_fact, "q", 4, "test")
        quiet(
            s.introduce_axiom,
            "comm",
            [EQ, [Symbol("+"), Symbol("?a"), Symbol("?b")], [Symbol("+"), Symbol("?b"), Symbol("?a")]],
            "test",
        )
        # Derive using the axiom — should work
        thm = quiet(
            s.derive,
            "ok",
            [EQ, [Symbol("+"), Symbol("p"), Symbol("q")], [Symbol("+"), Symbol("q"), Symbol("p")]],
            ["p", "q", "comm"],
        )
        self.assertEqual(thm.origin, "derived")

    def test_strict_rejects_axiom_not_in_using(self):
        """Strict mode: axiom not in :using — rewrite doesn't fire."""
        s = make_system()
        quiet(s.introduce_term, "plus", None, "test")
        quiet(s.set_fact, "a", 3, "test")
        quiet(s.set_fact, "b", 4, "test")
        quiet(
            s.introduce_axiom,
            "comm",
            [EQ, [Symbol("plus"), Symbol("?a"), Symbol("?b")], [Symbol("plus"), Symbol("?b"), Symbol("?a")]],
            "test",
        )
        # comm exists but not in :using — rewrite can't prove this
        thm = quiet(
            s.derive,
            "no_comm",
            [EQ, [Symbol("plus"), Symbol("a"), Symbol("b")], [Symbol("plus"), Symbol("b"), Symbol("a")]],
            ["plus", "a", "b"],
        )
        self.assertIn("does not hold", thm.origin)

    def test_strict_axiom_in_using_enables_rewrite(self):
        """Strict mode: same derivation succeeds when axiom IS in :using."""
        s = make_system()
        quiet(s.introduce_term, "plus", None, "test")
        quiet(s.set_fact, "a", 3, "test")
        quiet(s.set_fact, "b", 4, "test")
        quiet(
            s.introduce_axiom,
            "comm",
            [EQ, [Symbol("plus"), Symbol("?a"), Symbol("?b")], [Symbol("plus"), Symbol("?b"), Symbol("?a")]],
            "test",
        )
        # comm in :using — rewrite fires
        thm = quiet(
            s.derive,
            "with_comm",
            [EQ, [Symbol("plus"), Symbol("a"), Symbol("b")], [Symbol("plus"), Symbol("b"), Symbol("a")]],
            ["plus", "a", "b", "comm"],
        )
        self.assertEqual(thm.origin, "derived")

    def test_lax_ignores_using_for_eval(self):
        """Lax mode: all system facts/terms available regardless of :using."""
        s = make_system(strict_derive=False)
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 3, "test")
        quiet(s.set_fact, "c", 7, "test")
        # WFF uses a, b, c but :using only lists a
        thm = quiet(
            s.derive,
            "lax_ok",
            [Symbol("="), Symbol("a"), [Symbol("+"), Symbol("b"), Symbol("c")]],
            ["a"],
        )
        self.assertEqual(thm.origin, "derived")

    def test_strict_default(self):
        """System defaults to strict_derive=True."""
        s = make_system()
        self.assertTrue(s.engine.strict_derive)


# ==============================================================
# Transitive :using expansion
# ==============================================================


class TestTransitiveUsing(unittest.TestCase):
    """Tests that :using transitively pulls in dependencies from axioms and terms."""

    def test_axiom_deps_are_transparent(self):
        """Axiom references 'plus' — derive only lists axiom, plus is auto-included."""
        s = make_system()
        quiet(s.introduce_term, "plus", None, "test")
        quiet(s.set_fact, "a", 3, "test")
        quiet(s.set_fact, "b", 4, "test")
        quiet(
            s.introduce_axiom,
            "comm",
            [EQ, [Symbol("plus"), Symbol("?x"), Symbol("?y")], [Symbol("plus"), Symbol("?y"), Symbol("?x")]],
            "test",
        )
        # :using only lists comm, a, b — plus is pulled in from comm's WFF
        thm = quiet(
            s.derive,
            "ok",
            [EQ, [Symbol("plus"), Symbol("a"), Symbol("b")], [Symbol("plus"), Symbol("b"), Symbol("a")]],
            ["comm", "a", "b"],
        )
        self.assertEqual(thm.origin, "derived")

    def test_term_deps_are_transparent(self):
        """Term 'total' depends on facts x, y — derive only lists total."""
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.set_fact, "y", 3, "test")
        quiet(s.introduce_term, "total", [Symbol("+"), Symbol("x"), Symbol("y")], "test")
        # :using only lists total — x and y are pulled in from total's definition
        thm = quiet(
            s.derive,
            "ok",
            [Symbol(">"), Symbol("total"), 0],
            ["total"],
        )
        self.assertEqual(thm.origin, "derived")

    def test_chain_expansion(self):
        """term A depends on term B which depends on fact c — all resolved."""
        s = make_system()
        quiet(s.set_fact, "c", 10, "test")
        quiet(s.introduce_term, "doubled", [Symbol("*"), Symbol("c"), 2], "test")
        quiet(s.introduce_term, "final", [Symbol("+"), Symbol("doubled"), 1], "test")
        # :using only lists final — doubled and c are pulled in transitively
        thm = quiet(
            s.derive,
            "ok",
            [Symbol(">"), Symbol("final"), 0],
            ["final"],
        )
        self.assertEqual(thm.origin, "derived")

    def test_axiom_brings_in_its_terms(self):
        """Axiom WFF references a term — that term and its deps are included."""
        s = make_system()
        quiet(s.introduce_term, "f", None, "test")
        quiet(s.set_fact, "n", 5, "test")
        quiet(
            s.introduce_axiom,
            "f-def",
            [EQ, [Symbol("f"), Symbol("?x")], [Symbol("*"), Symbol("?x"), 2]],
            "test",
        )
        # :using lists f-def and n — f is pulled in from f-def's WFF
        thm = quiet(
            s.derive,
            "ok",
            [EQ, [Symbol("f"), Symbol("n")], 10],
            ["f-def", "n"],
        )
        self.assertEqual(thm.origin, "derived")

    def test_unknown_deps_are_ignored(self):
        """Symbols in axiom WFF that aren't in the system (operators like +) don't cause errors."""
        s = make_system()
        quiet(s.set_fact, "x", 7, "test")
        quiet(
            s.introduce_axiom,
            "pos",
            [Symbol(">"), Symbol("?v"), 0],
            "test",
        )
        # + and > are operators, not facts/terms — they're already callable in env
        thm = quiet(
            s.derive,
            "ok",
            [Symbol(">"), Symbol("x"), 0],
            ["pos", "x"],
        )
        self.assertEqual(thm.origin, "derived")


# ==============================================================
# Evidence Verification & Manual Override
# ==============================================================


class TestVerification(unittest.TestCase):
    def test_document_registry(self):
        s = make_system()
        quiet(s.register_document, "Doc", "some text")
        self.assertIn("Doc", s.documents)
        self.assertEqual(s.documents["Doc"], "some text")

    def test_verify_manual_evidence_origin(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Nonexistent quote"])
        quiet(s.set_fact, "x", 1, ev)
        self.assertFalse(ev.is_grounded)
        quiet(s.verify_manual, "x")
        self.assertTrue(ev.verify_manual)
        self.assertTrue(ev.is_grounded)

    def test_verify_manual_string_origin(self):
        s = make_system()
        quiet(s.set_fact, "x", 1, "plain origin")
        quiet(s.verify_manual, "x")
        origin = s.facts["x"].origin
        self.assertIsInstance(origin, Evidence)
        self.assertTrue(origin.verify_manual)
        self.assertTrue(origin.is_grounded)

    def test_verify_manual_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            quiet(s.verify_manual, "nonexistent")

    def test_verify_manual_on_axiom(self):
        s = make_system()
        quiet(s.introduce_axiom, "a1", [Symbol(">"), Symbol("?x"), 0], "string origin")
        quiet(s.verify_manual, "a1")
        self.assertIsInstance(s.axioms["a1"].origin, Evidence)
        self.assertTrue(s.axioms["a1"].origin.is_grounded)

    def test_verify_manual_on_term(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.introduce_term, "t1", [Symbol("+"), Symbol("x"), 1], "string origin")
        quiet(s.verify_manual, "t1")
        self.assertIsInstance(s.terms["t1"].origin, Evidence)
        self.assertTrue(s.terms["t1"].origin.is_grounded)


# ==============================================================
# Instantiation
# ==============================================================


class TestInstantiate(unittest.TestCase):
    def test_instantiate_axiom(self):
        s = make_system()
        quiet(s.introduce_axiom, "add-id", [Symbol("="), [Symbol("+"), Symbol("?n"), 0], Symbol("?n")], "test")
        result = s.instantiate("add-id", {Symbol("?n"): 5})
        self.assertEqual(result, [Symbol("="), [Symbol("+"), 5, 0], 5])

    def test_instantiate_term(self):
        s = make_system()
        quiet(s.introduce_term, "sum-template", [Symbol("+"), Symbol("?a"), Symbol("?b")], "test")
        result = s.instantiate("sum-template", {Symbol("?a"): 3, Symbol("?b"): 7})
        self.assertEqual(result, [Symbol("+"), 3, 7])

    def test_instantiate_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            s.instantiate("nonexistent", {Symbol("?n"): 5})

    def test_parameterized_axiom_accepted(self):
        """Axiom with ?-vars passes _check_wff."""
        s = make_system()
        ax = quiet(s.introduce_axiom, "add-id", [Symbol("="), [Symbol("+"), Symbol("?n"), 0], Symbol("?n")], "test")
        self.assertIn("add-id", s.axioms)


# ==============================================================
# Retract & Rederive
# ==============================================================


class TestRetract(unittest.TestCase):
    def test_retract_fact(self):
        s = make_system()
        quiet(s.set_fact, "x", 1, "test")
        quiet(s.retract, "x")
        self.assertNotIn("x", s.facts)
        self.assertNotIn(Symbol("x"), s.engine.env)

    def test_retract_axiom(self):
        s = make_system()
        quiet(s.introduce_axiom, "a1", [Symbol(">"), Symbol("?x"), 0], "test")
        quiet(s.retract, "a1")
        self.assertNotIn("a1", s.axioms)

    def test_retract_term(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.introduce_term, "t1", [Symbol("+"), Symbol("x"), 1], "test")
        quiet(s.retract, "t1")
        self.assertNotIn("t1", s.terms)
        with self.assertRaises(NameError):
            s.evaluate(Symbol("t1"))

    def test_retract_diff(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.register_diff, "d1", "a", "b")
        quiet(s.retract, "d1")
        self.assertNotIn("d1", s.diffs)

    def test_retract_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            quiet(s.retract, "nonexistent")


class TestRederive(unittest.TestCase):
    def test_rederive_clears_fabrication(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Nonexistent quote"])
        quiet(s.set_fact, "x", 999, ev)
        thm = quiet(s.derive, "d1", [Symbol(">"), Symbol("x"), 0], ["x"])
        self.assertIn("potential fabrication", thm.origin)

        # Manually verify the source
        quiet(s.verify_manual, "x")
        quiet(s.rederive, "d1")
        self.assertEqual(s.theorems["d1"].origin, "derived")

    def test_rederive_non_derived_raises(self):
        s = make_system()
        quiet(s.introduce_axiom, "a1", [Symbol(">"), Symbol("?x"), 0], "test")
        with self.assertRaises(KeyError):
            quiet(s.rederive, "a1")

    def test_rederive_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            quiet(s.rederive, "nonexistent")


# ==============================================================
# Diff (Lazy)
# ==============================================================


class TestDiff(unittest.TestCase):
    def test_register_stores_params(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.register_diff, "d1", "a", "b")
        self.assertIn("d1", s.diffs)
        self.assertEqual(s.diffs["d1"]["replace"], "a")
        self.assertEqual(s.diffs["d1"]["with"], "b")

    def test_eval_diff_no_divergence(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 10, "test")
        quiet(s.register_diff, "d1", "a", "b")
        result = s.eval_diff("d1")
        self.assertTrue(result.empty)
        self.assertEqual(result.value_a, 10)
        self.assertEqual(result.value_b, 10)

    def test_eval_diff_with_divergence(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.introduce_term, "double_a", [Symbol("*"), Symbol("a"), 2], "test")
        quiet(s.register_diff, "d1", "a", "b")
        result = s.eval_diff("d1")
        self.assertFalse(result.empty)
        self.assertIn("double_a", result.divergences)
        self.assertEqual(result.divergences["double_a"], [20, 40])

    def test_eval_diff_laziness(self):
        """Changing a fact changes the diff result on next eval."""
        s = make_system(overridable=True)
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.introduce_term, "x", [Symbol("+"), Symbol("a"), 1], "test")
        quiet(s.register_diff, "d1", "a", "b")

        r1 = s.eval_diff("d1")
        self.assertFalse(r1.empty)

        # Now make a=b so diff should be empty
        quiet(s.set_fact, "a", 20, "corrected")
        r2 = s.eval_diff("d1")
        self.assertTrue(r2.empty)

    def test_eval_diff_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            s.eval_diff("nonexistent")

    def test_eval_diff_with_term_values(self):
        """Diff where the replaced symbol is used by a term with an if-branch."""
        s = make_system()
        quiet(s.set_fact, "growth", 15, "test")
        quiet(s.set_fact, "target", 10, "test")
        quiet(s.set_fact, "alt_growth", 5, "test")
        quiet(
            s.introduce_term,
            "beat",
            [Symbol("if"), [Symbol(">"), Symbol("growth"), Symbol("target")], True, False],
            "test",
        )
        quiet(s.register_diff, "d1", "growth", "alt_growth")
        result = s.eval_diff("d1")
        self.assertFalse(result.empty)
        self.assertIn("beat", result.divergences)
        # growth=15 > target=10 → True; alt_growth=5 > target=10 → False
        self.assertEqual(result.divergences["beat"], [True, False])

    def test_eval_diff_term_vs_fact_resolves_values(self):
        """Diff between a fact and a computed term should resolve both to numbers."""
        s = make_system()
        quiet(s.set_fact, "revenue", 100, "test")
        quiet(s.set_fact, "prior", 80, "test")
        # A computed term: growth = ((revenue - prior) / prior) * 100
        quiet(
            s.introduce_term,
            "computed_growth",
            [Symbol("*"), [Symbol("/"), [Symbol("-"), Symbol("revenue"), Symbol("prior")], Symbol("prior")], 100],
            "test",
        )
        quiet(s.set_fact, "simple_growth", 15, "test")
        quiet(s.introduce_term, "dep", [Symbol("+"), Symbol("simple_growth"), 1], "test")
        quiet(s.register_diff, "d1", "simple_growth", "computed_growth")
        result = s.eval_diff("d1")
        # value_a should be 15 (the fact value)
        self.assertEqual(result.value_a, 15)
        # value_b should be 25.0 (evaluated), NOT the S-expression
        self.assertIsInstance(result.value_b, (int, float))
        self.assertEqual(result.value_b, 25.0)

    def test_eval_diff_term_with_term_refs_resolves(self):
        """Diff where the with-symbol is a term referencing other terms should evaluate."""
        s = make_system()
        quiet(s.set_fact, "base", 100, "test")
        quiet(s.set_fact, "rate", 0.2, "test")
        # bonus = base * rate (a computed term referencing facts)
        quiet(
            s.introduce_term,
            "bonus",
            [Symbol("*"), Symbol("base"), Symbol("rate")],
            "test",
        )
        # alt_rate is a term referencing another term
        quiet(s.set_fact, "alt_rate", 0.25, "test")
        quiet(
            s.introduce_term,
            "alt_bonus",
            [Symbol("*"), Symbol("base"), Symbol("alt_rate")],
            "test",
        )
        quiet(s.introduce_term, "dep", [Symbol("+"), Symbol("bonus"), 1], "test")
        quiet(s.register_diff, "d1", "bonus", "alt_bonus")
        result = s.eval_diff("d1")
        # Both values should be numbers
        self.assertIsInstance(result.value_a, (int, float))
        self.assertIsInstance(result.value_b, (int, float))
        self.assertAlmostEqual(result.value_a, 20.0)
        self.assertAlmostEqual(result.value_b, 25.0)

    def test_resolve_value_term_referencing_terms(self):
        """_resolve_value should evaluate a term that references other terms (not just facts)."""
        s = make_system()
        # Facts as base values
        quiet(s.set_fact, "revenue-q3", 1000, "test")
        quiet(s.set_fact, "revenue-prior", 800, "test")
        # Term defined in terms of other terms
        quiet(
            s.introduce_term,
            "revenue-diff",
            [Symbol("-"), Symbol("revenue-q3"), Symbol("revenue-prior")],
            "test",
        )
        quiet(
            s.introduce_term,
            "growth-pct",
            [Symbol("*"), [Symbol("/"), Symbol("revenue-diff"), Symbol("revenue-prior")], 100],
            "test",
        )
        quiet(s.set_fact, "simple-growth", 15, "test")
        quiet(s.introduce_term, "dep", [Symbol("+"), Symbol("simple-growth"), 1], "test")
        quiet(s.register_diff, "d1", "simple-growth", "growth-pct")
        result = s.eval_diff("d1")
        self.assertEqual(result.value_a, 15)
        # growth-pct = ((1000 - 800) / 800) * 100 = 25.0
        self.assertIsInstance(
            result.value_b, (int, float), f"Expected number, got {type(result.value_b)}: {result.value_b}"
        )
        self.assertAlmostEqual(result.value_b, 25.0)

    def test_resolve_value_forward_declared_term(self):
        """_resolve_value falls back to defn when term refs are forward-declared."""
        s = make_system()
        # Forward-declared terms (no definition — just name)
        quiet(s.introduce_term, "revenue-q3-absolute", None, "test")
        quiet(s.introduce_term, "revenue-prior-q3-implied", None, "test")
        # Computed term referencing forward-declared terms
        quiet(
            s.introduce_term,
            "growth-pct",
            [
                Symbol("*"),
                [
                    Symbol("/"),
                    [Symbol("-"), Symbol("revenue-q3-absolute"), Symbol("revenue-prior-q3-implied")],
                    Symbol("revenue-prior-q3-implied"),
                ],
                100,
            ],
            "test",
        )
        quiet(s.set_fact, "simple-growth", 15, "test")
        quiet(s.introduce_term, "dep", [Symbol("+"), Symbol("simple-growth"), 1], "test")
        quiet(s.register_diff, "d1", "simple-growth", "growth-pct")
        result = s.eval_diff("d1")
        self.assertEqual(result.value_a, 15)
        # value_b is a list (unevaluated) because sub-terms are forward-declared
        self.assertIsInstance(result.value_b, list, f"Expected list, got {type(result.value_b)}: {result.value_b}")


# ==============================================================
# Consistency
# ==============================================================


class TestConsistency(unittest.TestCase):
    def test_clean_system_consistent(self):
        s = make_system()
        report = quiet(s.consistency)
        self.assertTrue(report.consistent)
        self.assertEqual(report.issues, [])

    def test_unverified_evidence_issue(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Nonexistent quote"])
        quiet(s.set_fact, "x", 1, ev)
        report = quiet(s.consistency)
        self.assertFalse(report.consistent)
        types = [i.type for i in report.issues]
        self.assertIn("unverified_evidence", types)

    def test_no_evidence_issue(self):
        s = make_system()
        quiet(s.set_fact, "x", 1, "plain origin string")
        report = quiet(s.consistency)
        self.assertFalse(report.consistent)
        types = [i.type for i in report.issues]
        self.assertIn("no_evidence", types)

    def test_fabrication_issue(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Nonexistent quote"])
        quiet(s.set_fact, "x", 999, ev)
        quiet(s.derive, "d1", [Symbol(">"), Symbol("x"), 0], ["x"])
        report = quiet(s.consistency)
        types = [i.type for i in report.issues]
        self.assertIn("potential_fabrication", types)

    def test_diff_divergence_issue(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.introduce_term, "ta", [Symbol("+"), Symbol("a"), 1], "test")
        quiet(s.register_diff, "d1", "a", "b")
        # Mark facts as verified to avoid no_evidence issue
        quiet(s.verify_manual, "a")
        quiet(s.verify_manual, "b")
        quiet(s.verify_manual, "ta")
        report = quiet(s.consistency)
        self.assertFalse(report.consistent)
        types = [i.type for i in report.issues]
        self.assertIn("diff_divergence", types)

    def test_diff_value_divergence_no_downstream(self):
        """Diff with different values but no downstream terms is still inconsistent."""
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.register_diff, "d1", "a", "b")
        quiet(s.verify_manual, "a")
        quiet(s.verify_manual, "b")
        report = quiet(s.consistency)
        self.assertFalse(report.consistent)
        types = [i.type for i in report.issues]
        self.assertIn("diff_value_divergence", types)

    def test_diff_equal_values_no_downstream_is_consistent(self):
        """Diff with equal values and no downstream is consistent."""
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 10, "test")
        quiet(s.register_diff, "d1", "a", "b")
        quiet(s.verify_manual, "a")
        quiet(s.verify_manual, "b")
        report = quiet(s.consistency)
        self.assertTrue(report.consistent)

    def test_diff_values_diverge_property(self):
        """DiffResult.values_diverge reflects value comparison."""
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.register_diff, "d1", "a", "b")
        r = s.eval_diff("d1")
        self.assertTrue(r.values_diverge)
        self.assertTrue(r.empty)  # no downstream terms

    def test_diff_values_agree_property(self):
        """DiffResult.values_diverge is False when values match."""
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 10, "test")
        quiet(s.register_diff, "d1", "a", "b")
        r = s.eval_diff("d1")
        self.assertFalse(r.values_diverge)
        self.assertTrue(r.empty)

    def test_manually_verified_is_warning(self):
        s = make_system()
        quiet(s.set_fact, "x", 1, "plain")
        quiet(s.verify_manual, "x")
        report = quiet(s.consistency)
        # Should be consistent (manually verified is not an issue)
        # but should have a warning
        warning_types = [w.type for w in report.warnings]
        self.assertIn("manually_verified", warning_types)

    def test_report_str_indentation(self):
        """ConsistencyReport.__str__ produces clean, hierarchical indentation."""
        from parseltongue.core.engine import (
            ConsistencyIssue,
            ConsistencyReport,
            ConsistencyWarning,
            DiffResult,
        )

        # DiffResult with divergences
        diff = DiffResult(
            name="d1",
            replace="a",
            with_="b",
            value_a=10,
            value_b=20,
            divergences={"t1": [11, 21]},
        )
        # DiffResult with value divergence only
        vdiff = DiffResult(
            name="d2",
            replace="x",
            with_="y",
            value_a=5,
            value_b=9,
        )

        report = ConsistencyReport(
            consistent=False,
            issues=[
                ConsistencyIssue("potential_fabrication", ["bad-thm"]),
                ConsistencyIssue("diff_divergence", [diff]),
                ConsistencyIssue("diff_value_divergence", [vdiff]),
            ],
            warnings=[ConsistencyWarning("manually_verified", ["m1"])],
        )
        text = str(report)
        lines = text.splitlines()

        # Header
        self.assertEqual(lines[0], "System inconsistent: 3 issue(s)")
        # Each issue block starts with 2-space indent label
        self.assertEqual(lines[1], "  Potential fabrication:")
        self.assertEqual(lines[2], "    bad-thm")
        self.assertEqual(lines[3], "  Diff divergence:")
        self.assertEqual(lines[4], "    d1: a (10) vs b (20)")
        self.assertEqual(lines[5], "      t1: 11 \u2192 21")
        self.assertEqual(lines[6], "  Diff value divergence:")
        self.assertEqual(lines[7], "    d2: x (5) vs y (9) \u2014 values differ")
        # Warning
        self.assertEqual(lines[8], "  [warning] Manually verified: m1")

    def test_diff_result_str_flat(self):
        """DiffResult.__str__ produces flat lines (no indent)."""
        from parseltongue.core.engine import DiffResult

        diff = DiffResult(
            name="d1",
            replace="a",
            with_="b",
            value_a=10,
            value_b=20,
            divergences={"t1": [11, 21], "t2": [12, 22]},
        )
        lines = str(diff).splitlines()
        self.assertEqual(lines[0], "d1: a (10) vs b (20)")
        # Divergence lines have no leading spaces
        for line in lines[1:]:
            self.assertFalse(line.startswith(" "), f"Unexpected indent: {line!r}")

    def test_fix_all_makes_consistent(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Nonexistent quote"])
        quiet(s.set_fact, "x", 999, ev)
        quiet(s.derive, "d1", [Symbol(">"), Symbol("x"), 0], ["x"])

        # System inconsistent
        r1 = quiet(s.consistency)
        self.assertFalse(r1.consistent)

        # Fix: manually verify and rederive
        quiet(s.verify_manual, "x")
        quiet(s.rederive, "d1")
        r2 = quiet(s.consistency)
        self.assertTrue(r2.consistent)


# ==============================================================
# Provenance
# ==============================================================


class TestProvenance(unittest.TestCase):
    def test_fact_provenance(self):
        s = make_system()
        quiet(s.set_fact, "x", 42, "test origin")
        prov = s.provenance("x")
        self.assertEqual(prov["name"], "x")
        self.assertEqual(prov["type"], "fact")
        self.assertEqual(prov["origin"], "test origin")

    def test_derived_provenance_chain(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.set_fact, "y", 3, "test")
        quiet(s.derive, "d1", [Symbol(">"), Symbol("x"), Symbol("y")], ["x", "y"])
        prov = s.provenance("d1")
        self.assertEqual(prov["type"], "theorem")
        self.assertEqual(len(prov["derivation_chain"]), 2)

    def test_provenance_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            s.provenance("nonexistent")

    def test_fact_provenance_with_evidence(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        ev = Evidence(document="Doc", quotes=["Q3 revenue was $15M"])
        quiet(s.set_fact, "rev", 15.0, ev)
        prov = s.provenance("rev")
        self.assertIsInstance(prov["origin"], dict)
        self.assertEqual(prov["origin"]["document"], "Doc")
        self.assertTrue(prov["origin"]["grounded"])

    def test_diff_provenance(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.introduce_term, "ta", [Symbol("+"), Symbol("a"), 1], "test")
        quiet(s.register_diff, "d1", "a", "b")
        prov = s.provenance("d1")
        self.assertEqual(prov["type"], "diff")
        self.assertEqual(prov["replace"], "a")
        self.assertEqual(prov["with"], "b")
        self.assertEqual(prov["value_a"], 10)
        self.assertEqual(prov["value_b"], 20)
        self.assertIn("ta", prov["divergences"])
        self.assertEqual(prov["provenance_a"]["name"], "a")
        self.assertEqual(prov["provenance_b"]["name"], "b")


# ==============================================================
# __repr__
# ==============================================================


class TestRepr(unittest.TestCase):
    def test_repr(self):
        s = make_system()
        r = repr(s)
        self.assertIn("System(", r)
        self.assertIn("axioms", r)
        self.assertIn("terms", r)
        self.assertIn("facts", r)
        self.assertIn("diffs", r)
        self.assertIn("docs", r)


# ==============================================================
# Operator Constants
# ==============================================================


class TestOperatorConstants(unittest.TestCase):
    def test_arithmetic_values(self):
        self.assertEqual(ADD, "+")
        self.assertEqual(SUB, "-")
        self.assertEqual(MUL, "*")
        self.assertEqual(DIV, "/")
        self.assertEqual(MOD, "mod")

    def test_comparison_values(self):
        self.assertEqual(GT, ">")
        self.assertEqual(LT, "<")
        self.assertEqual(GE, ">=")
        self.assertEqual(LE, "<=")
        self.assertEqual(EQ, "=")
        self.assertEqual(NE, "!=")

    def test_logic_values(self):
        self.assertEqual(AND, "and")
        self.assertEqual(OR, "or")
        self.assertEqual(NOT, "not")
        self.assertEqual(IMPLIES, "implies")

    def test_all_are_symbols(self):
        for sym in ARITHMETIC_OPS + COMPARISON_OPS + LOGIC_OPS:
            self.assertIsInstance(sym, Symbol)

    def test_category_tuples(self):
        self.assertEqual(ARITHMETIC_OPS, (ADD, SUB, MUL, DIV, MOD))
        self.assertEqual(COMPARISON_OPS, (GT, LT, GE, LE, EQ, NE))
        self.assertEqual(LOGIC_OPS, (AND, OR, NOT, IMPLIES))


# ==============================================================
# Engine Docs
# ==============================================================


class TestEngineDocs(unittest.TestCase):
    def test_all_operators_documented(self):
        for sym in ARITHMETIC_OPS + COMPARISON_OPS + LOGIC_OPS:
            self.assertIn(sym, ENGINE_DOCS, f"{sym} missing from ENGINE_DOCS")

    def test_doc_entries_have_required_keys(self):
        for sym, doc in ENGINE_DOCS.items():
            self.assertIn("category", doc, f"{sym} doc missing 'category'")
            self.assertIn("description", doc, f"{sym} doc missing 'description'")
            self.assertIn("example", doc, f"{sym} doc missing 'example'")
            self.assertIn("expected", doc, f"{sym} doc missing 'expected'")


# ==============================================================
# DEFAULT_OPERATORS & Configurable Init
# ==============================================================


class TestDefaultOperators(unittest.TestCase):
    def test_default_operators_has_all_ops(self):
        for sym in ARITHMETIC_OPS + COMPARISON_OPS + LOGIC_OPS:
            self.assertIn(sym, DEFAULT_OPERATORS, f"{sym} missing from DEFAULT_OPERATORS")

    def test_default_init_has_all_operators(self):
        s = make_system()
        for sym in DEFAULT_OPERATORS:
            self.assertIn(sym, s.engine.env, f"{sym} missing from default env")

    def test_custom_initial_env_replaces(self):
        """initial_env replaces defaults entirely — only the provided symbols exist."""
        s = make_system(initial_env={ADD: operator.add})
        self.assertIn(ADD, s.engine.env)
        self.assertNotIn(SUB, s.engine.env)
        self.assertNotIn(GT, s.engine.env)
        self.assertNotIn(AND, s.engine.env)

    def test_custom_initial_env_extend(self):
        """Extending defaults by merging with DEFAULT_OPERATORS."""
        custom_sym = Symbol("double")
        custom_fn = lambda x: x * 2
        s = make_system(initial_env={**DEFAULT_OPERATORS, custom_sym: custom_fn})
        # Has all defaults
        for sym in DEFAULT_OPERATORS:
            self.assertIn(sym, s.engine.env)
        # Plus custom
        self.assertIn(custom_sym, s.engine.env)
        self.assertEqual(s.evaluate([custom_sym, 5]), 10)

    def test_custom_env_evaluation(self):
        """System with custom env can evaluate using custom operators."""
        s = make_system(initial_env={ADD: operator.add, SUB: operator.sub})
        self.assertEqual(s.evaluate([ADD, 2, 3]), 5)
        self.assertEqual(s.evaluate([SUB, 10, 4]), 6)
        with self.assertRaises(NameError):
            s.evaluate([MUL, 2, 3])


# ==============================================================
# doc() Method
# ==============================================================


class TestDoc(unittest.TestCase):
    def test_doc_returns_string(self):
        s = make_system()
        result = s.doc()
        self.assertIsInstance(result, str)

    def test_doc_contains_category_headers(self):
        s = make_system()
        result = s.doc()
        self.assertIn("Arithmetic Operators", result)
        self.assertIn("Comparison Operators", result)
        self.assertIn("Logic Operators", result)
        self.assertIn("Special Forms", result)

    def test_doc_contains_examples(self):
        s = make_system()
        result = s.doc()
        self.assertIn("(+ 2 3)", result)
        self.assertIn("(> 5 3)", result)
        self.assertIn("(and true true false)", result)

    def test_doc_contains_expected(self):
        s = make_system()
        result = s.doc()
        self.assertIn("=> 5", result)
        self.assertIn("=> True", result)

    def test_doc_does_not_include_state(self):
        """doc() shows DSL reference only, not runtime facts/terms."""
        s = make_system()
        quiet(s.set_fact, "my_test_fact", 15, "test")
        result = s.doc()
        self.assertNotIn("my_test_fact", result)

    def test_state_includes_user_facts(self):
        s = make_system()
        quiet(s.set_fact, "revenue", 15, "test")
        result = s.state()
        self.assertIn("Facts", result)
        self.assertIn("revenue", result)

    def test_state_includes_user_terms(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.introduce_term, "total", [Symbol("+"), Symbol("a"), 5], "test")
        result = s.state()
        self.assertIn("total", result)

    def test_doc_minimal_env(self):
        """doc() works with a minimal custom env."""
        s = make_system(initial_env={ADD: operator.add})
        result = s.doc()
        self.assertIn("Arithmetic Operators", result)
        self.assertIn("(+ 2 3)", result)
        # Should NOT contain logic since we didn't include it
        self.assertNotIn("Logic Operators", result)

    def test_doc_custom_docs_replaces(self):
        """docs= replaces ENGINE_DOCS entirely — only custom docs appear."""
        custom_sym = Symbol("double")
        custom_docs = {
            custom_sym: {
                "category": "custom",
                "description": "Doubles a value",
                "example": "(double 5)",
                "expected": "10",
            }
        }
        s = make_system(
            initial_env={custom_sym: lambda x: x * 2},
            docs=custom_docs,
        )
        result = s.doc()
        self.assertIn("double", result)
        self.assertIn("Doubles a value", result)
        # Default ENGINE_DOCS entries should NOT appear
        self.assertNotIn("Arithmetic Operators", result)
        self.assertNotIn("(+ 2 3)", result)

    def test_doc_default_when_docs_none(self):
        """When docs is not provided, ENGINE_DOCS is used."""
        s = make_system()
        result = s.doc()
        self.assertIn("Arithmetic Operators", result)
        self.assertIn("(+ 2 3)", result)

    def test_doc_extend_with_engine_docs(self):
        """Extending ENGINE_DOCS by merging with custom entries."""
        custom_sym = Symbol("double")
        custom_docs = {
            **ENGINE_DOCS,
            custom_sym: {
                "category": "custom",
                "description": "Doubles a value",
                "example": "(double 5)",
                "expected": "10",
            },
        }
        s = make_system(
            initial_env={**DEFAULT_OPERATORS, custom_sym: lambda x: x * 2},
            docs=custom_docs,
        )
        result = s.doc()
        # Has defaults
        self.assertIn("Arithmetic Operators", result)
        self.assertIn("(+ 2 3)", result)
        # Plus custom
        self.assertIn("double", result)
        self.assertIn("Doubles a value", result)

    def test_doc_empty_docs(self):
        """Empty docs={} means no operator docs — only LANG_DOCS remain."""
        s = make_system(docs={})
        result = s.doc()
        # LANG_DOCS (special forms, directives) should still appear
        self.assertIn("Special Forms", result)
        # But no operator categories
        self.assertNotIn("Arithmetic Operators", result)


# ==============================================================
# Evidence with Formatted Numbers (integration)
# ==============================================================


class TestEvidenceFormattedNumbers(unittest.TestCase):
    """Verify that quotes with dollar amounts, dotted symbols, and
    comma-separated numbers pass evidence verification through the
    full System pipeline."""

    DOC_TEXT = (
        "Base salary for eligible employees is $150,000. "
        "Eligibility requires quarterly revenue growth exceeds "
        "the stated annual growth target. "
        "The module parseltongue.core provides the DSL engine. "
        "Q2 FY2024 actual revenue was $210M. "
        "Q3 FY2024 actual revenue was $230M. "
        "Population reached 1,000,000 residents. "
        "Requires Python 3.12.1 or higher."
    )

    def setUp(self):
        self.s = make_system()
        quiet(self.s.register_document, "Doc", self.DOC_TEXT)

    def test_dollar_amount_with_comma(self):
        ev = Evidence(document="Doc", quotes=["Base salary for eligible employees is $150,000"])
        quiet(self.s.set_fact, "salary", 150000, ev)
        self.assertTrue(ev.verified)

    def test_dotted_symbol(self):
        ev = Evidence(document="Doc", quotes=["parseltongue.core provides the DSL engine"])
        quiet(self.s.set_fact, "module", "parseltongue.core", ev)
        self.assertTrue(ev.verified)

    def test_large_number_with_commas(self):
        ev = Evidence(document="Doc", quotes=["Population reached 1,000,000 residents"])
        quiet(self.s.set_fact, "pop", 1000000, ev)
        self.assertTrue(ev.verified)

    def test_version_number(self):
        ev = Evidence(document="Doc", quotes=["Python 3.12.1 or higher"])
        quiet(self.s.set_fact, "pyver", "3.12.1", ev)
        self.assertTrue(ev.verified)

    def test_dollar_millions(self):
        ev = Evidence(document="Doc", quotes=["Q3 FY2024 actual revenue was $230M"])
        quiet(self.s.set_fact, "rev-q3", 230, ev)
        self.assertTrue(ev.verified)

    def test_fabrication_propagates_from_bad_dollar_quote(self):
        ev = Evidence(document="Doc", quotes=["Base salary is $999,999"])
        quiet(self.s.set_fact, "wrong-salary", 999999, ev)
        self.assertFalse(ev.verified)
        thm = quiet(self.s.derive, "d1", [Symbol(">"), Symbol("wrong-salary"), 0], ["wrong-salary"])
        self.assertIn("potential fabrication", thm.origin)


if __name__ == "__main__":
    unittest.main()
