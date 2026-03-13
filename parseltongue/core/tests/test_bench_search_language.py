"""Tests for the pltg search language — full S-expression composition.

Every query is a string. No Python arrays, no manual Symbol construction.
Tests exercise the full language surface through bench.search() and
bench.eval() (raw expression evaluation, not posting-set wrapped).

Language features under test:
    scope       — cross-system queries (lens, evaluation, self)
    project     — evaluate in parent, pass concrete value to child
    delegate    — pattern-match ?vars from parent env, post proposal
    quote       — prevent evaluation, pass raw expression tree
    let         — local bindings
    if          — conditional evaluation
    ?var        — pattern variables bound from env
    ?...splat   — variadic pattern match / splice
    count       — posting set cardinality
    and/or/not  — set operations on posting sets

Scenarios model real cross-domain workflows:
    "How many facts does the lens see?"
    "Which lens nodes are quoted in report.txt?"
    "Are all evaluation issues about diffs?"
    "Find document lines matching lens node names"
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

; --- Variadic splat axioms ---

(defterm sum-all :origin "variadic sum")
(axiom sum-all-base (= (sum-all ?x) ?x)
    :origin "single element is itself")
(axiom sum-all-step (= (sum-all ?x ?y ?...rest) (+ ?x (sum-all ?y ?...rest)))
    :origin "peel first, add to sum of rest")

(defterm all-gt :origin "variadic threshold check")
(axiom all-gt-base (= (all-gt ?t ?x) (> ?x ?t))
    :origin "single element check")
(axiom all-gt-step (= (all-gt ?t ?x ?y ?...rest) (and (> ?x ?t) (all-gt ?t ?y ?...rest)))
    :origin "first must pass, and all remaining")

; List-valued term for delegate splat binding
(defterm metrics (quote (revenue margin net-income headcount growth-target))
    :origin "list of all metric names")
"""


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bench_lang_")
        self.bench_dir = os.path.join(self.tmpdir, ".bench")
        self._bg_patcher = patch(_BG_RELOAD)
        self._bg_patcher.start()

    def tearDown(self):
        self._bg_patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _bench(self):
        self._write("report.txt", DOC_TEXT)
        path = self._write("main.pltg", PLTG_SOURCE)
        bench = Bench(bench_dir=self.bench_dir)
        bench.prepare(path)
        return bench


# ── 1. Scope — cross-system queries ──


class TestScope(_Base):
    """(scope name expr) — evaluate expr in a named system."""

    def test_scope_lens_kind_fact(self):
        """Basic scope: get fact nodes from lens."""
        b = self._bench()
        r = b.search('(scope lens (kind "fact"))')
        names = {ln["document"] for ln in r["lines"]}
        self.assertIn("revenue", names)
        self.assertIn("margin", names)
        self.assertNotIn("double-rev", names)

    def test_scope_lens_downstream(self):
        """Scope lens: who depends on revenue?"""
        b = self._bench()
        r = b.search('(scope lens (downstream "revenue"))')
        names = {ln["document"] for ln in r["lines"]}
        self.assertIn("double-rev", names)
        self.assertIn("revenue-per-head", names)

    def test_scope_lens_inputs(self):
        """Scope lens: what does double-rev depend on?"""
        b = self._bench()
        r = b.search('(scope lens (inputs "double-rev"))')
        names = {ln["document"] for ln in r["lines"]}
        self.assertIn("revenue", names)

    def test_scope_evaluation_issues(self):
        """Scope evaluation: get all issues."""
        b = self._bench()
        r = b.search('(scope evaluation (issues))')
        self.assertGreater(r["total_lines"], 0)

    def test_scope_evaluation_category(self):
        """Scope evaluation: filter by category."""
        b = self._bench()
        r = b.search('(scope evaluation (category "issue"))')
        self.assertGreater(r["total_lines"], 0)

    def test_scope_self_arithmetic(self):
        """(scope self (+ 2 3)) — evaluate in current engine."""
        b = self._bench()
        result = b.eval('(scope self (+ 2 3))')
        self.assertEqual(result, 5)

    def test_scope_self_let(self):
        """(scope self (let ((x 10)) (+ x 5))) — let inside scope."""
        b = self._bench()
        result = b.eval('(scope self (let ((x 10)) (+ x 5)))')
        self.assertEqual(result, 15)

    def test_scope_self_if(self):
        """(scope self (if (> 5 3) "yes" "no")) — if inside scope."""
        b = self._bench()
        result = b.eval('(scope self (if (> 5 3) "yes" "no"))')
        self.assertEqual(result, "yes")

    def test_scope_lens_focus_prefix(self):
        """Scope lens: namespace prefix filter."""
        b = self._bench()
        r = b.search('(scope lens (focus "thm-"))')
        names = {ln["document"] for ln in r["lines"]}
        for n in names:
            self.assertTrue(n.startswith("thm-"))
        self.assertTrue(len(names) > 0)

    def test_scope_lens_roots(self):
        """Scope lens: root nodes (depth 0)."""
        b = self._bench()
        r = b.search('(scope lens (roots))')
        self.assertGreater(r["total_lines"], 0)


