# Discovered Use Cases

Real-world applications discovered through building, testing, and using Parseltongue. Every example below has been run — most are reproducible from the included demos and sample documents.

## Software Engineering

Parseltongue was developed for large-scale consistency validation. Its CLI was designed as a codebase validation tool — it can check consistency of a codebase or the accuracy of specification implementation.

### Code Implementation Checks

Load source code as a document. The pipeline extracts facts about function signatures, module structure, return types, and behavior — each citing a verbatim quote from the code. Derivations cross-check internal consistency: does the function actually return what the type hint promises? Do the documented parameters match the signature?

In practice (run against Parseltongue's own core `engine.py`): the pipeline correctly extracted hundreds of facts from a single source file. Among them, the LLM fabricated several issues that had no basis in the actual code — and the quote verification caught every one. The hallucinated claims were flagged as unverified, and their taint propagated to every conclusion that depended on them. This saved enormous time — we could see immediately where the LLM's critique had no factual basis.

### Code-Specification Cross-Validation

Load both the specification and the implementation as separate documents. The pipeline extracts requirements from the spec and facts from the code independently, then cross-validates via `diff` directives. When the implementation diverges from the spec — a missing edge case, a different default value, a mismatched interface — the divergence is flagged with full provenance to both documents.

Tested by running the core README against `engine.py`: the system identified where documented behavior diverged from actual implementation, tracing each discrepancy to the specific README sentence and code passage.

### Documentation Validation

Run Parseltongue against documentation to catch factual errors. Every claim in the docs is extracted as a fact with a verbatim quote, then cross-checked for internal consistency and, when possible, against external knowledge.

In v0.3.1, the project's own README was validated this way. The pipeline caught two real platform bugs:

- **Linux**: `apt install pipx` only works on Ubuntu 23.04+ — older LTS releases fail silently
- **Windows**: single-quoted `pip install` commands break in `cmd.exe`

Both were caught by the LLM extracting install instructions as facts, then deriving platform-specific conclusions that evaluated to false.

### License and Policy Verification

Simple factual extraction from legal documents. When run against the Apache 2.0 LICENSE file ("Is this Apache license?"), the system returned **fully consistent** — the only completely clean run in the project's history. This demonstrates that when source material is precise and unambiguous, the pipeline produces zero false positives.

## Research

### Literature Review

Extract claims from research papers with verbatim quotes. Every fact traces back to a specific passage. Ungrounded claims — where the LLM asserts something not present in the paper — are flagged automatically.

Tested against a real [NEJM paper](../parseltongue/cli/demo/nejm.pdf) ("Are the results as wonderful as they seem? Any red flags?"): the pipeline extracted findings, statistical claims, and methodology facts, then flagged several assertions as potential fabrications where the LLM's critique had no basis in the actual paper text. The red flags the LLM invented were themselves hallucinations — and Parseltongue caught them.

### Cross-Paper Synthesis

Load multiple papers studying the same phenomenon. The pipeline extracts facts from each independently, derives cross-paper conclusions, and flags contradictions.

The [biomarkers demo](../parseltongue/core/demos/biomarkers/) demonstrates this with two medical papers on fecal calprotectin as an IBD diagnostic marker. Paper A reports 93% sensitivity and recommends it as a first-line test. Paper B reports only 67% specificity and warns against standalone use. Both are individually accurate — but the formal system makes the tension explicit: `reliable-marker` evaluates to true (93 > 90) while `standalone-diagnostic` evaluates to false (67 < 90). The synthesized clinical utility term resolves to `"use-with-confirmation"`, with full provenance tracing each conclusion back to specific quotes in each paper.

### Meta-Analysis Validation

Compare consistency between multiple studies, cohorts, and conclusions. The engine cross-checks reported effect sizes, sample counts, and conclusions — flagging where numbers don't add up or where conclusions don't follow from the evidence.

Run against a real [NEJM lung cancer genomics paper](../parseltongue/cli/demo/nejm.pdf): the pipeline extracted facts from three validation cohorts (Duke, ACOSOG, CALGB), then cross-checked them via diffs. It caught that the headline 93% accuracy was a training-set estimate while independent validation showed 72–79% — a 14–21 point drop flagged by `diff:loocv-inflation-check`. It verified that total sample counts summed correctly across cohorts (`diff:cohort-sum-check`). It compared sensitivity/specificity patterns across cohorts and found them inconsistent (85%/58% in one vs 68%/88% in another). And crucially — several of the LLM's own critique points were flagged as unverified fabrications: claims about cohort composition and blinding that couldn't be traced to any quote in the source paper.

The `diff` mechanism is particularly powerful for this: register two values that should agree (reported vs computed, training vs validation, cohort A vs cohort B), and the system replays all dependent evaluations under both assumptions. Where results diverge, provenance traces exactly which source quotes led to the conflict.

## Math

### Interactive Formal System Building

For mathematical research: define axioms, introduce terms, derive theorems, and verify that every conclusion follows from stated premises. The `diff` mechanism allows fast consistency checking — register two computation paths that should agree and instantly see where they diverge.

The system supports starting from scratch (`initial_env={}`) with no built-in operators at all, or extending the default environment with domain-specific operators. Each layer of extension builds on everything below it — the ordinal hierarchy of the system grows as you add structure.

### Neuro-Symbolic Generation of Formal Systems from Unstructured Data

Use the LLM pipeline to extract a formal system from unstructured text — field notes, papers, textbooks. The neural side reads and structures; the symbolic side verifies. The result is a machine-checkable formal system built from natural language sources.

The [apples demo](../parseltongue/core/demos/apples/) was run through the full LLM pipeline: given two documents of informal field notes about counting apples, the LLM extracted Peano axioms (zero, successor, addition identity, commutativity), grounded each in verbatim quotes from the observations, then derived concrete arithmetic theorems via `:bind`. The symbolic engine verified every step — the LLM proposed the structure, but the formal engine confirmed it was sound.

### Learning Formal Systems Mechanisms and Epistemology

The [apples demo](../parseltongue/core/demos/apples/) builds Peano arithmetic from scratch — natural numbers as `zero` and `succ`, addition via recursive axioms, commutativity, and concrete theorems like `3 + 0 = 3` — purely within the Parseltongue DSL, grounded in observational evidence about counting physical apples.

This is a hands-on way to learn how formal systems work: what axioms are, how rewrite rules transform expressions, what it means for a derivation to be valid, and why the scope restriction (`:using`) matters. Every theorem traces back to its premises, and every premise traces back to a quote from the source documents. The epistemological chain is fully transparent.
