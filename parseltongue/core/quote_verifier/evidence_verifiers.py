"""Per-type evidence verifiers.

``Evidence.type`` selects the verifier structure. The engine holds a
registry ``{type: EvidenceVerifier}``; ``doc_quote`` and ``corpus_query``
ship as defaults — both grounded against the language's own closed world,
the registered-document corpus (already indexed by DocumentIndex; queried
through the core search engine). Other layers register verifiers for the
types or corpora they own — via ``System(evidence_verifiers=...)`` or
``engine.register_evidence_verifier`` — e.g. the bench overrides
``corpus_query`` with a file-corpus verifier. Evidence whose type has no
registered verifier is left ungrounded, which the consistency check
reports as unverified.
"""

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..atoms import CorpusSource, Evidence, QueryClaim, Symbol
from .verifier import QuoteVerifier

if TYPE_CHECKING:
    from ..search_engine.engine import QueryEngine

log = logging.getLogger("parseltongue.evidence")


@runtime_checkable
class EvidenceVerifier(Protocol):
    """Grounds Evidence of one type.

    Returns the evidence with the ``verification`` payload filled and
    ``verified`` set; returns it unchanged when grounding is not possible
    (e.g. the referenced source is not available to this verifier).
    """

    def verify(self, evidence: Evidence, caller: "str | None" = None) -> Evidence: ...


class DocQuoteEvidenceVerifier:
    """Default verifier: every quote must be FOUND in a registered document."""

    def __init__(self, quote_verifier: QuoteVerifier, documents: dict):
        self._verifier = quote_verifier
        self._documents = documents  # live view of the engine's document registry

    def verify(self, evidence: Evidence, caller: "str | None" = None) -> Evidence:
        if evidence.document not in self._documents:
            log.warning("Document '%s' not registered — skipping verification", evidence.document)
            return evidence

        results = self._verifier.verify_indexed_quotes(evidence.document, evidence.quotes, caller=caller)

        all_verified = True
        for r in results:
            if r["verified"]:
                conf = r.get("confidence", {})
                log.info('Quote verified: "%s" (confidence: %s)', r["quote"], conf.get("level", "?"))
            else:
                all_verified = False
                reason = r.get("reason", "unknown")
                log.warning('Quote NOT verified: "%s" (%s)', r["quote"], reason)

        return replace(evidence, verification=results, verified=all_verified)


class DocumentCorpusVerifier:
    """Grounds corpus_query evidence against the registered-document corpus.

    The language's own closed world: every document was explicitly
    registered, so closure holds by construction. Queries run through the
    core search engine over the quote verifier's DocumentIndex — the same
    inverted-index machinery that grounds quotes. Scope and :except match
    document names ((in ...) semantics). Provenance records each scoped
    document's content hash from the index.
    """

    def __init__(self, doc_index, counter_example_cap: int = 50):
        self._doc_index = doc_index  # the engine verifier's DocumentIndex
        self._counter_example_cap = counter_example_cap
        self._engine: "QueryEngine | None" = None  # lazy — built on first corpus claim

    def _query_engine(self) -> "QueryEngine":
        from ..search_engine.engine import QueryEngine

        if self._engine is None:
            self._engine = QueryEngine(self._doc_index)
        else:
            self._engine.refresh()
        return self._engine

    def verify(self, evidence: Evidence, caller: "str | None" = None) -> Evidence:
        from ..lang import PGStringParser
        from ..search_engine.engine import compose_satisfies
        from ..search_engine.select import is_ignored

        claim = evidence.claims[0] if evidence.claims else None
        if not isinstance(claim, QueryClaim):
            return evidence
        scope = evidence.document
        excludes = tuple(evidence.source.excludes) if isinstance(evidence.source, CorpusSource) else ()

        result: dict = {
            "query": claim.query,
            "polarity": claim.polarity,
            "satisfies": claim.satisfies,
            "scope": scope,
            "excludes": list(excludes),
            "corpus": "registered-documents",
            "verified": False,
        }

        qe = self._query_engine()
        in_scope = {
            name for (name, _line) in qe.evaluate_posting((Symbol("in"), scope) if scope else (Symbol("in"), "*"))
        }
        scoped_docs = sorted(name for name in in_scope if not is_ignored(name, excludes))
        if not scoped_docs:
            result["reason"] = f"no registered documents match scope '{scope}' — nothing to quantify over"
            return replace(evidence, verification=[result], verified=False)

        def _scoped(form):
            composed = (Symbol("in"), scope, form) if scope else form
            posting = qe.evaluate_posting(composed)
            return {k: v for k, v in posting.items() if not is_ignored(k[0], excludes)}

        parse = PGStringParser.translate
        try:
            matches = _scoped(parse(claim.query))
            if claim.polarity == "forall":
                satisfied = _scoped(compose_satisfies(parse(claim.query), parse(claim.satisfies or "")))
                violations = {k: v for k, v in matches.items() if k not in satisfied}
            else:
                violations = matches
        except Exception as exc:  # malformed query — refuse, never certify
            result["reason"] = f"query evaluation failed: {exc}"
            return replace(evidence, verification=[result], verified=False)

        result["checked_files"] = len(scoped_docs)
        result["content_hashes"] = {
            name: self._doc_index.documents[name].content_hash
            for name in scoped_docs
            if name in self._doc_index.documents
        }

        if violations:
            rows = sorted(violations.items())[: self._counter_example_cap]
            result["counter_examples"] = [[doc, line, str(p.get("context", "")).rstrip()] for (doc, line), p in rows]
            result["reason"] = f"{len(violations)} match(es) breach the claim"
            return replace(evidence, verification=[result], verified=False)

        result["verified"] = True
        return replace(evidence, verification=[result], verified=True)
