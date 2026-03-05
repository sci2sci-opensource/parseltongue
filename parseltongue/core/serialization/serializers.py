"""Serialize and deserialize Parseltongue core types to/from JSON-safe dicts."""

from typing import Any

from ..atoms import Evidence, Symbol
from ..engine import Fact
from ..lang import Axiom, Term, Theorem

# ============================================================
# S-expression
# ============================================================


def serialize_sexp(obj) -> Any:
    """Convert an s-expression (with Symbols) to JSON-safe form."""
    if isinstance(obj, list):
        return [serialize_sexp(x) for x in obj]
    if isinstance(obj, Symbol):
        return {"__symbol__": str(obj)}
    if isinstance(obj, bool):
        return obj
    return obj


def deserialize_sexp(obj) -> Any:
    """Reconstruct an s-expression from JSON-safe form."""
    if isinstance(obj, list):
        return [deserialize_sexp(x) for x in obj]
    if isinstance(obj, dict) and "__symbol__" in obj:
        return Symbol(obj["__symbol__"])
    return obj


# ============================================================
# Evidence / Origin
# ============================================================


def serialize_evidence(ev: Evidence) -> dict:
    return {
        "__evidence__": True,
        "document": ev.document,
        "quotes": ev.quotes,
        "explanation": ev.explanation,
        "verification": ev.verification,
        "verified": ev.verified,
        "verify_manual": ev.verify_manual,
    }


def deserialize_evidence(d: dict) -> Evidence:
    return Evidence(
        document=d["document"],
        quotes=d.get("quotes", []),
        explanation=d.get("explanation", ""),
        verification=d.get("verification", []),
        verified=d.get("verified", False),
        verify_manual=d.get("verify_manual", False),
    )


def serialize_origin(origin) -> Any:
    if isinstance(origin, Evidence):
        return serialize_evidence(origin)
    return origin


def deserialize_origin(origin) -> Any:
    if isinstance(origin, dict) and origin.get("__evidence__"):
        return deserialize_evidence(origin)
    return origin


# ============================================================
# Core types
# ============================================================


def serialize_term(term: Term) -> dict:
    return {
        "definition": serialize_sexp(term.definition),
        "origin": serialize_origin(term.origin),
    }


def deserialize_term(name: str, d: dict) -> Term:
    return Term(
        name=name,
        definition=deserialize_sexp(d["definition"]),
        origin=deserialize_origin(d["origin"]),
    )


def serialize_fact(fact: Fact) -> dict:
    return {
        "wff": serialize_sexp(fact.wff),
        "origin": serialize_origin(fact.origin),
    }


def deserialize_fact(name: str, d: dict) -> Fact:
    return Fact(
        name=name,
        wff=deserialize_sexp(d.get("wff", d.get("value"))),
        origin=deserialize_origin(d.get("origin", "")),
    )


def serialize_axiom(axiom: Axiom) -> dict:
    return {
        "wff": serialize_sexp(axiom.wff),
        "origin": serialize_origin(axiom.origin),
    }


def deserialize_axiom(name: str, d: dict) -> Axiom:
    return Axiom(
        name=name,
        wff=deserialize_sexp(d["wff"]),
        origin=deserialize_origin(d["origin"]),
    )


def serialize_theorem(thm: Theorem) -> dict:
    return {
        "wff": serialize_sexp(thm.wff),
        "derivation": thm.derivation,
        "origin": serialize_origin(thm.origin),
    }


def deserialize_theorem(name: str, d: dict) -> Theorem:
    return Theorem(
        name=name,
        wff=deserialize_sexp(d["wff"]),
        derivation=d.get("derivation", []),
        origin=deserialize_origin(d["origin"]),
    )


# ============================================================
# Result types (DiffResult, ConsistencyReport)
# ============================================================


def serialize_diff_result(result) -> dict:

    return {
        "name": result.name,
        "replace": result.replace,
        "with": result.with_,
        "value_a": serialize_sexp(result.value_a),
        "value_b": serialize_sexp(result.value_b),
        "divergences": {k: [serialize_sexp(a), serialize_sexp(b)] for k, (a, b) in result.divergences.items()},
    }


def deserialize_diff_result(data: dict):
    from ..engine import DiffResult

    return DiffResult(
        name=data["name"],
        replace=data["replace"],
        with_=data["with"],
        value_a=deserialize_sexp(data["value_a"]),
        value_b=deserialize_sexp(data["value_b"]),
        divergences={
            k: [deserialize_sexp(a), deserialize_sexp(b)] for k, (a, b) in data.get("divergences", {}).items()
        },
    )


def serialize_consistency_issue(issue) -> dict:

    if issue.type in ("diff_divergence", "diff_value_divergence"):
        return {"type": issue.type, "items": [serialize_diff_result(d) for d in issue.items]}
    return {"type": issue.type, "items": [str(i) for i in issue.items]}


def deserialize_consistency_issue(data: dict):
    from ..engine import ConsistencyIssue

    t = data["type"]
    if t in ("diff_divergence", "diff_value_divergence"):
        items = [deserialize_diff_result(d) for d in data["items"]]
    else:
        items = data["items"]
    return ConsistencyIssue(type=t, items=items)


def serialize_consistency_warning(warning) -> dict:
    return {"type": warning.type, "items": warning.items}


def deserialize_consistency_warning(data: dict):
    from ..engine import ConsistencyWarning

    return ConsistencyWarning(type=data["type"], items=data["items"])


def serialize_consistency_report(report) -> dict:
    return {
        "consistent": report.consistent,
        "issues": [serialize_consistency_issue(i) for i in report.issues],
        "warnings": [serialize_consistency_warning(w) for w in report.warnings],
    }


def deserialize_consistency_report(data: dict):
    from ..engine import ConsistencyReport

    return ConsistencyReport(
        consistent=data["consistent"],
        issues=[deserialize_consistency_issue(i) for i in data.get("issues", [])],
        warnings=[deserialize_consistency_warning(w) for w in data.get("warnings", [])],
    )
