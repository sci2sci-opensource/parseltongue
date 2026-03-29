"""Synthetic tests for parseltongue.core.inspect.config.

Generates random projects in /tmp, runs detection + init, validates pg.toml and .pgignore.
"""

import os
import random
import shutil
import tempfile
import tomllib
import unittest

from parseltongue.core.inspect.config import (
    _COMPOUND_EXTS,
    _EXT_TO_LANGS,
    _LANGUAGE_IGNORES,
    BASE_EXTENSIONS,
    BINARY_EXTENSIONS,
    DEFAULT_IGNORE,
    LANGUAGE_PRESETS,
    detect_languages,
    ensure_initialized,
    extensions_for,
    generate_pg_toml,
    generate_pgignore,
    init,
    is_initialized,
    load_config,
    load_extensions,
    load_ignore_patterns,
)

# All languages with at least one non-conflicting extension
ALL_LANGUAGES = sorted(LANGUAGE_PRESETS.keys())


def _make_project(root, languages, depth=1, files_per_lang=2, gitignore_lines=None):
    """Create a synthetic project with files for the given languages.

    Places files at varying depths. Optionally writes a .gitignore.
    """
    os.makedirs(root, exist_ok=True)
    created = []
    for lang in languages:
        exts = LANGUAGE_PRESETS.get(lang, [])
        if not exts:
            continue
        for i in range(files_per_lang):
            ext = exts[i % len(exts)]
            # Alternate between root and subdirs
            if depth > 0 and i % 2 == 1:
                subdir = os.path.join(root, f"src_{lang}")
                os.makedirs(subdir, exist_ok=True)
                path = os.path.join(subdir, f"file_{i}{ext}")
            else:
                path = os.path.join(root, f"file_{lang}_{i}{ext}")
            with open(path, "w") as f:
                f.write(f"// synthetic {lang} file\n")
            created.append(path)
    if gitignore_lines:
        with open(os.path.join(root, ".gitignore"), "w") as f:
            f.write("\n".join(gitignore_lines) + "\n")
    return created


