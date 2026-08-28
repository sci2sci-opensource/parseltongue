"""Array-backed index structures: RunMap, Vocab, postings, BlobPGZ, phrase lookup.

The search engine and quote verifier keep positional data in ``array('I')``
CSR tables and run-length position maps instead of per-int Python objects.
These tests pin the contracts the query layer relies on: set-like posting
semantics, exact round-trips through the blob cache, and id re-basing
between two term dictionaries.
"""

import os
import tempfile
import unittest
from array import array
from pathlib import Path

from parseltongue.core.inspect.pgz import blob_pgz_read, blob_pgz_write
from parseltongue.core.quote_verifier.config import QuoteVerifierConfig
from parseltongue.core.quote_verifier.index import DocumentIndex, IndexedDocument
from parseltongue.core.quote_verifier.normalizer import normalize_with_mapping
from parseltongue.core.quote_verifier.posmap import U32, RunMap
from parseltongue.core.quote_verifier.vocab import Vocab
from parseltongue.core.search_engine.document import SearchDocument
from parseltongue.core.search_engine.index import DocumentSearchIndex
from parseltongue.core.search_engine.postings import CSR, EMPTY, LineSet, TermLines
from parseltongue.core.search_engine.serialization import deserialize_search_index, serialize_search_index

SAMPLE = """Under the hood, LLMs are neural networks.
1. First point about something important.
2. Second point — with punctuation!
The index maps words to lines; the verifier maps quotes to offsets.
neural networks again, and inference methods too.
"""