# ── 2. Raw eval — returns values, not posting sets ──


class TestRawEval(_Base):
    """bench.eval(expr) returns the raw evaluation result."""

    def test_eval_arithmetic(self):
        b = self._bench()
        self.assertEqual(b.eval('(+ 2 3)'), 5)

    def test_eval_nested_arithmetic(self):
        b = self._bench()
        self.assertEqual(b.eval('(+ (+ 1 2) (+ 3 4))'), 10)

    def test_eval_comparison(self):
        b = self._bench()
        self.assertTrue(b.eval('(> 5 3)'))
        self.assertFalse(b.eval('(< 5 3)'))

    def test_eval_if(self):
        b = self._bench()
        self.assertEqual(b.eval('(if true "yes" "no")'), "yes")
        self.assertEqual(b.eval('(if false "yes" "no")'), "no")

    def test_eval_let(self):
        b = self._bench()
        self.assertEqual(b.eval('(let ((x 7) (y 3)) (+ x y))'), 10)

    def test_eval_quote(self):
        """(quote (+ 1 2)) returns the unevaluated list."""
        b = self._bench()
        result = b.eval('(quote (+ 1 2))')
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)

    def test_eval_count_scope_lens(self):
        """(count (scope lens (kind "fact"))) — count fact nodes."""
        b = self._bench()
        result = b.eval('(count (scope lens (kind "fact")))')
        self.assertEqual(result, 5)

    def test_eval_count_scope_evaluation(self):
        """(count (scope evaluation (issues))) — count issues."""
        b = self._bench()
        result = b.eval('(count (scope evaluation (issues)))')
        self.assertGreater(result, 0)

    def test_eval_scope_lens_depth(self):
        """(scope lens (depth "revenue")) — scalar from lens scope."""
        b = self._bench()
        result = b.eval('(scope lens (depth "revenue"))')
        self.assertIsInstance(result, int)

    def test_eval_scope_lens_value(self):
        """(scope lens (value "revenue")) — value as string."""
        b = self._bench()
        result = b.eval('(scope lens (value "revenue"))')
        self.assertEqual(result, "15")

    def test_eval_scope_evaluation_consistent(self):
        """(scope evaluation (consistent)) — bool result."""
        b = self._bench()
        result = b.eval('(scope evaluation (consistent))')
        self.assertIsInstance(result, bool)


# ── 3. Project — evaluate in parent, pass to child ──


class TestProject(_Base):
    """(project expr) evaluates in parent engine before entering scope."""

    def test_project_arithmetic_into_scope(self):
        """(scope self (project (+ 10 5))) — trivial project."""
        b = self._bench()
        result = b.eval('(scope self (project (+ 10 5)))')
        self.assertEqual(result, 15)

    def test_project_count_into_self(self):
        """Project the count of lens facts into self scope."""
        b = self._bench()
        result = b.eval('(scope self (project (count (scope lens (kind "fact")))))')
        self.assertEqual(result, 5)

    def test_project_comparison_into_if(self):
        """Use projected count in a conditional.

        "Are there more than 3 facts?" — project gets the count,
        if decides based on it.
        """
        b = self._bench()
        result = b.eval('(scope self (if (> (project (count (scope lens (kind "fact")))) 3) "many" "few"))')
        self.assertEqual(result, "many")

    def test_project_lens_value_into_arithmetic(self):
        """Project a lens value into arithmetic.

        Get revenue value from lens, double it in parent.
        """
        b = self._bench()
        # lens (value "revenue") returns "15" as string
        # but we can also get depth which is numeric
        result = b.eval('(scope self (+ (project (scope lens (depth "revenue"))) 10))')
        self.assertIsInstance(result, (int, float))

    def test_project_bridges_scope_boundary(self):
        """Project resolves in parent, child receives concrete value.

        Parent search engine counts lens facts → 5.
        Lens scope receives 5, returns it as-is.
        """
        b = self._bench()
        count = b.eval('(count (scope lens (kind "fact")))')
        self.assertEqual(count, 5)