class TestConfigDetection(unittest.TestCase):
    """Test language detection from file extensions."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pg_config_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_dir_defaults_to_python(self):
        langs = detect_languages(self.tmpdir)
        self.assertEqual(langs, ["python"])

    def test_single_language(self):
        for lang in ["python", "rust", "go", "java", "haskell", "elixir"]:
            d = os.path.join(self.tmpdir, lang)
            _make_project(d, [lang])
            detected = detect_languages(d)
            self.assertIn(lang, detected, f"{lang} not detected from its own files")

    def test_multi_language_project(self):
        langs = ["python", "typescript", "rust"]
        _make_project(self.tmpdir, langs)
        detected = detect_languages(self.tmpdir)
        for lang in langs:
            self.assertIn(lang, detected)

    def test_nested_files_detected(self):
        """Files one level deep should be detected."""
        subdir = os.path.join(self.tmpdir, "lib")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "main.go"), "w") as f:
            f.write("package main\n")
        detected = detect_languages(self.tmpdir)
        self.assertIn("go", detected)

    def test_dotdirs_skipped(self):
        """Files inside dotdirs should not be detected."""
        dotdir = os.path.join(self.tmpdir, ".hidden")
        os.makedirs(dotdir)
        with open(os.path.join(dotdir, "secret.rs"), "w") as f:
            f.write("fn main() {}\n")
        detected = detect_languages(self.tmpdir)
        self.assertNotIn("rust", detected)

    def test_junk_dirs_skipped(self):
        """node_modules, __pycache__ etc. should be skipped."""
        nm = os.path.join(self.tmpdir, "node_modules", "pkg")
        os.makedirs(nm)
        with open(os.path.join(nm, "index.js"), "w") as f:
            f.write("module.exports = {}\n")
        # Only the node_modules .js, no top-level js
        detected = detect_languages(self.tmpdir)
        self.assertNotIn("javascript", detected)

    def test_depth_limit(self):
        """Files beyond depth limit should not be detected."""
        deep = os.path.join(self.tmpdir, "a", "b", "c", "d")
        os.makedirs(deep)
        with open(os.path.join(deep, "deep.scala"), "w") as f:
            f.write("object Deep\n")
        detected = detect_languages(self.tmpdir, depth=2)
        self.assertNotIn("scala", detected)

    def test_all_languages_detectable(self):
        """Every language in LANGUAGE_PRESETS can be detected from its extensions."""
        for lang, exts in LANGUAGE_PRESETS.items():
            d = os.path.join(self.tmpdir, f"proj_{lang}")
            os.makedirs(d)
            for ext in exts[:1]:
                with open(os.path.join(d, f"file{ext}"), "w") as f:
                    f.write(f"// {lang}\n")
            detected = detect_languages(d)
            # Language should be detected (possibly along with others due to shared extensions)
            resolved = set()
            for ext in exts[:1]:
                resolved.update(_EXT_TO_LANGS.get(ext, []))
                for cext, clangs in _COMPOUND_EXTS:
                    if ext == cext:
                        resolved.update(clangs)
            self.assertTrue(
                resolved & set(detected),
                f"None of {resolved} detected for {lang} with extensions {exts[:1]}",
            )


class TestExtensionsFor(unittest.TestCase):
    """Test extension list building from language sets."""

    def test_always_includes_base(self):
        exts = extensions_for([])
        for base in BASE_EXTENSIONS:
            self.assertIn(base, exts)

    def test_includes_language_extensions(self):
        exts = extensions_for(["rust"])
        self.assertIn(".rs", exts)

    def test_deduplication(self):
        exts = extensions_for(["javascript", "typescript"])
        # .js appears in both but should appear once
        self.assertEqual(len(exts), len(set(exts)))

    def test_sorted(self):
        exts = extensions_for(["python", "rust", "go"])
        self.assertEqual(exts, sorted(exts))


class TestPgTomlGeneration(unittest.TestCase):
    """Test pg.toml generation and parsing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pg_config_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_toml(self):
        _make_project(self.tmpdir, ["python", "javascript"])
        content = generate_pg_toml(self.tmpdir)
        parsed = tomllib.loads(content)
        self.assertIn("detect", parsed)
        self.assertIn("index", parsed)
        self.assertIsInstance(parsed["detect"]["languages"], list)
        self.assertIsInstance(parsed["index"]["extensions"], list)

    def test_detected_languages_in_toml(self):
        _make_project(self.tmpdir, ["rust", "go"])
        parsed = tomllib.loads(generate_pg_toml(self.tmpdir))
        self.assertIn("rust", parsed["detect"]["languages"])
        self.assertIn("go", parsed["detect"]["languages"])

    def test_extensions_match_languages(self):
        langs = ["python", "haskell"]
        _make_project(self.tmpdir, langs)
        parsed = tomllib.loads(generate_pg_toml(self.tmpdir))
        exts = parsed["index"]["extensions"]
        self.assertIn(".py", exts)
        self.assertIn(".hs", exts)
        for base in BASE_EXTENSIONS:
            self.assertIn(base, exts)

    def test_random_language_combos(self):
        """Generate 20 random project combos and verify valid TOML."""
        rng = random.Random(42)
        for _ in range(20):
            k = rng.randint(1, 6)
            langs = rng.sample(ALL_LANGUAGES, min(k, len(ALL_LANGUAGES)))
            d = tempfile.mkdtemp(dir=self.tmpdir)
            _make_project(d, langs)
            content = generate_pg_toml(d)
            parsed = tomllib.loads(content)
            detected = parsed["detect"]["languages"]
            exts = parsed["index"]["extensions"]
            # Extensions should be non-empty and sorted
            self.assertTrue(len(exts) > 0)
            self.assertEqual(exts, sorted(exts))
            # Every detected language's extensions should be in the list
            for lang in detected:
                for ext in LANGUAGE_PRESETS.get(lang, []):
                    self.assertIn(ext, exts, f"{ext} missing for {lang}")


