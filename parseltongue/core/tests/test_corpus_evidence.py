"""Corpus-quantified evidence — :absent / :forall on the evidence form.

Covers the four layers of the feature:
  1. parsing (lang.parse_evidence → corpus_query Evidence)
  2. the Evidence typed interior (interface preservation, round-trips)
  3. the engine's per-type verifier registry (dispatch, injection, reverify)
  4. CorpusEvidenceVerifier against a real search index (closure gate,
     merkle provenance, counter-examples, :except, :forall composition)
"""

import os
import shutil
import unittest
from dataclasses import replace
from unittest.mock import patch

from ..atoms import (
    EVIDENCE_TYPE_CORPUS_QUERY,
    EVIDENCE_TYPE_DOC_QUOTE,
    CorpusSource,
    Evidence,
    QueryClaim,
    QuoteClaim,
)
from ..engine import IssueType, reverify_evidence
from ..inspect.corpus_evidence import CorpusEvidenceVerifier
from ..inspect.search import Search
from ..inspect.store import SearchStore, Store
from ..lang import PGStringParser, _clause_to_sexp, _sexp_to_clause, parse_evidence
from ..serialization.serializers import deserialize_evidence, serialize_evidence
from ..system import System, load_source

_p = PGStringParser()


def _ev(source: str) -> Evidence:
    return parse_evidence(_p.translate(source))


# ============================================================
# 1. Parsing
# ============================================================


class TestParseCorpusEvidence(unittest.TestCase):
    def test_absent_form(self):
        ev = _ev('(evidence "src/auth" :absent (re "md5|sha1") :except ("tests/"))')
        self.assertEqual(ev.type, EVIDENCE_TYPE_CORPUS_QUERY)
        self.assertEqual(ev.source, CorpusSource(pattern="src/auth", excludes=("tests/",)))
        self.assertEqual(len(ev.claims), 1)
        claim = ev.claims[0]
        self.assertIsInstance(claim, QueryClaim)
        self.assertEqual(claim.polarity, "absent")
        self.assertEqual(claim.query, '(re "md5|sha1")')
        self.assertIsNone(claim.satisfies)
        self.assertFalse(ev.is_grounded)

    def test_forall_form(self):
        ev = _ev('(evidence "src/api" :forall (re "route") :satisfies (near 5 (re "auth")))')
        claim = ev.claims[0]
        self.assertEqual(claim.polarity, "forall")
        self.assertEqual(claim.query, '(re "route")')
        self.assertEqual(claim.satisfies, '(near 5 (re "auth"))')

    def test_interface_preserving_views(self):
        ev = _ev('(evidence "src/auth" :absent (re "md5"))')
        self.assertEqual(ev.document, "src/auth")
        self.assertEqual(ev.quotes, ['(re "md5")'])

    def test_explanation_carried(self):
        ev = _ev('(evidence "src" :absent (re "x") :explanation "no x allowed")')
        self.assertEqual(ev.explanation, "no x allowed")

    def test_plain_string_query(self):
        ev = _ev('(evidence "src" :absent "MD5")')
        self.assertEqual(ev.claims[0].query, "MD5")

    def test_classic_form_unchanged(self):
        ev = _ev('(evidence "Paper" :quotes ("verbatim") :explanation "why")')
        self.assertEqual(ev.type, EVIDENCE_TYPE_DOC_QUOTE)
        self.assertEqual(ev.claims, (QuoteClaim(text="verbatim"),))

    def test_both_polarities_rejected(self):
        with self.assertRaises(SyntaxError):
            _ev('(evidence "s" :absent (re "x") :forall (re "y") :satisfies (re "z"))')

    def test_forall_requires_satisfies(self):
        with self.assertRaises(SyntaxError):
            _ev('(evidence "s" :forall (re "x"))')

    def test_absent_rejects_satisfies(self):
        with self.assertRaises(SyntaxError):
            _ev('(evidence "s" :absent (re "x") :satisfies (re "y"))')

    def test_corpus_rejects_quotes(self):
        with self.assertRaises(SyntaxError):
            _ev('(evidence "s" :absent (re "x") :quotes ("q"))')


