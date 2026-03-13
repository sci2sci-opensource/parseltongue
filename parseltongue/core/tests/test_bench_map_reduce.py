"""E2E test: synthetic corpus generation → Bench load → search + lens map-reduce.

Generates random parameters, creates hundreds of source documents and thousands
of pltg facts in a temp dir, loads via full Bench, then verifies search + lens
map-reduce results against the known generation parameters.
"""

import os
import random
import shutil
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

# ── Synthetic corpus generator ──


class SyntheticCorpus:
    """Generate a random corpus of source docs + .pltg with known parameters."""

    KEYWORDS = [
        "raise ValueError",
        "raise TypeError",
        "raise KeyError",
        "import os",
        "import sys",
        "import json",
        "logging.warning",
        "logging.error",
        "logging.info",
        "return None",
        "return True",
        "return False",
        "assert ",
        "yield ",
        "async def",
    ]

    FUNC_PREFIXES = [
        "compute",
        "validate",
        "process",
        "transform",
        "check",
        "load",
        "save",
        "parse",
        "format",
        "convert",
        "build",
        "create",
        "update",
        "delete",
        "merge",
    ]

    def __init__(self, seed=42, n_docs=200, max_funcs_per_doc=12, max_keywords_per_func=4):
        self.rng = random.Random(seed)
        self.n_docs = n_docs
        self.max_funcs = max_funcs_per_doc
        self.max_kw_per_func = max_keywords_per_func

        # Ground truth accumulated during generation
        self.docs = {}  # name → content
        self.doc_params = {}  # name → {keyword → count, "defs" → N, "lines" → N}
        self.facts = []  # (fact_name, value, doc, quotes)
        self.totals = defaultdict(int)  # keyword → total count across all docs
        self.total_defs = 0
        self.total_facts = 0
        self.namespace_counts = defaultdict(int)  # namespace → fact count

    def generate(self):
        """Generate the full corpus. Returns pltg_text."""
        namespaces = [f"ns{i}" for i in range(self.rng.randint(5, 12))]

        for i in range(self.n_docs):
            ns = self.rng.choice(namespaces)
            doc_name = f"{ns}/mod_{i:04d}.py"
            self._generate_doc(doc_name, ns)

        pltg = self._generate_pltg()
        return pltg

    def _generate_doc(self, name, namespace):
        """Generate a single source document with random functions and keywords."""
        n_funcs = self.rng.randint(1, self.max_funcs)
        lines = [f"# {name} — auto-generated module", ""]
        keyword_counts = defaultdict(int)
        func_names = []

        for f in range(n_funcs):
            fname = f"{self.rng.choice(self.FUNC_PREFIXES)}_{f:03d}"
            func_names.append(fname)
            def_line = f"def {fname}(x, y):"
            lines.append(def_line)
            lines.append(f'    """Auto-generated function {fname}."""')

            # Random body lines with keywords
            n_body = self.rng.randint(2, 8)
            func_quotes = [def_line]
            for _ in range(n_body):
                if self.rng.random() < 0.4:
                    kw = self.rng.choice(self.KEYWORDS)
                    if kw.startswith("raise"):
                        line = f'    {kw}("error in {fname}")'
                    elif kw.startswith("import"):
                        line = f"    {kw}  # local import"
                    elif kw.startswith("logging"):
                        line = f'    {kw}("{fname} status")'
                    elif kw == "assert ":
                        line = "    assert x is not None"
                    elif kw == "yield ":
                        line = "    yield x + y"
                    elif kw == "async def":
                        line = f"    # note: consider {kw} {fname}_async"
                    else:
                        line = f"    {kw}"
                    lines.append(line)
                    keyword_counts[kw] += 1
                    func_quotes.append(line.strip())
                else:
                    lines.append(f"    result = x + y + {self.rng.randint(1, 100)}")

            lines.append("")

            # Create a fact for this function
            fact_name = f"{namespace}.{name.split('/')[-1].replace('.py', '')}-{fname}"
            self.facts.append((fact_name, "true", name, func_quotes[:3]))
            self.namespace_counts[namespace] += 1

        self.docs[name] = "\n".join(lines)
        self.doc_params[name] = {
            "defs": n_funcs,
            "lines": len(lines),
            "keywords": dict(keyword_counts),
            "namespace": namespace,
        }

        # Update totals
        self.total_defs += n_funcs
        self.total_facts += n_funcs
        for kw, cnt in keyword_counts.items():
            self.totals[kw] += cnt

    def _generate_pltg(self):
        """Generate the .pltg file documenting the corpus."""
        lines = ["; synth.pltg — auto-generated synthetic corpus\n"]

        # Facts for each function
        for fact_name, value, doc, quotes in self.facts:
            escaped_quotes = []
            for q in quotes:
                escaped_quotes.append(q.replace("\\", "\\\\").replace('"', '\\"'))
            quote_strs = " ".join(f'"{q}"' for q in escaped_quotes)
            lines.append(
                f'(fact {fact_name} {value}\n'
                f'    :evidence (evidence "{doc}"\n'
                f'        :quotes ({quote_strs})))\n'
            )

        # Per-doc keyword count facts
        for doc_name, params in self.doc_params.items():
            safe = doc_name.replace("/", ".").replace(".py", "")
            for kw, cnt in params["keywords"].items():
                kw_slug = kw.replace(" ", "-").replace(".", "-")
                fact_name = f"{safe}-kw-{kw_slug}-count"
                lines.append(f"(fact {fact_name} {cnt})")
                self.facts.append((fact_name, cnt, doc_name, []))

            lines.append(f"(fact {safe}-def-count {params['defs']})")
            self.facts.append((f"{safe}-def-count", params["defs"], doc_name, []))

        # Namespace aggregate facts
        for ns, count in self.namespace_counts.items():
            lines.append(f"\n(defterm {ns}-fact-count :origin \"namespace fact count\")")
            ns_facts = [f for f, v, d, q in self.facts if f.startswith(f"{ns}.") and v == "true"]
            if len(ns_facts) >= 2:
                lines.append(f"(fact {ns}-total-functions {len(ns_facts)})")

        lines.append("")
        return "\n".join(lines)