class TestRunMap(unittest.TestCase):
    def test_roundtrip_equals_source_sequence(self):
        _, pos_map, _ = normalize_with_mapping(SAMPLE, QuoteVerifierConfig())
        rm = RunMap.from_seq(pos_map)
        self.assertEqual(len(rm), len(pos_map))
        self.assertEqual(list(rm), pos_map)
        self.assertEqual(rm, pos_map)
        self.assertLess(rm.runs, len(pos_map) // 2)
        for i in range(len(pos_map)):
            self.assertEqual(rm[i], pos_map[i])
        self.assertEqual(rm[-1], pos_map[-1])
        self.assertEqual(rm[3:9], pos_map[3:9])

    def test_index_errors_like_a_list(self):
        rm = RunMap.from_seq([0, 1, 2, 5, 6])
        self.assertEqual(rm[3], 5)
        with self.assertRaises(IndexError):
            rm[5]
        with self.assertRaises(IndexError):
            rm[-6]

    def test_blob_roundtrip(self):
        rm = RunMap.from_seq([0, 1, 2, 10, 11, 20])
        s, v = rm.to_blobs()
        back = RunMap.from_blobs(s, v, len(rm))
        self.assertEqual(back, rm)
        self.assertEqual(list(back), [0, 1, 2, 10, 11, 20])

    def test_empty_and_identity(self):
        self.assertEqual(len(RunMap.from_seq([])), 0)
        self.assertEqual(list(RunMap.identity(4)), [0, 1, 2, 3])


class TestVocab(unittest.TestCase):
    def test_ids_are_stable_and_append_only(self):
        v = Vocab()
        a = v.id("alpha")
        b = v.id("beta")
        self.assertEqual(v.id("alpha"), a)
        self.assertEqual((a, b), (0, 1))
        self.assertEqual(v.term(b), "beta")
        self.assertIsNone(v.lookup("gamma"))
        self.assertIn("alpha", v)

    def test_remap_from_other_term_list(self):
        v = Vocab(["x", "y"])
        table = v.remap_from(["y", "z", "x"])
        self.assertEqual(list(table), [1, 2, 0])
        self.assertEqual(v.term(2), "z")


class TestLineSet(unittest.TestCase):
    def test_set_semantics(self):
        a = LineSet.of([5, 1, 3, 3])
        b = LineSet.of([3, 4, 5])
        self.assertEqual(list(a), [1, 3, 5])
        self.assertEqual(a & b, {3, 5})
        self.assertEqual(a | b, {1, 3, 4, 5})
        self.assertEqual(a & {5, 9}, {5})
        self.assertEqual({5, 9} & a, {5})
        self.assertIn(3, a)
        self.assertNotIn(2, a)
        self.assertEqual(len(a), 3)
        self.assertTrue(a)
        self.assertFalse(EMPTY)
        self.assertEqual(EMPTY & a, set())

    def test_csr_build_and_lookup(self):
        csr = CSR.build({7: [3, 1, 3], 2: [9]})
        self.assertEqual(list(csr.terms), [2, 7])
        self.assertEqual(list(csr.get(7)), [1, 3])
        self.assertEqual(list(csr.get(2)), [9])
        self.assertIsNone(csr.get(5))
        back = CSR.from_blobs(csr.to_blobs("p"), "p")
        self.assertEqual((back.terms, back.offsets, back.values), (csr.terms, csr.offsets, csr.values))

    def test_term_lines_view(self):
        v = Vocab(["cat", "dog"])
        tl = TermLines(CSR.build({0: [2, 4], 1: [4]}), v)
        self.assertEqual(tl["cat"], {2, 4})
        self.assertEqual(tl.get("dog"), {4})
        self.assertIsNone(tl.get("emu"))
        self.assertIn("cat", tl)
        self.assertNotIn("emu", tl)
        self.assertEqual(sorted(tl), ["cat", "dog"])
        self.assertEqual({k: list(ls) for k, ls in tl.items()}, {"cat": [2, 4], "dog": [4]})


class TestBlobPGZ(unittest.TestCase):
    def test_roundtrip_meta_and_blobs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.pgz"
            arr = array(U32, [1, 2, 3, 70000])
            blob_pgz_write(p, {"k": "v", "n": [1, 2]}, {"a": arr.tobytes(), "b": b"", "c": b"\x00\xff"})
            meta, blobs = blob_pgz_read(p)
            self.assertEqual(meta, {"k": "v", "n": [1, 2]})
            got = array(U32)
            got.frombytes(blobs["a"])
            self.assertEqual(got, arr)
            self.assertEqual(bytes(blobs["b"]), b"")
            self.assertEqual(bytes(blobs["c"]), b"\x00\xff")
            self.assertFalse(os.path.exists(str(p) + ".tmp"))


class TestIndexedDocumentArrays(unittest.TestCase):
    def test_word_positions_view_matches_text(self):
        doc = IndexedDocument("s", SAMPLE, QuoteVerifierConfig())
        wp = doc.word_positions
        self.assertIn("neural", wp)
        for pos in wp["neural"]:
            self.assertEqual(doc.normalized_text[pos : pos + 6], "neural")
        self.assertEqual(len(wp["neural"]), 2)
        self.assertNotIn("zzz", wp)
        self.assertEqual(set(wp), set(doc.normalized_text.split()))

    def test_record_roundtrip_and_remap(self):
        idx = DocumentIndex({"s": SAMPLE, "t": "neural nets are networks"})
        meta, blobs = idx.to_record()
        back = DocumentIndex.from_record(meta, blobs, {"s": SAMPLE, "t": "neural nets are networks"})
        for name in ("s", "t"):
            a, b = idx.documents[name], back.documents[name]
            self.assertEqual(a.normalized_text, b.normalized_text)
            self.assertEqual(a.position_map, b.position_map)
            self.assertEqual(
                {k: list(v) for k, v in a.word_positions.items()}, {k: list(v) for k, v in b.word_positions.items()}
            )
        # JSON form (System caches) round-trips too, and an unknown layout rebuilds.
        d = idx.to_dict()
        again = DocumentIndex.from_dict(d, {"s": SAMPLE, "t": "neural nets are networks"})
        self.assertEqual(again.documents["s"].position_map, idx.documents["s"].position_map)
        rebuilt = DocumentIndex.from_dict({"documents": {}}, {"s": SAMPLE})
        self.assertIn("s", rebuilt.documents)

    def test_collapsed_fallback_is_lazy(self):
        doc = IndexedDocument("s", SAMPLE, QuoteVerifierConfig())
        self.assertIsNone(doc._collapsed_text)
        start, end, _ = doc.find("neuralnetworks")
        self.assertGreaterEqual(start, 0)
        self.assertIsNotNone(doc._collapsed_text)


class TestSearchDocumentPhrases(unittest.TestCase):
    def setUp(self):
        self.idx = DocumentIndex({"s": SAMPLE})
        self.sdoc = SearchDocument(self.idx.documents["s"])

    def test_word_and_stem_lines(self):
        self.assertEqual(self.sdoc.lines_with_word("neural"), {1, 5})
        self.assertEqual(self.sdoc.lines_with_stem("networks"), {1, 5})
        self.assertEqual(self.sdoc.lines_with_all_words(["neural", "networks"]), {1, 5})
        self.assertEqual(self.sdoc.lines_with_all_words(["neural", "inference"]), {5})
        self.assertEqual(self.sdoc.lines_with_all_words(["neural", "quotes"]), set())

    def test_phrase_requires_adjacency_in_order(self):
        from parseltongue.core.search_engine.stemmer import stem

        s = self.sdoc
        self.assertEqual(s.lines_with_phrase([stem("neural"), stem("networks")]), {1, 5})
        self.assertEqual(s.lines_with_phrase([stem("networks"), stem("neural")]), set())
        self.assertEqual(s.lines_with_phrase([stem("inference"), stem("methods")]), {5})
        self.assertEqual(s.lines_with_phrase([stem("neural"), stem("inference")]), set())
        self.assertEqual(s.lines_with_phrase([stem("neural")]), set())

    def test_line_ranges_cover_text(self):
        ranges = self.sdoc.line_ranges
        self.assertEqual(len(ranges), len(self.sdoc.lines) + 1)  # trailing newline → empty last line
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(SAMPLE[ranges[1][0] : ranges[1][1] + 1], "1. First point about something important.")


class TestSearchIndexSerialization(unittest.TestCase):
    def test_roundtrip_with_id_rebase(self):
        idx = DocumentIndex({"a.txt": SAMPLE, "b.txt": "inference methods live here\nneural stuff"})
        sidx = DocumentSearchIndex(idx)
        before = sidx.lookup("neural networks", "direct")
        meta, blobs = serialize_search_index(sidx)

        # A fresh DocumentIndex assigns ids in a different order — the cache
        # must re-base onto it and answer identically.
        idx2 = DocumentIndex({"b.txt": "inference methods live here\nneural stuff", "a.txt": SAMPLE})
        self.assertNotEqual(list(idx.vocab.terms)[:5], list(idx2.vocab.terms)[:5])
        restored = deserialize_search_index(meta, blobs, idx2)
        after = restored.lookup("neural networks", "direct")
        self.assertEqual(set(before), set(after))
        self.assertEqual(
            set(restored.lookup("inference method", "stemmed")), set(sidx.lookup("inference method", "stemmed"))
        )
        self.assertEqual(set(restored.lookup("inference methods", "ngram")), {("a.txt", 5), ("b.txt", 1)})
        self.assertEqual(restored._snap.doc_lengths, sidx._snap.doc_lengths)


if __name__ == "__main__":
    unittest.main()
