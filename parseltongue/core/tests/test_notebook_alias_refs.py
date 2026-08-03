"""Issue #20 — aliased inline refs in .pgmd notebooks.

An import alias valid in a pltg block must be valid in a prose ref:
[[fact:core.payoff-ss]] resolves like the bare and module-qualified
forms. Unresolved refs must fail loudly — red marker in the HTML, a
diagnostics box, and a stderr warning — never silent gray text.
"""

import contextlib
import io
import os
import shutil
import unittest

TEST_DIR = "/tmp/notebook-alias-refs-test"

_PLTG = '(fact payoff-ss 5 :origin "repro fact")\n'

_PGMD = """# Repro

```scheme
;; pltg Load
(import (quote ..analysis.coordination_core core))
```

Aliased ref: [[fact:core.payoff-ss]] end.
Bare ref: [[fact:payoff-ss]] end.
Qualified ref: [[fact:coordination_core.payoff-ss]] end.
"""


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestAliasedProseRefs(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TEST_DIR, ignore_errors=True)
        _write(os.path.join(TEST_DIR, "analysis/coordination_core.pltg"), _PLTG)
        self._cwd = os.getcwd()
        os.chdir(TEST_DIR)

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def _render(self, pgmd: str) -> tuple:
        from parseltongue.core.inspect.notebooks.render import render_pgmd

        _write(os.path.join(TEST_DIR, "notebooks/demo.pgmd"), pgmd)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            html = render_pgmd(os.path.join(TEST_DIR, "notebooks/demo.pgmd"))
        return html, err.getvalue()

    def test_alias_bare_and_qualified_refs_all_resolve(self):
        html, stderr = self._render(_PGMD)
        # No ref degrades to literal text — aliased included
        self.assertNotIn("fact:core.payoff-ss", html)
        self.assertNotIn("fact:payoff-ss", html)
        self.assertNotIn("fact:coordination_core.payoff-ss", html)
        self.assertNotIn("unresolved ref", stderr)
        # All three render as footnoted refs to the same canonical node
        self.assertEqual(html.count("nb-fn font-semibold"), 3)
        self.assertEqual(html.count('data-node="analysis.coordination_core.payoff-ss"') >= 3, True)

    def test_adjacent_run_displays_by_ref_type(self):
        """5-runs: silent collapse to one bracket; explicit values get commas; mixed extends."""
        extra = (
            "\nSilent run: end[[~fact:payoff-ss]][[~fact:payoff-ss]][[~fact:payoff-ss]]"
            "[[~fact:payoff-ss]][[~fact:payoff-ss]] done.\n"
            "\nExplicit run: [[fact:payoff-ss]][[fact:core.payoff-ss]][[fact:payoff-ss]]"
            "[[fact:core.payoff-ss]][[fact:payoff-ss]] done.\n"
            "\nMixed: [[fact:payoff-ss]][[~fact:payoff-ss]] done.\n"
        )
        html, _stderr = self._render(_PGMD + extra)
        import re

        def text_of(marker):
            raw = re.search(marker + r"(.*?) done", html, re.S).group(1)
            return re.sub(r"<[^>]+>", "", raw)  # visible text only — class attrs also carry brackets

        # Silent 5-run: one opening bracket, one closing, four ", " joins.
        silent_run = text_of(r"Silent run: end")
        self.assertEqual(silent_run.count("["), 1, silent_run)
        self.assertEqual(silent_run.count("]"), 1)
        self.assertEqual(silent_run.count(", "), 4)
        # Explicit 5-run: every value keeps its own [n]; four comma separators between spans.
        explicit_run = text_of(r"Explicit run: ")
        self.assertEqual(explicit_run.count("["), 5, explicit_run)
        raw_explicit = re.search(r"Explicit run: (.*?) done", html, re.S).group(1)
        self.assertEqual(len(re.findall(r"</span>, <span", raw_explicit)), 4)
        # Mixed: the value's bracket extends over the silent footnote — [n, m].
        mixed = text_of(r"Mixed: ")
        self.assertEqual(mixed.count("["), 1, mixed)
        self.assertEqual(mixed.count(", "), 1)

    def test_unresolved_ref_fails_loudly(self):
        html, stderr = self._render(_PGMD + "\nGhost ref: [[fact:ghost.nothing]] end.\n")
        self.assertIn("fact:ghost.nothing", html)  # rendered, but…
        self.assertIn("unresolved reference", html)  # …marked, with tooltip
        self.assertIn("reference problem(s)", html)  # …and listed in the diagnostics box
        self.assertIn("unresolved ref 'fact:ghost.nothing'", stderr)


if __name__ == "__main__":
    unittest.main()