class TestPgIgnoreGeneration(unittest.TestCase):
    """Test .pgignore generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pg_config_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_always_has_header(self):
        content = generate_pgignore(self.tmpdir)
        self.assertIn(".git/", content)
        self.assertIn(".DS_Store", content)
        self.assertIn(".parseltongue-bench/", content)

    def test_absorbs_gitignore(self):
        gi_patterns = ["*.log", "dist/", "secret_dir/"]
        _make_project(self.tmpdir, ["python"], gitignore_lines=gi_patterns)
        content = generate_pgignore(self.tmpdir)
        self.assertIn("# From .gitignore", content)
        for pat in gi_patterns:
            self.assertIn(pat, content)

    def test_no_gitignore_no_section(self):
        _make_project(self.tmpdir, ["python"])
        content = generate_pgignore(self.tmpdir)
        self.assertNotIn("# From .gitignore", content)

    def test_language_ignores_included(self):
        _make_project(self.tmpdir, ["python"])
        content = generate_pgignore(self.tmpdir)
        self.assertIn("__pycache__/", content)

    def test_dedup_gitignore_vs_language(self):
        """If .gitignore already has __pycache__/, language section shouldn't duplicate."""
        _make_project(self.tmpdir, ["python"], gitignore_lines=["__pycache__/"])
        content = generate_pgignore(self.tmpdir)
        # Count occurrences — should appear exactly once in gitignore section
        lines = [li.strip() for li in content.splitlines() if li.strip() == "__pycache__/"]
        self.assertEqual(len(lines), 1, f"__pycache__/ appears {len(lines)} times")

    def test_multi_language_ignores(self):
        _make_project(self.tmpdir, ["python", "rust", "javascript"])
        content = generate_pgignore(self.tmpdir)
        self.assertIn("__pycache__/", content)
        self.assertIn("target/", content)
        self.assertIn("node_modules/", content)

    def test_random_projects_valid_pgignore(self):
        """20 random combos — pgignore should always be non-empty with header."""
        rng = random.Random(99)
        for _ in range(20):
            k = rng.randint(1, 8)
            langs = rng.sample(ALL_LANGUAGES, min(k, len(ALL_LANGUAGES)))
            d = tempfile.mkdtemp(dir=self.tmpdir)
            gi = rng.choice([None, ["*.tmp", "build/"]])
            _make_project(d, langs, gitignore_lines=gi)
            content = generate_pgignore(d)
            self.assertIn(".git/", content)
            self.assertIn(".parseltongue-bench/", content)
            # Every language-specific ignore that was expected should be present
            detected = detect_languages(d)
            for lang in detected:
                for pat in _LANGUAGE_IGNORES.get(lang, []):
                    self.assertIn(pat, content, f"{pat} missing for {lang} in pgignore")


