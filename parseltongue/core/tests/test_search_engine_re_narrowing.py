"""(re …) narrowed through the vocabulary must equal the full per-line scan."""

import re
import unittest

from parseltongue.core.quote_verifier.index import DocumentIndex

from ..inspect.search import Search
from ..inspect.store import SearchStore
from ..search_engine.engine import narrowing_run

DOCS = {
    "a.py": "def alpha(x):\n    return x  # trailing\n\nclass Beta:\n    def gamma(self, y): raise ValueError(y)\n",
    "b.md": "A multi-\nlevel heading\n1. first item\n12. twelfth item\n   3. indented\nSearchDocumentIndex holds SearchDocument\n",
    "c.txt": "foo_bar.baz = widgets_v2/AssetEntry.tsx\nimport os\nimport sys\nzzz and ZZZ\nend$of^line\n",
    "d.py": "raise NameError('x')\nabcx abcy\n\n\n",
}

PATTERNS = [
    "level",
    "multi",
    "Multi",
    "(?i)MULTI",
    "item",
    "first item",
    "twelfth",
    r"\b12\b",
    r"3\.",
    "foo_bar",
    "bar.baz",
    "AssetEntry",
    "assetentry",
    "SearchDocument",
    r"\bdef \w+\(",
    "^import ",
    "import (os|sys)",
    "[A-Z]ab",
    "raise (ValueError|NameError)",
    "abc(?!x)",
    "z{2,}",
    "(abc)+y",
    ".",
    "",
    "^$",
    r"\$of\^",
    "nomatchanywhere",
]


def reference(pattern: str) -> set[tuple[str, int]]:
    rx = re.compile(pattern)
    hits = set()
    for name, text in DOCS.items():
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.add((name, i))
    return hits


class ReNarrowingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        idx = DocumentIndex()
        for name, text in DOCS.items():
            idx.add(name, text)
        cls.search = Search(SearchStore(index=idx))

    def test_matches_full_scan(self):
        for pattern in PATTERNS:
            with self.subTest(pattern=pattern):
                r = self.search.query(f'(re "{pattern}")')
                got = {(ln["document"], ln["line"]) for ln in r["lines"]}
                self.assertEqual(got, reference(pattern))

    def test_narrowing_run_choices(self):
        self.assertEqual(narrowing_run("SearchDocument"), "searchdocument")
        self.assertEqual(narrowing_run(r"\bdef \w+\("), "def")
        self.assertEqual(narrowing_run("raise (ValueError|NameError)"), "raise")
        self.assertEqual(narrowing_run("foo_bar\\.baz"), "foo_bar")
        self.assertEqual(narrowing_run("(?i)MULTI"), "multi")
        self.assertEqual(narrowing_run("(abc)+y"), "abc")
        self.assertIsNone(narrowing_run("."))
        self.assertIsNone(narrowing_run(""))
        self.assertIsNone(narrowing_run("ab"))
        self.assertIsNone(narrowing_run("1234"))
        self.assertIsNone(narrowing_run("(a|b)cd?"))
        self.assertEqual(narrowing_run("abc(?!xyz)"), "abc")  # a lookahead's literal is never required


if __name__ == "__main__":
    unittest.main()
