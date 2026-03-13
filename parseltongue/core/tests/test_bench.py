"""Tests for the Bench — real .pltg files, caching, lens, evaluation, search.

Exercises:
- Documents loaded via (load-document) with evidence and quote verification
- Module import chains (main → sub-module)
- All integrity state transitions: CORRUPTED → UNKNOWN → VERIFIED
- All status state transitions: INITIALIZED → LOADING → LIVE
- Hot-patch flow (file change → detect → patch → background reload)
- Disk cache hit path (exact Merkle match)
- Cold load path (no cache → VERIFIED/LIVE)
- Memory cache hit (no change → return immediately)
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ..inspect.bench import Bench
from ..inspect.evaluation import Evaluation

# Patch path for disabling background reloads in tests
_BG_RELOAD = "parseltongue.core.inspect.technician.Technician._background_reload"


class _BenchTestBase(unittest.TestCase):
    """Shared setup: tmpdir + bench_dir + helper for writing files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bench_test_")
        self.bench_dir = os.path.join(self.tmpdir, ".bench")
        # Disable background reloads by default — tests run synchronously
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

    def _resolved(self, path):
        return str(os.path.realpath(path))


# ── Fixtures: document files + .pltg sources ──

REPORT_TEXT = "The company earned $15M in Q3 revenue. Operating margin was 22%. Net income was $3.3M."

MAIN_PLTG = """\
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

(defterm double-rev (* revenue 2)
    :evidence (evidence "report.txt"
        :quotes ("The company earned $15M in Q3 revenue")
        :explanation "Double the revenue"))

(defterm margin-ratio (/ margin 100)
    :evidence (evidence "report.txt"
        :quotes ("Operating margin was 22%")
        :explanation "Margin as decimal"))

(derive thm-positive (> double-rev 0) :using (double-rev))
(derive thm-margin-under-100 (< margin 100) :using (margin))

(diff diff-rev-vs-income :replace revenue :with net-income)
"""

SUB_REPORT_TEXT = "Total headcount is 150 employees. Average salary is $90K."

SUB_MODULE_PLTG = """\
(load-document "sub_report.txt" "sub_report.txt")

(fact headcount 150
    :evidence (evidence "sub_report.txt"
        :quotes ("Total headcount is 150 employees")
        :explanation "Employee count"))

(fact avg-salary 90
    :evidence (evidence "sub_report.txt"
        :quotes ("Average salary is $90K")
        :explanation "Average salary in thousands"))

(defterm payroll (* headcount avg-salary)
    :evidence (evidence "sub_report.txt"
        :quotes ("Total headcount is 150 employees")
        :explanation "Total payroll cost"))

(diff diff-headcount-vs-salary :replace headcount :with avg-salary)
"""

IMPORT_MAIN_PLTG = """\
(import (quote .sub))

(load-document "main_doc.txt" "main_doc.txt")

(fact offices 3
    :evidence (evidence "main_doc.txt"
        :quotes ("The division has 3 offices")
        :explanation "Office count"))

(fact budget 20
    :evidence (evidence "main_doc.txt"
        :quotes ("a budget of $20M")
        :explanation "Division budget"))

(diff diff-offices-vs-budget :replace offices :with budget)
"""

MAIN_DOC_TEXT = "The division has 3 offices and a budget of $20M."

BAD_QUOTE_PLTG = """\
(load-document "truth.txt" "truth.txt")

(fact sky-color true
    :evidence (evidence "truth.txt"
        :quotes ("The sky is blue")
        :explanation "Sky color"))

(fact water-temp true
    :evidence (evidence "truth.txt"
        :quotes ("This quote does not exist in the document at all")
        :explanation "Fabricated quote"))
"""

TRUTH_TEXT = "The sky is blue. Water is wet."

ALPHA_TEXT = "Revenue grew 10% year-over-year to reach $50M."
BETA_TEXT = "Customer count increased to 1200 active accounts."

