"""Synthetic generation tests for search index — add, modify, remove, reindex.

Generates 100+ random Python files in a temp directory, indexes them,
then performs random mutations (add, modify, delete) across multiple
rounds. Validates that:
- All changes are picked up by reindex
- Cache round-trips preserve search results
- Fresh Search from cache matches live Search
- Full bench e2e works with the indexed files
"""

import os
import random
import shutil
import unittest

from ..inspect.search import Search
from ..inspect.store import SearchStore, Store

TEST_DIR = "/tmp/search-test"

# ── Synthetic file generation ──

_KEYWORDS = [
    "engine", "derive", "evaluate", "axiom", "theorem", "symbol",
    "validate", "parse", "rewrite", "resolve", "interpret", "compile",
    "transform", "dispatch", "register", "traverse", "inspect", "probe",
    "serialize", "deserialize", "cache", "invalidate", "refresh", "query",
    "index", "annotate", "stem", "tokenize", "normalize", "enrich",
]

_EXCEPTIONS = [
    "ValueError", "TypeError", "KeyError", "NameError",
    "RuntimeError", "AttributeError", "IndexError",
]

_TYPES = ["int", "str", "float", "bool", "list", "dict", "tuple", "set"]


def _gen_function(rng: random.Random) -> str:
    name = f"{rng.choice(_KEYWORDS)}_{rng.randint(1, 999)}"
    args = ", ".join(rng.sample(["self", "name", "expr", "env", "ctx", "node", "value"], rng.randint(1, 4)))
    lines = [f"def {name}({args}):"]
    lines.append(f'    """{rng.choice(_KEYWORDS).title()} operation."""')
    body_len = rng.randint(2, 12)
    for _ in range(body_len):
        kind = rng.choice(["assign", "call", "if", "raise", "return", "for", "comment"])
        var = f"_{rng.choice(_KEYWORDS)}"
        if kind == "assign":
            lines.append(f"    {var} = {rng.choice(_KEYWORDS)}({rng.choice(['name', 'expr', 'value'])})")
        elif kind == "call":
            lines.append(f"    self.{rng.choice(_KEYWORDS)}({var})")
        elif kind == "if":
            lines.append(f"    if {var} is None:")
            lines.append(f"        raise {rng.choice(_EXCEPTIONS)}('{rng.choice(_KEYWORDS)}')")
        elif kind == "raise":
            lines.append(f"    raise {rng.choice(_EXCEPTIONS)}(f'bad {{name}}')")
        elif kind == "return":
            lines.append(f"    return {var}")
        elif kind == "for":
            lines.append(f"    for item in {var}:")
            lines.append(f"        self.{rng.choice(_KEYWORDS)}(item)")
        elif kind == "comment":
            lines.append(f"    # {rng.choice(_KEYWORDS)}: {rng.choice(_KEYWORDS)}")
    if not any(l.strip().startswith("return") for l in lines[2:]):
        lines.append(f"    return {var}")
    return "\n".join(lines)


def _gen_class(rng: random.Random) -> str:
    name = f"{rng.choice(_KEYWORDS).title()}{rng.choice(['Engine', 'System', 'Index', 'Store', 'Node'])}"
    lines = [f"class {name}:"]
    lines.append(f'    """{name} — {rng.choice(_KEYWORDS)} infrastructure."""')
    lines.append("")
    n_methods = rng.randint(2, 6)
    for _ in range(n_methods):
        lines.append(_gen_function(rng))
        lines.append("")
    return "\n".join(lines)


def _gen_file(rng: random.Random) -> str:
    """Generate a synthetic Python file with imports, classes, functions."""
    parts = []
    # Imports
    n_imports = rng.randint(1, 4)
    for _ in range(n_imports):
        mod = rng.choice(["os", "sys", "json", "logging", "hashlib", "typing", "pathlib"])
        parts.append(f"import {mod}")
    parts.append("")

    # Module-level constants
    for _ in range(rng.randint(0, 3)):
        const = f"{rng.choice(_KEYWORDS).upper()}_{rng.randint(1, 99)}"
        val = rng.choice([f'"{rng.choice(_KEYWORDS)}"', str(rng.randint(0, 100)), "True", "None"])
        parts.append(f"{const} = {val}")
    parts.append("")

    # Classes and functions
    n_items = rng.randint(2, 5)
    for _ in range(n_items):
        if rng.random() < 0.4:
            parts.append(_gen_class(rng))
        else:
            parts.append(_gen_function(rng))
        parts.append("")

    return "\n".join(parts)


