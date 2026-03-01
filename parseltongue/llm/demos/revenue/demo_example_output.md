# Parseltongue LLM Pipeline — Revenue Reports

This is a sample run of the demo.

**Model:** `anthropic/claude-sonnet-4.6`

**Thinking:** Enabled

**Documents:** Q3 Report, FY2024 Targets Memo, Bonus Policy Doc

**Query:** *Did the company beat its growth target in Q3? What is the bonus?*

---

## Pass 1: Extraction

```scheme
;; ─────────────────────────────────────────────
;; FACTS – ground truth values from source docs
;; ─────────────────────────────────────────────

(fact revenue-q3 15.0
  :evidence (evidence "Q3 Report"
    :quotes ("Q3 revenue was $15M")
    :explanation "Q3 FY2024 revenue figure in millions"))

(fact revenue-q3-yoy-growth 15.0
  :evidence (evidence "Q3 Report"
    :quotes ("Q3 revenue was $15M, up 15% year-over-year")
    :explanation "Q3 year-over-year revenue growth percentage reported directly"))

(fact revenue-q2-baseline 210.0
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Q2 FY2024 actual revenue was $210M")
    :explanation "Q2 FY2024 audited revenue baseline used for target-setting"))

(fact revenue-q3-baseline 230.0
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Q3 FY2024 actual revenue was $230M")
    :explanation "Q3 FY2024 audited revenue baseline used for target-setting"))

(fact growth-target 10.0
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Revenue growth target for FY2024: 10%")
    :explanation "Board-approved annual revenue growth target for FY2024"))

(fact accelerated-tier-threshold 5.0
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Divisions that exceed the target by more than 5 percentage points
              will qualify for the accelerated bonus tier")
    :explanation "Margin above growth target required to qualify for accelerated bonus tier"))

(fact base-salary 150000.0
  :evidence (evidence "Bonus Policy Doc"
    :quotes ("Base salary for eligible employees is $150,000")
    :explanation "Base salary used for bonus calculation"))

(fact standard-bonus-rate 0.20
  :evidence (evidence "Bonus Policy Doc"
    :quotes ("Bonus is 20% of base salary if growth target is exceeded")
    :explanation "Standard bonus rate: 20% of base salary"))

(fact accelerated-bonus-rate 0.30
  :evidence (evidence "Bonus Policy Doc"
    :quotes ("the accelerated bonus tier, which pays 30% of base salary
              instead of the standard 20%")
    :explanation "Accelerated bonus rate: 30% of base salary"))

;; ─────────────────────────────────────────────
;; TERMS – derived / computed concepts
;; ─────────────────────────────────────────────

;; Compute growth from Q2→Q3 using audited baseline figures as a cross-check
(defterm revenue-q3-growth-computed
  (/ (- revenue-q3-baseline revenue-q2-baseline) revenue-q2-baseline)
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Q2 FY2024 actual revenue was $210M. Q3 FY2024 actual revenue was $230M.
              These figures are sourced from the finance team's audited quarterly submissions.")
    :explanation "Quarter-over-quarter growth rate computed from audited baselines: (230-210)/210"))

;; Primary growth figure taken directly from Q3 Report
(defterm revenue-q3-growth revenue-q3-yoy-growth
  :evidence (evidence "Q3 Report"
    :quotes ("Q3 revenue was $15M, up 15% year-over-year")
    :explanation "Year-over-year growth percentage as stated in Q3 Report"))

;; Did the company beat the standard growth target?
(defterm beat-growth-target
  (> revenue-q3-growth growth-target)
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Exceeding the growth target is defined as achieving year-over-year
              revenue growth above the stated target percentage")
    :explanation "Beat target when actual YoY growth exceeds the 10% target"))

;; How many percentage points above the target?
(defterm growth-above-target
  (- revenue-q3-growth growth-target)
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Divisions that exceed the target by more than 5 percentage points
              will qualify for the accelerated bonus tier")
    :explanation "Margin by which actual growth exceeds the stated target"))

;; Does the company qualify for the accelerated bonus tier?
(defterm qualifies-accelerated-tier
  (> growth-above-target accelerated-tier-threshold)
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Divisions that exceed the target by more than 5 percentage points
              will qualify for the accelerated bonus tier")
    :explanation "Accelerated tier triggered when growth exceeds target by more than 5pp"))

;; Standard bonus amount
(defterm standard-bonus-amount
  (* base-salary standard-bonus-rate)
  :evidence (evidence "Bonus Policy Doc"
    :quotes ("Bonus is 20% of base salary if growth target is exceeded"
             "Base salary for eligible employees is $150,000")
    :explanation "Standard bonus = 20% × $150,000 = $30,000"))

;; Accelerated bonus amount
(defterm accelerated-bonus-amount
  (* base-salary accelerated-bonus-rate)
  :evidence (evidence "Bonus Policy Doc"
    :quotes ("the accelerated bonus tier, which pays 30% of base salary
              instead of the standard 20%"
             "Base salary for eligible employees is $150,000")
    :explanation "Accelerated bonus = 30% × $150,000 = $45,000"))

;; Final bonus: accelerated if threshold exceeded, else standard (if target beaten), else 0
(defterm bonus-amount
  (if qualifies-accelerated-tier
      accelerated-bonus-amount
      (if beat-growth-target
          standard-bonus-amount
          0))
  :evidence (evidence "Bonus Policy Doc"
    :quotes ("Bonus is 20% of base salary if growth target is exceeded"
             "Eligibility requires that the quarterly revenue growth exceeds
              the stated annual growth target"
             "the accelerated bonus tier, which pays 30% of base salary
              instead of the standard 20%")
    :explanation "Bonus is accelerated (30%) if growth exceeds target by >5pp,
                  standard (20%) if target is merely exceeded, else $0"))

;; ─────────────────────────────────────────────
;; AXIOMS – general rewrite / logical rules
;; ─────────────────────────────────────────────

(axiom growth-target-exceeded-definition
  (= (> ?actual ?target) beat-growth-target)
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Exceeding the growth target is defined as achieving year-over-year
              revenue growth above the stated target percentage")
    :explanation "General rule: beating the target means actual growth strictly
                  exceeds the stated target"))

(axiom accelerated-tier-rule
  (implies (> growth-above-target accelerated-tier-threshold) qualifies-accelerated-tier)
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Divisions that exceed the target by more than 5 percentage points
              will qualify for the accelerated bonus tier")
    :explanation "If growth exceeds target by more than 5pp, accelerated tier is triggered"))

(axiom standard-bonus-rule
  (implies (and beat-growth-target (not qualifies-accelerated-tier))
           (= bonus-amount standard-bonus-amount))
  :evidence (evidence "Bonus Policy Doc"
    :quotes ("Bonus is 20% of base salary if growth target is exceeded"
             "Eligibility requires that the quarterly revenue growth exceeds
              the stated annual growth target")
    :explanation "Standard 20% bonus applies when target is exceeded
                  but accelerated tier is not reached"))

(axiom accelerated-bonus-rule
  (implies qualifies-accelerated-tier (= bonus-amount accelerated-bonus-amount))
  :evidence (evidence "Bonus Policy Doc"
    :quotes ("the accelerated bonus tier, which pays 30% of base salary
              instead of the standard 20%")
    :explanation "Accelerated 30% bonus applies when growth exceeds target
                  by more than 5 percentage points"))
```

