"""Tests for Search — full-text search with S-expression queries and scoped indexes.

Exercises:
- Literal phrase search
- S-expression operators: and, or, not, in, count, near, seq, re, lines
- Scoped indexes with scope operator
- Scope-specific operators injected into engine.env
- DocumentIndex integration: add, search, trace
- Incremental reindexing via Merkle hashing
- Ranking strategies: callers, coverage, document
"""

import os
import shutil
import tempfile
import unittest

from parseltongue.core.quote_verifier.index import DocumentIndex

from ..inspect.search import Search
from ..inspect.store import SearchStore

# ── Fixtures ──

DOC_A = """\
def derive(self, name):
    raise ValueError("missing")
    return self.engine.facts[name]
"""

DOC_B = """\
import os
import sys
from pathlib import Path

def load(path):
    raise KeyError("not found")
    return open(path).read()
"""

DOC_C = """\
class Engine:
    def eval(self, expr):
        raise ValueError("bad expression")
        return self.evaluate(expr)

    def derive(self, name):
        if name not in self.facts:
            raise NameError(f"unknown: {name}")
        return self.facts[name]
"""


def _make_search(*docs: tuple[str, str]) -> Search:
    """Create a Search with pre-loaded documents."""
    idx = DocumentIndex()
    for name, text in docs:
        idx.add(name, text)
    return Search(SearchStore(index=idx))


class TestLiteralSearch(unittest.TestCase):
    """Plain string (non S-expression) queries."""

    def setUp(self):
        self.search = _make_search(
            ("a.py", DOC_A),
            ("b.py", DOC_B),
            ("c.py", DOC_C),
        )

    def test_finds_exact_phrase(self):
        r = self.search.query("raise ValueError")
        self.assertGreater(r["total_lines"], 0)

    def test_no_match_returns_empty(self):
        r = self.search.query("xyzzy_not_here_42")
        self.assertEqual(r["total_lines"], 0)

    def test_finds_in_multiple_docs(self):
        r = self.search.query("raise")
        docs = {ln["document"] for ln in r["lines"]}
        self.assertGreaterEqual(len(docs), 2)

    def test_max_lines_respected(self):
        r = self.search.query("raise", max_lines=2)
        self.assertLessEqual(len(r["lines"]), 2)

    def test_offset_skips(self):
        r_all = self.search.query("raise", max_lines=100)
        r_off = self.search.query("raise", max_lines=100, offset=1)
        if r_all["total_lines"] > 1:
            self.assertEqual(len(r_off["lines"]), len(r_all["lines"]) - 1)

    def test_line_has_context(self):
        r = self.search.query("raise ValueError")
        self.assertGreater(len(r["lines"]), 0)
        self.assertIn("context", r["lines"][0])
        self.assertIn("raise ValueError", r["lines"][0]["context"])


class TestSExprOperators(unittest.TestCase):
    """S-expression query operators over posting sets."""

    def setUp(self):
        self.search = _make_search(
            ("a.py", DOC_A),
            ("b.py", DOC_B),
            ("c.py", DOC_C),
        )

    def test_and(self):
        r = self.search.query('(and "raise" "ValueError")')
        for ln in r["lines"]:
            self.assertIn("ValueError", ln["context"])

    def test_or(self):
        r = self.search.query('(or "KeyError" "NameError")')
        self.assertGreater(r["total_lines"], 0)
        texts = [ln["context"] for ln in r["lines"]]
        has_key = any("KeyError" in t for t in texts)
        has_name = any("NameError" in t for t in texts)
        self.assertTrue(has_key or has_name)

    def test_not(self):
        r_all = self.search.query('(or "raise ValueError" "raise KeyError")')
        r_not = self.search.query('(not "raise" "KeyError")')
        # not should exclude KeyError lines
        for ln in r_not["lines"]:
            self.assertNotIn("KeyError", ln["context"])

    def test_in_exact(self):
        r = self.search.query('(in "a.py" "raise")')
        for ln in r["lines"]:
            self.assertEqual(ln["document"], "a.py")

    def test_in_suffix(self):
        r = self.search.query('(in "b.py" "raise")')
        for ln in r["lines"]:
            self.assertTrue(ln["document"].endswith("b.py"))

    def test_in_glob(self):
        r = self.search.query('(in "*.py" "raise")')
        self.assertGreater(r["total_lines"], 0)

    def test_count(self):
        r = self.search.query('(count "raise")')
        self.assertEqual(r["total_lines"], 1)  # count returns a single result
        self.assertIn("__result__", r["lines"][0]["document"])

    def test_near(self):
        r = self.search.query('(near "def derive" "raise" 2)')
        self.assertGreater(r["total_lines"], 0)
        for ln in r["lines"]:
            self.assertIn("derive", ln["context"])

    def test_seq(self):
        r = self.search.query('(seq "def derive" "raise")')
        self.assertGreater(r["total_lines"], 0)

    def test_re(self):
        r = self.search.query('(re "raise (ValueError|NameError)")')
        self.assertGreater(r["total_lines"], 0)
        for ln in r["lines"]:
            ctx = ln["context"]
            self.assertTrue("ValueError" in ctx or "NameError" in ctx)

    def test_lines_range(self):
        r = self.search.query('(lines 1 2 (in "a.py" (re ".")))')
        for ln in r["lines"]:
            self.assertLessEqual(ln["line"], 2)
            self.assertGreaterEqual(ln["line"], 1)

    def test_compose_in_and_re(self):
        r = self.search.query('(in "c.py" (re "raise (ValueError|NameError)"))')
        self.assertGreater(r["total_lines"], 0)
        for ln in r["lines"]:
            self.assertEqual(ln["document"], "c.py")

    def test_compose_not_in_near(self):
        r = self.search.query('(not (in "c.py" "raise") "NameError")')
        for ln in r["lines"]:
            self.assertNotIn("NameError", ln["context"])


