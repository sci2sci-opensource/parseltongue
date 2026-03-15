"""Integrity tests: mechanical verification that the system loads and functions correctly.

Unlike consistency tests (which check semantic correctness — do facts match,
do diffs agree), integrity tests check structural health:

1. Loading: core.pltg loads without errors, no directives skipped
2. Std library: all std modules load, key axioms fire correctly
3. Engine: evaluate/rewrite/scope/project/delegate work mechanically
4. Report format: consistency() returns valid ConsistencyReport
5. Higher-order: apply, compose, pipe, map, fold produce correct results

These tests catch regressions in the engine, loader, or std library
without caring whether the pltg content is semantically consistent.
"""

import operator
import os
import unittest

from parseltongue.core import System, load_source
from parseltongue.core.atoms import Symbol
from parseltongue.core.lang import PGStringParser
from parseltongue.core.loader import LazyLoader

parse = PGStringParser.translate

CORE_PLTG = os.path.join(os.path.dirname(__file__), "..", "validation", "core_clean.pltg")
STD_DIR = os.path.join(os.path.dirname(__file__), "..", "std", "std.pltg")

# Module-level: load core once, share across all test classes.
# core.pltg imports std, so all std terms are available.
_loader = LazyLoader(lib_paths=[STD_DIR])
_result = _loader.load_main(CORE_PLTG, strict=True)
_system = _result if isinstance(_result, System) else _result.system


class TestCoreLoading(unittest.TestCase):
    """Core .pltg loads without errors."""

    def test_no_load_errors(self):
        """No directives failed during loading."""
        errors = _result.errors if hasattr(_result, "errors") else {}
        if errors:
            msgs = [f"  {node.name}: {err}" for node, err in errors.items()]
            self.fail("Load errors:\n" + "\n".join(msgs))

    def test_no_skipped_directives(self):
        """No directives were skipped due to dependency failures."""
        skipped = _result.skipped if hasattr(_result, "skipped") else {}
        if skipped:
            names = [node.name for node in skipped]
            self.fail(f"Skipped directives: {names[:20]}")

    def test_system_has_engine(self):
        """Loaded system has a functional engine."""
        self.assertIsNotNone(_system.engine)
        self.assertGreater(len(_system.engine.terms), 0)

    def test_consistency_report_format(self):
        """consistency() returns a report with expected attributes."""
        report = _system.consistency()
        self.assertTrue(hasattr(report, "consistent"))
        self.assertTrue(hasattr(report, "issues"))
        self.assertTrue(hasattr(report, "warnings"))
        self.assertIsInstance(report.consistent, bool)

    def test_theorems_present(self):
        """System has theorems after loading."""
        self.assertGreater(len(_system.engine.theorems), 0)

    def test_axioms_present(self):
        """System has axioms after loading."""
        self.assertGreater(len(_system.engine.axioms), 0)

    def test_diffs_present(self):
        """System has diffs after loading."""
        self.assertGreater(len(_system.engine.diffs), 0)


class TestStdLibrary(unittest.TestCase):
    """Std library modules load and their axioms fire correctly."""

    def test_std_terms_loaded(self):
        """Std modules register their terms."""
        engine = _system.engine
        expected = ["std.lists.cons", "std.counting.count-exists", "std.higher_order.apply", "std.predicates.member"]
        for name in expected:
            self.assertIn(name, engine.terms, f"Missing std term: {name}")

    def test_cons_single(self):
        """cons builds a singleton quoted list."""
        result = _system.engine.evaluate(parse("(std.lists.cons 42)"))
        self.assertEqual(result, [42])

    def test_cons_multi(self):
        """cons builds a multi-element quoted list."""
        result = _system.engine.evaluate(parse("(std.lists.cons 1 2 3)"))
        self.assertEqual(result, [1, 2, 3])

    def test_concat(self):
        """concat merges two lists."""
        result = _system.engine.evaluate(parse("(std.lists.concat (quote (1 2)) (quote (3 4)))"))
        self.assertEqual(result, [1, 2, 3, 4])

    def test_length(self):
        """length counts list elements."""
        result = _system.engine.evaluate(parse("(std.lists.length (a b c))"))
        self.assertEqual(result, 3)

    def test_nth(self):
        """nth returns element at index."""
        result = _system.engine.evaluate(parse("(std.lists.nth 0 (10 20 30))"))
        self.assertEqual(result, 10)
        result = _system.engine.evaluate(parse("(std.lists.nth 2 (10 20 30))"))
        self.assertEqual(result, 30)


