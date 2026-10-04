"""A corpus cache in the previous (v1, JSON) layout is the operator's data.

Contract pinned here:

- Starting on a v1 cache changes NOTHING on disk: every cache file is byte-
  identical after load, after queries, and after a background flush.
- The v1 cache is served: the corpus is searchable, straight from the old
  files, with the same answers a fresh index gives.
- Only an explicit choice touches the files — convert / migrate / rebuild —
  and each does exactly what it says; keep does nothing.
- An unreadable cache is never deleted either.
"""

import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path

from ..inspect.legacy import detect_legacy
from ..inspect.pgz import json_pgz_write, pgz_payload_kind, pgz_write
from ..inspect.search import Search
from ..inspect.store import SearchStore, Store
from ..quote_verifier.config import QuoteVerifierConfig
from ..quote_verifier.index import _content_hash
from ..quote_verifier.normalizer import normalize_with_mapping
from ..search_engine.stemmer import stem

TEST_DIR = "/tmp/legacy-cache-test"
FILES = {
    "alpha.py": "def alpha():\n    return ALPHA_VALUE\n\nclass Alpha:\n    pass\n",
    "beta.py": "import alpha\n\nBETA = alpha.ALPHA_VALUE + 1\n# neural networks here\n",
    "sub/gamma.py": "def gamma(x):\n    return x * 2  # gamma doubles\n\nneural networks again\n",
    # Empty files are documents too — the previous version indexed them.
    "sub/__init__.py": "",
}


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _snapshot(bench_dir: str) -> dict[str, str]:
    """name → sha256 of every file in the bench dir."""
    out = {}
    for p in sorted(Path(bench_dir).iterdir()):
        out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ── v1 fixture writer — the exact layout the previous version persisted ──


def _v1_indexed_document(name: str, text: str) -> dict:
    cfg = QuoteVerifierConfig()
    normalized, pos_map, _ = normalize_with_mapping(text, cfg)
    word_positions: dict[str, list[int]] = {}
    i, n = 0, len(normalized)
    while i < n:
        while i < n and normalized[i] == " ":
            i += 1
        if i >= n:
            break
        start = i
        while i < n and normalized[i] != " ":
            i += 1
        word_positions.setdefault(normalized[start:i], []).append(start)
    collapsed = [(c, k) for k, c in enumerate(normalized) if c != " "]
    return {
        "name": name,
        "normalized_text": normalized,
        "position_map": pos_map,
        "content_hash": _content_hash(text),
        "word_positions": word_positions,
        "collapsed_text": "".join(c for c, _ in collapsed),
        "collapsed_to_norm": [k for _, k in collapsed],
    }


def _v1_search_document(name: str, text: str, idoc: dict) -> dict:
    lines = text.splitlines()
    line_starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    word_to_lines: dict[str, set[int]] = {}
    stem_to_lines: dict[str, set[int]] = {}
    per_line: dict[int, list[str]] = {}
    pm = idoc["position_map"]
    import re as _re

    compound = _re.compile(r"[._\-]+")
    for word, positions in idoc["word_positions"].items():
        for p in positions:
            ln = line_of(pm[p] if p < len(pm) else 0)
            word_to_lines.setdefault(word, set()).add(ln)
            stem_to_lines.setdefault(stem(word), set()).add(ln)
            # The previous version also indexed compound parts ("a_b" → "a", "b").
            parts = compound.split(word)
            if len(parts) > 1:
                for part in parts:
                    if part:
                        word_to_lines.setdefault(part, set()).add(ln)
                        stem_to_lines.setdefault(stem(part), set()).add(ln)
            per_line.setdefault(ln, []).append((p, word))
    line_tokens = [[ln, [w for _, w in sorted(ws)]] for ln, ws in sorted(per_line.items())]
    bigrams: dict[str, set[int]] = {}
    for ln, toks in line_tokens:
        for a, b in zip(toks, toks[1:]):
            bigrams.setdefault(f"{a}\x00{b}", set()).add(ln)
    return {
        "name": name,
        "content_hash": idoc["content_hash"],
        "lines": lines,
        "line_ranges": [
            [s, max(s, (line_starts[i + 1] - 2) if i + 1 < len(line_starts) else len(text) - 1)]
            for i, s in enumerate(line_starts)
        ],
        "word_to_lines": {k: sorted(v) for k, v in word_to_lines.items()},
        "stem_to_lines": {k: sorted(v) for k, v in stem_to_lines.items()},
        "line_tokens": line_tokens,
        "ngram_index": {"bigrams": {k: sorted(v) for k, v in bigrams.items()}, "trigrams": {}},
        "meta": {
            "token_meta": {},
            "word_meta": {},
            "line_meta": {},
            "doc_meta": [{"key": "name", "value": name, "weight": 10.0, "text": f"Found document {name}"}],
        },
    }