### Quote Verification

```text
[INFO] Quote verified: "Q3 revenue was $15M" (confidence: HIGH)
[INFO] Quote verified: "Q3 revenue was $15M, up 15% year-over-year" (confidence: HIGH)
[INFO] Quote verified: "Q2 FY2024 actual revenue was $210M" (confidence: HIGH)
[INFO] Quote verified: "Q3 FY2024 actual revenue was $230M" (confidence: HIGH)
[INFO] Quote verified: "Revenue growth target for FY2024: 10%" (confidence: HIGH)
[INFO] Quote verified: "Divisions that exceed the target by more than 5 percentage points..." (confidence: HIGH)
[INFO] Quote verified: "Base salary for eligible employees is $150,000" (confidence: HIGH)
[INFO] Quote verified: "Bonus is 20% of base salary if growth target is exceeded" (confidence: HIGH)
[INFO] Quote verified: "the accelerated bonus tier, which pays 30% of base salary..." (confidence: HIGH)
[INFO] Quote verified: "Q2 FY2024 actual revenue was $210M. Q3 FY2024 actual..." (confidence: HIGH)
[INFO] Quote verified: "Exceeding the growth target is defined as achieving..." (confidence: HIGH)
[INFO] Quote verified: "Eligibility requires that the quarterly revenue growth..." (confidence: HIGH)
```

