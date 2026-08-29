"""Identifier tokenization (v2) and the pipe-friendly search rendering.

Words are split into the sub-tokens people type: path segments, snake and
kebab parts, dotted names, camelCase halves. Index and query go through the
same split, so ``widgets_v2`` finds ``src/widgets_v2/AssetEntry.tsx`` and
``AssetEntry`` finds it too.
"""

import json
import unittest

from ..inspect.bench_cli import _render_search
from ..quote_verifier.index import DocumentIndex
from ..search_engine.document import TOKENIZER_VERSION, SearchDocument, split_compound
from ..search_engine.index import DocumentSearchIndex
from ..search_engine.strategy import _tokenize_query


class TestSplitCompound(unittest.TestCase):
    def test_paths_and_identifiers(self):
        self.assertEqual(
            split_compound("src/widgets_v2/AssetEntry.tsx"),
            ["src", "widgets_v2", "widgets", "v2", "assetentry", "asset", "entry", "tsx"],
        )
        self.assertEqual(
            split_compound("app.services.inference_service"),
            ["app", "services", "inference_service", "inference", "service"],
        )
        self.assertEqual(split_compound("systems.operations_v2"), ["systems", "operations_v2", "operations", "v2"])
        self.assertEqual(split_compound("multi-level"), ["multi", "level"])
        self.assertEqual(
            split_compound("@widgets_v2/account/AccountLayout"),
            ["widgets_v2", "widgets", "v2", "account", "accountlayout", "layout"],
        )

    def test_camel_case(self):
        self.assertEqual(split_compound("LLMConfiguration"), ["llm", "configuration"])
        self.assertEqual(split_compound("getHTTPResponse"), ["get", "http", "response"])
        self.assertEqual(split_compound("inferenceMethod"), ["inference", "method"])

    def test_plain_words_have_no_parts(self):
        self.assertEqual(split_compound("cascade"), [])
        self.assertEqual(split_compound("v2"), [])
        self.assertEqual(split_compound("x"), [])

    def test_version_is_two(self):
        self.assertEqual(TOKENIZER_VERSION, 2)


class TestQueryTokens(unittest.TestCase):
    def test_query_gets_the_same_parts(self):
        self.assertEqual(_tokenize_query("widgets_v2"), ("widgets_v2", "widgets", "v2"))
        self.assertEqual(_tokenize_query("src/widgets_v2")[:1], ("src/widgets_v2",))
        self.assertIn("widgets_v2", _tokenize_query("src/widgets_v2"))
        toks = _tokenize_query("AssetEntry")
        self.assertIn("asset", toks)
        self.assertIn("entry", toks)


SAMPLE = {
    "a.tsx": "import { AssetEntry } from 'src/widgets_v2/search/card/AssetEntry';\nexport const x = 1;\n",
    "b.py": "class LLMConfiguration:\n    pass\n",
    "c.md": "plain words only here\n",
}


class TestIndexedParts(unittest.TestCase):
    def setUp(self):
        self.idx = DocumentIndex(SAMPLE)
        self.six = DocumentSearchIndex(self.idx)

    def test_path_segment_and_camel_parts_are_searchable(self):
        hits = self.six.lookup("widgets_v2", "direct")
        self.assertIn(("a.tsx", 1), hits)
        hits = self.six.lookup("AssetEntry", "direct")
        self.assertIn(("a.tsx", 1), hits)
        hits = self.six.lookup("entry", "direct")
        self.assertIn(("a.tsx", 1), hits)
        hits = self.six.lookup("configuration", "direct")
        self.assertIn(("b.py", 1), hits)
        self.assertEqual(self.six.lookup("widgets", "direct").keys() & {("c.md", 1)}, set())

    def test_document_parts_come_from_original_case(self):
        sdoc = SearchDocument(self.idx.documents["b.py"])
        self.assertIn("llm", sdoc.word_to_lines)
        self.assertIn("configuration", sdoc.word_to_lines)


class TestForcedReindexRebuildsSearchDocuments(unittest.TestCase):
    """`pg reindex --force` must re-derive the search documents even when no
    file changed: that is how an index built by another tokenizer version
    catches up, and how the notice about it goes away."""

    TEST_DIR = "/tmp/tokenizer-v2-reindex-test"

    def setUp(self):
        import os
        import shutil

        shutil.rmtree(self.TEST_DIR, ignore_errors=True)
        os.makedirs(self.TEST_DIR)
        with open(f"{self.TEST_DIR}/pg.toml", "w") as f:
            f.write('[detect]\nlanguages = ["python"]\n[index]\nextensions = [".py"]\n')
        open(f"{self.TEST_DIR}/.pgignore", "w").close()
        with open(f"{self.TEST_DIR}/a.py", "w") as f:
            f.write("x = src_widgets_v2\n")
        self._cwd = os.getcwd()
        os.chdir(self.TEST_DIR)

    def tearDown(self):
        import os
        import shutil

        os.chdir(self._cwd)
        shutil.rmtree(self.TEST_DIR, ignore_errors=True)

    def test_force_rebuilds_and_clears_notice(self):
        from unittest.mock import patch

        from ..inspect.search import Search
        from ..inspect.store import SearchStore, Store

        with patch("os.getcwd", return_value=self.TEST_DIR):
            # Index as if with a tokenizer that produced no sub-tokens.
            with patch("parseltongue.core.search_engine.document.split_compound", return_value=[]):
                search = Search(SearchStore(store=Store(f"{self.TEST_DIR}/.bench"), path=self.TEST_DIR))
                search.index_dir(self.TEST_DIR)
            self.assertEqual(search.query("widgets")["total_lines"], 0)
            search._store.tokenizer_built_with = 1
            self.assertTrue(any("tokenizer v1" in n for n in search.notices()))

            # No file changed; a plain pass changes nothing.
            search.reindex()
            self.assertEqual(search.query("widgets")["total_lines"], 0)

            # A forced pass rebuilds with the current tokenizer.
            search.reindex(force=True)
            self.assertGreater(search.query("widgets")["total_lines"], 0)
            self.assertEqual(search.notices(), [])


class TestRenderSearch(unittest.TestCase):
    RESULT = {
        "lines": [
            {"document": "a.py", "line": 3, "context": "x = 1", "callers": ["claim-a"]},
            {"document": "a.py", "line": 9, "context": "y = 2", "callers": []},
            {"document": "b/c.py", "line": 1, "context": "z: 3", "callers": []},
        ],
        "total": 3,
        "offset": 0,
        "limit": 0,
    }

    def test_grep_is_one_hit_per_line_no_footer(self):
        out = _render_search(self.RESULT, "grep", json)
        self.assertEqual(out, "a.py:3:x = 1\na.py:9:y = 2\nb/c.py:1:z: 3\n")

    def test_json_is_one_object_per_line(self):
        rows = [json.loads(line) for line in _render_search(self.RESULT, "json", json).splitlines()]
        self.assertEqual([r["line"] for r in rows], [3, 9, 1])
        self.assertEqual(rows[0]["callers"], ["claim-a"])

    def test_grouped_has_gaps_callers_and_footer(self):
        out = _render_search(self.RESULT, "grouped", json)
        self.assertIn("a.py\n  3      [claim-a] x = 1\n\n  9      y = 2\n\nb/c.py\n  1      z: 3\n\n(3 results)\n", out)

    def test_grouped_footer_pages_only_with_a_limit(self):
        paged = dict(self.RESULT, limit=2, total=5, offset=2)
        self.assertTrue(_render_search(paged, "grouped", json).endswith("(3-5/5 results, page 2/3)\n"))


if __name__ == "__main__":
    unittest.main()
