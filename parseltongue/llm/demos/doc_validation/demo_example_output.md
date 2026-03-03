============================================================
Parseltongue LLM Pipeline — Documentation Validation
============================================================

  Model: anthropic/claude-sonnet-4.6
  Thinking: True
  Documents: ['README']

  Query: Validate this README for internal consistency. Are there any contradictions, unverifiable claims, or factual errors?

------------------------------------------------------------
  [INFO] Pass 1: Extraction
  [INFO] Pass 1 output:

;; ── Primitive anchors ──────────────────────────────────────────────────────

(defterm sha256
  :evidence (evidence "README"
    :quotes ("All cryptographic operations use SHA-256.")
    :explanation "SHA-256 is the sole hashing algorithm used by the library."))

(defterm seconds
  :evidence (evidence "README"
    :quotes ("Token lifetime in seconds")
    :explanation "Unit used for expiry and max lifetime values."))

;; ── Ground facts ───────────────────────────────────────────────────────────

(fact default-algorithm "sha256"
  :evidence (evidence "README"
    :quotes ("algorithm | sha256  | Hashing algorithm")
    :explanation "Default hashing algorithm is sha256 per the configuration table."))

(fact default-expiry-seconds 1800
  :evidence (evidence "README"
    :quotes ("expiry    | 1800    | Token lifetime in seconds")
    :explanation "Default token lifetime is 1800 seconds per the configuration table."))

(fact default-expiry-minutes 30
  :evidence (evidence "README"
    :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default.")
    :explanation "Default expiry stated in minutes in the Quick Start prose section."))

(fact max-token-lifetime-seconds 7200
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "Upper bound on token lifetime stated in Quick Start section."))

(fact max-token-lifetime-hours 2
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "Upper bound on token lifetime stated in hours."))

(fact default-max-sessions 10
  :evidence (evidence "README"
    :quotes ("max_sessions | 10  | Maximum concurrent sessions")
    :explanation "Default maximum concurrent sessions per the configuration table."))

(fact min-python-version "3.9"
  :evidence (evidence "README"
    :quotes ("Requires Python 3.9 or higher.")
    :explanation "Minimum required Python version."))

(fact session-ip-bound true
  :evidence (evidence "README"
    :quotes ("Each session is bound to a single IP address for security.")
    :explanation "Sessions are tied to one IP address."))

(fact session-id-algorithm "sha256"
  :evidence (evidence "README"
    :quotes ("Session IDs use the same hashing algorithm as tokens (SHA-256).")
    :explanation "Session IDs are hashed with SHA-256, consistent with the token algorithm."))

(fact token-algorithm "sha256"
  :evidence (evidence "README"
    :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default.")
    :explanation "Tokens explicitly use SHA-256."))

(fact security-audit-count 3
  :evidence (evidence "README"
    :quotes ("The library has been audited by three independent security firms")
    :explanation "Number of independent security auditors claimed."))

(fact known-vulnerabilities 0
  :evidence (evidence "README"
    :quotes ("contains zero known vulnerabilities as of version 2.0.")
    :explanation "Claimed vulnerability count as of v2.0."))

(fact quick-start-algorithm "sha256"
  :evidence (evidence "README"
    :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)")
    :explanation "Algorithm parameter in the Quick Start code example."))

(fact quick-start-expiry 1800
  :evidence (evidence "README"
    :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)")
    :explanation "Expiry parameter in the Quick Start code example."))

;; ── Derived canonical values ────────────────────────────────────────────────

(defterm seconds-per-minute 60
  :evidence (evidence "README"
    :quotes ("expire after 30 minutes by default." "expiry    | 1800    | Token lifetime in seconds")
    :explanation "Implicit conversion factor needed to reconcile minutes and seconds."))

(defterm default-expiry-seconds-from-minutes (* default-expiry-minutes seconds-per-minute)
  :evidence (evidence "README"
    :quotes ("expire after 30 minutes by default." "expiry    | 1800    | Token lifetime in seconds")
    :explanation "30 minutes × 60 s/min = 1800 s — tests consistency between prose and table."))

(defterm seconds-per-hour 3600
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "Implicit conversion factor needed to verify hours↔seconds equivalence."))

(defterm max-lifetime-seconds-from-hours (* max-token-lifetime-hours seconds-per-hour)
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "2 hours × 3600 s/hr = 7200 s — tests internal consistency of the claim."))

;; ── Consistency checks (ground derivations) ────────────────────────────────

;; Check 1: default expiry table vs. prose (1800 == 30 × 60?)
(defterm expiry-prose-table-consistent
  (= default-expiry-seconds-from-minutes default-expiry-seconds)
  :evidence (evidence "README"
    :quotes ("expire after 30 minutes by default." "expiry    | 1800    | Token lifetime in seconds")
    :explanation "30 min × 60 = 1800 s matches the table value — should be TRUE."))

;; Check 2: max lifetime hours vs. seconds (7200 == 2 × 3600?)
(defterm max-lifetime-hours-seconds-consistent
  (= max-lifetime-seconds-from-hours max-token-lifetime-seconds)
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "2 hr × 3600 = 7200 s matches the parenthetical — should be TRUE."))

;; Check 3: Quick Start code expiry matches table default
(defterm quickstart-expiry-matches-default
  (= quick-start-expiry default-expiry-seconds)
  :evidence (evidence "README"
    :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)"
             "expiry    | 1800    | Token lifetime in seconds")
    :explanation "Code example expiry (1800) matches configuration table default (1800) — should be TRUE."))

;; Check 4: Quick Start code algorithm matches table default
(defterm quickstart-algorithm-matches-default
  (= quick-start-algorithm default-algorithm)
  :evidence (evidence "README"
    :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)"
             "algorithm | sha256  | Hashing algorithm")
    :explanation "Code example algorithm (sha256) matches configuration table default (sha256) — should be TRUE."))

;; Check 5: Token algorithm matches session ID algorithm (internal consistency)
(defterm token-session-algorithm-consistent
  (= token-algorithm session-id-algorithm)
  :evidence (evidence "README"
    :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default."
             "Session IDs use the same hashing algorithm as tokens (SHA-256).")
    :explanation "Both tokens and session IDs use SHA-256 — consistent."))

;; Check 6: Security section global claim consistent with token and session facts
(defterm all-ops-sha256-consistent
  (and (= token-algorithm "sha256") (= session-id-algorithm "sha256"))
  :evidence (evidence "README"
    :quotes ("All cryptographic operations use SHA-256."
             "Tokens are generated using SHA-256 and expire after 30 minutes by default."
             "Session IDs use the same hashing algorithm as tokens (SHA-256).")
    :explanation "Both enumerated crypto operations use SHA-256, consistent with blanket claim."))

;; ── Unverifiable / external claims flagged as hypothetical facts ───────────

(fact security-audit-verifiable false
  :origin "Unverifiable: no audit report links, firm names, or dates are provided in the README.")

(fact zero-vulnerabilities-verifiable false
  :origin "Unverifiable: point-in-time claim tied to v2.0 with no CVE registry reference or date.")

;; ── Axiom: unit conversion correctness (parametric) ───────────────────────

(axiom minutes-to-seconds-conversion
  (= (* ?minutes 60) ?seconds)
  :evidence (evidence "README"
    :quotes ("expire after 30 minutes by default." "expiry    | 1800    | Token lifetime in seconds")
    :explanation "Parametric rule: any duration in minutes multiplied by 60 equals that duration in seconds."))

