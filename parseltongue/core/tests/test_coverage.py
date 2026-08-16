"""Coverage — typed measurements over verification state.

Not language: no directives, no grammar. Typed like Evidence — the type
ClassVar is decisive for the subtype shape; providers register per type
on the System (composition layer), not the engine.
"""

import unittest
from dataclasses import dataclass
from typing import ClassVar

from ..coverage import Coverage, CorpusClaimCoverage, QuoteRangeCoverage, _merge_ranges
from ..system import System, load_source


def _by_type(system, t):
    return [c for c in system.coverage() if c.type == t]


class TestQuoteRangeCoverage(unittest.TestCase):
    def _system(self):
        s = System()
        s.engine.register_document("paper", "alpha beta gamma delta epsilon")
        s.engine.register_document("unread", "nothing cites this text")
        load_source(
            s,
            '(fact a true :evidence (evidence "paper" :quotes ("alpha beta")))\n'
            '(fact b true :evidence (evidence "paper" :quotes ("beta gamma")))',
        )
        return s

    def test_overlapping_quotes_merge(self):
        rows = {c.document: c for c in _by_type(self._system(), "quote_range")}
        paper = rows["paper"]
        self.assertIsInstance(paper, QuoteRangeCoverage)
        # "alpha beta" and "beta gamma" overlap — union is "alpha beta gamma"
        self.assertEqual(paper.covered_chars, len("alpha beta gamma"))
        self.assertAlmostEqual(paper.fraction, paper.covered_chars / paper.total_chars)

    def test_unquoted_document_reports_zero(self):
        rows = {c.document: c for c in _by_type(self._system(), "quote_range")}
        self.assertEqual(rows["unread"].fraction, 0.0)
        self.assertIn("0%", rows["unread"].describe())

    def test_merge_ranges(self):
        self.assertEqual(_merge_ranges([(5, 9), (0, 4), (20, 30)]), [(0, 9), (20, 30)])


class TestCorpusClaimCoverage(unittest.TestCase):
    def test_grounded_claims_cover_scoped_docs(self):
        s = System()
        s.engine.register_document("src/auth.py", "import bcrypt")
        s.engine.register_document("docs/readme.md", "hello")
        load_source(s, '(fact no-md5 true :evidence (evidence "src" :absent (re "md5")))')
        rows = {c.document: c for c in _by_type(s, "corpus_claim")}
        self.assertIsInstance(rows["src/auth.py"], CorpusClaimCoverage)
        self.assertEqual(rows["src/auth.py"].claims, ("no-md5",))
        self.assertNotIn("docs/readme.md", rows)  # out of scope

    def test_ungrounded_claims_cover_nothing(self):
        s = System()  # no documents — claim refuses, so it covers nothing
        load_source(s, '(fact no-md5 true :evidence (evidence "src" :absent (re "md5")))')
        self.assertEqual(_by_type(s, "corpus_claim"), [])


@dataclass(frozen=True)
class _PathCoverage(Coverage):
    type: ClassVar[str] = "path"
    route: str

    def describe(self) -> str:
        return f"route {self.route}: visited"


class _PathProvider:
    type = "path"

    def measure(self, engine):
        return [_PathCoverage(route="/login")]


class TestProviderRegistry(unittest.TestCase):
    def test_constructor_injection(self):
        s = System(coverage_providers={"path": _PathProvider()})
        rows = _by_type(s, "path")
        self.assertEqual(rows[0].describe(), "route /login: visited")

    def test_late_registration_and_type_dispatch(self):
        s = System()
        s.register_coverage_provider("path", _PathProvider())
        row = _by_type(s, "path")[0]
        self.assertIsInstance(row, _PathCoverage)  # subclass IS the subtype
        self.assertIsInstance(row, Coverage)
        self.assertEqual(row.type, "path")  # string discriminator agrees


if __name__ == "__main__":
    unittest.main()