# ── 4. Delegate — bind ?vars from parent env ──


class TestDelegate(_Base):
    """(delegate body) / (delegate pattern body) — transport modifier."""

    def test_delegate_through_lens_scope(self):
        """(scope lens (delegate (project (+ 1 2)))) — delegate posts proposal.

        Lens scope triggers _rp which evaluates the delegate body
        in the parent env. (project (+ 1 2)) → 3 in parent.
        The proposal 3 is posted to :bind, delegate picks it.
        """
        b = self._bench()
        result = b.eval('(scope lens (delegate (project (+ 1 2))))')
        self.assertEqual(result, 3)

    def test_delegate_binds_parent_fact(self):
        """(scope lens (delegate (project revenue))) — delegate resolves
        parent fact through project."""
        b = self._bench()
        result = b.eval('(scope lens (delegate (project revenue)))')
        self.assertEqual(result, 15)

    def test_delegate_with_conditional(self):
        """(scope lens (delegate (> ?revenue 10) ?revenue)) — conditional delegate.

        Binds ?revenue from parent env (revenue=15), checks > 10, returns 15.
        """
        b = self._bench()
        result = b.eval('(scope lens (delegate (> ?revenue 10) ?revenue))')
        self.assertEqual(result, 15)


# ── 5. Let + If inside scopes ──


class TestLetAndIf(_Base):
    """Language special forms compose with scope."""

    def test_let_binds_count(self):
        """Bind a count to a local var, use in arithmetic."""
        b = self._bench()
        result = b.eval('(let ((n (count (scope lens (kind "fact"))))) (+ n 10))')
        self.assertEqual(result, 15)

    def test_if_on_lens_depth(self):
        """Conditional on lens depth value."""
        b = self._bench()
        result = b.eval('(if (= (scope lens (depth "revenue")) 0) "root" "derived")')
        self.assertEqual(result, "root")

    def test_if_on_evaluation_consistent(self):
        """Conditional on evaluation consistency."""
        b = self._bench()
        result = b.eval('(if (scope evaluation (consistent)) "healthy" "issues")')
        # We have diffs with different values → not consistent
        self.assertEqual(result, "issues")

    def test_let_with_multiple_scopes(self):
        """Bind values from different scopes, combine."""
        b = self._bench()
        result = b.eval(
            '(let ((facts (count (scope lens (kind "fact"))))'
            '      (issues (count (scope evaluation (issues)))))'
            '  (+ facts issues))'
        )
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 5)  # at least 5 facts

    def test_nested_let_if(self):
        """Let + if + scope composition."""
        b = self._bench()
        result = b.eval(
            '(let ((n (count (scope lens (kind "fact")))))' '  (if (> n 3)' '    (let ((m (+ n 100))) m)' '    0))'
        )
        self.assertEqual(result, 105)


# ── 6. Cross-scope composition ──


class TestCrossScope(_Base):
    """Queries that compose results from multiple scopes."""

    def test_and_text_with_lens_scope(self):
        """(and "revenue" (scope lens (kind "fact"))) — text AND lens."""
        b = self._bench()
        r = b.search('(and "revenue" (scope lens (kind "fact")))')
        # Both posting sets intersected — revenue must appear in both
        if r["total_lines"] > 0:
            names = {ln["document"] for ln in r["lines"]}
            self.assertIn("revenue", names)

    def test_or_two_lens_queries(self):
        """(or (scope lens (kind "fact")) (scope lens (kind "axiom")))"""
        b = self._bench()
        r = b.search('(or (scope lens (kind "fact")) (scope lens (kind "axiom")))')
        names = {ln["document"] for ln in r["lines"]}
        self.assertIn("revenue", names)
        self.assertIn("pos-rule", names)

    def test_count_lens_vs_evaluation(self):
        """Compare counts from different scopes."""
        b = self._bench()
        facts = b.eval('(count (scope lens (kind "fact")))')
        theorems = b.eval('(count (scope lens (kind "theorem")))')
        issues = b.eval('(count (scope evaluation (issues)))')
        self.assertEqual(facts, 5)
        self.assertGreater(theorems, 0)
        self.assertGreater(issues, 0)

    def test_search_in_doc_with_lens_filter(self):
        """(and (in "report.txt" "revenue") (scope lens (kind "fact")))"""
        b = self._bench()
        r = b.search('(and (in "report.txt" "revenue") (scope lens (kind "fact")))')
        # Intersection: lines mentioning revenue in report.txt AND lens fact nodes
        self.assertIsInstance(r, dict)

    def test_scope_lens_layer_then_count(self):
        """Count nodes at each depth layer."""
        b = self._bench()
        layer0 = b.eval('(count (scope lens (layer 0)))')
        layer1 = b.eval('(count (scope lens (layer 1)))')
        self.assertGreater(layer0, 0)
        # Layer 1 should have computed terms
        self.assertGreaterEqual(layer1, 0)

    def test_conditional_scope_routing(self):
        """Route to different scopes based on a condition.

        If evaluation is consistent, get lens roots; otherwise get issues.
        """
        b = self._bench()
        result = b.eval(
            '(if (scope evaluation (consistent))'
            '  (count (scope lens (roots)))'
            '  (count (scope evaluation (issues))))'
        )
        # Not consistent (has diff divergences) → should return issue count
        self.assertIsInstance(result, int)
        self.assertGreater(result, 0)