# ============================================================
# 2. Typed interior + round-trips
# ============================================================


class TestEvidenceTypedInterior(unittest.TestCase):
    def test_legacy_constructor_positional(self):
        ev = Evidence("Doc", ["q1", "q2"], "expl")
        self.assertEqual(ev.type, EVIDENCE_TYPE_DOC_QUOTE)
        self.assertEqual(ev.document, "Doc")
        self.assertEqual(ev.quotes, ["q1", "q2"])
        self.assertEqual(ev.explanation, "expl")

    def test_replace_keeps_interior(self):
        ev = _ev('(evidence "src" :absent (re "x"))')
        grounded = replace(ev, verification=[{"verified": True}], verified=True)
        self.assertTrue(grounded.is_grounded)
        self.assertEqual(grounded.claims, ev.claims)
        self.assertEqual(grounded.source, ev.source)

    def test_clause_roundtrip(self):
        ev = _ev('(evidence "src/api" :forall (re "route") :satisfies (near 5 (re "auth")) :except ("tests/"))')
        self.assertEqual(_sexp_to_clause(_clause_to_sexp(ev)), replace(ev, explanation=ev.explanation))

    def test_serializer_roundtrip(self):
        ev = _ev('(evidence "src/auth" :absent (re "md5") :except ("tests/" "docs/"))')
        self.assertEqual(deserialize_evidence(serialize_evidence(ev)), ev)

    def test_doc_quote_sexp_shape_unchanged(self):
        ev = Evidence("Doc", ["q"])
        sexp = _clause_to_sexp(ev)
        self.assertEqual(len(sexp), 4)  # (evidence doc quotes verified) — no trailing type fields


# ============================================================
# 3. Verifier registry
# ============================================================


class _StubVerifier:
    """Test double implementing the EvidenceVerifier protocol."""

    def __init__(self, verified: bool, counter_examples=None, reason=None):
        self.verified = verified
        self.counter_examples = counter_examples
        self.reason = reason
        self.calls = 0

    def verify(self, evidence: Evidence, caller=None) -> Evidence:
        self.calls += 1
        result = {"verified": self.verified}
        if self.counter_examples is not None:
            result["counter_examples"] = self.counter_examples
        if self.reason:
            result["reason"] = self.reason
        return replace(evidence, verification=[result], verified=self.verified)


_ABSENT_FACT = '(fact no-weak-hash true\n  :evidence (evidence "src/auth" :absent (re "md5")))'
_FORALL_FACT = (
    '(fact all-routes-authed true\n'
    '  :evidence (evidence "src/api" :forall (re "route") :satisfies (near 5 (re "auth"))))'
)