(axiom hours-to-seconds-conversion
  (= (* ?hours 3600) ?seconds)
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "Parametric rule: any duration in hours multiplied by 3600 equals that duration in seconds."))

  [INFO] Quote verified: "All cryptographic operations use SHA-256." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "algorithm | sha256  | Hashing algorithm" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Tokens are generated using SHA-256 and expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "max_sessions | 10  | Maximum concurrent sessions" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Requires Python 3.9 or higher." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Each session is bound to a single IP address for security." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Session IDs use the same hashing algorithm as tokens (SHA-256)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Tokens are generated using SHA-256 and expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The library has been audited by three independent security firms" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "contains zero known vulnerabilities as of version 2.0." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "manager = TokenManager(algorithm="sha256", expiry=1800)" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "manager = TokenManager(algorithm="sha256", expiry=1800)" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "manager = TokenManager(algorithm="sha256", expiry=1800)" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "manager = TokenManager(algorithm="sha256", expiry=1800)" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "algorithm | sha256  | Hashing algorithm" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Tokens are generated using SHA-256 and expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Session IDs use the same hashing algorithm as tokens (SHA-256)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "All cryptographic operations use SHA-256." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Tokens are generated using SHA-256 and expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Session IDs use the same hashing algorithm as tokens (SHA-256)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Pass 2: Derivation (blinded)
  [INFO] Pass 2 output:

;; ── 1. Expiry: prose minutes vs. table seconds ──────────────────────────────
;; Verify that default-expiry-minutes * 60 == default-expiry-seconds
(derive expiry-prose-table-check
    (= default-expiry-seconds-from-minutes default-expiry-seconds)
    :using (expiry-prose-table-consistent
            default-expiry-seconds-from-minutes
            default-expiry-seconds))

;; ── 2. Max token lifetime: hours vs. seconds ────────────────────────────────
;; Verify that max-token-lifetime-hours * 3600 == max-token-lifetime-seconds
(derive max-lifetime-consistency-check
    (= max-lifetime-seconds-from-hours max-token-lifetime-seconds)
    :using (max-lifetime-hours-seconds-consistent
            max-lifetime-seconds-from-hours
            max-token-lifetime-seconds))

;; ── 3. Quick-start expiry matches default expiry ────────────────────────────
(derive quickstart-expiry-check
    (= quick-start-expiry default-expiry-seconds)
    :using (quickstart-expiry-matches-default
            quick-start-expiry
            default-expiry-seconds))

;; ── 4. Quick-start algorithm matches default algorithm ──────────────────────
(derive quickstart-algorithm-check
    (= quick-start-algorithm default-algorithm)
    :using (quickstart-algorithm-matches-default
            quick-start-algorithm
            default-algorithm))

;; ── 5. Token algorithm == session-id algorithm (cross-module consistency) ───
(derive token-session-algo-check
    (= token-algorithm session-id-algorithm)
    :using (token-session-algorithm-consistent
            token-algorithm
            session-id-algorithm))

;; ── 6. Both algorithms are SHA-256 ──────────────────────────────────────────
(derive all-sha256-check
    (and (= token-algorithm "sha256") (= session-id-algorithm "sha256"))
    :using (all-ops-sha256-consistent
            token-algorithm
            session-id-algorithm))

;; ── 7. Security-audit claim is verifiable ───────────────────────────────────
(derive security-audit-verifiable-check
    (= security-audit-verifiable true)
    :using (security-audit-verifiable))

;; ── 8. Zero-vulnerabilities claim is verifiable ─────────────────────────────
(derive zero-vulnerabilities-verifiable-check
    (= zero-vulnerabilities-verifiable true)
    :using (zero-vulnerabilities-verifiable))

;; ── 9. Known vulnerabilities count is zero ──────────────────────────────────
(derive no-known-vulnerabilities
    (= known-vulnerabilities 0)
    :using (known-vulnerabilities))

;; ── 10. Diff: expiry-seconds as stated vs. computed from minutes ─────────────
(diff expiry-unit-drift
    :replace default-expiry-seconds
    :with    default-expiry-seconds-from-minutes)

;; ── 11. Diff: max-lifetime-seconds as stated vs. computed from hours ─────────
(diff max-lifetime-unit-drift
    :replace max-token-lifetime-seconds
    :with    max-lifetime-seconds-from-hours)

;; ── 12. Diff: quick-start expiry vs. default expiry ─────────────────────────
(diff quickstart-expiry-drift
    :replace quick-start-expiry
    :with    default-expiry-seconds)

;; ── 13. Diff: quick-start algorithm vs. default algorithm ───────────────────
(diff quickstart-algo-drift
    :replace quick-start-algorithm
    :with    default-algorithm)

;; ── 14. Diff: token algorithm vs. session-id algorithm ──────────────────────
(diff token-session-algo-drift
    :replace token-algorithm
    :with    session-id-algorithm)

  [WARNING] Derivation 'security-audit-verifiable-check' does not hold: (= security-audit-verifiable true) evaluated to False
  [WARNING] Derivation 'zero-vulnerabilities-verifiable-check' does not hold: (= zero-vulnerabilities-verifiable true) evaluated to False
  [INFO] Pass 3: Fact Check
  [WARNING] System inconsistent: 2 issue(s)
  No evidence provided:
    security-audit-verifiable
    zero-vulnerabilities-verifiable
  Potential fabrication:
    security-audit-verifiable-check
    zero-vulnerabilities-verifiable-check
  [INFO] Pass 3 output:

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 1: Cross-check default expiry via the Quick Start code example.
;; The code snippet hardcodes expiry=1800. Verify this matches the prose claim
;; of "30 minutes" by recomputing 30 min × 60 s/min independently from the
;; code-example value, and diff against the configuration table value.
;; ─────────────────────────────────────────────────────────────────────────────

(fact quick-start-expiry-seconds 1800
    :evidence (evidence "README"
        :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)")
        :explanation "The Quick Start code example hardcodes expiry=1800 seconds."))

(fact prose-expiry-minutes 30
    :evidence (evidence "README"
        :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default.")
        :explanation "The Quick Start prose states 30 minutes as the default expiry."))

(defterm prose-expiry-seconds-recomputed
    (* prose-expiry-minutes 60)
    :evidence (evidence "README"
        :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default."
                 "manager = TokenManager(algorithm=\"sha256\", expiry=1800)")
        :explanation "30 min × 60 s/min = 1800 s — independently recomputed from prose minutes and code example."))

(diff code-vs-prose-expiry
    :replace quick-start-expiry-seconds
    :with prose-expiry-seconds-recomputed)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 2: Cross-check maximum lifetime — hours claim vs. seconds claim vs.
;; default expiry. The README says max is 2 hours (7200 s). Verify the max
;; is strictly greater than the default (1800 s), i.e. the ordering is sane.
;; ─────────────────────────────────────────────────────────────────────────────

(fact max-lifetime-seconds-stated 7200
    :evidence (evidence "README"
        :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
        :explanation "The README explicitly states the maximum lifetime as 7200 seconds."))

(fact default-lifetime-seconds-stated 1800
    :evidence (evidence "README"
        :quotes ("expiry    | 1800    | Token lifetime in seconds")
        :explanation "Configuration table gives the default expiry as 1800 seconds."))

(defterm max-exceeds-default
    (> max-lifetime-seconds-stated default-lifetime-seconds-stated)
    :evidence (evidence "README"
        :quotes ("The maximum token lifetime is 2 hours (7200 seconds)."
                 "expiry    | 1800    | Token lifetime in seconds")
        :explanation "The maximum lifetime (7200 s) must exceed the default (1800 s) — a basic sanity constraint."))

(defterm max-is-exactly-4x-default
    (= max-lifetime-seconds-stated (* 4 default-lifetime-seconds-stated))
    :evidence (evidence "README"
        :quotes ("The maximum token lifetime is 2 hours (7200 seconds)."
                 "expiry    | 1800    | Token lifetime in seconds")
        :explanation "7200 = 4 × 1800 — the max is exactly four times the default, a cross-document arithmetic check."))

(diff max-vs-default-ordering
    :replace max-lifetime-seconds-stated
    :with default-lifetime-seconds-stated)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 3: Cross-check the "All cryptographic operations use SHA-256" blanket
