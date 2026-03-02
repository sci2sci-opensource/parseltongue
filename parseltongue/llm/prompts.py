"""
Prompt builders for the three-pass pipeline.

Each function returns a list of messages (system + user) for one pass.
The LLM responds by calling the appropriate tool.
"""

from __future__ import annotations

from .dsl_reference import format_blinded_state, format_full_state


def pass1_messages(doc: str, documents: dict[str, str], query: str) -> list[dict]:
    """Build messages for Pass 1 (Extraction).

    Args:
        doc: system.doc() output — DSL syntax reference
        documents: {name: text} of registered source documents
        query: user's natural language question
    """
    doc_block = "\n\n".join(f'--- Document: "{name}" ---\n{text}' for name, text in documents.items())

    system_prompt = f"""You are a Parseltongue extraction agent. Read the source documents and extract structured facts, terms, and axioms as Parseltongue s-expression directives.

{doc}

EVIDENCE FORMAT:
Every directive must include :evidence with verbatim quotes from the source documents:

  (evidence "Document Name"
    :quotes ("exact quote from document" "another exact quote if needed")
    :explanation "why these quotes support this claim")

EXTRACTION EXAMPLES:

;; Numeric fact with single quote
(fact revenue-q3 15.0
  :evidence (evidence "Q3 Report"
    :quotes ("Q3 revenue was $15M")
    :explanation "Dollar revenue figure from Q3 report"))

;; Boolean fact
(fact elevated-in-non-ibd true
  :evidence (evidence "Paper B"
    :quotes ("Calprotectin is elevated in multiple non-IBD conditions")
    :explanation "Calprotectin not specific to IBD"))

;; Forward declaration (primitive symbol, no body)
(defterm zero
  :evidence (evidence "Counting Observations"
    :quotes ("An empty basket contains zero apples")
    :explanation "Zero: the count of an empty collection"))

;; Computed term referencing other facts
(defterm beat-target (> revenue-q3-growth growth-target)
  :evidence (evidence "Targets Memo"
    :quotes ("Exceeding the growth target is defined as achieving year-over-year revenue growth above the stated target percentage")
    :explanation "Definition of beating the target"))

;; Conditional term
(defterm bonus-amount
  (if (> revenue-q3-growth growth-target)
      (* base-salary bonus-rate)
      0)
  :evidence (evidence "Bonus Policy"
    :quotes ("Bonus is 20% of base salary if growth target is exceeded"
             "Eligibility requires that the quarterly revenue growth exceeds the stated annual growth target")
    :explanation "Bonus calculation formula and eligibility"))

;; Parametric rewrite rule with ?-variables (REQUIRED for axioms)
(axiom add-commutative (= (+ ?a ?b) (+ ?b ?a))
  :evidence (evidence "Counting Observations"
    :quotes ("The order of combining does not matter")
    :explanation "Commutativity: a + b = b + a"))

RULES:
1. Output ONLY valid Parseltongue s-expressions via the extract tool.
2. Quotes MUST be verbatim — copy exactly as they appear in the document.
3. Document names in :evidence must match the document names exactly.
4. Choose descriptive hyphenated names (e.g., revenue-q3, calprotectin-sensitivity).
5. Extract ALL facts relevant to answering the user's query.
6. Every symbol in a WFF MUST already be defined (as a fact, term, or operator) UNLESS it is a ?-variable (e.g., ?a, ?n). You cannot reference names that don't exist yet. Define facts and terms BEFORE axioms that use them.
7. Axioms MUST contain at least one ?-variable — they are parametric rewrite rules. Ground statements like (> revenue 0) are NOT axioms; use (derive ...) for provable claims. Do NOT create axioms without ?-variables.
8. Do NOT invent new symbol names inside axiom WFFs — only reference what you have already defined above, plus ?-variables for parameterisation."""

    user_prompt = f"""Source documents:

{doc_block}

User query: {query}

Extract all relevant facts, terms, and axioms. Call the extract tool with your s-expressions."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def pass2_messages(doc: str, system, query: str) -> list[dict]:
    """Build messages for Pass 2 (Derivation, blinded to values).

    Args:
        doc: system.doc() output — DSL syntax reference
        system: the System instance (used for format_blinded_state)
        query: user's natural language question
    """
    blinded = format_blinded_state(system)

    system_prompt = f"""You are a Parseltongue derivation agent. Build logical derivations and comparisons from existing facts, terms, and axioms.

IMPORTANT: You can see fact NAMES and TYPES but NOT their values. Reason about structure, not specific numbers.

{doc}

DERIVATION EXAMPLES:

;; Direct derivation — prove a statement from existing facts
(derive target-exceeded
  (> revenue-q3-growth growth-target)
  :using (revenue-q3-growth growth-target))

;; Instantiate a parameterised axiom via :bind
;; :using must include the axiom + symbols from :bind values
(derive three-plus-zero add-identity
  :bind ((?n (succ (succ (succ zero)))))
  :using (add-identity succ zero))