class TestVerifierRegistry(unittest.TestCase):
    def _issues(self, system) -> dict:
        report = system.engine.consistency()
        return {i.type: i.items for i in report.issues}

    def test_empty_corpus_left_ungrounded(self):
        """No registered documents match the scope — refused, never vacuously true."""
        system = System()
        load_source(system, _ABSENT_FACT)
        issues = self._issues(system)
        self.assertIn(IssueType.UNVERIFIED_EVIDENCE, issues)
        name, details = issues[IssueType.UNVERIFIED_EVIDENCE][0]
        self.assertTrue(any("no registered documents match scope" in d for d in details))

    def test_unregistered_type_left_ungrounded(self):
        system = System()
        system.engine._evidence_verifiers.pop(EVIDENCE_TYPE_CORPUS_QUERY)
        load_source(system, _ABSENT_FACT)
        issues = self._issues(system)
        self.assertIn(IssueType.UNVERIFIED_EVIDENCE, issues)

    def test_constructor_injection_grounds_claim(self):
        stub = _StubVerifier(verified=True)
        system = System(evidence_verifiers={EVIDENCE_TYPE_CORPUS_QUERY: stub})
        load_source(system, _ABSENT_FACT)
        self.assertEqual(stub.calls, 1)
        self.assertTrue(system.engine.facts["no-weak-hash"].origin.is_grounded)
        self.assertNotIn(IssueType.UNVERIFIED_EVIDENCE, self._issues(system))

    def test_refuted_absent_is_absence_violated(self):
        stub = _StubVerifier(verified=False, counter_examples=[["src/auth/legacy.py", 3, "import md5"]])
        system = System(evidence_verifiers={EVIDENCE_TYPE_CORPUS_QUERY: stub})
        load_source(system, _ABSENT_FACT)
        issues = self._issues(system)
        self.assertIn(IssueType.ABSENCE_VIOLATED, issues)
        name, examples = issues[IssueType.ABSENCE_VIOLATED][0]
        self.assertEqual(name, "no-weak-hash")
        self.assertEqual(examples, [["src/auth/legacy.py", 3, "import md5"]])

    def test_refuted_forall_is_obligation_violated(self):
        stub = _StubVerifier(verified=False, counter_examples=[["src/api/routes.py", 10, "@route"]])
        system = System(evidence_verifiers={EVIDENCE_TYPE_CORPUS_QUERY: stub})
        load_source(system, _FORALL_FACT)
        issues = self._issues(system)
        self.assertIn(IssueType.OBLIGATION_VIOLATED, issues)
        self.assertNotIn(IssueType.ABSENCE_VIOLATED, issues)

    def test_closure_refusal_is_unverified_with_reason(self):
        stub = _StubVerifier(verified=False, reason="closure failure — 1 file(s) unclassified")
        system = System(evidence_verifiers={EVIDENCE_TYPE_CORPUS_QUERY: stub})
        load_source(system, _ABSENT_FACT)
        issues = self._issues(system)
        self.assertIn(IssueType.UNVERIFIED_EVIDENCE, issues)
        name, details = issues[IssueType.UNVERIFIED_EVIDENCE][0]
        self.assertIn("reason: closure failure — 1 file(s) unclassified", details)

    def test_register_then_reverify(self):
        system = System()
        load_source(system, _ABSENT_FACT)
        self.assertFalse(system.engine.facts["no-weak-hash"].origin.is_grounded)
        system.engine.register_evidence_verifier(EVIDENCE_TYPE_CORPUS_QUERY, _StubVerifier(verified=True))
        changed = reverify_evidence(system.engine, EVIDENCE_TYPE_CORPUS_QUERY)
        self.assertEqual(changed, 1)
        self.assertTrue(system.engine.facts["no-weak-hash"].origin.is_grounded)
        self.assertNotIn(IssueType.UNVERIFIED_EVIDENCE, self._issues(system))

    def test_ungrounded_corpus_fact_taints_derives(self):
        system = System()
        load_source(system, _ABSENT_FACT)
        load_source(system, "(derive secure-auth no-weak-hash :using (no-weak-hash))")
        origin = system.engine.theorems["secure-auth"].origin
        self.assertIn("potential fabrication", str(origin))

    def test_doc_quote_still_dispatches_to_quote_verifier(self):
        system = System()
        system.engine.register_document("Paper", "the exact words are here")
        load_source(system, '(fact cited true :evidence (evidence "Paper" :quotes ("exact words")))')
        self.assertTrue(system.engine.facts["cited"].origin.is_grounded)


# ============================================================
# 4. Document-level claims — synthetic end-to-end over a real system
# ============================================================


_DOC_LEVEL_SOURCE = """
(fact no-weak-hash true
  :evidence (evidence "security" :absent (re "md5|sha1") :except ("security/archive")))

(fact all-endpoints-authed true
  :evidence (evidence "api" :forall (re "@route") :satisfies (near 2 (re "@auth"))))

(fact bcrypt-cited true
  :evidence (evidence "security/policy.md" :quotes ("passwords are hashed with bcrypt")))

(derive hardening-ok (and no-weak-hash all-endpoints-authed) :using (no-weak-hash all-endpoints-authed))
"""