All 25 quotes verified with HIGH confidence.

---

## Pass 2: Derivation (Blinded)

> *The LLM sees names and types but **not values** — forcing structural reasoning.*

```scheme
;; Step 1: Derive whether the company beat its growth target
(derive beat-growth-target-check
    (> revenue-q3-growth growth-target)
    :using (revenue-q3-growth growth-target))

;; Step 2: Derive how far above (or below) the target the growth is
(defterm growth-above-target-value
    (- revenue-q3-growth growth-target)
    :origin "Gap between actual Q3 growth and the growth target")

;; Step 3: Derive whether the accelerated tier is triggered
(derive accelerated-tier-check
    (> growth-above-target accelerated-tier-threshold)
    :using (growth-above-target accelerated-tier-threshold))

;; Step 4: Apply the accelerated-tier-rule axiom
(derive accelerated-tier-qualifies
    (implies (> growth-above-target accelerated-tier-threshold)
             qualifies-accelerated-tier)
    :using (accelerated-tier-rule growth-above-target
            accelerated-tier-threshold qualifies-accelerated-tier))

;; Step 5: Apply the accelerated bonus rule
(derive accelerated-bonus-applies
    (implies qualifies-accelerated-tier
             (= bonus-amount accelerated-bonus-amount))
    :using (accelerated-bonus-rule qualifies-accelerated-tier
            bonus-amount accelerated-bonus-amount))

;; Step 6: Apply the standard bonus rule
(derive standard-bonus-applies
    (implies (and beat-growth-target (not qualifies-accelerated-tier))
             (= bonus-amount standard-bonus-amount))
    :using (standard-bonus-rule beat-growth-target
            qualifies-accelerated-tier bonus-amount standard-bonus-amount))

;; Step 7: Derive the final bonus amount from the full conditional term
(derive final-bonus-amount
    (= bonus-amount
       (if qualifies-accelerated-tier
           accelerated-bonus-amount
           (if beat-growth-target standard-bonus-amount 0)))
    :using (bonus-amount qualifies-accelerated-tier
            accelerated-bonus-amount beat-growth-target standard-bonus-amount))

;; Step 8: Cross-check — compare YoY growth vs QoQ computed growth
(diff growth-source-check
    :replace revenue-q3-growth
    :with revenue-q3-growth-computed)
```

```text
[WARNING] Derivation 'accelerated-tier-check' does not hold:
          (> growth-above-target accelerated-tier-threshold) evaluated to False
```

---

## Pass 3: Fact Check

> *Full system state visible. The LLM independently constructs cross-validation angles, each ending in a diff.*

### Consistency State Entering Pass 3

```text
[WARNING] System inconsistent: 3 issue(s)
  No evidence provided: growth-above-target-value
  Potential fabrication: accelerated-tier-check
    growth-source-check: revenue-q3-growth (15.0) vs revenue-q3-growth-computed (0.095)
  beat-growth-target:      True → False
  growth-above-target-value: 5.0 → -9.90
  bonus-amount:            30000.0 → 0
  growth-above-target:     5.0 → -9.90
```

### Angle 1: Cross-check revenue growth metric type

```scheme
;; The system uses revenue-q3-yoy-growth = 15.0 (year-over-year %)
;; but the Targets Memo provides Q2→Q3 absolute figures ($210M→$230M),
;; implying the target comparison should use sequential growth (~9.52%),
;; NOT the YoY figure (15%).

(defterm revenue-q3-sequential-growth-pct
    (* (/ (- revenue-q3-baseline revenue-q2-baseline) revenue-q2-baseline) 100)
    :evidence (evidence "FY2024 Targets Memo"
        :quotes ("Q2 FY2024 actual revenue was $210M"
                 "Q3 FY2024 actual revenue was $230M"
                 "Revenue growth target for FY2024: 10%")
        :explanation "Sequential Q2-to-Q3 growth recomputed from audited absolute
                      baseline figures: (230-210)/210 * 100 = 9.52%. This does NOT
                      beat the 10% growth target — in direct conflict with the
                      system's use of the YoY figure (15%) which does."))

(diff growth-metric-type-check
    :replace revenue-q3-growth
    :with revenue-q3-sequential-growth-pct)
```

