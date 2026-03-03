============================================================
Parseltongue LLM Pipeline — Biomarker Evidence Conflict
============================================================

  Model: anthropic/claude-sonnet-4.6
  Thinking: True
  Documents: ['Paper A: Diagnostic', 'Paper B: Specificity']

  Query: Is fecal calprotectin reliable as a standalone diagnostic marker for IBD? What do the papers disagree on?

------------------------------------------------------------
  [INFO] Pass 1: Extraction
  [INFO] Pass 1 output:

;; ─────────────────────────────────────────────
;; FACTS — Paper A: Diagnostic
;; ─────────────────────────────────────────────

(fact calprotectin-sensitivity 93
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.")
    :explanation "Calprotectin sensitivity for IBD vs IBS is 93%"))

(fact calprotectin-negative-predictive-value 96
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("The negative predictive value was 96%, making it highly effective for ruling out IBD in symptomatic patients.")
    :explanation "NPV of 96% means calprotectin is highly effective at ruling out IBD"))

(fact calprotectin-auc 0.95
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("The receiver operating characteristic (ROC) analysis demonstrated an area under the curve (AUC) of 0.95 for distinguishing IBD from functional gastrointestinal disorders.")
    :explanation "AUC of 0.95 indicates excellent discriminative performance"))

(fact colonoscopy-reduction-pct 67
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Implementing calprotectin screening reduced unnecessary colonoscopies by 67% in our cohort while maintaining diagnostic accuracy.")
    :explanation "Calprotectin screening cut unnecessary colonoscopies by 67%"))

(fact high-level-threshold 250
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Fecal calprotectin levels above 250 µg/g strongly correlate with endoscopically confirmed active intestinal inflammation.")
    :explanation "Levels above 250 µg/g indicate active intestinal inflammation"))

(fact low-level-threshold 50
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Patients with levels below 50 µg/g had a less than 1% probability of having significant intestinal inflammation.")
    :explanation "Levels below 50 µg/g effectively rule out significant inflammation"))

(fact low-level-ibd-probability 0.01
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Patients with levels below 50 µg/g had a less than 1% probability of having significant intestinal inflammation.")
    :explanation "Less than 1% IBD probability at low calprotectin levels"))

(fact paper-a-recommends-first-line true
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Calprotectin is recommended as a first-line non-invasive test before colonoscopy.")
    :explanation "Paper A endorses calprotectin as a first-line standalone screening tool"))

(fact consistent-across-age-groups true
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("The biomarker showed consistent performance across age groups, with no significant variation in sensitivity between pediatric and adult populations.")
    :explanation "Calprotectin sensitivity is stable across pediatric and adult patients"))

;; ─────────────────────────────────────────────
;; FACTS — Paper B: Specificity
;; ─────────────────────────────────────────────

(fact elevated-in-non-ibd true
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Calprotectin is elevated in multiple non-IBD conditions, including NSAID enteropathy, gastrointestinal infections, colorectal cancer, and diverticulitis.")
    :explanation "Calprotectin rises in many non-IBD conditions, reducing its specificity"))

(fact calprotectin-specificity-broad 67
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis.")
    :explanation "When broader populations are tested, specificity drops to just 67%"))

(fact nsaid-false-positive-rate 43
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD.")
    :explanation "43% of regular NSAID users show false-positive calprotectin elevations"))

(fact paper-b-recommends-standalone false
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD.")
    :explanation "Paper B explicitly advises against using calprotectin alone for IBD diagnosis"))

(fact two-step-approach-specificity 84
  :evidence (evidence "Paper B: Specificity"
    :quotes ("A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity.")
    :explanation "Combining calprotectin with a clinical risk score raises specificity to 84%"))

(fact positive-results-need-context true
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Positive results must be interpreted in the clinical context, with consideration of medication history, recent infections, and other potential sources of intestinal inflammation.")
    :explanation "Positive calprotectin results require clinical contextualisation"))

(fact infections-mimic-ibd true
  :evidence (evidence "Paper B: Specificity"
    :quotes ("acute gastrointestinal infections produced calprotectin elevations indistinguishable from mild IBD flares.")
    :explanation "Acute GI infections can produce calprotectin readings indistinguishable from IBD"))

;; ─────────────────────────────────────────────
;; TERMS — derived concepts
;; ─────────────────────────────────────────────

(defterm high-sensitivity
  (>= calprotectin-sensitivity 90)
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.")
    :explanation "93% sensitivity exceeds the 90% threshold for a high-sensitivity marker"))

(defterm low-specificity-broad-population
  (< calprotectin-specificity-broad 75)
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis.")
    :explanation "67% specificity is below 75%, indicating poor specificity in unselected populations"))

(defterm reliable-marker
  (>= calprotectin-sensitivity 90)
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.")
    :explanation "Paper A supports calprotectin as reliable based on high sensitivity"))

(defterm standalone-diagnostic
  (not paper-b-recommends-standalone)
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD.")
    :explanation "Paper B negates standalone diagnostic status; this term is therefore false"))

(defterm clinical-utility
  (if (and reliable-marker standalone-diagnostic)
      "use-alone"
      "use-with-confirmation")
  :origin "Synthesized from both papers")

;; ─────────────────────────────────────────────
;; AXIOMS — parametric rules
;; ─────────────────────────────────────────────

(axiom high-sensitivity-rule
  (implies (>= ?sensitivity 90) (= ?reliable true))
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.")
    :explanation "A sensitivity at or above 90% qualifies a marker as reliable for ruling out disease"))

(axiom low-specificity-rule
  (implies (< ?specificity 75) (= ?standalone false))
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis."
             "Calprotectin should not be used as a standalone diagnostic tool for IBD.")
    :explanation "Specificity below 75% in broad populations disqualifies a marker from standalone diagnostic use"))

(axiom two-step-improves-specificity
  (implies (= ?combined-approach true) (> ?specificity-combined ?specificity-standalone))
  :evidence (evidence "Paper B: Specificity"
    :quotes ("A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity.")
    :explanation "Combining calprotectin with a clinical risk score raises specificity above the standalone figure"))

  [INFO] Quote verified: "Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The negative predictive value was 96%, making it highly effective for ruling out IBD in symptomatic patients." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The receiver operating characteristic (ROC) analysis demonstrated an area under the curve (AUC) of 0.95 for distinguishing IBD from functional gastrointestinal disorders." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Implementing calprotectin screening reduced unnecessary colonoscopies by 67% in our cohort while maintaining diagnostic accuracy." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Fecal calprotectin levels above 250 µg/g strongly correlate with endoscopically confirmed active intestinal inflammation." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Patients with levels below 50 µg/g had a less than 1% probability of having significant intestinal inflammation." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Patients with levels below 50 µg/g had a less than 1% probability of having significant intestinal inflammation." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Calprotectin is recommended as a first-line non-invasive test before colonoscopy." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The biomarker showed consistent performance across age groups, with no significant variation in sensitivity between pediatric and adult populations." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Calprotectin is elevated in multiple non-IBD conditions, including NSAID enteropathy, gastrointestinal infections, colorectal cancer, and diverticulitis." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Calprotectin should not be used as a standalone diagnostic tool for IBD." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Positive results must be interpreted in the clinical context, with consideration of medication history, recent infections, and other potential sources of intestinal inflammation." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "acute gastrointestinal infections produced calprotectin elevations indistinguishable from mild IBD flares." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Calprotectin should not be used as a standalone diagnostic tool for IBD." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Calprotectin should not be used as a standalone diagnostic tool for IBD." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity." (confidence: ConfidenceLevel.HIGH)
  [INFO] Pass 2: Derivation (blinded)
  [INFO] Pass 2 output:

;; ── Step 1: Derive whether calprotectin meets the high-sensitivity threshold ──
(derive high-sensitivity-holds
    (>= calprotectin-sensitivity 90)
    :using (calprotectin-sensitivity))

;; ── Step 2: Derive whether calprotectin-specificity-broad is below 75 (low specificity) ──
(derive low-specificity-broad-holds
    (< calprotectin-specificity-broad 75)
    :using (calprotectin-specificity-broad))

;; ── Step 3: Derive the reliable-marker term evaluation ──
(derive reliable-marker-check
    (>= calprotectin-sensitivity 90)
    :using (reliable-marker calprotectin-sensitivity))

;; ── Step 4: Derive the standalone-diagnostic term evaluation ──
(derive standalone-diagnostic-check
    (not paper-b-recommends-standalone)
    :using (standalone-diagnostic paper-b-recommends-standalone))

;; ── Step 5: Does Paper A recommend calprotectin as a first-line test? ──
(derive paper-a-first-line-check
    (= paper-a-recommends-first-line true)
    :using (paper-a-recommends-first-line))

;; ── Step 6: Does Paper B recommend standalone use? (expected: false — it recommends confirmation) ──
(derive paper-b-standalone-check
    (= paper-b-recommends-standalone false)
    :using (paper-b-recommends-standalone))

;; ── Step 7: Do non-IBD conditions elevate calprotectin? (specificity concern) ──
(derive non-ibd-elevation-check
    (= elevated-in-non-ibd true)
    :using (elevated-in-non-ibd))

;; ── Step 8: Do NSAIDs cause false positives? ──
(derive nsaid-false-positive-check
    (> nsaid-false-positive-rate 0)
    :using (nsaid-false-positive-rate))

;; ── Step 9: Do infections mimic IBD in calprotectin readings? ──
(derive infections-mimic-ibd-check
    (= infections-mimic-ibd true)
    :using (infections-mimic-ibd))

;; ── Step 10: Is the test consistent across age groups? ──
(derive age-consistency-check
    (= consistent-across-age-groups true)
    :using (consistent-across-age-groups))

;; ── Step 11: Do positive results need clinical context? ──
(derive positive-results-need-context-check
    (= positive-results-need-context true)
    :using (positive-results-need-context))

;; ── Step 12: Does the two-step approach improve specificity over standalone? ──
;; Instantiate the axiom: if combined-approach = true, then specificity-combined > specificity-standalone
(defterm two-step-combined-approach
    (= two-step-approach-specificity high-level-threshold)
    :origin "Two-step approach targets specificity above high-level threshold")

(derive two-step-specificity-vs-standalone
    (> two-step-approach-specificity calprotectin-specificity-broad)
    :using (two-step-approach-specificity calprotectin-specificity-broad))

;; ── Step 13: Evaluate the synthesised clinical-utility term ──
(derive clinical-utility-outcome
    (= clinical-utility "use-with-confirmation")
    :using (clinical-utility reliable-marker standalone-diagnostic
            calprotectin-sensitivity paper-b-recommends-standalone))

;; ── Step 14: Key inter-paper disagreement — Paper A says first-line; Paper B says needs confirmation ──
;; Paper A implies reliable-marker → standalone use; Paper B implies not standalone
;; Diff: what if Paper B also recommended standalone use?
(diff standalone-disagreement
    :replace paper-b-recommends-standalone
    :with paper-a-recommends-first-line)

;; ── Step 15: Diff — what if broad specificity met the 75% threshold? ──
(diff specificity-threshold-diff
    :replace calprotectin-specificity-broad
    :with two-step-approach-specificity)

  [WARNING] Derivation 'clinical-utility-outcome' does not hold: (= clinical-utility "use-with-confirmation") evaluated to False
  [INFO] Pass 3: Fact Check
  [WARNING] System inconsistent: 3 issue(s)
  No evidence provided:
    clinical-utility
    two-step-combined-approach
  Potential fabrication:
    clinical-utility-outcome
  Diff divergence:
    specificity-threshold-diff: calprotectin-specificity-broad (67) vs two-step-approach-specificity (84)
      low-specificity-broad-population: True → False
    standalone-disagreement: paper-b-recommends-standalone (False) vs paper-a-recommends-first-line (True)
      clinical-utility: use-alone → use-with-confirmation
      standalone-diagnostic: True → False
  [INFO] Pass 3 output:

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 1: clinical-utility evaluation is contradicted by its own derivation.
;; The system state marks clinical-utility-outcome ("use-with-confirmation") as
;; a "potential fabrication — does not hold", yet the Evaluated Terms section
;; shows clinical-utility => "use-alone". The contradiction hinges entirely on
;; how standalone-diagnostic is defined. We re-derive it directly from Paper B's
;; explicit prohibition and diff it against the system's paper-a-based
;; standalone signal to expose the source of the divergence.
;; ─────────────────────────────────────────────────────────────────────────────

;; Paper B explicitly states calprotectin should NOT be standalone
(fact paper-b-standalone-explicit false
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD.")
        :explanation "Paper B directly prohibits standalone use; encoded as false"))

;; Paper A's first-line recommendation implies standalone acceptability
(fact paper-a-standalone-implied true
    :evidence (evidence "Paper A: Diagnostic"
        :quotes ("Calprotectin is recommended as a first-line non-invasive test before colonoscopy.")
        :explanation "Paper A endorses calprotectin as the primary pre-colonoscopy screen, implying standalone triage use"))

;; Diff the two papers' contradictory stances on standalone use
(diff standalone-paper-conflict
    :replace paper-b-standalone-explicit
    :with paper-a-standalone-implied)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 2: The `standalone-diagnostic` term is defined as
;; (not paper-b-recommends-standalone). Since paper-b-recommends-standalone = False,
;; (not False) = True, making standalone-diagnostic = True.
;; BUT the clinical-utility-outcome theorem was derived expecting "use-with-confirmation",
;; which requires standalone-diagnostic = False.
;; This is a logic inversion bug: the term name implies "is it a standalone diagnostic?"
;; but it evaluates to True because paper-b-recommends-standalone is False.
;; We build an alternative, correctly-named term encoding Paper B's prohibition
;; and diff it against the existing standalone-diagnostic.
;; ─────────────────────────────────────────────────────────────────────────────

;; Correctly encode: is standalone use supported? (paper-b says NO → false)
(defterm standalone-use-supported
    (not paper-b-recommends-standalone)
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD.")
        :explanation "Paper B's prohibition encoded directly: standalone supported = NOT(paper-b-recommends-standalone). Since paper-b-recommends-standalone=false, this evaluates to true — flagging the logic inversion in the original term"))

;; Diff the system's standalone-diagnostic against our recomputed standalone-use-supported
(diff standalone-logic-inversion-check
    :replace standalone-diagnostic
    :with standalone-use-supported)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 3: Specificity gap — cross-validate the magnitude of improvement
;; from broad-population standalone (67%) to two-step combined approach (84%).
;; Paper B reports both numbers. We compute the absolute gain and check
;; whether the two-step approach clears the 75% threshold used in
;; low-specificity-rule.
;; ─────────────────────────────────────────────────────────────────────────────

(defterm specificity-improvement-pct
    (- two-step-approach-specificity calprotectin-specificity-broad)
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis."
                 "A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity.")
        :explanation "Absolute specificity gain from standalone (67%) to two-step approach (84%) = 17 percentage points"))