class TestDocumentLevelClaims(unittest.TestCase):
    """Real .pltg source, real System — no bench, no filesystem corpus."""

    def _system(self) -> System:
        system = System()
        system.engine.register_document("security/policy.md", "passwords are hashed with bcrypt\nno exceptions\n")
        system.engine.register_document("security/archive", "old md5 notes, exempted\n")
        system.engine.register_document("api/routes.md", "@route /login\n@auth required\n")
        load_source(system, _DOC_LEVEL_SOURCE)
        return system

    def test_clean_system_is_consistent(self):
        system = self._system()
        report = system.engine.consistency()
        self.assertTrue(report.consistent, [str(i) for i in report.issues])
        for name in ("no-weak-hash", "all-endpoints-authed", "bcrypt-cited"):
            origin = system.engine.facts[name].origin
            self.assertTrue(origin.is_grounded, name)
        self.assertNotIn("potential fabrication", str(system.engine.theorems["hardening-ok"].origin))

    def test_provenance_records_scoped_content_hashes(self):
        system = self._system()
        record = system.engine.facts["no-weak-hash"].origin.verification[0]
        self.assertEqual(record["corpus"], "registered-documents")
        self.assertEqual(sorted(record["content_hashes"]), ["security/policy.md"])

    def test_late_document_breach_flips_to_violation(self):
        system = self._system()
        system.engine.register_document("security/legacy.md", "digest = md5(password)\n")
        report = system.engine.consistency()
        self.assertFalse(report.consistent)
        by_type = {i.type: i.items for i in report.issues}
        self.assertIn(IssueType.ABSENCE_VIOLATED, by_type)
        name, examples = by_type[IssueType.ABSENCE_VIOLATED][0]
        self.assertEqual(name, "no-weak-hash")
        self.assertEqual(examples[0][0], "security/legacy.md")
        self.assertIn("md5", examples[0][2])

    def test_unmet_obligation_is_violated_with_counter_example(self):
        system = self._system()
        system.engine.register_document("api/admin.md", "@route /admin\nno guard here\n")
        report = system.engine.consistency()
        by_type = {i.type: i.items for i in report.issues}
        self.assertIn(IssueType.OBLIGATION_VIOLATED, by_type)
        name, examples = by_type[IssueType.OBLIGATION_VIOLATED][0]
        self.assertEqual(name, "all-endpoints-authed")
        self.assertEqual(examples[0][:2], ["api/admin.md", 1])

    def test_violation_taints_downstream_derives(self):
        system = self._system()
        system.engine.register_document("security/legacy.md", "digest = md5(password)\n")
        load_source(system, "(derive still-safe no-weak-hash :using (no-weak-hash))")
        self.assertIn("potential fabrication", str(system.engine.theorems["still-safe"].origin))


# ============================================================
# 5. CorpusEvidenceVerifier against a real file index (bench override)
# ============================================================