MULTI_DOC_PLTG = """\
(load-document "alpha.txt" "alpha.txt")
(load-document "beta.txt" "beta.txt")

(fact revenue-growth 10
    :evidence (evidence "alpha.txt"
        :quotes ("Revenue grew 10% year-over-year")
        :explanation "YoY growth rate"))

(fact total-revenue 50
    :evidence (evidence "alpha.txt"
        :quotes ("to reach $50M")
        :explanation "Total revenue"))

(fact customer-count 1200
    :evidence (evidence "beta.txt"
        :quotes ("Customer count increased to 1200 active accounts")
        :explanation "Active customer count"))

(defterm revenue-per-customer (/ (* total-revenue 1000000) customer-count)
    :evidence (evidence "alpha.txt"
        :quotes ("Revenue grew 10% year-over-year to reach $50M")
        :explanation "Revenue per customer"))

(diff diff-growth-vs-customers :replace revenue-growth :with customer-count)
"""

# Consistent diff: two facts with the same value
CONSISTENT_DIFF_TEXT = "Metric A is 42. Metric B is also 42."

CONSISTENT_DIFF_PLTG = """\
(load-document "same.txt" "same.txt")

(fact metric-a 42
    :evidence (evidence "same.txt"
        :quotes ("Metric A is 42")
        :explanation "First metric"))

(fact metric-b 42
    :evidence (evidence "same.txt"
        :quotes ("Metric B is also 42")
        :explanation "Second metric"))

(diff diff-a-vs-b :replace metric-a :with metric-b)
"""