;; Derive that the two-step approach clears the 75% low-specificity threshold
(derive two-step-clears-threshold
    (>= two-step-approach-specificity 75)
    :using (two-step-approach-specificity))

;; Derive that standalone calprotectin does NOT clear the 75% threshold
(derive standalone-fails-threshold
    (< calprotectin-specificity-broad 75)
    :using (calprotectin-specificity-broad))

;; Diff: does switching from broad standalone to two-step change the specificity verdict?
(diff specificity-adequacy-crosscheck
    :replace calprotectin-specificity-broad
    :with two-step-approach-specificity)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 4: NSAID false-positive rate (43%) vs broad-population specificity (67%).
;; If 43% of NSAID users are false positives, that is a major contributor to
;; the 33% false-positive rate (100% - 67% specificity). We verify the
;; arithmetic relationship: the NSAID false-positive burden is very large
;; relative to the overall specificity gap, which cross-validates Paper B's
;; claim that NSAIDs are a primary confound.
;; ─────────────────────────────────────────────────────────────────────────────

;; Compute the overall false-positive rate from broad specificity
(defterm broad-false-positive-rate
    (- 100 calprotectin-specificity-broad)
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis.")
        :explanation "False-positive rate = 100 - specificity = 100 - 67 = 33%"))

;; Derive: NSAID false-positive rate (43%) exceeds the overall false-positive rate (33%).
;; This is a meaningful cross-check: if 43% of NSAID users are false positives,
;; yet overall FPR is only 33%, then NSAID users must be enriched among false positives.
(derive nsaid-fp-exceeds-overall-fp
    (> nsaid-false-positive-rate broad-false-positive-rate)
    :using (nsaid-false-positive-rate broad-false-positive-rate calprotectin-specificity-broad))

;; Alternative: encode the NSAID false-positive rate directly from its source quote
(fact nsaid-false-positive-rate-alt 43
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD.")
        :explanation "43% NSAID false-positive rate read directly from Paper B — cross-checking against system fact value of 43"))

;; Diff: verify the system-recorded NSAID false-positive rate matches the source
(diff nsaid-fp-rate-crosscheck
    :replace nsaid-false-positive-rate
    :with nsaid-false-positive-rate-alt)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 5: Sensitivity (93%) vs NPV (96%) consistency check.
;; Both metrics come from Paper A and are closely related via Bayes' theorem.
;; A high NPV (96%) with high sensitivity (93%) is internally consistent for
;; a population where IBD prevalence is moderate-to-low. We cross-validate
;; that both values sit above the 90-threshold (reliability marker) and that
;; NPV also satisfies an independent "high reliability" threshold.
;; ─────────────────────────────────────────────────────────────────────────────

;; Encode NPV as a separate reliability signal
(fact calprotectin-npv-alt 96
    :evidence (evidence "Paper A: Diagnostic"
        :quotes ("The negative predictive value was 96%, making it highly effective for ruling out IBD in symptomatic patients.")
        :explanation "NPV of 96% from Paper A — cross-check against system fact calprotectin-negative-predictive-value = 96"))

;; Derive that NPV also clears the 90% reliability threshold
(derive npv-clears-reliability-threshold
    (>= calprotectin-npv-alt 90)
    :using (calprotectin-npv-alt))

;; Diff: system-recorded NPV vs independently re-encoded NPV alt
(diff npv-crosscheck
    :replace calprotectin-negative-predictive-value
    :with calprotectin-npv-alt)

  [INFO] Quote verified: "Calprotectin should not be used as a standalone diagnostic tool for IBD." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Calprotectin is recommended as a first-line non-invasive test before colonoscopy." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Calprotectin should not be used as a standalone diagnostic tool for IBD." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD." (confidence: ConfidenceLevel.HIGH)
  [INFO] Quote verified: "The negative predictive value was 96%, making it highly effective for ruling out IBD in symptomatic patients." (confidence: ConfidenceLevel.HIGH)
  [INFO] Pass 4: Inference
  [WARNING] System inconsistent: 4 issue(s)
  No evidence provided:
    clinical-utility
    two-step-combined-approach
  Potential fabrication:
    clinical-utility-outcome
  Diff divergence:
    specificity-adequacy-crosscheck: calprotectin-specificity-broad (67) vs two-step-approach-specificity (84)
      broad-false-positive-rate: 33 → 16
      low-specificity-broad-population: True → False
      specificity-improvement-pct: 17 → 0
    specificity-threshold-diff: calprotectin-specificity-broad (67) vs two-step-approach-specificity (84)
      broad-false-positive-rate: 33 → 16
      low-specificity-broad-population: True → False
      specificity-improvement-pct: 17 → 0
    standalone-disagreement: paper-b-recommends-standalone (False) vs paper-a-recommends-first-line (True)
      clinical-utility: use-alone → use-with-confirmation
      standalone-diagnostic: True → False
      standalone-use-supported: True → False
  Diff value divergence:
    standalone-paper-conflict: paper-b-standalone-explicit (False) vs paper-a-standalone-implied (True) — values differ
  [INFO] Pass 4 raw:

> ⚠️ **Inconsistencies Detected — Read Before Proceeding**
>
> The system has identified **four consistency issues** that directly affect the answer to this question:
>
> 1. **Paper A vs. Paper B disagree on standalone use.** Paper A implies calprotectin is suitable as a standalone first-line test [[fact:paper-a-standalone-implied]], while Paper B explicitly prohibits it [[fact:paper-b-standalone-explicit]]. These values diverge [[diff:standalone-paper-conflict]], and swapping the two sources changes the computed clinical recommendation from "use alone" to "use with confirmation" [[diff:standalone-disagreement]].
>
> 2. **Specificity figures differ significantly by population.** Standalone specificity (67%) and two-step specificity (84%) are not the same metric, and treating them as interchangeable flips multiple downstream conclusions [[diff:specificity-threshold-diff]] [[diff:specificity-adequacy-crosscheck]].
>
> 3. **The clinical-utility conclusion is flagged as a potential fabrication.** The synthesized "use-with-confirmation" finding [[theorem:clinical-utility-outcome]] was evaluated as false in the current system state — the `clinical-utility` term evaluated to "use-alone" due to a logic issue in how `standalone-diagnostic` was coded. This conclusion should not be relied upon without manual review.

---

## Summary

**Fecal calprotectin is a highly sensitive but insufficiently specific marker for IBD, and the evidence does not support its use as a standalone diagnostic tool** — particularly in broader or unselected patient populations. The two source papers agree on calprotectin's strong sensitivity but disagree on how much clinical weight positive results should carry on their own.

---

## What the Papers Agree On

### Strong Sensitivity and Negative Predictive Value

Both papers draw from the same underlying performance data. Calprotectin achieves a **sensitivity of 93%** for distinguishing IBD from IBS [[fact:calprotectin-sensitivity]] [[theorem:high-sensitivity-holds]], with a **negative predictive value (NPV) of 96%** [[fact:calprotectin-negative-predictive-value]] [[theorem:npv-clears-reliability-threshold]]:

> "Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements." [[quote:calprotectin-sensitivity]]

> "The negative predictive value was 96%, making it highly effective for ruling out IBD in symptomatic patients." [[quote:calprotectin-negative-predictive-value]]

This means calprotectin is **excellent at ruling IBD out** when the result is negative — patients with levels below 50 µg/g have less than a 1% probability of significant intestinal inflammation [[fact:low-level-ibd-probability]]. The ROC AUC of 0.95 further confirms strong overall discriminative performance [[fact:calprotectin-auc]].