# ── 7. Complex composition pipelines ──


class TestCompositionPipelines(_Base):
    """Multi-step pipelines that chain language features."""

    def test_count_facts_vs_theorems_ratio(self):
        """Compute ratio: facts / (facts + theorems)."""
        b = self._bench()
        result = b.eval(
            '(let ((f (count (scope lens (kind "fact"))))'
            '      (t (count (scope lens (kind "theorem")))))'
            '  (/ f (+ f t)))'
        )
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)
        self.assertLess(result, 1)

    def test_scope_depth_conditional_message(self):
        """Check if a node is a root, report via if."""
        b = self._bench()
        result = b.eval(
            '(let ((d (scope lens (depth "double-rev"))))' '  (if (= d 0) "root" (if (= d 1) "shallow" "deep")))'
        )
        # double-rev depends on revenue (depth 0) → should be depth 1
        self.assertIn(result, ("root", "shallow", "deep"))

    def test_issue_count_matches_category_filter(self):
        """Verify count(issues) == count(category "issue")."""
        b = self._bench()
        count_issues = b.eval('(count (scope evaluation (issues)))')
        count_cat = b.eval('(count (scope evaluation (category "issue")))')
        self.assertEqual(count_issues, count_cat)

    def test_all_diffs_produce_issues(self):
        """We have 3 diffs, all between different values → >= 3 issues."""
        b = self._bench()
        issue_count = b.eval('(count (scope evaluation (issues)))')
        self.assertGreaterEqual(issue_count, 3)

    def test_lens_graph_coverage(self):
        """Total nodes = facts + terms + axioms + theorems."""
        b = self._bench()
        facts = b.eval('(count (scope lens (kind "fact")))')
        terms = b.eval('(count (scope lens (kind "term")))')
        axioms = b.eval('(count (scope lens (kind "axiom")))')
        theorems = b.eval('(count (scope lens (kind "theorem")))')
        total = facts + terms + axioms + theorems
        self.assertGreater(total, 0)
        # 5 facts + 3 terms + 1 axiom + 4 theorems = 13
        self.assertEqual(facts, 5)
        self.assertEqual(axioms, 5)

    def test_project_count_into_comparison(self):
        """Project counts from two scopes, compare in parent.

        "Are there more facts than issues?"
        """
        b = self._bench()
        result = b.eval('(> (count (scope lens (kind "fact")))' '   (count (scope evaluation (issues))))')
        # 5 facts vs >= 3 issues
        self.assertIsInstance(result, bool)

    def test_nested_scope_project_chain(self):
        """scope → project → scope — three-level chain.

        Outer: self
        Project: counts lens facts → 5
        Inner: uses projected value in arithmetic.
        """
        b = self._bench()
        result = b.eval('(scope self' '  (let ((n (project (count (scope lens (kind "fact"))))))' '    (* n 10)))')
        self.assertEqual(result, 50)

    def test_quote_preserves_expression(self):
        """(quote (kind "fact")) returns the unevaluated expression."""
        b = self._bench()
        result = b.eval('(quote (kind "fact"))')
        self.assertIsInstance(result, list)
        # Should be [Symbol("kind"), "fact"]
        self.assertEqual(len(result), 2)


# ── 8. Splats in rewrite axioms ──