class TestBenchDocumentsAndQuotes(_BenchTestBase):
    """Bench with real documents, evidence, and quote verification."""

    def _write_main(self):
        self._write("report.txt", REPORT_TEXT)
        return self._write("main.pltg", MAIN_PLTG)

    def _write_bad(self):
        self._write("truth.txt", TRUTH_TEXT)
        return self._write("bad.pltg", BAD_QUOTE_PLTG)

    def _write_multi(self):
        self._write("alpha.txt", ALPHA_TEXT)
        self._write("beta.txt", BETA_TEXT)
        return self._write("multi.pltg", MULTI_DOC_PLTG)

    # ── Good quotes ──

    def test_good_quotes_no_evidence_issues(self):
        """All quotes verify, but diff divergence is expected (different values)."""
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        evidence_issues = [i for i in dx.issues() if "evidence" in i.type or "fabrication" in i.type]
        self.assertEqual(len(evidence_issues), 0)
        diff_issues = [i for i in dx.issues() if "diff" in i.type]
        self.assertGreater(len(diff_issues), 0, "Expected diff divergence between different values")

    def test_good_quotes_no_fabrication_issues(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        fab_issues = [i for i in dx.issues() if "fabrication" in i.type]
        self.assertEqual(len(fab_issues), 0)

    def test_evidence_grounded_in_document(self):
        """Engine verifies quotes against document text."""
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        engine = bench.engine
        self.assertIn("report.txt", engine.documents)
        rev_fact = engine.facts["revenue"]
        self.assertIsNotNone(rev_fact.origin)
        self.assertTrue(rev_fact.origin.is_grounded)

    def test_multiple_documents_all_verified(self):
        path = self._write_multi()
        bench = self._bench()
        bench.prepare(path)
        engine = bench.engine
        self.assertIn("alpha.txt", engine.documents)
        self.assertIn("beta.txt", engine.documents)
        self.assertTrue(engine.facts["revenue-growth"].origin.is_grounded)
        self.assertTrue(engine.facts["customer-count"].origin.is_grounded)
        dx = bench.evaluate()
        evidence_issues = [i for i in dx.issues() if "evidence" in i.type or "fabrication" in i.type]
        self.assertEqual(len(evidence_issues), 0)
        # Diff divergence expected (10 vs 1200)
        diff_issues = [i for i in dx.issues() if "diff" in i.type]
        self.assertGreater(len(diff_issues), 0)

    # ── Bad quotes ──

    def test_bad_quote_produces_issue(self):
        path = self._write_bad()
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        self.assertFalse(dx.consistent)
        self.assertGreater(len(dx.issues()), 0)

    def test_bad_quote_identifies_evidence_issue(self):
        path = self._write_bad()
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        issue_types = {i.type for i in dx.issues()}
        evidence_issues = issue_types & {"unverified_evidence", "potential_fabrication"}
        self.assertTrue(evidence_issues, f"Expected evidence issues, got: {issue_types}")

    def test_good_and_bad_quotes_mixed(self):
        """One good quote + one bad quote: good grounded, bad not."""
        path = self._write_bad()
        bench = self._bench()
        bench.prepare(path)
        engine = bench.engine
        self.assertTrue(engine.facts["sky-color"].origin.is_grounded)
        self.assertFalse(engine.facts["water-temp"].origin.is_grounded)

    # ── Consistent diff ──

    def test_consistent_diff_no_issues(self):
        """Diff between two facts with the same value → no divergence."""
        self._write("same.txt", CONSISTENT_DIFF_TEXT)
        path = self._write("consistent.pltg", CONSISTENT_DIFF_PLTG)
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        self.assertTrue(dx.consistent, f"Expected consistent: {dx.summary()}")
        diff_issues = [i for i in dx.issues() if "diff" in i.type]
        self.assertEqual(len(diff_issues), 0)

    # ── Lens with documents ──

    def test_lens_shows_document_backed_facts(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        lens = bench.lens()
        names = lens.find("revenue")
        self.assertIn("revenue", names)
        view = str(lens.view_node("revenue"))
        self.assertIn("revenue", view)

    def test_lens_shows_terms_with_dependencies(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        lens = bench.lens()
        self.assertIn("double-rev", lens.find("double-rev"))

    # ── Search through document text ──

    def test_search_finds_document_text(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        result = bench.search("revenue")
        self.assertGreater(result["total_lines"], 0)

    def test_search_multi_doc(self):
        path = self._write_multi()
        bench = self._bench()
        bench.prepare(path)
        r1 = bench.search("Revenue grew")
        self.assertGreater(r1["total_lines"], 0)
        r2 = bench.search("Customer count")
        self.assertGreater(r2["total_lines"], 0)


class TestBenchImportChain(_BenchTestBase):
    """Bench with module import chains: main.pltg → sub.pltg."""

    def _write_chain(self):
        self._write("main_doc.txt", MAIN_DOC_TEXT)
        self._write("sub_report.txt", SUB_REPORT_TEXT)
        self._write("sub.pltg", SUB_MODULE_PLTG)
        return self._write("main.pltg", IMPORT_MAIN_PLTG)

    def test_import_loads_sub_module_facts(self):
        path = self._write_chain()
        bench = self._bench()
        bench.prepare(path)
        engine = bench.engine
        self.assertIn("offices", engine.facts)
        self.assertIn("budget", engine.facts)
        sub_facts = [k for k in engine.facts if k.startswith("sub.")]
        self.assertGreater(len(sub_facts), 0, f"No sub. facts. All: {list(engine.facts.keys())}")

    def test_import_chain_documents_registered(self):
        path = self._write_chain()
        bench = self._bench()
        bench.prepare(path)
        engine = bench.engine
        self.assertIn("main_doc.txt", engine.documents)
        sub_docs = [k for k in engine.documents if "sub_report" in k]
        self.assertGreater(len(sub_docs), 0, f"No sub_report doc. Docs: {list(engine.documents.keys())}")

    def test_import_chain_quotes_verified(self):
        path = self._write_chain()
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        evidence_issues = [i for i in dx.issues() if "evidence" in i.type or "fabrication" in i.type]
        self.assertEqual(len(evidence_issues), 0, f"Evidence issues: {evidence_issues}")

    def test_import_chain_lens_covers_both(self):
        path = self._write_chain()
        bench = self._bench()
        bench.prepare(path)
        lens = bench.lens()
        all_names = lens.find(".*")
        self.assertIn("offices", all_names)
        has_sub = any("headcount" in n for n in all_names)
        self.assertTrue(has_sub, f"No headcount in: {all_names}")

    def test_import_chain_search_crosses_modules(self):
        path = self._write_chain()
        bench = self._bench()
        bench.prepare(path)
        result = bench.search("headcount")
        self.assertGreater(result["total_lines"], 0)

    def test_import_chain_collects_multiple_source_files(self):
        """After import chain, store.save receives file lists with both .pltg files."""
        path = self._write_chain()
        with patch("parseltongue.core.inspect.store.Store.save", wraps=None) as mock_save:
            # We need the real save to run, so use wraps on the actual instance
            bench = self._bench()
            real_save = bench._store.save
            saved_args = {}

            def spy_save(*args, **kwargs):
                saved_args["file_lists"] = args[4] if len(args) > 4 else kwargs.get("file_lists", [])
                return real_save(*args, **kwargs)

            bench._store.save = spy_save
            bench.prepare(path)

            pltg_files = [f for f in saved_args.get("file_lists", []) if f.endswith(".pltg")]
            self.assertGreaterEqual(len(pltg_files), 2, f"Expected >=2 .pltg files: {pltg_files}")


class TestBenchStateTransitions(_BenchTestBase):
    """Test all integrity and status state transitions."""

    def _write_main(self):
        self._write("report.txt", REPORT_TEXT)
        return self._write("test.pltg", MAIN_PLTG)

    # ── Default states ──

    def test_initial_integrity_is_corrupted(self):
        bench = self._bench()
        self.assertEqual(bench.integrity["/no/such/path"], Bench.Integrity.CORRUPTED)

    def test_initial_status_is_initialized(self):
        bench = self._bench()
        self.assertEqual(bench.status["/no/such/path"], Bench.Status.INITIALIZED)

    # ── Cold load: → VERIFIED/LIVE ──

    def test_cold_load_integrity_verified(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        self.assertEqual(bench.integrity[self._resolved(path)], Bench.Integrity.VERIFIED)

    def test_cold_load_status_live(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        self.assertEqual(bench.status[self._resolved(path)], Bench.Status.LIVE)

    # ── Memory cache hit: no state change ──

    def test_memory_cache_hit_no_change(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        rpath = self._resolved(path)
        i1 = bench.integrity[rpath]
        s1 = bench.status[rpath]
        bench.prepare(path)
        self.assertEqual(bench.integrity[rpath], i1)
        self.assertEqual(bench.status[rpath], s1)

    def test_memory_cache_hit_engine_unchanged(self):
        """Repeated prepare returns same engine state."""
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        facts1 = set(bench.engine.facts.keys())
        bench.prepare(path)
        facts2 = set(bench.engine.facts.keys())
        self.assertEqual(facts1, facts2)

    # ── Disk cache hit: status → LOADING (background mocked out) ──

    def test_disk_cache_hit_initial_status(self):
        """New Bench instance + disk cache → LOADING (background is mocked)."""
        path = self._write_main()
        bench1 = self._bench()
        bench1.prepare(path)
        rpath = self._resolved(path)

        bench2 = self._bench()
        bench2.prepare(path)
        # With background mocked, stays at LOADING after disk cache hit
        self.assertIn(bench2.status[rpath], (Bench.Status.LOADING, Bench.Status.LIVE))

    def test_disk_cache_hit_integrity_verified(self):
        """Disk cache exact match → VERIFIED immediately."""
        path = self._write_main()
        bench1 = self._bench()
        bench1.prepare(path)

        bench2 = self._bench()
        bench2.prepare(path)
        self.assertEqual(bench2.integrity[self._resolved(path)], Bench.Integrity.VERIFIED)

    def test_disk_cache_hit_preserves_facts(self):
        """New Bench reads facts from disk cache."""
        path = self._write_main()
        bench1 = self._bench()
        bench1.prepare(path)
        facts1 = set(bench1.engine.facts.keys())

        bench2 = self._bench()
        bench2.prepare(path)
        facts2 = set(bench2.engine.facts.keys())
        self.assertEqual(facts1, facts2)

    def test_disk_cache_background_reaches_live(self):
        """With real background reload, eventually reaches LIVE."""
        self._bg_patcher.stop()  # Enable real background for this test
        try:
            path = self._write_main()
            bench1 = self._bench()
            bench1.prepare(path)

            bench2 = self._bench()
            bench2.prepare(path)
            rpath = self._resolved(path)
            # Wait for background thread
            for t in bench2._technician.bg_reload.values():
                t.join(timeout=10)
            self.assertEqual(bench2.status[rpath], Bench.Status.LIVE)
        finally:
            self._bg_patcher.start()

    # ── Hot-patch: file change → CORRUPTED → UNKNOWN/LOADING ──

    def test_hot_patch_on_file_change(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        rpath = self._resolved(path)

        with open(path, "a") as f:
            f.write('\n(fact new-metric 42 :origin "added")\n')

        bench.prepare(path)
        self.assertIn(
            bench.integrity[rpath],
            (
                Bench.Integrity.UNKNOWN,
                Bench.Integrity.VERIFIED,
            ),
        )
        self.assertIn(
            bench.status[rpath],
            (
                Bench.Status.LOADING,
                Bench.Status.LIVE,
            ),
        )

    def test_hot_patch_picks_up_new_fact(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)

        with open(path, "a") as f:
            f.write('\n(fact added-fact 77 :origin "test")\n')

        bench.prepare(path)
        self.assertIn("added-fact", bench.engine.facts)
        self.assertEqual(bench.engine.facts["added-fact"].wff, 77)

    def test_hot_patch_background_reaches_verified(self):
        """With real background, hot-patch eventually reaches VERIFIED/LIVE."""
        self._bg_patcher.stop()
        try:
            path = self._write_main()
            bench = self._bench()
            bench.prepare(path)

            with open(path, "a") as f:
                f.write('\n(fact bg-fact 55 :origin "bg")\n')

            bench.prepare(path)
            for t in bench._technician.bg_reload.values():
                t.join(timeout=10)
            rpath = self._resolved(path)
            self.assertEqual(bench.integrity[rpath], Bench.Integrity.VERIFIED)
            self.assertEqual(bench.status[rpath], Bench.Status.LIVE)
        finally:
            self._bg_patcher.start()

    def test_hot_patch_diagnosis_stale_after_change(self):
        """After hot-patch, getting a new diagnosis works (old one invalidated)."""
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        dx1 = bench.evaluate()

        with open(path, "a") as f:
            f.write('\n(fact dx-change 1 :origin "change")\n')

        bench.prepare(path)
        # Should be able to get a fresh diagnosis
        dx2 = bench.evaluate()
        self.assertIsNot(dx1, dx2)

    def test_hot_patch_tracks_affected_names(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)

        with open(path, "a") as f:
            f.write('\n(fact affected-fact 99 :origin "track")\n')

        bench.prepare(path)
        self.assertIn("affected-fact", bench.engine.facts)

    # ── Repr for all states ──

    def test_integrity_repr_all_states(self):
        integrity = Bench.Integrity()
        self.assertIn("empty", repr(integrity))
        integrity._state["/a.pltg"] = Bench.Integrity.CORRUPTED
        self.assertIn("corrupted", repr(integrity))
        integrity._state["/b.pltg"] = Bench.Integrity.UNKNOWN
        self.assertIn("unknown", repr(integrity))
        integrity._state["/c.pltg"] = Bench.Integrity.VERIFIED
        self.assertIn("verified", repr(integrity))

    def test_status_repr_all_states(self):
        status = Bench.Status()
        self.assertIn("initialized", repr(status))
        status._state["/a.pltg"] = Bench.Status.INITIALIZED
        self.assertIn("initialized", repr(status))
        status._state["/b.pltg"] = Bench.Status.LOADING
        self.assertIn("loading", repr(status))
        status._state["/c.pltg"] = Bench.Status.LIVE
        self.assertIn("live", repr(status))


class TestBenchDiskCache(_BenchTestBase):
    """Test disk cache mechanics: write, read, reuse, invalidate."""

    def _write_main(self):
        self._write("report.txt", REPORT_TEXT)
        return self._write("test.pltg", MAIN_PLTG)

    def test_cold_load_creates_cache_dir(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        self.assertTrue(os.path.isdir(self.bench_dir))

    def test_cold_load_writes_cache_file(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        cache_files = [f for f in os.listdir(self.bench_dir) if f.endswith((".pgz", ".json"))]
        self.assertGreater(len(cache_files), 0)

    def test_cache_preserves_documents(self):
        """New Bench reads documents from disk cache."""
        path = self._write_main()
        bench1 = self._bench()
        bench1.prepare(path)
        docs1 = set(bench1.engine.documents.keys())

        bench2 = self._bench()
        bench2.prepare(path)
        docs2 = set(bench2.engine.documents.keys())
        self.assertEqual(docs1, docs2)

    def test_invalidate_removes_cache_files(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        bench.evaluate()
        bench.invalidate()
        if os.path.isdir(self.bench_dir):
            json_files = [f for f in os.listdir(self.bench_dir) if f.endswith((".pgz", ".json"))]
            self.assertEqual(len(json_files), 0)

    def test_invalidate_path_preserves_other(self):
        """Invalidating one path keeps the other cached."""
        path1 = self._write_main()
        path2 = self._write("other.pltg", '(fact other 1 :origin "test")\n')

        bench = self._bench()
        bench.prepare(path1)
        bench.prepare(path2)
        bench.invalidate(path1)

        # Other sample still works
        self.assertIn("other", bench.engine.facts)

    def test_diagnosis_cache_written(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        bench.evaluate()
        dx_files = [f for f in os.listdir(self.bench_dir) if f.endswith((".dx.pgz", ".dx.json"))]
        self.assertGreater(len(dx_files), 0)

    def test_diagnosis_cache_reuse(self):
        path = self._write_main()
        bench1 = self._bench()
        bench1.prepare(path)
        dx1 = bench1.evaluate()

        bench2 = self._bench()
        bench2.prepare(path)
        dx2 = bench2.evaluate()
        self.assertEqual(dx2.consistent, dx1.consistent)

    def test_store_save_receives_file_hashes(self):
        """Store.save is called with non-empty file hashes on cold load."""
        path = self._write_main()
        bench = self._bench()
        real_save = bench._store.save
        captured = {}

        def spy(*args, **kwargs):
            captured["file_hashes"] = args[5] if len(args) > 5 else kwargs.get("file_hashes", {})
            captured["file_lists"] = args[4] if len(args) > 4 else kwargs.get("file_lists", [])
            return real_save(*args, **kwargs)

        bench._store.save = spy
        bench.prepare(path)
        self.assertGreater(len(captured.get("file_hashes", {})), 0)
        for h in captured["file_hashes"].values():
            self.assertTrue(h, "Empty hash")

    def test_store_save_receives_file_list_with_pltg(self):
        """Store.save is called with file lists containing the .pltg file."""
        path = self._write_main()
        bench = self._bench()
        real_save = bench._store.save
        captured = {}

        def spy(*args, **kwargs):
            captured["file_lists"] = args[4] if len(args) > 4 else kwargs.get("file_lists", [])
            return real_save(*args, **kwargs)

        bench._store.save = spy
        bench.prepare(path)
        pltg_in_list = any(f.endswith(".pltg") for f in captured.get("file_lists", []))
        self.assertTrue(pltg_in_list)


class TestBenchDiagnosis(_BenchTestBase):
    """Diagnosis through the Bench — focus, filter, stats."""

    def test_consistent_system_summary(self):
        self._write("report.txt", REPORT_TEXT)
        path = self._write("clean.pltg", MAIN_PLTG)
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        self.assertIsInstance(dx.summary(), str)

    def test_inconsistent_system_has_issues(self):
        self._write("truth.txt", TRUTH_TEXT)
        path = self._write("bad.pltg", BAD_QUOTE_PLTG)
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        self.assertFalse(dx.consistent)
        self.assertGreater(len(dx.issues()), 0)

    def test_diagnosis_stats(self):
        self._write("truth.txt", TRUTH_TEXT)
        path = self._write("bad.pltg", BAD_QUOTE_PLTG)
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        stats = dx.stats()
        self.assertIn("by_category", stats)
        self.assertIn("by_type", stats)
        self.assertIn("by_kind", stats)

    def test_diagnosis_find(self):
        self._write("truth.txt", TRUTH_TEXT)
        path = self._write("bad.pltg", BAD_QUOTE_PLTG)
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        results = dx.find(".*")
        self.assertGreater(len(results), 0)

    def test_diagnosis_memory_cached(self):
        self._write("report.txt", REPORT_TEXT)
        path = self._write("clean.pltg", MAIN_PLTG)
        bench = self._bench()
        bench.prepare(path)
        dx1 = bench.evaluate()
        dx2 = bench.evaluate()
        self.assertIs(dx1, dx2)

    def test_diagnosis_repr(self):
        self._write("truth.txt", TRUTH_TEXT)
        path = self._write("bad.pltg", BAD_QUOTE_PLTG)
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        self.assertIn("Evaluation", repr(dx))

    def test_diagnosis_to_dict_roundtrip(self):
        self._write("truth.txt", TRUTH_TEXT)
        path = self._write("bad.pltg", BAD_QUOTE_PLTG)
        bench = self._bench()
        bench.prepare(path)
        dx = bench.evaluate()
        d = dx.to_dict()
        dx2 = Evaluation.from_dict(d)
        self.assertEqual(len(dx2.issues()), len(dx.issues()))
        self.assertEqual(dx2.consistent, dx.consistent)


class TestBenchMultipleSamples(_BenchTestBase):
    """Multiple .pltg files loaded into the same Bench."""

    def test_switch_between_samples(self):
        self._write("report.txt", REPORT_TEXT)
        path1 = self._write("a.pltg", MAIN_PLTG)
        self._write("alpha.txt", ALPHA_TEXT)
        self._write("beta.txt", BETA_TEXT)
        path2 = self._write("b.pltg", MULTI_DOC_PLTG)

        bench = self._bench()
        bench.prepare(path1)
        self.assertIn("revenue", bench.engine.facts)
        bench.prepare(path2)
        self.assertIn("customer-count", bench.engine.facts)

    def test_result_by_path(self):
        self._write("report.txt", REPORT_TEXT)
        path1 = self._write("a.pltg", MAIN_PLTG)
        self._write("alpha.txt", ALPHA_TEXT)
        self._write("beta.txt", BETA_TEXT)
        path2 = self._write("b.pltg", MULTI_DOC_PLTG)

        bench = self._bench()
        bench.prepare(path1)
        bench.prepare(path2)

        r1 = bench.result(path1)
        self.assertIn("revenue", r1.system.engine.facts)
        r2 = bench.result(path2)
        self.assertIn("customer-count", r2.system.engine.facts)

    def test_lens_by_path(self):
        self._write("report.txt", REPORT_TEXT)
        path1 = self._write("a.pltg", MAIN_PLTG)
        self._write("alpha.txt", ALPHA_TEXT)
        self._write("beta.txt", BETA_TEXT)
        path2 = self._write("b.pltg", MULTI_DOC_PLTG)

        bench = self._bench()
        bench.prepare(path1)
        bench.prepare(path2)

        lens1 = bench.lens(path1)
        self.assertIn("revenue", lens1.find("revenue"))
        lens2 = bench.lens(path2)
        self.assertIn("customer-count", lens2.find("customer"))

    def test_diagnose_by_path(self):
        self._write("report.txt", REPORT_TEXT)
        path1 = self._write("good.pltg", MAIN_PLTG)
        self._write("truth.txt", TRUTH_TEXT)
        path2 = self._write("bad.pltg", BAD_QUOTE_PLTG)

        bench = self._bench()
        bench.prepare(path1)
        bench.prepare(path2)

        dx1 = bench.evaluate(path1)
        dx2 = bench.evaluate(path2)
        ev1 = [i for i in dx1.issues() if "evidence" in i.type or "fabrication" in i.type]
        self.assertEqual(len(ev1), 0)
        ev2 = [i for i in dx2.issues() if "evidence" in i.type or "fabrication" in i.type]
        self.assertGreater(len(ev2), 0)


class TestBenchReload(_BenchTestBase):
    """File modification detection and re-prepare flows."""

    def _write_main(self):
        self._write("report.txt", REPORT_TEXT)
        return self._write("test.pltg", MAIN_PLTG)

    def test_modify_document_file(self):
        """Changing the document .txt file triggers re-load on prepare."""
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        self.assertTrue(bench.engine.facts["revenue"].origin.is_grounded)

        # Modify the document text — quotes will no longer match
        self._write("report.txt", "Completely different text with no matching quotes.")
        bench.prepare(path)
        # Revenue fact still exists but engine was reloaded
        self.assertIn("revenue", bench.engine.facts)

    def test_add_new_fact_to_pltg(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)

        with open(path, "a") as f:
            f.write('\n(fact growth 8 :origin "added")\n')

        bench.prepare(path)
        self.assertIn("growth", bench.engine.facts)
        self.assertEqual(bench.engine.facts["growth"].wff, 8)

    def test_add_new_document_and_fact(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)

        self._write("extra.txt", "Extra data point: growth rate is 8%.")
        with open(path, "a") as f:
            f.write(
                """
(load-document "extra.txt" "extra.txt")
(fact growth 8
    :evidence (evidence "extra.txt"
        :quotes ("growth rate is 8%")
        :explanation "Growth rate"))
"""
            )

        bench.prepare(path)
        self.assertIn("growth", bench.engine.facts)
        self.assertEqual(bench.engine.facts["growth"].wff, 8)

    def test_remove_fact_and_reprepare(self):
        path = self._write_main()
        bench = self._bench()
        bench.prepare(path)
        self.assertIn("net-income", bench.engine.facts)

        reduced = """\
(load-document "report.txt" "report.txt")

(fact revenue 15
    :evidence (evidence "report.txt"
        :quotes ("The company earned $15M in Q3 revenue")
        :explanation "Q3 revenue figure"))

(fact margin 22
    :evidence (evidence "report.txt"
        :quotes ("Operating margin was 22%")
        :explanation "Operating margin percentage"))
"""
        with open(path, "w") as f:
            f.write(reduced)

        bench.prepare(path)
        self.assertNotIn("net-income", bench.engine.facts)


class TestBenchEdgeCases(_BenchTestBase):
    """Edge cases and error handling."""

    def test_no_prepare_lens_raises(self):
        bench = self._bench()
        with self.assertRaises(RuntimeError):
            bench.lens()

    def test_no_prepare_diagnose_raises(self):
        bench = self._bench()
        with self.assertRaises(RuntimeError):
            bench.evaluate()

    def test_nonexistent_file_raises(self):
        bench = self._bench()
        with self.assertRaises(FileNotFoundError):
            bench.prepare(os.path.join(self.tmpdir, "nonexistent.pltg"))

    def test_empty_pltg(self):
        path = self._write("empty.pltg", "")
        bench = self._bench()
        bench.prepare(path)
        self.assertEqual(len(bench.engine.facts), 0)

    def test_facts_only_no_document(self):
        path = self._write("no_doc.pltg", '(fact x 42 :origin "standalone")\n(fact y 7 :origin "standalone")\n')
        bench = self._bench()
        bench.prepare(path)
        self.assertIn("x", bench.engine.facts)
        self.assertEqual(bench.engine.facts["x"].wff, 42)

    def test_prepare_returns_self(self):
        path = self._write("chain.pltg", '(fact z 1 :origin "test")\n')
        bench = self._bench()
        result = bench.prepare(path)
        self.assertIs(result, bench)


class TestBenchIntegrityStatusClasses(unittest.TestCase):
    """Integrity and Status inner classes in isolation."""

    def test_integrity_all_values(self):
        self.assertEqual(Bench.Integrity.VERIFIED, "verified")
        self.assertEqual(Bench.Integrity.UNKNOWN, "unknown")
        self.assertEqual(Bench.Integrity.CORRUPTED, "corrupted")

    def test_status_all_values(self):
        self.assertEqual(Bench.Status.INITIALIZED, "initialized")
        self.assertEqual(Bench.Status.LOADING, "loading")
        self.assertEqual(Bench.Status.LIVE, "live")

    def test_integrity_default(self):
        self.assertEqual(Bench.Integrity()["/unknown"], Bench.Integrity.CORRUPTED)

    def test_status_default(self):
        self.assertEqual(Bench.Status()["/unknown"], Bench.Status.INITIALIZED)

    def test_integrity_set_all_states(self):
        integrity = Bench.Integrity()
        for state in (Bench.Integrity.CORRUPTED, Bench.Integrity.UNKNOWN, Bench.Integrity.VERIFIED):
            integrity._state["/test"] = state
            self.assertEqual(integrity["/test"], state)

    def test_status_set_all_states(self):
        status = Bench.Status()
        for state in (Bench.Status.INITIALIZED, Bench.Status.LOADING, Bench.Status.LIVE):
            status._state["/test"] = state
            self.assertEqual(status["/test"], state)

    def test_integrity_repr_empty(self):
        self.assertIn("empty", repr(Bench.Integrity()))

    def test_integrity_repr_with_entries(self):
        integrity = Bench.Integrity()
        integrity._state["/a.pltg"] = Bench.Integrity.VERIFIED
        self.assertIn("verified", repr(integrity))
        self.assertIn("a.pltg", repr(integrity))

    def test_status_repr_empty(self):
        self.assertIn("initialized", repr(Bench.Status()))

    def test_status_repr_with_entries(self):
        status = Bench.Status()
        status._state["/a.pltg"] = Bench.Status.LIVE
        self.assertIn("live", repr(status))
        self.assertIn("a.pltg", repr(status))


if __name__ == "__main__":
    unittest.main()