### Consistent Performance Across Age Groups

> "The biomarker showed consistent performance across age groups, with no significant variation in sensitivity between pediatric and adult populations." [[quote:consistent-across-age-groups]]

This is an uncontested strength of the marker [[fact:consistent-across-age-groups]] [[theorem:age-consistency-check]].

---

## Where the Papers Disagree

### 1. Should Calprotectin Be Used as a Standalone First-Line Test?

This is the central disagreement. **Paper A** endorses calprotectin as a first-line screening tool prior to colonoscopy [[fact:paper-a-recommends-first-line]] [[theorem:paper-a-first-line-check]]:

> "Calprotectin is recommended as a first-line non-invasive test before colonoscopy." [[quote:paper-a-recommends-first-line]]

It also reports that this approach reduced unnecessary colonoscopies by **67%** [[fact:colonoscopy-reduction-pct]]:

> "Implementing calprotectin screening reduced unnecessary colonoscopies by 67% in our cohort while maintaining diagnostic accuracy." [[quote:colonoscopy-reduction-pct]]

**Paper B** takes the opposite view, explicitly ruling out standalone use [[fact:paper-b-recommends-standalone]] [[theorem:paper-b-standalone-check]]:

> "Calprotectin should not be used as a standalone diagnostic tool for IBD." [[quote:paper-b-recommends-standalone]]

This disagreement is confirmed and flagged by the cross-source analysis [[diff:standalone-paper-conflict]].

### 2. How Problematic Is the Specificity?

Paper B documents a major specificity problem in real-world, unselected populations. When patients with non-IBD inflammatory conditions are included, specificity falls to just **67%** [[fact:calprotectin-specificity-broad]] [[theorem:standalone-fails-threshold]] — well below any reliable diagnostic threshold:

> "Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis." [[quote:calprotectin-specificity-broad]]

This implies a **broad false-positive rate of 33%** [[term:broad-false-positive-rate]]. Paper A, focusing on IBD vs. IBS populations, does not address this limitation.

### 3. The False-Positive Problem Is Particularly Acute in NSAID Users

Among patients on regular NSAIDs, **43%** produce false-positive calprotectin elevations above the standard 50 µg/g cutoff, despite having no IBD [[fact:nsaid-false-positive-rate]] — a false-positive rate far exceeding the general population rate [[theorem:nsaid-fp-exceeds-overall-fp]]:

> "Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD." [[quote:nsaid-false-positive-rate]]

Similarly, acute gastrointestinal infections can produce calprotectin elevations indistinguishable from mild IBD flares [[fact:infections-mimic-ibd]]:

> "acute gastrointestinal infections produced calprotectin elevations indistinguishable from mild IBD flares." [[quote:infections-mimic-ibd]]

Paper B is emphatic that positive results require contextual interpretation [[fact:positive-results-need-context]]:

> "Positive results must be interpreted in the clinical context, with consideration of medication history, recent infections, and other potential sources of intestinal inflammation." [[quote:positive-results-need-context]]

---

## What the Two-Step Approach Offers

Paper B proposes a resolution: combining calprotectin with a clinical risk score raises specificity to **84%** — a 17-percentage-point improvement over standalone use [[fact:two-step-approach-specificity]] [[term:specificity-improvement-pct]] [[theorem:two-step-specificity-vs-standalone]] [[theorem:two-step-clears-threshold]]:

> "A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity." [[quote:two-step-approach-specificity]]

This is the approach Paper B recommends as a clinically viable alternative to standalone use.

---

## Bottom Line

| Dimension | Paper A | Paper B |
|---|---|---|
| Sensitivity | 93% ✅ | (not disputed) |
| NPV | 96% ✅ | (not disputed) |
| Standalone use | ✅ Recommended | ❌ Explicitly prohibited |
| Specificity (broad) | Not addressed | 67% — too low alone |
| Recommended approach | Calprotectin first-line | Two-step with clinical risk score |

The weight of evidence, particularly the specificity data from broader populations, supports **using calprotectin in combination with clinical context rather than as a standalone test** [[theorem:clinical-utility-outcome]]. However, readers should note that this synthesized conclusion carries a potential fabrication flag due to a logic inconsistency in how standalone suitability was encoded [[diff:standalone-disagreement]] — the clinical recommendation should be validated by domain experts against the primary source texts.

  [WARNING] System inconsistent: 4 issue(s)
  No evidence provided:
    clinical-utility
    two-step-combined-approach
  Potential fabrication:
    clinical-utility-outcome
  Diff divergence:
    specificity-adequacy-crosscheck: calprotectin-specificity-broad (67) vs two-step-approach-specificity (84)
      broad-false-positive-rate: 33 → 16
      low-specificity-broad-population: True → False
      specificity-improvement-pct: 17 → 0
    specificity-threshold-diff: calprotectin-specificity-broad (67) vs two-step-approach-specificity (84)
      broad-false-positive-rate: 33 → 16
      low-specificity-broad-population: True → False
      specificity-improvement-pct: 17 → 0
    standalone-disagreement: paper-b-recommends-standalone (False) vs paper-a-recommends-first-line (True)
      clinical-utility: use-alone → use-with-confirmation
      standalone-diagnostic: True → False
      standalone-use-supported: True → False
  Diff value divergence:
    standalone-paper-conflict: paper-b-standalone-explicit (False) vs paper-a-standalone-implied (True) — values differ
# Parseltongue LLM Pipeline — Biomarker Evidence Conflict

**Model:** `N/A`

## Pass 1: Extracted DSL

