import unittest

from ..quote_verifier import QuoteVerifier  # subpackage, not re-exported


class TestQuoteVerifier(unittest.TestCase):
    """Test cases for the QuoteVerifier class."""

    def setUp(self):
        """Set up test fixtures."""
        # Sample document for testing
        self.sample_document = """
        Retrieval-Augmented Generation (RAG) is a technique for enhancing the accuracy and reliability 
        of generative AI models with information fetched from specific and relevant data sources. 
        In other words, it fills a gap in how LLMs work. Under the hood, LLMs are neural networks, 
        typically measured by how many parameters they contain.

        RAG can be a double-edged sword: while the concept is straightforward – find relevant information 
        and feed it to the LLM – its implementation is difficult to master. Done incorrectly, it can impact 
        user trust in your AI's reliability.

        Large language models (LLMs) have emerged as a widely-used tool for information seeking, 
        but their generated outputs are prone to hallucination. That's why getting the AI models to 
        provide sources and citations is the key to improving their factual correctness and verifiability.

        Here are some numbered points:
        1. First point about something important.
        2. Second point that continues the discussion.
        3. Third point with extra details.

        This paragraph contains hyphen-
        ation at the end of a line, which should be handled properly.

        Another example of multi-
        level hyphenation that spans across lines.
        """

        # Create default verifier
        self.verifier = QuoteVerifier()

    def test_exact_match(self):
        """Test verification of exact quotes."""
        quote = "Retrieval-Augmented Generation (RAG) is a technique for enhancing the accuracy and reliability"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

    def test_case_insensitive_match(self):
        """Test case-insensitive matching."""
        quote = "retrieval-augmented generation (rag) is a technique for enhancing"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with case sensitivity enabled
        sensitive_verifier = QuoteVerifier(case_sensitive=True)
        sensitive_result = sensitive_verifier.verify_quote(self.sample_document, quote)
        self.assertFalse(sensitive_result["verified"])

    def test_punctuation_ignoring(self):
        """Test ignoring punctuation."""
        quote = "RAG can be a double-edged sword while the concept is straightforward"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with punctuation sensitivity enabled
        punct_verifier = QuoteVerifier(ignore_punctuation=False)
        punct_result = punct_verifier.verify_quote(self.sample_document, quote)
        self.assertFalse(punct_result["verified"])

    def test_whitespace_normalization(self):
        """Test normalization of whitespace."""
        quote = "RAG   can be a   double-edged   sword"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

    def test_non_existent_quote(self):
        """Test with a quote that doesn't exist in the document."""
        quote = "This text does not appear in the document."
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertFalse(result["verified"])

    def test_empty_quote(self):
        """Test with an empty quote."""
        quote = ""
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "Empty quote")

    def test_list_normalization(self):
        """Test normalization of numbered lists."""
        # Quote that includes a list number
        quote = "1. First point about something important."
        # Should match even with the list number included
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Quote without the list number
        quote = "First point about something important."
        # Should also match
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with list normalization disabled
        no_list_verifier = QuoteVerifier(normalize_lists=False)
        # Without normalization, only the exact match should work
        result_with_number = no_list_verifier.verify_quote(self.sample_document,
                                                           "1. First point about something important. 2. Second point that")
        result_without_number = no_list_verifier.verify_quote(self.sample_document,
                                                              "First point about something important. Second point that")
        self.assertTrue(result_with_number["verified"])
        self.assertFalse(result_without_number["verified"])

    def test_list_normalization_complex(self):
        """Test normalization of numbered lists."""
        # Create a document with numbered list items
        list_document = """Here is a list:
        1. Something and something else
        2. Next something important
        3. Final point with details."""

        # Test 1: With normalization ON, a quote that spans across list items should match
        # This should match because list numbers are normalized away and items can flow together
        spanning_quote = "Something and something else Next something"
        result_spanning = self.verifier.verify_quote(list_document, spanning_quote)
        self.assertTrue(result_spanning["verified"],
                        "With list normalization, a quote spanning list items should match")

        # Test 2: With normalization OFF, the same spanning quote should NOT match
        no_list_verifier = QuoteVerifier(normalize_lists=False)
        result_no_norm = no_list_verifier.verify_quote(list_document, spanning_quote)
        self.assertFalse(result_no_norm["verified"],
                         "Without list normalization, a quote spanning list items should not match")

        # Test 3: With normalization OFF, quotes should need exact matches including list numbers
        exact_quote = "1. Something and something else"
        result_exact = no_list_verifier.verify_quote(list_document, exact_quote)
        self.assertTrue(result_exact["verified"],
                        "Without list normalization, exact quote with number should match")

        # Test 4: Standard substring matching should work regardless of normalization
        # This text appears as-is without needing normalization
        substring_quote = "Something and something else"
        result_substring = no_list_verifier.verify_quote(list_document, substring_quote)
        self.assertTrue(result_substring["verified"],
                        "Standard substring matching should work regardless of normalization")

    def test_hyphenation_normalization(self):
        """Test normalization of hyphenation at line breaks."""
        # Test with hyphenation where the word is split across lines
        quote = "This paragraph contains hyphenation at the end of a line"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test the complete word being matched correctly
        quote = "Another example of multilevel hyphenation"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with hyphenation normalization disabled
        no_hyphen_verifier = QuoteVerifier(normalize_hyphenation=False)
        result_no_hyphen = no_hyphen_verifier.verify_quote(self.sample_document, "This paragraph contains")
        self.assertTrue(
            result_no_hyphen["verified"])  # This should still match as it doesn't include the hyphenated part

        result_no_hyphen_fail = no_hyphen_verifier.verify_quote(self.sample_document,
                                                                "Another example of multilevel hyphenation")
        self.assertFalse(result_no_hyphen_fail["verified"])  # This should fail as the hyphenation isn't normalized

    def test_multiple_quotes(self):
        """Test verification of multiple quotes."""
        quotes = [
            "Retrieval-Augmented Generation (RAG) is a technique",
            "This text does not appear in the document.",
            "Large language models (LLMs) have emerged",
        ]
        results = self.verifier.verify_quotes(self.sample_document, quotes)
        self.assertTrue(results[0]["verified"])
        self.assertFalse(results[1]["verified"])
        self.assertTrue(results[2]["verified"])

    def test_position_mapping(self):
        """Test that position mapping correctly identifies the original position."""
        quote = "Under the hood, LLMs are neural networks"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])
        # The position should correspond to the start of the quote in the original document
        self.assertGreater(result["original_position"], 0)

    def test_combined_normalizations(self):
        """Test combinations of normalization features working together."""
        # This quote combines case differences, punctuation, and a list item
        quote = "first POINT about something important"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with hyphenation and case differences
        quote = "another EXAMPLE of multilevel hyphenation"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

    def test_multiple_newlines(self):
        """Test handling of multiple newlines."""
        document = "Line one.\n\n\nLine two."
        quote = "Line one. Line two."
        result = self.verifier.verify_quote(document, quote)
        self.assertTrue(result["verified"])


class TestQuoteVerifier2(unittest.TestCase):
    """Test cases for the QuoteVerifier class."""

    def setUp(self):
        """Set up test fixtures."""
        # Sample document for testing
        self.sample_document = """
        Retrieval-Augmented Generation (RAG) is a technique for enhancing the accuracy and reliability 
        of generative AI models with information fetched from specific and relevant data sources. 
        In other words, it fills a gap in how LLMs work. Under the hood, LLMs are neural networks, 
        typically measured by how many parameters they contain.

        RAG can be a double-edged sword: while the concept is straightforward – find relevant information 
        and feed it to the LLM – its implementation is difficult to master. Done incorrectly, it can impact 
        user trust in your AI's reliability.

        Large language models (LLMs) have emerged as a widely-used tool for information seeking, 
        but their generated outputs are prone to hallucination. That's why getting the AI models to 
        provide sources and citations is the key to improving their factual correctness and verifiability.

        Here are some numbered points:
        1. First point about something important.
        2. Second point that continues the discussion.
        3. Third point with extra details.

        This paragraph contains hyphen-
        ation at the end of a line, which should be handled properly.

        Another example of multi-
        level hyphenation that spans across lines.

        Combination treatment in the KRAS-mutant cells disrupted this compensatory response, 
        potentially explaining the synergistic growth inhibition observed.
        """

        # Create default verifier
        self.verifier = QuoteVerifier()

        # Create verifier with stopwords enabled
        self.stopword_verifier = QuoteVerifier(remove_stopwords=True)

    def test_exact_match(self):
        """Test verification of exact quotes."""
        quote = "Retrieval-Augmented Generation (RAG) is a technique for enhancing the accuracy and reliability"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

    def test_case_insensitive_match(self):
        """Test case-insensitive matching."""
        quote = "retrieval-augmented generation (rag) is a technique for enhancing"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with case sensitivity enabled
        sensitive_verifier = QuoteVerifier(case_sensitive=True)
        sensitive_result = sensitive_verifier.verify_quote(self.sample_document, quote)
        self.assertFalse(sensitive_result["verified"])

    def test_punctuation_ignoring(self):
        """Test ignoring punctuation."""
        quote = "RAG can be a double-edged sword while the concept is straightforward"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with punctuation sensitivity enabled
        punct_verifier = QuoteVerifier(ignore_punctuation=False)
        punct_result = punct_verifier.verify_quote(self.sample_document, quote)
        self.assertFalse(punct_result["verified"])

    def test_whitespace_normalization(self):
        """Test normalization of whitespace."""
        quote = "RAG   can be a   double-edged   sword"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

    def test_skip_normalization(self):
        """Test normalization of whitespace."""
        quote = "RAG   can be a ...  double-edged   sword"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

    def test_non_existent_quote(self):
        """Test with a quote that doesn't exist in the document."""
        quote = "This text does not appear in the document."
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertFalse(result["verified"])

    def test_empty_quote(self):
        """Test with an empty quote."""
        quote = ""
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "Empty quote")

    def test_list_normalization(self):
        """Test normalization of numbered lists."""
        # Create a document with numbered list items
        list_document = """Here is a list:
        1. Something and something else
        2. Next something important
        3. Final point with details."""

        # Test 1: With normalization ON, a quote that spans across list items should match
        # This should match because list numbers are normalized away and items can flow together
        spanning_quote = "Something and something else Next something"
        result_spanning = self.verifier.verify_quote(list_document, spanning_quote)
        self.assertTrue(result_spanning["verified"],
                        "With list normalization, a quote spanning list items should match")

        # Test 2: With normalization OFF, the same spanning quote should NOT match
        no_list_verifier = QuoteVerifier(normalize_lists=False)
        result_no_norm = no_list_verifier.verify_quote(list_document, spanning_quote)
        self.assertFalse(result_no_norm["verified"],
                         "Without list normalization, a quote spanning list items should not match")

        # Test 3: With normalization OFF, quotes should need exact matches including list numbers
        exact_quote = "1. Something and something else"
        result_exact = no_list_verifier.verify_quote(list_document, exact_quote)
        self.assertTrue(result_exact["verified"],
                        "Without list normalization, exact quote with number should match")

        # Test 4: Standard substring matching should work regardless of normalization
        # This text appears as-is without needing normalization
        substring_quote = "Something and something else"
        result_substring = no_list_verifier.verify_quote(list_document, substring_quote)
        self.assertTrue(result_substring["verified"],
                        "Standard substring matching should work regardless of normalization")

    def test_hyphenation_normalization(self):
        """Test normalization of hyphenation at line breaks."""
        # Test with hyphenation where the word is split across lines
        quote = "This paragraph contains hyphenation at the end of a line"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test the complete word being matched correctly
        quote = "Another example of multilevel hyphenation"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with hyphenation normalization disabled
        no_hyphen_verifier = QuoteVerifier(normalize_hyphenation=False)
        result_no_hyphen = no_hyphen_verifier.verify_quote(self.sample_document, "This paragraph contains")
        self.assertTrue(
            result_no_hyphen["verified"])  # This should still match as it doesn't include the hyphenated part

        result_no_hyphen_fail = no_hyphen_verifier.verify_quote(self.sample_document,
                                                                "Another example of multilevel hyphenation")
        self.assertFalse(result_no_hyphen_fail["verified"])  # This should fail as the hyphenation isn't normalized

    def test_hyphenation_with_spaces(self):
        """Test normalization of hyphenation with excessive spaces after line breaks."""
        document = "This has a hyphen-\n      ated word with many spaces after the break."
        quote = "This has a hyphenated word with many spaces after the break."
        result = self.verifier.verify_quote(document, quote)
        self.assertTrue(result["verified"])

        # Additional test with even more complex spacing
        document2 = "Multi-\n   level hyphen-\n        ation with vary-\n  ing spaces."
        quote2 = "Multilevel hyphenation with varying spaces."
        result2 = self.verifier.verify_quote(document2, quote2)
        self.assertTrue(result2["verified"])

    def test_multiple_quotes(self):
        """Test verification of multiple quotes."""
        quotes = [
            "Retrieval-Augmented Generation (RAG) is a technique",
            "This text does not appear in the document.",
            "Large language models (LLMs) have emerged",
        ]
        results = self.verifier.verify_quotes(self.sample_document, quotes)
        self.assertTrue(results[0]["verified"])
        self.assertFalse(results[1]["verified"])
        self.assertTrue(results[2]["verified"])

    def test_position_mapping(self):
        """Test that position mapping correctly identifies the original position."""
        quote = "Under the hood, LLMs are neural networks"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])
        # The position should correspond to the start of the quote in the original document
        self.assertGreater(result["original_position"], 0)

    def test_combined_normalizations(self):
        """Test combinations of normalization features working together."""
        # This quote combines case differences, punctuation, and a list item
        quote = "first POINT about something important"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

        # Test with hyphenation and case differences
        quote = "another EXAMPLE of multilevel hyphenation"
        result = self.verifier.verify_quote(self.sample_document, quote)
        self.assertTrue(result["verified"])

    def test_multiple_newlines(self):
        """Test handling of multiple newlines."""
        document = "Line one.\n\n\nLine two."
        quote = "Line one. Line two."
        result = self.verifier.verify_quote(document, quote)
        self.assertTrue(result["verified"])

    def test_stopword_removal(self):
        """Test stopword removal functionality."""
        # Example from your use case
        document = "Combination treatment in the KRAS-mutant cells disrupted this compensatory response, potentially explaining the synergistic growth inhibition observed."
        quote = "Combination treatment KRAS-mutant cells disrupted compensatory response, potentially explaining synergistic growth inhibition"

        # Without stopword removal, this should fail
        result_no_stopwords = self.verifier.verify_quote(document, quote)
        self.assertFalse(result_no_stopwords["verified"],
                         "Without stopword removal, quote with missing stopwords should not match")

        # With stopword removal, this should match
        result_with_stopwords = self.stopword_verifier.verify_quote(document, quote)
        self.assertTrue(result_with_stopwords["verified"],
                        "With stopword removal, quote missing only stopwords should match")

        # Test with custom stopwords
        custom_stopwords = {"this", "the"}
        custom_verifier = QuoteVerifier(remove_stopwords=True, stopwords=custom_stopwords)
        result_custom = custom_verifier.verify_quote(document, quote)
        self.assertFalse(result_custom["verified"],
                         "With limited custom stopwords, quote missing non-stopwords should not match")

        # Quote missing only our custom stopwords
        quote_custom = "Combination treatment in KRAS-mutant cells disrupted compensatory response, potentially explaining synergistic growth inhibition observed."
        result_custom_match = custom_verifier.verify_quote(document, quote_custom)
        self.assertTrue(result_custom_match["verified"],
                        "With custom stopwords, quote missing only those stopwords should match")

    def test_extreme_stopword_case(self):
        """Test edge cases for stopword removal."""
        document = "The quick brown fox jumps over the lazy dog."

        # All stopwords
        stopword_verifier = QuoteVerifier(remove_stopwords=True,
                                          stopwords={"the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog"})
        quote = "quick brown fox jumps lazy dog"
        result = stopword_verifier.verify_quote(document, quote)
        self.assertFalse(result["verified"], "With all words as stopwords, reduced quote is empty and shouldn't match")

        # Quotes that change meaning by removing stopwords should not match
        document2 = "He said not to go there."
        quote2 = "He said to go there."  # Removing "not" changes meaning dramatically

        # Make a verifier where "not" is a stopword
        dangerous_verifier = QuoteVerifier(remove_stopwords=True, stopwords={"not"})
        result2 = dangerous_verifier.verify_quote(document2, quote2)

        # This is a case where stopword removal is dangerous - it would match when it shouldn't
        # In a real implementation, you might want to have a "safe stopwords" list
        self.assertFalse(result2["verified"],
                         "WARNING: Removing crucial words like 'not' changes meaning but still matches")

        # Make a verifier where "not" is a stopword
        dangerous_verifier = QuoteVerifier(remove_stopwords=True, stopwords={"not"}, confidence_threshold=0.3)
        result2 = dangerous_verifier.verify_quote(document2, quote2)

        # This is a case where stopword removal is dangerous - it would match when it shouldn't
        # In a real implementation, you might want to have a "safe stopwords" list
        self.assertTrue(result2["verified"],
                        "WARNING: Removing crucial words like 'not' changes meaning but still matches")