### Angle 2: Verify the accelerated-tier boundary condition

```scheme
;; growth-above-target = 15.0 - 10.0 = 5.0
;; qualifies-accelerated-tier = (> 5.0 5.0) = FALSE
;; The policy says "more than 5 percentage points" — exactly 5 does NOT qualify.

(fact growth-target-from-memo 10.0
    :evidence (evidence "FY2024 Targets Memo"
        :quotes ("Revenue growth target for FY2024: 10%")
        :explanation "Board-approved 10% annual growth target, confirmed
                      independently for boundary check"))

(defterm growth-margin-above-target
    (- revenue-q3-yoy-growth growth-target-from-memo)
    :evidence (evidence "FY2024 Targets Memo"
        :quotes ("Revenue growth target for FY2024: 10%"
                 "Divisions that exceed the target by more than 5 percentage
                  points will qualify for the accelerated bonus tier")
        :explanation "Margin = 15% - 10% = 5.0pp. Since the accelerated tier
                      requires STRICTLY MORE THAN 5pp, a margin of exactly 5.0
                      does NOT qualify. Confirms qualifies-accelerated-tier = False
                      and bonus-amount = standard ($30,000)."))

(diff accelerated-tier-boundary-check
    :replace growth-above-target
    :with growth-margin-above-target)
```

### Angle 3: Verify bonus amount via direct policy arithmetic

```scheme
;; Independent recomputation from raw policy numbers,
;; bypassing the system's own base-salary and standard-bonus-rate symbols.

(defterm standard-bonus-direct
    (* 150000.0 0.2)
    :evidence (evidence "Bonus Policy Doc"
        :quotes ("Bonus is 20% of base salary if growth target is exceeded"
                 "Base salary for eligible employees is $150,000")
        :explanation "Direct arithmetic: 20% × $150,000 = $30,000. Independent
                      of system symbols, confirms the standard bonus figure."))

(diff bonus-arithmetic-check
    :replace standard-bonus-amount
    :with standard-bonus-direct)
```

---

## Pass 4: Grounded Answer

> ⚠️ **Inconsistency Detected: Growth Rate Figures Do Not Agree Across Sources**
>
> Two independent ways of measuring Q3 revenue growth produce materially different results \[\[diff:growth-source-check\]\] \[\[diff:growth-metric-type-check\]\]:
> - The Q3 Report states **15% year-over-year growth** \[\[fact:revenue-q3-yoy-growth\]\]
> - Computing sequential growth from the audited quarterly baselines ($210M → $230M) yields only **~9.5% quarter-over-quarter** \[\[term:revenue-q3-sequential-growth-pct\]\]
> - Computing year-over-year growth from those same baselines yields only **~9.5%**, not 15% \[\[term:revenue-q3-growth-computed\]\]
>
> The bonus conclusion below rests on the **reported YoY figure of 15%**. If the correct growth rate is closer to 9.5%, the target would **not** be beaten and the bonus would be **$0**. This discrepancy should be resolved before the bonus is paid.

---

### Did the Company Beat Its Growth Target in Q3?

**Yes — based on the reported figure.** Q3 year-over-year revenue growth was reported at **15%** \[\[fact:revenue-q3-yoy-growth\]\], against a board-approved growth target of **10%** \[\[fact:growth-target\]\]. The growth target was therefore exceeded by **5 percentage points** \[\[term:growth-above-target\]\].

The Q3 Report states:

> "Q3 revenue was $15M, up 15% year-over-year." \[\[quote:revenue-q3-yoy-growth\]\]

The FY2024 Targets Memo confirms the hurdle:

> "Revenue growth target for FY2024: 10%." \[\[quote:growth-target\]\]