class TestConfigLifecycle(unittest.TestCase):
    """Test the full init → load → ensure cycle."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pg_config_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_not_initialized_initially(self):
        self.assertFalse(is_initialized(self.tmpdir))

    def test_init_creates_both_files(self):
        _make_project(self.tmpdir, ["python"])
        result = init(self.tmpdir)
        self.assertTrue(result["toml_action"] == "created")
        self.assertTrue(result["pgignore_action"] == "created")
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "pg.toml")))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, ".pgignore")))
        self.assertTrue(is_initialized(self.tmpdir))

    def test_init_idempotent_without_force(self):
        _make_project(self.tmpdir, ["python"])
        init(self.tmpdir)
        result = init(self.tmpdir)
        self.assertEqual(result["toml_action"], "skipped")
        self.assertEqual(result["pgignore_action"], "skipped")

    def test_init_force_overwrites(self):
        _make_project(self.tmpdir, ["python"])
        init(self.tmpdir)
        # Corrupt the toml
        with open(os.path.join(self.tmpdir, "pg.toml"), "w") as f:
            f.write("garbage")
        result = init(self.tmpdir, toml_mode="force", pgignore_mode="force")
        self.assertEqual(result["toml_action"], "overwritten")
        # Should be valid again
        conf = load_config(self.tmpdir)
        self.assertIn("detect", conf)

    def test_init_append_adds_missing_patterns(self):
        _make_project(self.tmpdir, ["python"])
        # Create a minimal hand-written .pgignore
        with open(os.path.join(self.tmpdir, ".pgignore"), "w") as f:
            f.write("# my custom ignore\nvenv/\n")
        init(self.tmpdir)  # creates pg.toml, skips .pgignore
        # Now append — should add missing patterns without removing venv/
        result = init(self.tmpdir, pgignore_mode="append")
        self.assertEqual(result["pgignore_action"], "appended")
        content = open(os.path.join(self.tmpdir, ".pgignore")).read()
        self.assertIn("venv/", content)  # original preserved
        self.assertIn("__pycache__/", content)  # appended

    def test_init_append_noop_if_complete(self):
        _make_project(self.tmpdir, ["python"])
        init(self.tmpdir)  # creates both fully
        result = init(self.tmpdir, toml_mode="append", pgignore_mode="append")
        self.assertEqual(result["toml_action"], "unchanged")
        self.assertEqual(result["pgignore_action"], "unchanged")

    def test_ensure_initialized_creates_if_missing(self):
        _make_project(self.tmpdir, ["go"])
        self.assertFalse(is_initialized(self.tmpdir))
        ensure_initialized(self.tmpdir)
        self.assertTrue(is_initialized(self.tmpdir))

    def test_ensure_initialized_noop_if_exists(self):
        _make_project(self.tmpdir, ["python"])
        init(self.tmpdir)
        toml_mtime = os.path.getmtime(os.path.join(self.tmpdir, "pg.toml"))
        ensure_initialized(self.tmpdir)
        self.assertEqual(toml_mtime, os.path.getmtime(os.path.join(self.tmpdir, "pg.toml")))

    def test_load_config_returns_parsed(self):
        _make_project(self.tmpdir, ["rust"])
        init(self.tmpdir)
        conf = load_config(self.tmpdir)
        self.assertIn("rust", conf["detect"]["languages"])
        self.assertIn(".rs", conf["index"]["extensions"])

    def test_load_extensions_auto_inits(self):
        _make_project(self.tmpdir, ["elixir"])
        self.assertFalse(is_initialized(self.tmpdir))
        exts = load_extensions(self.tmpdir)
        self.assertTrue(is_initialized(self.tmpdir))
        self.assertIn(".ex", exts)

    def test_load_ignore_patterns_auto_inits(self):
        _make_project(self.tmpdir, ["python"])
        self.assertFalse(is_initialized(self.tmpdir))
        patterns = load_ignore_patterns(self.tmpdir)
        self.assertTrue(is_initialized(self.tmpdir))
        self.assertTrue(len(patterns) > len(DEFAULT_IGNORE))

    def test_load_ignore_patterns_includes_defaults(self):
        _make_project(self.tmpdir, ["python"])
        patterns = load_ignore_patterns(self.tmpdir)
        for pat in DEFAULT_IGNORE:
            self.assertIn(pat, patterns)


def _make_rich_project(root, rng, languages):
    """Create a realistic synthetic project with traps and noise.

    - Multiple files per language at varying depths
    - Trap directories (node_modules, __pycache__, .hidden, target, vendor)
    - Binary decoy files that should never be indexed
    - Varied .gitignore content (sometimes overlapping with language ignores)
    - Empty dirs, deeply nested dirs, dirs with mixed content
    """
    os.makedirs(root, exist_ok=True)
    created_source = []  # files that SHOULD be detected
    created_traps = []  # files that should NOT be detected

    # ── Source files at various depths ──
    subdirs = ["", "src", "lib", "pkg", os.path.join("src", "core"), os.path.join("lib", "internal")]
    for lang in languages:
        exts = LANGUAGE_PRESETS.get(lang, [])
        if not exts:
            continue
        n_files = rng.randint(1, 5)
        for i in range(n_files):
            ext = exts[i % len(exts)]
            subdir = rng.choice(subdirs[: rng.randint(1, len(subdirs))])
            d = os.path.join(root, subdir) if subdir else root
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"{lang}_{i}{ext}")
            with open(path, "w") as f:
                f.write(f"// {lang} source file {i}\n")
            created_source.append(path)

    # ── Trap: dotdirs with real-looking source files ──
    for dotdir in [".hidden", ".cache", ".config"]:
        if rng.random() > 0.5:
            trap_dir = os.path.join(root, dotdir)
            os.makedirs(trap_dir, exist_ok=True)
            for lang in rng.sample(languages, min(2, len(languages))):
                exts = LANGUAGE_PRESETS.get(lang, [])
                if exts:
                    path = os.path.join(trap_dir, f"trap{exts[0]}")
                    with open(path, "w") as f:
                        f.write("// should not be detected\n")
                    created_traps.append(path)

    # ── Trap: junk directories ──
    junk_dirs = ["node_modules", "__pycache__", "vendor", "target"]
    for junk in junk_dirs:
        if rng.random() > 0.6:
            junk_path = os.path.join(root, junk, "nested")
            os.makedirs(junk_path, exist_ok=True)
            for lang in rng.sample(languages, min(2, len(languages))):
                exts = LANGUAGE_PRESETS.get(lang, [])
                if exts:
                    path = os.path.join(junk_path, f"junk{exts[0]}")
                    with open(path, "w") as f:
                        f.write("// junk dir file\n")
                    created_traps.append(path)

    # ── Trap: binary decoys at root ──
    binary_exts = [".png", ".jpg", ".zip", ".exe", ".pyc", ".dll", ".so", ".woff2"]
    for bext in rng.sample(binary_exts, rng.randint(1, 4)):
        path = os.path.join(root, f"decoy{bext}")
        with open(path, "wb") as f:
            f.write(b"\x00\x01\x02\x03")
        created_traps.append(path)

    # ── Trap: deeply nested files beyond depth limit ──
    if rng.random() > 0.4:
        deep = os.path.join(root, "a", "b", "c", "d", "e")
        os.makedirs(deep, exist_ok=True)
        for lang in rng.sample(languages, min(1, len(languages))):
            exts = LANGUAGE_PRESETS.get(lang, [])
            if exts:
                path = os.path.join(deep, f"deep{exts[0]}")
                with open(path, "w") as f:
                    f.write("// too deep\n")
                created_traps.append(path)

    # ── .gitignore: mix of real patterns, some overlapping language ignores ──
    gi_lines = None
    if rng.random() > 0.3:
        gi_pool = [
            "*.tmp",
            "*.bak",
            "*.log",
            "logs/",
            "tmp/",
            "cache/",
            ".env",
            "*.secret",
            "credentials/",
            "*.key",
            "build/",
            "dist/",
            "out/",
            "coverage/",
            "*.min.js",
            "__pycache__/",
            "node_modules/",
            "target/",  # overlap with language ignores
            f"*.{rng.choice(['old', 'orig', 'backup'])}",
        ]
        gi_lines = rng.sample(gi_pool, rng.randint(2, 8))

    if gi_lines:
        with open(os.path.join(root, ".gitignore"), "w") as f:
            f.write("\n".join(gi_lines) + "\n")

    # ── Empty directories (shouldn't cause crashes) ──
    for empty in ["empty_dir", os.path.join("src", "empty_nested")]:
        if rng.random() > 0.7:
            os.makedirs(os.path.join(root, empty), exist_ok=True)

    return created_source, created_traps, gi_lines


class TestSyntheticRandomProjects(unittest.TestCase):
    """Large-scale random project generation and validation with traps."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pg_config_stress_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_150_random_projects(self):
        """Generate 150 random projects with traps, init each, validate roundtrip."""
        rng = random.Random(2024)
        total_source = 0
        total_traps = 0
        total_files = 0

        for i in range(150):
            k = rng.randint(1, 12)
            langs = rng.sample(ALL_LANGUAGES, min(k, len(ALL_LANGUAGES)))

            d = os.path.join(self.tmpdir, f"proj_{i}")
            source, traps, gi_lines = _make_rich_project(d, rng, langs)
            total_source += len(source)
            total_traps += len(traps)

            # Count actual files on disk
            for _, _, fnames in os.walk(d):
                total_files += len(fnames)

            # ── Init ──
            result = init(d)
            self.assertEqual(result["toml_action"], "created", f"proj_{i}: toml not created")
            self.assertEqual(result["pgignore_action"], "created", f"proj_{i}: pgignore not created")

            # ── pg.toml is valid TOML ──
            conf = load_config(d)
            self.assertIn("detect", conf, f"proj_{i}: no [detect] in pg.toml")
            self.assertIn("index", conf, f"proj_{i}: no [index] in pg.toml")

            # ── Extensions sorted and deduplicated ──
            exts = conf["index"]["extensions"]
            self.assertEqual(exts, sorted(exts), f"proj_{i}: extensions not sorted")
            self.assertEqual(len(exts), len(set(exts)), f"proj_{i}: duplicate extensions")

            # ── Base extensions always present ──
            for base in BASE_EXTENSIONS:
                self.assertIn(base, exts, f"proj_{i}: base ext {base} missing")

            # ── Every detected language's extensions are in the list ──
            for lang in conf["detect"]["languages"]:
                for ext in LANGUAGE_PRESETS.get(lang, []):
                    self.assertIn(ext, exts, f"proj_{i}: {ext} missing for {lang}")

            # ── Detection doesn't pick up dotdir/junk-dir languages ──
            detected_set = set(conf["detect"]["languages"])
            # Files ONLY in traps should not cause detection (unless also in source)
            source_langs = set()
            for lang in langs:
                for ext in LANGUAGE_PRESETS.get(lang, []):
                    for s in source:
                        if s.endswith(ext):
                            source_langs.add(lang)

            # ── .pgignore has defaults ──
            patterns = load_ignore_patterns(d)
            for pat in DEFAULT_IGNORE:
                self.assertIn(pat, patterns, f"proj_{i}: default ignore {pat} missing")

            # ── .gitignore absorbed if present ──
            if gi_lines:
                pgignore_text = open(os.path.join(d, ".pgignore")).read()
                self.assertIn("# From .gitignore", pgignore_text, f"proj_{i}: gitignore not absorbed")
                for gp in gi_lines:
                    self.assertIn(gp, pgignore_text, f"proj_{i}: gitignore pattern {gp} missing")

            # ── Language ignores present (deduped against gitignore) ──
            pgignore_text = open(os.path.join(d, ".pgignore")).read()
            pgignore_patterns = [
                li.strip() for li in pgignore_text.splitlines() if li.strip() and not li.strip().startswith("#")
            ]
            # No duplicate non-comment lines
            self.assertEqual(
                len(pgignore_patterns),
                len(set(pgignore_patterns)),
                f"proj_{i}: duplicate patterns in .pgignore",
            )

            # ── Idempotent ──
            result2 = init(d)
            self.assertEqual(result2["toml_action"], "skipped", f"proj_{i}: toml not skipped on second init")
            self.assertEqual(result2["pgignore_action"], "skipped", f"proj_{i}: pgignore not skipped on second init")

            # ── Force reinit produces valid output ──
            if i % 20 == 0:
                result3 = init(d, toml_mode="force", pgignore_mode="force")
                self.assertEqual(result3["toml_action"], "overwritten")
                conf3 = load_config(d)
                self.assertIn("detect", conf3)

        # Sanity: we actually generated meaningful volume
        self.assertGreater(total_source, 500, f"Only {total_source} source files across 150 projects")
        self.assertGreater(total_traps, 200, f"Only {total_traps} trap files across 150 projects")
        self.assertGreater(total_files, 1000, f"Only {total_files} total files across 150 projects")