def write_v1_caches(store: Store, key: str, directory: str, files: dict[str, str]):
    """Persist *files* as a complete v1 cache set: idx (JSON), six (JSON), texts."""
    idocs = {name: _v1_indexed_document(name, text) for name, text in files.items()}
    sdocs = {name: _v1_search_document(name, text, idocs[name]) for name, text in files.items()}
    hashes = {name: d["content_hash"] for name, d in idocs.items()}
    idx_payload = {
        "directory": directory,
        "file_hashes": dict(hashes),
        "index": {"documents": idocs, "hashes": hashes},
        "indexed_dirs": {directory: [".py"]},
        "file_stats": {},
        "dir_mtimes": {},
    }
    corpus_words: dict[str, dict[str, list[int]]] = {}
    corpus_stems: dict[str, dict[str, list[int]]] = {}
    for name, sd in sdocs.items():
        for w, ls in sd["word_to_lines"].items():
            corpus_words.setdefault(w, {})[name] = ls
        for s, ls in sd["stem_to_lines"].items():
            corpus_stems.setdefault(s, {})[name] = ls
    six_payload = {
        "documents": sdocs,
        "corpus_stems": corpus_stems,
        "corpus_words": corpus_words,
        "stem_df": {s: len(d) for s, d in corpus_stems.items()},
        "name_stems": {},
        "doc_lengths": {name: sum(len(v) for v in sd["word_to_lines"].values()) for name, sd in sdocs.items()},
        "avgdl": 1.0,
    }
    store._ensure_dir()
    json_pgz_write(store._index_cache_path(key), idx_payload)
    json_pgz_write(store._search_index_cache_path(key), six_payload)
    store.save_texts(key, dict(files))


class LegacyCacheBase(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DIR):
            shutil.rmtree(TEST_DIR)
        os.makedirs(TEST_DIR)
        _write(os.path.join(TEST_DIR, "pg.toml"), '[detect]\nlanguages = ["python"]\n[index]\nextensions = [".py"]\n')
        _write(os.path.join(TEST_DIR, ".pgignore"), "")
        for rel, text in FILES.items():
            _write(os.path.join(TEST_DIR, rel), text)
        self.bench_dir = os.path.join(TEST_DIR, ".bench")
        self.store = Store(self.bench_dir)
        write_v1_caches(self.store, TEST_DIR, TEST_DIR, FILES)
        self.before = _snapshot(self.bench_dir)
        self._cwd = os.getcwd()
        os.chdir(TEST_DIR)

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def _search(self) -> Search:
        return Search(SearchStore(store=Store(self.bench_dir), path=TEST_DIR))

    def _v1_names(self) -> tuple[str, str]:
        return self.store._index_cache_path(TEST_DIR).name, self.store._search_index_cache_path(TEST_DIR).name


class TestDetection(LegacyCacheBase):
    def test_payload_kind_distinguishes_layouts(self):
        idx, six = self._v1_names()
        self.assertEqual(pgz_payload_kind(Path(self.bench_dir) / idx), "json")
        self.assertEqual(pgz_payload_kind(Path(self.bench_dir) / six), "json")
        other = Path(self.bench_dir) / "x.pgz"
        pgz_write(other, b"not json, not blob")
        self.assertEqual(pgz_payload_kind(other), "unknown")

    def test_detect_reports_files_and_head_without_touching_them(self):
        legacy = detect_legacy(
            self.store._index_cache_path(TEST_DIR), self.store._search_index_cache_path(TEST_DIR), TEST_DIR
        )
        self.assertIsNotNone(legacy)
        self.assertEqual(legacy.directory, TEST_DIR)
        self.assertEqual(legacy.documents, len(FILES))
        self.assertEqual(len(legacy.files), 2)
        self.assertEqual(_snapshot(self.bench_dir), self.before)
        text = "\n".join(legacy.describe())
        for choice in ("pg cache convert", "pg cache migrate", "pg cache rebuild", "pg cache keep"):
            self.assertIn(choice, text)


