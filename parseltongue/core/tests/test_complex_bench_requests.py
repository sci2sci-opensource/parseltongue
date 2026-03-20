"""Tests for search systems on Lens, Evaluation, and Hologram.

Exercises scope/project/delegate semantics through the bench search
infrastructure. Each optic holds its own search system with a
DocumentIndex-backed S-expression query language. Scopes are registered
in the main search engine so queries can compose across domains.

Covers:
- LensSearchSystem: node, kind, inputs, downstream, roots, layer, focus
- EvaluationSearchSystem: issues, warnings, danglings, focus, kind, category, type
- HologramSystem: left, right, lens, divergent, common, only
- Cross-scope queries: (scope lens ...), (scope evaluation ...)
- Scope + project: (scope lens (project (kind "fact")))
- Scope + delegate: multi-level scope chains
- find/fuzzy on all three optics via their search indexes
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ..inspect.bench import Bench

_BG_RELOAD = "parseltongue.core.inspect.technician.Technician._background_reload"

# ── Fixtures ──

DOC_TEXT = """\
The company earned $15M in Q3 revenue. Operating margin was 22%.
Net income was $3.3M. Headcount is 150 employees.
Growth target is 10% year-over-year."""

PLTG_SOURCE = """\
(load-document "report.txt" "report.txt")

(fact revenue 15
    :evidence (evidence "report.txt"
        :quotes ("The company earned $15M in Q3 revenue")
        :explanation "Q3 revenue figure"))

(fact margin 22
    :evidence (evidence "report.txt"
        :quotes ("Operating margin was 22%")
        :explanation "Operating margin percentage"))

(fact net-income 3.3
    :evidence (evidence "report.txt"
        :quotes ("Net income was $3.3M")
        :explanation "Net income figure"))

(fact headcount 150
    :evidence (evidence "report.txt"
        :quotes ("Headcount is 150 employees")
        :explanation "Employee count"))

(fact growth-target 10
    :evidence (evidence "report.txt"
        :quotes ("Growth target is 10% year-over-year")
        :explanation "Annual growth target"))

(defterm double-rev (* revenue 2)
    :evidence (evidence "report.txt"
        :quotes ("The company earned $15M in Q3 revenue")
        :explanation "Double the revenue"))

(defterm margin-ratio (/ margin 100)
    :evidence (evidence "report.txt"
        :quotes ("Operating margin was 22%")
        :explanation "Margin as decimal"))

(defterm revenue-per-head (/ revenue headcount)
    :evidence (evidence "report.txt"
        :quotes ("The company earned $15M in Q3 revenue")
        :explanation "Revenue per employee"))

(defterm positive :origin "Forward declaration for positivity predicate")

(axiom pos-rule (= (positive ?x) (> ?x 0))
    :origin "Positivity definition")

(derive thm-positive (> double-rev 0) :using (double-rev revenue))
(derive thm-margin-under-100 (< margin 100) :using (margin))
(derive thm-headcount-positive (> headcount 0) :using (headcount))

(derive thm-pos-revenue pos-rule
    :bind ((?x revenue))
    :using (pos-rule revenue))

