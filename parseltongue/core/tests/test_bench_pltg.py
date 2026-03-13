"""Tests for bench.pltg — sr/ln/dx/hn forms, accessor axioms, and dependent axioms.

Loads bench.pltg via FrozenBench, constructs tagged forms, applies rewrite
axioms, and verifies that user-defined axioms can compose with bench forms.
"""

import unittest
from pathlib import Path

from ..inspect.systems.frozen_bench import FrozenBench

# bench.pltg sits at inspect/ root
BENCH_PLTG = str(Path(__file__).resolve().parent.parent / "inspect" / "bench.pltg")
INSPECT_DIR = str(Path(__file__).resolve().parent.parent / "inspect")
STD_DIR = str(Path(__file__).resolve().parent.parent)


def _frozen():
    """Load bench.pltg into a FrozenBench system."""
    return FrozenBench(BENCH_PLTG, lib_paths=[INSPECT_DIR, STD_DIR])


def _eval(frozen, expr_str):
    """Evaluate a pltg expression string in the frozen system."""
    from parseltongue.core.atoms import read_tokens, tokenize

    tokens = tokenize(expr_str)
    expr = read_tokens(tokens)
    return frozen.system.engine.evaluate(expr)


def _exec(frozen, expr_str):
    """Execute a directive (defterm, axiom, etc.) in the frozen system."""
    from parseltongue.core.atoms import parse_all
    from parseltongue.core.engine import _execute_directive

    for expr in parse_all(expr_str):
        if isinstance(expr, list) and expr:
            _execute_directive(frozen.system.engine, expr)


class TestBenchPltgLoads(unittest.TestCase):
    """bench.pltg loads and defines all expected terms."""

    def setUp(self):
        self.frozen = _frozen()
        self.engine = self.frozen.system.engine

    def test_sr_alias_defined(self):
        self.assertIn("sr", self.engine.terms)

    def test_ln_alias_defined(self):
        self.assertIn("ln", self.engine.terms)

    def test_dx_alias_defined(self):
        self.assertIn("dx", self.engine.terms)

    def test_hn_alias_defined(self):
        self.assertIn("hn", self.engine.terms)

    def test_sr_accessors_defined(self):
        for acc in ["sr-doc", "sr-line", "sr-column", "sr-context", "sr-callers"]:
            self.assertIn(acc, self.engine.terms, f"{acc} not found in terms")

    def test_ln_accessors_defined(self):
        for acc in ["ln-name", "ln-kind", "ln-value", "ln-depth", "ln-inputs"]:
            self.assertIn(acc, self.engine.terms, f"{acc} not found in terms")

    def test_dx_accessors_defined(self):
        for acc in ["dx-name", "dx-category", "dx-kind", "dx-type", "dx-detail"]:
            self.assertIn(acc, self.engine.terms, f"{acc} not found in terms")

    def test_hn_accessors_defined(self):
        for acc in ["hn-name", "hn-kind", "hn-value", "hn-lenses"]:
            self.assertIn(acc, self.engine.terms, f"{acc} not found in terms")

    def test_sr_axioms_defined(self):
        for ax in [
            "bench_pg.search.sr-doc-rule",
            "bench_pg.search.sr-line-rule",
            "bench_pg.search.sr-column-rule",
            "bench_pg.search.sr-context-rule",
            "bench_pg.search.sr-callers-rule",
        ]:
            self.assertIn(ax, self.engine.axioms, f"{ax} not found in axioms")

    def test_ln_axioms_defined(self):
        for ax in [
            "bench_pg.lens.ln-name-rule",
            "bench_pg.lens.ln-kind-rule",
            "bench_pg.lens.ln-value-rule",
            "bench_pg.lens.ln-depth-rule",
            "bench_pg.lens.ln-inputs-rule",
        ]:
            self.assertIn(ax, self.engine.axioms, f"{ax} not found in axioms")

    def test_namespaced_terms_from_imports(self):
        """The full bench_pg.*.* terms exist from imports."""
        self.assertIn("bench_pg.search.sr", self.engine.terms)
        self.assertIn("bench_pg.lens.ln", self.engine.terms)
        self.assertIn("bench_pg.evaluation.dx", self.engine.terms)
        self.assertIn("bench_pg.hologram.hn", self.engine.terms)