class TestStartIsReadOnly(LegacyCacheBase):
    """Nothing in the cache directory changes unless the operator chose."""

    def test_start_serves_the_v1_corpus_and_changes_no_file(self):
        search = self._search()
        self.assertIsNotNone(search.legacy_cache)
        self.assertEqual(len(search._index.documents), len(FILES))
        self.assertGreater(search.query("ALPHA_VALUE")["total_lines"], 0)
        self.assertGreater(search.query("neural networks")["total_lines"], 0)
        self.assertEqual(_snapshot(self.bench_dir), self.before)

    def test_reindex_and_flush_are_held_while_v1_is_on_disk(self):
        search = self._search()
        # A real change on disk: it becomes searchable, but no cache is written.
        _write(os.path.join(TEST_DIR, "delta.py"), "DELTA_TOKEN = 4\n")
        search.reindex()
        self.assertGreater(search.query("DELTA_TOKEN")["total_lines"], 0)
        search._store.flush_pending_save()
        search._store.save_search_index(search._system._search_index)
        self.assertEqual(_snapshot(self.bench_dir), self.before)
        self.assertIsNotNone(search._store._pending_save)

    def test_keep_changes_nothing(self):
        search = self._search()
        self.assertIn("Kept", search.cache_choice("keep"))
        self.assertIsNotNone(search.legacy_cache)
        self.assertEqual(_snapshot(self.bench_dir), self.before)

    def test_unknown_choice_changes_nothing(self):
        search = self._search()
        self.assertIn("Unknown choice", search.cache_choice("discard"))
        self.assertEqual(_snapshot(self.bench_dir), self.before)

    def test_unreadable_cache_is_left_in_place(self):
        idx, six = self._v1_names()
        for name in (idx, six):
            pgz_write(Path(self.bench_dir) / name, b"garbage payload")
        before = _snapshot(self.bench_dir)
        search = self._search()
        self.assertIsNone(search.legacy_cache)
        self.assertEqual(len(search._index.documents), 0)
        self.assertEqual(_snapshot(self.bench_dir), before)


class TestServedEqualsFresh(LegacyCacheBase):
    def test_v1_answers_match_a_fresh_index(self):
        """Served-from-v1 answers equal a fresh index on plain-word queries
        and never exceed it: a v1 cache lacks the sub-tokens the current
        tokenizer emits (the start-up notice says so), so identifier
        queries may find more in the fresh index, never less."""
        served = self._search()
        self.assertTrue(any("tokenizer v1" in n for n in served.notices()))
        fresh_dir = os.path.join(TEST_DIR, ".bench-fresh")
        fresh = Search(SearchStore(store=Store(fresh_dir), path=TEST_DIR))
        fresh.index_dir(TEST_DIR)
        for q in ("neural networks", "gamma doubles", "alpha"):
            a = {(r["document"], r["line"]) for r in served.query(q)["lines"]}
            b = {(r["document"], r["line"]) for r in fresh.query(q)["lines"]}
            self.assertEqual(a, b, q)
        # Identifier query: v1 has the underscore parts, so both answer; the
        # fresh index may add lines reachable only through v2 units. (Queries
        # that v1 cannot answer at all fall through to the meta strategy and
        # yield doc-level hits instead — a different set, not a subset.)
        a = {(r["document"], r["line"]) for r in served.query("ALPHA_VALUE")["lines"]}
        b = {(r["document"], r["line"]) for r in fresh.query("ALPHA_VALUE")["lines"]}
        self.assertTrue(a and a <= b)