class TestRealCases(unittest.TestCase):

    def test_GSK(self):
        text = '# ***Sequencing & Computational Diagnostics (SCD)***\n\n## ***RNA Sequencing Analysis Report***\n\n*Project ID: SCD-25-0417\nClient Order #: ORD-12421\nReport Date: May 24, 2025\nVersion: Final 1.0*\n\n### ***Executive Summary***\n\n*Dear Dr. Martinez,*\n\n*We are pleased to present the final report for the RNA sequencing analysis of your MEK inhibitor study samples. All analyses have been completed according to the specifications in your order (ORD-12421). This report includes a summary of methods, key findings, and quality metrics for all samples.*\n\n*The sequencing and analysis were successfully completed for all 60 samples, comprising both mRNA-Seq and miRNA-Seq libraries. Our analysis revealed several significant findings:*\n\n1. *The mRNA-Seq analysis identified 3,842 differentially expressed genes across all treatment comparisons, with the most significant changes observed in the combination treatment group of KRAS-mutant cell lines.*\n2. *miRNA profiling detected 142 differentially expressed miRNAs, with distinct expression patterns between KRAS-mutant and BRAF-mutant cell lines.*\n3. *Integrated analysis of miRNA and mRNA data revealed several regulatory networks potentially involved in the response to combination treatment, particularly in pathways related to cell cycle regulation and stress response.*\n\n*The complete dataset and analysis results are available through our secure cloud platform. Access credentials are provided in the attached document.*\n\n*Key Finding: Our analysis revealed a novel transcriptional signature involving reciprocal regulation of MIF-related genes and specific miRNAs in KRAS-mutant cells treated with combination therapy. This signature may represent a potential mechanism for the synergistic effects observed in your previous studies.*\n\n*Please feel free to contact me if you have any questions about this report or need assistance with additional analyses.*\n\n*Sincerely,*\n\n*Dr. Michael Zhang\nDirector, Genomics Services\nSequencing & Computational Diagnostics\nmichael.zhang@scdiagnostics.com\n617-555-7423*\n\n### ***Sample Information***\n\n*Sample Receipt: April 17, 2025\nSample Condition upon Receipt: Excellent (all samples frozen, no signs of thawing)\nSample Storage: -80°C freezer (Facility ID: SCD-BOS-F02)*\n\n#### ***Sample Quality Control:***\n\n| ***Group*** | ***Cell Line*** | ***Treatment*** | ***Replicates*** | ***RNA Conc. Range (ng/μL)*** | ***RIN Range*** | ***QC Status*** |\n| --- | --- | --- | --- | --- | --- | --- |\n| *Group 1* | *HCT116* | *Control* | *3* | *498-521* | *9.7-9.8* | *Pass* |\n| *Group 1* | *HCT116* | *GSK-1120212* | *3* | *455-472* | *9.5-9.7* | *Pass* |\n| *Group 1* | *HCT116* | *4-IPP* | *3* | *475-492* | *9.6-9.7* | *Pass* |\n| *Group 1* | *HCT116* | *Combination* | *3* | *398-425* | *9.3-9.4* | *Pass* |\n| *Group 2* | *LOVO* | *Control* | *3* | *483-512* | *9.5-9.7* | *Pass* |\n| *Group 2* | *LOVO* | *GSK-1120212* | *3* | *432-458* | *9.3-9.5* | *Pass* |\n| *Group 2* | *LOVO* | *4-IPP* | *3* | *467-489* | *9.4-9.6* | *Pass\\** |\n| *Group 2* | *LOVO* | *Combination* | *3* | *385-412* | *9.2-9.4* | *Pass* |\n| *Group 3* | *SNU175* | *Control* | *3* | *492-518* | *9.6-9.8* | *Pass* |\n| *Group 3* | *SNU175* | *GSK-1120212* | *3* | *443-472* | *9.4-9.6* | *Pass* |\n| *Group 3* | *SNU175* | *4-IPP* | *3* | *479-502* | *9.5-9.7* | *Pass* |\n| *Group 3* | *SNU175* | *Combination* | *3* | *393-425* | *9.2-9.5* | *Pass* |\n| *Group 4* | *HT29* | *Control* | *3* | *502-535* | *9.7-9.9* | *Pass* |\n| *Group 4* | *HT29* | *GSK-1120212* | *3* | *348-385* | *9.2-9.5* | *Pass\\*\\** |\n| *Group 4* | *HT29* | *4-IPP* | *3* | *487-512* | *9.6-9.8* | *Pass* |\n| *Group 4* | *HT29* | *Combination* | *3* | *332-367* | *9.1-9.3* | *Pass\\*\\** |\n| *Group 5* | *Colo205* | *Control* | *3* | *488-522* | *9.6-9.8* | *Pass* |\n| *Group 5* | *Colo205* | *GSK-1120212* | *3* | *352-392* | *9.3-9.5* | *Pass\\*\\** |\n| *Group 5* | *Colo205* | *4-IPP* | *3* | *472-503* | *9.5-9.7* | *Pass* |\n| *Group 5* | *Colo205* | *Combination* | *3* | *341-375* | *9.1-9.4* | *Pass\\*\\** |\n\n*\\*LOVO-I-2 (4-IPP, Rep 2) sample showed slight discoloration as noted in submission form. Additional QC tests performed; no impact on RNA quality or sequencing results observed. \\*\\*HT29 and Colo205 GSK-1120212 and combination samples showed lower RNA concentration as expected based on treatment effects. Library preparation protocols adjusted accordingly to ensure adequate library complexity.*\n\n### ***Methodology***\n\n#### ***Library Preparation***\n\n* *mRNA-Seq Libraries:*\n+ *Protocol: NEBNext Ultra II Directional RNA Library Prep Kit*\n+ *Input: 1 μg total RNA per sample*\n+ *Enrichment: Poly(A) selection*\n+ *Fragmentation: RNA fragmentation buffer (94°C for 15 minutes)*\n+ *cDNA Synthesis: Random primed first strand followed by directional second strand synthesis*\n+ *Adapter Ligation: NEBNext Adaptors with unique dual indices*\n+ *PCR Amplification: 12 cycles*\n* *miRNA-Seq Libraries:*\n+ *Protocol: NEBNext Small RNA Library Prep Kit*\n+ *Input: 500 ng total RNA per sample*\n+ *Size Selection: PAGE purification (145-160 bp range)*\n+ *PCR Amplification: 15 cycles*\n+ *Depletion: rRNA removal not performed (unnecessary for small RNA libraries)*\n\n#### ***Sequencing***\n\n* *mRNA-Seq:*\n+ *Platform: Illumina NovaSeq 6000*\n+ *Read Configuration: 150 bp paired-end*\n+ *Sequencing Depth: Minimum 30 million read pairs per sample*\n+ *Lane Distribution: 8 samples per lane*\n+ *PhiX Spike-in: 1%*\n* *miRNA-Seq:*\n+ *Platform: Illumina NovaSeq 6000*\n+ *Read Configuration: 75 bp single-end*\n+ *Sequencing Depth: Minimum 10 million reads per sample*\n+ *Lane Distribution: 24 samples per lane*\n+ *PhiX Spike-in: 1%*\n\n#### ***Data Processing***\n\n* *mRNA-Seq Analysis Pipeline:*\n+ *Read QC: FastQC v0.12.1*\n+ *Adapter Trimming: Cutadapt v4.4*\n+ *Alignment: STAR v2.7.10b to GRCh38 reference genome*\n+ *Transcript Assembly: StringTie v2.2.1*\n+ *Gene Expression Quantification: RSEM v1.3.3*\n+ *Differential Expression: DESeq2 v1.40.1*\n* *miRNA-Seq Analysis Pipeline:*\n+ *Read QC: FastQC v0.12.1*\n+ *Adapter Trimming: Cutadapt v4.4 with specific parameters for small RNA*\n+ *Alignment: Bowtie2 v2.5.1 to miRBase v22 and GRCh38*\n+ *miRNA Quantification: miRDeep2 v0.1.3*\n+ *Differential Expression: DESeq2 v1.40.1*\n* *Integrated Analysis:*\n+ *miRNA Target Prediction: miRanda v3.3a and TargetScan v8.0*\n+ *Network Analysis: miRNA-mRNA interaction networks*\n+ *Pathway Analysis: GSEA v4.3.2, Reactome, KEGG*\n\n### ***Results Summary***\n\n#### ***1. mRNA-Seq Analysis***\n\n*The mRNA-Seq analysis achieved high-quality sequencing data for all samples, with an average of 34.2 million read pairs per sample (range: 31.5-38.7 million). On average, 95.3% of reads mapped to the reference genome, with 92.1% uniquely mapped.*\n\n*Key Observations:*\n\n* *GSK-1120212 treatment led to significant transcriptional changes in BRAF-mutant cell lines (HT29, Colo205), with 2,183 and 1,978 differentially expressed genes (DEGs) respectively (|log2FC| > 1, FDR < 0.05). In contrast, KRAS-mutant cell lines showed more modest changes, with 467 (HCT116), 534 (LOVO), and 498 (SNU175) DEGs.*\n* *4-IPP treatment resulted in fewer transcriptional changes across all cell lines, with 312-487 DEGs. Pathway analysis showed enrichment in inflammatory response pathways and modest effects on MIF-regulated genes.*\n* *Combination treatment in KRAS-mutant cell lines showed synergistic effects at the transcriptional level:*\n+ *1,834 DEGs in HCT116*\n+ *1,757 DEGs in LOVO*\n+ *1,682 DEGs in SNU175*\n* *These included 948 genes not significantly altered by either single agent alone. These synergistic DEGs were enriched in pathways related to:*\n+ *Cell cycle regulation (p = 2.7e-09)*\n+ *DNA damage response (p = 5.1e-08)*\n+ *Cellular stress response (p = 3.4e-07)*\n+ *Translation (p = 8.2e-06)*\n* *Mutation-specific transcriptional signatures: Principal component analysis clearly separated KRAS-mutant and BRAF-mutant cell lines based on their gene expression profiles (PC1: 42% variance explained), with treatment effects explaining PC2 (22% variance explained).*\n\n#### ***2. miRNA-Seq Analysis***\n\n*miRNA-Seq analysis identified 758 mature miRNAs across all samples, with 602 detected in at least 75% of samples. The sequencing depth was sufficient, with an average of 12.3 million reads per sample (range: 10.5-14.2 million).*\n\n*Key Observations:*\n\n* *GSK-1120212 treatment altered the expression of 67 miRNAs in BRAF-mutant cell lines but only 21-28 miRNAs in KRAS-mutant cell lines.*\n* *4-IPP treatment affected 32-41 miRNAs across all cell lines, with several inflammation-related miRNAs (miR-146a-5p, miR-155-5p) showing consistent regulation.*\n* *Combination treatment in KRAS-mutant cell lines led to significant changes in 87 miRNAs, including several that target key components of the MAPK and STAT3 signaling pathways:*\n+ *miR-124-3p (targets STAT3)*\n+ *miR-7-5p (targets ERK1/2)*\n+ *miR-218-5p (targets MIF pathway components)*\n+ *miR-199a-5p (targets mTOR signaling)*\n\n#### ***3. Integrated miRNA-mRNA Analysis***\n\n*By integrating miRNA and mRNA expression data, we identified 312 high-confidence miRNA-mRNA interaction pairs that were inversely correlated and showed significant expression changes in response to combination treatment.*\n\n*Key Observations:*\n\n* *Novel regulatory circuits: We identified several miRNA-mediated regulatory circuits specifically modulated by combination treatment in KRAS-mutant cells:*\n+ *miR-124-3p/STAT3/BCL2 axis*\n+ *miR-218-5p/CD74/MIF pathway*\n+ *miR-199a-5p/mTOR/S6K1 pathway*\n* *Cell cycle regulation: Combination treatment induced a coordinated set of miRNAs targeting cell cycle genes, particularly those involved in G1/S transition.*\n* *Feedback mechanisms: Several miRNAs involved in feedback regulation of MAPK signaling were differentially expressed in combination-treated KRAS-mutant cells.*\n\n### ***Data Package Contents***\n\n*Your complete data package is available through our secure cloud platform. Access credentials are provided in the attached document. The data package includes:*\n\n#### ***1. Raw Data***\n\n* *Raw sequencing files (FASTQ format)*\n* *Trimmed and filtered reads (FASTQ format)*\n* *Alignment files (BAM format)*\n\n#### ***2. Processed Data***\n\n* *Gene expression matrices (counts, TPM, FPKM formats)*\n* *miRNA expression matrices (counts, RPM formats)*\n* *Normalized expression matrices (for visualization and analysis)*\n* *Differential expression results (CSV and Excel formats)*\n\n#### ***3. Analysis Results***\n\n* *Quality control metrics and visualizations*\n* *Principal component analysis plots*\n* *Hierarchical clustering heatmaps*\n* *Volcano plots for all comparisons*\n* *Pathway enrichment results*\n* *miRNA target prediction and correlation analysis*\n* *Integrated miRNA-mRNA networks*\n\n#### ***4. R and Python Scripts***\n\n* *All analysis scripts*\n* *R markdown notebooks for reproducibility*\n\n#### ***5. Interactive Visualization Dashboard***\n\n* *Gene Explorer interactive tool*\n* *miRNA Network Visualizer*\n* *Expression heatmap generator*\n* *Pathway enrichment browser*\n\n### ***Data Access and File Structure***\n\n*Your data is available through our secure cloud platform:* [*https://data.scdiagnostics.com/*](https://data.scdiagnostics.com/)\n\n*Folder structure within your project:*\n\n*SCD-25-0417/*\n\n*├── 01\\_Raw\\_Data/*\n\n*│ ├── mRNA\\_Seq/*\n\n*│ │ ├── fastq/*\n\n*│ │ │ └── [cell\\_line]\\_[treatment]\\_[replicate]\\_[read].fastq.gz*\n\n*│ │ └── bam/*\n\n*│ │ └── [cell\\_line]\\_[treatment]\\_[replicate].bam*\n\n*│ └── miRNA\\_Seq/*\n\n*│ ├── fastq/*\n\n*│ │ └── [cell\\_line]\\_[treatment]\\_[replicate].fastq.gz*\n\n*│ └── bam/*\n\n*│ └── [cell\\_line]\\_[treatment]\\_[replicate].bam*\n\n*├── 02\\_Processed\\_Data/*\n\n*│ ├── mRNA\\_Seq/*\n\n*│ │ ├── counts/*\n\n*│ │ │ └── [cell\\_line]\\_[treatment]\\_[replicate]\\_counts.txt*\n\n*│ │ ├── expression\\_matrices/*\n\n*│ │ │ ├── counts\\_matrix.csv*\n\n*│ │ │ ├── tpm\\_matrix.csv*\n\n*│ │ │ └── fpkm\\_matrix.csv*\n\n*│ │ └── differential\\_expression/*\n\n*│ │ └── [comparison\\_group]\\_DESeq2\\_results.csv*\n\n*│ └── miRNA\\_Seq/*\n\n*│ ├── counts/*\n\n*│ │ └── [cell\\_line]\\_[treatment]\\_[replicate]\\_mirna\\_counts.txt*\n\n*│ ├── expression\\_matrices/*\n\n*│ │ ├── mirna\\_counts\\_matrix.csv*\n\n*│ │ └── mirna\\_rpm\\_matrix.csv*\n\n*│ └── differential\\_expression/*\n\n*│ └── [comparison\\_group]\\_mirna\\_DESeq2\\_results.csv*\n\n*├── 03\\_Analysis\\_Results/*\n\n*│ ├── QC/*\n\n*│ │ ├── mRNA\\_Seq\\_QC/*\n\n*│ │ └── miRNA\\_Seq\\_QC/*\n\n*│ ├── mRNA\\_Seq/*\n\n*│ │ ├── PCA/*\n\n*│ │ ├── clustering/*\n\n*│ │ ├── volcano\\_plots/*\n\n*│ │ └── pathway\\_analysis/*\n\n*│ ├── miRNA\\_Seq/*\n\n*│ │ ├── PCA/*\n\n*│ │ ├── clustering/*\n\n*│ │ └── target\\_analysis/*\n\n*│ └── Integrated\\_Analysis/*\n\n*│ ├── miRNA\\_mRNA\\_correlations.csv*\n\n*│ ├── network\\_analysis/*\n\n*│ └── pathway\\_enrichment/*\n\n*├── 04\\_Scripts/*\n\n*│ ├── R/*\n\n*│ │ ├── mRNA\\_analysis\\_pipeline.R*\n\n*│ │ ├── miRNA\\_analysis\\_pipeline.R*\n\n*│ │ └── integration\\_analysis.R*\n\n*│ └── Python/*\n\n*│ ├── network\\_analysis.py*\n\n*│ └── visualization.py*\n\n*└── 05\\_Interactive\\_Tools/*\n\n*├── RNA\\_Explorer.html*\n\n*└── README.txt*\n\n*File naming convention:*\n\n* *Cell line abbreviations: HCT (HCT116), LOVO (LOVO), SNU (SNU175), HT29 (HT29), COLO (Colo205)*\n* *Treatment abbreviations: CTRL (Control), GSK (GSK-1120212), IPP (4-IPP), COMBO (Combination)*\n* *Replicate numbers: R1, R2, R3*\n* *Read numbers (for paired-end): R1, R2*\n\n*Example: "HCT\\_GSK\\_R2\\_R1.fastq.gz" indicates HCT116 cell line, GSK-1120212 treatment, replicate 2, read 1.*\n\n### ***Key Findings Highlight***\n\n#### ***1. Novel Transcriptional Signature in KRAS-Mutant Cells***\n\n*Our analysis uncovered a transcriptional signature specific to KRAS-mutant cell lines treated with the combination of GSK-1120212 and 4-IPP. This signature was characterized by:*\n\n* *Downregulation of cell cycle progression genes*\n* *Upregulation of cellular stress response genes*\n* *Altered expression of immune modulatory genes*\n* *Coordinated changes in STAT3 pathway components*\n\n*This transcriptional program was largely absent in BRAF-mutant cell lines, suggesting a KRAS-specific response mechanism.*\n\n#### ***2. miRNA-Mediated Regulatory Networks***\n\n*We identified several miRNA-mediated regulatory networks that appear to be specifically modulated by combination treatment in KRAS-mutant cells:*\n\n* *miR-124-3p/STAT3 axis: Upregulation of miR-124-3p was associated with downregulation of STAT3 and its downstream targets. This regulation was more pronounced in combination-treated cells than with either agent alone.*\n* *miR-218-5p/CD74/MIF pathway: miR-218-5p, which targets the MIF receptor CD74, was significantly upregulated in combination-treated cells, potentially contributing to inhibition of MIF signaling.*\n* *miR-199a-5p/mTOR network: miR-199a-5p, a known regulator of mTOR signaling, showed synergistic upregulation in combination-treated cells, coinciding with downregulation of multiple mTOR pathway components.*\n\n*These miRNA-mediated networks may contribute to the synergistic effects observed in your previous cellular assays.*\n\n#### ***3. Feedback Mechanisms in MAPK Signaling***\n\n*Our analysis revealed complex transcriptional feedback mechanisms in MAPK signaling that differ between KRAS-mutant and BRAF-mutant cell lines:*\n\n* *BRAF-mutant cells showed strong transcriptional suppression of negative feedback regulators (DUSPs, SPRYs) upon MEK inhibition*\n* *KRAS-mutant cells maintained expression of these feedback regulators and showed compensatory upregulation of alternative MAPK pathway components*\n* *Combination treatment in KRAS-mutant cells disrupted this compensatory response, potentially explaining the synergistic growth inhibition*\n\n#### ***4. Potential Biomarkers of Response***\n\n*Through integrated analysis of mRNA and miRNA data, we identified several potential biomarkers that could predict response to combination therapy:*\n\n* *A 23-gene transcriptional signature*\n* *A 7-miRNA signature*\n\n*Both signatures show strong separation between responsive (KRAS-mutant) and non-responsive (BRAF-mutant) cell lines in principal component analysis.*\n\n### ***Next Steps and Recommendations***\n\n*Based on our analysis, we suggest the following next steps:*\n\n1. *Validation of key findings using qRT-PCR or NanoString for selected genes and miRNAs in additional cell line models or patient-derived samples*\n2. *Integration with proteomics data to build a comprehensive multi-omics view of response mechanisms*\n3. *Functional validation of key miRNA-mRNA interactions identified in our analysis, particularly those involving miR-124-3p, miR-218-5p, and miR-199a-5p*\n4. *Analysis of alternative splicing events as an additional potential mechanism of drug response (we can perform this analysis using your existing data if requested)*\n\n*We would be happy to discuss these recommendations in more detail and provide guidance on follow-up studies.*\n\n### ***Quality Assurance Statement***\n\n*All sequencing and analyses were performed according to SCD\'s standard operating procedures and quality control guidelines. The study was conducted in compliance with our CAP/CLIA certified laboratory practices.*\n\n*Sequencing Lead: Dr. Sarah Johnson, Senior Sequencing Scientist\nBioinformatics Lead: Dr. David Chen, Computational Biologist\nQC Review: Dr. Elizabeth Taylor, QC Manager\nProject Director: Dr. Michael Zhang, Director of Genomics Services*\n\n### ***Contact Information***\n\n*For technical questions regarding this report or additional analysis requests, please contact:*\n\n*Dr. Michael Zhang\nDirector, Genomics Services\nSequencing & Computational Diagnostics\nmichael.zhang@scdiagnostics.com\n617-555-7423*\n\n*For administrative inquiries:*\n\n*Client Services\nsupport@scdiagnostics.com\n617-555-7400*\n\n*This report contains confidential information and is intended solely for Pharma Discovery, Inc. Distribution, reproduction, or any use of this report or its contents by anyone other than the intended recipient is prohibited without prior written consent from Sequencing & Computational Diagnostics.*'
        verifier = QuoteVerifier(remove_stopwords=True)
        quote = verifier.verify_quote(text,
                                      "GSK-1120212 treatment altered the expression of 67 miRNAs in BRAF-mutant cell lines but only 21-28 miRNAs in KRAS-mutant cell lines")

        self.assertTrue(quote['verified'])


    # It's a match time problem, since there was a space which the quote didn't repeat. We'll fix it later.

    def test_complex_molecule(self):
        "3-(4,5-Dimethylthiazol-2-y1)-2,5-diphe nyltetrazolium bromide (MTT) assay and ELISA\nwere used to determine cell viability and cell proliferation"

        text ='[BioMed Central](http://www.biomedcentral.com/)\nPage 1 of 21\n(page number not for citation purposes)\nBMC Gastroenterology\nOpen AccessResearch article\nOver-expression of the mitogen-activated protein kinase (MAPK)\nkinase (MEK)-MAPK in hepatocellular carcinoma: Its role in tumor\nprogression and apoptosis\nHung Huynh*1, Thi Thanh Tuyen Nguyen1, Kah-Hoe Pierce Chow2,5, Puay\nHoon Tan3, Khee Chee Soo4,2 and Evelyne Tran1\nAddress: 1Laboratory of Molecular Endocrinology, Division of Cellular and Molecular Research, Singapore General Hospital, Singapore 169610,\n2National Cancer Centre of Singapore, Singapore General Hospital, Singapore 169610, 3Department of Pathology, Singapore General Hospital,\nSingapore 169610, 4Department of General Surgery, Singapore General Hospital, Singapore 169610 and 5Department of Experimental Surgery,\nSingapore General Hospital, Singapore 169610\nEmail: Hung Huynh* - cmrhth@nccs.com.sg; Thi Thanh Tuyen Nguyen - cmrnttt@nccs.com.sg; Kah-Hoe Pierce Chow - gsupc@sgh.com.sg; Puay\nHoon Tan - gpttph@sgh.com.sg; Khee Chee Soo - admskc@nccs.com.sg; Evelyne Tran - cmrhth@nccs.com.sg\n* Corresponding author\nAbstract\nBackground: Hepatocellular carcinoma (HCC) is one of the most common malignancies in South\nEast Asia. Although activation of the MEK-MAPK is often associated with cellular growth, the role\nof MEK-MAPK in growth and survival of hepatocarcinoma cells has not been established.\nMethods: Immuno-histochemistry was used to localize phosphorylated MAPK and MEK1/2 in the\ntissues. 3-(4,5-Dimethylthiazol-2-y1)-2,5-diphe nyltetrazolium bromide (MTT) assay and ELISA\nwere used to determine cell viability and cell proliferation. Deoxynucleotidyl transferase-mediated\ndUTP nick-end labeling (TUNEL) assay was used to detect apoptotic cells. Western blots analysis\nwas performed to determine the levels of proteins involved in the MEK-MAPK and apoptotic\npathways. Transfection study was performed to assess the role of MEK-MAPK pathway in growth\nand survival of liver cancer cells.\nResults: We report that phosphorylation of MEK1/2  at Ser217/221 was detected by immuno-\nhistochemistry in 100% (46 of 46) of HCCs examined. A positive signal was localized in the nuclei\nof hepatocarcinoma cells but not in dysplastic hepatocytes or stromal cells. Over-expression and\nphosphorylation of MAPK was al so detected in 91% (42 of 46)  and 69% (32 of 46) of HCCs\nexamined, respectively. The percentage of cell s showing positively fo r phosphorylated MEK1/2\nincreased with advancing tumor stage. In vitro, treatment of human HepG2 and Hep3B cells with\nMEK1/2 specific inhibitors U0126 and PD98059 led to growth inhibition and apoptosis. U0126\ninduced the release of cytochrome c and increased the cleavage of caspase-3, caspase-7, and poly\nADP-ribose polymerase (PARP). Inhibition of phosphatidylinosi tol 3-kinase (PI-3K), c-Jun N-\nterminal kinase (JNK) and p38 kinase activities caused only a mild apoptosis in HepG2 and Hep3B\ncells. Activated MEK1-transfected cells were  more resistant to UO126-induced apoptosis in vitro\nand formed larger tumors in SCID mice than mock-transfected cells.\nPublished: 08 August 2003\nBMC Gastroenterology 2003, 3:19\nReceived: 25 April 2003\nAccepted: 08 August 2003\n[This article is available from: http://www.biomedcentral.com/1471-230X/3/19](http://www.biomedcentral.com/1471-230X/3/19)\n© 2003 Hung et al; licensee BioMed Central Ltd. This is an Open Access article: verbatim copying and redistribution of this article are permitted in all\nmedia for any purpose, provided this notice is preserved along with the article\'s original URL.\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 2 of 21\n(page number not for citation purposes)\nConclusion: In conclusion, our results demonstrate th at MEK-MAPK plays an important role in\nthe growth and survival of live r cancer cells and suggest that blocking MEK-MAPK activity may\nrepresent an alternative approach for the treatment of liver cancer.\nBackground\nHCC is one of the most common malignancies in South\nEast Asia. The incidence of HCC is between 250,000 to 1,2\nmillion cases per year [1,2]. The disease is associated with\nenvironmental exposure to hepatitis B virus, hepatitis C\nvirus, and Aflatoxin B1 [1,2]. Treatment outcomes for\nHCC have remained generally poor. The majority of the\npatients with HCC have inoperable disease with a very\npoor prognosis [3]. Five-year survival rate is limited to 15\nto 39% after surgery [4,5]. Long-term survival is uncom-\nmon because of the frequency of recurrence in the form of\nmetastases or the development of new primaries [6,7].\nThere are also not currently accepted adjuvant or palliative\ntreatment modalities that have been conclusively shown\nto prolong survival in HCC [8].\nSeveral lines of evidence indicate that HCC may be the\nresult of inactivation of tumor suppressor genes, activa-\ntion of multiple oncogenes and over-expression of growth\nfactors. More than 20 cellular genes have been identified\nto be associated with HCC (Reviewed in [9]). They\ninclude Ras, c-myc, c-fos and c-jun, rho, transforming\ngrowth factor-α, hepatocyte growth factor and c-met, c-\nErbB-2, u-plasminogen activator, MXR7, MDM2, MAGE,\nmatrix metalloproteinase, Smads, p53, pRB, p16 INK4,\np21WAF1/CIP1, p27Kip1, PTEN, E-cadherin, β-catenin, AXIN1\nand HCCA1. We recently reported [10] that insulin-like\ngrowth factor (IGF) II (IGF-II) is over-expressed in approx-\nimately 39% of HCC samples. In addition, IGF binding\nprotein 3 (IGFBP-3) is either undetectable (28.5%) or low\n(71.5%) in HCCs examined compared with adjacent\nbenign liver (ABL) tissues.\nOne of the most frequent targets downstream of receptor\nand non-receptor tyrosine kinases and the ras family of\nGTP-binding proteins is the MEK-MAPK signal transduc-\ntion pathway [11,12]. Elevated levels of constitutively\nactivated MEK1 are seen frequently in carcinoma cell lines\n[13,14]. Constitutive MEK1 activation contributes to cell\nsurvival (Reviewed in [12]), migration [15], transforma-\ntion of fibroblasts and epithelial cells [16-18]. Studies\nwith small molecule inhibitors of MEK activity [19,20].\ndemonstrate a role for MEK in mediating expression of\nproteinases implicated in invasion and metastasis\n[21,22], and disruption of normal epithelial morphology\n[23,24]Treatment of HepG2 with PD98059 resulted in\napoptosis [25]. No substrates of MEK have been identified\nother than p44/42 MAPK (Reviewed in [26]). Increased\nMAPK (ERK1/2) and MEK1/2 expression and p42 MAPK\nin 5 HCC samples has been reported [27]. Treatment of\ncells with various growth factors produces activation of\nMEK1/2 and its downstream target, MAPK, resulting in\nproliferation, differentiation and survival\n(Reviewed in [12]). Activation of MAPK regulates the\nactivities of a number of substrates including transcription\nfactor p62TCF (Elk-1), c-myc, ATF2 and AP-1 components,\nc-Jun and c-fos [20]. MAPK is also involved in nuclear\ntransport, nucleosome assembly, and cytoskeletal regula-\ntion [28]. The tight selectivity of MEK1/2, coupled with its\nunique ability to phosphorylate both tyrosine and threo-\nnine residues of MAPK, indicates that this kinase is essen-\ntial in integrating signals into the MAPK pathway. Thus,\nMEK1/2 represents an excellent target for pharmacologi-\ncal intervention in proliferative disease [19,29,30]. Sev-\neral MEK-MAPK anticancer drugs are currently in clinical\ntrials [31].\nIn this study, we report that the protein MEK1/2 is acti-\nvated in 100% of HCCs examined. Tumor cells were the\nmain sites of activated MEK1/2 and MAPK proteins within\nHCCs and not the surrounding non-neoplastic tissues.\nOver-expression and hyperphosphorylation of MAPK\nwere detected in 91% and 69% of HCCs examined,\nrespectively. Treatment of HepG2 and Hep3B cells with\nU0126 led to a time and dose-dependent reduction in cell\nproliferation and apoptosis. Over-expression of activated\nMEK1 in HepG2 enhanced tumor growth in vivo and con-\nferred resistance to U0126-induced apoptosis in vitro. Our\ndata suggest that blocking MEK-MAPK activities may rep-\nresent a novel approach for the treatment of HCC.\nExperimental Procedures\nReagents\nU0126, PD98059 and LY294002 were supplied by New\nEngland Biolabs, Beverly, MA. p38 kinase inhibitor\nSB203580 and JNK inhibitor SP600125 were purchased\nfrom Calbiochem, San Diego, CA. They were dissolved in\ndimethylsulfoxide (DMSO) with the final concentration\nof 20 mM and stored frozen under light-protected condi-\ntions at -20°C. Antibodies against α-tubulin, rabbit anti-\np38 kinase, rabbit anti-phospho-p38 kinase (Tyr182),\nrabbit anti-JNK-2, rabbit anti-phospho-JNK (Thr183/\nTyr185), mouse anti-cytochrome c, mouse anti-MAPK,\nrabbit anti-Akt-1 and MEK-1 were obtained from Santa\nCruz Biotechnology, Santa Cruz, CA. Anti-cleaved form-\nspecific caspase-7 (20 kDa), caspase-3 and caspase-9, rab-\nbit anti-phospho Akt-1 (Ser473), phospho-specific anti-\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 3 of 21\n(page number not for citation purposes)\nMEK1/2 (Ser217/221), phospho-specific anti-MAPK\n(Thr202/Tyr204), and cleaved PARP (89 kDa) antibodies\nwere obtained from Cell Signaling Technology, Beverly,\nMA. Horseradish peroxidase-conjugated secondary anti-\nbodies were supplied by Pierce, Rockford, Illinois. The\nchemiluminescent detection system was supplied by\nAmersham, Pharmacia Biotech, Arlington Heights, IL. 96-\nwell plates, tissue culture petri-dishes and 8-chamber\nslides were from Nunc Inc., Naperville, IL. Cell Prolifera-\ntion ELISA, BrdU (colorimetric), In Situ Cell Death Detec-\ntion Kit and Fluorescein were supplied by Roche\nDiagnostics Corporation, Indianapolis, IN.\nPatients and tissue samples\nPrior written informed consent was obtained from all\npatients and the study received ethics board approval at\nthe National Cancer Centre of Singapore as well as the\nSingapore General Hospital. Tissue samples were\nobtained intra-operatively from tumors and ABL tissues\nduring liver resection for HCC in 46 patients at the Singa-\npore General Hospital. 14 of 46 resected samples had sin-\ngle tumor and 32 of 46 had two tumors. The samples were\nsnap frozen in liquid nitrogen and stored at -80°C until\nanalysis. A similar set of samples was fixed in 10% forma-\nlin and paraffin embedded. The diagnosis of HCC was\nconfirmed histologically in all cases.\nStaging of tumors was performed using the TNM system\n[32]. In addition, every tumor was examined macroscopi-\ncally and microscopically for capsule formation, satellite\nnodules, multiplicity and necrosis. Dysplasia and cirrho-\nsis in the surrounding liver tissue were noted. 15 of 46\ntumors were associated with cirrhosis. Within 15 cirrhotic\nHCCs, 12 showed dysplastic changes in adjacent non-\nneoplastic tissue. Multifocality was defined as multiple\nsmall uniformly sized tumors that likely represented inde-\npendent primary tumors [33]. This is distinguished from\nsatellites, which were defined as tumor nodules, smaller\nthan the main tumor mass, located within a maximum\ndistance of 2 cm. The term multiplicity was used for both\nmultifocal tumors and for multiple intrahepatic metasta-\nsis from a single primary tumor that were situated further\nthan 2 cm from the edge of the main tumor mass.\nImmunohistochemical analysis and assessment\nFor immunohistochemical analysis of MEK1/2 and MAPK\nor Ki-67, sections (5 µM thick) were cut, dewaxed, rehy-\ndrated and antigen retrieval as described [10]. After block-\ning endogenous peroxidase activity and reducing\nnonspecific background staining, the sections were incu-\nbated with the primary antisera against phosphorylated\nMEK1/2 (Ser217/221) or phosphorylated MAPK\n(Thr202/Tyr204) (overnight at 4°C). Immunohistochem-\nistry was performed using the streptavidin-biotin peroxi-\ndase complex method, according to the manufacturer\'s\ninstructions (Lab Vision, Fremont, CA) using AEC as the\nchromogen. Sections known to stain positively were incu-\nbated in each batch and negative controls were also pre-\npared by replacing primary antibody with preimmune\nsera. Only nuclear immunoreactivity was considered pos-\nitive. For phosphorylated MEK1/2, tumors were scored as\n1 (<1.0% of tumor cells positive); 2 (1–5% of tumor cells\npositive); 3 (5–10% of tumor cells positive) and 4 (>10%\nof tumor cells positive). To determine the rate of cellular\nproliferation in vivo, sections derived from tumor\nxenografts of mock-transfected and activated MEK1-tran-\nfected HepG2 cells were stained with anti-Ki-67 antibody.\nFive hundred tumor cells were counted in randomly cho-\nsen fields at ×400 magnification. The Ki-67 labelling\nindex was expressed as the number of clearly labelled Ki-\n67 reactive nuclei in 500 cells counted.\nCell viability and cell proliferation\nHuman hepatoma HepG2 and Hep3B cells were obtained\nfrom American Type Culture Collection (Rockville, Mary-\nland) and maintained as monolayer cultures in Modified\nEagle\'s Media (MEM) supplemented with 10% fetal\nbovine serum (growth medium). For study of prolifera-\ntion, confluent cultures of cells were trypsinized and\nplated at a density of 2.0 × 104 cells in 24-well plates with\ngrowth medium. After 48 h, the cell monolayer was rinsed\ntwice with phenol-red-free-serum-free MEM (PSF)\nmedium and incubated further in PSF medium for 24 h.\nAfter 24 h, various concentrations of U0126 (0, 2, 4, 6, 8\nand 10 µM) or 10 µM LY294002 or 50 µM PD98059 or 5\nµM SB203580 or 10 µM SP600125 in PSF medium were\nadded and incubated for 24 h or 48 h. Cell viability and\ncell proliferation were determined by the MTT assay [34]\nand Cell Proliferation ELISA, Bromo-deoxyuridine (BrdU)\nkit (Roche) respectively as described by the manufacturer.\nExperiments were repeated at least 3 times, and the data\nwere expressed as the mean ± SE.\nDetection of apoptotic cells\nHepG2 and Hep3B cells were grown in 8-chamber slides\nand treated with appropriate concentrations of U0126 in\nPSF medium for 48 h. Cells were fixed with phosphate\nbuffer saline (PBS) containing 4% formalin solution for 1\nhour at room temperature and washed with PBS. Apopto-\nsis was detected by TUNEL assay using the In Situ Cell\nDeath Detection Kit (Roche) as described by the manufac-\nturer. Apoptotic cells were then visualized under fluores-\ncent microscope equipped with an FITC filter. Labelling\nindices were obtained by counting cell number of labelled\ncells among at least 500 cells per region and expressed as\na percentage values.\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 4 of 21\n(page number not for citation purposes)\nPreparation of mitochondria-free cytosol for detection of\ncytochrome c release\nHepG2 or Hep3B were grown in the presence of indicated\nconcentrations of U0126 or PD98059 or SB203580 or\nSP600125 in PSF medium for 24 h or 48 h. Cells were har-\nvested, washed with ice-cold PBS. Mitochondria-free\ncytosol was prepared as described [35]. For detection of\ncytochrome c release, mitochondria-free cytosol was ana-\nlyzed by Western blot analysis as described [10].\nWestern Blotting\nTissue lysates from HCCs and ABL tissues as well as cell\nlysate were prepared as previously described [10]. Tissue\nor cell lysate or mitochondria-free cytosol was subjected\nto Western blot analysis as previously described [10].\nBlots were incubated with indicated primary antibodies\nand 1:7500 horseradish peroxidase-conjugated secondary\nantibodies. The blots were then visualized with a chemi-\nluminescent detection system (Amersham) as described\nby the manufacturer.\nStable activated MEK1 cell lines\nTo examine whether activated MEK was associated with\nthe growth and survival of liver cancer cells, HepG2 cells\nwere transfected with 5 µg of the pUSE-MEK1 (S218D/\nS222D) or pUSE control plasmid DNA and 28 µl of Lipo-\nfectamine reagent (Life Technologies) following the man-\nufacturer\'s recommendation. The pUSE-MEK1 (S218D/\nS222D) was the Ha-Tagged rat MEK1 (activated) cDNA\n(Upstate, Lake Placid, NY). The activating mutations were\nthe substitutions of aspartic acid for serine at residues 218\nand 222. Forty-eight hours post-transfection, cells were\nsubcultured at a ratio of 1:10 and replaced with selective\ngrowth medium containing 800 µg/ml G418 (Calbio-\nchem, La Jolla, CA). Four weeks post-transfection, individ-\nual clones were isolated, expanded and assayed for MEK1\nexpression by Western blot analysis using anti-HA tag\nantibody (1:1000 dilution). The phenotype of transfect-\nants expressing activated MEK1 was compared with that of\ncontrol pUSE plasmid. The proliferative behaviour of the\nclones and in vivo tumor formation were assayed.\nFor proliferation study, 2.5 × 10 4 cells were seeded per\nwell in 24-well plates containing MEM supplemented\nwith 10% fetal bovine serum. Cell number was counted\ndaily by hemocytometer for 5 days. Means were deter-\nmined from quadruplicate wells and in no case did stand-\nard deviation exceed 15% of the mean value.\nTumorigenicity in SCID mice\nMale SCID mice of 9–10 weeks of age were purchased\nfrom the Animal Resources Centre, Canning Vale, West\nAustralia. All mice were maintained according to the\n"Guide for the Care and Use of Laboratory Animals" pub-\nlished by National Institute of Health, USA. They were\nprovided with sterilized food and water ad libitum , and\nhoused in negative pressure isolators with 12 h light/dark\ncycles. 5 × 10 6 cells (2 mock-transfected clones, pUSE-9\nand pUSE-12; and 2 activated MEK1-transfected clones,\nH-MEK1-15 and H-MEK1-17) were suspended in calcium\nfree phosphate buffer saline and subcutaneously injected\non both sides of the SCID mice. Tumor growth was mon-\nitored at least twice weekly by vernier caliper measure-\nment of the length (a) and width (b) of tumor. Tumor\nvolumes was calculated as (a × b2)/2. Eight animals per\ngroup were used in three sets of independent experiments.\nAll mice were sacrificed when the tumors reached approx-\nimately 1 cm3. Tumors were harvested, fixed and paraffin\nembedded for determination of apoptosis and prolifera-\ntion. Differences in tumor incidence number and tumor\nvolume among groups were analyzed by ANOVA.\nStatistical analysis\nFor quantitation analysis, the sum of the density of bands\ncorresponding to protein blotting with the antibody\nunder study was calculated, and the amount of α-tubulin\nnormalized. For MAPK, phosphorylated MAPK, MEK1/2\nand phosphorylated MEK1/2, the mean of densitometric\nscanning in the adjacent benign tissues and tumors was\ndetermined. To estimate the specific increase in MEK or\nMAPK phosphorylation, the ratio of pMEK1/2/ MEK and\npMAPK/MAPK was calculated. Differences in cell number\nand the levels of protein under study were analyzed by\nANOVA.\nResults\nPathologic evaluation of the resected specimens showed\ncirrhosis without dysplasia (3 of 46) and with dysplasia\n(12 of 46) in adjacent non-neoplastic liver in 33% (15 of\n46) patients. Multiplicity of tumors was detected in 32\ncases (70%) with 2 or 3 HCC nodules. Satellite formation\noccurred in 26 (56%) patients. The overall observed 1-\nyear disease-free survival rate of all patients was 74% (34\nof 46). In this study, the median survival of all HCC\npatients studied and the 5-year survival rate was not\ncalculated.\nSince the MEK-MAPK pathway has been implicated in reg-\nulating cell growth and survival (Reviewed in [12]), the\nabundance of MAPK was determined in HCCs and ABL\ntissues. Figure 1 shows that the 42 and 44 kDa forms of\nMAPK were detected in both HCCs and ABL tissues. Eleva-\ntion of MAPK was detected in 91% (42 of 46) of HCCs\nexamined. Quantitative analysis revealed that HCCs had\napproximately 1.6-fold more MAPK than ABL tissues.\nWhen the blots were stripped and reblotted with anti-\nphosphorylated MAPK (active form of MAPK), 69% (32\nof 46) of HCCs displayed increased staining as compared\nwith ABL tissues (Fig. 1A, 1B &1C). The ratio of pMAPK/\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 5 of 21\n(page number not for citation purposes)\nMAPK protein and phosphorylated MAPK were markedly elevated in extract of HCCs as compared with ABL tissuesFigure 1\nMAPK protein and phosphorylated MAPK were markedly elevated in extract of HCCs as compared with ABL\ntissues. Human HCCs (T) and ABL tissues (N) were collected and tissue lysate was prepared as described under Experimen-\ntal Procedures. Samples (100 µg protein/sample) were subjected to Western blot analysis as described [10]. Blots were incu-\nbated with mouse anti-MAPK and mouse anti-phospho-MAP kinase (Thr202/Tyr204) (A, B and C) (A, B and C) and mouse\nanti-α-tubulin antibodies. The ratio of phosphorylated MAPK to MAPK is shown in (D). Bars with different letters are signifi-\ncantly different from one another at p < 0.01 as determined by ANOVA test. All the samples in A &B are paired and samples\nin C are individual.\n0\n0.1\n0.2\n0.3\n0.4\n0.5\n0.6\n0.7\nNT\nRatio of phospho-MAPK to MAPK\nN    T   N   T N  T    N T   N       T\n1 2345\nα-tubulin\n678 9\nN    T      N    T       N     T N   T\nα-tubulin\nα-tubulin\nA\nB\nC\n1 2 3 4 5 6 7 8 9 10 11 12 13 14\nPhospho-MAPK\nPhospho-MAPK\nPhospho-MAPK\nN T\nMAPK\nMAPK\nMAPK\na\nb\nD\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 6 of 21\n(page number not for citation purposes)\nMAPK was significantly higher (p < 0.01) in HCCs as com-\npared to ABL tissues as determined by ANOVA (Fig. 1D).\nSince increased MAPK phosphorylation may reflect activa-\ntion of MAPK via upstream signalling elements, the\namount of phospho MEK1/2 was determined in tissue\nextracts from both HCCs and ABL tissues. Immunostain-\ning of the blots displayed a marked increase in phosphor-\nylated MEK1/2 (Fig. 2A, 2B &2C). While MEK 1/2 was\nheavily phosphorylated on serine 217/221 in 100% (46/\n46) of HCCs, ABL tissues of the same patients showed lit-\ntle phosphorylated MEK1/2 under the same conditions\n(Fig. 2A, 2B &2C). Approximately 7-fold increase in\nMEK1/2 phosphorylation was detected in HCC as com-\npared with ABL tissues (Fig. 2D).\nHCC tumors are heterogeneous with respect to cell-type,\nand therefore it was critical to identify the cell-type\nresponsible for the elevation of phosphorylated MEK1/2\nand MAPK. A total of 46 HCCs and their ABL tissues were\nexamined by immunohistochemistry. An antibody spe-\ncific for phosphorylated MEK1/2 at serine (Ser217/221)\nwas used to stain the tissue sections. Figure 3A and 3B\nshow that intense staining was observed only in the nuclei\nof cancerous hepatocytes, some of which underwent\nmitotic division. No nuclear staining was observed in\nadjacent benign hepatocytes (Fig. 3A &3B). Bile duct epi-\nthelial cells were uniformly negative, as were the fibrovas-\ncular stroma within cirrhotic livers. A summary of the\nimmunohistochemical analysis of MEK1/2 phosphoryla-\ntion in human HCCs is shown in table 1. The percentage\nof cells showing positively for phosphorylated MEK1/2\nappears to increase with advancing tumor stage. When the\nabove tissues were stained using phosphorylated MAPK at\nthreonine 202 and tyrosine 204, a strong immunoreactiv-\nity of the tumor cells was observed in tumor nodules (Fig.\n3C &3D). Surrounding benign hepatocytes were weakly\npositive for phosphorylated MAPK (Fig. 3C &3D).\nThe immunohistochemistry and Western blot analysis of\nHCC samples suggested an important link between HCC\nand activation of the MEK-MAPK pathway. However, the\nrole of MEK-MAPK activation in hepatogenesis and sur-\nvival of hepatoma cells was not well understood. It has\nbeen shown that MEK-MAPK activation generally plays a\ncritical role in cell proliferation and apoptosis (Reviewed\nin [12]). It was reasoned that MEK-MAPK activation in\nHCCs might enhance tumor cell proliferation and sur-\nvival. To elucidate the role of MEK1/2 activation in the\ngrowth and survival of hepatocarcinoma cells, we chal-\nlenged human HepG2 cells with either vehicle or 10 µM\nof highly selective MEK1/2 inhibitor U0126 or 50 µM of\nPD98059. To serve as controls, HepG2 cells were also\ntreated with 5 µM of p38 kinase inhibitor SB203580 or 10\nµM of JNK inhibitor SP600125 or 10 µM of PI-3 kinase\ninhibitor LY294002. Figure 4 demonstrates that U0126\nand PD98059 inhibited phosphorylation of MAPK while\nSB203580, SP600125 and LY294002 effectively blocked\nphosphorylation of p38 kinase and JNK and Akt-1 respec-\ntively (Fig. 4A). While SB203580, SP600125 and\nLY294002 had a little effect on cell viability as determined\nby the MTT assay, both U0126 and PD98059 significantly\ndecreased the cell viability in HepG2 cells (Fig. 4B). Simi-\nlar effects were observed when Hep3B were used (data not\nshown).\nBecause HepG2 and Hep3B cells responded similarly to\nU0126 or PD98059, subsequent experiments were mainly\nperformed on HepG2 cells. For the time-course and dose-\nresponse experiments, HepG2 cells were treated with 0, 2,\n4, 6, 8 and 10 µM U0126 in serum free medium for 24 h\nand 48 h. Cell viability and cell growth were then assessed\nby the MTT assay and BrdU incorporation, respectively.\nFigure 5 shows that U0126 caused a dose-dependent\nreduction in cell growth and viability. Significant inhibi-\ntion in cell viability was observed as early as 24 hours\npost-treatment. The effects were more pronounced and\ndose-dependent at 48 h of treatment (Fig. 5B). Fifty-per-\ncent inhibitions in cell growth and viability were detected\nat a dose of 4 µM U0126. The influence of U0126 on cell\ngrowth and viability occurred at the dose expected to sup-\npress phosphorylation of MAPK (Fig. 8). Another\nhepatoma cell line of human origin PLC/PRF/S was also\ninhibited by U0126 treatment in a similar manner (data\nnot shown).\nPhase-contrast photomicrographs revealed that U0126-\ntreated HepG2 cells displayed typical features of apopto-\nsis: shrinkage of cytoplasm and membrane blebbing (Fig.\n6). To assess if the cell death observed above represented\napoptosis, TUNEL assay was performed. While LY294002,\nSB203580 and SP600125 caused a little cell death (data\nnot shown), U0126 induced apoptosis in a dose-depend-\nent manner (Fig. 7 &8B).\nSince cytochrome c release plays a major role in mediating\napoptosis in several experimental systems [36-38], we\ndetermined whether U0126-induced apoptosis in HepG2\ncells was associated with cytochrome c release in the cyto-\nplasm. Figures 4 shows that levels of cytochrome c in the\ncytoplasm of HepG2 cells were significantly increased fol-\nlowing U0126 or PD98059 treatment. Since the proteo-\nlytic cleavage of caspase-3 and caspase-7 plays a central\nrole in PARP cleavage during apoptosis [39], we investi-\ngated whether this apoptosis machinery was activated\nupon U0126 or PD98059 treatment. The activation of\nthese two caspases and cleaved PARP were determined by\nWestern blot analysis using antibodies capable of detect-\ning cleaved caspase-3, caspase-7 and PARP. Cleaved cas-\npase-7 and cleaved caspase-3 fragments were detectable at\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 7 of 21\n(page number not for citation purposes)\nPhosphorylated MEK1/2 was elevated in extract of HCCs as compared with ABL tissuesFigure 2\nPhosphorylated MEK1/2 was elevated in extract of HCCs as compared with ABL tissues. Human HCCs (T) and\nABL tissues (N) were collected and tissue lysate was prepared as described in Experimental Procedures. Samples (100 µg pro-\ntein/sample) were subjected to Western blot analysis as described [10]. Blots were incubated with rabbit anti-phospho-MEK1/\n2 (Ser217/221), mouse anti-α-tubulin and rabbit anti-MEK1 antibodies (A, B and C). The ratio of phosphorylated MEK1/2 to\ntotal MEK is shown in (D). Bars with different letters are significantly different from one another at p < 0.01 as determined by\nANOVA test. All the samples in A &B are paired and samples in C are individual.\nD\nA\nPhospho-MEK1/2\nα-tubulin\nN     T   N       T N  T  N   T N   T\n1 2345\nMEK1\nPhospho-MEK1/2\n67 8 9\nN        T        N    T       N    T  N       T\nα-tubulin B\nMEK1\nPhospho-MEK1/2\nα-tubulin\nC\n12 3 4 5 6 7 8 9 1 0 1 1 1 2 1 3 1 4\nN T\nMEK1\n0\n0.1\n0.2\n0.3\n0.4\n0.5\n0.6\n0.7\n0.8\n0.9\nNT\nRatio of phospho-MEK1/2 to MEK1/2\na\nb\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 8 of 21\n(page number not for citation purposes)\n24 and 48 hours of U0126 treatment and increased in a\ndose-dependent manner (Fig. 8A). The cleaved caspase-7\nand -3 were detected at similar time course as PARP cleav-\nage (Fig. 8A). In contrast, blocking PI-3 kinase, p38 kinase\nand JNK activities by LY294002, SB20358 and SP600125\nrespectively abolished the phosphorylation of Akt-1, p38\nkinase and JNK without affecting the levels of cleaved cas-\npase-3 and -7 (Fig. 4A). Furthermore, the levels of cyto-\nchrome c released from mitochondria and PARP cleavage\nwere only slightly elevated following LY294002 or\nSB20358 or SP600125 treatment (Fig. 4A) indicating that\nMEK-MAPK but not PI-3 kinase or p38 or JNK plays a crit-\nical role in HepG2 cell survival under serum deprivation.\nSince our in vitro study indicated that MEK1/2 activity was\nrequired for the survival of liver cancer cells, transfection\nstudies were performed to determine whether over-\nexpression of MEK-MAPK would protect cells from\nU0126-induced apoptosis and enhance tumor growth in\nvivo. HepG2 cells were transfected with Ha-Tagged rat\nMEK1 (activated) cDNA. The activating mutations were\nthe substitutions of aspartic acid for serine at residues 218\nand 222. As shown in figure 9B, HA-MEK1 expression was\ndetected in representative transfected clones (H-MEK1-5,\nH-MEK1-15, H-MEK1-16 and H-MEK1-17). Basal levels\nof phosphorylated MAPK were also higher in activated\nMEK1-transfected clones compared with mock pUSE-\ntransfected clones, pUSE-9 and pUSE-12 (Fig 9D). Since\nImmunohistochemical demonstration of phosphorylated MEK1/2 and MAPK in malignant and adjacent benign hepatocytesFigure 3\nImmunohistochemical demonstration of phosphorylated MEK1/2 and MAPK in malignant and adjacent benign\nhepatocytes. Human HCCs (T) and ABL tissues (N) were collected and paraffin blocks were prepared as described under\nExperimental Procedures. 5 µm sections were subjected to immunohistochemical analysis as described under Experimental\nProcedures. The sections were stained with primary antibody to phospho-MEK1/2 (Ser217/221) (A &B) or mouse anti-phos-\npho-MAP kinase (Thr202/Tyr204) (C &D) antibodies. Original magnification ×400.\nA B\nC D\nN\nT\nN\nN\nN\nT\nT\nT\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 9 of 21\n(page number not for citation purposes)\nthe MEK-MAPK pathway has been implicated in regulat-\ning cell growth (Reviewed in [12]), the proliferative\nbehavior of H-MEK1-15, H-MEK1-17, pUSE-9 and pUSE-\n12 clones was evaluated by determining cell number on\nplastic dishes daily for 5 days. As shown in figure 9E, there\nwas no significant increase in cell number in activated\nMEK1-transfectant cells compared with mock-transfected\ncells. The results suggest that over-expression of activated\nMEK1 did not alter growth rate of HepG2 cells in culture.\nSince constitutive MEK1 activation contributes to cell sur-\nvival (Reviewed in [12]), we wished to determine if con-\nstitutive activation of MEK-MAPK in HepG2 cells would\nmake the cells more resistant to U0126-induced apopto-\nsis. Mock-transfectant pUSE-9 and activated MEK1-15\nclones were selected for this study. They were treated with\n0, 2, 4, 6 and 8 µM U0126 for 24 h. Because cleaved cas-\npase-3 and -7 and PARP has been proposed as one of the\nevents in the execution phase of apoptosis, the levels of\ncleaved caspase-3, -7 and PARP were used as markers for\napoptosis. As shown in figures 10, cleaved caspase-3, -7\nand PARP were readily detected in pUSE-9 cells at a dose\nas low as 4 µM. In contrast, these apoptotic markers were\nnot detected in the H-MEK-15 cells at low doses of U0126.\nThey became visible only at a dose of 8 µM. Similar results\nwere obtained when the H-MEK1-17 clone was used (data\nnot shown). These results further supported the important\nrole of activated MEK-MAPK in the survival of liver cancer\ncells.\nTo test the neoplastic behaviour of activated MEK1 cells in\nvivo, mock-transfected pUSE-9 and pUSE-12 and activated\nMEK1-transfected pMEK1-15 and pMEK1-17 clones were\ninjected in the flanks of SCID mice. Tumor formation was\ndetected in 40–45 and 55–60 days for activated MEK1-\ntransfected (H-MEK-15, H-MEK-17) and mock-trans-\nfected (pUSE-9, pUSE-12) clones respectively. By day 60,\ntumor incidence was 100% in both mock-transfected\nclones (pUSE-9 and pUSE-12) and two activated MEK1\nclones (H-MEK1-15 and H-MEK1-17). However, both the\nH-MEK1-15 and H-MEK1-17 clones grew much faster\nthan the pUSE-9 and pUSE-12 clones (Fig. 11). The final\ntumor volume was 270 ± 30 mm 3 and 309 ± 25 mm3 for\npUSE-9 and pUSE-12 mock transfected clones respectively\nand 1,210 ± 49 mm3 and 1,034 ± 54 mm3 for H-MEK1-15\nand H-MEK1-17 clones respectively. Differences in tumor\nvolume between mock-transfected and activated MEK1-\ntransfected clones were statistically significant at p < 0.01\nas analyzed in the ANOVA-test. To determine whether the\nincreased growth rate of HepG2-MEK1 tumors was due to\nincrease in cell proliferation, Ki-67 labelling index was\nperformed. As shown in figure 12, the Ki-67 labelling\nindex was slightly but significantly higher in HepG2-MEK-\n1 than HepG2-mock tumors (p < 0.05). The results sug-\ngest that over-expression of activated MEK1 enhances the\nsurvival and to a lesser extent, the proliferation of HepG2\ncells in vivo.\nDiscussion\nMolecular genetic and biochemical studies of HCC have\nrevealed abundant evidence for aberrant growth factor\nTable 1: A summary of immunohistochemical analysis of MEK1/2 and its phosphorylation at Ser217/221 in human HCC. Human HCCs\n(T) and adjacent benign liver (ABL) tissues (N) were collected, paraffin blocks were prepared and immunohistochemical analysis was\nperformed as described under Experimental Procedures. Tissue sections were stained with anti-phospho-MEK1/2 (Ser217/221)\nantibody. Only nuclear immunoreactivity was considered positive. Sections were scored as 1 (<1.0% of tumor cells positive); 2 (1–5% of\ntumor cells positive); 3 (5–10% of tumor cells positive) and 4 (>10% of tumor cells positive).\nGenes examined Normal adjacent Liver\ntissues (n = 46)\nHCC Tumours (n = 46)\nStages\nII I I I I I V\n(n = 4) (n = 25) (n = 11) (n = 6)\nMEK 1/2 46/46 (100%) 4/4 (100%) 25/25 (100%) 11/11 (100%) 6/6 (100%)\nPhosphorylated MEK 1/2 Score\n(% of positive cells)\n0/0 (0%)\n1 (< 1.0) 0 2/4 (50%) 20/25 (80%) 4/11 (36.36%) 1/6 (16.67%)\n2 (1 – 5) 0 - 4/25 (16%) 4/11 (36/36%) -\n3 (5 – 10) 0 1/4 (25%) 1/25 (4%) 1/11 (9.09%) 3/6 (50%)\n4 (>10) 0 1/4 (25%) - 2/11 (18.19%) 2/6 (33.33%)\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 10 of 21\n(page number not for citation purposes)\nEffects of MEK1/2 inhibitor U0126 or PD98059, p38 kinase inhibitor SB203580, JNK inhibitor SP600125 and PI-3 kinase inhibi-tor LY294002 on cell viability, MAPK, Akt-1, phosphorylation of MAPK (Thr202/Tyr204), phosphorylation of Akt-1 (Ser473), p38 kinase, phosphorylation of p38 kinase (Tyr182), JNK, phosphorylation of JNK (Thr183/Tyr185), cytochrome c release, and cleavage of caspase 3, caspase 7 and PARP in HepG2 cellsFigure 4\nEffects of MEK1/2 inhibitor U0126 or PD98059, p38 kinase inhibitor SB203580, JNK inhibitor SP600125 and PI-\n3 kinase inhibitor LY294002 on cell viability, MAPK, Akt-1, phosphorylation of MAPK (Thr202/Tyr204), phos-\nphorylation of Akt-1 (Ser473), p38 kinase, phosphorylation of p38 kinase (Tyr182), JNK, phosphorylation of\nJNK (Thr183/Tyr185), cytochrome c release, and cleavage of caspase 3, caspase 7 and PARP in HepG2 cells.\nCells were grown and treated with 0.1% of DMSO (C) or 10 µM of U0126 (U0) or 10 µM of LY294002 (LY) or 50 µM of\nPD98059 (PD) or 5 µM of SB203580 (SB) or 10 µM of SP600125 (SP) in phenol red free serum free MEM (PSF) medium for\n48 h as described under Experimental Procedures. Total cell lysate (for detection of all proteins except cytochrome c) or\nmitochondria free cytosol (detection of cytochrome c) from HepG2 (A) cells was subjected to Western blot analysis as\ndescribed under Experimental Procedures. Blots containing total cell lysate were incubated with mouse anti-α-tubulin, mouse\nanti-phospho-MAPK (Thr202/Tyr204), rabbit anti-Akt-1, rabbit anti-phospho Akt-1 (Ser473), rabbit anti-p38, rabbit anti-phos-\npho-p38 (Tyr182), rabbit anti-JNK1/2, rabbit anti-phospho-JNK1/2 (Thr183/Tyr185), rabbit anti-caspase-3, rabbit anti-cleaved\ncaspase-7 (20 kDa), rabbit anti-cleaved PARP antibodies. Blots containing mitochondria free cytosol were blotted with mouse\nanti-cytochrome c antibody. All the antibodies were used at a final concentration of 1 µg per ml. (B) Cell viability of HepG2\nfollowing different treatments was analyzed by MTT assay as described under Experimental Procedures. Bars with different let-\nters are significantly different from one another at (p < 0.01) as determined by ANOVA test. The results represent the mean\nof 3 experiments ± SE is shown.\n0\n0.2\n0.4\n0.6\n0.8\n1\n1.2\n1.4\n1.6\n1.8\nCU 0 L Y P D S B S P\nAbsorbance at 570 nm\nα-tubulin\nCytochrome c\nCleaved caspase 7 (20 kDa)\nCleaved caspase 3 (19 kDa)\nCleaved caspase 3 (17 kDa)\nCleaved PARP\n0.1% DMSO\n10 µM U0126\n10 µM  LY294002\n+ + +\n+\n+\n-\n- -\n-\nA\nB\nAkt-1\nPhospho-Akt-1\nMAPK\nPhospho-MAPK\np38\nPhospho-p38\nJNK1/2\nPhospho-JNK1/2\n+ + +\n-\n-\n-\n- -\n-\n50 µM PD98059\n5 µM SB203580\n10 µM  SP600125\n- - -\n-\n-\n-\n- -\n-\n+ - -\n+\n+\n-\n- -\n-\na\nb\na\nb\na a\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 11 of 21\n(page number not for citation purposes)\nEffects of U0126 on HepG2 cell viability and proliferationFigure 5\nEffects of U0126 on HepG2 cell viability and proliferation. HepG2 cells were grown and treated with 0.1% DMSO or\nescalating doses of U0126 in PSF medium. Cell proliferation and cell viability were determined by BrdU incorporation and MTT\nassay, respectively as described under Experimental Procedures. HepG2 cell proliferation at 48-h (A) and cell viability at 24 and\n48 h (B) are shown. Experiments were performed in quadruplicate, with the results reflecting the mean of the quadruplicate of\neach group. Bars with different letters are significantly different from one another at (p < 0.01) as determined by ANOVA test.\nThe results represent the mean of 3 experiments ± SE is shown.\n0\n0.2\n0.4\n0.6\n0.8\n1\n1.2\n1.4\n024681 0\n24h\n48ha\nb b b b b\na\nb\nc\nc dc d\nd\nMTT Assay (Absorbance at 570 nm)\nµM  U0126\nB\na\nb\nc\nd d d\nBrdU Incorporation(Absorbance at 370 nm)0                2 4                6               8  10\nµM UO126\n0\n0.2\n0.4\n0.6\n0.8\n1.0 A\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 12 of 21\n(page number not for citation purposes)\nsignalling, thus implicating downstream signalling path-\nways in HCC pathogenesis. Immunohistochemical appli-\ncation of a phospho-state specific antibody MEK1/2 and\nMAPK enables the morphological imaging of dynamic\nintratumor signalling events. Using phospho-specific\nMEK1/2 antibody we demonstrate significant activation\nof MEK1/2 in 100% (46 of 46) of HCC tumors at both\nearly and late stages of malignancy. Only tumor cells\nexhibit elevated MEK1/2 phosphorylation. Consistent\npatterns of selective activation in tumor cells suggest that\nactivation of MEK1/2 may contribute to the neoplastic\nliver phenotype. This in vivo analysis of active MEK1/2 and\nMAPK in human HCCs, reported herein, reveals sharply\nelevated activities of these proteins. The activation of\nMAPK observed in HCCs could not be ascribed solely to\nphosphorylation of the protein. Immunoblotting reveals\na marked increase in the amount of MAPK in 91% (42 of\n46) of HCCs when compared with adjacent benign liver\ntissues. The results are consistent with an early observa-\ntion by Schmidt et al. [27] who demonstrated that MAPK\nexpression and p42 MAPK activity were significantly\nhigher in 5 HCCs examined as compared with 5 adjacent\nnormal control tissues. Treatment of human liver cancer\ncells with MEK1/2 inhibitor U0126 or PD98059, which\ninhibits MEK-MAPK activation, leads to a time- and dose-\ndependent reduction in cell proliferation and viability.\nOur data are in agreement with previous study [25] show-\ning that in vitro treatment of HepG2 with MEK inhibitor\nPD98059 resulted in apoptosis. Furthermore, over-expres-\nsion of activated MEK1 in HepG2 enhances tumor growth\nEffects of U0126 on HepG2 cell morphologyFigure 6\nEffects of U0126 on HepG2 cell morphology. HepG2 cells were grown and treated with either 0.1% DMSO or 3 doses\nof U0126 in PSF medium for 48 h as described under Experimental Procedures. Bright field views of cells treated with 0.1%\nDMSO (A) or 2 (B), 4 (C), and 6 (D) µM of U0126 for 48 hours. Representative samples are shown. Original magnification,\n×200.\nA\nC\nB\nD\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 13 of 21\n(page number not for citation purposes)\nin vivo and confers resistance to U0126-induced apoptosis\nimplicating the requirement of MEK-MAPK activity for\nliver cancer cells to survive and tumor growth in vivo .\nAlthough the etiology and pathogenesis of HCC remain\nunclear, our observation suggests a role for the MEK-\nMAPK regulatory network. It remains to be determined to\nwhat extent MEK-MAPK represents a common point of\nactivation by agents promoting HCC cell proliferation or\nwhether MEK-MAPK is itself a critical element in the etiol-\nogy or pathogenesis of HCC.\nThe presence of highly activated MEK1/2 in high grade\nHCCs suggests that MEK activation may tie into malig-\nnant progression of liver cancer. In the present study, we\nshow that over-expression of activated MEK1 in HepG2\ncells does not alter the growth rate of HepG2 cells in vitro.\nHowever, over-expression of activated MEK1 enhances\ntumor growth in vivo and confers drug resistance in vitro.\nThis is in agreement with early studies demonstrating that\ntransient expression of active MEK1 into HepG2 pre-\nvented apoptosis in serum-deprived condition [25].\nBecause the in vitro growth rate is similar between pUSE-\ntransfected cells and activated MEK1-tranfected cells, sus-\nceptibility to apoptosis and low basal MAPK phosphoryla-\ntion may explain in part by the slower growth of the\nmock-transfected cells than activated MEK1-transfected\ncells in SCID mice. We also noticed that both HepG2-\nmock and HepG2-MEK1-transfected cells grew slowly for\nthe first 40 days in SCID mice, then HepG2-MEK1 tumors\ngrew faster. The long latent period in tumors expressing an\nInduction of apoptosis by U0126 treatment in HepG2 cellsFigure 7\nInduction of apoptosis by U0126 treatment in HepG2 cells. HepG2 cells were grown and treated with either 0.1%\nDMSO (A) or 2 (B), 4 (C) and 6 (D) µM of U0126 in PSF medium for 48 h. Apoptotic cells were determined by TUNEL assay\nas described under Experimental Procedures. Apoptotic cells in 0.1% DMSO and U0126-treated samples were visualized under\na fluorescent microscope. Representative samples are shown. Original magnification, ×200.\nA B\nC D\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 14 of 21\n(page number not for citation purposes)\nEffects of MEK1/2 inhibitor U0126 on MAPK, phospho-MAPK (Thr202/Tyr204), cytochrome c release, and cleavage of caspase 3, caspase 7 and PARP in HepG2 cellsFigure 8\nEffects of MEK1/2 inhibitor U0126 on MAPK, phospho-MAPK (Thr202/Tyr204), cytochrome c release, and\ncleavage of caspase 3, caspase 7 and PARP in HepG2 cells. HepG2 cells were cultured as described under Experimen-\ntal Procedures. Cells were incubated with PSF medium containing 0.1% DMSO or indicated concentrations of U0126 for 24 h\nor 48 h. Total cell lysate (for detection of cleaved caspase 3, cleaved caspase 7, cleaved PARP, and α-tubulin) or mitochondria\nfree cytosol (for detection of cytochrome c) was prepared for Western blot analysis as described under Experimental Proce-\ndures (A). Blots containing cell lysate were incubated with mouse anti-α-tubulin, mouse anti-MAPK, mouse anti-phospho-\nMAPK (Thr202/Tyr204), rabbit anti-caspase 3, rabbit anti-cleaved caspase 7, rabbit anti-cleaved PARP antibodies. Blots contain-\ning mitochondria free cytosol were blotted with mouse anti-cytochrome c antibody. All the antibodies were used at a final con-\ncentration of 1 µg per ml. Apoptotic cells were determined by TUNEL assay 48 h post-UO126 treatment as described under\nExperimental Procedures. Apoptotic cells were expressed as a percentage of total cells counted (B). Representative samples\nare shown.\n0\n10\n20\n30\n40\n50\n60\n70\n80\n90\n024681 0\nα-tubulin\nCytochrome C\nCleaved caspase 7 (20 kDa)\nCleaved caspase 3 (19 kDa)\nCleaved caspase 3(17 kDa)\nCleaved PARPRate of apoptosis\n(percentage of total cells counted)\nµM U0126\na\nb\nc\nd\ne\nf\n02468 1 0 02468 1 0\nµM U0126 (24 h treatment)µM U0126 (48 h treatment)\nA\nB\nMAPK\nPhospho-MAPK\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 15 of 21\n(page number not for citation purposes)\nWestern blot analysis for levels of HA-MEK1 and phosphorylated MAPK and in vitro growth of transfectant clonesFigure 9\nWestern blot analysis for levels of HA-MEK1 and phosphorylated MAPK and in vitro growth of transfectant\nclones. For detection of HA-MEK1 and phosphorylated MAPK, mock-transfectant (pUSE-9 and pUSE-12) and activated MEK1-\ntransfectant (H-MEK1-5, H-MEK1-15, H-MEK1-16 and H-MEK1-17) clones were grown and total cell lysate was prepared for\nWestern blot analysis as described under Experimental Procedures. Blots were incubated with mouse anti-α-tubulin (A), rab-\nbit anti-HA-MEK1 (B), mouse anti-MAPK (C), mouse anti-phospho-MAPK (Thr202/Tyr204) antibodies (D). All the antibodies\nwere used at a final concentration of 1 µg per ml. For proliferation study, pUSE-9, pUSE-12, H-MEK1-15, H-MEK1-17 clones\nwere seeded at a density of 2.5 × 104 cells per well in 24-well plates containing MEM supplemented with 10% fetal calf serum.\n(E) Cell number was counted daily by hemocytometer for 5 days and is plotted against number of days. Means were deter-\nmined from quadruplicate wells and in no case did standard deviation exceed 15% of the mean value.\nHA-tag\npMAPK\nA\nB\nC\nα-Tubulin\npUSE pUSE-MEK1\nClones 9           12 5          16         17       15\nE\n0\n50\n100\n150\n200\n250\n12345\nDays\npUSE-9\nUSE-12\nH-MEK1-15\nH-MEK1-17\nCellnumber(104)\nMAPK\nD\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 16 of 21\n(page number not for citation purposes)\nactive MEK1 may reflect a need of MEK1-expressing cells\nto generate neovascularization or may be due to low basal\nlevel of MAPK phosphorylation and weak induction that\nactive MEK1 induces.\nIn the present study, the more focal pattern of MEK-MAPK\nobserved in HCC nodules may reflect local autocrine/\nparacrine signalling. It has been observed that paclitaxel\n[40] or cisplatin [41] preferentially induced phosphoryla-\ntion of p42 MAPK (ERK2) while phosphorylation of p44\nMAPK was found during EGF- [42], PDGF- [29] and ara-\nchidonic acid- [43] induced MAPK activation. Thus, the\nwidespread activation of MEK1/2 and phosphorylation of\np44 MAPK (ERK1) observed in HCCs could reflect consti-\ntutive activation mediated by absence of growth inhibitor\n[10] or over-expression of ras [44], IGF-II [10], TGF- α\n[45], HGF, c-met [46], and Shc [47]. Activation of MEK-\nMAPK by autocrine/paracrine growth factors may help the\ncells to survive even in the presence of limited nutrients\nand to increase the secretion of angiogenic factors from\nthe tumor cells [48,49]In vivo , these angiogenic factors\nthen stimulate neovascularization, which is essential for\ngrowth, survival, invasion and metastasis of liver cancer\ncells.\nIn the present study, activated MAPK is predominantly\nlocalized in the cytoplasm. It has been reported that\nMAPK has cytoplasmic substrate in addition to the better-\ncharacterized nuclear transcription factors [50,51]. Poten-\ntial cytoplasmic substrates of MAPK include cytoskeletal\nelements and regulatory enzymes, including microtubule-\nassociated proteins and myosin light chain kinase. [52,53]\nEffects of MEK1/2 inhibitor U0126 on MAPK, phospho-MAPK (Thr202/Tyr204), and cleavage of caspase 3, caspase 7 and PARP in pUSE-9 and H-MEK1-15 clonesFigure 10\nEffects of MEK1/2 inhibitor U0126 on MAPK, phospho-MAPK (Thr202/Tyr204), and cleavage of caspase 3, cas-\npase 7 and PARP in pUSE-9 and H-MEK1-15 clones. pUSE-9 and H-MEK1-15 cells were cultured as described under\nExperimental Procedures. Cells were incubated with PSF medium containing 0.1% DMSO or indicated concentrations of\nU0126 for 24 h. Total cell lysate was prepared for Western blot analysis as described under Experimental Procedures. Blots\ncontaining total cell lysate were incubated with mouse anti-α-tubulin (A), mouse anti-MAPK (B), mouse anti-phospho-MAPK\n(Thr202/Tyr204) (C), rabbit anti-caspase 3 (D), rabbit anti-cleaved caspase 7 (E), rabbit anti-cleaved PARP (F) antibodies. All\nthe antibodies were used at a final concentration of 1 µg per ml. Representative blots are shown.\nCleaved caspase-3\nα-Tubulin\nCleaved caspase-7\npMAPK\nCleaved-PARP\nMAPK\nA\nB\nC\nD\nE\nF\n0     2     4        6         8      0         2        4   6 8\npUSE-9 pUSE-MEK1-15\nµM U0126\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 17 of 21\n(page number not for citation purposes)\nThus, our observation of significant cytoplasmic activated\nMAPK in neoplastic cells suggests possible nontranscrip-\ntional roles, such as the regulation of cytoarchitecture and\ncell motility.\nIn the present study we are unable to co-localize activated\nMAPK and MEK1/2. While phosphorylated MEK1/2 was\nlocalized in mitotic cells (those with nuclear phosphor-\nylated MEK1/2 immunolabelling), phosphorylated\nMAPK is found in every cell in the tumor nodule. Further-\nmore, activated MAPK is detected only in 69% (32 of 46)\nof HCCs examined, while activated MEK1/2 is in 100% of\ntumors. This observation is consistent with a previous\nreport [54] showing absent or diminished MAPK phos-\nphorylation in mitotic tumor cells. It is also possible that\nchanges in MAPK phosphorylation are rapid. The time\nfrom the tumor removal to the time when the tumor is\nfrozen or fixed may have been too long. This may explain\nour failure to co-localize activated MAPK in certain tumor\nsamples.\nAlthough it is well documented that apoptosis is also reg-\nulated by the Bcl-2 family of proteins [55], we do not\ndetect any significant changes in the levels of Bax, Bad,\nBcl-2 and Bcl-x L followed by U0126 treatment (data not\nshown). Previous studies have shown that p90Rsk is acti-\nvated by the MEK-MAPK [56-60]. Activated p90Rsk can\nphosphorylate Bad and prevent its proapoptotic activity\nIn vivo growth of activated MEK1 tranfected cellsFigure 11\nIn vivo growth of activated MEK1 tranfected cells. Mock transfected (pUSE-9 and pUSE-12) and activated MEK1 (H-\nMEK1-15 and H-MEK1-17) clones were subcutaneously injected on both flanks of male SCID mice as described under Experi-\nmental Procedures. Tumor growth was measured and calculated as described under Experimental Procedures. Tumor volume\nat a given time for mock transfected clones and activated MEK1-transfected clones is plotted and shown. Differences in tumor\nvolume between mock-transfected and activated MEK1-transfected clones were statistically significant at p < 0.01 as analyzed\nby ANOVA test.\nTum\nourvolum\ne\n(m\nm\n3)\n0\n200\n400\n600\n800\n1000\n1200\n1400\n60 65 70 80 85 90\nDays (Post-injection)\npUSE-9\npUSE-12\nH-MEK1-15\nH-MEK1-17\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 18 of 21\n(page number not for citation purposes)\nImmunostaining of Ki-67 in HepG2-mock (pUSE-9 and pUSE-12) and HepG2-MEK1 (H-MEK1-15 and H-MEK1-17) tumorsFigure 12\nImmunostaining of Ki-67 in HepG2-mock (pUSE-9 and pUSE-12) and HepG2-MEK1 (H-MEK1-15 and H-MEK1-\n17) tumors. pUSE-9, pUSE-12 H-MEK1-15 and H-MEK1-17 clones were subcutaneously injected on both flanks of male SCID\nmice as described under Experimental Procedures. Tumors were harvested, fixed, paraffin embedded and immunohistochemi-\ncal analysis was performed as described under Experimental Procedures. The sections were stained with mouse anti-Ki-67\nantibody (A). For each clone, 500 cells were counted in randomly chosen fields at 400 × magnification. The Ki-67 labelling\nindex was expressed as the number of clearly labelled Ki-67 reactive nuclei in 500 cells counted (B). Differences in Ki-67 label-\nling index between HepG2-mock and HepG2-MEK1-tumours were statistically significant at p < 0.05 as analyzed by ANOVA\ntest. Original magnification × 400.\npUSE-12\nH-MEK1-15 H-MEK1-17\npUSE-9\n0\n10\n20\n30\n40\n50\n60\n70\n80\n90\n100\n9 1 21 51 7\nKi-67 index in tumour cells\n(per 500 cells)\npUSE H-MEK-1\na a\nb b\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 19 of 21\n(page number not for citation purposes)\n[61]. Furthermore, blocking p90Rsk activity by over-\nexpression of a catalytically inactive form of p90Rsk\nenhanced Fas-mediated cell death [61]. Using anti-phos-\npho-specific Bad (Ser122) and Bad (Ser136) antibodies,\nwe observed that blocking MEK1/2 activity did not alter\nthe levels of Bad phosphorylation at Serine 112 and Serine\n136 (data not shown). Therefore, it is unlikely that\nalterations of Bcl-2 family of proteins or phosphorylation\nof Bad are responsible for apoptosis seen in HepG2 and\nHep3B cells following U0126 treatment.\nAlthough activated Akt-1 exerts an anti-apoptotic effect\nagainst various stimuli [62] and confers resistance to\nchemotherapeutic drugs [63], blocking the phosphoryla-\ntion of Akt by LY294002 only causes mild apoptosis in\nHepG2 and Hep3B cells. The results indicate that at least\nunder our experimental conditions, Akt activity does not\nplay a significant role in the survival of liver cancer cells in\nserum-deprived condition. In vivo the tumor cells may\ndepend on more than one survival pathway. Interaction\nwith extracellular matrices in vivo allows the tumor cells to\nactivate other survival pathways such as fibronectin-FAK-\nJNK [64], which also plays an important role in the sur-\nvival of tumor cells.\nIn mammalian cells, there are at least two pathways\ninvolved in apoptosis. One involves caspase 8, which is\nrecruited by the adapter molecule Fas/APO-1 associated\ndeath domain protein to death receptors upon extracellu-\nlar ligand binding [65,66]. The other involves cytochrome\nc release-dependent activation of caspase 9 through Apaf-\n1 [37,38]. We did not observe any changes in either Fas or\nFasL expression in U0126-treated HepG2 and Hep3B\ncells. We did, however, observe an increase in cleaved\ncaspase 3, cleaved caspase 7, cleaved PARP and cytoplas-\nmic cytochrome c in U0126 treated cells indicating that\ncytochrome c release following U0126 treatment may be\nresponsible for the activation of both caspase 7 and 3\nwhich, in turn, induce apoptosis. This hypothesis is sup-\nported by Germain et al. [67] who demonstrate that\nactivation of caspase 7 is involved in cleavage of PARP and\napoptosis.\nIn summary, we have shown that high expression levels of\nMAPK, phosphorylated MAPK and phosphorylated\nMEK1/2 are found in tumors of HCC patients. Treatment\nof liver cancer cells with MEK inhibitor U0126, leads to\ngrowth inhibition and apoptosis in vitro. Over-expression\nof activated MEK1 enhances tumor growth in vivo and\nconfers resistance to U0126-induced apoptosis. Our data\npoint to the role(s) of activated MEK1/2 and MAPK in\nhepatocarcinoma cell survival and tumor growth, and the\npotential use of MEK1/2 inhibitors in treatment of HCC.\nList of abbreviations\nHepatocellular carcinoma, HCC; mitogen-activated pro-\ntein kinase, MAPK; mitogen-activated protein kinase\nkinase, MEK; poly ADP-ribose polymerase, PARP; phos-\nphatidylinositol 3-kinase, PI-3K; insulin-like growth fac-\ntor, IGF; insulin-like growth factor II, IGF-II; IGF binding\nprotein 3, IGFBP-3; c-Jun N-terminal kinase, JNK; adja-\ncent benign liver, ABL; dimethylsulfoxide, DMSO;\nModified Eagle\'s Media, MEM; phenol-red-free-serum-\nfree MEM, PSF; [3-(4,5-Dimethylthiazol-2-y1)-2,5-diphe-\nnyltetrazolium bromide], MTT; Bromo-deoxyuridine,\nBrdU; terminal deoxynucleotidyl transferase-mediated\ndUTP nick-end labelling, TUNEL.\nCompeting Interests\nThis work was supported by National Cancer Centre Tis-\nsue Repository and grants from National Medical\nResearch Council of Singapore (NMRC/0541/2001),\nSingHealth Cluster Research Fund (EX 008/2001),\nA*STAR-BMRC (LS/00/017) and A*STAR-BMRC (LS/00/\n019) to Huynh Hung.\nAuthors\' contributions\nHH performed immunohistochemistry, transfection\nstudy and in vitro tumorigenicity in addition to the draft-\ning of the manuscript. SKC and CP contributed the HCC\ntissues and some clinical data required for this study. TPH\nperformed the pathological classification and staging of\ntumor samples. NTTT and TE performed cell culture and\nwestern blot analysis. All authors read and approved the\nfinal manuscript.\nAcknowledgements\nWe thank Dr. John Robertson for his critical review of the manuscript.\nReferences\n1. Hussain SA, Ferry DR, El Gazzaz G, Mirza DF, James ND, McMaster\nP, Kerr DJ: Hepatocellular carcinoma.  ann oncol  2001,\n12:161-172.\n2. Ince N, Wands JR: The increasing incide nce of hepatocellular\ncarcinoma. N Engl J Med 1999, 340:798-799.\n3. Okuda K, Ohtsuki T, Obata H, Tomimatsu M, Okazaki N, Hasegawa\nH, Nakajima Y, Ohnishi K: Natural history of hepatocellular car-\n[cinoma and prognosis in relation to treatment. Study of 850](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=2990661)\npatients. Cancer 1985, 56:918-928.\n4. Lai EC, Fan ST, Lo CM, Chu KM, Liu CL, Wong J: Hepatic resection\nfor hepatocellular carcinoma. An audit of 343 patients.  Ann\nSurg 1995, 221:291-298.\n5. Takenaka K, Kawahara N, Yamamoto K, Kajiyama K, Maeda T, Itasaka\nH, Shirabe K, Nishizaki T, Yanaga K, Sugimachi K: Results of 280\nliver resections for he patocellular carcinoma. Arch Surg 1996,\n131:71-76.\n6. Huguet CSFaGA: Primary hepatocellula r cancer: Western\nexperience. In: Surgery of the Liver and Billary Tract Edited by: Blumgart\nL. London: Churchill Livingstone; 2000:1365-1369.\n7. Lai EaWJ: Hepatocellular carcinoma: the Asian experience. In:\nSurgery of the Liver and the Biliary Tract  Edited by: Blumgart L. London:\nChurchill Livingstone; 1994:1349-1363.\n8. Chan ES, Chow PK, Tai B, Machin D, Soo K: Neoadjuvant and\n[adjuvant therapy for operab le hepatocellular carcinoma.](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10796754)\nCochrane Database Syst Rev 2000:CD001199.\n\n\n\n---\n\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 20 of 21\n(page number not for citation purposes)\n9. Zeng JZ, Wang HY, Chen ZJ, Ullrich A, Wu MC: Molecular cloning\n[and characterization of a novel gene which is highly](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1038/sj.onc.1205652)\nexpressed in hepatoc ellular carcinoma.  Oncogene 2002,\n21:4932-4943.\n10. Huynh H, Chow PK, Ooi LL, Soo KC: A possible role for insulin-\nlike growth factor-binding protein-3 autocr ine/paracrine\nloops in controlling hepa tocellular carcinoma cell\nproliferation. Cell Growth Differ 2002, 13:115-122.\n11. Lewis TS, Shapiro PS, Ahn NG: Signal transduction through MAP\nkinase cascades. Adv Cancer Res 1998, 74:49-139.\n12. Ballif BA, Blenis J: Molecular mechanisms mediating mamma-\n[lian mitogen-activated protein kinase (MAPK) kinase (MEK)-](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=11504705)\nMAPK cell survival signals. Cell Growth Differ 2001, 12:397-408.\n13. Hoshino R, Chatani Y, Yamori T, Tsuruo T, Oka H, Yoshida O, Shi-\nmada Y, Ari-i S, Wada H, Fujimoto J, Kohno M: Constitutive acti-\n[vation of the 41-/43-kDa mi togen-activated protein kinase](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1038/sj.onc.1202367)\nsignaling pathway in human tumors.  Oncogene 1999,\n18:813-822.\n14. Amundadottir LT, Leder P: Signal transduction pathways acti-\n[vated and required for mammary carcinogenesis in response](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1038/sj.onc.1201829)\nto specific oncogenes. Oncogene 1998, 16:737-746.\n15. Krueger JS, Keshamouni VG, Atanaskova N, Reddy KB: Temporal\n[and quantitative regulation of mitogen-activated protein](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1038/sj.onc.1204541)\nkinase (MAPK) modulates cell motility and invasion. Oncogene\n2001, 20:4209-4218.\n16. Cowley S, Paterson H, Kemp P, Marshall CJ: Activation of MAP\n[kinase kinase is necessary and sufficient for PC12 differenti-](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=7911739)\nation and for transformation of NIH 3T3 cells.  Cell 1994,\n77:841-852.\n17. Mansour SJ, Matten WT, Hermann AS, Candia JM, Rong S, Fukasawa\nK, Vande Woude GF, Ahn NG: Transformation of mammalian\ncells by constitutively active MAP kinase kinase. Science 1994,\n265:966-970.\n18. Montesano R, Soriano JV, Hosseini G, Pepper MS, Schramek H: Con-\nstitutively active mitogen-activated protein kinase kinase\nMEK1 disrupts morphogenesis and induces an invasive phe-\nnotype in Madin-Darby cani ne kidney ep ithelial cells.  Cell\nGrowth Differ 1999, 10:317-332.\n19. Dudley DT, Pang L, Decker  SJ, Bridges AJ, Saltiel AR: A synthetic\n[inhibitor of the mitogen-activ ated protein kinase cascade.](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=41210)\nProc Natl Acad Sci U S A 1995, 92:7686-7689.\n20. Favata MF, Horiuchi KY, Manos EJ, Daulerio AJ, Stradley DA, Feeser\nWS, Van Dyk DE, Pitts WJ, Earl RA, Hobbs F, Copeland RA, Magolda\nRL, Scherle PA, Trzaskos JM: Identification of a novel inhibitor of\nmitogen-activated prote in kinase kinase.  J Biol Chem  1998,\n273:18623-18632.\n21. Liu E, Thant AA, Kikkawa F, Kurata H, Tanaka S, Nawa A, Mizutani S,\nMatsuda S, Hanafusa H, Hamaguchi M: The Ras-mitogen-activated\nprotein kinase pathway is critical for the activation of matrix\nmetalloproteinase secretion and the invasiveness in v-crk-\ntransformed 3Y1. Cancer Res 2000, 60:2361-2364.\n22. Reddy KB, Krueger JS, Kondapaka SB, Diglio CA: Mitogen-acti-\n[vated protein kinase (MAPK) regulates the expression of](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1002/(SICI)1097-0215(19990719)82:2<268::AID-IJC18>3.3.CO;2-W)\nprogelatinase B (MMP-9) in breast epithelial cells. Int J Cancer\n1999, 82:268-273.\n23. Chen Y, Lu Q, Schneeberger EE, Goodenough DA: Restoration of\ntight junction structure and ba rrier function by down-regu-\nlation of the mitogen-activat ed protein kinase pathway in\nras- transformed Madin-Darby canine kidney cells. Mol Biol Cell\n2000, 11:849-862.\n24. Lu Q, Paredes M, Zhang J, Kosik KS: Basal extracellular signal-\n[regulated kinase activity modulates cell-cell and cell-matrix](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=108907)\ninteractions. Mol Cell Biol 1998, 18:3257-3265.\n25. Mitsui H, Takuwa N, Maruyama T, Maekawa H, Hirayama M, Sawatari\nT, Hashimoto N, Takuwa Y, Kimura S: The MEK1-ERK map\nkinase pathway and the PI 3-kinase-Akt pathway independ-\nently mediate anti-apoptotic si gnals in HepG2 liver cancer\ncells. Int J Cancer 2001, 92:55-62.\n26. Anderson NG, Maller JL, Tonks NK, Sturgill TW: Requirement for\n[integration of signals from two distinct phosphorylation](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1038/343651a0)\npathways for activation of MAP kinase.  Nature 1990,\n343:651-653.\n27. Schmidt CM, McKillop IH, Cahill PA, Sitzmann JV: Increased MAPK\n[expression and activity in primary human hepatocellular](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1006/bbrc.1997.6840)\ncarcinoma. Biochem Biophys Res Commun 1997, 236:54-58.\n28. Lewis TS, Hunt JB, Aveline LD, Jonscher KR, Louie DF, Yeh JM, Nah-\nreini TS, Resing KA, Ahn NG: Identification of novel MAP kinase\n[pathway signaling targets by functional proteomics and mass](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=11163208)\nspectrometry. Mol Cell 2000, 6:1343-1354.\n29. Sebolt-Leopold JS, Dudley DT, He rrera R, Van Becelaere K, Wiland\nA, Gowan RC, Tecle H, Barrett SD, Bridges A, Przybranowski S,\nLeopold WR, Saltiel AR: Blockade of the MAP kinase pathway\nsuppresses growth of colon tumors in vivo.  Nat Med  1999,\n5:810-816.\n30. Alessi DR, Cuenda A, Cohen P, Dudley DT, Saltiel AR: PD 098059\n[is a specific inhibitor of the activation of mitogen- activated](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1074/jbc.270.46.27489)\nprotein kinase kinase in vitro and in vivo.  J Biol Chem  1995,\n270:27489-27494.\n31. Sebolt-Leopold JS: Development of anticancer drugs targeting\nthe MAP kinase pathway. Oncogene 2000, 19:6594-6599.\n32. Spiessl B, Beahrs OH, Hermanek P, Hutter RVP, Scheibe O, Sobin LH,\nWagner G: TNM – Atlas. Illustrated Guide to the TNM/pTNM\nClassification of Malignant Tumours. 104–111. 1992.  Springer\nVerlag, Berlin Heidelberg New York 1989:357.\n33. Ishak KG, Goodman ZD, Stocker JT: Tumors of the liver and int-\nrahepatic bile. Atlas of tumor pathology, Third Series. Armed\nForces Institute of Pathology 2001:199-230.\n34. Lim IJ, Phan TT, Song C, Tan WT, Longaker MT: Investigation of\n[the influence of keloid-derived  keratinocytes on fibroblast](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1097/00006534-200103000-00022)\ngrowth and proliferation in vitro.  Plast Reconstr Surg  2001,\n107:797-808.\n35. Gewies A, Rokhlin OW, Cohen MB: Cytochrome c is involved in\n[Fas-mediated apoptosis of pr ostatic carcinoma cell lines.](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10786680)\nCancer Res 2000, 60:2163-2168.\n36. Green DR, Reed JC: Mitochondria and apoptosis.  Science 1998,\n281:1309-1312.\n37. Cai J, Yang J, Jones DP: Mitochondrial control of apoptosis: the\nrole of cytochrome c. Biochim Biophys Acta 1998, 1366:139-149.\n3 8 . Z o u  H ,  L i  Y ,  L i u  X ,  W a n g  X :  An APAF-1.cytochrome c mul-\n[timeric complex is a function al apoptosome that activates](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1074/jbc.274.17.11549)\nprocaspase-9. J Biol Chem 1999, 274:11549-11556.\n39. Cohen GM: Caspases: the executioners of apoptosis. Biochem J\n1997, 326(Pt 1):1-16.\n40. MacKeigan JP, Collins TS, Ting JP: MEK inhibition enhances pacl-\nitaxel-induced tumor apoptosis.  J Biol Chem  2000,\n275:38953-38956.\n41. Wang X, Martindale JL, Holbrook NJ: Requirement for ERK acti-\nvation in cisplatin-induced apoptosis.  J Biol Chem  2000,\n275:39435-39443.\n42. Lobenhofer EK, Huper G, Iglehart JD, Marks JR: Inhibition of\nmitogen-activated protein kinase and phosphatidylinositol 3-\nkinase activity in MCF-7 cells prevents estrogen-induced\nmitogenesis. Cell Growth Differ 2000, 11:99-110.\n43. Hii CS, Ferrante A, Edwards YS, Huang ZH, Hartfield PJ, Rathjen DA,\nPoulos A, Murray AW: Activation of mitogen-activated protein\n[kinase by arachidonic acid in rat liver epithelial WB cells by](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1074/jbc.270.9.4201)\na protein kinase C-dependent mechanism.  J Biol Chem  1995,\n270:4201-4204.\n44. Kim YC, Song KS, Yoon G, Nam MJ, Ryu WS: Activated ras onco-\n[gene collaborates with HBx ge ne of hepatitis B virus to](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1038/sj.onc.1203840)\n[transform cells by suppressi ng HBx-mediated apoptosis.](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1038/sj.onc.1203840)\nOncogene 2001, 20:16-23.\n45. Chung YH, Kim JA, Song BC, Le e GC, Koh MS, Lee YS, Lee SG, Suh\nDJ: Expression of transforming growth factor-alpha mRNA in\n[livers of patients with chroni c viral hepatitis and hepatocel-](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1002/1097-0142(20000901)89:5<977::AID-CNCR6>3.0.CO;2-I)\nlular carcinoma. Cancer 2000, 89:977-982.\n46. Ueki T, Fujimoto J, Suzuki T, Yamamoto H, Okamoto E: Expression\n[of hepatocyte growth factor and its receptor c-met proto-](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=9096589)\noncogene in hepatoc ellular carcinoma.  Hepatology 1997,\n25:862-866.\n47. Pelicci G, Lanfrancone L, Salcini AE, Romano A, Mele S, Grazia BM,\nSegatto O, Di Fiore PP, Pelicci PG: Constitutive phosphorylation\nof Shc proteins in human tumors. Oncogene 1995, 11:899-907.\n48. Petit AM, Rak J, Hung MC, Rockwell P, Goldstein N, Fendly B, Kerbel\nRS: Neutralizing antibodies against epidermal growth factor\nand ErbB-2/neu receptor tyrosine kinases down-regulate\nvascular endothelial growth factor production by tumor cells\nin vitro and in vivo: angiogenic  implications for signal trans-\nduction therapy of solid tumors.  Am J Pathol  1997,\n151:1523-1530.\n\n\n\n---\n\nPublish with BioMed Central   and  every\nscientist can read your work free of charge\n"BioMed Central will be the most significant development for\ndisseminating the results of biomedical research in our lifetime."\nSir Paul Nurse, Cancer Research UK\nYour research papers will be:\navailable free of charge to the entire biomedical community\npeer reviewed and published immediately upon acceptance\ncited in PubMed and archived on PubMed Central\nyours — you keep the copyright\nSubmit your manuscript here:\n[http://www.biomedcentral.com/info/publishing_adv.asp](http://www.biomedcentral.com/info/publishing_adv.asp)\nBioMedcentral\nBMC Gastroenterology 2003, 3 http://www.biomedcentral.com/1471-230X/3/19\nPage 21 of 21\n(page number not for citation purposes)\n49. Eliceiri BP, Klemke R, Stromblad S, Cheresh DA: Integrin\n[alphavbeta3 requirement for sustained mito gen-activated](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1083/jcb.140.5.1255)\nprotein kinase activity  during angiogenesis.  J Cell Biol  1998,\n140:1255-1263.\n50. Marshall CJ: ERK/MAP kinase kinase kinase, ERK/MAP kinase\nkinase, and ERK/MAP kinase. Curr Opin Genet Dev 1994, 4:82-89.\n51. Seger R, Krebs EG: The MAPK signaling cascade.  FASEB J 1995,\n9:726-735.\n52. Morishima-Kawashima M, Kosik KS: The pool of map kinase asso-\n[ciated with microtubules is sm all but constitutively active.](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=8816996)\nMol Biol Cell 1996, 7:893-905.\n53. Klemke RL, Cai S, Giannini AL, Gallagher PJ, de Lanerolle P, Cheresh\nDA: Regulation of cell motility by mitogen-activated protein\nkinase. J Cell Biol 1997, 137:481-492.\n54. Mandell JW, Hussaini IM, Zecevic M, Weber MJ, VandenBerg SR: In\nsitu visualization of intratum or growth factor signaling:\nimmunohistochemical localizat ion of activa ted ERK/MAP\nkinase in glial neoplasms. Am J Pathol 1998, 153:1411-1423.\n55. Lotem J, Sachs L: Regulation of bcl-2, bcl-XL and bax in the con-\n[trol of apoptosis by he matopoietic cytokines and](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=7669718)\ndexamethasone. Cell Growth Differ 1995, 6:647-653.\n56. Fan HY, Tong C, Lian L, Li SW, Gao WX, Cheng Y, Chen DY, Schat-\nten H, Sun QY: Characterization of Ribosomal S6 Protein\nKinase p90rsk During Meiotic Maturation and Fertilization in\nPig Oocytes: Mitogen-Activa ted Protein Kinase-Associated\nActivation and Localization. Biol Reprod 2003, 68:968-977.\n57. Wade CB, Dorsa DM: Estrogen activation of cyclic adenosine\n5\'-monophosphate response element-mediated transcrip-\ntion requires the ex tracellularly regula ted kinase/mitogen-\nactivated protein kinase pathway. Endocrinol 2003, 144:832-838.\n58. Boglari G, Szeberenyi J: Nuclear translocation of p90Rsk and\n[phosphorylation of CREB is induced by ionomycin in a Ras-](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=12371612)\nindependent manner in PC12 cells. Acta Biol Hung  2002,\n53:325-334.\n59. Brognard J, Dennis PA: Variable apoptotic response of NSCLC\n[cells to inhibition of the ME K/ERK pathway by small mole-](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1038/sj.cdd.4401054)\ncules or dominant negative mutants.  Cell Death Differ  2002,\n9:893-904.\n60. Sautin YY, Crawford JM, Svetlov SI: Enhancement of survival by\n[LPA via Erk1/Erk2 and PI 3-kinase/Akt pathways in a murine](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=11698260)\nhepatocyte cell line.  Am J Physiol Cell Physiol  2001,\n281:C2010-C2019.\n61. Bertolotto C, Maulon L, Filippa N, Baier G, Auberger P: Protein\n[kinase C theta and epsilon promote T-cell survival by a rsk-](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10.1074/jbc.M007732200)\ndependent phosphorylation and inactivation of BAD.  J Biol\nChem 2000, 275:37246-37250.\n62. Franke TF, Yang SI, Chan TO, Datta  K, Kazlauskas A, Morrison DK,\nKaplan DR, Tsichlis PN: The protein kinase encoded by the Akt\n[proto-oncogene is a target of the PDGF-activated phosphati-](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=7774014)\ndylinositol 3-kinase. Cell 1995, 81:727-736.\n63. Page C, Lin HJ, Jin Y, Castle VP, Nunez G, Huang M, Lin J: Overex-\n[pression of Akt/AK T can modulate chemotherapy-induced](http://www.ncbi.nlm.nih.gov/entrez/query.fcgi?cmd=Retrieve&db=PubMed&dopt=Abstract&list_uids=10769688)\napoptosis. Anticancer Res 2000, 20:407-416.\n64. Almeida EA, Ilic D, Han Q, Hauck CR, Jin F, Kawakatsu H, Schlaepfer\nDD, Damsky CH: Matrix survival signa ling: from fibronectin\nvia focal adhesion kinase to c-Jun NH(2)-terminal kinase.  J\nCell Biol 2000, 149:741-754.\n65. Muzio M, Stockwell BR, Stenni cke HR, Salvesen GS, Dixit VM: An\ninduced proximity model for caspase-8 activation. J Biol Chem\n1998, 273:2926-2930.\n66. Cryns V, Yuan J: Proteases to die for.  Genes Dev  1998,\n12:1551-1570.\n67. Germain M, Affar EB, D\'Amours D,  Dixit VM, Salvesen GS, Poirier\nGG: Cleavage of automodified poly(ADP-ribose) polymerase\nduring apoptosis. Evidence for involvement of caspase-7. J Biol\nChem 1999, 274:28379-28384.\nPre-publication history\nThe pre-publication history for this paper can be accessed\nhere:\nhttp://www.biomedcentral.com/1471-230X/3/19/pre\npub\n\n\n\n---\n'
        verifier = QuoteVerifier(remove_stopwords=True)
        quote = verifier.verify_quote(text,"'3-(4,5-Dimethylthiazol-2-y1)-2,5-diphenyltetrazolium bromide (MTT) assay and ELISA were used to determine cell viability and cell proliferation',")
        self.assertTrue(quote['verified'])

