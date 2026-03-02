"""
System state formatters for LLM prompts.

Pass 1 uses system.doc() directly (DSL reference + empty state).
Pass 2 needs blinded state (fact values hidden).
Pass 3 (fact check) + Pass 4 (inference) need full state + consistency + provenance.
"""

from __future__ import annotations

import json

from ..core import to_sexp


def format_blinded_state(system) -> str:
    """Format system state with fact values hidden.

    Shows fact names and types but NOT values, term definitions,
    axiom WFFs, and existing theorems. Forces the LLM to reason
    about structure rather than specific numbers.
    """
    lines = []

    if system.facts:
        lines.append("Facts (names and types only — values hidden):")
        for name, info in system.facts.items():
            type_name = type(info["value"]).__name__
            lines.append(f"  {name}: {type_name}")

    if system.terms:
        lines.append("\nTerms:")
        for name, term in system.terms.items():
            defn = to_sexp(term.definition) if term.definition is not None else "(forward declaration)"
            lines.append(f"  {name} := {defn}")

    if system.axioms:
        lines.append("\nAxioms:")
        for name, ax in system.axioms.items():
            lines.append(f"  {name}: {to_sexp(ax.wff)}")

    if system.theorems:
        lines.append("\nTheorems (already derived):")
        for name, thm in system.theorems.items():
            sources = ", ".join(thm.derivation)
            lines.append(f"  {name}: {to_sexp(thm.wff)}  [from: {sources}]")

    return "\n".join(lines)


def format_full_state(system) -> str:
    """Format the fully evaluated system state for Pass 3.

    Combines system.doc() (DSL reference) + system.state() (runtime state)
    plus evaluated term values, consistency report, provenance chains,
    and diff results.
    """
    lines = [system.doc(), "\n" + system.state()]

    # Evaluated term values (state() shows definitions but not results)
    evaluated = []
    for name, term in system.terms.items():
        if term.definition is not None:
            try:
                val = system.evaluate(term.definition)
                evaluated.append(f"  {name} => {val}")
            except Exception:
                evaluated.append(f"  {name} => (could not evaluate)")
    if evaluated:
        lines.append("\n  Evaluated Terms")
        lines.append("  " + "-" * 15)
        lines.extend(evaluated)

    # Diff results
    if system.diffs:
        lines.append("\n  Diff Results")
        lines.append("  " + "-" * 12)
        for diff_name in system.diffs:
            try:
                result = system.eval_diff(diff_name)
                lines.append(f"  {result}")
            except Exception as e:
                lines.append(f"  {diff_name}: error — {e}")

    # Consistency
    report = system.consistency()
    lines.append(f"\n  Consistency: {report}")

    # Provenance chains
    prov_items = list(system.facts) + list(system.theorems)
    if prov_items:
        lines.append("\n  Provenance")
        lines.append("  " + "-" * 10)
        for name in prov_items:
            try:
                prov = system.provenance(name)
                lines.append(f"  {name}: {json.dumps(prov, indent=4, default=str)}")
            except Exception:
                pass

    return "\n".join(lines)