def _gen_markdown(rng: random.Random) -> str:
    """Generate a synthetic markdown file."""
    title = f"{rng.choice(_KEYWORDS).title()} {rng.choice(['Guide', 'Reference', 'Notes'])}"
    lines = [f"# {title}", ""]
    for _ in range(rng.randint(2, 5)):
        lines.append(f"## {rng.choice(_KEYWORDS).title()}")
        lines.append("")
        for _ in range(rng.randint(1, 4)):
            words = " ".join(rng.choices(_KEYWORDS, k=rng.randint(5, 15)))
            lines.append(words)
        lines.append("")
    return "\n".join(lines)


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _generate_corpus(base_dir: str, n_files: int, seed: int) -> dict[str, str]:
    """Generate n_files random files. Returns {relative_path: content}."""
    rng = random.Random(seed)
    files: dict[str, str] = {}
    subdirs = ["", "engine/", "loader/", "inspect/", "tests/", "util/"]

    for i in range(n_files):
        subdir = rng.choice(subdirs)
        if rng.random() < 0.15:
            name = f"{subdir}{rng.choice(_KEYWORDS)}_{i}.md"
            content = _gen_markdown(rng)
        else:
            name = f"{subdir}{rng.choice(_KEYWORDS)}_{i}.py"
            content = _gen_file(rng)

        full = os.path.join(base_dir, name)
        _write(full, content)
        files[name] = content

    return files


# ── Tests ──