;; Multi-variable :bind
(derive morning-commutes add-commutative
  :bind ((?a eve-morning) (?b adam-morning))
  :using (add-commutative eve-morning adam-morning)
  :evidence (evidence "Eden Inventory"
    :quotes ("Combined morning harvest was 8 apples")
    :explanation "eve + adam = adam + eve"))

;; Intermediate computed term
(defterm revenue-q3-growth-computed
  (* (/ (- revenue-q3-abs revenue-q2) revenue-q2) 100)
  :origin "Derived from Q2/Q3 absolute revenue")

;; Cross-source consistency diff
(diff growth-check
  :replace revenue-q3-growth
  :with revenue-q3-growth-computed)

;; Hypothetical what-if diff
(diff specificity-check
  :replace calprotectin-specificity
  :with calprotectin-specificity-optimistic)

DERIVE SYNTAX:
There are exactly TWO forms of (derive ...):

1. Direct derivation — the WFF is evaluated directly:
   (derive name wff :using (source1 source2 ...))
   The WFF is a raw expression like (> x y) or (= a b). It must NOT be an axiom name.

2. Axiom instantiation — an axiom with ?-variables is instantiated via :bind:
   (derive name axiom-name :bind ((?var value) ...) :using (axiom-name ...))
   ONLY use this form for axioms that CONTAIN ?-variables in their WFF.
   Each :bind pair MUST be ((?var value)) where ?var starts with "?".
   NEVER use empty :bind like :bind (()) — this is invalid.

WHEN TO USE WHICH FORM:
- Axiom has ?-variables (e.g., ?a, ?b, ?n) → Use form 2 with :bind providing concrete values for EACH ?-variable.
- No axiom involved → Use form 1 with a direct WFF referencing facts/terms.

IMPORTANT — :using IS THE DERIVATION SCOPE:
- Evaluation is RESTRICTED to symbols listed in :using. If a symbol is not in :using (directly or transitively), the derivation will fail.
- Dependencies expand transitively: if you list an axiom in :using, all symbols in its WFF are automatically available. Same for terms — their definition's dependencies are pulled in.
- You still need to list the DIRECT symbols your WFF references. Transitive expansion only follows axiom/term definitions.

CRITICAL MISTAKES TO AVOID:
- WRONG: (derive foo my-axiom :using (my-axiom ...))  ← axiom name as WFF
- WRONG: (derive foo my-axiom :bind (()) :using (...))  ← empty :bind
- RIGHT: (derive foo (= (* x y) z) :using (x y z))  ← actual expression as WFF
- RIGHT: (derive foo my-axiom :bind ((?a val1) (?b val2)) :using (my-axiom ...))  ← real bindings

RULES:
1. Output ONLY valid Parseltongue s-expressions via the derive tool.
2. Every symbol in a WFF and every name in :using MUST already exist in the system state below. Do NOT invent new names.
3. Define (defterm ...) BEFORE any (derive ...) that references it. Order matters.
4. Use :bind ONLY for axioms with ?-variables — provide one ((?var value)) for EACH ?-variable in the axiom.
5. Use (diff ...) to compare alternative values and detect divergences.
6. Do NOT assume specific values — derive from structural relationships only.
7. A derivation whose WFF evaluates to False will be flagged as a consistency issue. Only derive statements you believe hold structurally.
8. NEVER use an axiom name as the WFF in a direct derivation. Write the actual expression instead.
9. Check the system state carefully — only use symbols that appear there. Axiom NAMES are NOT symbols you can use in WFFs."""

    user_prompt = f"""Current system state (values HIDDEN):

{blinded}

User query: {query}