# TODO
# class TestScopedIndexes(unittest.TestCase):
#     """Scoped indexes with the (scope ...) operator."""
#
#     def setUp(self):
#         # Main file index
#         self.search = _make_search(
#             ("a.py", DOC_A),
#             ("b.py", DOC_B),
#         )
#         # Diagnosis-like scope
#         dx_index = DocumentIndex()
#         dx_index.add("evidence", "revenue [fact] ok: verified\nmargin [fact] ok: verified")
#         dx_index.add("diffs", "diff-rev [diff] diverge: 15 vs 3.3\ndiff-margin [diff] ok: consistent")
#
#         def _kind(*args):
#             """Filter by kind field."""
#             from parseltongue.core.atoms import Symbol
#             posting = args[0]
#             kind_val = str(args[1]) if len(args) > 1 else ""
#             if isinstance(posting, str):
#                 posting = self.search._to_posting(posting)
#             return {k: v for k, v in posting.items() if kind_val in v.get("context", "")}
#
#         def _category(*args):
#             """Filter by category."""
#             from parseltongue.core.atoms import Symbol
#             posting = args[0]
#             cat = str(args[1]) if len(args) > 1 else ""
#             if isinstance(posting, str):
#                 posting = self.search._to_posting(posting)
#             return {k: v for k, v in posting.items() if cat in v.get("context", "")}
#
#         self.search.register_scope("diagnosis", dx_index, {
#             "kind": _kind,
#             "category": _category,
#         })
#
#     def test_scope_switches_index(self):
#         r = self.search.query('(scope diagnosis "diverge")')
#         self.assertGreater(r["total_lines"], 0)
#         for ln in r["lines"]:
#             self.assertIn("diverge", ln["context"])
#
#     def test_scope_doesnt_leak(self):
#         """After scope, default index is restored."""
#         self.search.query('(scope diagnosis "diverge")')
#         r = self.search.query('"raise"')
#         self.assertGreater(r["total_lines"], 0)
#         docs = {ln["document"] for ln in r["lines"]}
#         self.assertTrue(any(d.endswith(".py") for d in docs))
#
#     def test_scope_unknown_raises(self):
#         with self.assertRaises(Exception):
#             self.search.query('(scope nonexistent "test")')
#
#     def test_scope_operator_outside_scope_raises(self):
#         """Scope-specific operators used outside their scope give an error."""
#         with self.assertRaises(Exception):
#             self.search.query('(kind "raise" "fact")')
#
#     def test_default_scope_is_files(self):
#         self.assertEqual(self.search._active_scope, "files")
#
#     def test_register_scope_stores_ops(self):
#         _, ops = self.search._scopes["diagnosis"]
#         self.assertIn("kind", ops)
#         self.assertIn("category", ops)


