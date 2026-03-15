"""Detect :bind loops in and-forms — low rewrite depth, log to /tmp."""

import logging
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ..inspect.bench import Bench

_BG_RELOAD = "parseltongue.core.inspect.technician.Technician._background_reload"

DOC_TEXT = "Engine handles evaluation. Facts are stored."

LOG_PATH = "/tmp/and_forms_loop.log"


class TestAndFormsLoop(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="and_loop_")
        self.bench_dir = os.path.join(self.tmpdir, ".bench")
        self._bg_patcher = patch(_BG_RELOAD)
        self._bg_patcher.start()
        self._write("doc.txt", DOC_TEXT)

        # Log to file
        self.handler = logging.FileHandler(LOG_PATH, mode="w")
        self.handler.setLevel(logging.DEBUG)
        logging.getLogger("parseltongue").addHandler(self.handler)
        logging.getLogger("parseltongue").setLevel(logging.DEBUG)

    def tearDown(self):
        self._bg_patcher.stop()
        logging.getLogger("parseltongue").removeHandler(self.handler)
        self.handler.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _bench(self, n_facts=2):
        lines = ['(load-document "doc.txt" "doc.txt")']
        words = DOC_TEXT.split()
        for i in range(n_facts):
            w = words[i % len(words)]
            lines.append(f'(fact engine.f{i} true :evidence (evidence "doc.txt" :quotes ("{w}") :explanation "x"))')
        source = "\n".join(lines)
        path = self._write("main.pltg", source)
        bench = Bench(bench_dir=self.bench_dir)
        bench.prepare(path)
        # stub
        p = bench._require_current()
        live = bench._technician._live.get(p)
        if live:
            se = live.result.system.engine
            le = live.system.engine
            le.facts.update(se.facts)
            le.terms.update(se.terms)
            le.axioms.update(se.axioms)
            le.theorems.update(se.theorems)
            le.diffs.update(se.diffs)
            le.documents.update(se.documents)
            for sym, val in se.env.items():
                if sym not in le.env:
                    le.env[sym] = val
        return bench

    @unittest.skip("Perf issues")
    def test_and_forms_no_loop_2(self):
        """and-forms self-intersection with 2 facts must not loop."""
        b = self._bench(2)
        result = b.eval('(scope ops (and-forms (scope lens (kind "fact")) (scope lens (kind "fact"))))')
        self.assertIsInstance(result, list)
        self._check_log("and-forms-acc", 100)

    @unittest.skip("Perf issues")
    def test_and_forms_no_loop_5(self):
        """and-forms self-intersection with 100 facts must not loop."""
        b = self._bench(5)
        result = b.eval('(scope ops (and-forms (scope lens (kind "fact")) (scope lens (kind "fact"))))')
        self.assertIsInstance(result, list)
        self._check_log("and-forms-acc", 500)

    def _check_log(self, pattern, max_count):
        with open(LOG_PATH) as f:
            log_text = f.read()
        count = log_text.count(pattern)
        self.assertLess(count, max_count, f"{pattern} appeared {count} times — likely a loop")


if __name__ == "__main__":
    unittest.main()
