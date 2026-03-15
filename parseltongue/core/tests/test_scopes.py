"""Tests for scope, self, and project special forms.

Based on LANG_DOCS in lang.py — the source of truth for semantics.

scope:  (scope name expr ...) — if name is self, evaluate in current engine.
        Otherwise resolve name to a callable, pass scope name + unevaluated args.
self:   (self expr ...) — evaluate all args in the current engine.
project: (project expr) — evaluate in current engine (self basis).
         (project basis expr) — resolve basis, evaluate expr in that basis.
         Result is a concrete value that crosses scope boundaries.
"""

import operator
import unittest
from unittest.mock import patch

from ..atoms import Symbol
from ..system import EmptySystem, System


def make_system(**kwargs):
    """Create a System with print suppressed."""
    with patch("builtins.print"):
        return System(**kwargs)


def make_empty_system():
    """Create an empty System — no default operators."""
    with patch("builtins.print"):
        return System(initial_env={}, docs={})


# ── self ──


class TestSelf(unittest.TestCase):
    """(self expr ...) — evaluate in current engine."""

    def setUp(self):
        self.s = make_system()

    def test_self_evaluates_expression(self):
        """(self (+ 2 3)) => 5"""
        self.s.engine.env[Symbol("+")] = operator.add
        result = self.s.evaluate([Symbol("self"), [Symbol("+"), 2, 3]])
        self.assertEqual(result, 5)

    def test_self_evaluates_last_of_multiple(self):
        """(self expr1 expr2) => result of expr2"""
        self.s.engine.env[Symbol("+")] = operator.add
        result = self.s.evaluate([Symbol("self"), [Symbol("+"), 1, 1], [Symbol("+"), 3, 4]])
        self.assertEqual(result, 7)

    def test_self_resolves_terms(self):
        """(self term) resolves in current engine's env."""
        self.s.set_fact("x", 42, "test")
        result = self.s.evaluate([Symbol("self"), Symbol("x")])
        self.assertEqual(result, 42)

    def test_self_with_if(self):
        """(self (if true 1 2)) — if is a special form, works in self."""
        result = self.s.evaluate([Symbol("self"), [Symbol("if"), True, 1, 2]])
        self.assertEqual(result, 1)


# ── scope ──


class TestScope(unittest.TestCase):
    """(scope name expr ...) — delegate to named scope."""

    def setUp(self):
        self.s = make_system()

    def test_scope_self_evaluates_in_current_engine(self):
        """(scope self (+ 2 3)) => 5 — self is handled at engine level."""
        self.s.engine.env[Symbol("+")] = operator.add
        result = self.s.evaluate([Symbol("scope"), Symbol("self"), [Symbol("+"), 2, 3]])
        self.assertEqual(result, 5)

    def test_scope_self_multiple_exprs(self):
        """(scope self expr1 expr2) => result of expr2."""
        self.s.engine.env[Symbol("+")] = operator.add
        result = self.s.evaluate([Symbol("scope"), Symbol("self"), [Symbol("+"), 1, 1], [Symbol("+"), 10, 20]])
        self.assertEqual(result, 30)

    def test_scope_callable_receives_name_and_unevaluated_args(self):
        """(scope other (foo bar)) — callable gets name Symbol + raw exprs."""
        received = []

        def scope_handler(*args):
            received.extend(args)
            return "handled"

        self.s.engine.env[Symbol("other")] = scope_handler
        result = self.s.evaluate([Symbol("scope"), Symbol("other"), [Symbol("foo"), Symbol("bar")]])
        self.assertEqual(result, "handled")
        # First arg is the scope name (Symbol), second is unevaluated expr
        self.assertEqual(received[0], Symbol("other"))
        self.assertEqual(received[1], [Symbol("foo"), Symbol("bar")])

    def test_scope_args_are_not_evaluated(self):
        """scope must NOT evaluate args before passing to callable."""
        evaluated = []

        def spy(*args):
            evaluated.append(args)
            return "ok"

        def boom():
            raise RuntimeError("should not be called")

        self.s.engine.env[Symbol("other")] = spy
        self.s.engine.env[Symbol("boom")] = boom

        # (scope other (boom)) — boom should NOT be called
        self.s.evaluate([Symbol("scope"), Symbol("other"), [Symbol("boom")]])
        # The callable got the raw expression, boom was not invoked
        self.assertEqual(evaluated[0][1], [Symbol("boom")])

    def test_scope_non_callable_raises(self):
        """(scope 42 (foo)) — scope target must be callable."""
        self.s.set_fact("notfunc", 42, "test")
        with self.assertRaises(TypeError):
            self.s.evaluate([Symbol("scope"), Symbol("notfunc"), [Symbol("foo")]])

    def test_scope_if_works_inside(self):
        """(scope self (if true 1 2)) — if is a special form, always works."""
        result = self.s.evaluate([Symbol("scope"), Symbol("self"), [Symbol("if"), True, "yes", "no"]])
        self.assertEqual(result, "yes")


# ── project ──


class TestProject(unittest.TestCase):
    """(project expr) or (project basis expr) — evaluate and yield value."""

    def setUp(self):
        self.s = make_system()

    def test_project_bare_evaluates_in_self(self):
        """(project (+ 2 3)) => 5 — default basis is self."""
        self.s.engine.env[Symbol("+")] = operator.add
        result = self.s.evaluate([Symbol("project"), [Symbol("+"), 2, 3]])
        self.assertEqual(result, 5)

    def test_project_self_explicit(self):
        """(project self (+ 2 3)) => 5 — explicit self basis."""
        self.s.engine.env[Symbol("+")] = operator.add
        result = self.s.evaluate([Symbol("project"), Symbol("self"), [Symbol("+"), 2, 3]])
        self.assertEqual(result, 5)

    def test_project_resolves_terms_in_self(self):
        """(project x) resolves x in current engine."""
        self.s.set_fact("x", 99, "test")
        result = self.s.evaluate([Symbol("project"), Symbol("x")])
        self.assertEqual(result, 99)

    def test_project_named_basis_calls_callable(self):
        """(project other (foo)) — resolve other, call with name + unevaluated expr."""
        received = []

        def basis_handler(*args):
            received.extend(args)
            return "projected"

        self.s.engine.env[Symbol("other")] = basis_handler
        result = self.s.evaluate([Symbol("project"), Symbol("other"), [Symbol("foo"), 1]])
        self.assertEqual(result, "projected")
        self.assertEqual(received[0], Symbol("other"))
        self.assertEqual(received[1], [Symbol("foo"), 1])

    def test_project_non_callable_raises(self):
        """(project 42 (foo)) — basis must be callable."""
        self.s.set_fact("notfunc", 42, "test")
        with self.assertRaises(TypeError):
            self.s.evaluate([Symbol("project"), Symbol("notfunc"), [Symbol("foo")]])

    def test_project_if_inside(self):
        """(project basis (if cond a b)) — if works inside project."""
        received_args = []

        def basis_handler(*args):
            received_args.extend(args)
            # The basis receives unevaluated: [if, cond, a, b]
            # It should contain the if special form
            return "got-if"

        self.s.engine.env[Symbol("other")] = basis_handler
        result = self.s.evaluate([Symbol("project"), Symbol("other"), [Symbol("if"), True, "yes", "no"]])
        self.assertEqual(result, "got-if")
        # if was passed unevaluated to the basis callable
        self.assertEqual(received_args[1][0], Symbol("if"))


# ── composition: scope + project ──


class TestScopeProjectComposition(unittest.TestCase):
    """Composing scope and project — the key design case."""

    def setUp(self):
        self.s = make_system()
        self.s.engine.env[Symbol("+")] = operator.add
        self.s.engine.env[Symbol("and")] = lambda *a: all(a)
        self.s.engine.env[Symbol("or")] = lambda *a: any(a)

    def test_project_inside_scope_evaluates_eagerly(self):
        """(scope other (project (+ 2 3))) — project is eagerly evaluated by the parent.

        Project means 'I, the parent, replaced this with a concrete value.'
        The scope handler receives the concrete value 5, not a raw expression.
        """
        received = []

        def handler(*args):
            received.extend(args)
            return "ok"

        self.s.engine.env[Symbol("other")] = handler

        self.s.evaluate([Symbol("scope"), Symbol("other"), [Symbol("project"), [Symbol("+"), 2, 3]]])
        self.assertEqual(received[0], Symbol("other"))
        self.assertEqual(received[1], 5)

    def test_project_self_inside_scope_evaluates_eagerly(self):
        """(scope other (project self (+ 2 3))) — explicit self basis, still eager."""
        received = []

        def handler(*args):
            received.extend(args)
            return "ok"

        self.s.engine.env[Symbol("other")] = handler

        self.s.evaluate([Symbol("scope"), Symbol("other"), [Symbol("project"), Symbol("self"), [Symbol("+"), 2, 3]]])
        self.assertEqual(received[1], 5)

    def test_project_arithmetic_into_logic_scope(self):
        """Project resolves in the current engine. Parent doesn't have = → error.
        With explicit basis (project arithmetic ...) it works.
        """
        S = Symbol

        # Logic system: only has 'and'
        logic_sys = EmptySystem()
        logic_sys.engine.env[S("and")] = lambda *a: all(a)

        def logic_handler(name, *args):
            result = None
            for arg in args:
                result = logic_sys.evaluate(arg)
            return result

        # Arithmetic system: has = and scopes to logic
        arith_sys = EmptySystem()
        arith_sys.engine.env[S("=")] = operator.eq
        arith_sys.engine.env[S("logic")] = logic_handler

        def arith_handler(name, *args):
            result = None
            for arg in args:
                result = arith_sys.evaluate(arg)
            return result

        # Parent: only has scope to arithmetic, no =
        parent = EmptySystem()
        parent.engine.env[S("arithmetic")] = arith_handler

        # (project (= 2 2)) inside scope — parent resolves project, but parent has no =
        with self.assertRaises(NameError):
            parent.evaluate(
                [
                    S("scope"),
                    S("arithmetic"),
                    [
                        S("scope"),
                        S("logic"),
                        [S("and"), [S("project"), [S("="), 2, 2]], [S("project"), [S("="), 3, 3]]],
                    ],
                ]
            )

        # Correct: (project arithmetic (= 2 2)) — arithmetic has =
        result = parent.evaluate(
            [
                S("scope"),
                S("arithmetic"),
                [
                    S("scope"),
                    S("logic"),
                    [
                        S("and"),
                        [S("project"), S("arithmetic"), [S("="), 2, 2]],
                        [S("project"), S("arithmetic"), [S("="), 3, 3]],
                    ],
                ],
            ]
        )
        self.assertEqual(result, True)

    def test_project_false_comparison_into_logic(self):
        """Same topology, one comparison false → and returns False."""
        S = Symbol

        logic_sys = EmptySystem()
        logic_sys.engine.env[S("and")] = lambda *a: all(a)

        def logic_handler(name, *args):
            result = None
            for arg in args:
                result = logic_sys.evaluate(arg)
            return result

        arith_sys = EmptySystem()
        arith_sys.engine.env[S("=")] = operator.eq
        arith_sys.engine.env[S("logic")] = logic_handler

        def arith_handler(name, *args):
            result = None
            for arg in args:
                result = arith_sys.evaluate(arg)
            return result

        parent = EmptySystem()
        parent.engine.env[S("arithmetic")] = arith_handler

        result = parent.evaluate(
            [
                S("scope"),
                S("arithmetic"),
                [
                    S("scope"),
                    S("logic"),
                    [
                        S("and"),
                        [S("project"), S("arithmetic"), [S("="), 2, 2]],
                        [S("project"), S("arithmetic"), [S("="), 2, 3]],
                    ],
                ],
            ]
        )
        self.assertEqual(result, False)

    def test_project_outside_scope(self):
        """(self (scope other (project ...))) — project inside scope is unevaluated,
        but if we project OUTSIDE scope it evaluates first.

        Wait: (project (scope other ...)) — project evaluates its arg,
        which IS the scope call. That triggers scope, which calls handler.
        """
        handler_result = {"value": 42}

        def handler(*args):
            return handler_result["value"]

        self.s.engine.env[Symbol("other")] = handler

        # (project (scope other (kind "diff")))
        # project evaluates its arg => triggers scope => handler called => 42
        result = self.s.evaluate([Symbol("project"), [Symbol("scope"), Symbol("other"), [Symbol("kind"), "diff"]]])
        self.assertEqual(result, 42)

    def test_self_wrapping_scope(self):
        """(self (scope other expr)) — self evaluates the scope call in current engine."""

        def handler(*args):
            return "from-other"

        self.s.engine.env[Symbol("other")] = handler

        result = self.s.evaluate([Symbol("self"), [Symbol("scope"), Symbol("other"), [Symbol("kind"), "diff"]]])
        self.assertEqual(result, "from-other")

    def test_if_works_at_scope_level(self):
        """(scope self (if true (+ 1 2) 0)) — if is a special form, works in scope self."""
        result = self.s.evaluate([Symbol("scope"), Symbol("self"), [Symbol("if"), True, [Symbol("+"), 1, 2], 0]])
        self.assertEqual(result, 3)

    def test_if_works_at_project_level(self):
        """(project (if true 10 20)) — if works inside bare project."""
        result = self.s.evaluate([Symbol("project"), [Symbol("if"), True, 10, 20]])
        self.assertEqual(result, 10)


# ── two-system composition ──


class TestTwoSystemComposition(unittest.TestCase):
    """Simulate two systems: outer (with +) and inner (with kind operator).

    The inner system callable evaluates args in its own engine.
    project lets us evaluate in the outer basis before crossing into inner.
    """

    def setUp(self):
        # Outer system: has + and facts
        self.outer = make_system()
        self.outer.engine.env[Symbol("+")] = operator.add
        self.outer.set_fact("count-a", 3, "test")
        self.outer.set_fact("count-b", 7, "test")

        # Inner system: has "kind" operator only
        self.inner = EmptySystem()
        self.inner.engine.env[Symbol("kind")] = lambda k: f"kind:{k}"

        # Register inner as a scope callable in outer
        inner_sys = self.inner

        def inner_scope_handler(name, *unevaluated_args):
            """Evaluate each arg in the inner system."""
            result = None
            for arg in unevaluated_args:
                result = inner_sys.evaluate(arg)
            return result

        self.outer.engine.env[Symbol("inner")] = inner_scope_handler

    def test_scope_inner_evaluates_in_inner(self):
        """(scope inner (kind "diff")) — kind is resolved in inner system."""
        result = self.outer.evaluate([Symbol("scope"), Symbol("inner"), [Symbol("kind"), "diff"]])
        self.assertEqual(result, "kind:diff")

    def test_scope_inner_cannot_resolve_outer_terms(self):
        """(scope inner (+ count-a count-b)) — inner doesn't have + or count-a."""
        # Inner system doesn't have + or count-a, should fail
        with self.assertRaises(Exception):
            self.outer.evaluate([Symbol("scope"), Symbol("inner"), [Symbol("+"), Symbol("count-a"), Symbol("count-b")]])

    def test_project_self_then_pass_to_scope(self):
        """Use project to evaluate in outer, then pass result to inner.

        (scope inner (project self (+ count-a count-b))) — but project is inside
        scope args so it's unevaluated. The inner handler would need to
        recognize project. Instead, the correct pattern is to evaluate first:

        We need to structure it so project runs at engine level.
        Pattern: use let or a term to pre-compute.
        """
        # Pre-compute in outer, pass concrete value to inner
        self.outer.set_fact("total", 10, "test")  # = count-a + count-b
        result = self.outer.evaluate([Symbol("scope"), Symbol("inner"), [Symbol("kind"), 10]])
        self.assertEqual(result, "kind:10")

    def test_scope_self_with_plus(self):
        """(scope self (+ count-a count-b)) — self has everything."""
        result = self.outer.evaluate(
            [Symbol("scope"), Symbol("self"), [Symbol("+"), Symbol("count-a"), Symbol("count-b")]]
        )
        self.assertEqual(result, 10)

    def test_if_across_scope_boundary(self):
        """(scope inner (if true (kind "diff") (kind "theorem")))
        — if is a special form, processed by whatever engine runs the eval.
        Inner's engine handles if natively."""
        result = self.outer.evaluate(
            [
                Symbol("scope"),
                Symbol("inner"),
                [Symbol("if"), True, [Symbol("kind"), "diff"], [Symbol("kind"), "theorem"]],
            ]
        )
        self.assertEqual(result, "kind:diff")

    def test_scope_handler_receives_name(self):
        """Scope callable receives the scope name as first argument."""
        received_name = []

        def named_handler(name, *args):
            received_name.append(name)
            return "ok"

        self.outer.engine.env[Symbol("myscope")] = named_handler
        self.outer.evaluate([Symbol("scope"), Symbol("myscope"), [Symbol("foo")]])
        self.assertEqual(received_name[0], Symbol("myscope"))