The eligibility rule is clear:

> "Exceeding the growth target is defined as achieving year-over-year revenue growth above the stated target percentage." \[\[quote:beat-growth-target\]\]

This confirms that the 15% reported growth beats the 10% target \[\[theorem:beat-growth-target-check\]\].

---

### What Is the Bonus?

**The computed bonus is $30,000 (standard tier).**

#### Bonus Structure

There are two tiers \[\[axiom:accelerated-tier-rule\]\] \[\[axiom:standard-bonus-rule\]\]:

| Tier | Condition | Rate | Amount |
|---|---|---|---|
| **Standard** | Growth exceeds 10% target | 20% of base salary | **$30,000** |
| **Accelerated** | Growth exceeds target by **more than 5 pp** | 30% of base salary | $45,000 |

#### Which Tier Applies?

The reported growth exceeded the 10% target by exactly **5 percentage points** \[\[term:growth-above-target\]\]. The accelerated tier requires exceeding the target by **more than** 5 pp — so this division lands precisely at the boundary and does **not** qualify for the accelerated tier \[\[term:qualifies-accelerated-tier\]\].

The standard tier therefore applies \[\[theorem:standard-bonus-applies\]\]:

> **$150,000 base salary** \[\[fact:base-salary\]\] × **20%** \[\[fact:standard-bonus-rate\]\] = **$30,000** \[\[term:standard-bonus-amount\]\]

The arithmetic is independently confirmed \[\[diff:bonus-arithmetic-check\]\].

---

### ⚠️ Key Caveats

1. **The growth figure is disputed.** The reported 15% YoY growth does not reconcile with growth computed from the audited quarterly baselines ($210M Q2 → $230M Q3), which implies only ~9.5% \[\[diff:growth-source-check\]\]. If the correct growth rate is ≤10%, the target is not beaten and the bonus is **$0**.

2. **The boundary case matters.** The division is exactly at the 5 pp accelerated-tier boundary. The policy language says "more than 5 percentage points", so 5 pp exactly does not qualify for the $45,000 accelerated bonus — but this conclusion is sensitive to the precision of the growth figure \[\[diff:accelerated-tier-boundary-check\]\].

3. **Growth metric type is ambiguous.** The reported 15% is a year-over-year figure, while the baseline revenue data ($210M and $230M) appears to be sequential quarters. These measure different things and should not be compared directly \[\[diff:growth-metric-type-check\]\].

**Bottom line:** Subject to resolution of the growth rate discrepancy, the bonus is **$30,000** at the standard tier \[\[term:bonus-amount\]\] \[\[theorem:final-bonus-amount\]\].

---

## Resolved References

```text
[[diff:growth-source-check]]
  revenue-q3-growth (15.0) vs revenue-q3-growth-computed (0.095)
    beat-growth-target:        True → False
    growth-above-target-value: 5.0 → -9.90
    bonus-amount:              30000.0 → 0
    growth-above-target:       5.0 → -9.90

[[diff:growth-metric-type-check]]
  revenue-q3-growth (15.0) vs revenue-q3-sequential-growth-pct (9.52)
    beat-growth-target:        True → False
    growth-above-target-value: 5.0 → -0.48
    bonus-amount:              30000.0 → 0
    growth-above-target:       5.0 → -0.48

[[diff:bonus-arithmetic-check]]
  standard-bonus-amount (30000.0) vs standard-bonus-direct (30000.0) — no divergences

[[diff:accelerated-tier-boundary-check]]
  growth-above-target (5.0) vs growth-margin-above-target (5.0) — no divergences

[[fact:revenue-q3-yoy-growth]]          = 15.0
[[fact:growth-target]]                  = 10.0
[[fact:base-salary]]                    = 150000.0
[[fact:standard-bonus-rate]]            = 0.2
[[term:revenue-q3-sequential-growth-pct]] = 9.52
[[term:revenue-q3-growth-computed]]     = 0.095
[[term:growth-above-target]]           = 5.0
[[term:qualifies-accelerated-tier]]    = False
[[term:standard-bonus-amount]]         = 30000.0
[[term:bonus-amount]]                  = 30000.0
```

---

## Provenance: `beat-growth-target-check`