class TestHyphensAndDashes(unittest.TestCase):
    """Test handling of hyphens, en dashes, and em dashes."""

    def setUp(self):
        self.verifier = QuoteVerifier()

    # -- Attached hyphens are preserved --

    def test_attached_hyphen_exact_match(self):
        """Attached hyphens in both source and quote should match."""
        doc = "The well-known anti-inflammatory drug was effective."
        result = self.verifier.verify_quote(doc, "well-known anti-inflammatory drug")
        self.assertTrue(result["verified"])

    def test_attached_hyphen_missing_in_quote(self):
        """Quote without hyphen should NOT match hyphenated source."""
        doc = "The well-known drug was effective."
        result = self.verifier.verify_quote(doc, "wellknown drug")
        self.assertFalse(result["verified"])

    def test_attached_hyphen_missing_in_source(self):
        """Source without hyphen should NOT match hyphenated quote."""
        doc = "The wellknown drug was effective."
        result = self.verifier.verify_quote(doc, "well-known drug")
        self.assertFalse(result["verified"])

    def test_hyphenated_compound_words(self):
        """Complex hyphenated compounds should match exactly."""
        doc = "The state-of-the-art method uses high-throughput sequencing."
        result = self.verifier.verify_quote(doc, "state-of-the-art method uses high-throughput")
        self.assertTrue(result["verified"])

    def test_hyphen_at_line_break_enabled(self):
        """With hyphenation enabled, word-\\n joins the word."""
        doc = "The anti-\ninflammatory response was measured."
        v = QuoteVerifier(normalize_hyphenation=True)
        result = v.verify_quote(doc, "antiinflammatory response")
        self.assertTrue(result["verified"])

    def test_hyphen_at_line_break_disabled(self):
        """With hyphenation disabled, word-\\n should NOT rejoin."""
        doc = "The anti-\ninflammatory response was measured."
        v = QuoteVerifier(normalize_hyphenation=False)
        result = v.verify_quote(doc, "antiinflammatory response")
        self.assertFalse(result["verified"])

    # -- Em dashes and en dashes --

    def test_em_dash_in_source(self):
        """Em dash in source should be treated as punctuation (replaced by space)."""
        doc = "The drug\u2014a novel compound\u2014showed strong results."
        result = self.verifier.verify_quote(doc, "The drug a novel compound showed strong results")
        self.assertTrue(result["verified"])

    def test_em_dash_in_both(self):
        """Em dash in both source and quote should match (both become spaces)."""
        doc = "The drug\u2014a novel compound\u2014showed results."
        result = self.verifier.verify_quote(doc, "The drug\u2014a novel compound\u2014showed results")
        self.assertTrue(result["verified"])

    def test_en_dash_in_source(self):
        """En dash in source should be treated as punctuation."""
        doc = "Pages 10\u201320 describe the findings."
        result = self.verifier.verify_quote(doc, "Pages 10 20 describe the findings")
        self.assertTrue(result["verified"])

    def test_em_dash_vs_detached_hyphen(self):
        """Em dash in source, detached hyphen in quote -- both become spaces, should match."""
        doc = "The drug\u2014a compound\u2014showed results."
        result = self.verifier.verify_quote(doc, "The drug - a compound - showed results")
        self.assertTrue(result["verified"])

    def test_em_dash_vs_attached_hyphen(self):
        """Em dash in source, attached hyphen in quote -- should NOT match.
        Em dash becomes space, attached hyphen is preserved."""
        doc = "The drug\u2014a compound\u2014showed results."
        result = self.verifier.verify_quote(doc, "The drug-a compound-showed results")
        self.assertFalse(result["verified"])

    def test_attached_hyphen_vs_em_dash(self):
        """Attached hyphen in source vs em dash in quote should NOT match.
        Hyphen is preserved, em dash becomes space -- different tokens."""
        doc = "The well-known drug was effective."
        result = self.verifier.verify_quote(doc, "The well\u2014known drug was effective")
        self.assertFalse(result["verified"])

    # -- Mixed scenarios --

    def test_multiple_hyphen_types_in_one_sentence(self):
        """Source with attached hyphens and em dashes."""
        doc = "The anti-inflammatory drug\u2014first tested in 2019\u2014is now FDA-approved."
        result = self.verifier.verify_quote(
            doc, "anti-inflammatory drug first tested in 2019 is now FDA-approved")
        self.assertTrue(result["verified"])

    def test_hyphen_between_numbers(self):
        """Hyphen between numbers (e.g. phone number, range) should be preserved."""
        doc = "Call 555-1234 for the dose range 10-20 mg."
        result = self.verifier.verify_quote(doc, "555-1234 for the dose range 10-20")
        self.assertTrue(result["verified"])

    def test_detached_hyphen_removed(self):
        """Detached hyphen (spaces around it) should be removed as punctuation."""
        doc = "The drug - a novel compound - showed results."
        result = self.verifier.verify_quote(doc, "The drug a novel compound showed results")
        self.assertTrue(result["verified"])