TEST_DIR = "/tmp/corpus-evidence-test"


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestCorpusEvidenceVerifier(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DIR):
            shutil.rmtree(TEST_DIR)
        os.makedirs(TEST_DIR)
        _write(
            os.path.join(TEST_DIR, "pg.toml"),
            '[detect]\nlanguages = ["python"]\n'
            "[index]\n"
            'extensions = [".py"]\n'
            "max_file_size_bytes = 1048576\n"
            "allow_large = []\n",
        )
        _write(os.path.join(TEST_DIR, ".pgignore"), ".bench/\npg.toml\n.pgignore\n")
        _write(os.path.join(TEST_DIR, "src/auth/login.py"), "import sha256\n\ndef login():\n    pass\n")
        _write(os.path.join(TEST_DIR, "src/auth/session.py"), "TOKEN = 'sha256'\n")
        _write(
            os.path.join(TEST_DIR, "src/api/routes.py"),
            "@route\n@auth\ndef a():\n    pass\n\n\n\n\n@route\ndef unprotected():\n    pass\n",
        )

    def tearDown(self):
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def _verifier(self) -> CorpusEvidenceVerifier:
        with patch("os.getcwd", return_value=TEST_DIR):
            search = Search(SearchStore(store=Store(os.path.join(TEST_DIR, ".bench")), path=TEST_DIR))
            search.index_dir(TEST_DIR)
        return CorpusEvidenceVerifier(search, TEST_DIR)

    def test_absent_satisfied_pins_merkle_root(self):
        v = self._verifier()
        out = v.verify(_ev('(evidence "src/auth" :absent (re "md5"))'))
        self.assertTrue(out.verified)
        record = out.verification[0]
        self.assertTrue(record["merkle_root"])
        self.assertEqual(record["checked_files"], 2)

    def test_absent_violated_yields_counter_examples(self):
        _write(os.path.join(TEST_DIR, "src/auth/legacy.py"), "import md5\n")
        v = self._verifier()
        out = v.verify(_ev('(evidence "src/auth" :absent (re "md5"))'))
        self.assertFalse(out.verified)
        examples = out.verification[0]["counter_examples"]
        self.assertEqual(len(examples), 1)
        doc, line, context = examples[0]
        self.assertIn("legacy.py", doc)
        self.assertEqual(line, 1)
        self.assertIn("md5", context)

    def test_except_exempts_matches(self):
        _write(os.path.join(TEST_DIR, "src/auth/tests/test_legacy.py"), "import md5\n")
        v = self._verifier()
        refused = v.verify(_ev('(evidence "src/auth" :absent (re "md5"))'))
        self.assertFalse(refused.verified)
        exempted = v.verify(_ev('(evidence "src/auth" :absent (re "md5") :except ("tests/"))'))
        self.assertTrue(exempted.verified)

    def test_forall_near_satisfied_and_violated(self):
        v = self._verifier()
        out = v.verify(_ev('(evidence "src/api" :forall (re "@route") :satisfies (near 1 (re "@auth")))'))
        self.assertFalse(out.verified)
        examples = out.verification[0]["counter_examples"]
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0][1], 9)  # the unprotected @route line

    def test_closure_gate_refuses_unclassified_file(self):
        _write(os.path.join(TEST_DIR, "src/auth/creds.bin"), "opaque")
        v = self._verifier()
        out = v.verify(_ev('(evidence "src/auth" :absent (re "md5"))'))
        self.assertFalse(out.verified)
        reason = out.verification[0]["reason"]
        self.assertIn("closure failure", reason)
        self.assertIn("creds.bin", reason)
        self.assertIn(".pgignore", reason)

    def test_closure_gate_accepts_excepted_file(self):
        _write(os.path.join(TEST_DIR, "src/auth/creds.bin"), "opaque")
        v = self._verifier()
        out = v.verify(_ev('(evidence "src/auth" :absent (re "md5") :except ("creds.bin"))'))
        self.assertTrue(out.verified)

    def test_reverify_flips_after_corpus_change(self):
        v = self._verifier()
        ev = v.verify(_ev('(evidence "src/auth" :absent (re "md5"))'))
        self.assertTrue(ev.verified)
        root_before = ev.verification[0]["merkle_root"]

        _write(os.path.join(TEST_DIR, "src/auth/legacy.py"), "import md5\n")
        with patch("os.getcwd", return_value=TEST_DIR):
            v._search.reindex()
        again = v.verify(ev)
        self.assertFalse(again.verified)
        self.assertIn("legacy.py", again.verification[0]["counter_examples"][0][0])

        # ...and back: removing the breach re-grounds with a new root
        os.remove(os.path.join(TEST_DIR, "src/auth/legacy.py"))
        with patch("os.getcwd", return_value=TEST_DIR):
            v._search.reindex()
        healed = v.verify(again)
        self.assertTrue(healed.verified)
        self.assertNotEqual(healed.verification[0]["merkle_root"], "")
        self.assertEqual(healed.verification[0]["merkle_root"], root_before)


if __name__ == "__main__":
    unittest.main()