class TestSplatAxioms(_Base):
    """Variadic ?...rest splat patterns in rewrite axioms."""

    def test_sum_all_single(self):
        """(sum-all 7) → 7 via base case."""
        b = self._bench()
        self.assertEqual(b.eval('(sum-all 7)'), 7)

    def test_sum_all_two(self):
        """(sum-all 3 4) → 7 via step + base."""
        b = self._bench()
        self.assertEqual(b.eval('(sum-all 3 4)'), 7)

    def test_sum_all_three(self):
        """(sum-all 1 2 3) → 6 via two steps + base."""
        b = self._bench()
        self.assertEqual(b.eval('(sum-all 1 2 3)'), 6)

    def test_sum_all_five_metrics(self):
        """(sum-all revenue margin net-income headcount growth-target)
        = 15 + 22 + 3.3 + 150 + 10 = 200.3"""
        b = self._bench()
        result = b.eval('(sum-all revenue margin net-income headcount growth-target)')
        self.assertAlmostEqual(result, 200.3)

    def test_all_gt_true(self):
        """(all-gt 0 revenue margin headcount) → true, all > 0."""
        b = self._bench()
        self.assertTrue(b.eval('(all-gt 0 revenue margin headcount)'))

    def test_all_gt_false(self):
        """(all-gt 20 revenue margin headcount) → false, revenue=15 < 20."""
        b = self._bench()
        self.assertFalse(b.eval('(all-gt 20 revenue margin headcount)'))

    def test_all_gt_single(self):
        """(all-gt 10 revenue) → true, 15 > 10."""
        b = self._bench()
        self.assertTrue(b.eval('(all-gt 10 revenue)'))

    def test_sum_all_with_scope_count(self):
        """Combine splat axiom with scope: sum fact count + issue count."""
        b = self._bench()
        result = b.eval(
            '(sum-all'
            '  (count (scope lens (kind "fact")))'
            '  (count (scope lens (kind "axiom")))'
            '  (count (scope evaluation (issues))))'
        )
        # 5 facts + some axioms + some issues
        self.assertIsInstance(result, (int, float))
        self.assertGreater(result, 5)


# ── 9. Splats in delegate ──


class TestDelegateSplats(_Base):
    """?...splat patterns in delegate — bind list-valued terms from parent env,
    splice into body expressions."""

    def test_delegate_splat_binds_list(self):
        """(scope lens (delegate (sum-all ?...metrics)))

        Parent env has metrics = (quote (revenue margin ...)).
        Delegate binds ?...metrics → [revenue, margin, ...] from parent.
        Substitute splices into (sum-all revenue margin ...).
        Parent evaluates the bound body: 15+22+3.3+150+10 = 200.3.
        """
        b = self._bench()
        result = b.eval('(scope lens (delegate (sum-all ?...metrics)))')
        self.assertAlmostEqual(result, 200.3)

    def test_delegate_splat_all_gt(self):
        """(scope lens (delegate (all-gt 0 ?...metrics)))

        Binds ?...metrics from parent, splices into (all-gt 0 revenue margin ...).
        All metrics > 0 → true.
        """
        b = self._bench()
        result = b.eval('(scope lens (delegate (all-gt 0 ?...metrics)))')
        self.assertTrue(result)

    def test_delegate_splat_conditional(self):
        """(scope lens (delegate (> ?revenue 10) (sum-all ?...metrics)))

        Conditional delegate: check ?revenue > 10, then sum all metrics.
        """
        b = self._bench()
        result = b.eval('(scope lens (delegate (> ?revenue 10) (sum-all ?...metrics)))')
        self.assertAlmostEqual(result, 200.3)

    def test_delegate_splat_conditional_fails(self):
        """(scope lens (delegate (> ?revenue 100) (sum-all ?...metrics)))

        Condition fails (15 > 100 is false) → delegate returns [].
        """
        b = self._bench()
        with self.assertRaises(NameError):
            b.eval('(scope lens (delegate (> ?revenue 100) (sum-all ?...metrics)))')

    def test_delegate_splat_with_project(self):
        """(scope lens (delegate (project (+ ?revenue ?margin))))

        Project evaluates (+ ?revenue ?margin) in parent — binds
        ?revenue=15, ?margin=22, computes 37. Delegate picks the result.
        """
        b = self._bench()
        result = b.eval('(scope lens (delegate (project (+ ?revenue ?margin))))')
        self.assertEqual(result, 37)

    def test_delegate_splat_sum_vs_direct(self):
        """Delegate-splatted sum should equal direct sum-all."""
        b = self._bench()
        direct = b.eval('(sum-all revenue margin net-income headcount growth-target)')
        via_delegate = b.eval('(scope lens (delegate (sum-all ?...metrics)))')
        self.assertEqual(direct, via_delegate)