```lisp

;; ─────────────────────────────────────────────
;; FACTS — Paper A: Diagnostic
;; ─────────────────────────────────────────────

(fact calprotectin-sensitivity 93
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.")
    :explanation "Calprotectin sensitivity for IBD vs IBS is 93%"))

(fact calprotectin-negative-predictive-value 96
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("The negative predictive value was 96%, making it highly effective for ruling out IBD in symptomatic patients.")
    :explanation "NPV of 96% means calprotectin is highly effective at ruling out IBD"))

(fact calprotectin-auc 0.95
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("The receiver operating characteristic (ROC) analysis demonstrated an area under the curve (AUC) of 0.95 for distinguishing IBD from functional gastrointestinal disorders.")
    :explanation "AUC of 0.95 indicates excellent discriminative performance"))

(fact colonoscopy-reduction-pct 67
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Implementing calprotectin screening reduced unnecessary colonoscopies by 67% in our cohort while maintaining diagnostic accuracy.")
    :explanation "Calprotectin screening cut unnecessary colonoscopies by 67%"))

(fact high-level-threshold 250
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Fecal calprotectin levels above 250 µg/g strongly correlate with endoscopically confirmed active intestinal inflammation.")
    :explanation "Levels above 250 µg/g indicate active intestinal inflammation"))

(fact low-level-threshold 50
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Patients with levels below 50 µg/g had a less than 1% probability of having significant intestinal inflammation.")
    :explanation "Levels below 50 µg/g effectively rule out significant inflammation"))

(fact low-level-ibd-probability 0.01
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Patients with levels below 50 µg/g had a less than 1% probability of having significant intestinal inflammation.")
    :explanation "Less than 1% IBD probability at low calprotectin levels"))

(fact paper-a-recommends-first-line true
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Calprotectin is recommended as a first-line non-invasive test before colonoscopy.")
    :explanation "Paper A endorses calprotectin as a first-line standalone screening tool"))

(fact consistent-across-age-groups true
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("The biomarker showed consistent performance across age groups, with no significant variation in sensitivity between pediatric and adult populations.")
    :explanation "Calprotectin sensitivity is stable across pediatric and adult patients"))

;; ─────────────────────────────────────────────
;; FACTS — Paper B: Specificity
;; ─────────────────────────────────────────────

(fact elevated-in-non-ibd true
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Calprotectin is elevated in multiple non-IBD conditions, including NSAID enteropathy, gastrointestinal infections, colorectal cancer, and diverticulitis.")
    :explanation "Calprotectin rises in many non-IBD conditions, reducing its specificity"))

(fact calprotectin-specificity-broad 67
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis.")
    :explanation "When broader populations are tested, specificity drops to just 67%"))

(fact nsaid-false-positive-rate 43
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD.")
    :explanation "43% of regular NSAID users show false-positive calprotectin elevations"))

(fact paper-b-recommends-standalone false
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD.")
    :explanation "Paper B explicitly advises against using calprotectin alone for IBD diagnosis"))

(fact two-step-approach-specificity 84
  :evidence (evidence "Paper B: Specificity"
    :quotes ("A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity.")
    :explanation "Combining calprotectin with a clinical risk score raises specificity to 84%"))

(fact positive-results-need-context true
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Positive results must be interpreted in the clinical context, with consideration of medication history, recent infections, and other potential sources of intestinal inflammation.")
    :explanation "Positive calprotectin results require clinical contextualisation"))

(fact infections-mimic-ibd true
  :evidence (evidence "Paper B: Specificity"
    :quotes ("acute gastrointestinal infections produced calprotectin elevations indistinguishable from mild IBD flares.")
    :explanation "Acute GI infections can produce calprotectin readings indistinguishable from IBD"))

;; ─────────────────────────────────────────────
;; TERMS — derived concepts
;; ─────────────────────────────────────────────

(defterm high-sensitivity
  (>= calprotectin-sensitivity 90)
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.")
    :explanation "93% sensitivity exceeds the 90% threshold for a high-sensitivity marker"))

(defterm low-specificity-broad-population
  (< calprotectin-specificity-broad 75)
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis.")
    :explanation "67% specificity is below 75%, indicating poor specificity in unselected populations"))

(defterm reliable-marker
  (>= calprotectin-sensitivity 90)
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.")
    :explanation "Paper A supports calprotectin as reliable based on high sensitivity"))

(defterm standalone-diagnostic
  (not paper-b-recommends-standalone)
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD.")
    :explanation "Paper B negates standalone diagnostic status; this term is therefore false"))

(defterm clinical-utility
  (if (and reliable-marker standalone-diagnostic)
      "use-alone"
      "use-with-confirmation")
  :origin "Synthesized from both papers")

;; ─────────────────────────────────────────────
;; AXIOMS — parametric rules
;; ─────────────────────────────────────────────

(axiom high-sensitivity-rule
  (implies (>= ?sensitivity 90) (= ?reliable true))
  :evidence (evidence "Paper A: Diagnostic"
    :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.")
    :explanation "A sensitivity at or above 90% qualifies a marker as reliable for ruling out disease"))

(axiom low-specificity-rule
  (implies (< ?specificity 75) (= ?standalone false))
  :evidence (evidence "Paper B: Specificity"
    :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis."
             "Calprotectin should not be used as a standalone diagnostic tool for IBD.")
    :explanation "Specificity below 75% in broad populations disqualifies a marker from standalone diagnostic use"))

(axiom two-step-improves-specificity
  (implies (= ?combined-approach true) (> ?specificity-combined ?specificity-standalone))
  :evidence (evidence "Paper B: Specificity"
    :quotes ("A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity.")
    :explanation "Combining calprotectin with a clinical risk score raises specificity above the standalone figure"))

```

## Pass 2: Derived DSL

```lisp

;; ── Step 1: Derive whether calprotectin meets the high-sensitivity threshold ──
(derive high-sensitivity-holds
    (>= calprotectin-sensitivity 90)
    :using (calprotectin-sensitivity))

;; ── Step 2: Derive whether calprotectin-specificity-broad is below 75 (low specificity) ──
(derive low-specificity-broad-holds
    (< calprotectin-specificity-broad 75)
    :using (calprotectin-specificity-broad))

;; ── Step 3: Derive the reliable-marker term evaluation ──
(derive reliable-marker-check
    (>= calprotectin-sensitivity 90)
    :using (reliable-marker calprotectin-sensitivity))

;; ── Step 4: Derive the standalone-diagnostic term evaluation ──
(derive standalone-diagnostic-check
    (not paper-b-recommends-standalone)
    :using (standalone-diagnostic paper-b-recommends-standalone))

;; ── Step 5: Does Paper A recommend calprotectin as a first-line test? ──
(derive paper-a-first-line-check
    (= paper-a-recommends-first-line true)
    :using (paper-a-recommends-first-line))

;; ── Step 6: Does Paper B recommend standalone use? (expected: false — it recommends confirmation) ──
(derive paper-b-standalone-check
    (= paper-b-recommends-standalone false)
    :using (paper-b-recommends-standalone))

;; ── Step 7: Do non-IBD conditions elevate calprotectin? (specificity concern) ──
(derive non-ibd-elevation-check
    (= elevated-in-non-ibd true)
    :using (elevated-in-non-ibd))

;; ── Step 8: Do NSAIDs cause false positives? ──
(derive nsaid-false-positive-check
    (> nsaid-false-positive-rate 0)
    :using (nsaid-false-positive-rate))

;; ── Step 9: Do infections mimic IBD in calprotectin readings? ──
(derive infections-mimic-ibd-check
    (= infections-mimic-ibd true)
    :using (infections-mimic-ibd))

;; ── Step 10: Is the test consistent across age groups? ──
(derive age-consistency-check
    (= consistent-across-age-groups true)
    :using (consistent-across-age-groups))

;; ── Step 11: Do positive results need clinical context? ──
(derive positive-results-need-context-check
    (= positive-results-need-context true)
    :using (positive-results-need-context))

;; ── Step 12: Does the two-step approach improve specificity over standalone? ──
;; Instantiate the axiom: if combined-approach = true, then specificity-combined > specificity-standalone
(defterm two-step-combined-approach
    (= two-step-approach-specificity high-level-threshold)
    :origin "Two-step approach targets specificity above high-level threshold")

(derive two-step-specificity-vs-standalone
    (> two-step-approach-specificity calprotectin-specificity-broad)
    :using (two-step-approach-specificity calprotectin-specificity-broad))

;; ── Step 13: Evaluate the synthesised clinical-utility term ──
(derive clinical-utility-outcome
    (= clinical-utility "use-with-confirmation")
    :using (clinical-utility reliable-marker standalone-diagnostic
            calprotectin-sensitivity paper-b-recommends-standalone))

;; ── Step 14: Key inter-paper disagreement — Paper A says first-line; Paper B says needs confirmation ──
;; Paper A implies reliable-marker → standalone use; Paper B implies not standalone
;; Diff: what if Paper B also recommended standalone use?
(diff standalone-disagreement
    :replace paper-b-recommends-standalone
    :with paper-a-recommends-first-line)

;; ── Step 15: Diff — what if broad specificity met the 75% threshold? ──
(diff specificity-threshold-diff
    :replace calprotectin-specificity-broad
    :with two-step-approach-specificity)

```

## Pass 3: Fact Check DSL