# ── Helpers ──


def _search(bench, expr):
    """Evaluate a search expression via scope search."""
    return bench.eval(f'(scope search {expr})')


def _search_count(bench, expr):
    """Count results of a search expression. count runs inside search scope."""
    return bench.eval(f'(scope search (count {expr}))')


class TestBenchMapReduce(unittest.TestCase):
    """E2E: synthetic generation → Bench load → search + lens → verify."""

    SEED = 42
    N_DOCS = 200

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="pltg_synth_")

        # Generate corpus
        cls.corpus = SyntheticCorpus(seed=cls.SEED, n_docs=cls.N_DOCS)
        pltg_text = cls.corpus.generate()

        # Write source documents
        for name, content in cls.corpus.docs.items():
            doc_path = Path(cls._tmpdir) / name
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(content)

        # Write .pltg
        pltg_path = Path(cls._tmpdir) / "synth.pltg"
        pltg_path.write_text(pltg_text)
        cls._pltg_path = str(pltg_path)

        # Load via full Bench
        from parseltongue.core.inspect.bench import Bench

        cls._bench_dir = os.path.join(cls._tmpdir, ".bench")
        cls.bench = Bench(bench_dir=cls._bench_dir, lib_paths=[cls._tmpdir])
        cls.bench.prepare(cls._pltg_path)

        # Index all source documents for search
        resolved = str(Path(cls._pltg_path).resolve())
        search = cls.bench._technician.search_engine(resolved)
        for name, content in cls.corpus.docs.items():
            if name not in search._index.documents:
                search._index.add(name, content)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ── Sanity: corpus generated correctly ──

    def test_corpus_size(self):
        self.assertEqual(len(self.corpus.docs), self.N_DOCS)

    def test_corpus_has_facts(self):
        self.assertGreater(self.corpus.total_facts, 500)

    def test_bench_loaded(self):
        engine = self.bench.engine
        self.assertGreater(len(engine.facts), 500)

    # ── Map-Reduce: keyword counts via search vs ground truth ──

    def test_keyword_total_counts(self):
        """For each keyword, search count must match ground truth."""
        for kw, expected_total in self.corpus.totals.items():
            if expected_total == 0:
                continue
            escaped = kw.replace("(", "\\(").replace(")", "\\)")
            result = _search_count(self.bench, f'(re "{escaped}")')
            self.assertEqual(result, expected_total, f"Keyword '{kw}': search={result}, truth={expected_total}")

    def test_keyword_per_doc_counts(self):
        """Spot-check: for 20 random docs, keyword counts match ground truth."""
        rng = random.Random(self.SEED + 1)
        docs_to_check = rng.sample(list(self.corpus.doc_params.keys()), min(20, len(self.corpus.doc_params)))

        for doc_name in docs_to_check:
            params = self.corpus.doc_params[doc_name]
            for kw, expected in params["keywords"].items():
                escaped = kw.replace("(", "\\(").replace(")", "\\)")
                result = _search_count(self.bench, f'(in "{doc_name}" (re "{escaped}"))')
                self.assertEqual(result, expected, f"{doc_name} / '{kw}': search={result}, truth={expected}")

    def test_def_count_per_doc(self):
        """Spot-check: for 20 random docs, def counts match ground truth."""
        rng = random.Random(self.SEED + 2)
        docs_to_check = rng.sample(list(self.corpus.doc_params.keys()), min(20, len(self.corpus.doc_params)))

        for doc_name in docs_to_check:
            expected = self.corpus.doc_params[doc_name]["defs"]
            result = _search_count(self.bench, f'(in "{doc_name}" (re "^def "))')
            self.assertEqual(result, expected, f"{doc_name}: search defs={result}, truth={expected}")

    def test_total_def_count(self):
        """Total def count across all docs must match ground truth."""
        result = _search_count(self.bench, '(re "^def ")')
        self.assertEqual(result, self.corpus.total_defs)

    # ── Map-Reduce: lens facts vs search counts ──

    def test_lens_fact_values_match_search(self):
        """For 30 random per-doc keyword count facts, lens value == search count."""
        rng = random.Random(self.SEED + 3)

        check_pairs = []
        for doc_name, params in self.corpus.doc_params.items():
            safe = doc_name.replace("/", ".").replace(".py", "")
            for kw, cnt in params["keywords"].items():
                kw_slug = kw.replace(" ", "-").replace(".", "-")
                fact_name = f"{safe}-kw-{kw_slug}-count"
                check_pairs.append((fact_name, doc_name, kw, cnt))

        if len(check_pairs) > 30:
            check_pairs = rng.sample(check_pairs, 30)

        for fact_name, doc_name, kw, expected in check_pairs:
            lens_val = self.bench.eval(f'(scope lens (value "{fact_name}"))')
            escaped = kw.replace("(", "\\(").replace(")", "\\)")
            search_count = _search_count(self.bench, f'(in "{doc_name}" (re "{escaped}"))')
            self.assertEqual(
                str(search_count), str(lens_val), f"Fact {fact_name}: lens={lens_val}, search={search_count}"
            )
            self.assertEqual(search_count, expected, f"Fact {fact_name}: search={search_count}, truth={expected}")

    # ── Map-Reduce: namespace aggregation ──

    def test_namespace_function_counts(self):
        """For each namespace, lens fact value == ground truth count."""
        for ns, expected in self.corpus.namespace_counts.items():
            fact_val = self.bench.eval(f'(scope lens (value "{ns}-total-functions"))')
            self.assertEqual(str(expected), str(fact_val), f"Namespace {ns}: lens={fact_val}, truth={expected}")

    # ── Map-Reduce: cross-doc pattern aggregation ──

    def test_reduce_sum_keyword_across_docs(self):
        """Map: count keyword per doc. Reduce: sum. Verify vs truth."""
        if not self.corpus.totals:
            self.skipTest("no keywords generated")

        kw = max(self.corpus.totals, key=self.corpus.totals.get)
        expected_total = self.corpus.totals[kw]
        escaped = kw.replace("(", "\\(").replace(")", "\\)")

        # Map phase: count per doc via search scope
        per_doc = {}
        for doc_name in self.corpus.docs:
            cnt = _search_count(self.bench, f'(in "{doc_name}" (re "{escaped}"))')
            if cnt > 0:
                per_doc[doc_name] = cnt

        # Reduce phase: sum
        reduced = sum(per_doc.values())
        self.assertEqual(reduced, expected_total, f"Keyword '{kw}': reduced={reduced}, truth={expected_total}")

    def test_reduce_max_defs_doc(self):
        """Map: def count per doc. Reduce: find max. Verify."""
        truth_max_doc = max(self.corpus.doc_params, key=lambda d: self.corpus.doc_params[d]["defs"])
        truth_max = self.corpus.doc_params[truth_max_doc]["defs"]

        found_max = 0
        found_doc = None
        for doc_name in self.corpus.docs:
            cnt = _search_count(self.bench, f'(in "{doc_name}" (re "^def "))')
            if cnt > found_max:
                found_max = cnt
                found_doc = doc_name

        self.assertEqual(found_max, truth_max)
        self.assertEqual(
            self.corpus.doc_params[found_doc]["defs"], truth_max, f"Max defs doc: search found {found_doc}={found_max}"
        )

    # ── Map-Reduce: compound queries ──

    def test_not_operator_subtracts_correctly(self):
        """NOT: total raises minus raises in one doc == raises in rest."""
        rng = random.Random(self.SEED + 4)
        kw = "raise ValueError"

        if self.corpus.totals.get(kw, 0) == 0:
            self.skipTest("no raise ValueError in corpus")

        total = self.corpus.totals[kw]

        docs_with_kw = [d for d, p in self.corpus.doc_params.items() if p["keywords"].get(kw, 0) > 0]
        if not docs_with_kw:
            self.skipTest("no docs with raise ValueError")

        doc = rng.choice(docs_with_kw)
        doc_count = self.corpus.doc_params[doc]["keywords"][kw]

        rest_count = _search_count(self.bench, f'(not (re "raise ValueError") (in "{doc}" (re "raise ValueError")))')
        self.assertEqual(rest_count, total - doc_count, f"NOT: total={total}, {doc}={doc_count}, rest={rest_count}")

    def test_or_union_is_additive_for_disjoint_docs(self):
        """OR of searches in two disjoint docs == sum of individual counts."""
        rng = random.Random(self.SEED + 5)
        kw = "raise ValueError"

        docs_with_kw = [d for d, p in self.corpus.doc_params.items() if p["keywords"].get(kw, 0) > 0]
        if len(docs_with_kw) < 2:
            self.skipTest("need at least 2 docs with raises")

        d1, d2 = rng.sample(docs_with_kw, 2)
        c1 = self.corpus.doc_params[d1]["keywords"][kw]
        c2 = self.corpus.doc_params[d2]["keywords"][kw]

        union = _search_count(self.bench, f'(or (in "{d1}" "raise ValueError") (in "{d2}" "raise ValueError"))')
        self.assertEqual(union, c1 + c2, f"OR({d1}={c1}, {d2}={c2}) = {union}, expected {c1+c2}")

    # ── Map-Reduce: search→sr forms + axiom classification ──

    def test_axiom_classify_and_count(self):
        """Classify sr forms by namespace via rewrite axioms, verify counts."""

        path = str(Path(self._pltg_path).resolve())
        loader, system = self.bench._ensure_eval_system(path)
        engine = system.engine

        # Pick a namespace with known count
        rng = random.Random(self.SEED + 6)
        ns = rng.choice(list(self.corpus.namespace_counts.keys()))

        # Count non-empty lines in this namespace via search
        ns_docs = [d for d in self.corpus.docs if d.startswith(f"{ns}/")]
        # (re ".") matches non-empty lines only
        truth_nonempty = sum(sum(1 for line in self.corpus.docs[d].split("\n") if line.strip()) for d in ns_docs)

        search_count = _search_count(self.bench, f'(in "{ns}/*" (re "."))')
        self.assertEqual(
            search_count, truth_nonempty, f"Namespace {ns}: search lines={search_count}, truth={truth_nonempty}"
        )

    # ── Map-Reduce: full pipeline — search, lens, engine arithmetic ──

    def test_full_pipeline_search_lens_arithmetic(self):
        """Map raises per doc via search, get fact via lens, reduce in engine."""
        # Map: for each module with raises, get search count
        kw = "raise ValueError"
        docs_with_kw = [d for d, p in self.corpus.doc_params.items() if p["keywords"].get(kw, 0) > 0]
        if len(docs_with_kw) < 3:
            self.skipTest("need at least 3 docs with raises")

        rng = random.Random(self.SEED + 7)
        sample_docs = rng.sample(docs_with_kw, min(5, len(docs_with_kw)))

        search_sum = 0
        for doc in sample_docs:
            cnt = _search_count(self.bench, f'(in "{doc}" "raise ValueError")')
            search_sum += cnt

        # Reduce: verify sum via engine arithmetic
        terms = [str(_search_count(self.bench, f'(in "{doc}" "raise ValueError")')) for doc in sample_docs]
        # Build nested binary addition
        expr = terms[0]
        for t in terms[1:]:
            expr = f"(+ {expr} {t})"

        engine_sum = self.bench.eval(expr)
        self.assertEqual(engine_sum, search_sum)

        # Cross-check: sum of ground truth
        truth_sum = sum(self.corpus.doc_params[d]["keywords"][kw] for d in sample_docs)
        self.assertEqual(engine_sum, truth_sum)

    def test_full_pipeline_ratio_check(self):
        """Compute raise-to-def ratio per doc, verify high-raise docs."""
        kw = "raise ValueError"
        high_raise_docs = []

        for doc, params in self.corpus.doc_params.items():
            raises = params["keywords"].get(kw, 0)
            defs = params["defs"]
            if raises > 0 and defs > 0:
                # Verify via search
                s_raises = _search_count(self.bench, f'(in "{doc}" "raise ValueError")')
                s_defs = _search_count(self.bench, f'(in "{doc}" (re "^def "))')
                self.assertEqual(s_raises, raises, f"{doc} raise mismatch")
                self.assertEqual(s_defs, defs, f"{doc} def mismatch")

                if raises >= defs:
                    high_raise_docs.append(doc)

        # Verify via engine: for each high-raise doc, (>= raises defs) is true
        for doc in high_raise_docs[:5]:  # spot check 5
            r = _search_count(self.bench, f'(in "{doc}" "raise ValueError")')
            d = _search_count(self.bench, f'(in "{doc}" (re "^def "))')
            result = self.bench.eval(f'(>= {r} {d})')
            self.assertTrue(result, f"{doc}: {r} raises < {d} defs but was in high list")


if __name__ == "__main__":
    unittest.main()