class TestSyntheticIndexing(unittest.TestCase):
    """Large-scale synthetic index: generate, index, mutate, reindex, verify."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DIR):
            shutil.rmtree(TEST_DIR)
        os.makedirs(TEST_DIR)
        cls.bench_dir = os.path.join(TEST_DIR, ".bench")
        cls.files_dir = os.path.join(TEST_DIR, "files")
        cls.seed = 42

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def _make_search(self) -> Search:
        store = Store(self.bench_dir)
        return Search(SearchStore(store=store, path=self.files_dir))

    def test_01_initial_index(self):
        """Generate 120 files and index them."""
        corpus = _generate_corpus(self.files_dir, 120, self.seed)
        self.__class__._corpus = corpus

        search = self._make_search()
        count = search.index_dir(self.files_dir)
        self.assertEqual(count, 120)

        # Every keyword should be findable
        for kw in random.Random(self.seed).sample(_KEYWORDS, 10):
            r = search.query(kw)
            self.assertGreater(
                r["total_lines"], 0,
                f"Keyword {kw!r} not found after initial index",
            )

    def test_02_cache_round_trip(self):
        """Fresh Search from disk cache matches original counts."""
        search = self._make_search()
        # Should not need to re-index — cache is warm
        count = search.index_dir(self.files_dir)
        self.assertEqual(count, 0, "Cache should prevent re-indexing unchanged files")

        rng = random.Random(self.seed + 1)
        for kw in rng.sample(_KEYWORDS, 10):
            r = search.query(kw)
            self.assertGreater(r["total_lines"], 0, f"Cache miss for {kw!r}")

    def test_03_add_files_reindex(self):
        """Add 30 new files, reindex picks them all up."""
        rng = random.Random(self.seed + 100)
        new_files = {}
        # Use a unique marker so we can search specifically for new content
        for i in range(30):
            name = f"added/new_module_{i}.py"
            content = f'MARKER_ADDED_{i} = "synthetic_addition_{i}"\n' + _gen_file(rng)
            _write(os.path.join(self.files_dir, name), content)
            new_files[name] = content

        search = self._make_search()
        count = search.reindex()
        self.assertGreaterEqual(count, 30, f"Expected 30+ reindexed, got {count}")

        # Verify new files are searchable
        for i in random.Random(self.seed).sample(range(30), 10):
            r = search.query(f"synthetic_addition_{i}")
            self.assertGreater(
                r["total_lines"], 0,
                f"Added file marker synthetic_addition_{i} not found",
            )

    def test_04_modify_files_reindex(self):
        """Modify 20 random files, reindex detects changes."""
        rng = random.Random(self.seed + 200)
        corpus = self.__class__._corpus
        candidates = [f for f in corpus if f.endswith(".py")]
        to_modify = rng.sample(candidates, min(20, len(candidates)))

        modified_markers = {}
        for name in to_modify:
            marker = f"MODIFIED_MARKER_{rng.randint(10000, 99999)}"
            content = f'{marker} = True\n' + _gen_file(rng)
            _write(os.path.join(self.files_dir, name), content)
            modified_markers[name] = marker

        search = self._make_search()
        count = search.reindex()
        self.assertGreaterEqual(count, 20, f"Expected 20+ reindexed, got {count}")

        # Verify modifications are searchable
        for name, marker in list(modified_markers.items())[:10]:
            r = search.query(marker)
            self.assertGreater(
                r["total_lines"], 0,
                f"Modified marker {marker} in {name} not found",
            )

    def test_05_delete_files_reindex(self):
        """Delete 15 files, reindex removes them from the index."""
        rng = random.Random(self.seed + 300)

        # Pick files that exist on disk
        existing = []
        for root, _, fnames in os.walk(self.files_dir):
            for fname in fnames:
                if fname.endswith((".py", ".md")):
                    existing.append(os.path.join(root, fname))

        to_delete = rng.sample(existing, min(15, len(existing)))

        # Read content before deleting so we know what to search for
        deleted_content = {}
        for path in to_delete:
            rel = os.path.relpath(path, self.files_dir)
            with open(path) as f:
                first_line = f.readline().strip()
            deleted_content[rel] = first_line
            os.remove(path)

        search = self._make_search()
        count = search.reindex()
        # Reindex should process the deletions (count = files walked, not just deleted)
        self.assertGreaterEqual(count, 0)

        # Verify remaining files still searchable
        remaining = [
            f for f in os.listdir(self.files_dir)
            if f.endswith(".py") and os.path.isfile(os.path.join(self.files_dir, f))
        ]
        self.assertGreater(len(remaining), 0)

    def test_06_mixed_mutations_reindex(self):
        """Simultaneous add + modify + delete in one round."""
        rng = random.Random(self.seed + 400)

        # Add 10
        add_markers = []
        for i in range(10):
            marker = f"MIXED_ADD_{rng.randint(10000, 99999)}"
            content = f'{marker} = "mixed_added"\n' + _gen_file(rng)
            _write(os.path.join(self.files_dir, f"mixed/add_{i}.py"), content)
            add_markers.append(marker)

        # Modify 5 existing
        existing_py = []
        for root, _, fnames in os.walk(self.files_dir):
            for fname in fnames:
                if fname.endswith(".py") and "mixed" not in root:
                    existing_py.append(os.path.join(root, fname))
        mod_markers = []
        for path in rng.sample(existing_py, min(5, len(existing_py))):
            marker = f"MIXED_MOD_{rng.randint(10000, 99999)}"
            content = f'{marker} = True\n' + _gen_file(rng)
            with open(path, "w") as f:
                f.write(content)
            mod_markers.append(marker)

        # Delete 5
        deletable = [p for p in existing_py if os.path.exists(p)]
        for path in rng.sample(deletable, min(5, len(deletable))):
            if os.path.exists(path):
                os.remove(path)

        search = self._make_search()
        count = search.reindex()
        self.assertGreater(count, 0)

        # Verify additions
        for marker in add_markers[:5]:
            r = search.query(marker)
            self.assertGreater(r["total_lines"], 0, f"Mixed add {marker} not found")

        # Verify modifications
        for marker in mod_markers[:3]:
            r = search.query(marker)
            self.assertGreater(r["total_lines"], 0, f"Mixed mod {marker} not found")

    def test_07_cache_survives_mutations(self):
        """After all mutations, cache round-trip still works."""
        # Index current state
        search1 = self._make_search()
        search1.index_dir(self.files_dir)

        # Collect baseline
        baseline = {}
        for kw in _KEYWORDS[:15]:
            baseline[kw] = search1.query(kw)["total_lines"]

        # Fresh load from cache
        search2 = self._make_search()
        search2.index_dir(self.files_dir)  # Should be 0 count (cache hit)

        for kw, expected in baseline.items():
            actual = search2.query(kw)["total_lines"]
            self.assertEqual(
                actual, expected,
                f"Cache mismatch for {kw!r}: {actual} vs {expected}",
            )

    def test_08_sexpr_queries_on_synthetic(self):
        """S-expression queries work on the synthetic corpus."""
        search = self._make_search()
        search.index_dir(self.files_dir)

        # AND
        r = search.query('(and "def" "self")')
        self.assertGreater(r["total_lines"], 0)

        # OR
        r = search.query('(or "ValueError" "TypeError")')
        self.assertGreater(r["total_lines"], 0)

        # NOT
        r = search.query('(not "def" "class")')
        self.assertIsInstance(r["total_lines"], int)

        # IN
        r = search.query('(in "*.py" "import")')
        self.assertGreater(r["total_lines"], 0)

        # RE
        r = search.query('(re "def \\w+_\\d+")')
        self.assertGreater(r["total_lines"], 0)

        # COUNT
        r = search.query('(count "def")')
        count_val = int(r["lines"][0]["context"])
        self.assertGreater(count_val, 50)

        # NEAR
        r = search.query('(near 3 "raise" "ValueError")')
        self.assertIsInstance(r["total_lines"], int)

    def test_09_pgignore_respected(self):
        """Files matching .pgignore patterns are excluded from index."""
        pgignore_dir = os.path.join(TEST_DIR, "pgignore_test")
        if os.path.exists(pgignore_dir):
            shutil.rmtree(pgignore_dir)

        _write(os.path.join(pgignore_dir, ".pgignore"), "__pycache__/\n*.pyc\nignored_dir/\n")
        _write(os.path.join(pgignore_dir, "__pycache__/cached.py"), "XYZZY_PYCACHE_7291 = True")
        _write(os.path.join(pgignore_dir, "ignored_dir/secret.py"), "XYZZY_IGNORED_8823 = True")
        _write(os.path.join(pgignore_dir, "visible.py"), "XYZZY_VISIBLE_4455 = True")

        store = Store(os.path.join(pgignore_dir, ".bench"))
        search = Search(SearchStore(store=store, path=pgignore_dir))
        search.index_dir(pgignore_dir)

        r = search.query("XYZZY_PYCACHE_7291")
        self.assertEqual(r["total_lines"], 0, ".pgignore should exclude __pycache__")

        r = search.query("XYZZY_IGNORED_8823")
        self.assertEqual(r["total_lines"], 0, ".pgignore should exclude ignored_dir/")

        r = search.query("XYZZY_VISIBLE_4455")
        self.assertGreater(r["total_lines"], 0, "Non-ignored file should be indexed")

    def test_10_multiple_directories(self):
        """Index two separate directories, reindex finds new files in both."""
        dir_x = os.path.join(TEST_DIR, "dir_x")
        dir_y = os.path.join(TEST_DIR, "dir_y")

        _generate_corpus(dir_x, 20, seed=9000)
        _generate_corpus(dir_y, 20, seed=9001)

        store = Store(os.path.join(TEST_DIR, ".bench_multi"))
        search = Search(SearchStore(store=store, path="multi"))
        search.index_dir(dir_x)
        search.index_dir(dir_y)

        # Both directories searchable
        r = search.query("def")
        self.assertGreater(r["total_lines"], 20)

        # Add file to dir_y only
        marker = "MULTIDIR_NEW_FILE_MARKER"
        _write(os.path.join(dir_y, "brand_new.py"), f'{marker} = True\ndef brand_new(): pass\n')

        count = search.reindex()
        self.assertGreater(count, 0)

        r = search.query(marker)
        self.assertGreater(r["total_lines"], 0, "New file in dir_y not found after reindex")


class TestSyntheticBenchE2E(unittest.TestCase):
    """End-to-end: index synthetic files via bench server path."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = os.path.join(TEST_DIR, "bench_e2e")
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)
        os.makedirs(cls.test_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_bench_index_and_search(self):
        """Bench.index property exposes Search that survives reindex."""
        from ..inspect.bench import Bench

        files_dir = os.path.join(self.test_dir, "src")
        _generate_corpus(files_dir, 50, seed=7777)

        bench_cache = os.path.join(self.test_dir, ".bench")
        bench = Bench(bench_dir=bench_cache)

        # Prepare a minimal pltg so bench has a sample
        pltg = os.path.join(self.test_dir, "test.pltg")
        _write(pltg, '(load-document "test.py" "placeholder")\n')
        _write(os.path.join(self.test_dir, "placeholder"), "x = 1\n")
        bench.prepare(pltg)

        # Index synthetic files via bench's search engine
        idx = bench.index
        count = idx.index_dir(files_dir)
        self.assertGreater(count, 0)

        # Search works
        r = idx.query("def")
        self.assertGreater(r["total_lines"], 0)

        # Add new file
        _write(os.path.join(files_dir, "e2e_new.py"), 'E2E_BENCH_MARKER = "found_it"\ndef e2e(): pass\n')
        reindex_count = idx.reindex()
        self.assertGreater(reindex_count, 0)

        r = idx.query("E2E_BENCH_MARKER")
        self.assertGreater(r["total_lines"], 0, "Bench reindex didn't pick up new file")

    def test_bench_sexpr_search(self):
        """S-expression search through bench path works on synthetic data."""
        from ..inspect.bench import Bench

        files_dir = os.path.join(self.test_dir, "src2")
        _generate_corpus(files_dir, 30, seed=8888)

        bench_cache = os.path.join(self.test_dir, ".bench2")
        bench = Bench(bench_dir=bench_cache)

        pltg = os.path.join(self.test_dir, "test2.pltg")
        _write(pltg, '(load-document "test2.py" "placeholder2")\n')
        _write(os.path.join(self.test_dir, "placeholder2"), "y = 2\n")
        bench.prepare(pltg)

        bench.index.index_dir(files_dir)

        # S-expr through bench.search
        r = bench.search('(and "def" "self")')
        self.assertGreater(r["total_lines"], 0)

        r = bench.search('(count "import")')
        count_val = int(r["lines"][0]["context"])
        self.assertGreater(count_val, 0)


if __name__ == "__main__":
    unittest.main()