```json
{
  "name": "beat-growth-target-check",
  "type": "theorem",
  "wff": "(> revenue-q3-growth growth-target)",
  "origin": "derived",
  "derivation_chain": [
    {
      "name": "revenue-q3-growth",
      "type": "term",
      "definition": "revenue-q3-yoy-growth",
      "origin": {
        "document": "Q3 Report",
        "quotes": ["Q3 revenue was $15M, up 15% year-over-year"],
        "explanation": "Year-over-year growth percentage as stated in Q3 Report",
        "verified": true,
        "grounded": true,
        "verification": [
          {
            "quote": "Q3 revenue was $15M, up 15% year-over-year",
            "verified": true,
            "positions": {
              "original": { "start": 60, "end": 101 },
              "normalized": { "start": 57, "end": 95 }
            },
            "confidence": { "score": 0.969, "level": "high" },
            "transformations": [
              { "type": "case_normalization", "penalty": 0.01 },
              { "type": "punctuation_removal", "penalty": 0.02 },
              { "type": "whitespace_normalization", "penalty": 0.001 }
            ],
            "context": {
              "before": "Report\n\nSection 1: Revenue Performance\n\n",
              "after": ". This represents the strongest\nquarter"
            }
          }
        ]
      }
    },
    {
      "name": "growth-target",
      "type": "fact",
      "origin": {
        "document": "FY2024 Targets Memo",
        "quotes": ["Revenue growth target for FY2024: 10%"],
        "explanation": "Board-approved annual revenue growth target for FY2024",
        "verified": true,
        "grounded": true,
        "verification": [
          {
            "quote": "Revenue growth target for FY2024: 10%",
            "verified": true,
            "positions": {
              "original": { "start": 214, "end": 249 },
              "normalized": { "start": 200, "end": 234 }
            },
            "confidence": { "score": 0.968, "level": "high" },
            "transformations": [
              { "type": "case_normalization", "penalty": 0.01 },
              { "type": "punctuation_removal", "penalty": 0.02 },
              { "type": "whitespace_normalization", "penalty": 0.001 },
              { "type": "whitespace_trimming", "penalty": 0.001 }
            ],
            "context": {
              "before": "Growth Objectives\n\n2.1 Revenue Targets\n\n",
              "after": "%. This target was set based on\nmarket "
            }
          }
        ]
      }
    }
  ]
}
```

---

## Final System State

```text
System(4 axioms, 6 theorems, 12 terms, 10 facts, 4 diffs, 3 docs)

Facts:    revenue-q3, revenue-q3-yoy-growth, revenue-q2-baseline, revenue-q3-baseline,
          growth-target, accelerated-tier-threshold, base-salary, standard-bonus-rate,
          accelerated-bonus-rate, growth-target-from-memo

Terms:    revenue-q3-growth-computed, revenue-q3-growth, beat-growth-target,
          growth-above-target, qualifies-accelerated-tier, standard-bonus-amount,
          accelerated-bonus-amount, bonus-amount, growth-above-target-value,
          revenue-q3-sequential-growth-pct, growth-margin-above-target, standard-bonus-direct

Theorems: beat-growth-target-check, accelerated-tier-check, accelerated-tier-qualifies,
          accelerated-bonus-applies, standard-bonus-applies, final-bonus-amount

Diffs:    growth-source-check, growth-metric-type-check,
          accelerated-tier-boundary-check, bonus-arithmetic-check
```

### Consistency

```text
System inconsistent: 3 issue(s)

  No evidence provided: growth-above-target-value
  Potential fabrication: accelerated-tier-check

  growth-source-check:
    revenue-q3-growth (15.0) vs revenue-q3-growth-computed (0.095)
      beat-growth-target:        True → False
      growth-above-target-value: 5.0 → -9.90
      bonus-amount:              30000.0 → 0
      growth-above-target:       5.0 → -9.90

  growth-metric-type-check:
    revenue-q3-growth (15.0) vs revenue-q3-sequential-growth-pct (9.52)
      beat-growth-target:        True → False
      growth-above-target-value: 5.0 → -0.48
      bonus-amount:              30000.0 → 0
      growth-above-target:       5.0 → -0.48
```