class TestSrAccessors(unittest.TestCase):
    """sr rewrite axioms extract fields from (sr doc line col ctx callers)."""

    def setUp(self):
        self.frozen = _frozen()

    def test_sr_doc(self):
        result = _eval(
            self.frozen, '(sr-doc (bench_pg.search.sr "engine.py" 42 1 "def derive(self):" (("engine.derive" 0.9))))'
        )
        self.assertEqual(result, "engine.py")

    def test_sr_line(self):
        result = _eval(
            self.frozen, '(sr-line (bench_pg.search.sr "engine.py" 42 1 "def derive(self):" (("engine.derive" 0.9))))'
        )
        self.assertEqual(result, 42)

    def test_sr_column(self):
        result = _eval(
            self.frozen, '(sr-column (bench_pg.search.sr "engine.py" 42 3 "def derive(self):" (("engine.derive" 0.9))))'
        )
        self.assertEqual(result, 3)

    def test_sr_context(self):
        result = _eval(
            self.frozen,
            '(sr-context (bench_pg.search.sr "engine.py" 42 1 "def derive(self):" (("engine.derive" 0.9))))',
        )
        self.assertEqual(result, "def derive(self):")

    def test_sr_callers(self):
        result = _eval(
            self.frozen,
            '(sr-callers (bench_pg.search.sr "engine.py" 42 1 "def derive(self):" (("engine.derive" 0.9))))',
        )
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    def test_sr_empty_callers(self):
        result = _eval(self.frozen, '(sr-doc (bench_pg.search.sr "test.py" 1 1 "import foo" ()))')
        self.assertEqual(result, "test.py")


class TestLnAccessors(unittest.TestCase):
    """ln rewrite axioms extract fields from (ln name kind value depth inputs)."""

    def setUp(self):
        self.frozen = _frozen()

    def test_ln_name(self):
        result = _eval(self.frozen, '(ln-name (strict (ln "engine.derive" "theorem" "true" 3 ("revenue" "margin"))))')
        self.assertEqual(result, "engine.derive")

    def test_ln_kind(self):
        result = _eval(self.frozen, '(ln-kind (strict (ln "engine.derive" "theorem" "true" 3 ("revenue" "margin"))))')
        self.assertEqual(result, "theorem")

    def test_ln_value(self):
        result = _eval(self.frozen, '(ln-value (strict (ln "engine.derive" "theorem" "true" 3 ("revenue" "margin"))))')
        self.assertEqual(result, "true")

    def test_ln_depth(self):
        result = _eval(self.frozen, '(ln-depth (strict (ln "engine.derive" "theorem" "true" 3 ("revenue" "margin"))))')
        self.assertEqual(result, 3)

    def test_ln_inputs(self):
        result = _eval(self.frozen, '(ln-inputs (strict (ln "engine.derive" "theorem" "true" 3 ("revenue" "margin"))))')
        self.assertIsInstance(result, list)
        self.assertEqual(result, ["revenue", "margin"])


class TestDxAccessors(unittest.TestCase):
    """dx rewrite axioms extract fields from (dx name category kind type detail)."""

    def setUp(self):
        self.frozen = _frozen()

    def test_dx_name(self):
        result = _eval(
            self.frozen, '(dx-name (strict (dx "engine.derive-count" "issue" "diff" "diverge" "expected 5, got 3")))'
        )
        self.assertEqual(result, "engine.derive-count")

    def test_dx_category(self):
        result = _eval(
            self.frozen,
            '(dx-category (strict (dx "engine.derive-count" "issue" "diff" "diverge" "expected 5, got 3")))',
        )
        self.assertEqual(result, "issue")

    def test_dx_kind(self):
        result = _eval(
            self.frozen, '(dx-kind (strict (dx "engine.derive-count" "issue" "diff" "diverge" "expected 5, got 3")))'
        )
        self.assertEqual(result, "diff")

    def test_dx_type(self):
        result = _eval(
            self.frozen, '(dx-type (strict (dx "engine.derive-count" "issue" "diff" "diverge" "expected 5, got 3")))'
        )
        self.assertEqual(result, "diverge")

    def test_dx_detail(self):
        result = _eval(
            self.frozen, '(dx-detail (strict (dx "engine.derive-count" "issue" "diff" "diverge" "expected 5, got 3")))'
        )
        self.assertEqual(result, "expected 5, got 3")