class TestDotsAndCommasBetweenAlphanums(unittest.TestCase):
    """Test that dots and commas between alphanumeric chars are preserved."""

    def setUp(self):
        self.verifier = QuoteVerifier()

    def test_dotted_symbol_unsplit(self):
        """parseltongue.core should not be split at the dot."""
        doc = "The module parseltongue.core provides the DSL engine."
        result = self.verifier.verify_quote(doc, "parseltongue.core provides the DSL engine")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_dotted_package_path(self):
        """A fully qualified package like a.b.c should stay intact."""
        doc = "Import from com.example.utils to use the helper."
        result = self.verifier.verify_quote(doc, "com.example.utils")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_version_number(self):
        """Version strings like 3.12.1 should stay intact."""
        doc = "Requires Python 3.12.1 or higher."
        result = self.verifier.verify_quote(doc, "Python 3.12.1 or higher")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_decimal_number(self):
        """Decimal like 3.14 should stay intact."""
        doc = "The value of pi is approximately 3.14 for this calculation."
        result = self.verifier.verify_quote(doc, "approximately 3.14 for this calculation")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_comma_in_large_number(self):
        """Commas in 1,000,000 should be preserved."""
        doc = "The population reached 1,000,000 residents last year."
        result = self.verifier.verify_quote(doc, "population reached 1,000,000 residents")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_dot_at_sentence_end_removed(self):
        """Dot at end of sentence (not between alphanums) should be removed as punctuation."""
        doc = "The result is final."
        result = self.verifier.verify_quote(doc, "The result is final")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")


