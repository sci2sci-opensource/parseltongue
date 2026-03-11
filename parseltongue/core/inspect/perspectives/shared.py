"""Shared formatting helpers for perspectives."""

from parseltongue.core.atoms import Evidence, Symbol
from parseltongue.core.lang import to_sexp

from ..probe_core_to_consequence import NodeKind


def fmt_origin_rows(atom, detailed: bool = False) -> list[list[str]]:
    """Build table rows for origin/evidence fields.

    When *detailed* is True, each quote includes the document line number
    and confidence from the quote-verifier result (if available).
    """
    if atom is None or not hasattr(atom, "origin"):
        return []
    origin = atom.origin
    if isinstance(origin, Evidence):
        rows = [["document", origin.document]]
        vr_by_quote = {}
        if detailed and origin.verification:
            for v in origin.verification:
                vr_by_quote[v.get("quote", "")] = v
        for q in origin.quotes:
            vr = vr_by_quote.get(q)
            if vr:
                line = vr.get("original_line", -1)
                conf = vr.get("confidence", {})
                score = conf.get("score", 0)
                loc = f"line {line}" if line != -1 else "not found"
                rows.append(["quote", f"{q}  ({loc}, confidence {score:.2f})"])
            else:
                rows.append(["quote", q])
        if origin.explanation:
            rows.append(["explanation", origin.explanation])
        status = "grounded" if origin.is_grounded else "UNVERIFIED"
        rows.append(["status", status])
        return rows
    return [["origin", str(origin)]]


def fmt_value(v):
    if isinstance(v, (list, Symbol)):
        return to_sexp(v)
    return repr(v)


def _truncate(s: str, maxlen: int = 60) -> str:
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def fmt_origin(origin, brief: bool = False) -> str:
    if isinstance(origin, Evidence):
        parts = [f':evidence ("{origin.document}"']
        if origin.quotes:
            if brief:
                quoted = " ".join(repr(_truncate(q)) for q in origin.quotes)
            else:
                quoted = " ".join(repr(q) for q in origin.quotes)
            parts.append(f"  :quotes ({quoted})")
        if origin.explanation:
            parts.append(f'  :explanation "{origin.explanation}"')
        return "\n".join(parts) + ")"
    return f':origin "{origin}"'


def fmt_dsl(node, brief: bool = False) -> str:
    """Reconstruct DSL directive form from node kind + atom.

    When *brief* is True, quotes in evidence are truncated to avoid bloat
    in structure-level views.
    """
    atom = node.atom
    if atom is None:
        return f"; {node.name} (synthetic)"

    kind = node.kind
    name = atom.name

    if kind in (NodeKind.FACT,):
        wff = to_sexp(atom.wff)
        origin = fmt_origin(atom.origin, brief=brief)
        return f"(fact {name} {wff}\n  {origin})"

    if kind in (NodeKind.AXIOM,):
        wff = to_sexp(atom.wff)
        origin = fmt_origin(atom.origin, brief=brief)
        return f"(axiom {name}\n  {wff}\n  {origin})"

    if kind in (NodeKind.THEOREM, NodeKind.CALC):
        wff = to_sexp(atom.wff)
        using = " ".join(atom.derivation)
        return f"(derive {name}\n  {wff}\n  :using ({using}))"

    if kind in (NodeKind.TERM_FWD, NodeKind.TERM_COMP):
        origin = fmt_origin(atom.origin, brief=brief)
        if atom.definition is not None:
            defn = to_sexp(atom.definition)
            return f"(defterm {name} {defn}\n  {origin})"
        return f"(defterm {name}\n  {origin})"

    return str(atom)