class TestDependentAxioms(unittest.TestCase):
    """User-defined axioms that compose with bench forms."""

    def setUp(self):
        self.frozen = _frozen()

    def test_extract_doc_from_sr_via_custom_axiom(self):
        """Define an axiom that extracts and transforms sr results."""
        _exec(
            self.frozen,
            """
(defterm is-engine-file :origin "check if sr is from engine")
(axiom is-engine-file-rule
    (= (is-engine-file (bench_pg.search.sr "engine.py" ?line ?col ?ctx ?callers)) true)
    :origin "match engine.py results")
""",
        )
        result = _eval(self.frozen, '(is-engine-file (bench_pg.search.sr "engine.py" 42 1 "raise ValueError" ()))')
        self.assertEqual(result, True)

    def test_extract_doc_from_sr_no_match(self):
        """Custom axiom should not match non-engine files."""
        _exec(
            self.frozen,
            """
(defterm is-engine-file :origin "check if sr is from engine")
(axiom is-engine-file-rule
    (= (is-engine-file (bench_pg.search.sr "engine.py" ?line ?col ?ctx ?callers)) true)
    :origin "match engine.py results")
""",
        )
        # "test.py" should NOT match the "engine.py" pattern
        result = _eval(self.frozen, '(is-engine-file (bench_pg.search.sr "test.py" 1 1 "import foo" ()))')
        # Should not rewrite to true — returns the unreduced form
        self.assertNotEqual(result, True)

    def test_compose_ln_accessor_in_custom_axiom(self):
        """Custom axiom that uses ln-kind to check node type."""
        _exec(
            self.frozen,
            """
(defterm is-fact :origin "check if ln node is a fact")
(axiom is-fact-rule
    (= (is-fact (ln ?name "fact" ?val ?depth ?inputs)) true)
    :origin "match fact nodes")
""",
        )
        result = _eval(self.frozen, '(is-fact (ln "revenue" "fact" "15" 0 ()))')
        self.assertEqual(result, True)

        result = _eval(self.frozen, '(is-fact (ln "thm-high" "theorem" "true" 3 ("revenue")))')
        self.assertNotEqual(result, True)

    def test_chain_accessors(self):
        """Extract a field, then use it in another expression."""
        _exec(
            self.frozen,
            """
(defterm get-depth :origin "get depth from ln")
(axiom get-depth-rule (= (get-depth ?node) (ln-depth ?node))
    :origin "delegate to ln-depth")
""",
        )
        result = _eval(self.frozen, '(get-depth (strict (ln "engine.derive" "theorem" "true" 3 ("revenue" "margin"))))')
        self.assertEqual(result, 3)

    def test_dx_issue_filter_axiom(self):
        """Custom axiom matching only issue-category dx items."""
        _exec(
            self.frozen,
            """
(defterm is-issue :origin "check if dx item is an issue")
(axiom is-issue-rule
    (= (is-issue (dx ?name "issue" ?kind ?type ?detail)) true)
    :origin "match issue items")
""",
        )
        result = _eval(self.frozen, '(is-issue (dx "engine.count" "issue" "diff" "diverge" "5 vs 3"))')
        self.assertEqual(result, True)

        result = _eval(self.frozen, '(is-issue (dx "engine.count" "warning" "diff" "unused" ""))')
        self.assertNotEqual(result, True)

    def test_nested_accessor_composition(self):
        """Use sr-doc result as input to another expression."""
        _exec(
            self.frozen,
            """
(defterm doc-is :origin "check document name")
(axiom doc-is-rule (= (doc-is ?expected ?sr-form)
    (= (sr-doc ?sr-form) ?expected))
    :origin "compare doc name")
""",
        )
        result = _eval(self.frozen, '(doc-is "engine.py" (bench_pg.search.sr "engine.py" 42 1 "def derive:" ()))')
        # The rewrite should produce (= "engine.py" "engine.py") → true
        self.assertEqual(result, True)