;; claim against the configuration table algorithm entry. The table is the
;; authoritative config surface; if it ever diverged from "sha256" that blanket
;; claim would be false. Introduce an alternative algorithm to expose the
;; dependency, then diff.
;; ─────────────────────────────────────────────────────────────────────────────

(fact config-table-algorithm "sha256"
    :evidence (evidence "README"
        :quotes ("algorithm | sha256  | Hashing algorithm")
        :explanation "Configuration table lists sha256 as the algorithm — the authoritative config surface."))

(fact security-section-algorithm "sha256"
    :evidence (evidence "README"
        :quotes ("All cryptographic operations use SHA-256.")
        :explanation "Security section makes a blanket claim that all crypto operations use SHA-256."))

(defterm config-matches-security-claim
    (= config-table-algorithm security-section-algorithm)
    :evidence (evidence "README"
        :quotes ("algorithm | sha256  | Hashing algorithm"
                 "All cryptographic operations use SHA-256.")
        :explanation "The config table algorithm and the security-section blanket claim must agree."))

(diff config-table-vs-security-claim
    :replace config-table-algorithm
    :with security-section-algorithm)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 4: Verifiability audit — the security audit count (3 firms) and the
;; zero-vulnerabilities claim are both stated without supporting references.
;; Introduce explicit unverifiable markers and diff them against a hypothetical
;; "verified" baseline to surface the gap in evidence quality.
;; ─────────────────────────────────────────────────────────────────────────────

(fact security-audit-count-stated 3
    :evidence (evidence "README"
        :quotes ("The library has been audited by three independent security firms")
        :explanation "README claims three independent security audits but names no firms, dates, or report links."))

(fact audit-firms-named 0
    :origin "Hypothetical count of named audit firms — zero are named in the README.")

(defterm audit-claim-has-supporting-detail
    (> audit-firms-named 0)
    :origin "Check whether any audit firms are actually named — evaluates to False since audit-firms-named = 0.")

(diff audit-count-vs-named-firms
    :replace security-audit-count-stated
    :with audit-firms-named)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 5: Cross-check default-expiry-seconds against the configuration-table
;; entry via the minutes-to-seconds-conversion axiom instantiated with the
;; prose value (30 min), producing an independent derivation path, then diff
;; the derived value against the directly stated table fact.
;; ─────────────────────────────────────────────────────────────────────────────

(fact prose-minutes-value 30
    :evidence (evidence "README"
        :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default.")
        :explanation "The prose expiry in minutes, used to drive the unit-conversion axiom."))

(derive expiry-seconds-from-axiom
    (= (* 30 60) 1800)
    :using (prose-minutes-value default-expiry-seconds))

(defterm expiry-from-axiom-path
    (* prose-minutes-value 60)
    :evidence (evidence "README"
        :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default."
                 "expiry    | 1800    | Token lifetime in seconds")
        :explanation "Alternative derivation of 1800 s by applying 60 s/min to the prose 30-minute figure."))