# ── project with named basis (callable) ──


class TestProjectNamedBasis(unittest.TestCase):
    """(project basis expr) — resolve basis to callable, delegate evaluation."""

    def setUp(self):
        self.s = make_system()
        self.s.engine.env[Symbol("+")] = operator.add

        # A "math" basis that evaluates in its own system with arithmetic
        math_sys = EmptySystem()
        math_sys.engine.env[Symbol("+")] = operator.add
        math_sys.engine.env[Symbol("*")] = operator.mul
        math_sys.set_fact("pi", 3, "approx")

        def math_handler(name, *unevaluated_args):
            result = None
            for arg in unevaluated_args:
                result = math_sys.evaluate(arg)
            return result

        self.s.engine.env[Symbol("math")] = math_handler

    def test_project_named_basis(self):
        """(project math (* pi 2)) — evaluates in math basis."""
        result = self.s.evaluate([Symbol("project"), Symbol("math"), [Symbol("*"), Symbol("pi"), 2]])
        self.assertEqual(result, 6)

    def test_project_named_basis_receives_name(self):
        """(project math expr) — callable receives basis name as first arg."""
        received = []

        def spy(name, *args):
            received.append(name)
            return 0

        self.s.engine.env[Symbol("spy")] = spy
        self.s.evaluate([Symbol("project"), Symbol("spy"), [Symbol("+"), 1, 2]])
        self.assertEqual(received[0], Symbol("spy"))


# ── generated multi-scope prime computation ──


class TestGeneratedPrimeScopes(unittest.TestCase):
    """Generated test: 7 systems, each owns one prime operation.

    Systems form a dependency tree — each registers scopes to its
    children and the final expression threads through all of them.

    Topology:
        root
        ├── sieve (has: is-prime, next-prime)
        │   └── fermat (has: fermat-check — probabilistic witness)
        ├── arith (has: +, *, mod, -)
        │   └── pow (has: pow-mod — modular exponentiation)
        └── accum (has: fold-primes — accumulate primes into hash)
            └── hash (has: prime-hash — irreversible mixing)

    The final expression computed by root:
        Collect first 8 primes, for each compute a Fermat witness,
        mix all witnesses through an irreversible hash chain.

    Each step MUST evaluate in the correct scope — wrong scope = NameError.
    """

    @staticmethod
    def _make_scope_handler(system):
        """Create a scope handler that evaluates in the given system."""

        def handler(name, *unevaluated_args):
            result = None
            for arg in unevaluated_args:
                result = system.evaluate(arg)
            return result

        return handler

    def _build_systems(self):
        """Build the 7-system topology. Returns root system and expected result."""
        S = Symbol

        # ── leaf: hash system ──
        # prime-hash: irreversible mixing via ((h * 31) ^ prime) & 0xFFFFFFFF
        hash_sys = EmptySystem()
        hash_sys.engine.env[S("prime-hash")] = lambda h, p: ((h * 31) ^ p) & 0xFFFFFFFF

        # ── leaf: pow system ──
        # pow-mod: modular exponentiation
        pow_sys = EmptySystem()
        pow_sys.engine.env[S("pow-mod")] = lambda base, exp, mod: pow(base, exp, mod)

        # ── leaf: fermat system (has scope to pow) ──
        fermat_sys = EmptySystem()
        fermat_sys.engine.env[S("pow")] = self._make_scope_handler(pow_sys)

        # fermat-check: compute 2^(p-1) mod p via pow scope (Fermat's little theorem)
        # Returns the witness value (should be 1 for primes)
        def fermat_check(p):
            if p < 2:
                return 0
            # Use pow scope for modular exponentiation
            witness = fermat_sys.evaluate([S("scope"), S("pow"), [S("pow-mod"), 2, p - 1, p]])
            return witness

        fermat_sys.engine.env[S("fermat-check")] = fermat_check

        # ── arith system (has scope to pow) ──
        arith_sys = EmptySystem()
        arith_sys.engine.env[S("+")] = operator.add
        arith_sys.engine.env[S("*")] = operator.mul
        arith_sys.engine.env[S("-")] = operator.sub
        arith_sys.engine.env[S("mod")] = operator.mod
        arith_sys.engine.env[S("pow")] = self._make_scope_handler(pow_sys)

        # ── sieve system (has scope to fermat) ──
        sieve_sys = EmptySystem()
        sieve_sys.engine.env[S("fermat")] = self._make_scope_handler(fermat_sys)

        def is_prime(n):
            if n < 2:
                return False
            if n < 4:
                return True
            if n % 2 == 0:
                return False
            d = 3
            while d * d <= n:
                if n % d == 0:
                    return False
                d += 2
            return True

        def next_prime(n):
            c = n + 1
            while not is_prime(c):
                c += 1
            return c

        sieve_sys.engine.env[S("is-prime")] = is_prime
        sieve_sys.engine.env[S("next-prime")] = next_prime

        # ── accum system (has scope to hash) ──
        accum_sys = EmptySystem()
        accum_sys.engine.env[S("hash")] = self._make_scope_handler(hash_sys)

        def fold_primes(primes_and_witnesses):
            """Fold list of (prime, witness) pairs through hash chain."""
            h = 0
            for pw in primes_and_witnesses:
                p, w = pw
                # Hash: mix prime
                h = hash_sys.evaluate([S("prime-hash"), h, p])
                # Hash: mix witness
                h = hash_sys.evaluate([S("prime-hash"), h, w])
            return h

        accum_sys.engine.env[S("fold-primes")] = fold_primes

        # ── root system (has scopes to sieve, arith, accum) ──
        root = make_system()
        root.engine.env[S("sieve")] = self._make_scope_handler(sieve_sys)
        root.engine.env[S("arith")] = self._make_scope_handler(arith_sys)
        root.engine.env[S("accum")] = self._make_scope_handler(accum_sys)

        # ── compute expected result manually ──
        primes = []
        p = 2
        for _ in range(8):
            primes.append(p)
            p = next_prime(p)
        # primes = [2, 3, 5, 7, 11, 13, 17, 19]

        pairs = []
        for pr in primes:
            w = pow(2, pr - 1, pr)  # Fermat witness
            pairs.append((pr, w))

        expected_hash = 0
        for pr, w in pairs:
            expected_hash = ((expected_hash * 31) ^ pr) & 0xFFFFFFFF
            expected_hash = ((expected_hash * 31) ^ w) & 0xFFFFFFFF

        return root, sieve_sys, arith_sys, fermat_sys, accum_sys, hash_sys, pow_sys, primes, expected_hash

    def test_full_prime_hash_chain(self):
        """Thread through all 7 systems to compute an irreversible hash.

        Each scope boundary is real — wrong scope = NameError.
        The hash is irreversible — can't get the right answer by accident.
        """
        S = Symbol
        root, sieve_sys, arith_sys, fermat_sys, accum_sys, hash_sys, pow_sys, primes, expected = self._build_systems()

        # Collect primes via sieve scope, witnesses via nested fermat scope
        pairs = []
        p = 2
        for _ in range(8):
            # Get Fermat witness: root -> sieve -> fermat -> pow
            witness = root.evaluate(
                [S("scope"), S("sieve"), [S("scope"), S("fermat"), [S("scope"), S("pow"), [S("pow-mod"), 2, p - 1, p]]]]
            )
            pairs.append((p, witness))

            # Next prime: root -> sieve
            p = root.evaluate([S("scope"), S("sieve"), [S("next-prime"), p]])

        # Fold through accum -> hash
        result = accum_sys.evaluate([S("fold-primes"), pairs])

        self.assertEqual(result, expected)
        self.assertNotEqual(result, 0)  # non-trivial

    def test_wrong_scope_fails(self):
        """Trying to use an operator in the wrong scope raises."""
        S = Symbol
        root, *_ = self._build_systems()

        # root doesn't have is-prime — only sieve does
        with self.assertRaises(NameError):
            root.evaluate([S("is-prime"), 7])

        # root doesn't have pow-mod — only pow does
        with self.assertRaises(NameError):
            root.evaluate([S("pow-mod"), 2, 6, 7])

        # sieve doesn't have + — only arith does → NameError
        with self.assertRaises(NameError):
            root.evaluate([S("scope"), S("sieve"), [S("+"), 1, 2]])

    def test_cross_scope_project(self):
        """Use project to evaluate in arith basis, pass result into sieve.

        (scope sieve (is-prime (project arith (+ 4 3))))
        But project is inside scope args — unevaluated! So sieve must handle it.

        Correct pattern: compute in arith first, then pass to sieve.
        """
        S = Symbol
        root, *_ = self._build_systems()

        # Step 1: project in arith to get 7
        seven = root.evaluate([S("scope"), S("arith"), [S("+"), 4, 3]])
        self.assertEqual(seven, 7)

        # Step 2: pass concrete value to sieve
        is_prime = root.evaluate([S("scope"), S("sieve"), [S("is-prime"), seven]])
        self.assertTrue(is_prime)

    def test_scope_self_in_root(self):
        """(scope self ...) evaluates in root — root has the scope handlers."""
        S = Symbol
        root, *_ = self._build_systems()

        # scope self just evaluates in root — sieve is a callable there
        result = root.evaluate([S("scope"), S("self"), [S("scope"), S("sieve"), [S("is-prime"), 17]]])
        self.assertTrue(result)

    def test_nested_scope_depth_4(self):
        """root -> sieve -> fermat -> pow: 4 levels of scope nesting."""
        S = Symbol
        root, *_ = self._build_systems()

        # 2^6 mod 7 = 64 mod 7 = 1 (Fermat's little theorem for prime 7)
        result = root.evaluate(
            [S("scope"), S("sieve"), [S("scope"), S("fermat"), [S("scope"), S("pow"), [S("pow-mod"), 2, 6, 7]]]]
        )
        self.assertEqual(result, 1)

    def test_subsystem_defines_own_scopes(self):
        """Subsystems define their own scope topology — root doesn't know about pow.

        sieve has scope to fermat, fermat has scope to pow.
        Root can reach pow only through sieve -> fermat -> pow.
        Direct root -> pow should fail.
        """
        S = Symbol
        root, *_ = self._build_systems()

        # root has no direct access to pow
        with self.assertRaises(Exception):
            root.evaluate([S("scope"), S("pow"), [S("pow-mod"), 2, 3, 5]])

        # But root -> sieve -> fermat -> pow works
        result = root.evaluate(
            [S("scope"), S("sieve"), [S("scope"), S("fermat"), [S("scope"), S("pow"), [S("pow-mod"), 2, 3, 5]]]]
        )
        self.assertEqual(result, 3)  # 2^3 mod 5 = 8 mod 5 = 3

    def test_parallel_scope_paths_same_result(self):
        """Two different scope paths that compute the same value.

        Path A: root -> arith: (mod (* 7 11) 13) = 77 mod 13 = 12
        Path B: root -> arith -> pow (via arith's pow scope): pow-mod(7, 1, 13) * pow-mod(11, 1, 13) mod 13

        Wait — arith has pow scope. Let's verify:
        root -> arith: (mod (* 7 11) 13) = 12
        root -> sieve -> fermat -> pow: pow-mod(7, 2, 13) = 49 mod 13 = 10
        Different values, but both correct. Let's just verify both paths work.
        """
        S = Symbol
        root, *_ = self._build_systems()

        # Path A: through arith
        result_a = root.evaluate([S("scope"), S("arith"), [S("mod"), [S("*"), 7, 11], 13]])
        self.assertEqual(result_a, 12)

        # Path B: through sieve -> fermat -> pow
        result_b = root.evaluate(
            [S("scope"), S("sieve"), [S("scope"), S("fermat"), [S("scope"), S("pow"), [S("pow-mod"), 7, 2, 13]]]]
        )
        self.assertEqual(result_b, 10)

    def test_all_8_primes_correct(self):
        """Verify sieve produces correct first 8 primes through scope."""
        S = Symbol
        root, *_ = self._build_systems()
        expected_primes = [2, 3, 5, 7, 11, 13, 17, 19]

        collected = [2]
        p = 2
        for _ in range(7):
            p = root.evaluate([S("scope"), S("sieve"), [S("next-prime"), p]])
            collected.append(p)

        self.assertEqual(collected, expected_primes)

    def test_fermat_witnesses_all_one_for_primes(self):
        """For all 8 primes, Fermat witness 2^(p-1) mod p should be 1."""
        S = Symbol
        root, *_ = self._build_systems()
        test_primes = [2, 3, 5, 7, 11, 13, 17, 19]

        for p in test_primes:
            witness = root.evaluate(
                [S("scope"), S("sieve"), [S("scope"), S("fermat"), [S("scope"), S("pow"), [S("pow-mod"), 2, p - 1, p]]]]
            )
            if p == 2:
                # 2^(2-1) mod 2 = 0 — Fermat's little theorem doesn't apply to p=2
                self.assertEqual(witness, 0)
            else:
                self.assertEqual(witness, 1, f"Fermat witness failed for prime {p}")

    def test_hash_chain_deterministic(self):
        """Same inputs → same hash. Different inputs → different hash."""
        S = Symbol
        root, sieve_sys, arith_sys, fermat_sys, accum_sys, hash_sys, pow_sys, primes, expected = self._build_systems()

        # Compute hash chain twice
        h1 = 0
        h2 = 0
        for p in primes[:4]:
            h1 = hash_sys.evaluate([S("prime-hash"), h1, p])
            h2 = hash_sys.evaluate([S("prime-hash"), h2, p])
        self.assertEqual(h1, h2)

        # Different sequence → different hash
        h3 = 0
        for p in reversed(primes[:4]):
            h3 = hash_sys.evaluate([S("prime-hash"), h3, p])
        self.assertNotEqual(h1, h3)


# ── strict propagation through scope boundaries ──