class TestDollarAmounts(unittest.TestCase):
    """Test that dollar amounts and numbers with commas are handled correctly."""

    def setUp(self):
        self.verifier = QuoteVerifier()

    def test_dollar_amount_with_comma(self):
        """$150,000 in document should match quote 'Base salary for eligible employees is $150,000'."""
        doc = "Bonus is 20% of base salary if growth target is exceeded. Base salary\nfor eligible employees is $150,000. Eligibility requires that the\nquarterly revenue growth exceeds the stated annual growth target."
        result = self.verifier.verify_quote(doc, "Base salary for eligible employees is $150,000")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_dollar_amount_with_period(self):
        """Same quote but with trailing period."""
        doc = "Base salary for eligible employees is $150,000."
        result = self.verifier.verify_quote(doc, "Base salary for eligible employees is $150,000.")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_dollar_amount_across_linebreak(self):
        """Quote spanning a line break should still verify."""
        doc = "Base salary\nfor eligible employees is $150,000."
        result = self.verifier.verify_quote(doc, "Base salary for eligible employees is $150,000.")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_number_with_comma_preserved(self):
        """Numbers like 150,000 should normalize consistently in doc and quote."""
        doc = "The total was 150,000 units."
        result = self.verifier.verify_quote(doc, "The total was 150,000 units")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")

    def test_dollar_millions(self):
        """$15M style amounts should work."""
        doc = "Q3 revenue was $15M, up 15% year-over-year."
        result = self.verifier.verify_quote(doc, "Q3 revenue was $15M, up 15% year-over-year")
        self.assertTrue(result["verified"], f"Failed: {result.get('reason', 'unknown')}")


if __name__ == "__main__":
    unittest.main()