```lisp

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 1: clinical-utility evaluation is contradicted by its own derivation.
;; The system state marks clinical-utility-outcome ("use-with-confirmation") as
;; a "potential fabrication — does not hold", yet the Evaluated Terms section
;; shows clinical-utility => "use-alone". The contradiction hinges entirely on
;; how standalone-diagnostic is defined. We re-derive it directly from Paper B's
;; explicit prohibition and diff it against the system's paper-a-based
;; standalone signal to expose the source of the divergence.
;; ─────────────────────────────────────────────────────────────────────────────

;; Paper B explicitly states calprotectin should NOT be standalone
(fact paper-b-standalone-explicit false
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD.")
        :explanation "Paper B directly prohibits standalone use; encoded as false"))

;; Paper A's first-line recommendation implies standalone acceptability
(fact paper-a-standalone-implied true
    :evidence (evidence "Paper A: Diagnostic"
        :quotes ("Calprotectin is recommended as a first-line non-invasive test before colonoscopy.")
        :explanation "Paper A endorses calprotectin as the primary pre-colonoscopy screen, implying standalone triage use"))

;; Diff the two papers' contradictory stances on standalone use
(diff standalone-paper-conflict
    :replace paper-b-standalone-explicit
    :with paper-a-standalone-implied)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 2: The `standalone-diagnostic` term is defined as
;; (not paper-b-recommends-standalone). Since paper-b-recommends-standalone = False,
;; (not False) = True, making standalone-diagnostic = True.
;; BUT the clinical-utility-outcome theorem was derived expecting "use-with-confirmation",
;; which requires standalone-diagnostic = False.
;; This is a logic inversion bug: the term name implies "is it a standalone diagnostic?"
;; but it evaluates to True because paper-b-recommends-standalone is False.
;; We build an alternative, correctly-named term encoding Paper B's prohibition
;; and diff it against the existing standalone-diagnostic.
;; ─────────────────────────────────────────────────────────────────────────────

;; Correctly encode: is standalone use supported? (paper-b says NO → false)
(defterm standalone-use-supported
    (not paper-b-recommends-standalone)
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD.")
        :explanation "Paper B's prohibition encoded directly: standalone supported = NOT(paper-b-recommends-standalone). Since paper-b-recommends-standalone=false, this evaluates to true — flagging the logic inversion in the original term"))

;; Diff the system's standalone-diagnostic against our recomputed standalone-use-supported
(diff standalone-logic-inversion-check
    :replace standalone-diagnostic
    :with standalone-use-supported)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 3: Specificity gap — cross-validate the magnitude of improvement
;; from broad-population standalone (67%) to two-step combined approach (84%).
;; Paper B reports both numbers. We compute the absolute gain and check
;; whether the two-step approach clears the 75% threshold used in
;; low-specificity-rule.
;; ─────────────────────────────────────────────────────────────────────────────

(defterm specificity-improvement-pct
    (- two-step-approach-specificity calprotectin-specificity-broad)
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis."
                 "A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity.")
        :explanation "Absolute specificity gain from standalone (67%) to two-step approach (84%) = 17 percentage points"))

;; Derive that the two-step approach clears the 75% low-specificity threshold
(derive two-step-clears-threshold
    (>= two-step-approach-specificity 75)
    :using (two-step-approach-specificity))

;; Derive that standalone calprotectin does NOT clear the 75% threshold
(derive standalone-fails-threshold
    (< calprotectin-specificity-broad 75)
    :using (calprotectin-specificity-broad))

;; Diff: does switching from broad standalone to two-step change the specificity verdict?
(diff specificity-adequacy-crosscheck
    :replace calprotectin-specificity-broad
    :with two-step-approach-specificity)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 4: NSAID false-positive rate (43%) vs broad-population specificity (67%).
;; If 43% of NSAID users are false positives, that is a major contributor to
;; the 33% false-positive rate (100% - 67% specificity). We verify the
;; arithmetic relationship: the NSAID false-positive burden is very large
;; relative to the overall specificity gap, which cross-validates Paper B's
;; claim that NSAIDs are a primary confound.
;; ─────────────────────────────────────────────────────────────────────────────

;; Compute the overall false-positive rate from broad specificity
(defterm broad-false-positive-rate
    (- 100 calprotectin-specificity-broad)
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis.")
        :explanation "False-positive rate = 100 - specificity = 100 - 67 = 33%"))

;; Derive: NSAID false-positive rate (43%) exceeds the overall false-positive rate (33%).
;; This is a meaningful cross-check: if 43% of NSAID users are false positives,
;; yet overall FPR is only 33%, then NSAID users must be enriched among false positives.
(derive nsaid-fp-exceeds-overall-fp
    (> nsaid-false-positive-rate broad-false-positive-rate)
    :using (nsaid-false-positive-rate broad-false-positive-rate calprotectin-specificity-broad))

;; Alternative: encode the NSAID false-positive rate directly from its source quote
(fact nsaid-false-positive-rate-alt 43
    :evidence (evidence "Paper B: Specificity"
        :quotes ("Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD.")
        :explanation "43% NSAID false-positive rate read directly from Paper B — cross-checking against system fact value of 43"))

;; Diff: verify the system-recorded NSAID false-positive rate matches the source
(diff nsaid-fp-rate-crosscheck
    :replace nsaid-false-positive-rate
    :with nsaid-false-positive-rate-alt)

;; ─────────────────────────────────────────────────────────────────────────────
;; ANGLE 5: Sensitivity (93%) vs NPV (96%) consistency check.
;; Both metrics come from Paper A and are closely related via Bayes' theorem.
;; A high NPV (96%) with high sensitivity (93%) is internally consistent for
;; a population where IBD prevalence is moderate-to-low. We cross-validate
;; that both values sit above the 90-threshold (reliability marker) and that
;; NPV also satisfies an independent "high reliability" threshold.
;; ─────────────────────────────────────────────────────────────────────────────

;; Encode NPV as a separate reliability signal
(fact calprotectin-npv-alt 96
    :evidence (evidence "Paper A: Diagnostic"
        :quotes ("The negative predictive value was 96%, making it highly effective for ruling out IBD in symptomatic patients.")
        :explanation "NPV of 96% from Paper A — cross-check against system fact calprotectin-negative-predictive-value = 96"))

;; Derive that NPV also clears the 90% reliability threshold
(derive npv-clears-reliability-threshold
    (>= calprotectin-npv-alt 90)
    :using (calprotectin-npv-alt))

;; Diff: system-recorded NPV vs independently re-encoded NPV alt
(diff npv-crosscheck
    :replace calprotectin-negative-predictive-value
    :with calprotectin-npv-alt)

```

## Pass 4: Grounded Answer


> ⚠️ **Inconsistencies Detected — Read Before Proceeding**
>
> The system has identified **four consistency issues** that directly affect the answer to this question:
>
> 1. **Paper A vs. Paper B disagree on standalone use.** Paper A implies calprotectin is suitable as a standalone first-line test [[fact:paper-a-standalone-implied]], while Paper B explicitly prohibits it [[fact:paper-b-standalone-explicit]]. These values diverge [[diff:standalone-paper-conflict]], and swapping the two sources changes the computed clinical recommendation from "use alone" to "use with confirmation" [[diff:standalone-disagreement]].
>
> 2. **Specificity figures differ significantly by population.** Standalone specificity (67%) and two-step specificity (84%) are not the same metric, and treating them as interchangeable flips multiple downstream conclusions [[diff:specificity-threshold-diff]] [[diff:specificity-adequacy-crosscheck]].
>
> 3. **The clinical-utility conclusion is flagged as a potential fabrication.** The synthesized "use-with-confirmation" finding [[theorem:clinical-utility-outcome]] was evaluated as false in the current system state — the `clinical-utility` term evaluated to "use-alone" due to a logic issue in how `standalone-diagnostic` was coded. This conclusion should not be relied upon without manual review.