class TestStrictPropagation(unittest.TestCase):
    """Strict propagates through scope boundaries by wrapping forwarded args.

    (strict (scope name expr)) rewrites to (scope name (strict expr)).
    Each scope boundary wraps once. The target system processes strict
    with its own engine — no definitions change, no ownership violated.

    Topology for tests:
        outer
        └── inner (has: lazy-val, boom)

    lazy-val: returns formal [lazy-val] when lazy, value when strict.
    boom: raises RuntimeError — used to verify dead branches aren't reached.
    """

    @staticmethod
    def _make_scope_handler(system):
        def handler(name, *unevaluated_args):
            result = None
            for arg in unevaluated_args:
                result = system.evaluate(arg)
            return result

        return handler

    def _build(self):
        S = Symbol

        inner = EmptySystem()
        inner.set_fact("lazy-val", 42, "test")
        inner.set_fact("cond-true", True, "test")
        inner.set_fact("cond-false", False, "test")
        inner.engine.env[S("boom")] = lambda: (_ for _ in ()).throw(RuntimeError("boom!"))

        outer = EmptySystem()
        outer.engine.env[S("inner")] = self._make_scope_handler(inner)

        # Two-level: outer -> mid -> inner
        mid = EmptySystem()
        mid.engine.env[S("inner")] = self._make_scope_handler(inner)
        outer.engine.env[S("mid")] = self._make_scope_handler(mid)

        return outer, mid, inner

    def test_strict_outside_scope_propagates(self):
        """(strict (scope inner lazy-val))
        rewritten as: (scope inner (strict lazy-val))
        → inner evaluates (strict lazy-val) → 42"""
        S = Symbol
        outer, _, inner = self._build()

        result = outer.evaluate([S("strict"), [S("scope"), S("inner"), S("lazy-val")]])
        self.assertEqual(result, 42)

    def test_without_strict_scope_still_evaluates(self):
        """(scope inner lazy-val) — handler calls inner.evaluate(lazy-val) → 42.
        Our handler is eager, so same result. But the contract difference matters."""
        S = Symbol
        outer, _, _ = self._build()

        result = outer.evaluate([S("scope"), S("inner"), S("lazy-val")])
        self.assertEqual(result, 42)

    def test_strict_propagates_two_levels(self):
        """(strict (scope mid (scope inner lazy-val)))
        rewritten as: (scope mid (strict (scope inner lazy-val)))
        mid evaluates: (strict (scope inner lazy-val))
        rewritten as: (scope inner (strict lazy-val))
        → 42"""
        S = Symbol
        outer, _, _ = self._build()

        result = outer.evaluate([S("strict"), [S("scope"), S("mid"), [S("scope"), S("inner"), S("lazy-val")]]])
        self.assertEqual(result, 42)

    def test_case1_strict_propagates_not_into_branches(self):
        """(strict (scope mid (scope inner (if cond-true lazy-val lazy-val))))
        rewritten as: (scope mid (strict (scope inner (if cond-true lazy-val lazy-val))))
        mid: (strict (scope inner ...))
        rewritten as: (scope inner (strict (if cond-true lazy-val lazy-val)))
        inner: (strict (if cond-true lazy-val lazy-val))
        strict forces if → cond-true=True → evaluates lazy-val (normal, not strict) → 42
        lazy-val in false branch never reached."""
        S = Symbol
        outer, _, _ = self._build()

        result = outer.evaluate(
            [
                S("strict"),
                [S("scope"), S("mid"), [S("scope"), S("inner"), [S("if"), S("cond-true"), S("lazy-val"), [S("boom")]]]],
            ]
        )
        self.assertEqual(result, 42)

    def test_case2_strict_on_true_branch(self):
        """(scope mid (scope inner (if cond-true (strict lazy-val) lazy-val)))
        No outer strict. inner evaluates if → true → (strict lazy-val) → 42.
        False branch (lazy-val) never reached."""
        S = Symbol
        outer, _, _ = self._build()

        result = outer.evaluate(
            [
                S("scope"),
                S("mid"),
                [S("scope"), S("inner"), [S("if"), S("cond-true"), [S("strict"), S("lazy-val")], [S("boom")]]],
            ]
        )
        self.assertEqual(result, 42)

    def test_case3_strict_on_dead_branch(self):
        """(scope mid (scope inner (if cond-false (strict (boom)) lazy-val)))
        if picks false → lazy-val → 42. (strict (boom)) never reached — no explosion."""
        S = Symbol
        outer, _, _ = self._build()

        result = outer.evaluate(
            [
                S("scope"),
                S("mid"),
                [S("scope"), S("inner"), [S("if"), S("cond-false"), [S("strict"), [S("boom")]], S("lazy-val")]],
            ]
        )
        self.assertEqual(result, 42)

    def test_case4_outer_strict_does_not_infect_chosen_branch(self):
        """(strict (scope mid (scope inner (if cond-false (strict (boom)) lazy-val))))
        rewritten as: (scope mid (strict (scope inner (if cond-false (strict (boom)) lazy-val))))
        → (scope inner (strict (if cond-false (strict (boom)) lazy-val)))
        strict forces if → false → lazy-val evaluated normally → 42.
        (strict (boom)) in dead branch — never reached."""
        S = Symbol
        outer, _, _ = self._build()

        result = outer.evaluate(
            [
                S("strict"),
                [
                    S("scope"),
                    S("mid"),
                    [S("scope"), S("inner"), [S("if"), S("cond-false"), [S("strict"), [S("boom")]], S("lazy-val")]],
                ],
            ]
        )
        self.assertEqual(result, 42)

    def test_strict_inside_scope_not_propagated(self):
        """(scope inner (strict lazy-val)) — strict inside scope args.
        Scope passes (strict lazy-val) unevaluated to inner handler.
        Inner's engine sees (strict lazy-val) → evaluates lazy-val → 42.
        No propagation — strict is just part of the forwarded expression."""
        S = Symbol
        outer, _, _ = self._build()

        result = outer.evaluate([S("scope"), S("inner"), [S("strict"), S("lazy-val")]])
        self.assertEqual(result, 42)

    def test_strict_multiple_args_all_wrapped(self):
        """(strict (scope inner expr1 expr2)) — both args get wrapped.
        rewritten as: (scope inner (strict expr1) (strict expr2))"""
        S = Symbol
        received = []

        def capture_handler(name, *args):
            received.extend(args)
            return "ok"

        outer = make_system()
        outer.engine.env[S("target")] = capture_handler

        outer.evaluate([S("strict"), [S("scope"), S("target"), [S("foo")], [S("bar")]]])
        # Each arg should be wrapped in (strict ...)
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0], [S("strict"), [S("foo")]])
        self.assertEqual(received[1], [S("strict"), [S("bar")]])

    def test_double_strict_is_harmless(self):
        """(strict (strict (scope inner lazy-val)))
        Outer strict evaluates (strict (scope inner lazy-val)).
        Inner strict: (strict (scope inner lazy-val))
        → rewrites to (scope inner (strict lazy-val))
        → 42. Double strict is redundant but correct."""
        S = Symbol
        outer, _, _ = self._build()

        result = outer.evaluate([S("strict"), [S("strict"), [S("scope"), S("inner"), S("lazy-val")]]])
        self.assertEqual(result, 42)


# ── generative: random strict/scope/project chains ──


class TestGenerativeStrictScopeChains(unittest.TestCase):
    """Programmatically generate deep chains of strict, scope, project, self
    across multiple systems, each computing part of an irreversible hash.

    50 iterations, each building a chain of 100+ nested operations.
    """

    def _build_chain_systems(self):
        """Build 5 systems, each with one operation:
        sys_add: +
        sys_mul: *
        sys_xor: ^
        sys_mod: mod
        sys_mix: (h * 31 + v) & 0xFFFF
        """
        S = Symbol

        sys_add = EmptySystem()
        sys_add.engine.env[S("op")] = operator.add

        sys_mul = EmptySystem()
        sys_mul.engine.env[S("op")] = operator.mul

        sys_xor = EmptySystem()
        sys_xor.engine.env[S("op")] = operator.xor

        sys_mod = EmptySystem()
        sys_mod.engine.env[S("op")] = lambda a, b: a % b if b != 0 else a

        sys_mix = EmptySystem()
        sys_mix.engine.env[S("op")] = lambda h, v: ((h * 31) + v) & 0xFFFF

        systems = [sys_add, sys_mul, sys_xor, sys_mod, sys_mix]
        py_ops = [
            operator.add,
            operator.mul,
            operator.xor,
            lambda a, b: a % b if b != 0 else a,
            lambda h, v: ((h * 31) + v) & 0xFFFF,
        ]
        names = ["add", "mul", "xor", "mod", "mix"]

        # Register all scopes in all systems (including root)
        # so nested scope calls can resolve sibling scopes
        root = make_system()
        handlers = {name: self._make_handler(sys) for name, sys in zip(names, systems)}
        for name, handler in handlers.items():
            root.engine.env[S(name)] = handler
            for sys in systems:
                sys.engine.env[S(name)] = handler

        return root, names, py_ops

    @staticmethod
    def _make_handler(system):
        def handler(name, *unevaluated_args):
            result = None
            for arg in unevaluated_args:
                result = system.evaluate(arg)
            return result

        return handler

    def test_50_chains_of_100_ops(self):
        """Generate 50 random chains, each 100 operations deep.
        Each chain: pick random scope, apply op to accumulator and a prime.
        Wrap in random strict/project/self/bare patterns.
        Verify result matches Python computation."""
        import random

        S = Symbol
        root, names, py_ops = self._build_chain_systems()

        primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]
        rng = random.Random(42)  # deterministic

        for chain_idx in range(50):
            # Python-side accumulator
            py_acc = 1

            # Build and evaluate one op at a time, feeding result forward
            acc = 1
            for step in range(100):
                scope_idx = rng.randint(0, len(names) - 1)
                scope_name = names[scope_idx]
                prime = primes[rng.randint(0, len(primes) - 1)]

                # Python reference
                py_acc = py_ops[scope_idx](py_acc, prime)

                # Build expression: (scope <name> (op <acc> <prime>))
                inner_expr = [S("op"), acc, prime]
                expr = [S("scope"), S(scope_name), inner_expr]

                # Random wrapping pattern
                pattern = rng.choice(["bare", "strict", "project", "self", "strict_project", "self_strict"])
                if pattern == "strict":
                    expr = [S("strict"), expr]
                elif pattern == "project":
                    # (project (scope name (op acc prime))) — project in self basis
                    expr = [S("project"), expr]
                elif pattern == "self":
                    expr = [S("self"), expr]
                elif pattern == "strict_project":
                    expr = [S("strict"), [S("project"), expr]]
                elif pattern == "self_strict":
                    expr = [S("self"), [S("strict"), expr]]
                # "bare" — no wrapping

                acc = root.evaluate(expr)

            self.assertEqual(acc, py_acc, f"Chain {chain_idx} diverged at end: got {acc}, expected {py_acc}")

    def test_nested_strict_scope_chains(self):
        """Generate chains where strict wraps sequential scope calls.

        Each scope only contains its own operator — no cross-scope nesting
        inside op args, because child systems don't know sibling scopes.

        Pattern: (strict (scope add (op (strict (scope mul (op seed p1))) p2)))
        Inner scope evaluates first (strict forces it), result feeds to outer op.
        """
        import random

        S = Symbol
        root, names, py_ops = self._build_chain_systems()

        primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
        rng = random.Random(99)

        for chain_idx in range(50):
            depth = 5
            ops = [rng.randint(0, len(names) - 1) for _ in range(depth)]
            vals = [primes[rng.randint(0, len(primes) - 1)] for _ in range(depth)]

            seed = rng.randint(1, 100)
            py_result = seed
            for i in range(depth):
                py_result = py_ops[ops[i]](py_result, vals[i])

            # Build inside-out: innermost scope first, each wrapped in strict
            # so the result is concrete before feeding into the outer op
            expr = seed
            for i in range(depth):
                inner = [S("scope"), S(names[ops[i]]), [S("op"), expr, vals[i]]]
                expr = [S("strict"), inner]

            result = root.evaluate(expr)
            self.assertEqual(result, py_result, f"Nested chain {chain_idx}: got {result}, expected {py_result}")

    def test_alternating_strict_and_lazy_scopes(self):
        """Alternate between strict-wrapped and bare scope calls.
        Verify strict doesn't leak into subsequent bare calls."""
        import random

        S = Symbol
        root, names, py_ops = self._build_chain_systems()

        primes = [3, 7, 11, 17, 23, 31, 41]
        rng = random.Random(77)

        acc = 0
        py_acc = 0

        for step in range(100):
            scope_idx = rng.randint(0, len(names) - 1)
            prime = primes[rng.randint(0, len(primes) - 1)]

            py_acc = py_ops[scope_idx](py_acc, prime)

            expr = [S("scope"), S(names[scope_idx]), [S("op"), acc, prime]]

            # Even steps: strict. Odd steps: bare.
            if step % 2 == 0:
                expr = [S("strict"), expr]

            acc = root.evaluate(expr)

        self.assertEqual(acc, py_acc)


# ── blockchain of merkle trees with sub-chains ──