(diff axiom-path-vs-table-expiry
    :replace default-expiry-seconds
    :with expiry-from-axiom-path)

  [INFO] Quote verified: "manager = TokenManager(algorithm="sha256", expiry=1800)" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Tokens are generated using SHA-256 and expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Tokens are generated using SHA-256 and expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "manager = TokenManager(algorithm="sha256", expiry=1800)" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The maximum token lifetime is 2 hours (7200 seconds)." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "algorithm | sha256  | Hashing algorithm" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "All cryptographic operations use SHA-256." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "algorithm | sha256  | Hashing algorithm" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "All cryptographic operations use SHA-256." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The library has been audited by three independent security firms" (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Tokens are generated using SHA-256 and expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Tokens are generated using SHA-256 and expire after 30 minutes by default." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "expiry    | 1800    | Token lifetime in seconds" (confidence: ConfidenceLevel.HIGH)
  [INFO] Pass 4: Inference
  [WARNING] System inconsistent: 4 issue(s)
  No evidence provided:
    audit-claim-has-supporting-detail
    audit-firms-named
    security-audit-verifiable
    zero-vulnerabilities-verifiable
  Potential fabrication:
    security-audit-verifiable-check
    zero-vulnerabilities-verifiable-check
  Diff divergence:
    max-vs-default-ordering: max-lifetime-seconds-stated (7200) vs default-lifetime-seconds-stated (1800)
      max-exceeds-default: True → False
      max-is-exactly-4x-default: True → False
  Diff value divergence:
    audit-count-vs-named-firms: security-audit-count-stated (3) vs audit-firms-named (0) — values differ
  [INFO] Pass 4 raw:

> ⚠️ **Inconsistencies Detected:** Two issues were found where the README's claims cannot be independently verified or internally reconciled. Details are in the **Flags & Warnings** section below.

---

# README Consistency Validation Report

## Summary

The README is **largely internally consistent** across its numeric values, algorithms, and timing claims. However, it contains **two significant issues**: one data divergence (the security audit claim is unsubstantiated) and two unverifiable security assertions. All other cross-checks passed cleanly.

---

## ✅ What Checks Out

### Token Expiry — Consistent Across All Sections

The default token lifetime of 1,800 seconds (30 minutes) is stated three separate ways in the README, and all three agree:

- The Quick Start prose says [[quote:default-expiry-minutes]]:
  > "Tokens are generated using SHA-256 and expire after 30 minutes by default."

- The Quick Start code example hardcodes `expiry=1800` [[quote:quick-start-expiry]]:
  > `manager = TokenManager(algorithm="sha256", expiry=1800)`

- The configuration table lists `expiry | 1800` [[quote:default-expiry-seconds]]:
  > "expiry    | 1800    | Token lifetime in seconds"

Cross-checks confirm 30 minutes × 60 seconds = 1,800 seconds [[theorem:expiry-prose-table-check]], the code example matches the table default [[theorem:quickstart-expiry-check]], and an independent unit-conversion path also yields 1,800 [[theorem:expiry-seconds-from-axiom]]. No drift anywhere [[diff:expiry-unit-drift]] [[diff:quickstart-expiry-drift]] [[diff:code-vs-prose-expiry]] [[diff:axiom-path-vs-table-expiry]].

### Maximum Token Lifetime — Consistent

The README states [[quote:max-token-lifetime-seconds]]:
> "The maximum token lifetime is 2 hours (7200 seconds)."

2 hours × 3,600 seconds/hour = 7,200 seconds — the arithmetic checks out [[theorem:max-lifetime-consistency-check]], and no divergence was found [[diff:max-lifetime-unit-drift]]. The maximum (7,200 s) correctly exceeds the default (1,800 s) [[term:max-exceeds-default]], and is exactly 4× the default [[term:max-is-exactly-4x-default]].

### Hashing Algorithm — Consistent Everywhere

SHA-256 is stated as the algorithm in four independent locations: the Quick Start prose [[quote:token-algorithm]], the code example [[quote:quick-start-algorithm]], the configuration table [[quote:default-algorithm]], and the Security section [[quote:security-section-algorithm]]:

> "All cryptographic operations use SHA-256."

All four agree [[theorem:all-sha256-check]]. Session IDs also use SHA-256, consistent with tokens [[theorem:token-session-algo-check]] [[quote:session-id-algorithm]]:
> "Session IDs use the same hashing algorithm as tokens (SHA-256)."

No algorithm drift found anywhere [[diff:quickstart-algo-drift]] [[diff:token-session-algo-drift]] [[diff:config-table-vs-security-claim]].

### Other Configuration Values — Verified

- Maximum concurrent sessions: **10** [[fact:default-max-sessions]], sourced from the config table [[quote:default-max-sessions]]:
  > "max_sessions | 10  | Maximum concurrent sessions"
- Minimum Python version: **3.9** [[fact:min-python-version]] [[quote:min-python-version]]:
  > "Requires Python 3.9 or higher."
- Session IP binding is documented [[fact:session-ip-bound]] [[quote:session-ip-bound]]:
  > "Each session is bound to a single IP address for security."

---

## 🚨 Flags & Warnings

### 1. Security Audit Claim — Unsubstantiated

The README asserts [[quote:security-audit-count]]:
> "The library has been audited by three independent security firms"

However, **zero firms are named**, and no audit report links, dates, or other corroborating details appear anywhere in the document [[fact:audit-firms-named]]. This creates a stark data divergence: the README claims 3 audits [[fact:security-audit-count-stated]], but 0 can be verified [[diff:audit-count-vs-named-firms]]. The claim is present in the text but provides no evidence a reader could independently check [[fact:security-audit-verifiable]].

This is a **credibility risk** — readers have no way to validate it.

### 2. Zero Known Vulnerabilities — Unverifiable Point-in-Time Claim

The README states [[quote:known-vulnerabilities]]:
> "contains zero known vulnerabilities as of version 2.0."

While the claim itself is textually present [[theorem:no-known-vulnerabilities]], it is tied to a specific version (v2.0) with **no CVE registry reference, no date, and no link to a vulnerability database** [[fact:zero-vulnerabilities-verifiable]]. There is no way for a reader to independently confirm this claim holds for their version or at the time of reading.

---

## Summary Table

| Check | Result |
|---|---|
| Prose expiry (30 min) matches config table (1800 s) | ✅ Consistent |
| Code example expiry matches config table | ✅ Consistent |
| Max lifetime hours/seconds internally consistent | ✅ Consistent |
| SHA-256 stated consistently across all sections | ✅ Consistent |
| Token and session ID algorithm match | ✅ Consistent |
| Config table algorithm matches Security section | ✅ Consistent |
| Security audit by 3 firms — verifiable | ❌ No firm names, dates, or links [[diff:audit-count-vs-named-firms]] |
| Zero known vulnerabilities — verifiable | ⚠️ Point-in-time claim, no CVE reference [[fact:zero-vulnerabilities-verifiable]] |

---

## Recommendations

1. **Name the audit firms** and link to published audit reports, or remove the claim.
2. **Add a CVE reference or vulnerability disclosure link** alongside the zero-vulnerabilities claim, and include the date the claim was last verified.

All numeric and algorithmic values in the README are internally self-consistent and pass cross-validation. The only issues are in the security section, where marketing-style claims lack the supporting evidence needed for independent verification.

  [WARNING] System inconsistent: 4 issue(s)
  No evidence provided:
    audit-claim-has-supporting-detail
    audit-firms-named
    security-audit-verifiable
    zero-vulnerabilities-verifiable
  Potential fabrication:
    security-audit-verifiable-check
    zero-vulnerabilities-verifiable-check
  Diff divergence:
    max-vs-default-ordering: max-lifetime-seconds-stated (7200) vs default-lifetime-seconds-stated (1800)
      max-exceeds-default: True → False
      max-is-exactly-4x-default: True → False
  Diff value divergence:
    audit-count-vs-named-firms: security-audit-count-stated (3) vs audit-firms-named (0) — values differ
# Parseltongue LLM Pipeline — Documentation Validation

**Model:** `N/A`

## Pass 1: Extracted DSL

```lisp

;; ── Primitive anchors ──────────────────────────────────────────────────────

(defterm sha256
  :evidence (evidence "README"
    :quotes ("All cryptographic operations use SHA-256.")
    :explanation "SHA-256 is the sole hashing algorithm used by the library."))

(defterm seconds
  :evidence (evidence "README"
    :quotes ("Token lifetime in seconds")
    :explanation "Unit used for expiry and max lifetime values."))

;; ── Ground facts ───────────────────────────────────────────────────────────

(fact default-algorithm "sha256"
  :evidence (evidence "README"
    :quotes ("algorithm | sha256  | Hashing algorithm")
    :explanation "Default hashing algorithm is sha256 per the configuration table."))

(fact default-expiry-seconds 1800
  :evidence (evidence "README"
    :quotes ("expiry    | 1800    | Token lifetime in seconds")
    :explanation "Default token lifetime is 1800 seconds per the configuration table."))

(fact default-expiry-minutes 30
  :evidence (evidence "README"
    :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default.")
    :explanation "Default expiry stated in minutes in the Quick Start prose section."))

(fact max-token-lifetime-seconds 7200
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "Upper bound on token lifetime stated in Quick Start section."))

(fact max-token-lifetime-hours 2
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "Upper bound on token lifetime stated in hours."))

(fact default-max-sessions 10
  :evidence (evidence "README"
    :quotes ("max_sessions | 10  | Maximum concurrent sessions")
    :explanation "Default maximum concurrent sessions per the configuration table."))

(fact min-python-version "3.9"
  :evidence (evidence "README"
    :quotes ("Requires Python 3.9 or higher.")
    :explanation "Minimum required Python version."))

(fact session-ip-bound true
  :evidence (evidence "README"
    :quotes ("Each session is bound to a single IP address for security.")
    :explanation "Sessions are tied to one IP address."))

(fact session-id-algorithm "sha256"
  :evidence (evidence "README"
    :quotes ("Session IDs use the same hashing algorithm as tokens (SHA-256).")
    :explanation "Session IDs are hashed with SHA-256, consistent with the token algorithm."))

(fact token-algorithm "sha256"
  :evidence (evidence "README"
    :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default.")
    :explanation "Tokens explicitly use SHA-256."))

(fact security-audit-count 3
  :evidence (evidence "README"
    :quotes ("The library has been audited by three independent security firms")
    :explanation "Number of independent security auditors claimed."))

(fact known-vulnerabilities 0
  :evidence (evidence "README"
    :quotes ("contains zero known vulnerabilities as of version 2.0.")
    :explanation "Claimed vulnerability count as of v2.0."))

(fact quick-start-algorithm "sha256"
  :evidence (evidence "README"
    :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)")
    :explanation "Algorithm parameter in the Quick Start code example."))

(fact quick-start-expiry 1800
  :evidence (evidence "README"
    :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)")
    :explanation "Expiry parameter in the Quick Start code example."))

;; ── Derived canonical values ────────────────────────────────────────────────

(defterm seconds-per-minute 60
  :evidence (evidence "README"
    :quotes ("expire after 30 minutes by default." "expiry    | 1800    | Token lifetime in seconds")
    :explanation "Implicit conversion factor needed to reconcile minutes and seconds."))

(defterm default-expiry-seconds-from-minutes (* default-expiry-minutes seconds-per-minute)
  :evidence (evidence "README"
    :quotes ("expire after 30 minutes by default." "expiry    | 1800    | Token lifetime in seconds")
    :explanation "30 minutes × 60 s/min = 1800 s — tests consistency between prose and table."))

(defterm seconds-per-hour 3600
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "Implicit conversion factor needed to verify hours↔seconds equivalence."))

(defterm max-lifetime-seconds-from-hours (* max-token-lifetime-hours seconds-per-hour)
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "2 hours × 3600 s/hr = 7200 s — tests internal consistency of the claim."))

;; ── Consistency checks (ground derivations) ────────────────────────────────

;; Check 1: default expiry table vs. prose (1800 == 30 × 60?)
(defterm expiry-prose-table-consistent
  (= default-expiry-seconds-from-minutes default-expiry-seconds)
  :evidence (evidence "README"
    :quotes ("expire after 30 minutes by default." "expiry    | 1800    | Token lifetime in seconds")
    :explanation "30 min × 60 = 1800 s matches the table value — should be TRUE."))

;; Check 2: max lifetime hours vs. seconds (7200 == 2 × 3600?)
(defterm max-lifetime-hours-seconds-consistent
  (= max-lifetime-seconds-from-hours max-token-lifetime-seconds)
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "2 hr × 3600 = 7200 s matches the parenthetical — should be TRUE."))

;; Check 3: Quick Start code expiry matches table default
(defterm quickstart-expiry-matches-default
  (= quick-start-expiry default-expiry-seconds)
  :evidence (evidence "README"
    :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)"
             "expiry    | 1800    | Token lifetime in seconds")
    :explanation "Code example expiry (1800) matches configuration table default (1800) — should be TRUE."))

;; Check 4: Quick Start code algorithm matches table default
(defterm quickstart-algorithm-matches-default
  (= quick-start-algorithm default-algorithm)
  :evidence (evidence "README"
    :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)"
             "algorithm | sha256  | Hashing algorithm")
    :explanation "Code example algorithm (sha256) matches configuration table default (sha256) — should be TRUE."))

;; Check 5: Token algorithm matches session ID algorithm (internal consistency)
(defterm token-session-algorithm-consistent
  (= token-algorithm session-id-algorithm)
  :evidence (evidence "README"
    :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default."
             "Session IDs use the same hashing algorithm as tokens (SHA-256).")
    :explanation "Both tokens and session IDs use SHA-256 — consistent."))

;; Check 6: Security section global claim consistent with token and session facts
(defterm all-ops-sha256-consistent
  (and (= token-algorithm "sha256") (= session-id-algorithm "sha256"))
  :evidence (evidence "README"
    :quotes ("All cryptographic operations use SHA-256."
             "Tokens are generated using SHA-256 and expire after 30 minutes by default."
             "Session IDs use the same hashing algorithm as tokens (SHA-256).")
    :explanation "Both enumerated crypto operations use SHA-256, consistent with blanket claim."))

;; ── Unverifiable / external claims flagged as hypothetical facts ───────────

(fact security-audit-verifiable false
  :origin "Unverifiable: no audit report links, firm names, or dates are provided in the README.")

(fact zero-vulnerabilities-verifiable false
  :origin "Unverifiable: point-in-time claim tied to v2.0 with no CVE registry reference or date.")

;; ── Axiom: unit conversion correctness (parametric) ───────────────────────

(axiom minutes-to-seconds-conversion
  (= (* ?minutes 60) ?seconds)
  :evidence (evidence "README"
    :quotes ("expire after 30 minutes by default." "expiry    | 1800    | Token lifetime in seconds")
    :explanation "Parametric rule: any duration in minutes multiplied by 60 equals that duration in seconds."))

(axiom hours-to-seconds-conversion
  (= (* ?hours 3600) ?seconds)
  :evidence (evidence "README"
    :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
    :explanation "Parametric rule: any duration in hours multiplied by 3600 equals that duration in seconds."))

```

## Pass 2: Derived DSL

```lisp

;; ── 1. Expiry: prose minutes vs. table seconds ──────────────────────────────
;; Verify that default-expiry-minutes * 60 == default-expiry-seconds
(derive expiry-prose-table-check
    (= default-expiry-seconds-from-minutes default-expiry-seconds)
    :using (expiry-prose-table-consistent
            default-expiry-seconds-from-minutes
            default-expiry-seconds))

;; ── 2. Max token lifetime: hours vs. seconds ────────────────────────────────
;; Verify that max-token-lifetime-hours * 3600 == max-token-lifetime-seconds
(derive max-lifetime-consistency-check
    (= max-lifetime-seconds-from-hours max-token-lifetime-seconds)
    :using (max-lifetime-hours-seconds-consistent
            max-lifetime-seconds-from-hours
            max-token-lifetime-seconds))

;; ── 3. Quick-start expiry matches default expiry ────────────────────────────
(derive quickstart-expiry-check
    (= quick-start-expiry default-expiry-seconds)
    :using (quickstart-expiry-matches-default
            quick-start-expiry
            default-expiry-seconds))

;; ── 4. Quick-start algorithm matches default algorithm ──────────────────────
(derive quickstart-algorithm-check
    (= quick-start-algorithm default-algorithm)
    :using (quickstart-algorithm-matches-default
            quick-start-algorithm
            default-algorithm))

;; ── 5. Token algorithm == session-id algorithm (cross-module consistency) ───
(derive token-session-algo-check
    (= token-algorithm session-id-algorithm)
    :using (token-session-algorithm-consistent
            token-algorithm
            session-id-algorithm))

;; ── 6. Both algorithms are SHA-256 ──────────────────────────────────────────
(derive all-sha256-check
    (and (= token-algorithm "sha256") (= session-id-algorithm "sha256"))
    :using (all-ops-sha256-consistent
            token-algorithm
            session-id-algorithm))

;; ── 7. Security-audit claim is verifiable ───────────────────────────────────
(derive security-audit-verifiable-check
    (= security-audit-verifiable true)
    :using (security-audit-verifiable))

;; ── 8. Zero-vulnerabilities claim is verifiable ─────────────────────────────
(derive zero-vulnerabilities-verifiable-check
    (= zero-vulnerabilities-verifiable true)
    :using (zero-vulnerabilities-verifiable))

;; ── 9. Known vulnerabilities count is zero ──────────────────────────────────
(derive no-known-vulnerabilities
    (= known-vulnerabilities 0)
    :using (known-vulnerabilities))

;; ── 10. Diff: expiry-seconds as stated vs. computed from minutes ─────────────
(diff expiry-unit-drift
    :replace default-expiry-seconds
    :with    default-expiry-seconds-from-minutes)

;; ── 11. Diff: max-lifetime-seconds as stated vs. computed from hours ─────────
(diff max-lifetime-unit-drift
    :replace max-token-lifetime-seconds
    :with    max-lifetime-seconds-from-hours)

;; ── 12. Diff: quick-start expiry vs. default expiry ─────────────────────────
(diff quickstart-expiry-drift
    :replace quick-start-expiry
    :with    default-expiry-seconds)

;; ── 13. Diff: quick-start algorithm vs. default algorithm ───────────────────
(diff quickstart-algo-drift
    :replace quick-start-algorithm
    :with    default-algorithm)

;; ── 14. Diff: token algorithm vs. session-id algorithm ──────────────────────
(diff token-session-algo-drift
    :replace token-algorithm
    :with    session-id-algorithm)

```

## Pass 3: Fact Check DSL

```lisp

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 1: Cross-check default expiry via the Quick Start code example.
;; The code snippet hardcodes expiry=1800. Verify this matches the prose claim
;; of "30 minutes" by recomputing 30 min × 60 s/min independently from the
;; code-example value, and diff against the configuration table value.
;; ─────────────────────────────────────────────────────────────────────────────

(fact quick-start-expiry-seconds 1800
    :evidence (evidence "README"
        :quotes ("manager = TokenManager(algorithm=\"sha256\", expiry=1800)")
        :explanation "The Quick Start code example hardcodes expiry=1800 seconds."))

(fact prose-expiry-minutes 30
    :evidence (evidence "README"
        :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default.")
        :explanation "The Quick Start prose states 30 minutes as the default expiry."))

(defterm prose-expiry-seconds-recomputed
    (* prose-expiry-minutes 60)
    :evidence (evidence "README"
        :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default."
                 "manager = TokenManager(algorithm=\"sha256\", expiry=1800)")
        :explanation "30 min × 60 s/min = 1800 s — independently recomputed from prose minutes and code example."))

(diff code-vs-prose-expiry
    :replace quick-start-expiry-seconds
    :with prose-expiry-seconds-recomputed)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 2: Cross-check maximum lifetime — hours claim vs. seconds claim vs.
;; default expiry. The README says max is 2 hours (7200 s). Verify the max
;; is strictly greater than the default (1800 s), i.e. the ordering is sane.
;; ─────────────────────────────────────────────────────────────────────────────

(fact max-lifetime-seconds-stated 7200
    :evidence (evidence "README"
        :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
        :explanation "The README explicitly states the maximum lifetime as 7200 seconds."))

(fact default-lifetime-seconds-stated 1800
    :evidence (evidence "README"
        :quotes ("expiry    | 1800    | Token lifetime in seconds")
        :explanation "Configuration table gives the default expiry as 1800 seconds."))

(defterm max-exceeds-default
    (> max-lifetime-seconds-stated default-lifetime-seconds-stated)
    :evidence (evidence "README"
        :quotes ("The maximum token lifetime is 2 hours (7200 seconds)."
                 "expiry    | 1800    | Token lifetime in seconds")
        :explanation "The maximum lifetime (7200 s) must exceed the default (1800 s) — a basic sanity constraint."))

(defterm max-is-exactly-4x-default
    (= max-lifetime-seconds-stated (* 4 default-lifetime-seconds-stated))
    :evidence (evidence "README"
        :quotes ("The maximum token lifetime is 2 hours (7200 seconds)."
                 "expiry    | 1800    | Token lifetime in seconds")
        :explanation "7200 = 4 × 1800 — the max is exactly four times the default, a cross-document arithmetic check."))

(diff max-vs-default-ordering
    :replace max-lifetime-seconds-stated
    :with default-lifetime-seconds-stated)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 3: Cross-check the "All cryptographic operations use SHA-256" blanket
;; claim against the configuration table algorithm entry. The table is the
;; authoritative config surface; if it ever diverged from "sha256" that blanket
;; claim would be false. Introduce an alternative algorithm to expose the
;; dependency, then diff.
;; ─────────────────────────────────────────────────────────────────────────────

(fact config-table-algorithm "sha256"
    :evidence (evidence "README"
        :quotes ("algorithm | sha256  | Hashing algorithm")
        :explanation "Configuration table lists sha256 as the algorithm — the authoritative config surface."))

(fact security-section-algorithm "sha256"
    :evidence (evidence "README"
        :quotes ("All cryptographic operations use SHA-256.")
        :explanation "Security section makes a blanket claim that all crypto operations use SHA-256."))

(defterm config-matches-security-claim
    (= config-table-algorithm security-section-algorithm)
    :evidence (evidence "README"
        :quotes ("algorithm | sha256  | Hashing algorithm"
                 "All cryptographic operations use SHA-256.")
        :explanation "The config table algorithm and the security-section blanket claim must agree."))

(diff config-table-vs-security-claim
    :replace config-table-algorithm
    :with security-section-algorithm)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 4: Verifiability audit — the security audit count (3 firms) and the
;; zero-vulnerabilities claim are both stated without supporting references.
;; Introduce explicit unverifiable markers and diff them against a hypothetical
;; "verified" baseline to surface the gap in evidence quality.
;; ─────────────────────────────────────────────────────────────────────────────

(fact security-audit-count-stated 3
    :evidence (evidence "README"
        :quotes ("The library has been audited by three independent security firms")
        :explanation "README claims three independent security audits but names no firms, dates, or report links."))

(fact audit-firms-named 0
    :origin "Hypothetical count of named audit firms — zero are named in the README.")

(defterm audit-claim-has-supporting-detail
    (> audit-firms-named 0)
    :origin "Check whether any audit firms are actually named — evaluates to False since audit-firms-named = 0.")

(diff audit-count-vs-named-firms
    :replace security-audit-count-stated
    :with audit-firms-named)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 5: Cross-check default-expiry-seconds against the configuration-table
;; entry via the minutes-to-seconds-conversion axiom instantiated with the
;; prose value (30 min), producing an independent derivation path, then diff
;; the derived value against the directly stated table fact.
;; ─────────────────────────────────────────────────────────────────────────────

(fact prose-minutes-value 30
    :evidence (evidence "README"
        :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default.")
        :explanation "The prose expiry in minutes, used to drive the unit-conversion axiom."))

(derive expiry-seconds-from-axiom
    (= (* 30 60) 1800)
    :using (prose-minutes-value default-expiry-seconds))

(defterm expiry-from-axiom-path
    (* prose-minutes-value 60)
    :evidence (evidence "README"
        :quotes ("Tokens are generated using SHA-256 and expire after 30 minutes by default."
                 "expiry    | 1800    | Token lifetime in seconds")
        :explanation "Alternative derivation of 1800 s by applying 60 s/min to the prose 30-minute figure."))

(diff axiom-path-vs-table-expiry
    :replace default-expiry-seconds
    :with expiry-from-axiom-path)

```

## Pass 4: Grounded Answer


> ⚠️ **Inconsistencies Detected:** Two issues were found where the README's claims cannot be independently verified or internally reconciled. Details are in the **Flags & Warnings** section below.

---

# README Consistency Validation Report

## Summary

The README is **largely internally consistent** across its numeric values, algorithms, and timing claims. However, it contains **two significant issues**: one data divergence (the security audit claim is unsubstantiated) and two unverifiable security assertions. All other cross-checks passed cleanly.

---

## ✅ What Checks Out

### Token Expiry — Consistent Across All Sections

The default token lifetime of 1,800 seconds (30 minutes) is stated three separate ways in the README, and all three agree:

- The Quick Start prose says [[quote:default-expiry-minutes]]:
  > "Tokens are generated using SHA-256 and expire after 30 minutes by default."

- The Quick Start code example hardcodes `expiry=1800` [[quote:quick-start-expiry]]:
  > `manager = TokenManager(algorithm="sha256", expiry=1800)`

- The configuration table lists `expiry | 1800` [[quote:default-expiry-seconds]]:
  > "expiry    | 1800    | Token lifetime in seconds"

Cross-checks confirm 30 minutes × 60 seconds = 1,800 seconds [[theorem:expiry-prose-table-check]], the code example matches the table default [[theorem:quickstart-expiry-check]], and an independent unit-conversion path also yields 1,800 [[theorem:expiry-seconds-from-axiom]]. No drift anywhere [[diff:expiry-unit-drift]] [[diff:quickstart-expiry-drift]] [[diff:code-vs-prose-expiry]] [[diff:axiom-path-vs-table-expiry]].

### Maximum Token Lifetime — Consistent

The README states [[quote:max-token-lifetime-seconds]]:
> "The maximum token lifetime is 2 hours (7200 seconds)."

2 hours × 3,600 seconds/hour = 7,200 seconds — the arithmetic checks out [[theorem:max-lifetime-consistency-check]], and no divergence was found [[diff:max-lifetime-unit-drift]]. The maximum (7,200 s) correctly exceeds the default (1,800 s) [[term:max-exceeds-default]], and is exactly 4× the default [[term:max-is-exactly-4x-default]].

### Hashing Algorithm — Consistent Everywhere

SHA-256 is stated as the algorithm in four independent locations: the Quick Start prose [[quote:token-algorithm]], the code example [[quote:quick-start-algorithm]], the configuration table [[quote:default-algorithm]], and the Security section [[quote:security-section-algorithm]]:

> "All cryptographic operations use SHA-256."

All four agree [[theorem:all-sha256-check]]. Session IDs also use SHA-256, consistent with tokens [[theorem:token-session-algo-check]] [[quote:session-id-algorithm]]:
> "Session IDs use the same hashing algorithm as tokens (SHA-256)."

No algorithm drift found anywhere [[diff:quickstart-algo-drift]] [[diff:token-session-algo-drift]] [[diff:config-table-vs-security-claim]].

### Other Configuration Values — Verified

- Maximum concurrent sessions: **10** [[fact:default-max-sessions]], sourced from the config table [[quote:default-max-sessions]]:
  > "max_sessions | 10  | Maximum concurrent sessions"
- Minimum Python version: **3.9** [[fact:min-python-version]] [[quote:min-python-version]]:
  > "Requires Python 3.9 or higher."
- Session IP binding is documented [[fact:session-ip-bound]] [[quote:session-ip-bound]]:
  > "Each session is bound to a single IP address for security."

---

## 🚨 Flags & Warnings

### 1. Security Audit Claim — Unsubstantiated

The README asserts [[quote:security-audit-count]]:
> "The library has been audited by three independent security firms"

However, **zero firms are named**, and no audit report links, dates, or other corroborating details appear anywhere in the document [[fact:audit-firms-named]]. This creates a stark data divergence: the README claims 3 audits [[fact:security-audit-count-stated]], but 0 can be verified [[diff:audit-count-vs-named-firms]]. The claim is present in the text but provides no evidence a reader could independently check [[fact:security-audit-verifiable]].

This is a **credibility risk** — readers have no way to validate it.

### 2. Zero Known Vulnerabilities — Unverifiable Point-in-Time Claim

The README states [[quote:known-vulnerabilities]]:
> "contains zero known vulnerabilities as of version 2.0."

While the claim itself is textually present [[theorem:no-known-vulnerabilities]], it is tied to a specific version (v2.0) with **no CVE registry reference, no date, and no link to a vulnerability database** [[fact:zero-vulnerabilities-verifiable]]. There is no way for a reader to independently confirm this claim holds for their version or at the time of reading.

---

## Summary Table

| Check | Result |
|---|---|
| Prose expiry (30 min) matches config table (1800 s) | ✅ Consistent |
| Code example expiry matches config table | ✅ Consistent |
| Max lifetime hours/seconds internally consistent | ✅ Consistent |
| SHA-256 stated consistently across all sections | ✅ Consistent |
| Token and session ID algorithm match | ✅ Consistent |
| Config table algorithm matches Security section | ✅ Consistent |
| Security audit by 3 firms — verifiable | ❌ No firm names, dates, or links [[diff:audit-count-vs-named-firms]] |
| Zero known vulnerabilities — verifiable | ⚠️ Point-in-time claim, no CVE reference [[fact:zero-vulnerabilities-verifiable]] |

---

## Recommendations

1. **Name the audit firms** and link to published audit reports, or remove the claim.
2. **Add a CVE reference or vulnerability disclosure link** alongside the zero-vulnerabilities claim, and include the date the claim was last verified.

All numeric and algorithmic values in the README are internally self-consistent and pass cross-validation. The only issues are in the security section, where marketing-style claims lack the supporting evidence needed for independent verification.


## Resolved References

- `[[quote:default-expiry-minutes]]` = 30
- `[[quote:quick-start-expiry]]` = 1800
- `[[quote:default-expiry-seconds]]` = 1800
- `[[theorem:expiry-prose-table-check]]` = (= default-expiry-seconds-from-minutes default-expiry-seconds)
- `[[theorem:quickstart-expiry-check]]` = (= quick-start-expiry default-expiry-seconds)
- `[[theorem:expiry-seconds-from-axiom]]` = (= (* 30 60) 1800)
- `[[diff:expiry-unit-drift]]` = expiry-unit-drift: default-expiry-seconds (1800) vs default-expiry-seconds-from-minutes (1800) — no divergences
- `[[diff:quickstart-expiry-drift]]` = quickstart-expiry-drift: quick-start-expiry (1800) vs default-expiry-seconds (1800) — no divergences
- `[[diff:code-vs-prose-expiry]]` = code-vs-prose-expiry: quick-start-expiry-seconds (1800) vs prose-expiry-seconds-recomputed (1800) — no divergences
- `[[diff:axiom-path-vs-table-expiry]]` = axiom-path-vs-table-expiry: default-expiry-seconds (1800) vs expiry-from-axiom-path (1800) — no divergences
- `[[quote:max-token-lifetime-seconds]]` = 7200
- `[[theorem:max-lifetime-consistency-check]]` = (= max-lifetime-seconds-from-hours max-token-lifetime-seconds)
- `[[diff:max-lifetime-unit-drift]]` = max-lifetime-unit-drift: max-token-lifetime-seconds (7200) vs max-lifetime-seconds-from-hours (7200) — no divergences
- `[[term:max-exceeds-default]]` = True
- `[[term:max-is-exactly-4x-default]]` = True
- `[[quote:token-algorithm]]` = sha256
- `[[quote:quick-start-algorithm]]` = sha256
- `[[quote:default-algorithm]]` = sha256
- `[[quote:security-section-algorithm]]` = sha256
- `[[theorem:all-sha256-check]]` = (and (= token-algorithm "sha256") (= session-id-algorithm "sha256"))
- `[[theorem:token-session-algo-check]]` = (= token-algorithm session-id-algorithm)
- `[[quote:session-id-algorithm]]` = sha256
- `[[diff:quickstart-algo-drift]]` = quickstart-algo-drift: quick-start-algorithm (sha256) vs default-algorithm (sha256) — no divergences
- `[[diff:token-session-algo-drift]]` = token-session-algo-drift: token-algorithm (sha256) vs session-id-algorithm (sha256) — no divergences
- `[[diff:config-table-vs-security-claim]]` = config-table-vs-security-claim: config-table-algorithm (sha256) vs security-section-algorithm (sha256) — no divergences
- `[[fact:default-max-sessions]]` = 10
- `[[quote:default-max-sessions]]` = 10
- `[[fact:min-python-version]]` = 3.9
- `[[quote:min-python-version]]` = 3.9
- `[[fact:session-ip-bound]]` = True
- `[[quote:session-ip-bound]]` = True
- `[[quote:security-audit-count]]` = 3
- `[[fact:audit-firms-named]]` = 0
- `[[fact:security-audit-count-stated]]` = 3
- `[[diff:audit-count-vs-named-firms]]` = audit-count-vs-named-firms: security-audit-count-stated (3) vs audit-firms-named (0) — values differ
- `[[fact:security-audit-verifiable]]` = False
- `[[quote:known-vulnerabilities]]` = 0
- `[[theorem:no-known-vulnerabilities]]` = (= known-vulnerabilities 0)
- `[[fact:zero-vulnerabilities-verifiable]]` = False

## Final System State

- **System:** System(2 axioms, 10 theorems, 18 terms, 25 facts, 10 diffs, 1 docs)
- **Facts:** `default-algorithm`, `default-expiry-seconds`, `default-expiry-minutes`, `max-token-lifetime-seconds`, `max-token-lifetime-hours`, `default-max-sessions`, `min-python-version`, `session-ip-bound`, `session-id-algorithm`, `token-algorithm`, `security-audit-count`, `known-vulnerabilities`, `quick-start-algorithm`, `quick-start-expiry`, `security-audit-verifiable`, `zero-vulnerabilities-verifiable`, `quick-start-expiry-seconds`, `prose-expiry-minutes`, `max-lifetime-seconds-stated`, `default-lifetime-seconds-stated`, `config-table-algorithm`, `security-section-algorithm`, `security-audit-count-stated`, `audit-firms-named`, `prose-minutes-value`
- **Terms:** `sha256`, `seconds`, `seconds-per-minute`, `default-expiry-seconds-from-minutes`, `seconds-per-hour`, `max-lifetime-seconds-from-hours`, `expiry-prose-table-consistent`, `max-lifetime-hours-seconds-consistent`, `quickstart-expiry-matches-default`, `quickstart-algorithm-matches-default`, `token-session-algorithm-consistent`, `all-ops-sha256-consistent`, `prose-expiry-seconds-recomputed`, `max-exceeds-default`, `max-is-exactly-4x-default`, `config-matches-security-claim`, `audit-claim-has-supporting-detail`, `expiry-from-axiom-path`
- **Theorems:** `expiry-prose-table-check`, `max-lifetime-consistency-check`, `quickstart-expiry-check`, `quickstart-algorithm-check`, `token-session-algo-check`, `all-sha256-check`, `security-audit-verifiable-check`, `zero-vulnerabilities-verifiable-check`, `no-known-vulnerabilities`, `expiry-seconds-from-axiom`
- **Diffs:** `expiry-unit-drift`, `max-lifetime-unit-drift`, `quickstart-expiry-drift`, `quickstart-algo-drift`, `token-session-algo-drift`, `code-vs-prose-expiry`, `max-vs-default-ordering`, `config-table-vs-security-claim`, `audit-count-vs-named-firms`, `axiom-path-vs-table-expiry`

## Consistency

{'consistent': False, 'issues': [{'type': 'no_evidence', 'items': ['audit-claim-has-supporting-detail', 'audit-firms-named', 'security-audit-verifiable', 'zero-vulnerabilities-verifiable']}, {'type': 'potential_fabrication', 'items': ['security-audit-verifiable-check', 'zero-vulnerabilities-verifiable-check']}, {'type': 'diff_divergence', 'items': [{'name': 'max-vs-default-ordering', 'replace': 'max-lifetime-seconds-stated', 'with': 'default-lifetime-seconds-stated', 'value_a': 7200, 'value_b': 1800, 'divergences': {'max-exceeds-default': [True, False], 'max-is-exactly-4x-default': [True, False]}}]}, {'type': 'diff_value_divergence', 'items': [{'name': 'audit-count-vs-named-firms', 'replace': 'security-audit-count-stated', 'with': 'audit-firms-named', 'value_a': 3, 'value_b': 0, 'divergences': {}}]}], 'warnings': []}

## Provenance: `expiry-prose-table-check`

```json
{
  "name": "expiry-prose-table-check",
  "type": "theorem",
  "wff": "(= default-expiry-seconds-from-minutes default-expiry-seconds)",
  "origin": "derived",
  "derivation_chain": [
    {
      "name": "expiry-prose-table-consistent",
      "type": "term",
      "definition": "(= default-expiry-seconds-from-minutes default-expiry-seconds)",
      "origin": {
        "document": "README",
        "quotes": [
          "expire after 30 minutes by default.",
          "expiry    | 1800    | Token lifetime in seconds"
        ],
        "explanation": "30 min \u00d7 60 = 1800 s matches the table value \u2014 should be TRUE.",
        "verified": true,
        "verify_manual": false,
        "grounded": true,
        "verification": [
          {
            "quote": "expire after 30 minutes by default.",
            "verified": true,
            "original_position": 354,
            "normalized_position": 310,
            "length": 6,
            "positions": {
              "original": {
                "start": 354,
                "end": 387
              },
              "normalized": {
                "start": 310,
                "end": 343
              }
            },
            "confidence": {
              "score": 0.979,
              "level": "high"
            },
            "transformations": [
              {
                "type": "punctuation_removal",
                "description": "Removed 1 punctuation character(s)",
                "penalty": 0.02
              },
              {
                "type": "whitespace_trimming",
                "description": "Trimmed leading/trailing whitespace",
                "penalty": 0.001
              }
            ],
            "context": {
              "full": "...\nTokens are generated using SHA-256 and expire after 30 minutes by default.\nThe maximum token lifetime is 2 hours...",
              "before": "\nTokens are generated using SHA-256 and ",
              "after": ".\nThe maximum token lifetime is 2 hours"
            }
          },
          {
            "quote": "expiry    | 1800    | Token lifetime in seconds",
            "verified": true,
            "original_position": 585,
            "normalized_position": 475,
            "length": 6,
            "positions": {
              "original": {
                "start": 585,
                "end": 631
              },
              "normalized": {
                "start": 475,
                "end": 511
              }
            },
            "confidence": {
              "score": 0.969,
              "level": "high"
            },
            "transformations": [
              {
                "type": "case_normalization",
                "description": "Converted text to lowercase",
                "penalty": 0.01
              },
              {
                "type": "punctuation_removal",
                "description": "Removed 2 punctuation character(s)",
                "penalty": 0.02
              },
              {
                "type": "whitespace_normalization",
                "description": "Normalized whitespace",
                "penalty": 0.001
              }
            ],
            "context": {
              "full": "...rithm | sha256  | Hashing algorithm |\n| expiry    | 1800    | Token lifetime in seconds |\n| max_sessions | 10  | Maximum concu...",
              "before": "rithm | sha256  | Hashing algorithm |\n| ",
              "after": " |\n| max_sessions | 10  | Maximum concu"
            }
          }
        ]
      }
    },
    {
      "name": "default-expiry-seconds-from-minutes",
      "type": "term",
      "definition": "(* default-expiry-minutes seconds-per-minute)",
      "origin": {
        "document": "README",
        "quotes": [
          "expire after 30 minutes by default.",
          "expiry    | 1800    | Token lifetime in seconds"
        ],
        "explanation": "30 minutes \u00d7 60 s/min = 1800 s \u2014 tests consistency between prose and table.",
        "verified": true,
        "verify_manual": false,
        "grounded": true,
        "verification": [
          {
            "quote": "expire after 30 minutes by default.",
            "verified": true,
            "original_position": 354,
            "normalized_position": 310,
            "length": 6,
            "positions": {
              "original": {
                "start": 354,
                "end": 387
              },
              "normalized": {
                "start": 310,
                "end": 343
              }
            },
            "confidence": {
              "score": 0.979,
              "level": "high"
            },
            "transformations": [
              {
                "type": "punctuation_removal",
                "description": "Removed 1 punctuation character(s)",
                "penalty": 0.02
              },
              {
                "type": "whitespace_trimming",
                "description": "Trimmed leading/trailing whitespace",
                "penalty": 0.001
              }
            ],
            "context": {
              "full": "...\nTokens are generated using SHA-256 and expire after 30 minutes by default.\nThe maximum token lifetime is 2 hours...",
              "before": "\nTokens are generated using SHA-256 and ",
              "after": ".\nThe maximum token lifetime is 2 hours"
            }
          },
          {
            "quote": "expiry    | 1800    | Token lifetime in seconds",
            "verified": true,
            "original_position": 585,
            "normalized_position": 475,
            "length": 6,
            "positions": {
              "original": {
                "start": 585,
                "end": 631
              },
              "normalized": {
                "start": 475,
                "end": 511
              }
            },
            "confidence": {
              "score": 0.969,
              "level": "high"
            },
            "transformations": [
              {
                "type": "case_normalization",
                "description": "Converted text to lowercase",
                "penalty": 0.01
              },
              {
                "type": "punctuation_removal",
                "description": "Removed 2 punctuation character(s)",
                "penalty": 0.02
              },
              {
                "type": "whitespace_normalization",
                "description": "Normalized whitespace",
                "penalty": 0.001
              }
            ],
            "context": {
              "full": "...rithm | sha256  | Hashing algorithm |\n| expiry    | 1800    | Token lifetime in seconds |\n| max_sessions | 10  | Maximum concu...",
              "before": "rithm | sha256  | Hashing algorithm |\n| ",
              "after": " |\n| max_sessions | 10  | Maximum concu"
            }
          }
        ]
      }
    },
    {
      "name": "default-expiry-seconds",
      "type": "fact",
      "origin": {
        "document": "README",
        "quotes": [
          "expiry    | 1800    | Token lifetime in seconds"
        ],
        "explanation": "Default token lifetime is 1800 seconds per the configuration table.",
        "verified": true,
        "verify_manual": false,
        "grounded": true,
        "verification": [
          {
            "quote": "expiry    | 1800    | Token lifetime in seconds",
            "verified": true,
            "original_position": 585,
            "normalized_position": 475,
            "length": 6,
            "positions": {
              "original": {
                "start": 585,
                "end": 631
              },
              "normalized": {
                "start": 475,
                "end": 511
              }
            },
            "confidence": {
              "score": 0.969,
              "level": "high"
            },
            "transformations": [
              {
                "type": "case_normalization",
                "description": "Converted text to lowercase",
                "penalty": 0.01
              },
              {
                "type": "punctuation_removal",
                "description": "Removed 2 punctuation character(s)",
                "penalty": 0.02
              },
              {
                "type": "whitespace_normalization",
                "description": "Normalized whitespace",
                "penalty": 0.001
              }
            ],
            "context": {
              "full": "...rithm | sha256  | Hashing algorithm |\n| expiry    | 1800    | Token lifetime in seconds |\n| max_sessions | 10  | Maximum concu...",
              "before": "rithm | sha256  | Hashing algorithm |\n| ",
              "after": " |\n| max_sessions | 10  | Maximum concu"
            }
          }
        ]
      }
    }
  ]
}
```