class TestExtensionConflicts(unittest.TestCase):
    """Verify known extension conflicts are documented and handled."""

    KNOWN_CONFLICTS = {
        ".m": {"objc", "matlab"},
        ".v": {"v", "verilog"},
        ".pp": {"pascal", "puppet"},
    }

    def _all_ext_langs(self):
        """Merge simple + compound maps into one dict for conflict checking."""
        merged: dict[str, list[str]] = {}
        for ext, langs in _EXT_TO_LANGS.items():
            merged.setdefault(ext, []).extend(langs)
        for ext, langs in _COMPOUND_EXTS:
            merged.setdefault(ext, []).extend(langs)
        return merged

    def test_conflicts_mapped_correctly(self):
        """All known conflicting extensions map to their expected languages."""
        all_map = self._all_ext_langs()
        for ext, expected_langs in self.KNOWN_CONFLICTS.items():
            mapped = set(all_map.get(ext, []))
            self.assertTrue(
                expected_langs <= mapped,
                f"{ext}: expected {expected_langs} but got {mapped}",
            )

    def test_no_unexpected_conflicts(self):
        """Extensions claimed by >1 language should be in KNOWN_CONFLICTS."""
        all_map = self._all_ext_langs()
        for ext, langs in all_map.items():
            if len(langs) > 1:
                self.assertIn(
                    ext,
                    self.KNOWN_CONFLICTS,
                    f"{ext} claimed by {langs} — not in KNOWN_CONFLICTS, add it",
                )


class TestBinaryExtensions(unittest.TestCase):
    """Verify binary extensions don't overlap with language presets."""

    def test_no_overlap_with_presets(self):
        all_preset_exts = set()
        for exts in LANGUAGE_PRESETS.values():
            all_preset_exts.update(exts)
        overlap = all_preset_exts & BINARY_EXTENSIONS
        self.assertEqual(overlap, set(), f"Extensions in both presets and binary: {overlap}")


if __name__ == "__main__":
    unittest.main()