class TestRanking(unittest.TestCase):
    """Ranking strategies."""

    def setUp(self):
        self.search = _make_search(
            ("a.py", DOC_A),
            ("b.py", DOC_B),
            ("c.py", DOC_C),
        )

    def test_callers_ranking(self):
        r = self.search.query("raise", rank="callers")
        self.assertGreater(r["total_lines"], 0)

    def test_coverage_ranking(self):
        r = self.search.query("raise", rank="coverage")
        self.assertGreater(r["total_lines"], 0)

    def test_document_ranking(self):
        r = self.search.query("raise", rank="document")
        self.assertGreater(r["total_lines"], 0)


class TestIndexDir(unittest.TestCase):
    """index_dir: walk directory, index files, Merkle cache."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="search_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_index_dir_finds_files(self):
        self._write("foo.py", "def hello(): pass")
        self._write("bar.py", "def world(): pass")
        search = Search(SearchStore())
        count = search.index_dir(self.tmpdir)
        self.assertEqual(count, 2)

    def test_index_dir_searchable(self):
        self._write("foo.py", "def hello(): pass")
        search = Search(SearchStore())
        search.index_dir(self.tmpdir)
        r = search.query("hello")
        self.assertGreater(r["total_lines"], 0)

    def test_index_dir_filters_extensions(self):
        self._write("code.py", "def test(): pass")
        self._write("data.csv", "a,b,c")
        search = Search(SearchStore())
        count = search.index_dir(self.tmpdir, extensions=[".py"])
        self.assertEqual(count, 1)

    def test_index_dir_with_store_caches(self):
        """With a Store, index is cached to disk."""
        from ..inspect.store import Store

        bench_dir = os.path.join(self.tmpdir, ".bench")
        store = Store(bench_dir)

        self._write("foo.py", "def cached(): pass")
        search = Search(SearchStore(store=store, path=self.tmpdir))
        search.index_dir(self.tmpdir)

        # Second search with fresh Search should use cache
        search2 = Search(SearchStore(store=store, path=self.tmpdir))
        count = search2.index_dir(self.tmpdir)
        self.assertEqual(count, 0)  # cache hit — nothing re-indexed
        r = search2.query("cached")
        self.assertGreater(r["total_lines"], 0)

    def test_index_dir_incremental_reindex(self):
        """Only changed files are re-indexed."""
        from ..inspect.store import Store

        bench_dir = os.path.join(self.tmpdir, ".bench")
        store = Store(bench_dir)

        self._write("stable.py", "def stable(): pass")
        self._write("changing.py", "def v1(): pass")
        search = Search(SearchStore(store=store, path=self.tmpdir))
        search.index_dir(self.tmpdir)

        # Change one file
        self._write("changing.py", "def v2(): pass")
        search2 = Search(SearchStore(store=store, path=self.tmpdir))
        search2.index_dir(self.tmpdir)

        r = search2.query("v2")
        self.assertGreater(r["total_lines"], 0)
        r_old = search2.query("v1")
        # v1 should no longer match (reindexed)
        self.assertEqual(r_old["total_lines"], 0)

    def test_progress_callback(self):
        self._write("a.py", "x = 1")
        self._write("b.py", "y = 2")
        calls = []
        search = Search(SearchStore())
        search.index_dir(self.tmpdir, on_progress=lambda c, t, f: calls.append((c, t, f)))
        self.assertGreater(len(calls), 0)
        # Last call should have count == total
        self.assertEqual(calls[-1][0], calls[-1][1])


class TestSearchEdgeCases(unittest.TestCase):
    """Edge cases and error handling."""

    def test_empty_index_returns_empty(self):
        search = Search(SearchStore())
        r = search.query("anything")
        self.assertEqual(r["total_lines"], 0)

    def test_empty_query(self):
        search = _make_search(("a.py", "hello"))
        r = search.query("")
        # Empty string matches nothing or everything depending on index
        self.assertIsInstance(r, dict)

    def test_sexpr_on_empty_index(self):
        search = Search(SearchStore())
        r = search.query('(or "a" "b")')
        self.assertEqual(r["total_lines"], 0)

    def test_count_on_empty(self):
        search = Search(SearchStore())
        r = search.query('(count "anything")')
        self.assertEqual(r["lines"][0]["context"], "0")

    def test_result_structure(self):
        search = _make_search(("a.py", "hello world"))
        r = search.query("hello")
        self.assertIn("total_lines", r)
        self.assertIn("total_callers", r)
        self.assertIn("offset", r)
        self.assertIn("lines", r)
        self.assertIsInstance(r["lines"], list)


if __name__ == "__main__":
    unittest.main()
