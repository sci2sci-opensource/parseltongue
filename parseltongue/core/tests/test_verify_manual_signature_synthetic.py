"""Synthetic end-to-end tests for verify_manual signature.

Creates real .pltg/.pgmd files under /tmp, loads through Bench,
renders screen and HTML notebook output, checks the strings.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from parseltongue.core.inspect.bench import Bench


class TestVerifyManualSignatureScreen(unittest.TestCase):
    """Full pipeline: .pltg files → Bench → screen summary → check strings."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="pltg_sig_test_"))
        self.bench_dir = self.tmpdir / ".parseltongue-bench"
        self.addCleanup(shutil.rmtree, str(self.tmpdir))

    def _write(self, name: str, content: str) -> Path:
        p = self.tmpdir / name
        p.write_text(content)
        return p

    def _screen(self, main_name: str = "main.pltg") -> str:
        bench = Bench(bench_dir=str(self.bench_dir))
        bench.prepare(str(self.tmpdir / main_name))
        dx = bench.evaluate()
        return dx.summary()

    def test_signature_in_screen(self):
        self._write(
            "main.pltg",
            """\
(fact threshold 60 :origin "business rule: gross margin > 60%")
(verify-manual (quote threshold) "Claude")
""",
        )
        self.assertIn("[Signed: Claude]", self._screen())

    def test_default_signature(self):
        self._write(
            "main.pltg",
            """\
(fact x 42 :origin "assumed")
(verify-manual (quote x))
""",
        )
        self.assertIn("[Signed: system]", self._screen())

    def test_origin_text_preserved(self):
        self._write(
            "main.pltg",
            """\
(fact margin-ok true :origin "VC standard: gross margin must exceed 60%")
(verify-manual (quote margin-ok) "Alice")
""",
        )
        summary = self._screen()
        self.assertIn("VC standard", summary)
        self.assertIn("[Signed: Alice]", summary)

    def test_multiple_signatures(self):
        self._write(
            "main.pltg",
            """\
(fact a 1 :origin "rule A")
(fact b 2 :origin "rule B")
(verify-manual (quote a) "Claude")
(verify-manual (quote b) "Alice")
""",
        )
        summary = self._screen()
        self.assertIn("[Signed: Claude]", summary)
        self.assertIn("[Signed: Alice]", summary)

    def test_review_file_import(self):
        self._write(
            "facts.pltg",
            """\
(fact revenue 5000000 :origin "memo says 5M")
(fact margin 0.65 :origin "business rule")
""",
        )
        self._write(
            "review.pltg",
            """\
(import (quote facts))
(verify-manual (quote facts.revenue) "Claude")
(verify-manual (quote facts.margin) "Alice")
""",
        )
        self._write(
            "main.pltg",
            """\
(import (quote facts))
(import (quote review))
""",
        )
        summary = self._screen()
        self.assertIn("[Signed: Claude]", summary)
        self.assertIn("[Signed: Alice]", summary)

    def test_axiom_signature(self):
        self._write(
            "main.pltg",
            """\
(defterm healthy :origin "business rule predicate")
(axiom margin-ok (> ?m 0.6) :origin "business rule: margin > 60%")
(verify-manual (quote margin-ok) "Claude")
(verify-manual (quote healthy) "Claude")
""",
        )
        summary = self._screen()
        self.assertIn("[Signed: Claude]", summary)
        self.assertIn("margin-ok", summary)


class TestVerifyManualSignatureNotebookRender(unittest.TestCase):
    """Full pipeline: .pgmd files → render_pgmd → HTML → check strings."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="pgmd_sig_test_"))
        self.addCleanup(shutil.rmtree, str(self.tmpdir))

    def _write(self, name: str, content: str) -> Path:
        p = self.tmpdir / name
        p.write_text(content)
        return p

    def _render(self, pgmd_name: str) -> str:
        from parseltongue.core.inspect.notebooks.render import render_pgmd

        return render_pgmd(self.tmpdir / pgmd_name)

    def test_signature_in_rendered_html(self):
        self._write(
            "notebook.pgmd",
            """\
# Test

```scheme
;; pltg Facts
(fact threshold 60 :origin "business rule: gross margin > 60%")
(verify-manual (quote threshold) "Claude")
```

Threshold is [[fact:threshold]].
""",
        )
        html = self._render("notebook.pgmd")
        self.assertIn("[Signed: Claude]", html)

    def test_origin_in_rendered_html(self):
        self._write(
            "notebook.pgmd",
            """\
# Test

```scheme
;; pltg Facts
(fact x 42 :origin "VC standard: must exceed threshold")
(verify-manual (quote x) "Alice")
```

Value is [[fact:x]].
""",
        )
        html = self._render("notebook.pgmd")
        self.assertIn("VC standard", html)
        self.assertIn("[Signed: Alice]", html)

    def test_review_file_in_notebook(self):
        self._write(
            "facts.pltg",
            """\
(fact revenue 5000000 :origin "memo says 5M")
""",
        )
        self._write(
            "review-notebook.pltg",
            """\
(import (quote facts))
(verify-manual (quote facts.revenue) "Claude")
""",
        )
        self._write(
            "notebook.pgmd",
            """\
# Report

```scheme
;; pltg Load
(import (quote facts))
(import (quote review-notebook))
```

Revenue: $[[fact:facts.revenue]].
""",
        )
        html = self._render("notebook.pgmd")
        self.assertIn("[Signed: Claude]", html)

    def test_no_output_node_in_html(self):
        """__output__ synthetic node should not appear in rendered notebook."""
        self._write(
            "notebook.pgmd",
            """\
# Test

```scheme
;; pltg Facts
(fact x 42 :origin "test")
```

Value: [[fact:x]].
""",
        )
        html = self._render("notebook.pgmd")
        self.assertNotIn("__output__", html)

    def test_default_signature_in_html(self):
        self._write(
            "notebook.pgmd",
            """\
# Test

```scheme
;; pltg Facts
(fact x 42 :origin "assumed")
(verify-manual (quote x))
```

X is [[fact:x]].
""",
        )
        html = self._render("notebook.pgmd")
        self.assertIn("[Signed: system]", html)


if __name__ == "__main__":
    unittest.main()