class TestTextsTrailingTheIndex(LegacyCacheBase):
    """The text history may lag the v1 index; a document listed by the v1
    cache but absent from the history is read from disk, never dropped."""

    def test_missing_text_is_fetched_from_disk_and_survives_convert(self):
        store = Store(self.bench_dir)
        # Rewrite the text history without gamma — as if the base layer was
        # committed before that file was indexed.
        for p in Path(self.bench_dir).glob("*.texts.*"):
            p.unlink()
        store.save_texts(TEST_DIR, {k: v for k, v in FILES.items() if k != "sub/gamma.py"})

        search = self._search()
        self.assertEqual(sorted(search._index.documents), sorted(FILES))
        self.assertGreater(search.query("gamma doubles")["total_lines"], 0)

        search.cache_choice("convert")
        reborn = self._search()
        self.assertIsNone(reborn.legacy_cache)
        self.assertEqual(sorted(reborn._index.documents), sorted(FILES))
        self.assertGreater(reborn.query("gamma doubles")["total_lines"], 0)


class TestChoices(LegacyCacheBase):
    def _v1_backups(self) -> list[str]:
        return sorted(p.name for p in Path(self.bench_dir).iterdir() if ".v1" in p.name)

    def test_convert_writes_current_layout_and_keeps_v1_aside(self):
        search = self._search()
        text = search.cache_choice("convert")
        self.assertIn("Converted", text)
        idx, six = self._v1_names()
        self.assertEqual(pgz_payload_kind(Path(self.bench_dir) / idx), "blob")
        self.assertEqual(pgz_payload_kind(Path(self.bench_dir) / six), "blob")
        backups = self._v1_backups()
        self.assertEqual(len(backups), 2)
        # The set-aside files are the original bytes, unchanged.
        after = _snapshot(self.bench_dir)
        self.assertEqual(after[backups[0]], self.before[idx])
        self.assertEqual(after[backups[1]], self.before[six])
        self.assertIsNone(search.legacy_cache)
        # A fresh start reads the converted cache and answers the same.
        reborn = self._search()
        self.assertIsNone(reborn.legacy_cache)
        self.assertGreater(reborn.query("neural networks")["total_lines"], 0)

    def test_migrate_converts_then_deletes_v1(self):
        search = self._search()
        text = search.cache_choice("migrate")
        self.assertIn("Migrated", text)
        idx, six = self._v1_names()
        self.assertEqual(pgz_payload_kind(Path(self.bench_dir) / idx), "blob")
        self.assertEqual(self._v1_backups(), [])
        reborn = self._search()
        self.assertIsNone(reborn.legacy_cache)
        self.assertGreater(reborn.query("ALPHA_VALUE")["total_lines"], 0)

    def test_migrate_after_convert_removes_the_backups(self):
        search = self._search()
        search.cache_choice("convert")
        self.assertEqual(len(self._v1_backups()), 2)
        # The converted cache is served by a fresh start; migrate then only
        # touches the backups, nothing else in the directory.
        reborn = self._search()
        self.assertIsNone(reborn.legacy_cache)
        snap = _snapshot(self.bench_dir)
        text = reborn.cache_choice("migrate")
        self.assertIn("Migrated", text)
        self.assertEqual(self._v1_backups(), [])
        after = _snapshot(self.bench_dir)
        self.assertEqual({k: v for k, v in snap.items() if ".v1" not in k}, after)
        self.assertIn("no *.v1.pgz backups", reborn.cache_choice("migrate"))

    def test_rebuild_rewalks_and_keeps_v1_aside(self):
        search = self._search()
        _write(os.path.join(TEST_DIR, "delta.py"), "DELTA_TOKEN = 4\n")
        text = search.cache_choice("rebuild")
        self.assertIn("Rebuilt", text)
        self.assertEqual(len(self._v1_backups()), 2)
        idx, _ = self._v1_names()
        self.assertEqual(pgz_payload_kind(Path(self.bench_dir) / idx), "blob")
        self.assertGreater(search.query("DELTA_TOKEN")["total_lines"], 0)
        reborn = self._search()
        self.assertIsNone(reborn.legacy_cache)
        self.assertGreater(reborn.query("DELTA_TOKEN")["total_lines"], 0)

    def test_convert_never_overwrites_an_existing_backup(self):
        search = self._search()
        idx, _ = self._v1_names()
        sentinel = Path(self.bench_dir) / idx.replace(".pgz", ".v1.pgz")
        sentinel.write_bytes(b"older backup")
        search.cache_choice("convert")
        self.assertEqual(sentinel.read_bytes(), b"older backup")
        self.assertEqual(len(self._v1_backups()), 3)


if __name__ == "__main__":
    unittest.main()
