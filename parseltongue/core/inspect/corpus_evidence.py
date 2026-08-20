"""corpus_query evidence verifier — grounds :absent / :forall claims.

Quantifies a claim over the closed corpus of the bench search index.

Soundness gate: a claim is only certifiable when every file in its scope
is classified — indexed, ignored (.pgignore), or excluded by the claim's
:except. Anything unclassified refuses certification with an actionable
message, mirroring the size guardrail's "every file must be classified"
discipline.

Provenance: the Merkle root over the scoped files' content hashes at
verification time, recorded in the opaque verification payload together
with the corpus size and — on refutation — counter-example rows.
"""

import fnmatch
import logging
import os
from dataclasses import replace
from pathlib import Path

from ..atoms import CorpusSource, Evidence, QueryClaim
from ..integrity.merkle import MerkleNode, merkle_combine
from ..lang import PGStringParser, to_sexp
from .config import load_ignore_patterns
from .store import _is_ignored

log = logging.getLogger("parseltongue.corpus_evidence")


class CorpusEvidenceVerifier:
    """Grounds corpus_query Evidence against a bench Search index.

    Implements the EvidenceVerifier protocol; registered on the engine for
    type "corpus_query" by whichever layer owns a search index (the bench).
    """

    def __init__(self, search, root: "str | Path", counter_example_cap: int = 50):
        self._search = search
        self._root = Path(root)
        self._counter_example_cap = counter_example_cap
        self._parser = PGStringParser()

    # ── EvidenceVerifier protocol ──

    def verify(self, evidence: Evidence, caller: "str | None" = None) -> Evidence:
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
            "verified": False,
        }

        indexed = self._indexed_docs()
        if not indexed:
            result["reason"] = "search index is empty — nothing to quantify over"
            return replace(evidence, verification=[result], verified=False)

        # A scope that names no indexed file and no directory under the
        # root refers to a registered document, not a file-corpus region —
        # that claim is grounded by the document-corpus verifier at load
        # time; re-certifying it over zero files would be vacuous.
        if scope and not (self._root / scope).is_dir() and not any(self._in_scope(d, scope) for d in indexed):
            return evidence

        unclassified = self._closure_gaps(scope, excludes, indexed)
        if unclassified:
            shown = ", ".join(unclassified[:5]) + ("…" if len(unclassified) > 5 else "")
            result["reason"] = (
                f"closure failure — {len(unclassified)} file(s) in scope neither indexed nor classified: "
                f"{shown} (fix: add to .pgignore, allowlist in pg.toml, or narrow the scope)"
            )
            return replace(evidence, verification=[result], verified=False)

        try:
            matches = self._postings(claim.query, scope, excludes)
            if claim.polarity == "forall":
                satisfied = self._postings(self._compose_satisfies(claim), scope, excludes)
                violations = {k: v for k, v in matches.items() if k not in satisfied}
            else:
                violations = matches
        except Exception as exc:  # malformed query — refuse, never certify
            result["reason"] = f"query evaluation failed: {exc}"
            return replace(evidence, verification=[result], verified=False)

        checked, root_hash = self._scoped_merkle(scope, excludes, indexed)
        result["merkle_root"] = root_hash
        result["checked_files"] = checked

        if violations:
            rows = sorted(violations.items())[: self._counter_example_cap]
            result["counter_examples"] = [[doc, line, str(p.get("context", "")).rstrip()] for (doc, line), p in rows]
            result["reason"] = f"{len(violations)} match(es) breach the claim"
            return replace(evidence, verification=[result], verified=False)

        result["verified"] = True
        return replace(evidence, verification=[result], verified=True)

    # ── scope semantics (shared by gate, query filter, and merkle) ──

    @staticmethod
    def _in_scope(rel: str, scope: str) -> bool:
        if not scope:
            return True
        rel = rel.replace("\\", "/")
        s = scope.rstrip("/")
        return rel == s or rel.startswith(s + "/") or fnmatch.fnmatch(rel, scope) or fnmatch.fnmatch(rel, s + "/*")

    @staticmethod
    def _excluded(rel: str, excludes: tuple) -> bool:
        """An :except pattern matches at any path level, gitignore-style."""
        rel = rel.replace("\\", "/")
        for pat in excludes:
            p = str(pat).rstrip("/")
            candidates = (str(pat), p, p + "/*", "*/" + p, "*/" + p + "/*")
            if rel == p or rel.startswith(p + "/") or any(fnmatch.fnmatch(rel, c) for c in candidates):
                return True
        return False

    # ── internals ──

    def _indexed_docs(self) -> set:
        try:
            return set(self._search._system._search_index._snap.documents)
        except AttributeError:
            return set()

    def _closure_gaps(self, scope: str, excludes: tuple, indexed: set) -> list:
        """Files on disk inside the scope that are neither indexed nor classified.

        Walks only when the scope names a real directory under the root —
        a scope naming a single document (or an index-relative file) has
        no directory tree to close over. The walk prunes ignored
        directories instead of enumerating them (rglob through .git or a
        virtualenv costs minutes per claim).
        """
        if scope and (self._root / scope).is_dir():
            base = self._root / scope
        elif scope:
            # Scope names a document / file, not a directory — closure over
            # the index alone; nothing on disk to walk.
            return []
        else:
            base = self._root
        patterns = load_ignore_patterns(self._root)
        gaps = []
        for dirpath, dirnames, filenames in os.walk(base):
            rel_dir = Path(dirpath).relative_to(self._root).as_posix()
            # Prune ignored subtrees before descending
            dirnames[:] = [
                d
                for d in sorted(dirnames)
                if not _is_ignored((f"{rel_dir}/{d}" if rel_dir != "." else d) + "/placeholder", patterns)
            ]
            for fname in sorted(filenames):
                rel = f"{rel_dir}/{fname}" if rel_dir != "." else fname
                if not self._in_scope(rel, scope):
                    continue
                if self._excluded(rel, excludes):
                    continue
                if _is_ignored(rel, patterns):
                    continue
                if rel not in indexed:
                    gaps.append(rel)
        return gaps

    def _postings(self, query_text: str, scope: str, excludes: tuple) -> dict:
        """Evaluate a search query, restricted and post-filtered to the scope."""
        expr = f'(in "{scope}" {query_text})' if scope else query_text
        sr = self._search.evaluate(expr)
        posting = self._search._system.posting_morphism.inverse(sr) if isinstance(sr, list) else {}
        out = {}
        for key, val in posting.items():
            doc, _line = key
            if not self._in_scope(doc, scope) or self._excluded(doc, excludes):
                continue
            out[key] = val
        return out

    def _compose_satisfies(self, claim: QueryClaim) -> str:
        """Render the shared :forall composition back to query source text."""
        from ..search_engine.engine import compose_satisfies

        x_form = self._parser.translate(claim.query)
        s_form = self._parser.translate(claim.satisfies or "")
        return to_sexp(compose_satisfies(x_form, s_form))

    def _scoped_merkle(self, scope: str, excludes: tuple, indexed: set) -> tuple:
        """(checked_files, merkle_root) over the scoped indexed files' hashes."""
        hashes: dict = {}
        store = getattr(self._search, "_store", None)
        for entries in (getattr(store, "_dir_hashes", None) or {}).values():
            for rel, h in entries.items():
                if rel in indexed and self._in_scope(rel, scope) and not self._excluded(rel, excludes):
                    hashes[rel] = h
        if not hashes:
            n = sum(1 for d in indexed if self._in_scope(d, scope) and not self._excluded(d, excludes))
            return n, ""
        leaves = [MerkleNode(hash=h, content=f) for f, h in sorted(hashes.items())]
        return len(leaves), merkle_combine(leaves).hash
