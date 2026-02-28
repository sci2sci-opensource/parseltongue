"""Performance comparison: old QuoteVerifier (str.find) vs new (inverted index)."""

import time
import unittest

from quote_verifier import QuoteVerifier as NewVerifier
from tests.quote_verifier_v2_old import QuoteVerifier as OldVerifier


# ---------------------------------------------------------------------------
# Test documents of increasing size
# ---------------------------------------------------------------------------

SMALL_DOC = (
    "Retrieval-Augmented Generation (RAG) is a technique for enhancing "
    "the accuracy and reliability of generative AI models with information "
    "fetched from specific and relevant data sources."
)

MEDIUM_DOC = SMALL_DOC * 100  # ~20 KB

LARGE_DOC = SMALL_DOC * 1000  # ~200 KB

HUGE_DOC = SMALL_DOC * 2000  # ~400 KB

# Quotes that exist in the document
EXISTING_QUOTES = [
    "Retrieval-Augmented Generation",
    "enhancing the accuracy and reliability",
    "generative AI models with information fetched from specific",
    "relevant data sources",
]

# Quotes that do NOT exist — force full scan on old verifier
MISSING_QUOTES = [
    "This quote does not appear anywhere in the document at all",
    "Another completely fabricated sentence that has no match",
    "Quantum computing will revolutionize cryptography forever",
    "The mitochondria is the powerhouse of the cell",
]


def _bench(verifier_cls, doc, quotes, n_rounds, label):
    """Run n_rounds of verify_quotes, return total seconds."""
    v = verifier_cls()
    # Warm-up (build index for new verifier on first call)
    v.verify_quotes(doc, quotes[:1])

    start = time.perf_counter()
    for _ in range(n_rounds):
        v.verify_quotes(doc, quotes)
    elapsed = time.perf_counter() - start
    return elapsed


class TestPerformance(unittest.TestCase):
    """Benchmark old vs new QuoteVerifier.

    Not a correctness test — prints a comparison table.
    Uses subTest so individual sizes are reported separately.
    """

    def _run_comparison(self, doc, quotes, n_rounds, size_label):
        old_time = _bench(OldVerifier, doc, quotes, n_rounds, "old")
        new_time = _bench(NewVerifier, doc, quotes, n_rounds, "new")
        speedup = old_time / new_time if new_time > 0 else float('inf')
        return old_time, new_time, speedup

    def test_performance_comparison(self):
        """Compare old vs new across document sizes and quote types."""
        scenarios = [
            ("small  (~0.2 KB)", SMALL_DOC,  200),
            ("medium (~20 KB)",  MEDIUM_DOC,  50),
            ("large  (~200 KB)", LARGE_DOC,   5),
            ("huge   (~400 KB)",   HUGE_DOC,     2),
        ]

        quote_sets = [
            ("existing", EXISTING_QUOTES),
            ("missing",  MISSING_QUOTES),
        ]

        print("\n" + "=" * 72)
        print(f"{'Scenario':<28} {'Quotes':<10} {'Old (s)':<10} {'New (s)':<10} {'Speedup':<10}")
        print("-" * 72)

        for size_label, doc, n_rounds in scenarios:
            for q_label, quotes in quote_sets:
                old_t, new_t, speedup = self._run_comparison(
                    doc, quotes, n_rounds, size_label)
                print(f"{size_label:<28} {q_label:<10} {old_t:<10.4f} {new_t:<10.4f} {speedup:<10.1f}x")

        print("=" * 72)

    def test_repeated_verify_same_doc(self):
        """New verifier should amortize index build across repeated calls."""
        n = 50
        quotes = EXISTING_QUOTES + MISSING_QUOTES

        old = OldVerifier()
        new = NewVerifier()

        # Old: each call re-normalizes the full document
        start = time.perf_counter()
        for _ in range(n):
            old.verify_quotes(SMALL_DOC, quotes)
        old_time = time.perf_counter() - start

        # New: first call builds index, subsequent calls reuse it
        start = time.perf_counter()
        for _ in range(n):
            new.verify_quotes(SMALL_DOC, quotes)
        new_time = time.perf_counter() - start

        speedup = old_time / new_time if new_time > 0 else float('inf')

        print(f"\n{'Repeated verify (large doc, 50 rounds, 8 quotes each)':}")
        print(f"  Old: {old_time:.4f}s | New: {new_time:.4f}s | Speedup: {speedup:.1f}x")

    def test_correctness_parity(self):
        """Verify that old and new produce identical results."""
        old = OldVerifier()
        new = NewVerifier()

        all_quotes = EXISTING_QUOTES + MISSING_QUOTES

        for doc_label, doc in [("small", SMALL_DOC), ("medium", MEDIUM_DOC)]:
            old_results = old.verify_quotes(doc, all_quotes)
            new_results = new.verify_quotes(doc, all_quotes)

            for i, (o, n) in enumerate(zip(old_results, new_results)):
                with self.subTest(doc=doc_label, quote=all_quotes[i]):
                    self.assertEqual(o["verified"], n["verified"],
                                     f"verified mismatch for: {all_quotes[i]}")
                    self.assertEqual(o["original_position"], n["original_position"],
                                     f"position mismatch for: {all_quotes[i]}")


if __name__ == "__main__":
    unittest.main()