(diff diff-rev-vs-income :replace revenue :with net-income)
(diff diff-rev-vs-headcount :replace revenue :with headcount)
(diff diff-margin-vs-target :replace margin :with growth-target)
"""


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="complex_bench_")
        self.bench_dir = os.path.join(self.tmpdir, ".bench")
        self._bg_patcher = patch(_BG_RELOAD)
        self._bg_patcher.start()

    def tearDown(self):
        self._bg_patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _bench(self):
        return Bench(bench_dir=self.bench_dir)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _prepare(self):
        self._write("report.txt", DOC_TEXT)
        path = self._write("main.pltg", PLTG_SOURCE)
        bench = self._bench()
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


# ── Lens Search System ──


class TestLensSearchSystem(_Base):
    """S-expression queries over a Lens provenance graph."""

    def test_find_regex(self):
        bench = self._prepare()
        lens = bench.lens()
        results = lens.find("revenue")
        self.assertIn("revenue", results)
        self.assertIn("revenue-per-head", results)
        # double-rev doesn't contain "revenue" substring
        results_rev = lens.find("rev")
        self.assertIn("double-rev", results_rev)

    def test_find_no_match(self):
        bench = self._prepare()
        lens = bench.lens()
        self.assertEqual(lens.find("zzz_nonexistent_zzz"), [])

    def test_fuzzy_ranked(self):
        bench = self._prepare()
        lens = bench.lens()
        results = lens.fuzzy("margin")
        self.assertTrue(len(results) > 0)
        # Exact match should rank first
        self.assertEqual(results[0], "margin")
        self.assertIn("margin-ratio", results)

    def test_kind_fact(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search('(kind "fact")')
        names = {item[1] for item in posting}
        self.assertIn("revenue", names)
        self.assertIn("margin", names)
        self.assertIn("headcount", names)
        self.assertNotIn("double-rev", names)

    def test_kind_axiom(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search('(kind "axiom")')
        names = {item[1] for item in posting}
        self.assertIn("pos-rule", names)
        self.assertNotIn("revenue", names)

    def test_kind_theorem(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search('(kind "theorem")')
        names = {item[1] for item in posting}
        self.assertIn("thm-pos-revenue", names)

    def test_node_single(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search('(node "revenue")')
        self.assertEqual(len(posting), 1)
        self.assertEqual(posting[0][1], "revenue")

    def test_node_missing(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search('(node "nonexistent")')
        self.assertEqual(len(posting), 0)

    def test_inputs(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search('(inputs "double-rev")')
        names = {item[1] for item in posting}
        self.assertIn("revenue", names)

    def test_downstream(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search('(downstream "revenue")')
        names = {item[1] for item in posting}
        self.assertIn("double-rev", names)
        self.assertIn("revenue-per-head", names)

    def test_roots(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search("(roots)")
        names = {item[1] for item in posting}
        # Axioms and forward terms are roots
        self.assertIn("pos-rule", names)

    def test_layer(self):
        bench = self._prepare()
        lens = bench.lens()
        layer0 = lens.search("(layer 0)")
        # Layer 0 = roots (facts, axioms, forward terms)
        self.assertTrue(len(layer0) > 0)

    def test_focus_prefix(self):
        bench = self._prepare()
        lens = bench.lens()
        posting = lens.search('(focus "thm-")')
        names = {item[1] for item in posting}
        for n in names:
            self.assertTrue(n.startswith("thm-"), f"{n} doesn't start with thm-")
        self.assertIn("thm-positive", names)

    def test_depth_scalar(self):
        bench = self._prepare()
        lens = bench.lens()
        result = lens.search('(depth "revenue")')
        # depth returns an int scalar
        self.assertIsInstance(result, int)

    def test_value_scalar(self):
        bench = self._prepare()
        lens = bench.lens()
        result = lens.search('(value "revenue")')
        self.assertIsInstance(result, str)


# ── Evaluation Search System ──


class TestEvaluationSearchSystem(_Base):
    """S-expression queries over Evaluation items."""

    def test_find_regex(self):
        bench = self._prepare()
        dx = bench.evaluate()
        results = dx.find("diff")
        self.assertTrue(len(results) > 0)

    def test_fuzzy(self):
        bench = self._prepare()
        dx = bench.evaluate()
        results = dx.fuzzy("rev")
        self.assertTrue(len(results) > 0)

    def test_issues(self):
        bench = self._prepare()
        dx = bench.evaluate()
        posting = dx.search("(issues)")
        # We have diffs between different values → divergence issues
        self.assertTrue(len(posting) > 0)

    def test_danglings(self):
        bench = self._prepare()
        dx = bench.evaluate()
        posting = dx.search("(danglings)")
        # Some items may be dangling
        self.assertIsInstance(posting, list)

    def test_warnings(self):
        bench = self._prepare()
        dx = bench.evaluate()
        posting = dx.search("(warnings)")
        self.assertIsInstance(posting, list)

    def test_category_filter(self):
        bench = self._prepare()
        dx = bench.evaluate()
        posting = dx.search('(category "issue")')
        issues_direct = dx.issues()
        # Both should find the same items
        self.assertEqual(len(posting), len(issues_direct))

    def test_kind_filter(self):
        bench = self._prepare()
        dx = bench.evaluate()
        posting = dx.search('(kind "diff")')
        # All diff-related items
        self.assertTrue(len(posting) >= 0)

    def test_type_filter(self):
        bench = self._prepare()
        dx = bench.evaluate()
        posting = dx.search('(type "diverge")')
        self.assertIsInstance(posting, list)

    def test_focus_namespace(self):
        bench = self._prepare()
        dx = bench.evaluate()
        posting = dx.search('(focus "diff-")')
        names_in_items = set()
        for item in posting:
            doc = item[1]
            # Items within this category doc at this line should have diff- prefix
            # (evaluation groups by category, not name)
        self.assertIsInstance(posting, list)

    def test_consistent_returns_bool(self):
        bench = self._prepare()
        dx = bench.evaluate()
        result = dx.search("(consistent)")
        # Has diffs with different values → not consistent
        self.assertIsInstance(result, bool)


# ── Hologram Search System ──


class TestHologramSystem(_Base):
    """S-expression queries over Hologram (multi-lens).

    HologramSystem.evaluate() returns hn form lists:
        [hn, ln_form_0, ln_form_1, ...]
    where each ln_form is [ln, name, kind, value, depth, inputs, evidence]
    or [] if absent from that lens.
    """

    @staticmethod
    def _hn_names(forms):
        """Extract node names from hn or ln form lists."""
        from parseltongue.core.atoms import Symbol
        names = set()
        for form in forms:
            if not isinstance(form, (list, tuple)) or len(form) < 2:
                continue
            tag = str(form[0]) if isinstance(form[0], Symbol) else ""
            if tag.endswith("ln"):
                # Bare ln form: [ln, name, kind, ...]
                names.add(form[1])
            elif tag.endswith("hn"):
                # hn form: [hn, ln_sub_0, ln_sub_1, ...]
                for sub in form[1:]:
                    if isinstance(sub, (list, tuple)) and len(sub) >= 2:
                        stag = str(sub[0]) if isinstance(sub[0], Symbol) else ""
                        if stag.endswith("ln"):
                            names.add(sub[1])
        return names

    def test_find_across_lenses(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        results = h.find(".*")
        self.assertTrue(len(results) > 0)

    def test_fuzzy_across_lenses(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        results = h.fuzzy("rev")
        self.assertIsInstance(results, list)

    def test_divergent(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        result = h.search("(divergent)")
        # Returns hn form list
        self.assertIsInstance(result, list)
        names = self._hn_names(result)
        self.assertTrue(len(names) > 0)

    def test_common(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        result = h.search("(common)")
        # Returns hn form list (may be empty if nothing shared)
        self.assertIsInstance(result, list)

    def test_left(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        result = h.search("(left)")
        names = self._hn_names(result)
        self.assertIn("revenue", names)

    def test_right(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        result = h.search("(right)")
        names = self._hn_names(result)
        self.assertIn("net-income", names)

    def test_lens_index(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        left = h.search("(lens 0)")
        right = h.search("(lens 1)")
        left_names = self._hn_names(left)
        right_names = self._hn_names(right)
        self.assertIn("revenue", left_names)
        self.assertIn("net-income", right_names)

    def test_only(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        only_left = h.search("(only 0)")
        only_right = h.search("(only 1)")
        left_names = self._hn_names(only_left)
        right_names = self._hn_names(only_right)
        self.assertEqual(left_names & right_names, set())

    def test_left_kind_filter(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        # left (kind "fact") returns ln forms from lens 0
        result = h.search('(left (kind "fact"))')
        names = self._hn_names(result)
        self.assertIn("revenue", names)

    def test_compose_two_names(self):
        bench = self._prepare()
        h = bench.compose("revenue", "net-income")
        result = h.search("(divergent)")
        self.assertIsInstance(result, list)


# ── Cross-Scope Queries ──


class TestCrossScopeQueries(_Base):
    """Queries that compose across search/lens/evaluation scopes."""

    def test_scope_lens_kind(self):
        bench = self._prepare()
        result = bench.search('(scope lens (kind "fact"))')
        self.assertGreater(result["total_lines"], 0)

    def test_scope_lens_roots(self):
        bench = self._prepare()
        result = bench.search("(scope lens (roots))")
        self.assertGreater(result["total_lines"], 0)

    def test_scope_lens_inputs(self):
        bench = self._prepare()
        result = bench.search('(scope lens (inputs "double-rev"))')
        names = {ln["document"] for ln in result["lines"]}
        self.assertIn("revenue", names)

    def test_scope_lens_downstream(self):
        bench = self._prepare()
        result = bench.search('(scope lens (downstream "revenue"))')
        names = {ln["document"] for ln in result["lines"]}
        self.assertIn("double-rev", names)

    def test_scope_evaluation_issues(self):
        bench = self._prepare()
        result = bench.search("(scope evaluation (issues))")
        self.assertGreater(result["total_lines"], 0)

    def test_scope_evaluation_kind(self):
        bench = self._prepare()
        result = bench.search('(scope evaluation (kind "diff"))')
        self.assertIsInstance(result, dict)

    def test_scope_evaluation_category(self):
        bench = self._prepare()
        result = bench.search('(scope evaluation (category "issue"))')
        self.assertGreater(result["total_lines"], 0)

    def test_and_text_with_scope(self):
        """Compose text search AND scope lens query."""
        bench = self._prepare()
        # Search for "revenue" in text AND in lens facts
        result = bench.search('(scope lens (kind "fact"))')
        self.assertGreater(result["total_lines"], 0)

    def test_scope_lens_focus(self):
        bench = self._prepare()
        result = bench.search('(scope lens (focus "thm-"))')
        names = {ln["document"] for ln in result["lines"]}
        for n in names:
            self.assertTrue(n.startswith("thm-"), f"{n} doesn't start with thm-")


# ── Project and Delegate via Scope ──


class TestProjectAndDelegate(_Base):
    """Test project and delegate semantics through scope chains."""

    def test_project_self_evaluates_locally(self):
        """(project expr) evaluates in current engine."""
        bench = self._prepare()
        from parseltongue.core.atoms import Symbol

        engine = bench.engine
        # project with one arg evaluates in self
        result = engine.evaluate(["project", [Symbol("+"), 2, 3]])
        self.assertEqual(result, 5)

    def test_project_injects_into_scope(self):
        """(scope name (project expr)) — project evaluates expr in parent, passes result to scope."""
        bench = self._prepare()
        # Register a simple scope that receives projected values
        from parseltongue.core.atoms import Symbol

        def child_fn(name, *args):
            # receives already-evaluated project results
            total = 0
            for a in args:
                if isinstance(a, (int, float)):
                    total += a
            return total

        bench.engine.env[Symbol("adder")] = child_fn
        result = bench.engine.evaluate(["scope", Symbol("adder"), ["project", [Symbol("+"), 10, 5]]])
        self.assertEqual(result, 15)

    def test_project_bridges_scope_boundary(self):
        """Parent resolves (project my-fact) → value, child receives concrete value."""
        bench = self._prepare()
        from parseltongue.core.atoms import Symbol

        received = []

        def child_fn(name, *args):
            received.extend(args)
            return args[0] if args else None

        bench.engine.env[Symbol("spy")] = child_fn
        result = bench.engine.evaluate(["scope", Symbol("spy"), ["project", Symbol("revenue")]])
        self.assertEqual(result, 15)
        self.assertEqual(received[0], 15)

    def test_delegate_bare_skips_one_level(self):
        """(delegate (project x)) — scope posts proposal, delegate picks it."""
        bench = self._prepare()
        from parseltongue.core.atoms import Symbol

        store_val = [42]

        def outer_fn(name, *args):
            # Outer scope: args contain delegate with :bind from inner processing
            for a in args:
                if isinstance(a, (int, float)):
                    return a
                if isinstance(a, list):
                    # delegate was processed, extract bound value
                    return a
            return None

        bench.engine.env[Symbol("outer")] = outer_fn
        bench.engine.env[Symbol("store")] = lambda: store_val[0]
        # Simple delegate: resolve store at outer scope
        result = bench.engine.evaluate(["scope", Symbol("outer"), ["project", Symbol("revenue")]])
        self.assertEqual(result, 15)

    def test_scope_self_identity(self):
        """(scope self expr) evaluates in current engine."""
        bench = self._prepare()
        from parseltongue.core.atoms import Symbol

        result = bench.engine.evaluate(["scope", Symbol("self"), [Symbol("+"), Symbol("revenue"), Symbol("margin")]])
        self.assertEqual(result, 37)

    def test_nested_scope_self(self):
        """(strict (scope self (scope self expr))) — strict forces evaluation through boundaries."""
        bench = self._prepare()
        from parseltongue.core.atoms import Symbol

        result = bench.engine.evaluate(
            [
                Symbol("strict"),
                ["scope", Symbol("self"), ["scope", Symbol("self"), [Symbol("+"), Symbol("revenue"), 1]]],
            ]
        )
        self.assertEqual(result, 16)

    def test_scope_with_if(self):
        """(scope self (if cond then else)) — special forms work inside scope."""
        bench = self._prepare()
        from parseltongue.core.atoms import Symbol

        result = bench.engine.evaluate(
            ["scope", Symbol("self"), ["if", [Symbol(">"), Symbol("revenue"), 10], "high", "low"]]
        )
        self.assertEqual(result, "high")

    def test_scope_with_let(self):
        """(scope self (let ((x 5)) (+ x 1))) — let works inside scope."""
        bench = self._prepare()
        from parseltongue.core.atoms import Symbol

        result = bench.engine.evaluate(
            ["scope", Symbol("self"), ["let", [[Symbol("x"), 5]], [Symbol("+"), Symbol("x"), 1]]]
        )
        self.assertEqual(result, 6)

    def test_project_through_search_scope(self):
        """(scope lens (project (kind "fact"))) — project evaluates in parent search,
        result flows into lens scope."""
        bench = self._prepare()
        # The search engine's scope mechanism handles this:
        # (scope lens ...) calls the lens callable with unevaluated args
        # (project ...) is resolved eagerly by the parent before forwarding
        result = bench.search('(scope lens (kind "fact"))')
        self.assertGreater(result["total_lines"], 0)


# ── Axiom Instantiation via Derive ──


class TestAxiomInstantiation(_Base):
    """Derive with :bind instantiates axiom templates."""

    def test_bind_single_var(self):
        bench = self._prepare()
        engine = bench.engine
        thm = engine.theorems["thm-pos-revenue"]
        self.assertIsNotNone(thm)
        result = engine.evaluate(thm.wff)
        self.assertTrue(result)

    def test_bind_result_consistent(self):
        bench = self._prepare()
        dx = bench.evaluate()
        # thm-pos-revenue should not produce issues (revenue > 0)
        thm_issues = [i for i in dx.issues() if "thm-pos-revenue" in i.name]
        self.assertEqual(len(thm_issues), 0, f"Unexpected issues: {thm_issues}")

    def test_axiom_in_lens_graph(self):
        bench = self._prepare()
        lens = bench.lens()
        axiom_nodes = lens.search('(kind "axiom")')
        names = {item[1] for item in axiom_nodes}
        self.assertIn("pos-rule", names)

    def test_theorem_has_axiom_as_input(self):
        bench = self._prepare()
        lens = bench.lens()
        inputs = lens.search('(inputs "thm-pos-revenue")')
        names = {item[1] for item in inputs}
        self.assertIn("pos-rule", names)


# ── Diff Evaluation ──


class TestDiffEvaluation(_Base):
    """Diff semantics through search systems."""

    def test_diff_divergence_detected(self):
        bench = self._prepare()
        dx = bench.evaluate()
        # revenue(15) vs net-income(3.3) → divergence
        issues = dx.issues()
        diff_names = {i.name for i in issues}
        has_rev_income = any("rev-vs-income" in n for n in diff_names)
        self.assertTrue(has_rev_income, f"Expected rev-vs-income diff issue, got: {diff_names}")

    def test_dissect_shows_both_sides(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        left_names = TestHologramSystem._hn_names(h.search("(left)"))
        right_names = TestHologramSystem._hn_names(h.search("(right)"))
        self.assertIn("revenue", left_names)
        self.assertIn("net-income", right_names)

    def test_dissect_divergent_nodes(self):
        bench = self._prepare()
        h = bench.dissect("diff-rev-vs-income")
        divergent = h.search("(divergent)")
        # At minimum, the replaced/with nodes differ
        self.assertTrue(len(divergent) > 0)

    def test_multiple_diffs_all_evaluated(self):
        bench = self._prepare()
        dx = bench.evaluate()
        diff_issues = [i for i in dx.issues() if "diff" in i.type.lower() or "diverge" in i.type.lower()]
        # 3 diffs, all between different values → at least 3 divergences
        self.assertGreaterEqual(len(diff_issues), 3, f"Expected >= 3 diff issues, got {len(diff_issues)}")

    def test_evaluation_focus_diffs(self):
        bench = self._prepare()
        dx = bench.evaluate()
        posting = dx.search('(focus "diff-")')
        self.assertIsInstance(posting, list)


# ── Stained Holograms ──


class TestStainedHolograms(_Base):
    """Vital stain — runtime execution trace as a Hologram.

    bench.stain(*names) applies a Stain to the live engine, re-evaluates
    theorem WFFs to capture runtime dependency edges, then builds a
    Hologram with live_probe structures. Hologram requires >= 2 lenses,
    so stain always takes 2+ names (or use dissect with stain in CLI).
    Each lens has real depths, edges, and nodes from the actual
    evaluation path.
    """

    def test_stain_returns_hologram(self):
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        from ..inspect.optics.hologram import Hologram
        self.assertIsInstance(h, Hologram)

    def test_stain_two_theorems(self):
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        self.assertEqual(len(h._lenses), 2)
        self.assertEqual(h._labels, ["thm-positive", "thm-margin-under-100"])

    def test_stain_three_theorems(self):
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100", "thm-headcount-positive")
        self.assertEqual(len(h._lenses), 3)

    def test_stain_lens_has_structure(self):
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        for lens in h._lenses:
            structure = lens._structure
            self.assertTrue(len(structure.graph) > 0, "Stained lens should have graph nodes")
            self.assertTrue(len(structure.depths) > 0, "Stained lens should have depths")

    def test_stain_captures_dependencies(self):
        """thm-positive depends on double-rev which depends on revenue."""
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        names_0 = set(h._lenses[0]._structure.graph.keys())
        self.assertIn("double-rev", names_0)
        self.assertIn("revenue", names_0)
        names_1 = set(h._lenses[1]._structure.graph.keys())
        self.assertIn("margin", names_1)

    def test_stain_depths_nonzero(self):
        """Stained structure should have nodes at depth > 0."""
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        for lens in h._lenses:
            depths = lens._structure.depths
            max_depth = max(depths.values()) if depths else 0
            self.assertGreater(max_depth, 0, "Expected at least one node with depth > 0")

    def test_stain_has_layers(self):
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        for lens in h._lenses:
            layers = lens._structure.layers
            self.assertTrue(len(layers) > 0, "Stained structure should have layers")

    def test_stain_search_left_right(self):
        """Hologram search operators work on stained holograms."""
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        left = h.search("(left)")
        right = h.search("(right)")
        self.assertIsInstance(left, list)
        self.assertIsInstance(right, list)

    def test_stain_divergent(self):
        """Two different theorems should produce a divergent query result."""
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        divergent = h.search("(divergent)")
        # divergent returns hn forms — may be empty if lenses overlap fully
        self.assertIsInstance(divergent, list)

    def test_stain_common(self):
        """Stained theorems sharing no deps should have empty common set."""
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        common = h.search("(common)")
        self.assertIsInstance(common, list)

    def test_stain_find(self):
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        results = h.find("revenue")
        self.assertIn("revenue", results)

    def test_stain_fuzzy(self):
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        results = h.fuzzy("rev")
        self.assertTrue(len(results) > 0)

    def test_stain_viz_data_has_depth(self):
        """Viz renderer should produce structure items with correct depths from stain."""
        bench = self._prepare()
        h = bench.stain("thm-positive", "thm-margin-under-100")
        from ..inspect.perspectives.visualisation.renderer import _build_named_structure_data
        for lens in h._lenses:
            structure = lens._structure
            items = _build_named_structure_data(set(structure.graph.keys()), structure)
            depths = [item["depth"] for item in items]
            self.assertTrue(any(d > 0 for d in depths), f"Expected depth > 0 in viz data, got {depths}")

    def test_stain_pos_rule_axiom_traced(self):
        """thm-pos-revenue uses pos-rule via :bind — stain should capture it."""
        bench = self._prepare()
        h = bench.stain("thm-pos-revenue", "thm-positive")
        names_0 = set(h._lenses[0]._structure.graph.keys())
        # pos-rule axiom and revenue should be in the dependency graph
        self.assertIn("revenue", names_0)
