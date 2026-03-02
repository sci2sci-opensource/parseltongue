"""
Reference resolver — parses [[type:name]] tags in Pass 3 markdown
and resolves them against the parseltongue System.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..core import to_sexp

TAG_RE = re.compile(r"\[\[(\w+):([^\]]+)\]\]")

VALID_TYPES = frozenset({"fact", "term", "axiom", "theorem", "quote", "diff"})


@dataclass
class Reference:
    """A resolved inline reference from the markdown output."""

    type: str
    name: str
    value: Any = None
    provenance: dict | None = None
    error: str | None = None


@dataclass
class ResolvedOutput:
    """Result of resolving all [[type:name]] tags in the markdown."""

    markdown: str
    references: list[Reference] = field(default_factory=list)
    consistency: str = ""

    def __str__(self):
        return self.markdown


def _resolve_one(tag_type: str, name: str, system) -> Reference:
    """Resolve a single [[type:name]] tag against the system."""
    ref = Reference(type=tag_type, name=name)

    try:
        if tag_type == "fact":
            if name not in system.facts:
                ref.error = f"unknown fact: {name}"
            else:
                ref.value = system.facts[name]["value"]
                ref.provenance = system.provenance(name)

        elif tag_type == "term":
            if name not in system.terms:
                ref.error = f"unknown term: {name}"
            else:
                term = system.terms[name]
                if term.definition is not None:
                    try:
                        ref.value = system.evaluate(term.definition)
                    except Exception:
                        ref.value = to_sexp(term.definition)
                else:
                    ref.value = "(forward declaration)"

        elif tag_type == "axiom":
            if name not in system.axioms:
                ref.error = f"unknown axiom: {name}"
            else:
                ref.value = to_sexp(system.axioms[name].wff)

        elif tag_type == "theorem":
            if name not in system.theorems:
                ref.error = f"unknown theorem: {name}"
            else:
                thm = system.theorems[name]
                ref.value = to_sexp(thm.wff)
                ref.provenance = system.provenance(name)

        elif tag_type == "quote":
            ref.provenance = system.provenance(name)
            # Pull the value from whatever store has it
            if name in system.facts:
                ref.value = system.facts[name]["value"]
            elif name in system.axioms:
                ref.value = to_sexp(system.axioms[name].wff)
            elif name in system.theorems:
                ref.value = to_sexp(system.theorems[name].wff)
            elif name in system.terms:
                ref.value = to_sexp(system.terms[name].definition)

        elif tag_type == "diff":
            if name not in system.diffs:
                ref.error = f"unknown diff: {name}"
            else:
                ref.value = system.eval_diff(name)

        else:
            ref.error = f"unknown reference type: {tag_type}"

    except KeyError as e:
        ref.error = str(e)

    return ref


def resolve_references(markdown: str, system) -> ResolvedOutput:
    """Parse all [[type:name]] tags and resolve against the System.

    Returns a ResolvedOutput with the original markdown, resolved
    references, and a consistency summary.
    """
    references = []
    seen = set()

    for match in TAG_RE.finditer(markdown):
        tag_type, name = match.group(1), match.group(2)
        key = (tag_type, name)
        if key in seen:
            continue
        seen.add(key)

        if tag_type not in VALID_TYPES:
            references.append(
                Reference(
                    type=tag_type,
                    name=name,
                    error=f"unknown reference type: {tag_type}",
                )
            )
            continue

        references.append(_resolve_one(tag_type, name, system))

    report = system.consistency()
    consistency = str(report)

    return ResolvedOutput(
        markdown=markdown,
        references=references,
        consistency=consistency,
    )
