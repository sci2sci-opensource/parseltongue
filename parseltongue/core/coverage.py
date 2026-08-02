"""Coverage — typed measurements of how thoroughly a corpus was examined.

Coverage is not language: nothing is declared and no grammar exists. It
is measurement over verification state the system already holds — quote
provenance, grounded corpus claims. Measurements are typed: ``type`` is
a ClassVar discriminator decisive for the concrete shape, and the
subclass IS the subtype. Providers register per type — constructor
injection (``coverage_providers=...``) or
``register_coverage_provider`` — mirroring the evidence-verifier
registry, so richer coverage kinds plug in as new types without core
changes. Reporting (thresholds, grouping, display policy) belongs to
consumers; core only measures.
"""

from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable

from .atoms import EVIDENCE_TYPE_CORPUS_QUERY, Evidence


@dataclass(frozen=True)
class Coverage:
    """Base of all coverage measurements.

    ``type`` is decisive for the concrete shape — stable for
    serialization and registry dispatch; typed consumers may equally
    dispatch by isinstance on the subclass.
    """

    type: ClassVar[str]

    def describe(self) -> str:
        """Presentation-only — generic renderers know nothing else."""
        raise NotImplementedError


@runtime_checkable
class CoverageProvider(Protocol):
    """Measures one coverage type over an engine's verification state."""

    type: str

    def measure(self, engine) -> "list[Coverage]": ...


# ============================================================
# quote_range — how much of each document is covered by quotes
# ============================================================


@dataclass(frozen=True)
class QuoteRangeCoverage(Coverage):
    """Merged verified-quote spans over one document's normalized text."""

    type: ClassVar[str] = "quote_range"

    document: str
    fraction: float
    covered_chars: int  # normalized-text coordinates, like the ranges
    total_chars: int

    def describe(self) -> str:
        return f"{self.document}: {self.fraction:.0%} quoted ({self.covered_chars}/{self.total_chars} chars)"


def _merge_ranges(ranges: "list[tuple[int, int]]") -> "list[tuple[int, int]]":
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class QuoteRangeCoverageProvider:
    """Default provider: verified quote ranges / normalized document length."""

    type = QuoteRangeCoverage.type

    def measure(self, engine) -> "list[Coverage]":
        index = engine._verifier.index
        by_doc: dict[str, list[tuple[int, int]]] = {}
        for doc, start, end, _caller in index._quote_ranges:
            if start >= 0:
                by_doc.setdefault(doc, []).append((start, end))
        out: list[Coverage] = []
        for name, doc in sorted(index.documents.items()):
            total = len(doc.normalized_text)
            covered = min(total, sum(e - s + 1 for s, e in _merge_ranges(by_doc.get(name, []))))
            out.append(
                QuoteRangeCoverage(
                    document=name,
                    fraction=(covered / total) if total else 0.0,
                    covered_chars=covered,
                    total_chars=total,
                )
            )
        return out


# ============================================================
# corpus_claim — which grounded :absent/:forall claims quantify a document
# ============================================================


@dataclass(frozen=True)
class CorpusClaimCoverage(Coverage):
    """Scrutiny by quantification: grounded corpus claims covering one document."""

    type: ClassVar[str] = "corpus_claim"

    document: str
    claims: "tuple[str, ...]"

    def describe(self) -> str:
        return f"{self.document}: quantified by {', '.join(self.claims)}"


class CorpusClaimCoverageProvider:
    """Reads grounded corpus_query evidence; a claim covers every scoped doc."""

    type = CorpusClaimCoverage.type

    def measure(self, engine) -> "list[Coverage]":
        by_doc: dict[str, set] = {}
        for store in (engine.facts, engine.axioms, engine.theorems, engine.terms):
            for name, item in store.items():
                origin = item.origin
                if not isinstance(origin, Evidence) or origin.type != EVIDENCE_TYPE_CORPUS_QUERY:
                    continue
                if not origin.is_grounded:
                    continue
                for record in origin.verification:
                    if isinstance(record, dict):
                        for doc in record.get("content_hashes") or {}:
                            by_doc.setdefault(doc, set()).add(name)
        return [CorpusClaimCoverage(document=doc, claims=tuple(sorted(names))) for doc, names in sorted(by_doc.items())]


def default_coverage_providers() -> "dict[str, CoverageProvider]":
    return {
        QuoteRangeCoverageProvider.type: QuoteRangeCoverageProvider(),
        CorpusClaimCoverageProvider.type: CorpusClaimCoverageProvider(),
    }