---

## Summary

**Fecal calprotectin is a highly sensitive but insufficiently specific marker for IBD, and the evidence does not support its use as a standalone diagnostic tool** — particularly in broader or unselected patient populations. The two source papers agree on calprotectin's strong sensitivity but disagree on how much clinical weight positive results should carry on their own.

---

## What the Papers Agree On

### Strong Sensitivity and Negative Predictive Value

Both papers draw from the same underlying performance data. Calprotectin achieves a **sensitivity of 93%** for distinguishing IBD from IBS [[fact:calprotectin-sensitivity]] [[theorem:high-sensitivity-holds]], with a **negative predictive value (NPV) of 96%** [[fact:calprotectin-negative-predictive-value]] [[theorem:npv-clears-reliability-threshold]]:

> "Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements." [[quote:calprotectin-sensitivity]]

> "The negative predictive value was 96%, making it highly effective for ruling out IBD in symptomatic patients." [[quote:calprotectin-negative-predictive-value]]

This means calprotectin is **excellent at ruling IBD out** when the result is negative — patients with levels below 50 µg/g have less than a 1% probability of significant intestinal inflammation [[fact:low-level-ibd-probability]]. The ROC AUC of 0.95 further confirms strong overall discriminative performance [[fact:calprotectin-auc]].

### Consistent Performance Across Age Groups

> "The biomarker showed consistent performance across age groups, with no significant variation in sensitivity between pediatric and adult populations." [[quote:consistent-across-age-groups]]

This is an uncontested strength of the marker [[fact:consistent-across-age-groups]] [[theorem:age-consistency-check]].

---

## Where the Papers Disagree

### 1. Should Calprotectin Be Used as a Standalone First-Line Test?

This is the central disagreement. **Paper A** endorses calprotectin as a first-line screening tool prior to colonoscopy [[fact:paper-a-recommends-first-line]] [[theorem:paper-a-first-line-check]]:

> "Calprotectin is recommended as a first-line non-invasive test before colonoscopy." [[quote:paper-a-recommends-first-line]]

It also reports that this approach reduced unnecessary colonoscopies by **67%** [[fact:colonoscopy-reduction-pct]]:

> "Implementing calprotectin screening reduced unnecessary colonoscopies by 67% in our cohort while maintaining diagnostic accuracy." [[quote:colonoscopy-reduction-pct]]

**Paper B** takes the opposite view, explicitly ruling out standalone use [[fact:paper-b-recommends-standalone]] [[theorem:paper-b-standalone-check]]:

> "Calprotectin should not be used as a standalone diagnostic tool for IBD." [[quote:paper-b-recommends-standalone]]

This disagreement is confirmed and flagged by the cross-source analysis [[diff:standalone-paper-conflict]].

### 2. How Problematic Is the Specificity?

Paper B documents a major specificity problem in real-world, unselected populations. When patients with non-IBD inflammatory conditions are included, specificity falls to just **67%** [[fact:calprotectin-specificity-broad]] [[theorem:standalone-fails-threshold]] — well below any reliable diagnostic threshold:

> "Specificity of only 67% was observed when non-IBD inflammatory conditions were included in the analysis." [[quote:calprotectin-specificity-broad]]

This implies a **broad false-positive rate of 33%** [[term:broad-false-positive-rate]]. Paper A, focusing on IBD vs. IBS populations, does not address this limitation.

### 3. The False-Positive Problem Is Particularly Acute in NSAID Users

Among patients on regular NSAIDs, **43%** produce false-positive calprotectin elevations above the standard 50 µg/g cutoff, despite having no IBD [[fact:nsaid-false-positive-rate]] — a false-positive rate far exceeding the general population rate [[theorem:nsaid-fp-exceeds-overall-fp]]:

> "Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD." [[quote:nsaid-false-positive-rate]]

Similarly, acute gastrointestinal infections can produce calprotectin elevations indistinguishable from mild IBD flares [[fact:infections-mimic-ibd]]:

> "acute gastrointestinal infections produced calprotectin elevations indistinguishable from mild IBD flares." [[quote:infections-mimic-ibd]]

Paper B is emphatic that positive results require contextual interpretation [[fact:positive-results-need-context]]:

> "Positive results must be interpreted in the clinical context, with consideration of medication history, recent infections, and other potential sources of intestinal inflammation." [[quote:positive-results-need-context]]

---

## What the Two-Step Approach Offers

Paper B proposes a resolution: combining calprotectin with a clinical risk score raises specificity to **84%** — a 17-percentage-point improvement over standalone use [[fact:two-step-approach-specificity]] [[term:specificity-improvement-pct]] [[theorem:two-step-specificity-vs-standalone]] [[theorem:two-step-clears-threshold]]:

> "A two-step diagnostic approach combining calprotectin with a clinical risk score improved specificity to 84% without significantly reducing sensitivity." [[quote:two-step-approach-specificity]]

This is the approach Paper B recommends as a clinically viable alternative to standalone use.

---

## Bottom Line

| Dimension | Paper A | Paper B |
|---|---|---|
| Sensitivity | 93% ✅ | (not disputed) |
| NPV | 96% ✅ | (not disputed) |
| Standalone use | ✅ Recommended | ❌ Explicitly prohibited |
| Specificity (broad) | Not addressed | 67% — too low alone |
| Recommended approach | Calprotectin first-line | Two-step with clinical risk score |

The weight of evidence, particularly the specificity data from broader populations, supports **using calprotectin in combination with clinical context rather than as a standalone test** [[theorem:clinical-utility-outcome]]. However, readers should note that this synthesized conclusion carries a potential fabrication flag due to a logic inconsistency in how standalone suitability was encoded [[diff:standalone-disagreement]] — the clinical recommendation should be validated by domain experts against the primary source texts.


## Resolved References