class TestHigherOrder(unittest.TestCase):
    """Higher-order patterns: apply, compose, pipe, map, fold.

    Uses a separate System (not core) because we need to define test axioms
    (double, inc, square) that don't exist in std.
    """

    @classmethod
    def setUpClass(cls):
        # Fresh system with std loaded via core, plus test axioms
        cls.system = _system
        load_source(
            cls.system,
            """
            (defterm double :origin "test: multiply by 2")
            (axiom double-rule (= (double ?x) (* 2 ?x)) :origin "test")
            (defterm inc :origin "test: add 1")
            (axiom inc-rule (= (inc ?x) (+ ?x 1)) :origin "test")
            (defterm square :origin "test: square")
            (axiom square-rule (= (square ?x) (* ?x ?x)) :origin "test")
        """,
        )

    def test_apply_unary(self):
        """(apply f x) dispatches to f's axioms."""
        result = self.system.engine.evaluate(parse("(std.higher_order.apply double 5)"))
        self.assertEqual(result, 10)

    def test_apply_binary(self):
        """(apply f x y) dispatches to f's axioms."""
        result = self.system.engine.evaluate(parse("(std.higher_order.apply + 3 4)"))
        self.assertEqual(result, 7)

    def test_compose(self):
        """(compose f g x) applies g then f."""
        result = self.system.engine.evaluate(parse("(std.higher_order.compose double inc 3)"))
        self.assertEqual(result, 8)

    def test_pipe(self):
        """(pipe x f g) applies f then g (left to right)."""
        result = self.system.engine.evaluate(parse("(std.higher_order.pipe 3 inc double)"))
        self.assertEqual(result, 8)

    def test_map(self):
        """map applies function to each element."""
        result = self.system.engine.evaluate(parse("(std.lists.map double (3 4 5))"))
        self.assertEqual(result, [6, 8, 10])

    def test_fold(self):
        """fold reduces list with binary function."""
        result = self.system.engine.evaluate(parse("(std.lists.fold + 0 (1 2 3))"))
        self.assertEqual(result, 6)


class TestPredicates(unittest.TestCase):
    """Predicate axioms: all, any-true, none, member."""

    def test_member_found(self):
        """member returns true when element is in list."""
        result = _system.engine.evaluate(parse("(std.predicates.member 3 (1 2 3))"))
        self.assertTrue(result)

    def test_member_not_found(self):
        """member returns false when element is not in list."""
        result = _system.engine.evaluate(parse("(std.predicates.member 4 (1 2 3))"))
        self.assertFalse(result)

    def test_all_true(self):
        """all returns true when all elements truthy."""
        result = _system.engine.evaluate(parse("(std.predicates.all (true true true))"))
        self.assertTrue(result)

    def test_all_false(self):
        """all short-circuits on first falsy."""
        result = _system.engine.evaluate(parse("(std.predicates.all (true false true))"))
        self.assertFalse(result)

    def test_any_true(self):
        """any-true returns true when any element truthy."""
        result = _system.engine.evaluate(parse("(std.predicates.any-true (false true false))"))
        self.assertTrue(result)

    def test_none(self):
        """none returns true when no elements truthy."""
        result = _system.engine.evaluate(parse("(std.predicates.none false false false)"))
        self.assertTrue(result)