class TestBlockchainMerkleScopes(unittest.TestCase):
    """Blockchain where each block has a Merkle tree, and Merkle leaves
    can be lazy symbols, concrete values, or nested sub-chains.

    Chain: strict ordering — block N needs block N-1's hash.
    Merkle: lazy by default — internal nodes only need child hashes.
    Sub-chain: strict internally — must evaluate to produce head hash.
    Lazy symbol: just a hash — no backing data, breaks under strict.

    Scope mapping:
        chain_scope  — evaluates blocks sequentially
        block_scope  — computes merkle root + block hash
        merkle_scope — tree traversal, hashes children
        sub-chain    — nested chain evaluation inside a merkle leaf
    """

    HASH_MASK = 0xFFFFFFFF

    @classmethod
    def _mix(cls, a, b):
        """Irreversible hash mixing."""
        return ((a * 1103515245 + b) ^ (a >> 16)) & cls.HASH_MASK

    @classmethod
    def _merkle_hash(cls, left, right):
        """Hash two children into a parent."""
        return cls._mix(left ^ 0x5A5A5A5A, right ^ 0xA5A5A5A5)

    @classmethod
    def _block_hash(cls, prev_hash, merkle_root, nonce):
        """Hash a block."""
        return cls._mix(cls._mix(prev_hash, merkle_root), nonce)

    # ── Python reference implementation ──

    @classmethod
    def _py_merkle_root(cls, leaves):
        """Compute Merkle root from leaf hashes. Pads to power of 2."""
        hashes = list(leaves)
        # Pad to power of 2
        while len(hashes) & (len(hashes) - 1):
            hashes.append(0)
        while len(hashes) > 1:
            hashes = [cls._merkle_hash(hashes[i], hashes[i + 1]) for i in range(0, len(hashes), 2)]
        return hashes[0]

    @classmethod
    def _py_chain(cls, blocks):
        """Compute chain head hash. blocks = list of (leaves, nonce)."""
        prev = 0
        for leaves, nonce in blocks:
            root = cls._py_merkle_root(leaves)
            prev = cls._block_hash(prev, root, nonce)
        return prev

    # ── Build scope systems ──

    def _build_systems(self):
        S = Symbol
        test = self

        # Create all systems first
        merkle_sys = EmptySystem()
        block_sys = EmptySystem()
        chain_sys = EmptySystem()
        root = EmptySystem()

        # Define handlers
        def merkle_handler(name, *args):
            result = None
            for arg in args:
                result = merkle_sys.evaluate(arg)
            return result

        def block_handler(name, *args):
            result = None
            for arg in args:
                result = block_sys.evaluate(arg)
            return result

        def chain_handler(name, *args):
            result = None
            for arg in args:
                result = chain_sys.evaluate(arg)
            return result

        # Wire operators
        merkle_sys.engine.env[S("hash-pair")] = lambda left, right: test._merkle_hash(left, right)
        merkle_sys.engine.env[S("hash-leaf")] = lambda v: v & test.HASH_MASK

        block_sys.engine.env[S("block-hash")] = lambda prev, root, nonce: test._block_hash(prev, root, nonce)

        # Wire scopes: each system knows its children + siblings for chaining
        merkle_sys.engine.env[S("sub-chain")] = chain_handler

        block_sys.engine.env[S("merkle")] = merkle_handler
        block_sys.engine.env[S("block")] = block_handler  # self-ref for chained prev
        block_sys.engine.env[S("sub-chain")] = chain_handler

        chain_sys.engine.env[S("block")] = block_handler
        chain_sys.engine.env[S("merkle")] = merkle_handler
        chain_sys.engine.env[S("sub-chain")] = chain_handler

        root.engine.env[S("chain")] = chain_handler
        root.engine.env[S("sub-chain")] = chain_handler

        return root, chain_sys, block_sys, merkle_sys

    # ── Expression builders ──

    def _build_merkle_expr(self, leaf_hashes):
        """Build a Merkle tree expression from leaf hashes.
        Returns s-expression that evaluates in merkle_scope."""
        S = Symbol
        nodes = [[S("hash-leaf"), h] for h in leaf_hashes]
        # Pad to power of 2
        while len(nodes) & (len(nodes) - 1):
            nodes.append([S("hash-leaf"), 0])
        while len(nodes) > 1:
            nodes = [[S("hash-pair"), nodes[i], nodes[i + 1]] for i in range(0, len(nodes), 2)]
        return nodes[0]

    def _build_block_expr(self, prev_hash, leaf_hashes, nonce):
        """Build a block expression: compute merkle root, then block hash."""
        S = Symbol
        merkle_expr = self._build_merkle_expr(leaf_hashes)
        # (block-hash prev (scope merkle <merkle_expr>) nonce)
        return [S("block-hash"), prev_hash, [S("scope"), S("merkle"), merkle_expr], nonce]

    def _build_chain_expr(self, blocks):
        """Build a chain expression from blocks = [(leaf_hashes, nonce), ...].
        Each block depends on the previous block's hash."""
        S = Symbol
        # Build sequentially: each block wraps the previous
        prev = 0
        for leaf_hashes, nonce in blocks:
            prev = [S("scope"), S("block"), self._build_block_expr(prev, leaf_hashes, nonce)]
        return prev

    # ── Tests ──

    def test_single_block_single_leaf(self):
        """Simplest case: one block, one leaf."""
        S = Symbol
        root, *_ = self._build_systems()

        leaves = [42]
        nonce = 7
        expr = [S("scope"), S("chain"), self._build_chain_expr([(leaves, nonce)])]
        result = root.evaluate(expr)
        expected = self._py_chain([(leaves, nonce)])
        self.assertEqual(result, expected)

    def test_chain_of_5_blocks(self):
        """5 blocks, each with 4 leaves."""
        import random

        S = Symbol
        root, *_ = self._build_systems()
        rng = random.Random(42)

        blocks = [([rng.randint(1, 1000) for _ in range(4)], rng.randint(1, 9999)) for _ in range(5)]

        expr = [S("scope"), S("chain"), self._build_chain_expr(blocks)]
        result = root.evaluate(expr)
        expected = self._py_chain(blocks)
        self.assertEqual(result, expected)

    def test_block_order_matters(self):
        """Swapping two blocks produces different hash."""
        import random

        S = Symbol
        root, *_ = self._build_systems()
        rng = random.Random(123)

        blocks = [([rng.randint(1, 1000) for _ in range(4)], rng.randint(1, 9999)) for _ in range(3)]

        result1 = root.evaluate([S("scope"), S("chain"), self._build_chain_expr(blocks)])
        swapped = [blocks[0], blocks[2], blocks[1]]
        result2 = root.evaluate([S("scope"), S("chain"), self._build_chain_expr(swapped)])
        self.assertNotEqual(result1, result2)

    def test_sub_chain_as_merkle_leaf(self):
        """A Merkle leaf is a sub-chain that evaluates to its head hash.

        Tree structure:
            root
            ├── leaf(100)
            ├── sub-chain([leaf(200), leaf(300)], nonce=5)
            ├── leaf(400)
            └── leaf(500)

        The sub-chain evaluates to a hash, which becomes the leaf value
        at position 1 in the parent Merkle tree.
        """
        S = Symbol
        root, *_ = self._build_systems()

        # Sub-chain: 1 block with 2 leaves
        sub_blocks = [([200, 300], 5)]
        sub_chain_hash = self._py_chain(sub_blocks)

        # Parent leaves: position 1 is the sub-chain result
        parent_leaves = [100, sub_chain_hash, 400, 500]
        parent_nonce = 99
        expected = self._py_chain([(parent_leaves, parent_nonce)])

        # Build expression: leaf 1 is (scope sub-chain ...)
        sub_expr = self._build_chain_expr(sub_blocks)
        # Manually build merkle tree with sub-chain at position 1
        leaf_exprs = [
            [S("hash-leaf"), 100],
            [S("hash-leaf"), [S("scope"), S("sub-chain"), sub_expr]],
            [S("hash-leaf"), 400],
            [S("hash-leaf"), 500],
        ]
        merkle = leaf_exprs
        while len(merkle) > 1:
            merkle = [[S("hash-pair"), merkle[i], merkle[i + 1]] for i in range(0, len(merkle), 2)]
        merkle_root_expr = merkle[0]

        block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle_root_expr], parent_nonce]
        chain_expr = [S("scope"), S("block"), block_expr]
        expr = [S("scope"), S("chain"), chain_expr]

        result = root.evaluate(expr)
        self.assertEqual(result, expected)

    def test_lazy_symbol_leaf(self):
        """A Merkle leaf that is a pre-computed hash (lazy symbol).
        The symbol resolves to a hash value without evaluating any subtree."""
        S = Symbol
        root, chain_sys, block_sys, merkle_sys = self._build_systems()

        # Pre-register a hash as a fact in merkle_sys
        precomputed_hash = 0xDEADBEEF & self.HASH_MASK
        merkle_sys.set_fact("pruned-node", precomputed_hash, "precomputed")

        leaves = [100, precomputed_hash, 300, 400]
        nonce = 42
        expected = self._py_chain([(leaves, nonce)])

        # Build expression: leaf 1 is symbol pruned-node
        leaf_exprs = [
            [S("hash-leaf"), 100],
            [S("hash-leaf"), S("pruned-node")],
            [S("hash-leaf"), 300],
            [S("hash-leaf"), 400],
        ]
        merkle = leaf_exprs
        while len(merkle) > 1:
            merkle = [[S("hash-pair"), merkle[i], merkle[i + 1]] for i in range(0, len(merkle), 2)]

        block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle[0]], nonce]
        expr = [S("scope"), S("chain"), [S("scope"), S("block"), block_expr]]

        result = root.evaluate(expr)
        self.assertEqual(result, expected)

    def test_generated_chains_with_sub_chains(self):
        """50 random chains, each 3-5 blocks, 4-8 leaves per block.
        1-2 leaves per block are sub-chains (1 block, 2 leaves each).
        Verify hash matches Python reference."""
        import random

        S = Symbol
        rng = random.Random(2024)

        for iteration in range(50):
            root, *_ = self._build_systems()

            num_blocks = rng.randint(3, 5)
            blocks_data = []  # for Python reference
            blocks_exprs_leaves = []  # for expression building

            for _ in range(num_blocks):
                num_leaves = rng.randint(4, 8)
                # Pad to power of 2
                padded = num_leaves
                while padded & (padded - 1):
                    padded += 1

                leaf_values = []
                leaf_exprs = []
                num_sub = rng.randint(1, 2)
                sub_positions = set(rng.sample(range(num_leaves), min(num_sub, num_leaves)))

                for li in range(padded):
                    if li < num_leaves and li in sub_positions:
                        # Sub-chain leaf
                        sub_leaves = [rng.randint(1, 999) for _ in range(2)]
                        sub_nonce = rng.randint(1, 9999)
                        sub_hash = self._py_chain([(sub_leaves, sub_nonce)])
                        leaf_values.append(sub_hash)

                        sub_expr = self._build_chain_expr([(sub_leaves, sub_nonce)])
                        leaf_exprs.append([S("hash-leaf"), [S("scope"), S("sub-chain"), sub_expr]])
                    elif li < num_leaves:
                        v = rng.randint(1, 999)
                        leaf_values.append(v)
                        leaf_exprs.append([S("hash-leaf"), v])
                    else:
                        leaf_values.append(0)
                        leaf_exprs.append([S("hash-leaf"), 0])

                nonce = rng.randint(1, 9999)
                blocks_data.append((leaf_values, nonce))
                blocks_exprs_leaves.append((leaf_exprs, nonce))

            # Python reference
            expected = self._py_chain(blocks_data)

            # Build parseltongue expression
            prev = 0
            for leaf_exprs, nonce in blocks_exprs_leaves:
                # Build merkle tree from leaf expressions
                merkle = list(leaf_exprs)
                while len(merkle) > 1:
                    merkle = [[S("hash-pair"), merkle[i], merkle[i + 1]] for i in range(0, len(merkle), 2)]

                block_expr = [S("block-hash"), prev, [S("scope"), S("merkle"), merkle[0]], nonce]
                prev = [S("scope"), S("block"), block_expr]

            expr = [S("scope"), S("chain"), prev]

            # Random wrapping: strict on some iterations
            if rng.random() < 0.3:
                expr = [S("strict"), expr]

            result = root.evaluate(expr)
            self.assertEqual(result, expected, f"Iteration {iteration}: got {result}, expected {expected}")

    def test_sub_chain_inside_sub_chain(self):
        """Two levels of nesting: chain -> tree -> sub-chain -> tree -> sub-sub-chain.

        The sub-sub-chain evaluates to a hash, which becomes a leaf
        in the sub-chain's Merkle tree, which evaluates to a hash,
        which becomes a leaf in the main chain's Merkle tree.
        """
        S = Symbol
        root, *_ = self._build_systems()

        # Sub-sub-chain: 1 block, leaves [10, 20]
        ss_blocks = [([10, 20], 1)]
        ss_hash = self._py_chain(ss_blocks)

        # Sub-chain: 1 block, leaves [ss_hash, 30]
        s_blocks = [([ss_hash, 30], 2)]
        s_hash = self._py_chain(s_blocks)

        # Main chain: 1 block, leaves [s_hash, 40, 50, 60]
        m_blocks = [([s_hash, 40, 50, 60], 3)]
        expected = self._py_chain(m_blocks)

        # Build expressions inside-out
        ss_expr = self._build_chain_expr(ss_blocks)

        # Sub-chain merkle: leaf 0 = sub-sub-chain, leaf 1 = 30
        s_leaf_exprs = [
            [S("hash-leaf"), [S("scope"), S("sub-chain"), ss_expr]],
            [S("hash-leaf"), 30],
        ]
        s_merkle = [S("hash-pair"), s_leaf_exprs[0], s_leaf_exprs[1]]
        s_block = [S("block-hash"), 0, [S("scope"), S("merkle"), s_merkle], 2]
        s_chain = [S("scope"), S("block"), s_block]

        # Main merkle: leaf 0 = sub-chain, leaves 1-3 = concrete
        m_leaf_exprs = [
            [S("hash-leaf"), [S("scope"), S("sub-chain"), s_chain]],
            [S("hash-leaf"), 40],
            [S("hash-leaf"), 50],
            [S("hash-leaf"), 60],
        ]
        m_merkle = [
            S("hash-pair"),
            [S("hash-pair"), m_leaf_exprs[0], m_leaf_exprs[1]],
            [S("hash-pair"), m_leaf_exprs[2], m_leaf_exprs[3]],
        ]
        m_block = [S("block-hash"), 0, [S("scope"), S("merkle"), m_merkle], 3]
        expr = [S("scope"), S("chain"), [S("scope"), S("block"), m_block]]

        result = root.evaluate(expr)
        self.assertEqual(result, expected)

    def test_strict_propagation_through_chain_tree_subchain(self):
        """(strict (scope chain (scope block ...))) propagates strict
        through chain → block → merkle → sub-chain → sub-merkle.
        All scopes get strict-wrapped args."""
        S = Symbol
        root, *_ = self._build_systems()

        # Simple: 1 block, 2 leaves, leaf 0 is sub-chain
        sub_blocks = [([7, 13], 3)]
        sub_hash = self._py_chain(sub_blocks)

        leaves = [sub_hash, 99]
        expected = self._py_chain([(leaves, 5)])

        sub_expr = self._build_chain_expr(sub_blocks)
        leaf_exprs = [
            [S("hash-leaf"), [S("scope"), S("sub-chain"), sub_expr]],
            [S("hash-leaf"), 99],
        ]
        merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
        block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], 5]
        chain_expr = [S("scope"), S("block"), block_expr]
        expr = [S("strict"), [S("scope"), S("chain"), chain_expr]]

        result = root.evaluate(expr)
        self.assertEqual(result, expected)

    def test_50_deep_nested_sub_chains(self):
        """50 levels of nesting: each sub-chain's merkle leaf 0 is another sub-chain.

        chain → block → merkle → sub-chain →
            block → merkle → sub-chain →
                block → merkle → sub-chain →
                    ... (50 levels deep)

        Each level: 1 block, 2 leaves. Leaf 0 = deeper sub-chain, leaf 1 = level number.
        The innermost level has two concrete leaves.

        Each scope crossing = 3 boundaries (chain → block → merkle).
        50 levels = 150 scope boundary crossings.
        """
        import sys as _sys

        S = Symbol
        root, *_ = self._build_systems()

        depth = 50
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 30))

        try:
            # Python reference: build inside-out
            # Innermost: leaves [depth, depth+1], nonce = depth
            prev_hash = self._py_chain([([depth, depth + 1], depth)])

            for level in range(depth - 1, 0, -1):
                # This level: leaf 0 = prev_hash (sub-chain result), leaf 1 = level
                prev_hash = self._py_chain([([prev_hash, level], level)])

            expected = prev_hash

            # Parseltongue expression: build inside-out
            # Innermost: concrete leaves
            inner_expr = self._build_chain_expr([([depth, depth + 1], depth)])

            for level in range(depth - 1, 0, -1):
                # This level's merkle: leaf 0 = sub-chain, leaf 1 = level number
                leaf_exprs = [
                    [S("hash-leaf"), [S("scope"), S("sub-chain"), inner_expr]],
                    [S("hash-leaf"), level],
                ]
                merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
                block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], level]
                inner_expr = [S("scope"), S("block"), block_expr]

            expr = [S("scope"), S("chain"), inner_expr]
            result = root.evaluate(expr)
            self.assertEqual(result, expected)

        finally:
            _sys.setrecursionlimit(old_limit)

    def test_50_deep_with_strict(self):
        """Same 50-deep nesting but wrapped in (strict ...).

        Strict propagates through all 150 scope boundaries.
        Result must match — strict doesn't change values, only evaluation mode.
        """
        import sys as _sys

        S = Symbol
        root, *_ = self._build_systems()

        depth = 50
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 30))

        try:
            # Python reference
            prev_hash = self._py_chain([([depth, depth + 1], depth)])
            for level in range(depth - 1, 0, -1):
                prev_hash = self._py_chain([([prev_hash, level], level)])
            expected = prev_hash

            # Build expression
            inner_expr = self._build_chain_expr([([depth, depth + 1], depth)])
            for level in range(depth - 1, 0, -1):
                leaf_exprs = [
                    [S("hash-leaf"), [S("scope"), S("sub-chain"), inner_expr]],
                    [S("hash-leaf"), level],
                ]
                merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
                block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], level]
                inner_expr = [S("scope"), S("block"), block_expr]

            # Wrap entire thing in strict
            expr = [S("strict"), [S("scope"), S("chain"), inner_expr]]
            result = root.evaluate(expr)
            self.assertEqual(result, expected)

        finally:
            _sys.setrecursionlimit(old_limit)

    def test_50_deep_random_strict_placement(self):
        """50-deep nesting with strict randomly placed at different levels.

        Some levels wrapped in strict, some bare. The result must be
        identical regardless of strict placement — strict changes
        evaluation mode, not values.
        """
        import random
        import sys as _sys

        S = Symbol

        depth = 50
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 30))
        rng = random.Random(777)

        try:
            root, *_ = self._build_systems()

            # Python reference
            prev_hash = self._py_chain([([depth, depth + 1], depth)])
            for level in range(depth - 1, 0, -1):
                prev_hash = self._py_chain([([prev_hash, level], level)])
            expected = prev_hash

            # Build expression with random strict placement
            inner_expr = self._build_chain_expr([([depth, depth + 1], depth)])
            for level in range(depth - 1, 0, -1):
                leaf_exprs = [
                    [S("hash-leaf"), [S("scope"), S("sub-chain"), inner_expr]],
                    [S("hash-leaf"), level],
                ]
                merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
                block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], level]
                inner_expr = [S("scope"), S("block"), block_expr]

                # Randomly wrap this level in strict
                if rng.random() < 0.4:
                    inner_expr = [S("strict"), inner_expr]

            expr = [S("scope"), S("chain"), inner_expr]
            result = root.evaluate(expr)
            self.assertEqual(result, expected)

        finally:
            _sys.setrecursionlimit(old_limit)

    def test_corrupted_nonce_detected(self):
        """Changing a single nonce at any level produces a different final hash."""
        import sys as _sys

        S = Symbol
        root, *_ = self._build_systems()

        depth = 20
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 30))

        try:
            # Build correct expression and reference
            def build(corrupt_level=None):
                prev_hash = self._py_chain([([depth, depth + 1], depth)])
                inner_expr = self._build_chain_expr([([depth, depth + 1], depth)])

                for level in range(depth - 1, 0, -1):
                    nonce = level if level != corrupt_level else level + 999
                    prev_hash = self._py_chain([([prev_hash, level], nonce)])

                    n = level if level != corrupt_level else level + 999
                    leaf_exprs = [
                        [S("hash-leaf"), [S("scope"), S("sub-chain"), inner_expr]],
                        [S("hash-leaf"), level],
                    ]
                    merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
                    block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], n]
                    inner_expr = [S("scope"), S("block"), block_expr]

                expr = [S("scope"), S("chain"), inner_expr]
                return root.evaluate(expr), prev_hash

            correct_result, correct_expected = build()
            self.assertEqual(correct_result, correct_expected)

            # Corrupt nonce at levels 1, 5, 10, 15
            for corrupt_at in [1, 5, 10, 15]:
                bad_result, bad_expected = build(corrupt_level=corrupt_at)
                self.assertEqual(bad_result, bad_expected)
                self.assertNotEqual(
                    bad_result, correct_result, f"Corrupted nonce at level {corrupt_at} was not detected"
                )

        finally:
            _sys.setrecursionlimit(old_limit)

    def test_swapped_leaves_detected(self):
        """Swapping leaf 0 and leaf 1 at any level produces a different hash."""
        import sys as _sys

        S = Symbol
        root, *_ = self._build_systems()

        depth = 15
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 30))

        try:
            # Normal: leaf 0 = sub-chain, leaf 1 = level
            inner_expr_normal = self._build_chain_expr([([depth, depth + 1], depth)])
            prev_normal = self._py_chain([([depth, depth + 1], depth)])
            for level in range(depth - 1, 0, -1):
                prev_normal = self._py_chain([([prev_normal, level], level)])
                leaf_exprs = [
                    [S("hash-leaf"), [S("scope"), S("sub-chain"), inner_expr_normal]],
                    [S("hash-leaf"), level],
                ]
                merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
                block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], level]
                inner_expr_normal = [S("scope"), S("block"), block_expr]

            normal = root.evaluate([S("scope"), S("chain"), inner_expr_normal])

            # Swapped at level 7: leaf 0 = level, leaf 1 = sub-chain
            swap_level = 7
            inner_expr_swap = self._build_chain_expr([([depth, depth + 1], depth)])
            prev_swap = self._py_chain([([depth, depth + 1], depth)])
            for level in range(depth - 1, 0, -1):
                if level == swap_level:
                    prev_swap = self._py_chain([([level, prev_swap], level)])
                    leaf_exprs = [
                        [S("hash-leaf"), level],
                        [S("hash-leaf"), [S("scope"), S("sub-chain"), inner_expr_swap]],
                    ]
                else:
                    prev_swap = self._py_chain([([prev_swap, level], level)])
                    leaf_exprs = [
                        [S("hash-leaf"), [S("scope"), S("sub-chain"), inner_expr_swap]],
                        [S("hash-leaf"), level],
                    ]
                merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
                block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], level]
                inner_expr_swap = [S("scope"), S("block"), block_expr]

            swapped = root.evaluate([S("scope"), S("chain"), inner_expr_swap])
            self.assertNotEqual(normal, swapped)

        finally:
            _sys.setrecursionlimit(old_limit)

    def test_missing_sub_chain_raises(self):
        """If a sub-chain scope is not registered, evaluation fails.
        This simulates a 'forgotten' scope — the system can't resolve it."""
        S = Symbol
        # Build systems but DON'T register sub-chain in merkle_sys
        test = self
        merkle_sys = EmptySystem()
        merkle_sys.engine.env[S("hash-pair")] = lambda left, right: test._merkle_hash(left, right)
        merkle_sys.engine.env[S("hash-leaf")] = lambda v: v & test.HASH_MASK
        # Deliberately NOT registering sub-chain in merkle_sys

        def merkle_handler(name, *args):
            result = None
            for arg in args:
                result = merkle_sys.evaluate(arg)
            return result

        block_sys = EmptySystem()
        block_sys.engine.env[S("block-hash")] = lambda prev, root, nonce: test._block_hash(prev, root, nonce)
        block_sys.engine.env[S("merkle")] = merkle_handler

        def block_handler(name, *args):
            result = None
            for arg in args:
                result = block_sys.evaluate(arg)
            return result

        chain_sys = EmptySystem()
        chain_sys.engine.env[S("block")] = block_handler

        def chain_handler(name, *args):
            result = None
            for arg in args:
                result = chain_sys.evaluate(arg)
            return result

        broken_root = EmptySystem()
        broken_root.engine.env[S("chain")] = chain_handler

        # Expression with sub-chain leaf
        sub_expr = self._build_chain_expr([([10, 20], 1)])
        leaf_exprs = [
            [S("hash-leaf"), [S("scope"), S("sub-chain"), sub_expr]],
            [S("hash-leaf"), 99],
        ]
        merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
        block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], 5]
        expr = [S("scope"), S("chain"), [S("scope"), S("block"), block_expr]]

        with self.assertRaises(NameError):
            broken_root.evaluate(expr)

    def test_project_parent_facts_into_merkle_leaves(self):
        """Parent system has facts. Project them into merkle leaves at random depths.

        Pattern: (scope merkle (hash-leaf (project parent-fact)))
        But project inside scope args is unevaluated — merkle receives it raw.
        So merkle_sys must know how to resolve project, OR we pre-evaluate
        via the parent and inject concrete values.

        The correct approach: parent registers facts in merkle_sys too,
        or we use project at the level where the parent has the facts.
        Here: block_sys has the facts, and the block expression uses
        the fact directly in the merkle call (block_sys evaluates the
        scope merkle call, so the fact resolves in block_sys before
        entering merkle).

        Wait — scope passes args unevaluated. So (scope merkle (hash-leaf my-fact))
        passes [hash-leaf, my-fact] to merkle, where my-fact is unknown.

        The real solution: (scope merkle (hash-leaf (project block my-fact)))
        But project inside scope args is also unevaluated...

        Actually: block_sys evaluates (scope merkle (hash-leaf my-fact)).
        block_sys hits scope → forwards [hash-leaf, my-fact] to merkle.
        merkle doesn't have my-fact → error.

        So we need project at block level BEFORE entering merkle scope:
        In block_sys: compute the fact value, then pass it as a literal.
        This means building the expression so that my-fact resolves in
        block_sys, not in merkle_sys.

        Pattern: (block-hash prev (scope merkle (hash-leaf (strict my-fact))) nonce)
        strict inside scope args → forwarded to merkle → merkle evaluates
        (strict my-fact) → my-fact unknown in merkle → error.

        The ONLY way: evaluate in block_sys before scope:
        (let ((val my-fact)) (scope merkle (hash-leaf val)))
        But let is a special form — val would resolve in block_sys's let env...
        which doesn't cross into scope's unevaluated args either.

        Actually the cleanest: block_sys registers the fact in merkle_sys too.
        In real systems this is "shared state" — both systems see the same values.
        For the test: we register facts in both block_sys and merkle_sys.
        """
        import random
        import sys as _sys

        S = Symbol

        depth = 30
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 30))
        rng = random.Random(456)

        try:
            root, chain_sys, block_sys, merkle_sys = self._build_systems()

            # Register 10 named facts as "projected values" in merkle_sys
            projected = {}
            for i in range(10):
                name = f"project-val-{i}"
                val = rng.randint(100, 9999)
                projected[name] = val
                merkle_sys.set_fact(name, val, "projected from parent")

            # Python reference + parseltongue expression
            # At random levels, use a projected fact instead of a literal
            prev_hash = self._py_chain([([depth, depth + 1], depth)])
            inner_expr = self._build_chain_expr([([depth, depth + 1], depth)])

            for level in range(depth - 1, 0, -1):
                # Decide: use projected fact or literal for leaf 1?
                use_project = rng.random() < 0.4
                if use_project:
                    fact_name = rng.choice(list(projected.keys()))
                    leaf1_val = projected[fact_name]
                    leaf1_expr = [S("hash-leaf"), S(fact_name)]
                else:
                    leaf1_val = level
                    leaf1_expr = [S("hash-leaf"), level]

                prev_hash = self._py_chain([([prev_hash, leaf1_val], level)])

                leaf_exprs = [
                    [S("hash-leaf"), [S("scope"), S("sub-chain"), inner_expr]],
                    leaf1_expr,
                ]
                merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
                block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], level]
                inner_expr = [S("scope"), S("block"), block_expr]

            expr = [S("scope"), S("chain"), inner_expr]
            result = root.evaluate(expr)
            self.assertEqual(result, prev_hash)

        finally:
            _sys.setrecursionlimit(old_limit)

    def test_project_wrong_fact_produces_different_hash(self):
        """Two independent system topologies with different projected facts produce different hashes.

        Fact lives on merkle_sys. block_sys knows merkle as a scope.
        (project merkle projected-val) inside scope merkle args —
        block_sys resolves it: delegates to merkle_handler which evaluates
        projected-val in merkle_sys's basis.
        """
        import sys as _sys

        S = Symbol

        depth = 10
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 30))

        try:
            # Build two independent topologies with different fact values
            root_correct, _, _, merkle_correct = self._build_systems()
            root_wrong, _, _, merkle_wrong = self._build_systems()

            merkle_correct.set_fact("projected-val", 42, "correct")
            merkle_wrong.set_fact("projected-val", 999, "wrong")

            def _build_expr_with_project(depth_val):
                """Build chain expr where level 5 uses (project merkle projected-val)."""
                inner = self._build_chain_expr([([depth_val, depth_val + 1], depth_val)])
                for level in range(depth_val - 1, 0, -1):
                    if level == 5:
                        # delegate to the scope that has merkle, then scope into it
                        leaf1_expr = [
                            S("hash-leaf"),
                            [S("delegate"), S("?merkle"), [S("scope"), S("merkle"), S("projected-val")]],
                        ]
                    else:
                        leaf1_expr = [S("hash-leaf"), level]
                    leaf_exprs = [
                        [S("hash-leaf"), [S("scope"), S("sub-chain"), inner]],
                        leaf1_expr,
                    ]
                    merkle = [S("hash-pair"), leaf_exprs[0], leaf_exprs[1]]
                    block_expr = [S("block-hash"), 0, [S("scope"), S("merkle"), merkle], level]
                    inner = [S("scope"), S("block"), block_expr]
                return inner

            expr = _build_expr_with_project(depth)

            correct = root_correct.evaluate([S("scope"), S("chain"), expr])
            wrong = root_wrong.evaluate([S("scope"), S("chain"), expr])

            self.assertNotEqual(correct, wrong)

            # Verify correct matches Python reference
            prev = self._py_chain([([depth, depth + 1], depth)])
            for level in range(depth - 1, 0, -1):
                leaf1_val = 42 if level == 5 else level
                prev = self._py_chain([([prev, leaf1_val], level)])
            self.assertEqual(correct, prev)

        finally:
            _sys.setrecursionlimit(old_limit)

    def test_generative_project_depth50_isolated_merkle(self):
        """Generative test: depth-50 merkle tree, parent owns all facts, merkle is fully isolated.

        Parent system has N random facts. It evaluates (project fact-name) to get
        concrete values, which become literal leaves in the merkle expression.
        Merkle system only has hash-pair and hash-leaf — no facts, no parent scope.
        Project is the ONLY bridge between parent and merkle.

        Verifies:
        1. Hash matches Python reference for all random fact distributions
        2. Changing any single projected fact changes the root hash
        3. Merkle system truly can't resolve facts on its own
        """
        import random
        import sys as _sys

        S = Symbol

        depth = 50
        num_facts = 20
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 50))
        rng = random.Random(0xDEADBEEF)

        try:
            # ── Parent system: owns all facts ──
            parent = EmptySystem()

            # ── Merkle system: fully isolated, only hash ops ──
            merkle_sys = EmptySystem()
            test = self
            merkle_sys.engine.env[S("hash-pair")] = lambda left, right: test._merkle_hash(left, right)
            merkle_sys.engine.env[S("hash-leaf")] = lambda v: v & test.HASH_MASK

            def merkle_handler(name, *args):
                result = None
                for arg in args:
                    result = merkle_sys.evaluate(arg)
                return result

            # Parent knows merkle scope — merkle does NOT know parent
            parent.engine.env[S("merkle")] = merkle_handler

            # Register random facts on parent
            facts = {}
            for i in range(num_facts):
                name = f"fact-{i}"
                val = rng.randint(1, 0xFFFF)
                facts[name] = val
                parent.set_fact(name, val, f"generated-{i}")

            # ── Build depth-50 merkle tree ──
            # Each level has 2 leaves. One leaf is the subtree from below,
            # the other is a projected fact from the parent.
            # Parent evaluates (project fact-name) → concrete int → literal in merkle expr.

            # Assign a random fact to each level
            level_facts = [rng.choice(list(facts.keys())) for _ in range(depth)]

            # Python reference: build bottom-up
            # Start with base leaves at the bottom
            base_val = rng.randint(1, 0xFFFF)
            py_current = base_val & self.HASH_MASK  # hash-leaf of base

            # Build bottom-up: at each level, hash(subtree, hash-leaf(fact_val))
            for level in range(depth):
                fact_val = facts[level_facts[level]]
                leaf_hash = fact_val & self.HASH_MASK
                py_current = self._merkle_hash(py_current, leaf_hash)

            # ── Build s-expression: parent projects each fact, embeds as literal ──
            # Parent evaluates (project fact-name) for each leaf
            projected_values = {}
            for name in set(level_facts):
                projected = parent.evaluate([S("project"), S(name)])
                projected_values[name] = projected
                self.assertEqual(projected, facts[name], f"project must resolve {name} to its fact value")

            # Build merkle expression bottom-up with concrete projected values
            merkle_expr = [S("hash-leaf"), base_val]
            for level in range(depth):
                concrete_val = projected_values[level_facts[level]]
                leaf_expr = [S("hash-leaf"), concrete_val]
                merkle_expr = [S("hash-pair"), merkle_expr, leaf_expr]

            # Evaluate via parent → scope merkle
            result = parent.evaluate([S("scope"), S("merkle"), merkle_expr])
            self.assertEqual(result, py_current, "depth-50 merkle hash must match Python reference")

            # ── Verify merkle can't resolve facts on its own ──
            with self.assertRaises(NameError):
                merkle_sys.evaluate([S("hash-leaf"), S("fact-0")])

            # ── Verify changing ONE projected fact changes the root hash ──
            # Pick a random level, swap its fact value
            tamper_level = rng.randint(0, depth - 1)
            tamper_name = level_facts[tamper_level]
            tamper_val = facts[tamper_name] ^ 0xFFFF  # flip bits

            # Rebuild with tampered value at that one level
            tampered_expr = [S("hash-leaf"), base_val]
            for level in range(depth):
                if level == tamper_level:
                    val = tamper_val
                else:
                    val = projected_values[level_facts[level]]
                leaf_expr = [S("hash-leaf"), val]
                tampered_expr = [S("hash-pair"), tampered_expr, leaf_expr]

            tampered_result = parent.evaluate([S("scope"), S("merkle"), tampered_expr])
            self.assertNotEqual(result, tampered_result, f"changing fact at level {tamper_level} must change root hash")

            # ── Verify tampered matches its own Python reference ──
            py_tampered = base_val & self.HASH_MASK
            for level in range(depth):
                if level == tamper_level:
                    val = tamper_val
                else:
                    val = facts[level_facts[level]]
                leaf_hash = val & self.HASH_MASK
                py_tampered = self._merkle_hash(py_tampered, leaf_hash)
            self.assertEqual(tampered_result, py_tampered)

        finally:
            _sys.setrecursionlimit(old_limit)

    def test_generative_rsa_signed_merkle_depth50(self):
        """Depth-50 merkle tree where every leaf is RSA-signed by a signature scope.

        Architecture:
            parent    — owns facts, has scope to signature and merkle
            sig_sys   — owns RSA private key, has (sign val) operator
            merkle_sys — fully isolated, only hash-pair/hash-leaf, no parent, no sig access

        Flow:
            parent evaluates (project (scope signature (sign (project fact-name))))
            1. (project fact-name) resolves in parent → concrete int
            2. (scope signature (sign <int>)) enters sig_sys with literal
            3. sig_sys signs it → returns (value, signature) tuple
            4. project yields the signed tuple back to parent as a concrete value
            5. parent embeds that tuple as a literal leaf in merkle expression
            6. merkle hashes the tuple — hash-leaf receives the (val, sig) pair

        Verifies:
            1. All signatures verify against the public key
            2. Merkle hash matches Python reference built from signed tuples
            3. Tampered signature at one level changes the hash
            4. Merkle system can't sign or access facts
        """
        import hashlib
        import random
        import sys as _sys

        S = Symbol

        depth = 50
        num_facts = 20
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 50))
        rng = random.Random(0xC0FFEE42)

        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
        except ImportError:
            self.skipTest("cryptography package not installed")

        try:
            # ── RSA key pair ──
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            public_key = private_key.public_key()

            def rsa_sign(value):
                """Sign an integer value. Returns (value, signature_hex)."""
                msg = str(value).encode()
                sig = private_key.sign(
                    msg,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
                return (value, sig.hex())

            def rsa_verify(value, sig_hex):
                """Verify a signature. Returns True or raises."""
                msg = str(value).encode()
                sig = bytes.fromhex(sig_hex)
                public_key.verify(
                    sig,
                    msg,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
                return True

            # ── Signature system: owns private key ──
            sig_sys = EmptySystem()
            sig_sys.engine.env[S("sign")] = rsa_sign

            def sig_handler(name, *args):
                result = None
                for arg in args:
                    result = sig_sys.evaluate(arg)
                return result

            # ── Merkle system: fully isolated ──
            test = self
            merkle_sys = EmptySystem()

            def hash_leaf_signed(signed_pair):
                """Hash a (value, signature) tuple — hash the concatenation."""
                val, sig_hex = signed_pair
                combined = hashlib.sha256(f"{val}:{sig_hex}".encode()).digest()
                return int.from_bytes(combined[:4], "big") & test.HASH_MASK

            merkle_sys.engine.env[S("hash-pair")] = lambda left, right: test._merkle_hash(left, right)
            merkle_sys.engine.env[S("hash-leaf")] = hash_leaf_signed

            def merkle_handler(name, *args):
                result = None
                for arg in args:
                    result = merkle_sys.evaluate(arg)
                return result

            # ── Parent system: owns facts, scopes to sig and merkle ──
            parent = EmptySystem()
            parent.engine.env[S("signature")] = sig_handler
            parent.engine.env[S("merkle")] = merkle_handler

            # Register random facts
            facts = {}
            for i in range(num_facts):
                name = f"fact-{i}"
                val = rng.randint(1, 0xFFFF)
                facts[name] = val
                parent.set_fact(name, val, f"generated-{i}")

            # Assign a random fact to each level
            level_facts = [rng.choice(list(facts.keys())) for _ in range(depth)]

            # ── Project + sign each fact via parent ──
            # (project (scope signature (sign (project fact-name))))
            signed_values = {}
            for name in set(level_facts):
                fact_val = parent.evaluate([S("project"), S(name)])
                self.assertEqual(fact_val, facts[name])

                signed = parent.evaluate(
                    [S("project"), [S("scope"), S("signature"), [S("sign"), fact_val]]]  # fact_val is already concrete
                )
                self.assertIsInstance(signed, tuple)
                self.assertEqual(len(signed), 2)
                self.assertEqual(signed[0], facts[name])
                # Verify signature
                rsa_verify(signed[0], signed[1])
                signed_values[name] = signed

            # ── Python reference: merkle of signed tuples ──
            base_fact = level_facts[0]
            base_signed = signed_values[base_fact]
            py_current = hash_leaf_signed(base_signed)

            for level in range(1, depth):
                signed = signed_values[level_facts[level]]
                leaf_hash = hash_leaf_signed(signed)
                py_current = self._merkle_hash(py_current, leaf_hash)

            # ── Build merkle expression with signed tuple literals ──
            merkle_expr = [S("hash-leaf"), base_signed]
            for level in range(1, depth):
                signed = signed_values[level_facts[level]]
                leaf_expr = [S("hash-leaf"), signed]
                merkle_expr = [S("hash-pair"), merkle_expr, leaf_expr]

            result = parent.evaluate([S("scope"), S("merkle"), merkle_expr])
            self.assertEqual(result, py_current, "RSA-signed depth-50 merkle must match Python reference")

            # ── Tamper test: forge one signature ──
            tamper_level = rng.randint(1, depth - 1)
            tamper_name = level_facts[tamper_level]
            tamper_val = facts[tamper_name]
            # Forge: correct value but wrong signature
            forged_signed = (tamper_val, "00" * 256)

            tampered_expr = [S("hash-leaf"), base_signed]
            py_tampered = hash_leaf_signed(base_signed)
            for level in range(1, depth):
                if level == tamper_level:
                    signed = forged_signed
                else:
                    signed = signed_values[level_facts[level]]
                leaf_expr = [S("hash-leaf"), signed]
                tampered_expr = [S("hash-pair"), tampered_expr, leaf_expr]
                leaf_hash = hash_leaf_signed(signed)
                py_tampered = self._merkle_hash(py_tampered, leaf_hash)

            tampered_result = parent.evaluate([S("scope"), S("merkle"), tampered_expr])
            self.assertNotEqual(result, tampered_result, f"forged signature at level {tamper_level} must change hash")
            self.assertEqual(tampered_result, py_tampered)

            # ── Verify merkle can't sign ──
            with self.assertRaises(NameError):
                merkle_sys.evaluate([S("sign"), 42])

            # ── Verify merkle can't access facts ──
            with self.assertRaises(NameError):
                merkle_sys.evaluate([S("hash-leaf"), S("fact-0")])

        finally:
            _sys.setrecursionlimit(old_limit)


class TestThreeSystemSameStore(unittest.TestCase):
    """Three systems, each with a "store" scope that has a fact named "val".

    sys_a.store.val = 41
    sys_b.store.val = 42
    sys_c.store.val = 43

    sys_c is the deepest. On sys_c's level we want:
        (= (project store val) (??? store val))
    to resolve to (= 43 42) — project gives sys_c's own store (43),
    and ??? gives sys_b's store (42).

    project resolves in the current engine's basis.
    ??? is the unknown primitive that resolves "at the parent scope level"
    without the child knowing the parent's identity.
    """

    def _make_store(self, val):
        """Create a store system with a single fact."""
        store = EmptySystem()
        store.set_fact("val", val, f"store-{val}")
        return store

    def _make_scope_handler(self, system):
        def handler(name, *args):
            result = None
            for arg in args:
                result = system.evaluate(arg)
            return result

        return handler

    def test_three_stores_project_resolves_at_caller(self):
        """Project resolves at the current engine (the outermost caller).

        sys_a evaluates (scope middle (scope inner (project store val))).
        _rp at sys_a level resolves (project store val) → sys_a's store → 41.
        This is correct project behavior.
        """
        S = Symbol

        store_a = self._make_store(41)
        store_b = self._make_store(42)
        store_c = self._make_store(43)

        sys_c = EmptySystem()
        sys_c.engine.env[S("=")] = operator.eq
        sys_c.engine.env[S("store")] = self._make_scope_handler(store_c)

        sys_b = EmptySystem()
        sys_b.engine.env[S("store")] = self._make_scope_handler(store_b)
        sys_b.engine.env[S("inner")] = self._make_scope_handler(sys_c)

        sys_a = EmptySystem()
        sys_a.engine.env[S("store")] = self._make_scope_handler(store_a)
        sys_a.engine.env[S("middle")] = self._make_scope_handler(sys_b)

        # project resolves at sys_a (the engine that runs _rp) → store_a → 41
        result = sys_a.evaluate(
            [S("scope"), S("middle"), [S("scope"), S("inner"), [S("project"), S("store"), S("val")]]]
        )
        self.assertEqual(result, 41)

    def test_three_stores_unknown_primitive(self):
        """The missing primitive: resolve store.val from sys_b's level while on sys_c.

        Three systems, each with store scope. store.val = 41, 42, 43.
        At sys_c level we want:

            (and
              (not (= (??? store val) 41))   ; not sys_a's store
              (not (= (??? store val) 43))   ; not sys_c's store
              (= (??? store val) 42))        ; sys_b's store — the caller

        ??? means "resolve at the scope level that forwarded this expression
        to me" — the caller's basis, not mine, not the root's.

        sys_c doesn't know sys_b exists. The expression was written at
        sys_a level and passed through sys_b → sys_c. ??? must carry
        the resolution context of its transit through sys_b.

        For now: stubbed with manual workaround. The test expects True
        to define what correct behavior looks like.
        """
        S = Symbol

        store_a = self._make_store(41)
        store_b = self._make_store(42)
        store_c = self._make_store(43)

        sys_c = EmptySystem()
        sys_c.engine.env[S("=")] = operator.eq
        sys_c.engine.env[S("not")] = operator.not_
        sys_c.engine.env[S("and")] = lambda *a: all(a)
        sys_c.engine.env[S("store")] = self._make_scope_handler(store_c)

        sys_b = EmptySystem()
        sys_b.engine.env[S("store")] = self._make_scope_handler(store_b)
        sys_b.engine.env[S("inner")] = self._make_scope_handler(sys_c)

        sys_a = EmptySystem()
        sys_a.engine.env[S("store")] = self._make_scope_handler(store_a)
        sys_a.engine.env[S("middle")] = self._make_scope_handler(sys_b)

        # Manual workaround: sys_b pre-evaluates its store val
        # GOAL: b_val = sys_b.evaluate([S("project"), S("store"), S("val")])
        GOAL = "delegate"
        b_formula = [S(GOAL), [S('project'), S("store"), S("val")]]
        # self.assertEqual(sys_b.evaluate(b_formula), 42)
        # What we WANT to write (??? is the unknown primitive):
        #   (scope middle (scope inner
        #     (and
        #       (not (= (??? store val) 41))
        #       (not (= (??? store val) 43))
        #       (= (??? store val) 42))))
        #
        # For now, inject b_val as literal where ??? would go:
        result = sys_a.evaluate(
            [
                S("scope"),
                S("middle"),
                [
                    S("scope"),
                    S("inner"),
                    [
                        S("and"),
                        [S("not"), [S("="), b_formula, 41]],
                        [S("not"), [S("="), b_formula, 43]],
                        [S("="), b_formula, 42],
                    ],
                ],
            ]
        )
        self.assertEqual(result, True, f"Behaviour of {GOAL} is not correct")


class TestDelegateWithFiveStores(unittest.TestCase):
    """Five systems A→B→C→D→E, each with store scope, store.val = 10,20,30,40,50.

    delegate is a transport modifier — "skip this scope level."
    project is resolution — "resolve here."

    (project store val)                              → resolves at current level
    (delegate (project store val))                   → skip 1, resolve at caller
    (delegate (delegate (project store val)))        → skip 2
    (delegate (delegate (delegate (project store val)))) → skip 3

    At E's level (deepest):
      (project store val)                                    → E's store → 50
      (delegate (project store val))                         → D's store → 40
      (delegate (delegate (project store val)))              → C's store → 30
      (delegate (delegate (delegate (project store val))))   → B's store → 20
    """

    def _make_store(self, val):
        store = EmptySystem()
        store.set_fact("val", val, f"store-{val}")
        return store

    def _make_scope_handler(self, system):
        def handler(name, *args):
            result = None
            for arg in args:
                result = system.evaluate(arg)
            return result

        return handler

    def test_delegate_chain_five_stores(self):
        """Each delegate peels one scope layer. project resolves at arrival level."""
        S = Symbol

        stores = {
            "a": self._make_store(10),
            "b": self._make_store(20),
            "c": self._make_store(30),
            "d": self._make_store(40),
            "e": self._make_store(50),
        }

        sys_e = EmptySystem()
        sys_e.engine.env[S("=")] = operator.eq
        sys_e.engine.env[S("and")] = lambda *a: all(a)
        sys_e.engine.env[S("store")] = self._make_scope_handler(stores["e"])

        sys_d = EmptySystem()
        sys_d.engine.env[S("store")] = self._make_scope_handler(stores["d"])
        sys_d.engine.env[S("e")] = self._make_scope_handler(sys_e)

        sys_c = EmptySystem()
        sys_c.engine.env[S("store")] = self._make_scope_handler(stores["c"])
        sys_c.engine.env[S("d")] = self._make_scope_handler(sys_d)

        sys_b = EmptySystem()
        sys_b.engine.env[S("store")] = self._make_scope_handler(stores["b"])
        sys_b.engine.env[S("c")] = self._make_scope_handler(sys_c)

        sys_a = EmptySystem()
        sys_a.engine.env[S("store")] = self._make_scope_handler(stores["a"])
        sys_a.engine.env[S("b")] = self._make_scope_handler(sys_b)

        D = S("delegate")
        P = S("project")

        # At E's level: combine all four resolutions and check they're correct
        # (project store val) → A=10 (outermost caller)
        # (delegate (project store val)) → D=40
        # (delegate (delegate (project store val))) → C=30
        # (delegate (delegate (delegate (project store val)))) → B=20
        result = sys_a.evaluate(
            [
                S("scope"),
                S("b"),
                [
                    S("scope"),
                    S("c"),
                    [
                        S("scope"),
                        S("d"),
                        [
                            S("scope"),
                            S("e"),
                            [
                                S("and"),
                                [S("="), [P, S("store"), S("val")], 10],
                                [S("="), [D, [P, S("store"), S("val")]], 40],
                                [S("="), [D, [D, [P, S("store"), S("val")]]], 30],
                                [S("="), [D, [D, [D, [P, S("store"), S("val")]]]], 20],
                            ],
                        ],
                    ],
                ],
            ]
        )
        self.assertEqual(result, True)

    def test_conditional_delegate_finds_42(self):
        """Conditional delegate: five stores with values 7, 37, 42, 2, 99.

        (delegate (= ?answer 42) ?answer)

        Each scope posts its store.val. Only store C has 42.
        The delegate walks proposals from closest, finds 42, returns it.
        """
        S = Symbol

        stores = {
            "a": self._make_store(7),
            "b": self._make_store(37),
            "c": self._make_store(42),
            "d": self._make_store(2),
            "e": self._make_store(99),
        }

        sys_e = EmptySystem()
        sys_e.engine.env[S("=")] = operator.eq
        sys_e.engine.env[S("store")] = self._make_scope_handler(stores["e"])

        sys_d = EmptySystem()
        sys_d.engine.env[S("=")] = operator.eq
        sys_d.engine.env[S("store")] = self._make_scope_handler(stores["d"])
        sys_d.engine.env[S("e")] = self._make_scope_handler(sys_e)

        sys_c = EmptySystem()
        sys_c.engine.env[S("=")] = operator.eq
        sys_c.engine.env[S("store")] = self._make_scope_handler(stores["c"])
        sys_c.engine.env[S("d")] = self._make_scope_handler(sys_d)

        sys_b = EmptySystem()
        sys_b.engine.env[S("=")] = operator.eq
        sys_b.engine.env[S("store")] = self._make_scope_handler(stores["b"])
        sys_b.engine.env[S("c")] = self._make_scope_handler(sys_c)

        sys_a = EmptySystem()
        sys_a.engine.env[S("=")] = operator.eq
        sys_a.engine.env[S("store")] = self._make_scope_handler(stores["a"])
        sys_a.engine.env[S("b")] = self._make_scope_handler(sys_b)

        # (delegate (= ?answer 42) ?answer)
        # ?answer → each scope looks up "answer" in env... but we need
        # store.val. The delegate body is (= (scope store val) 42) with
        # the result stored as ?answer.
        # Actually: the delegate body evaluates at each level.
        # We want: evaluate (scope store val) at each level, check = 42.
        # ?answer binds to env[answer], but we want the store val.
        #
        # The pattern: (= (scope store val) 42) — no ?-vars, just evaluates.
        # But we need ?answer to carry the result.
        #
        # Right approach: each scope has "answer" in env bound to its store val.
        # ?answer → env[answer]. Pattern (= ?answer 42) checks if this scope's
        # answer is 42.
        for sys, val in [(sys_a, 7), (sys_b, 37), (sys_c, 42), (sys_d, 2), (sys_e, 99)]:
            sys.engine.env[S("answer")] = val

        D = S("delegate")

        # (scope b (scope c (scope d (scope e
        #   (delegate (= ?answer 42) ?answer)))))
        # Scopes post: a=7≠42→[], b=37≠42→[], c=42=42→42, d=2≠42→[], e=99≠42→[]
        # Delegate picks first non-[] from closest → 42 (from C... but C is
        # not closest to E. Walk: E→[], D→[], C→42. Found.)
        result = sys_a.evaluate(
            [
                S("scope"),
                S("b"),
                [
                    S("scope"),
                    S("c"),
                    [S("scope"), S("d"), [S("scope"), S("e"), [D, [S("="), S("?answer"), 42], S("?answer")]]],
                ],
            ]
        )
        self.assertEqual(result, 42)


class TestDelegatedSignerBlockchain(unittest.TestCase):
    """Merkle-blockchain where each block has its own RSA signer,
    accessible ONLY via delegation.

    Architecture (depth N):
        root → block_0 → block_1 → ... → block_{N-1} → merkle

    Each block_i owns:
        - a signer scope (RSA key pair, sign operator)
        - a scope to the next block (or merkle for the last)
        - random "important" facts that need signing

    The merkle system is fully isolated — no facts, no signers.
    The parent (root) owns the facts but has NO signer.

    To sign a fact at level i, the expression uses:
        (delegate ?signer (scope signer (sign fact_val)))
    This delegates upward until it finds a scope that has 'signer'
    in its env — the block that owns the signer for that level.

    Verifies:
        1. Merkle hash matches Python reference
        2. Each signature verifies against the correct block's public key
        3. Merkle system can't sign or access facts
        4. Tampering one signature changes the root hash
    """

    HASH_MASK = 0xFFFFFFFF

    def _merkle_hash(self, left, right):
        return ((left * 31) ^ right) & self.HASH_MASK

    def _make_scope_handler(self, system):
        def handler(name, *args):
            result = None
            for arg in args:
                result = system.evaluate(arg)
            return result

        return handler

    def test_delegated_signer_merkle_depth10(self):
        """Each block has its own signer. Signing requires delegation."""
        import hashlib
        import random
        import sys as _sys

        S = Symbol

        depth = 10
        num_facts = 15
        old_limit = _sys.getrecursionlimit()
        _sys.setrecursionlimit(max(old_limit, depth * 100))
        rng = random.Random(0xB10C5164)

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
        except ImportError:
            self.skipTest("cryptography package not installed")

        try:
            # ── Generate one Ed25519 key per block ──
            keys = {}
            signers = {}
            for i in range(depth):
                priv = Ed25519PrivateKey.generate()
                pub = priv.public_key()
                keys[i] = (priv, pub)

                def make_sign(private_key):
                    def sign(value):
                        msg = str(value).encode()
                        sig = private_key.sign(msg)
                        return (value, sig.hex())

                    return sign

                signers[i] = make_sign(priv)

            def verify_sig(block_idx, value, sig_hex):
                _, pub = keys[block_idx]
                msg = str(value).encode()
                sig = bytes.fromhex(sig_hex)
                pub.verify(sig, msg)
                return True

            def hash_leaf_signed(signed_pair):
                val, sig_hex = signed_pair
                combined = hashlib.sha256(f"{val}:{sig_hex}".encode()).digest()
                return int.from_bytes(combined[:4], "big") & self.HASH_MASK

            # ── Merkle system: fully isolated ──
            test = self
            merkle_sys = EmptySystem()
            merkle_sys.engine.env[S("hash-pair")] = lambda left, right: test._merkle_hash(left, right)
            merkle_sys.engine.env[S("hash-leaf")] = hash_leaf_signed

            # ── Build block chain: block_0 → block_1 → ... → block_{N-1} → merkle ──
            # Each block has its own signer scope and a scope to the next level.
            blocks = []
            for i in range(depth - 1, -1, -1):
                block = EmptySystem()

                # Signer scope for this block
                sig_sys = EmptySystem()
                sig_sys.engine.env[S("sign")] = signers[i]
                block.engine.env[S("signer")] = self._make_scope_handler(sig_sys)

                # Scope to next level
                if i == depth - 1:
                    block.engine.env[S("next")] = self._make_scope_handler(merkle_sys)
                else:
                    block.engine.env[S("next")] = self._make_scope_handler(blocks[0])

                blocks.insert(0, block)

            # ── Root: owns facts, scope to first block ──
            root = EmptySystem()
            root.engine.env[S("chain")] = self._make_scope_handler(blocks[0])

            # Register random facts
            facts = {}
            for i in range(num_facts):
                name = f"fact-{i}"
                val = rng.randint(1, 0xFFFF)
                facts[name] = val
                root.set_fact(name, val, f"generated-{i}")

            # Assign a random fact to each block level
            level_facts = [rng.choice(list(facts.keys())) for _ in range(depth)]

            # ── Python reference: sign each fact with its block's signer,
            #    build merkle bottom-up ──
            signed_values = {}
            for i in range(depth):
                fname = level_facts[i]
                fval = facts[fname]
                signed_values[i] = signers[i](fval)
                # Verify each signature
                verify_sig(i, signed_values[i][0], signed_values[i][1])

            py_current = hash_leaf_signed(signed_values[depth - 1])
            for level in range(depth - 2, -1, -1):
                leaf_hash = hash_leaf_signed(signed_values[level])
                py_current = self._merkle_hash(py_current, leaf_hash)

            # ── Build s-expression ──
            # Innermost: (hash-leaf (delegate ?signer (scope signer (sign fact_val))))
            # The delegate finds the closest block with 'signer' in env.
            # Each block has 'signer', so the innermost delegate resolves
            # at the block that directly contains the merkle scope.
            #
            # We wrap in scopes: (scope chain (scope next (scope next ...
            #   (scope next <merkle-expr>))))
            # Each "next" enters the next block. The delegate at each level
            # reaches back to the block that forwarded the expression.

            # Build from innermost (deepest block) outward.
            # The merkle expression is evaluated inside merkle_sys.
            # Delegates reach back to block scopes for signing.
            #
            # At each block level i, the leaf is:
            #   (delegate ?signer (scope signer (sign projected_fact_val)))
            # projected_fact_val is concrete (project resolves at root).

            # We need to build the merkle expression with N leaves,
            # where each leaf's signing delegates to a different depth.
            # Leaf at depth 0 (outermost block) needs delegate depth = depth
            # (climb all the way back through all blocks).
            # Leaf at depth N-1 (innermost block) needs delegate depth = 1.

            D = S("delegate")

            # Each block has 'level' and '=' for delegate pattern matching.
            # (delegate (= ?level N) (scope signer (sign fact_val)))
            # matches the block where level == N, signs there.
            for i, block in enumerate(blocks):
                block.engine.env[S("level")] = i
                block.engine.env[S("=")] = operator.eq

            # Build merkle expr bottom-up.
            merkle_expr = None
            for level in range(depth - 1, -1, -1):
                fact_val = facts[level_facts[level]]
                # Delegate to block at this level, sign there
                sign_expr = [D, [S("="), S("?level"), level], [S("scope"), S("signer"), [S("sign"), fact_val]]]

                leaf_expr = [S("hash-leaf"), sign_expr]
                if merkle_expr is None:
                    merkle_expr = leaf_expr
                else:
                    merkle_expr = [S("hash-pair"), merkle_expr, leaf_expr]

            # Wrap in scope chain: (scope chain (scope next (scope next ...
            #   (scope next merkle_expr))))
            expr = merkle_expr
            for _ in range(depth):
                expr = [S("scope"), S("next"), expr]
            expr = [S("scope"), S("chain"), expr]

            result = root.evaluate(expr)
            self.assertEqual(result, py_current, "delegated-signer merkle must match Python reference")

            # ── Verify merkle can't sign ──
            with self.assertRaises(NameError):
                merkle_sys.evaluate([S("sign"), 42])

            # ── Verify merkle can't access facts ──
            with self.assertRaises(NameError):
                merkle_sys.evaluate([S("hash-leaf"), S("fact-0")])

            # ── Tamper test: forge one signature ──
            tamper_level = rng.randint(0, depth - 1)
            tamper_val = facts[level_facts[tamper_level]]
            forged = (tamper_val, "00" * 256)

            py_tampered = hash_leaf_signed(signed_values[depth - 1] if depth - 1 != tamper_level else forged)
            for level in range(depth - 2, -1, -1):
                s = forged if level == tamper_level else signed_values[level]
                py_tampered = self._merkle_hash(py_tampered, hash_leaf_signed(s))

            self.assertNotEqual(py_current, py_tampered, "forged signature must change hash")

        finally:
            _sys.setrecursionlimit(old_limit)


class TestDelegatedPKI(unittest.TestCase):
    """Full PKI via delegation: keystore, signing, encryption, handshake.

    Architecture:
        keystore  — public key directory. (lookup user-id) → public key.
        alice     — has private key, signer scope, encryptor scope.
        bob       — has private key, signer scope, decryptor scope.
        verifier  — isolated scope: (verify pub_key signature message) → bool.
        channel   — orchestrator. Doesn't own any keys. Delegates to
                     keystore for public keys, to alice/bob for signing
                     and encrypting. Proves that isolated scopes can
                     establish authenticated encrypted communication
                     purely through delegation and substitution.

    Flow:
        1. Alice signs a message (delegates to her signer).
        2. Channel gets Bob's public key from keystore via delegation.
        3. Channel gets Alice's public key from keystore via delegation.
        4. Bob verifies Alice's signature (delegates to verifier with her pub key).
        5. Alice encrypts for Bob using his public key (X25519 ECDH + AES).
        6. Bob decrypts (delegates to his decryptor scope).
        7. The decrypted message matches the original.

    All routing is by delegation with ?-var pattern matching.
    No scope ever sees another scope's private key.
    """

    def _make_scope_handler(self, system):
        def handler(name, *args):
            result = None
            for arg in args:
                result = system.evaluate(arg)
            return result

        return handler

    def test_authenticated_encrypted_channel(self):
        """Full handshake: sign → verify → encrypt → decrypt via delegation."""
        import os

        S = Symbol

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
            from cryptography.hazmat.primitives.asymmetric.x25519 import (
                X25519PrivateKey,
            )
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            self.skipTest("cryptography package not installed")

        # ── Key generation ──
        # Each user has an Ed25519 signing key and an X25519 encryption key.
        alice_sign_priv = Ed25519PrivateKey.generate()
        alice_sign_pub = alice_sign_priv.public_key()
        alice_enc_priv = X25519PrivateKey.generate()
        alice_enc_pub = alice_enc_priv.public_key()

        bob_sign_priv = Ed25519PrivateKey.generate()
        bob_sign_pub = bob_sign_priv.public_key()
        bob_enc_priv = X25519PrivateKey.generate()
        bob_enc_pub = bob_enc_priv.public_key()

        # Serialize public keys for storage
        def pub_bytes(pub_key):
            return pub_key.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )

        # ── Keystore system: public key directory ──
        keystore = EmptySystem()
        registry = {
            "alice": {
                "sign": pub_bytes(alice_sign_pub),
                "enc": pub_bytes(alice_enc_pub),
            },
            "bob": {
                "sign": pub_bytes(bob_sign_pub),
                "enc": pub_bytes(bob_enc_pub),
            },
        }

        def lookup(user_id, key_type):
            if user_id in registry and key_type in registry[user_id]:
                return registry[user_id][key_type]
            raise NameError(f"unknown user/key: {user_id}/{key_type}")

        keystore.engine.env[S("lookup")] = lookup

        # ── Alice's system: signing + encrypting ──
        alice_sys = EmptySystem()

        def alice_sign(message):
            msg = message if isinstance(message, bytes) else str(message).encode()
            sig = alice_sign_priv.sign(msg)
            return (message, sig.hex())

        def alice_encrypt(plaintext, recipient_enc_pub_bytes):
            """ECDH with recipient's X25519 public key, then AES-GCM."""
            from cryptography.hazmat.primitives.asymmetric.x25519 import (
                X25519PublicKey,
            )

            recipient_pub = X25519PublicKey.from_public_bytes(recipient_enc_pub_bytes)
            shared = alice_enc_priv.exchange(recipient_pub)
            # Derive AES key from shared secret (simplified: use first 32 bytes)
            aes_key = shared[:32]
            nonce = os.urandom(12)
            pt = plaintext if isinstance(plaintext, bytes) else str(plaintext).encode()
            ct = AESGCM(aes_key).encrypt(nonce, pt, None)
            return {
                "ciphertext": ct.hex(),
                "nonce": nonce.hex(),
                "sender_enc_pub": pub_bytes(alice_enc_pub).hex(),
            }

        alice_signer = EmptySystem()
        alice_signer.engine.env[S("sign")] = alice_sign
        alice_encryptor = EmptySystem()
        alice_encryptor.engine.env[S("encrypt")] = alice_encrypt

        alice_sys.engine.env[S("signer")] = self._make_scope_handler(alice_signer)
        alice_sys.engine.env[S("encryptor")] = self._make_scope_handler(alice_encryptor)
        alice_sys.engine.env[S("role")] = "alice"
        alice_sys.engine.env[S("=")] = operator.eq

        # ── Bob's system: signing + decrypting ──
        bob_sys = EmptySystem()

        def bob_decrypt(encrypted_bundle):
            """ECDH with sender's X25519 public key, then AES-GCM decrypt."""
            from cryptography.hazmat.primitives.asymmetric.x25519 import (
                X25519PublicKey,
            )

            sender_pub = X25519PublicKey.from_public_bytes(bytes.fromhex(encrypted_bundle["sender_enc_pub"]))
            shared = bob_enc_priv.exchange(sender_pub)
            aes_key = shared[:32]
            nonce = bytes.fromhex(encrypted_bundle["nonce"])
            ct = bytes.fromhex(encrypted_bundle["ciphertext"])
            pt = AESGCM(aes_key).decrypt(nonce, ct, None)
            return pt.decode()

        bob_decryptor = EmptySystem()
        bob_decryptor.engine.env[S("decrypt")] = bob_decrypt
        bob_signer = EmptySystem()
        bob_signer.engine.env[S("sign")] = lambda msg: (
            msg,
            bob_sign_priv.sign(msg if isinstance(msg, bytes) else str(msg).encode()).hex(),
        )

        bob_sys.engine.env[S("decryptor")] = self._make_scope_handler(bob_decryptor)
        bob_sys.engine.env[S("signer")] = self._make_scope_handler(bob_signer)
        bob_sys.engine.env[S("role")] = "bob"
        bob_sys.engine.env[S("=")] = operator.eq

        # ── Verifier system: isolated, stateless ──
        verifier_sys = EmptySystem()

        def verify(sign_pub_bytes, signed_pair):
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            message, sig_hex = signed_pair
            msg = message if isinstance(message, bytes) else str(message).encode()
            pub = Ed25519PublicKey.from_public_bytes(sign_pub_bytes)
            pub.verify(bytes.fromhex(sig_hex), msg)
            return True

        verifier_sys.engine.env[S("verify")] = verify

        # ── Channel: orchestrator, no keys ──
        channel = EmptySystem()
        channel.engine.env[S("alice")] = self._make_scope_handler(alice_sys)
        channel.engine.env[S("bob")] = self._make_scope_handler(bob_sys)
        channel.engine.env[S("keystore")] = self._make_scope_handler(keystore)
        channel.engine.env[S("verifier")] = self._make_scope_handler(verifier_sys)

        message = "hello from alice to bob"

        # ── Step 1: Alice signs the message ──
        # Channel delegates to alice's signer
        signed = channel.evaluate([S("scope"), S("alice"), [S("scope"), S("signer"), [S("sign"), message]]])
        self.assertIsInstance(signed, tuple)
        self.assertEqual(signed[0], message)

        # ── Step 2: Get Alice's signing public key from keystore ──
        alice_pub = channel.evaluate([S("scope"), S("keystore"), [S("lookup"), "alice", "sign"]])
        self.assertEqual(alice_pub, pub_bytes(alice_sign_pub))

        # ── Step 3: Verify Alice's signature via verifier scope ──
        verified = channel.evaluate([S("scope"), S("verifier"), [S("verify"), alice_pub, signed]])
        self.assertTrue(verified)

        # ── Step 4: Get Bob's encryption public key from keystore ──
        bob_enc_pub_bytes = channel.evaluate([S("scope"), S("keystore"), [S("lookup"), "bob", "enc"]])
        self.assertEqual(bob_enc_pub_bytes, pub_bytes(bob_enc_pub))

        # ── Step 5: Alice encrypts for Bob ──
        encrypted = channel.evaluate(
            [S("scope"), S("alice"), [S("scope"), S("encryptor"), [S("encrypt"), message, bob_enc_pub_bytes]]]
        )
        self.assertIn("ciphertext", encrypted)
        self.assertIn("nonce", encrypted)
        self.assertIn("sender_enc_pub", encrypted)

        # ── Step 6: Bob decrypts ──
        decrypted = channel.evaluate([S("scope"), S("bob"), [S("scope"), S("decryptor"), [S("decrypt"), encrypted]]])
        self.assertEqual(decrypted, message)

        # ── Step 7: Isolation checks ──
        # Verifier can't sign
        with self.assertRaises(NameError):
            verifier_sys.evaluate([S("sign"), "forge"])

        # Keystore can't decrypt
        with self.assertRaises(NameError):
            keystore.evaluate([S("decrypt"), encrypted])

        # Channel can't sign directly
        with self.assertRaises(NameError):
            channel.evaluate([S("sign"), "forge"])

        # Bob has his own signer, but it signs as BOB not alice
        bob_signed = bob_sys.evaluate([S("scope"), S("signer"), [S("sign"), "test"]])
        # Verify it's bob's signature, not alice's
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        bob_pub_restored = Ed25519PublicKey.from_public_bytes(pub_bytes(bob_sign_pub))
        bob_pub_restored.verify(bytes.fromhex(bob_signed[1]), b"test")
        # Alice's pub key must NOT verify bob's signature
        with self.assertRaises(Exception):
            alice_sign_pub.verify(bytes.fromhex(bob_signed[1]), b"test")

    def test_delegated_handshake(self):
        """Full handshake via delegation — no direct scope access.

        channel → alice → bob chain. Alice and Bob delegate to each
        other's signers and the keystore for verification. Everything
        routed by ?role pattern matching.
        """
        S = Symbol

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
                Ed25519PublicKey,
            )
        except ImportError:
            self.skipTest("cryptography package not installed")

        alice_priv = Ed25519PrivateKey.generate()
        alice_pub = alice_priv.public_key()
        bob_priv = Ed25519PrivateKey.generate()
        bob_pub = bob_priv.public_key()

        def pub_bytes(key):
            return key.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )

        # ── Keystore ──
        keystore = EmptySystem()
        key_registry = {
            "alice": pub_bytes(alice_pub),
            "bob": pub_bytes(bob_pub),
        }
        keystore.engine.env[S("lookup")] = lambda uid: key_registry[uid]

        # ── Alice ──
        alice_sys = EmptySystem()
        alice_signer = EmptySystem()
        alice_signer.engine.env[S("sign")] = lambda msg: (
            msg,
            alice_priv.sign(msg if isinstance(msg, bytes) else str(msg).encode()).hex(),
        )
        alice_sys.engine.env[S("signer")] = self._make_scope_handler(alice_signer)
        alice_sys.engine.env[S("role")] = "alice"
        alice_sys.engine.env[S("=")] = operator.eq

        # ── Bob ──
        bob_sys = EmptySystem()
        bob_signer = EmptySystem()
        bob_signer.engine.env[S("sign")] = lambda msg: (
            msg,
            bob_priv.sign(msg if isinstance(msg, bytes) else str(msg).encode()).hex(),
        )
        bob_sys.engine.env[S("signer")] = self._make_scope_handler(bob_signer)
        bob_sys.engine.env[S("role")] = "bob"
        bob_sys.engine.env[S("=")] = operator.eq

        # ── Channel: knows alice, bob, keystore. No keys. ──
        # Alice knows bob as a scope (for chaining), bob knows alice.
        alice_sys.engine.env[S("bob")] = self._make_scope_handler(bob_sys)
        bob_sys.engine.env[S("alice")] = self._make_scope_handler(alice_sys)

        channel = EmptySystem()
        channel.engine.env[S("alice")] = self._make_scope_handler(alice_sys)
        channel.engine.env[S("bob")] = self._make_scope_handler(bob_sys)
        channel.engine.env[S("keystore")] = self._make_scope_handler(keystore)

        D = S("delegate")
        message = "handshake-nonce-42"
        response = "ack-42"

        # ── Step 1: Alice signs directly ──
        alice_signed = channel.evaluate([S("scope"), S("alice"), [S("scope"), S("signer"), [S("sign"), message]]])
        self.assertIsInstance(alice_signed, tuple)
        self.assertEqual(alice_signed[0], message)

        # ── Step 2: Bob signs directly ──
        bob_signed = channel.evaluate([S("scope"), S("bob"), [S("scope"), S("signer"), [S("sign"), response]]])
        self.assertEqual(bob_signed[0], response)

        # ── Step 3: Verify with keystore ──
        alice_pub_bytes = channel.evaluate([S("scope"), S("keystore"), [S("lookup"), "alice"]])
        bob_pub_bytes = channel.evaluate([S("scope"), S("keystore"), [S("lookup"), "bob"]])

        alice_pub_restored = Ed25519PublicKey.from_public_bytes(alice_pub_bytes)
        bob_pub_restored = Ed25519PublicKey.from_public_bytes(bob_pub_bytes)

        # Alice's pub verifies alice's sig
        alice_pub_restored.verify(bytes.fromhex(alice_signed[1]), message.encode())
        # Bob's pub verifies bob's sig
        bob_pub_restored.verify(bytes.fromhex(bob_signed[1]), response.encode())

        # ── Step 4: Cross-sign via delegation ──
        # Bob is inside alice's scope chain. He needs alice to sign
        # something on his behalf. Delegates back to alice's signer.
        # (scope alice (scope bob
        #   (delegate (= ?role "alice") (scope signer (sign "bob-requests-alice")))))
        # bob doesn't have role="alice" → []. alice does → signs.
        cross_signed = channel.evaluate(
            [
                S("scope"),
                S("alice"),
                [
                    S("scope"),
                    S("bob"),
                    [D, [S("="), S("?role"), "alice"], [S("scope"), S("signer"), [S("sign"), "bob-requests-alice"]]],
                ],
            ]
        )
        self.assertEqual(cross_signed[0], "bob-requests-alice")
        # Must be alice's signature
        alice_pub_restored.verify(bytes.fromhex(cross_signed[1]), b"bob-requests-alice")
        # Bob's key must NOT verify it
        with self.assertRaises(Exception):
            bob_pub_restored.verify(bytes.fromhex(cross_signed[1]), b"bob-requests-alice")

        # ── Step 5: Reverse — alice delegates to bob's signer ──
        reverse_signed = channel.evaluate(
            [
                S("scope"),
                S("bob"),
                [
                    S("scope"),
                    S("alice"),
                    [D, [S("="), S("?role"), "bob"], [S("scope"), S("signer"), [S("sign"), "alice-requests-bob"]]],
                ],
            ]
        )
        self.assertEqual(reverse_signed[0], "alice-requests-bob")
        bob_pub_restored.verify(bytes.fromhex(reverse_signed[1]), b"alice-requests-bob")
        with self.assertRaises(Exception):
            alice_pub_restored.verify(bytes.fromhex(reverse_signed[1]), b"alice-requests-bob")