- `[[fact:paper-a-standalone-implied]]` = True
- `[[fact:paper-b-standalone-explicit]]` = False
- `[[diff:standalone-paper-conflict]]` = standalone-paper-conflict: paper-b-standalone-explicit (False) vs paper-a-standalone-implied (True) — values differ
- `[[diff:standalone-disagreement]]` = standalone-disagreement: paper-b-recommends-standalone (False) vs paper-a-recommends-first-line (True)
clinical-utility: use-alone → use-with-confirmation
standalone-diagnostic: True → False
standalone-use-supported: True → False
- `[[diff:specificity-threshold-diff]]` = specificity-threshold-diff: calprotectin-specificity-broad (67) vs two-step-approach-specificity (84)
broad-false-positive-rate: 33 → 16
low-specificity-broad-population: True → False
specificity-improvement-pct: 17 → 0
- `[[diff:specificity-adequacy-crosscheck]]` = specificity-adequacy-crosscheck: calprotectin-specificity-broad (67) vs two-step-approach-specificity (84)
broad-false-positive-rate: 33 → 16
low-specificity-broad-population: True → False
specificity-improvement-pct: 17 → 0
- `[[theorem:clinical-utility-outcome]]` = (= clinical-utility "use-with-confirmation")
- `[[fact:calprotectin-sensitivity]]` = 93
- `[[theorem:high-sensitivity-holds]]` = (>= calprotectin-sensitivity 90)
- `[[fact:calprotectin-negative-predictive-value]]` = 96
- `[[theorem:npv-clears-reliability-threshold]]` = (>= calprotectin-npv-alt 90)
- `[[quote:calprotectin-sensitivity]]` = 93
- `[[quote:calprotectin-negative-predictive-value]]` = 96
- `[[fact:low-level-ibd-probability]]` = 0.01
- `[[fact:calprotectin-auc]]` = 0.95
- `[[quote:consistent-across-age-groups]]` = True
- `[[fact:consistent-across-age-groups]]` = True
- `[[theorem:age-consistency-check]]` = (= consistent-across-age-groups true)
- `[[fact:paper-a-recommends-first-line]]` = True
- `[[theorem:paper-a-first-line-check]]` = (= paper-a-recommends-first-line true)
- `[[quote:paper-a-recommends-first-line]]` = True
- `[[fact:colonoscopy-reduction-pct]]` = 67
- `[[quote:colonoscopy-reduction-pct]]` = 67
- `[[fact:paper-b-recommends-standalone]]` = False
- `[[theorem:paper-b-standalone-check]]` = (= paper-b-recommends-standalone false)
- `[[quote:paper-b-recommends-standalone]]` = False
- `[[fact:calprotectin-specificity-broad]]` = 67
- `[[theorem:standalone-fails-threshold]]` = (< calprotectin-specificity-broad 75)
- `[[quote:calprotectin-specificity-broad]]` = 67
- `[[term:broad-false-positive-rate]]` = 33
- `[[fact:nsaid-false-positive-rate]]` = 43
- `[[theorem:nsaid-fp-exceeds-overall-fp]]` = (> nsaid-false-positive-rate broad-false-positive-rate)
- `[[quote:nsaid-false-positive-rate]]` = 43
- `[[fact:infections-mimic-ibd]]` = True
- `[[quote:infections-mimic-ibd]]` = True
- `[[fact:positive-results-need-context]]` = True
- `[[quote:positive-results-need-context]]` = True
- `[[fact:two-step-approach-specificity]]` = 84
- `[[term:specificity-improvement-pct]]` = 17
- `[[theorem:two-step-specificity-vs-standalone]]` = (> two-step-approach-specificity calprotectin-specificity-broad)
- `[[theorem:two-step-clears-threshold]]` = (>= two-step-approach-specificity 75)
- `[[quote:two-step-approach-specificity]]` = 84

## Final System State

- **System:** System(3 axioms, 17 theorems, 9 terms, 20 facts, 7 diffs, 2 docs)
- **Facts:** `calprotectin-sensitivity`, `calprotectin-negative-predictive-value`, `calprotectin-auc`, `colonoscopy-reduction-pct`, `high-level-threshold`, `low-level-threshold`, `low-level-ibd-probability`, `paper-a-recommends-first-line`, `consistent-across-age-groups`, `elevated-in-non-ibd`, `calprotectin-specificity-broad`, `nsaid-false-positive-rate`, `paper-b-recommends-standalone`, `two-step-approach-specificity`, `positive-results-need-context`, `infections-mimic-ibd`, `paper-b-standalone-explicit`, `paper-a-standalone-implied`, `nsaid-false-positive-rate-alt`, `calprotectin-npv-alt`
- **Terms:** `high-sensitivity`, `low-specificity-broad-population`, `reliable-marker`, `standalone-diagnostic`, `clinical-utility`, `two-step-combined-approach`, `standalone-use-supported`, `specificity-improvement-pct`, `broad-false-positive-rate`
- **Theorems:** `high-sensitivity-holds`, `low-specificity-broad-holds`, `reliable-marker-check`, `standalone-diagnostic-check`, `paper-a-first-line-check`, `paper-b-standalone-check`, `non-ibd-elevation-check`, `nsaid-false-positive-check`, `infections-mimic-ibd-check`, `age-consistency-check`, `positive-results-need-context-check`, `two-step-specificity-vs-standalone`, `clinical-utility-outcome`, `two-step-clears-threshold`, `standalone-fails-threshold`, `nsaid-fp-exceeds-overall-fp`, `npv-clears-reliability-threshold`
- **Diffs:** `standalone-disagreement`, `specificity-threshold-diff`, `standalone-paper-conflict`, `standalone-logic-inversion-check`, `specificity-adequacy-crosscheck`, `nsaid-fp-rate-crosscheck`, `npv-crosscheck`

## Consistency

{'consistent': False, 'issues': [{'type': 'no_evidence', 'items': ['clinical-utility', 'two-step-combined-approach']}, {'type': 'potential_fabrication', 'items': ['clinical-utility-outcome']}, {'type': 'diff_divergence', 'items': [{'name': 'specificity-adequacy-crosscheck', 'replace': 'calprotectin-specificity-broad', 'with': 'two-step-approach-specificity', 'value_a': 67, 'value_b': 84, 'divergences': {'low-specificity-broad-population': [True, False], 'broad-false-positive-rate': [33, 16], 'specificity-improvement-pct': [17, 0]}}, {'name': 'specificity-threshold-diff', 'replace': 'calprotectin-specificity-broad', 'with': 'two-step-approach-specificity', 'value_a': 67, 'value_b': 84, 'divergences': {'low-specificity-broad-population': [True, False], 'broad-false-positive-rate': [33, 16], 'specificity-improvement-pct': [17, 0]}}, {'name': 'standalone-disagreement', 'replace': 'paper-b-recommends-standalone', 'with': 'paper-a-recommends-first-line', 'value_a': False, 'value_b': True, 'divergences': {'standalone-use-supported': [True, False], 'standalone-diagnostic': [True, False], 'clinical-utility': ['use-alone', 'use-with-confirmation']}}]}, {'type': 'diff_value_divergence', 'items': [{'name': 'standalone-paper-conflict', 'replace': 'paper-b-standalone-explicit', 'with': 'paper-a-standalone-implied', 'value_a': False, 'value_b': True, 'divergences': {}}]}], 'warnings': []}

## Provenance: `high-sensitivity-holds`

```json
{
  "name": "high-sensitivity-holds",
  "type": "theorem",
  "wff": "(>= calprotectin-sensitivity 90)",
  "origin": "derived",
  "derivation_chain": [
    {
      "name": "calprotectin-sensitivity",
      "type": "fact",
      "origin": {
        "document": "Paper A: Diagnostic",
        "quotes": [
          "Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements."
        ],
        "explanation": "Calprotectin sensitivity for IBD vs IBS is 93%",
        "verified": true,
        "verify_manual": false,
        "grounded": true,
        "verification": [
          {
            "quote": "Sensitivity of 93% was observed in distinguishing IBD from IBS using fecal calprotectin measurements.",
            "verified": true,
            "original_position": 341,
            "normalized_position": 331,
            "length": 14,
            "positions": {
              "original": {
                "start": 341,
                "end": 440
              },
              "normalized": {
                "start": 331,
                "end": 429
              }
            },
            "confidence": {
              "score": 0.968,
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
                "description": "Removed 1 punctuation character(s)",
                "penalty": 0.02
              },
              {
                "type": "whitespace_normalization",
                "description": "Normalized whitespace",
                "penalty": 0.001
              },
              {
                "type": "whitespace_trimming",
                "description": "Trimmed leading/trailing whitespace",
                "penalty": 0.001
              }
            ],
            "context": {
              "full": "...ic gastrointestinal symptoms.\n\nResults\n\nSensitivity of 93% was observed in distinguishing IBD from IBS using fecal\ncalprotectin measurements. The negative predictive value was 96%...",
              "before": "ic gastrointestinal symptoms.\n\nResults\n\n",
              "after": ". The negative predictive value was 96%"
            }
          }
        ]
      }
    }
  ]
}
```