class TestEngineIntegrity(unittest.TestCase):
    """Engine special forms work mechanically."""

    @classmethod
    def setUpClass(cls):
        cls.system = System()

    def test_if_true(self):
        result = self.system.engine.evaluate(parse("(if true 1 2)"))
        self.assertEqual(result, 1)

    def test_if_false(self):
        result = self.system.engine.evaluate(parse("(if false 1 2)"))
        self.assertEqual(result, 2)

    def test_let(self):
        result = self.system.engine.evaluate(parse("(let ((x 10)) (+ x 1))"))
        self.assertEqual(result, 11)

    def test_quote(self):
        result = self.system.engine.evaluate(parse("(quote (a b c))"))
        self.assertEqual(len(result), 3)

    def test_arithmetic(self):
        result = self.system.engine.evaluate(parse("(+ (* 3 4) 1)"))
        self.assertEqual(result, 13)

    def test_comparison(self):
        self.assertTrue(self.system.engine.evaluate(parse("(> 5 3)")))
        self.assertFalse(self.system.engine.evaluate(parse("(< 5 3)")))

    def test_logic(self):
        self.assertTrue(self.system.engine.evaluate(parse("(and true true)")))
        self.assertFalse(self.system.engine.evaluate(parse("(and true false)")))
        self.assertTrue(self.system.engine.evaluate(parse("(or false true)")))


class TestScopeAndDelegate(unittest.TestCase):
    """Scope, project, and delegate work across system boundaries."""

    @classmethod
    def setUpClass(cls):
        def make_env():
            return {
                Symbol("="): lambda *args: all(a == args[0] for a in args[1:]),
                Symbol("+"): operator.add,
                Symbol("*"): operator.mul,
                Symbol("not"): lambda a: not a,
            }

        def make_scope_fn(child):
            def _scope_fn(_name, *args):
                result = None
                for arg in args:
                    if isinstance(arg, list):
                        result = child.engine.evaluate(arg)
                    else:
                        result = arg
                return result

            return _scope_fn

        # Child system with axiom
        cls.child = System(initial_env=make_env(), overridable=True)
        load_source(
            cls.child,
            """
            (defterm double :origin "test")
            (axiom double-rule (= (double ?x) (* 2 ?x)) :origin "test")
        """,
        )

        # Parent system
        cls.parent = System(initial_env=make_env(), overridable=True)
        cls.parent.engine.env[Symbol("child")] = make_scope_fn(cls.child)

    def test_scope_basic(self):
        """scope dispatches evaluation to child system."""
        result = self.parent.engine.evaluate(parse("(scope child (double (project 5)))"))
        self.assertEqual(result, 10)

    def test_scope_self(self):
        """scope self evaluates in current engine."""
        result = self.parent.engine.evaluate(parse("(scope self (+ 2 3))"))
        self.assertEqual(result, 5)

    def test_project(self):
        """project evaluates in current engine before crossing scope."""
        result = self.parent.engine.evaluate(parse("(scope child (double (project (+ 1 2))))"))
        self.assertEqual(result, 6)


class TestRewritePatterns(unittest.TestCase):
    """Turing-complete rewrite patterns: recursion, self-passing, head dispatch."""

    @classmethod
    def setUpClass(cls):
        cls.system = System()
        load_source(
            cls.system,
            """
            (defterm factorial :origin "test")
            (axiom factorial-rule
                (= (factorial ?n) (if (> ?n 1) (* ?n (factorial (- ?n 1))) 1))
                :origin "test")
            (defterm sfact :origin "test: self-passing")
            (axiom sfact-rule
                (= (sfact ?self ?n) (if (> ?n 1) (* ?n (?self ?self (- ?n 1))) 1))
                :origin "test")
        """,
        )

    def test_recursive_factorial(self):
        self.assertEqual(self.system.engine.evaluate(parse("(factorial 5)")), 120)
        self.assertEqual(self.system.engine.evaluate(parse("(factorial 1)")), 1)

    def test_self_passing_factorial(self):
        """Y-combinator pattern: term receives itself as argument."""
        self.assertEqual(self.system.engine.evaluate(parse("(sfact sfact 5)")), 120)

    def test_head_dispatch(self):
        """?-var in head position dispatches to bound symbol's axioms."""
        load_source(
            self.system,
            """
            (defterm apply-test :origin "test")
            (axiom apply-test-rule (= (apply-test ?f ?x) (?f ?x)) :origin "test")
        """,
        )
        result = self.system.engine.evaluate(parse("(apply-test factorial 5)"))
        self.assertEqual(result, 120)


if __name__ == "__main__":
    unittest.main()
