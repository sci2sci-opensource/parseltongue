"""A type error is a taint source.

A value of the wrong type taints whatever uses it, however well it is evidenced:
the visualisation marks the node as a source, says which type error made it one,
and propagates the taint to its consumers as it does for unverified evidence.
"""

import contextlib
import io
import json
import os
import re
import shutil
import unittest

from parseltongue.core.inspect.perspectives.visualisation.taints import compute_taints

VERIFIED = [{"status": "verified"}]


class TestTypeErrorsTaint(unittest.TestCase):
    def test_a_well_evidenced_node_with_a_type_error_is_a_source(self):
        items = [{"id": "a", "evidence": VERIFIED}, {"id": "b", "evidence": VERIFIED}]
        health = {"a": [{"category": "issue", "type": "type_error", "detail": "('a', 'true is Bool, expected Num')"}]}
        result = compute_taints(items, [{"source": "a", "target": "b", "type": "use"}], health=health)
        self.assertEqual(result.sources, {"a"})
        self.assertEqual(result.reasons["a"], "type error: true is Bool, expected Num")
        self.assertEqual(result.tainted, {"a", "b"})
        self.assertEqual(result.reasons["b"], "depends on tainted: a")

    def test_other_findings_do_not_make_a_source(self):
        items = [{"id": "a", "evidence": VERIFIED}]
        health = {"a": [{"category": "warning", "type": "vacuous_rule", "detail": "a"}]}
        self.assertEqual(compute_taints(items, [], health=health).sources, set())

    def test_without_health_only_evidence_decides(self):
        items = [{"id": "a", "evidence": VERIFIED}]
        self.assertEqual(compute_taints(items, []).sources, set())


TEST_DIR = "/tmp/type-error-taints-test"

_PGMD = """# Probe

```scheme
;; pltg Load
(defterm bad (+ 1 true))
(defterm uses-bad (+ bad 1))
```

Bad: [[term:bad]] end.
"""


class TestNotebookTaintsTypeErrors(unittest.TestCase):
    def test_the_notebook_page_names_the_type_error(self):
        from parseltongue.core.inspect.notebooks.render import render_pgmd

        shutil.rmtree(TEST_DIR, ignore_errors=True)
        os.makedirs(os.path.join(TEST_DIR, "notebooks"))
        path = os.path.join(TEST_DIR, "notebooks/p.pgmd")
        with open(path, "w") as f:
            f.write(_PGMD)
        cwd = os.getcwd()
        os.chdir(TEST_DIR)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                html = render_pgmd(path)
        finally:
            os.chdir(cwd)
            shutil.rmtree(TEST_DIR, ignore_errors=True)
        taints = json.loads(re.search(r"TAINT_DATA = (\{.*?\})\s*[;\n]", html).group(1))
        bad = next(n for n in taints["sources"] if n.endswith("bad") and not n.endswith("uses-bad"))
        self.assertTrue(taints["reasons"][bad].startswith("type error: "), taints["reasons"][bad])
        self.assertTrue(any(n.endswith("uses-bad") for n in taints["tainted"]))
        # The prose's ref carries the type error as its taint reason
        self.assertIn("nb-taint-source", html.split('id="notebook-container"', 1)[-1])


if __name__ == "__main__":
    unittest.main()
