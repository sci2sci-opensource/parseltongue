"""Viz health overlay — screen findings and coverage reach the rendered page."""

import unittest

from ..coverage import QuoteRangeCoverage
from ..inspect.perspectives.visualisation.renderer import VizRenderer, _render_app
from ..inspect.screen import Screen, ScreenItem


def _screen():
    return Screen(
        [
            ScreenItem("no-md5", "issue", "absence_violated", "fact", "f.pltg:3", "1 match(es) breach the claim"),
            ScreenItem("cited", "warning", "manually_verified", "fact", "f.pltg:9", "signed by user"),
            ScreenItem("orphan", "dangling", "dangling", "defterm", "f.pltg:12", None),
        ],
        consistent=False,
    )


class TestHealthIndex(unittest.TestCase):
    def test_findings_keyed_by_name_danglings_skipped(self):
        r = VizRenderer(screen=_screen())
        index = r._health_index()
        self.assertEqual(index["no-md5"][0]["category"], "issue")
        self.assertEqual(index["no-md5"][0]["type"], "absence_violated")
        self.assertEqual(index["cited"][0]["category"], "warning")
        self.assertNotIn("orphan", index)  # danglings are noise

    def test_no_screen_means_empty(self):
        self.assertEqual(VizRenderer()._health_index(), {})


class TestRenderedPage(unittest.TestCase):
    def test_health_and_coverage_blobs_substituted(self):
        health = VizRenderer(screen=_screen())._health_index()
        coverage = VizRenderer(coverage=[QuoteRangeCoverage("paper", 0.45, 10, 22)])._coverage_rows()
        html = _render_app([], "ln", "t", None, health=health, coverage=coverage)
        self.assertIn("const HEALTH_DATA = ", html)
        self.assertIn("absence_violated", html)
        self.assertIn("const COVERAGE_DATA = ", html)
        self.assertIn("45% quoted", html)

    def test_blobs_default_empty(self):
        html = _render_app([], "ln", "t", None)
        self.assertIn("const HEALTH_DATA = {}", html)
        self.assertIn("const COVERAGE_DATA = []", html)

    def test_health_view_and_search_shipped(self):
        html = _render_app([], "ln", "t", None)
        self.assertIn('id="health-view"', html)  # first-class view, not a drawer
        self.assertIn("'health'", html)  # registered in VIEW_BTNS
        self.assertIn("function renderHealth", html)
        self.assertIn("JSON.stringify(findings)", html)  # page search sees health
        self.assertIn("data-health", html)  # search suggestions carry health facets


class TestScreenScopeReachesNewTypes(unittest.TestCase):
    """The search language reaches absence/obligation findings via the screen scope."""

    def test_type_and_category_queries_match(self):
        from ..inspect.systems.screen import ScreenSearchSystem

        system = ScreenSearchSystem(_screen())
        by_type = system.evaluate('(type "absence_violated")')
        self.assertEqual(len(by_type), 1)
        issues = system.evaluate("(issues)")
        self.assertEqual(len(issues), 1)


if __name__ == "__main__":
    unittest.main()
