"""Typed values in .pgmd notebooks.

A record is shown in prose as its name, its type and its fields, the keywords
bare as the source writes them: ``primary-endpoint: PrimaryEndpoint (:level
primary ...)``. A hidden ref still shows only its footnote number, and a value
of any other type is shown as before.
"""

import contextlib
import io
import os
import re
import shutil
import unittest

TEST_DIR = "/tmp/notebook-typed-values-test"

_PGMD = """# Endpoints

```scheme
;; pltg Load
(deftype PrimaryEndpoint (Record :level Sym :measure Sym :timepoint Sym) :origin "the USDM endpoint")
(fact primary-endpoint (:level primary :measure pvr-change-from-baseline :timepoint week-25)
  :type PrimaryEndpoint :origin "protocol")
(fact secondary-endpoint (:level secondary :measure response-rate) :origin "protocol")
(fact enrolled 480 :origin "protocol")
```

Primary: [[fact:primary-endpoint]] end.
Secondary: [[fact:secondary-endpoint]] end.
Hidden: claim[[~fact:primary-endpoint]] end.
Count: [[fact:enrolled]] end.
"""


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _text(html: str) -> str:
    """The page's visible text: tags dropped, entities as written, without the taint marks (a fact with an
    :origin alone is a taint source, which this test does not look at)."""
    import html as html_mod

    return html_mod.unescape(re.sub(r"<[^>]+>", "", html)).replace("✖", "").replace("⚠", "")


class TestTypedValuesInProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from parseltongue.core.inspect.notebooks.render import render_pgmd

        shutil.rmtree(TEST_DIR, ignore_errors=True)
        _write(os.path.join(TEST_DIR, "notebooks/demo.pgmd"), _PGMD)
        cwd = os.getcwd()
        os.chdir(TEST_DIR)
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                cls.html = render_pgmd(os.path.join(TEST_DIR, "notebooks/demo.pgmd"))
            cls.stderr = err.getvalue()
        finally:
            os.chdir(cwd)
            shutil.rmtree(TEST_DIR, ignore_errors=True)
        cls.notebook = cls.html.split('id="notebook-container"', 1)[-1]
        cls.text = _text(cls.notebook)

    def line(self, start: str) -> str:
        found = re.search(re.escape(start) + r"(.*?) end\.", self.text)
        self.assertIsNotNone(found, f"no line starting {start!r}")
        return found.group(1).strip()

    def test_a_declared_record_shows_its_name_type_and_fields(self):
        self.assertEqual(
            self.line("Primary:"),
            "primary-endpoint: PrimaryEndpoint (:level primary :measure pvr-change-from-baseline :timepoint week-25)[1]",
        )

    def test_an_inferred_record_shows_as_a_record(self):
        self.assertEqual(
            self.line("Secondary:"), "secondary-endpoint: Record (:level secondary :measure response-rate)[2]"
        )

    def test_a_hidden_ref_shows_only_its_footnote(self):
        self.assertEqual(self.line("Hidden:"), "claim[1]")

    def test_a_value_of_another_type_shows_as_before(self):
        self.assertEqual(self.line("Count:"), "480[3]")

    def test_no_keyword_is_shown_quoted(self):
        self.assertNotIn('":level"', self.text)

    def test_the_footnote_gives_the_record_with_its_type(self):
        self.assertIn(
            "primary-endpoint: PrimaryEndpoint (:level primary :measure pvr-change-from-baseline :timepoint week-25)",
            _text(self.notebook.split("nb-footnote-list", 1)[-1]),
        )


if __name__ == "__main__":
    unittest.main()
