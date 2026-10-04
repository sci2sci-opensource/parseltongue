import unittest

from .test_search import _make_search


class SearchHighlightTests(unittest.TestCase):
    def test_separated_terms_have_a_passage_and_precise_offsets(self):
        text = '- A small `lighthouse04`/Azure bridge is additional network infrastructure, not a workload machine.'
        search = _make_search(('doc', text))
        row = search.query('azure infrastructure', highlights=True)['lines'][0]
        terms = [text[h['start'] : h['end']] for h in row['highlights'] if h['kind'] == 'term']
        self.assertIn('Azure', terms)
        self.assertIn('infrastructure', terms)
        self.assertTrue(
            any(
                text[h['start'] : h['end']] == 'Azure bridge is additional network infrastructure'
                for h in row['highlights']
                if h['kind'] == 'passage'
            )
        )

    def test_boolean_queries_preserve_only_contributing_terms(self):
        search = _make_search(('doc', 'azure infrastructure\nazure unrelated'))
        row = search.query('(and "azure" "infrastructure")', highlights=True)['lines'][0]
        self.assertEqual(set(row['matched_terms']), {'azure', 'infrastructure'})
        row = search.query('(not "azure" "infrastructure")', highlights=True)['lines'][0]
        self.assertEqual(row['matched_terms'], ['azure'])
        row = search.query('(or "azure" "infrastructure")', highlights=True)['lines'][0]
        self.assertEqual(set(row['matched_terms']), {'azure', 'infrastructure'})

    def test_stems_compounds_regex_and_utf16(self):
        search = _make_search(('doc', '😀 Running azureInfrastructure'))
        row = search.query('running', highlights=True)['lines'][0]
        self.assertTrue(any(h['start'] == 3 for h in row['highlights']))
        row = search.query('(re "azure[A-Z]\\\\w+")', highlights=True)['lines'][0]
        self.assertTrue(row['highlights'])

    def test_reversed_and_repeated_phrase_terms(self):
        text = 'infrastructure supports Azure; azure supports infrastructure'
        row = _make_search(('doc', text)).query('azure infrastructure', highlights=True)['lines'][0]
        self.assertGreaterEqual(sum(h['kind'] == 'passage' for h in row['highlights']), 2)

    def test_index_synonym_positions_identify_the_original_word(self):
        from parseltongue.core.quote_verifier.index import DocumentIndex
        from parseltongue.core.search_engine.index import DocumentSearchIndex
        from parseltongue.core.search_engine.synonyms import SynonymIndex, ExpansionScope
        from parseltongue.core.search_engine.highlight import highlight_entry

        documents = DocumentIndex()
        documents.add("doc", "A motor drives the machine")
        synonyms = SynonymIndex()
        synonyms.add_group(["motor", "engine"], scope=ExpansionScope.DOCUMENTS)
        index = DocumentSearchIndex(documents, synonyms=synonyms)
        row = next(iter(index.search("engine").values()))
        self.assertEqual(highlight_entry(index, row)["matched_terms"], ["motor"])

    def test_positions_survive_rebase_without_accessing_normalized_text(self):
        from parseltongue.core.quote_verifier.index import DocumentIndex
        from parseltongue.core.search_engine.index import DocumentSearchIndex
        from parseltongue.core.search_engine.serialization import serialize_search_index, deserialize_search_index
        from parseltongue.core.search_engine.highlight import highlight_entry

        text = "😀 ignored\n😀 Azure infrastructure and azureInfrastructure"
        documents = DocumentIndex()
        documents.add("doc", text)
        index = DocumentSearchIndex(documents)
        row = next(iter(index.search("azure infrastructure").values()))
        expected = highlight_entry(index, row)
        meta, blobs = serialize_search_index(index)
        target = DocumentIndex()
        target.add("other", "reorder the vocabulary")
        target.add("doc", text)
        restored = deserialize_search_index(meta, blobs, target)
        # Highlighting needs only the positional arrays and original lexemes.
        target.documents["doc"].normalized_text = None
        self.assertEqual(highlight_entry(restored, row), expected)
        self.assertIn({"start": 3, "end": 8, "kind": "term"}, expected["highlights"])
        self.assertTrue(any(term == "Azure" for term in expected["matched_terms"]))

    def test_old_cache_reports_missing_positions_without_rebuilding(self):
        from parseltongue.core.search_engine.serialization import serialize_search_index, deserialize_search_index

        search = _make_search(("doc", "azure infrastructure"))
        index = search._system._engine._search_index
        meta, blobs = serialize_search_index(index)
        blobs = {
            key: value
            for key, value in blobs.items()
            if key.split('.', 1)[1] not in index.documents['doc'].POSITION_BLOB_KEYS
        }
        restored = deserialize_search_index(meta, blobs, search._index)
        self.assertFalse(restored._snap.has_match_positions)
        self.assertIsNone(restored.documents['doc']._match_starts)

    def test_highlights_are_opt_in_and_disabled_skips_highlighter(self):
        from unittest.mock import patch

        search = _make_search(("doc", "azure infrastructure"))
        with patch(
            "parseltongue.core.search_engine.highlight.highlight_entry", side_effect=AssertionError("must not run")
        ):
            result = search.query("azure infrastructure")
            self.assertNotIn("highlights", result["lines"][0])
            self.assertFalse(any(key.startswith("_match_") for key in result["lines"][0]))
        self.assertTrue(search.query("azure infrastructure", highlights=True)["lines"][0]["highlights"])