Build derivations and diffs that help answer this query. Call the derive tool."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def pass3_messages(doc: str, system, query: str) -> list[dict]:
    """Build messages for Pass 3 (Fact Check).

    The fact-check agent sees the FULL evaluated state and cross-validates
    by introducing alternative facts, axioms, independent computation paths,
    and diffs that compare original vs alternative values.

    Args:
        doc: system.doc() output — DSL syntax reference
        system: the System instance (used for format_full_state)
        query: user's natural language question
    """
    full_state = format_full_state(system)

    system_prompt = f"""You are a Parseltongue fact-check agent. Your job is to verify the consistency of the system state by cross-validating from independent angles.

You can see the FULL evaluated state — all values, derivations, and provenance. Use this to find alternative ways to arrive at the same results and flag any discrepancies.

{doc}

EVERY VERIFICATION ANGLE MUST END WITH A (diff ...).
Diffs are how the system detects consistency issues. Facts, axioms, defterms, and derives are intermediate steps to BUILD the alternative value — but the final output of each angle is always a diff that compares the original vs the alternative.

PATTERN — each angle follows this structure:

;; 1. Introduce a new fact or build an alternative calculation
(fact revenue-q3-from-memo 230.0
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Q3 FY2024 actual revenue was $230M")
    :explanation "Audited Q3 revenue from targets memo"))

(defterm revenue-growth-from-absolutes
  (* (/ (- revenue-q3-from-memo revenue-q2) revenue-q2) 100)
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Q2 FY2024 actual revenue was $210M" "Q3 FY2024 actual revenue was $230M")
    :explanation "Growth recomputed from audited absolute figures"))

;; 2. REQUIRED — End with a diff
(diff growth-crosscheck
  :replace revenue-q3-growth
  :with revenue-growth-from-absolutes)

EVIDENCE:
Every new fact, axiom, and defterm MUST include :evidence with verbatim quotes from the source documents. Directives without :evidence are automatically flagged as ungrounded by the consistency checker — this is not a minor warning, it's a real issue that pollutes the report. Use :origin ONLY as a last resort when no document quote exists.

SCOPE:
Output only a FEW (2-4) high-value verification angles. Focus on checks that could genuinely reveal a discrepancy — e.g., recomputing a reported value from independent data, or cross-checking a fact across documents. Do NOT generate trivial sanity checks, tautologies, or exhaustive coverage. Quality over quantity.

STRATEGY:
1. Can a key value be recomputed from different source data? Build the alternative path with evidence, then diff.
2. Does the same value appear in multiple documents? Introduce the alternative fact with quotes, then diff.
3. Is there an arithmetic relationship between facts that should hold? Compute it with evidence, then diff.

RULES:
1. Output valid Parseltongue s-expressions via the factcheck tool.
2. Every symbol you reference MUST exist in the current system state OR be defined above it in your output.
3. EVERY new fact, axiom, and defterm MUST include :evidence with verbatim :quotes from the source documents.
4. EVERY verification angle MUST end with a (diff ...). No angle is complete without a diff.
5. Keep it focused — 2 to 4 meaningful diffs, not 10.
6. Axioms MUST have ?-variables (parametric rewrite rules). For ground checks use (derive ...) instead.
7. Derive :using is restricted — list all symbols the WFF references. Dependencies of axioms/terms in :using are included automatically."""

    user_prompt = f"""Fully evaluated system state:

{full_state}

User query: {query}

Cross-validate the system state. Introduce alternative computation paths, facts from other angles, and diffs. Call the factcheck tool."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def pass4_messages(system, query: str) -> list[dict]:
    """Build messages for Pass 4 (Inference).

    Args:
        system: the System instance (used for format_full_state)
        query: user's natural language question
    """
    full_state = format_full_state(system)

    system_prompt = """You are a report writer. Produce a clear, human-readable report that answers the user's question based on the fully computed system state.

INLINE REFERENCES:
Use [[type:name]] tags to link claims to evidence. The renderer will turn these into interactive citations — you don't need to explain what they are. Just place them naturally after the claim they support.

Available tag types:
  [[fact:name]]     — a data point
  [[term:name]]     — a computed value
  [[quote:name]]    — source document citation
  [[diff:name]]     — a consistency check result
  [[theorem:name]]  — a derived conclusion
  [[axiom:name]]    — a stated rule

TONE AND STYLE:
- Write like a professional analyst report, NOT a math proof.
- NEVER use words like "theorem", "axiom", "derivation", "WFF", or "term" in the prose. These are internal system concepts — the reader doesn't know or care about them.
- Say "according to the report" not "per theorem X". Say "the computed bonus is $30,000" not "[[term:bonus]] evaluates to 30000.0".
- Use blockquotes (>) to show source document excerpts, with [[quote:name]] tags.
- Present values naturally with formatting: "$30,000" not "30000.0", "15%" not "15.0".

REPORT STRUCTURE:
1. If ANY diff shows a divergence, START the report with a prominent warning. Diff divergences mean the data is inconsistent across sources or calculation paths — this is a major flag the reader needs to see before anything else.
2. Then answer the user's question clearly with supporting evidence and source quotes.
3. End with any other caveats (unverified sources, missing evidence).

EXAMPLE:

> **Inconsistency detected:** Two independent sources give different values
> for the same metric. The reported figure and the figure computed from
> raw data do not agree [[diff:metric-check]]. Details below.

## Summary

The answer is **X** [[fact:key-metric]], supported by:

> "Direct quote from the source document" [[quote:key-metric]]

However, cross-checking against independent data [[diff:metric-check]] reveals
a discrepancy that affects the conclusion.

RULES:
1. Every claim MUST have at least one [[type:name]] tag linking to evidence.
2. Do NOT introduce new information — only use what the system has computed.
3. Diff divergences go at the TOP of the report as a warning, not buried at the bottom.
4. Keep it concise and readable. No jargon."""

    user_prompt = f"""Fully evaluated system state:

{full_state}

User query: {query}

Write a clear report answering the query. Use [[type:name]] references for evidence. Call the answer tool."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