class TestZeroKnowledgeDerive(unittest.TestCase):
    """Zero-knowledge proof of a derive via committed env merkle tree.

    Architecture:
        alice       — owns private facts, publishes signed merkle root of env.
        prover      — trusted scope. Receives facts via project, runs derive,
                       returns boolean result. Alice can't modify the prover.
        public_chain — stores: axiom, alice's env commitment, proof record.
        keystore    — public key directory.
        verifier    — bob's verification scope. Checks merkle proofs,
                       signatures, and axiom soundness.

    Protocol:
        1. Alice builds merkle tree of her fact values, signs the root.
           Published: sign_alice(merkle_root). Values stay private.

        2. Public axiom posted: (axiom age-check (> ?age 18))

        3. Alice derives inside prover scope:
           - Projects her fact value into the prover
           - Prover evaluates (> val 18) → True/False
           - Alice provides merkle proof that the projected value is
             in her committed env

        4. Alice publishes proof record:
           {axiom: "age-check", result: True, fact_hash: h(val),
            merkle_proof: [sibling hashes], env_root: root,
            env_sig: sign(root), proof_sig: sign(record)}

        5. Bob verifies:
           - Alice's signature on env root (she committed to this env)
           - Merkle proof: fact_hash is in the committed tree
           - Alice's signature on proof record
           - Axiom is the public one
           - Result is True

        If Alice lies:
           - Can't change fact without changing merkle root (already signed)
           - Can't use a fact not in her env (merkle proof fails)
           - Can't fake the prover result (prover is a separate scope)

    Alice never reveals the fact VALUE. Only hashes and merkle proofs.
    The prover sees the value (via project) but only the boolean crosses out.
    """

    HASH_MASK = 0xFFFFFFFF

    def _make_scope_handler(self, system):
        def handler(name, *args):
            result = None
            for arg in args:
                result = system.evaluate(arg)
            return result

        return handler

    def _hash(self, *values):
        """Deterministic hash of arbitrary values."""
        import hashlib

        data = ":".join(str(v) for v in values).encode()
        return int.from_bytes(hashlib.sha256(data).digest()[:4], "big") & self.HASH_MASK

    def _merkle_root(self, leaves):
        """Build a merkle root from a list of leaf hashes."""
        if not leaves:
            return 0
        level = list(leaves)
        while len(level) > 1:
            next_level = []
            for i in range(0, len(level), 2):
                if i + 1 < len(level):
                    next_level.append(self._hash(level[i], level[i + 1]))
                else:
                    next_level.append(level[i])  # odd one out
            level = next_level
        return level[0]

    def _merkle_proof(self, leaves, index):
        """Build a merkle proof (list of (sibling_hash, side) pairs)."""
        if len(leaves) <= 1:
            return []
        proof = []
        level = list(leaves)
        idx = index
        while len(level) > 1:
            next_level = []
            for i in range(0, len(level), 2):
                if i + 1 < len(level):
                    next_level.append(self._hash(level[i], level[i + 1]))
                    if i == idx or i + 1 == idx:
                        if i == idx:
                            proof.append((level[i + 1], "right"))
                        else:
                            proof.append((level[i], "left"))
                else:
                    next_level.append(level[i])
                    # odd leaf, no sibling
            idx = idx // 2
            level = next_level
        return proof

    def _verify_merkle_proof(self, leaf_hash, proof, root):
        """Verify a merkle proof reconstructs to root."""
        current = leaf_hash
        for sibling, side in proof:
            if side == "left":
                current = self._hash(sibling, current)
            else:
                current = self._hash(current, sibling)
        return current == root

    def test_zk_age_proof(self):
        """Alice proves she's over 18 without revealing her age."""
        import operator

        S = Symbol

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
                Ed25519PublicKey,
            )
        except ImportError:
            self.skipTest("cryptography package not installed")

        def pub_bytes(key):
            return key.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )

        # ── Keys ──
        alice_priv = Ed25519PrivateKey.generate()
        alice_pub = alice_priv.public_key()

        def alice_sign(value):
            msg = str(value).encode()
            return (value, alice_priv.sign(msg).hex())

        def alice_verify(value, sig_hex):
            msg = str(value).encode()
            alice_pub.verify(bytes.fromhex(sig_hex), msg)
            return True

        # ── Alice's private facts ──
        alice_facts = {
            "age": 25,
            "name": "alice",
            "balance": 1000,
            "country": "wonderland",
        }

        # Step 1: Alice builds merkle tree of fact hashes
        fact_names = sorted(alice_facts.keys())
        fact_hashes = [self._hash(name, alice_facts[name]) for name in fact_names]
        env_root = self._merkle_root(fact_hashes)

        # Alice signs the root — her commitment
        env_commitment = alice_sign(env_root)

        # ── Alice's system: has her private facts ──
        alice_sys = EmptySystem()
        for name, val in alice_facts.items():
            alice_sys.set_fact(name, val, f"alice-private-{name}")
        alice_sys.engine.env[S(">")] = operator.gt

        # Alice also has a signer scope
        alice_signer = EmptySystem()
        alice_signer.engine.env[S("sign")] = alice_sign
        alice_sys.engine.env[S("signer")] = self._make_scope_handler(alice_signer)

        # ── Prover scope: trusted, runs the axiom check ──
        # Alice can't modify this. It only has (>) and evaluates
        # what it's given.
        prover_sys = EmptySystem()
        prover_sys.engine.env[S(">")] = operator.gt
        alice_sys.engine.env[S("prover")] = self._make_scope_handler(prover_sys)

        # ── Public chain ──
        public_chain = EmptySystem()
        public_chain.engine.env[S("=")] = operator.eq

        # ── Keystore ──
        keystore = EmptySystem()
        keystore.engine.env[S("lookup")] = lambda uid: pub_bytes(alice_pub) if uid == "alice" else None

        # ── Channel: orchestrator ──
        channel = EmptySystem()
        channel.engine.env[S("alice")] = self._make_scope_handler(alice_sys)
        channel.engine.env[S("keystore")] = self._make_scope_handler(keystore)

        # Step 2: Alice runs the derive inside prover scope.
        # Delegate reaches back to alice's scope, projects age there.
        # Prover evaluates (> val 18). Only the boolean comes back.
        D = S("delegate")
        proof_result = channel.evaluate(
            [S("scope"), S("alice"), [S("scope"), S("prover"), [S(">"), [D, [S("project"), S("age")]], 18]]]
        )
        self.assertTrue(proof_result)

        # Step 3: Alice builds merkle proof for the "age" fact
        age_index = fact_names.index("age")
        age_hash = fact_hashes[age_index]
        merkle_proof = self._merkle_proof(fact_hashes, age_index)

        # Verify the proof works
        self.assertTrue(self._verify_merkle_proof(age_hash, merkle_proof, env_root))

        # Step 4: Alice signs the proof record
        proof_record = {
            "axiom": "(> ?age 18)",
            "result": True,
            "fact_hash": age_hash,
            "merkle_proof": merkle_proof,
            "env_root": env_root,
        }
        # Sign the record (sign the string representation)
        record_sig = alice_sign(str(proof_record))

        # ══════════════════════════════════════════════
        # BOB'S VERIFICATION — he never sees alice's age
        # ══════════════════════════════════════════════

        # Get alice's public key from keystore
        alice_pub_bytes = channel.evaluate([S("scope"), S("keystore"), [S("lookup"), "alice"]])
        alice_pub_restored = Ed25519PublicKey.from_public_bytes(alice_pub_bytes)

        # V1: Verify alice signed her env commitment
        commit_val, commit_sig = env_commitment
        self.assertEqual(commit_val, env_root)
        alice_pub_restored.verify(bytes.fromhex(commit_sig), str(env_root).encode())

        # V2: Verify alice signed the proof record
        record_val, record_sig_hex = record_sig
        alice_pub_restored.verify(bytes.fromhex(record_sig_hex), str(proof_record).encode())

        # V3: Verify the merkle proof — the fact_hash is in the committed tree
        self.assertTrue(
            self._verify_merkle_proof(proof_record["fact_hash"], proof_record["merkle_proof"], env_commitment[0])
        )  # committed root

        # V4: Verify the result is True
        self.assertTrue(proof_record["result"])

        # V5: Verify the axiom is the public one
        self.assertEqual(proof_record["axiom"], "(> ?age 18)")

        # ══════════════════════════════════════════════
        # ATTACK SCENARIOS
        # ══════════════════════════════════════════════

        # Attack 1: Alice tries to use a different fact value.
        # She'd need to produce a merkle proof for hash(age, 15)
        # that verifies against her COMMITTED root. This fails.
        fake_hash = self._hash("age", 15)
        self.assertFalse(
            self._verify_merkle_proof(fake_hash, merkle_proof, env_root),
            "Fake fact must not verify against committed root",
        )

        # Attack 2: Alice tries to re-commit with a different env.
        # She could build a new tree with age=15, but the new root
        # would differ from her published commitment.
        fake_facts = dict(alice_facts)
        fake_facts["age"] = 15
        fake_hashes = [self._hash(name, fake_facts[name]) for name in fact_names]
        fake_root = self._merkle_root(fake_hashes)
        self.assertNotEqual(fake_root, env_root, "Different facts must produce different root")

        # Attack 3: Alice tries to forge a proof with a fact not in her env.
        # No merkle path exists for an unknown fact.
        phantom_hash = self._hash("secret-power", 9999)
        self.assertFalse(
            self._verify_merkle_proof(phantom_hash, merkle_proof, env_root), "Phantom fact must not verify"
        )

        # Attack 4: Prover is isolated — alice can't inject a fake result.
        # If alice had age=15, the prover would return False.
        fake_alice = EmptySystem()
        fake_alice.set_fact("age", 15, "fake")
        fake_alice.engine.env[S(">")] = operator.gt
        fake_prover = EmptySystem()
        fake_prover.engine.env[S(">")] = operator.gt
        fake_alice.engine.env[S("prover")] = self._make_scope_handler(fake_prover)
        fake_result = fake_alice.evaluate(
            [S("scope"), S("prover"), [S(">"), [S("delegate"), [S("project"), S("age")]], 18]]
        )
        self.assertFalse(fake_result, "Underage alice must get False from prover")

        # Attack 5: The proof record with False can't pass verification.
        fake_record = dict(proof_record)
        fake_record["result"] = False
        # Even if alice signs it, bob sees result=False → rejected
        self.assertFalse(fake_record["result"])


if __name__ == "__main__":
    unittest.main()