class TestPostingToSrRoundTrip(unittest.TestCase):
    """_posting_to_sr and _sr_to_posting preserve all data."""

    def test_round_trip_preserves_column(self):
        from parseltongue.core.inspect.systems.search import _posting_to_sr, _sr_to_posting

        posting = {
            ("engine.py", 42): {
                "document": "engine.py",
                "line": 42,
                "column": 5,
                "context": "def derive(self):",
                "callers": [{"name": "engine.derive", "overlap": 0.85}],
                "total_callers": 1,
            }
        }
        sr_list = _posting_to_sr(posting)
        restored = _sr_to_posting(sr_list)

        self.assertEqual(restored[("engine.py", 42)]["column"], 5)

    def test_round_trip_preserves_overlap(self):
        from parseltongue.core.inspect.systems.search import _posting_to_sr, _sr_to_posting

        posting = {
            ("engine.py", 10): {
                "document": "engine.py",
                "line": 10,
                "column": 1,
                "context": "import os",
                "callers": [
                    {"name": "engine.derive", "overlap": 0.85},
                    {"name": "engine.eval", "overlap": 0.42},
                ],
                "total_callers": 2,
            }
        }
        sr_list = _posting_to_sr(posting)
        restored = _sr_to_posting(sr_list)

        callers = restored[("engine.py", 10)]["callers"]
        self.assertEqual(len(callers), 2)
        self.assertAlmostEqual(callers[0]["overlap"], 0.85)
        self.assertAlmostEqual(callers[1]["overlap"], 0.42)
        self.assertEqual(callers[0]["name"], "engine.derive")

    def test_round_trip_preserves_all_fields(self):
        from parseltongue.core.inspect.systems.search import _posting_to_sr, _sr_to_posting

        posting = {
            ("doc.py", 7): {
                "document": "doc.py",
                "line": 7,
                "column": 3,
                "context": "raise ValueError",
                "callers": [],
                "total_callers": 0,
            }
        }
        sr_list = _posting_to_sr(posting)
        restored = _sr_to_posting(sr_list)

        orig = posting[("doc.py", 7)]
        rest = restored[("doc.py", 7)]
        self.assertEqual(rest["document"], orig["document"])
        self.assertEqual(rest["line"], orig["line"])
        self.assertEqual(rest["column"], orig["column"])
        self.assertEqual(rest["context"], orig["context"])
        self.assertEqual(rest["callers"], orig["callers"])
        self.assertEqual(rest["total_callers"], orig["total_callers"])

    def test_multiple_entries_round_trip(self):
        from parseltongue.core.inspect.systems.search import _posting_to_sr, _sr_to_posting

        posting = {
            ("a.py", 1): {
                "document": "a.py",
                "line": 1,
                "column": 1,
                "context": "line one",
                "callers": [{"name": "x", "overlap": 1.0}],
                "total_callers": 1,
            },
            ("b.py", 5): {
                "document": "b.py",
                "line": 5,
                "column": 2,
                "context": "line five",
                "callers": [],
                "total_callers": 0,
            },
        }
        sr_list = _posting_to_sr(posting)
        self.assertEqual(len(sr_list), 2)

        restored = _sr_to_posting(sr_list)
        self.assertEqual(len(restored), 2)
        self.assertIn(("a.py", 1), restored)
        self.assertIn(("b.py", 5), restored)


if __name__ == "__main__":
    unittest.main()
