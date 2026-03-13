"""
Parseltongue Engine — evaluation core.

Accepts an env dict and provides: evaluation, rewriting, derivation,
diffs, consistency checking, document management (direct registration,
loading from files, and ground-truth indexing for evidence verification),
evidence verification, and DSL loading.
"""

import logging
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from .atoms import Evidence, Symbol, free_vars, match, substitute
from .lang import (
    AXIOM,
    DEFTERM,
    DELEGATE,
    DERIVE,
    DIFF,
    EQ,
    FACT,
    IF,
    KW_BIND,
    KW_EVIDENCE,
    KW_ORIGIN,
    KW_REPLACE,
    KW_USING,
    KW_WITH,
    LET,
    PROJECT,
    QUOTE,
    SCOPE,
    SELF,
    SPECIAL_FORMS,
    STRICT,
    Axiom,
    Term,
    Theorem,
    get_keyword,
    parse_evidence,
    read_tokens,
    to_sexp,
    tokenize,
)
from .quote_verifier import QuoteVerifier

log = logging.getLogger("parseltongue")


# ============================================================
# Consistency classification
# ============================================================


class IssueType(StrEnum):
    """Types of consistency issues (errors — break consistent=True)."""

    UNVERIFIED_EVIDENCE = "unverified_evidence"
    NO_EVIDENCE = "no_evidence"
    POTENTIAL_FABRICATION = "potential_fabrication"
    DIFF_DIVERGENCE = "diff_divergence"
    DIFF_VALUE_DIVERGENCE = "diff_value_divergence"


class WarningType(StrEnum):
    """Types of consistency warnings (noted but don't break consistency)."""

    MANUALLY_VERIFIED = "manually_verified"
    DIFF_CONTAMINATION = "diff_contamination"


# ============================================================
# Result Types
# ============================================================


@dataclass(frozen=True)
class Fact(Axiom):
    """A fact: non-parametric axiom — ground truth value with evidence."""


@dataclass
class DiffResult:
    """Result of evaluating a diff between two symbols."""

    name: str
    replace: str
    with_: str
    value_a: Any
    value_b: Any
    divergences: dict[str, list] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.divergences

    @property
    def values_diverge(self) -> bool:
        return self.value_a != self.value_b

    @property
    def diff_contamination_only(self) -> bool:
        """True when all divergences are sibling-diff contamination (no theorem/fact/term/axiom hits)."""
        if self.empty:
            return False
        return all(isinstance(v[0], str) and v[0].startswith("diff(") for v in self.divergences.values())

    def to_dict(self) -> dict:
        from .serialization import serialize_diff_result

        return serialize_diff_result(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DiffResult":
        from .serialization import deserialize_diff_result

        return deserialize_diff_result(data)

    def __str__(self):
        va = to_sexp(self.value_a) if isinstance(self.value_a, (list, Symbol)) else self.value_a
        vb = to_sexp(self.value_b) if isinstance(self.value_b, (list, Symbol)) else self.value_b
        header = f"{self.name}: {self.replace} ({va}) vs {self.with_} ({vb})"
        if self.empty and not self.values_diverge:
            return f"{header} — no divergences"
        if self.empty and self.values_diverge:
            return f"{header} — values differ"
        lines = [header]
        for term, (a, b) in sorted(self.divergences.items()):
            a_s = to_sexp(a) if isinstance(a, (list, Symbol)) else a
            b_s = to_sexp(b) if isinstance(b, (list, Symbol)) else b
            lines.append(f"{term}: {a_s} → {b_s}")
        return "\n".join(lines)


@dataclass
class ConsistencyIssue:
    """A single consistency issue."""

    type: IssueType
    items: list

    def to_dict(self) -> dict:
        from .serialization import serialize_consistency_issue

        return serialize_consistency_issue(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConsistencyIssue":
        from .serialization import deserialize_consistency_issue

        return deserialize_consistency_issue(data)

    def __str__(self):
        labels = {
            IssueType.UNVERIFIED_EVIDENCE: "Unverified evidence",
            IssueType.NO_EVIDENCE: "No evidence provided",
            IssueType.POTENTIAL_FABRICATION: "Potential fabrication",
            IssueType.DIFF_DIVERGENCE: "Diff divergence",
            IssueType.DIFF_VALUE_DIVERGENCE: "Diff value divergence",
        }
        label = labels.get(self.type, self.type)
        parts = [f"{label}:"]
        if self.type in (IssueType.DIFF_DIVERGENCE, IssueType.DIFF_VALUE_DIVERGENCE):
            for d in self.items:
                for i, line in enumerate(str(d).splitlines()):
                    parts.append(f"    {line}" if i else f"  {line}")
        elif self.type == IssueType.UNVERIFIED_EVIDENCE:
            for item in self.items:
                if isinstance(item, tuple):
                    name, quotes = item
                    parts.append(f"    {name}")
                    for q in quotes or []:
                        parts.append(f"      quote: {q!r}")
                else:
                    parts.append(f"    {item}")
        elif self.type == IssueType.NO_EVIDENCE:
            for item in self.items:
                if isinstance(item, tuple):
                    name, origin = item
                    parts.append(f"    {name} (origin: {origin})")
                else:
                    parts.append(f"    {item}")
        else:
            for item in self.items:
                parts.append(f"    {item}")
        return "\n".join(parts)


@dataclass
class ConsistencyWarning:
    """A single consistency warning."""

    type: WarningType
    items: list[str]
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        from .serialization import serialize_consistency_warning

        return serialize_consistency_warning(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConsistencyWarning":
        from .serialization import deserialize_consistency_warning

        return deserialize_consistency_warning(data)

    def __str__(self):
        if self.type == WarningType.MANUALLY_VERIFIED:
            return f"Manually verified: {', '.join(self.items)}"
        return f"{self.type}: {', '.join(self.items)}"

    def verbose(self) -> str:
        """Detailed warning with per-item context."""
        if not self.details:
            return str(self)
        lines = [f"{self.type} ({len(self.items)} items):"]
        for item in self.items:
            detail = self.details.get(item)
            if detail:
                lines.append(f"  {item}: {detail}")
            else:
                lines.append(f"  {item}")
        return "\n".join(lines)


@dataclass
class ConsistencyReport:
    """Full consistency report for the system."""

    consistent: bool
    issues: list[ConsistencyIssue] = field(default_factory=list)
    warnings: list[ConsistencyWarning] = field(default_factory=list)

    def to_dict(self) -> dict:
        from .serialization import serialize_consistency_report

        return serialize_consistency_report(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConsistencyReport":
        from .serialization import deserialize_consistency_report

        return deserialize_consistency_report(data)

    def __str__(self):
        if self.consistent and not self.warnings:
            return "System is fully consistent"
        lines = []
        if self.consistent:
            lines.append("System is consistent")
        else:
            lines.append(f"System inconsistent: {len(self.issues)} issue(s)")
            for issue in self.issues:
                issue_str = str(issue)
                for line in issue_str.splitlines():
                    lines.append(f"  {line}")
        for w in self.warnings:
            lines.append(f"  [warning] {w}")
        return "\n".join(lines)

    def verbose(self) -> str:
        """Full report with detailed warnings."""
        lines = [str(self)]
        if any(w.details for w in self.warnings):
            lines.append("")
            lines.append("  Detailed warnings:")
            for w in self.warnings:
                for line in w.verbose().splitlines():
                    lines.append(f"    {line}")
        return "\n".join(lines)


# ============================================================
# Delegate helpers
# ============================================================


# ============================================================
# Engine
# ============================================================


class Engine:
    """Evaluation engine with document management. No serialization."""

    def __init__(
        self, env: dict, overridable: bool = False, strict_derive: bool = True, verifier: QuoteVerifier | None = None
    ):
        self.axioms: dict[str, Axiom] = {}
        self.theorems: dict[str, Theorem] = {}
        self.terms: dict[str, Term] = {}
        self.facts: dict[str, Fact] = {}
        self.env: dict = dict(env)
        self.diffs: dict[str, dict] = {}
        self.diff_refs: dict[str, set[str]] = {}  # name → diff names that reference it
        self.documents: dict[str, str] = {}
        self._verifier = verifier or QuoteVerifier()
        self.overridable = overridable
        self.strict_derive = strict_derive

    # ----------------------------------------------------------
    # Document Registry
    # ----------------------------------------------------------

    def register_document(self, name: str, text: str):
        self.documents[name] = text
        self._verifier.index.add(name, text)

    def load_document(self, name: str, path: str):
        with open(path) as f:
            text = f.read()
        self.documents[name] = text
        self._verifier.index.add(name, text)

    # ----------------------------------------------------------
    # Evidence Verification
    # ----------------------------------------------------------

    def _verify_evidence(self, evidence: Evidence, caller: str | None = None) -> Evidence:
        if evidence.document not in self.documents:
            log.warning("Document '%s' not registered — skipping verification", evidence.document)
            return evidence

        results = self._verifier.verify_indexed_quotes(evidence.document, evidence.quotes, caller=caller)

        all_verified = True
        for r in results:
            if r["verified"]:
                conf = r.get("confidence", {})
                log.info('Quote verified: "%s" (confidence: %s)', r["quote"], conf.get("level", "?"))
            else:
                all_verified = False
                reason = r.get("reason", "unknown")
                log.warning('Quote NOT verified: "%s" (%s)', r["quote"], reason)

        return replace(evidence, verification=results, verified=all_verified)

    def _lookup(self, name: str) -> Axiom | Theorem | Term | None:
        """Find a named item across all stores."""
        if name in self.facts:
            return self.facts[name]
        if name in self.axioms:
            return self.axioms[name]
        if name in self.theorems:
            return self.theorems[name]
        if name in self.terms:
            return self.terms[name]
        return None

    def verify_manual(self, name: str):
        item = self._lookup(name)
        if item is None:
            raise KeyError(f"Unknown: {name}")

        origin = item.origin
        if isinstance(origin, Evidence):
            new_origin = replace(origin, verify_manual=True)
        else:
            new_origin = Evidence(
                document="manual",
                quotes=[],
                explanation=origin if isinstance(origin, str) else str(origin),
                verify_manual=True,
            )

        # Write back to the correct store with narrowed type
        if name in self.facts:
            self.facts[name] = replace(self.facts[name], origin=new_origin)
        elif name in self.axioms:
            self.axioms[name] = replace(self.axioms[name], origin=new_origin)
        elif name in self.theorems:
            self.theorems[name] = replace(self.theorems[name], origin=new_origin)
        elif name in self.terms:
            self.terms[name] = replace(self.terms[name], origin=new_origin)

        log.info("'%s' manually marked as grounded", name)

    # ----------------------------------------------------------
    # Evaluation
    # ----------------------------------------------------------

    def evaluate(self, expr, local_env=None) -> Any:
        """Evaluate an s-expression in the current system."""
        env = {**self.env, **(local_env or {})}
        return self._eval(expr, env)

    def _eval_rewritten(self, expr, env, axiom_scope, restricted):
        """Rewrite an expression then re-evaluate the result."""
        rewritten = self._rewrite(expr, axiom_scope=axiom_scope)
        if rewritten != expr and isinstance(rewritten, list):
            return self._eval(rewritten, env, axiom_scope, restricted)
        return rewritten

    def _rewrite(self, expr, depth=0, axiom_scope=None, _prev=None):
        """Reduce an expression by applying axioms as rewrite rules.

        Axioms of the form (= LHS RHS) are used left-to-right:
        if expr matches LHS, substitute to get RHS.

        When *axiom_scope* is provided, only those rules are tried;
        otherwise all axioms and theorems in the system are used.
        """
        log.debug("_rewrite depth=%d expr=%r", depth, expr)
        if depth > 100:
            return expr
        if not isinstance(expr, list):
            return expr

        # Reduce subexpressions first (innermost-first)
        expr = [self._rewrite(sub, depth + 1, axiom_scope) for sub in expr]

        # Try axioms and theorems as rewrite rules
        if axiom_scope is not None:
            rules = axiom_scope
        else:
            rules = list(self.axioms.values()) + list(self.theorems.values())
        for rule in rules:
            wff = rule.wff
            if not (isinstance(wff, list) and len(wff) == 3 and wff[0] == EQ):
                continue
            lhs, rhs = wff[1], wff[2]
            if not isinstance(lhs, list):
                continue
            bindings = match(lhs, expr)
            if bindings is not None:
                result = substitute(rhs, bindings)
                if result == expr or result == _prev:
                    continue  # 1-cycle or 2-cycle — skip
                log.debug("_rewrite rule %s: %r -> %r", rule.name, expr, result)
                return self._rewrite(result, depth + 1, axiom_scope, _prev=expr)

        return expr

    def _eval(self, expr, env, axiom_scope=None, restricted=False) -> Any:
        log.debug("_eval expr=%r restricted=%s", expr, restricted)
        if isinstance(expr, Symbol):
            if expr in env:
                val = env[expr]
                log.debug("_eval symbol %r -> %r", expr, val)
                return val
            name = str(expr)
            # In restricted mode, symbols must be in env — no global fallthrough
            if not restricted and name in self.terms:
                defn = self.terms[name].definition
                if defn is not None:
                    return self._eval(defn, env, axiom_scope, restricted)
                return expr  # forward-declared / primitive term
            if not restricted and name in self.theorems:
                return self._eval(self.theorems[name].wff, env, axiom_scope, restricted)
            if self.strict_derive:
                raise NameError(
                    f"Unresolved symbol: {expr} — not in :using"
                    if restricted
                    else f"Unresolved symbol: {expr} — not in current system"
                )
        if not isinstance(expr, list):
            return expr

        if not expr:
            return None

        head = expr[0]

        if head == IF:
            _, cond, then, else_ = expr
            return (
                self._eval(then, env, axiom_scope, restricted)
                if self._eval(cond, env, axiom_scope, restricted)
                else self._eval(else_, env, axiom_scope, restricted)
            )

        if head == LET:
            _, bindings, body = expr
            new_env = env.copy()
            for binding in bindings:
                new_env[binding[0]] = self._eval(binding[1], new_env, axiom_scope, restricted)
            return self._eval(body, new_env, axiom_scope, restricted)

        if head == QUOTE:
            return expr[1]

        if head == STRICT:
            inner = expr[1]
            # Propagate strict through scope boundaries:
            # (strict (scope name expr ...)) → (scope name (strict expr) ...)
            if isinstance(inner, list) and inner and inner[0] == SCOPE and len(inner) > 2:
                wrapped = [SCOPE, inner[1]] + [[STRICT, arg] for arg in inner[2:]]
                return self._eval(wrapped, env, axiom_scope, restricted)
            return self._eval(inner, env, axiom_scope, restricted)

        if head == SELF:
            # (self expr ...) — evaluate all args in the current engine
            result = None
            for arg in expr[1:]:
                result = self._eval(arg, env, axiom_scope, restricted)
            return result

        if head == PROJECT:
            # (project expr) — evaluate expr in current engine (self basis)
            # (project basis expr) — resolve basis to a callable, evaluate expr in that basis
            if len(expr) == 2:
                return self._eval(expr[1], env, axiom_scope, restricted)
            basis = expr[1]
            if basis == SELF:
                return self._eval(expr[2], env, axiom_scope, restricted)
            basis_val = self._eval(basis, env, axiom_scope, restricted)
            if callable(basis_val):
                return basis_val(basis, *expr[2:])
            raise TypeError(f"project basis is not callable: {basis_val!r}")

        if head == DELEGATE:
            # (delegate body :bind (...)) or (delegate pattern body :bind (...))
            # Count nesting depth — each delegate layer = +1 level.
            depth = 0
            e = expr
            while isinstance(e, list) and e and e[0] == DELEGATE:
                depth += 1
                e = e[1]
            binds = get_keyword(expr, KW_BIND, [])
            # Pick the depth-th non-[] entry from closest (end)
            found = 0
            for proposal in reversed(binds):
                if proposal != []:
                    found += 1
                    if found == depth:
                        return proposal
            raise NameError(f"delegate depth {depth} but only {found} matching proposals: " f"{to_sexp(expr)}")

        if head == SCOPE:
            # (scope name expr ...) — resolve name to callable, pass args with:
            #   - (project ...) eagerly evaluated by THIS engine
            #   - (delegate ...) pattern evaluated, proposal posted to :bind
            name = expr[1]
            if name == SELF:
                result = None
                for arg in expr[2:]:
                    result = self._eval(arg, env, axiom_scope, restricted)
                return result
            scope_val = self._eval(name, env, axiom_scope, restricted)
            if callable(scope_val):

                def _delegate_proposal(delegate_expr):
                    """Post a proposal for this scope level.

                    Peel all delegate nesting to find the innermost body.
                    Collect ?-vars, bind ?name → env[name], ?level → stack pos.
                    If conditional (pattern present): evaluate pattern first,
                    return [] if it doesn't hold.
                    Evaluate body with bindings → return result.
                    """
                    # Peel to innermost body, collect any patterns
                    pattern = None
                    e = delegate_expr
                    while isinstance(e, list) and e and e[0] == DELEGATE:
                        # Check for conditional: e[2] exists and isn't :bind
                        if len(e) > 2 and e[2] != KW_BIND:
                            pattern = e[1]
                            e = e[2]
                        else:
                            e = e[1]
                    body = e

                    existing = get_keyword(delegate_expr, KW_BIND, [])
                    level = len(existing) + 1

                    # Collect ?-vars from pattern + body
                    all_vars = set()
                    if pattern:
                        all_vars |= free_vars(pattern)
                    all_vars |= free_vars(body)

                    # Bind ?name → resolved(name), ?...name → resolved(name), ?_level → stack position
                    bindings = {}
                    for var in all_vars:
                        vname = str(var)
                        if vname == "?_level":
                            bindings[var] = level
                            continue
                        if vname.startswith("?..."):
                            plain = Symbol(vname[4:])
                        else:
                            plain = Symbol(vname[1:])
                        try:
                            bindings[var] = self._eval(plain, env, axiom_scope, restricted)
                        except (NameError, TypeError):
                            return []

                    if pattern is not None:
                        bound_pattern = substitute(pattern, bindings)
                        try:
                            result = self._eval(bound_pattern, env, axiom_scope, restricted)
                        except (NameError, TypeError):
                            return []
                        if not result:
                            return []

                    bound_body = substitute(body, bindings)
                    return self._eval(bound_body, env, axiom_scope, restricted)

                def _rp(e):
                    """Resolve (project ...) and build delegate proposals."""
                    if not isinstance(e, list) or not e:
                        return e
                    if e[0] == PROJECT:
                        return self._eval(e, env, axiom_scope, restricted)
                    if e[0] == DELEGATE:
                        # Post this level's proposal, keep body unevaluated
                        existing = get_keyword(e, KW_BIND, [])
                        try:
                            proposal = _delegate_proposal(e)
                            new_binds = existing + [proposal]
                        except (NameError, TypeError):
                            new_binds = existing + [[]]
                        # Rebuild: strip old :bind, attach new
                        base = []
                        for x in e:
                            if x == KW_BIND:
                                break
                            base.append(x)
                        return base + [KW_BIND, new_binds]
                    return [_rp(x) for x in e]

                resolved = [_rp(a) for a in expr[2:]]
                return scope_val(name, *resolved)
            raise TypeError(f"scope target is not callable: {scope_val!r}")

        head_val = self._eval(head, env, axiom_scope, restricted)

        # Lazy: if head is not callable, try rewrite before evaluating args
        if not callable(head_val):
            # Bang: force-eval any (strict ...) args before rewrite
            lazy_args = []
            for arg in expr[1:]:
                if isinstance(arg, list) and arg and arg[0] == STRICT:
                    lazy_args.append(self._eval(arg[1], env, axiom_scope, restricted))
                else:
                    lazy_args.append(arg)
            formal_expr = [head_val] + lazy_args
            rewritten = self._rewrite(formal_expr, axiom_scope=axiom_scope)
            if rewritten != formal_expr:
                # Only re-eval if the head changed (avoids infinite recursion)
                new_head = rewritten[0] if isinstance(rewritten, list) and rewritten else rewritten
                if new_head != head_val:
                    log.debug("_eval lazy rewrite %r -> %r", formal_expr, rewritten)
                    return self._eval(rewritten, env, axiom_scope, restricted)
            # No rewrite or same head — evaluate args and return as formal result
            args = [self._eval(arg, env, axiom_scope, restricted) for arg in expr[1:]]
            log.debug("_eval formal result=%r", [head_val] + args)
            return [head_val] + args

        args = [self._eval(arg, env, axiom_scope, restricted) for arg in expr[1:]]
        log.debug("_eval head_val=%r callable=%s args=%r", head_val, callable(head_val), args)

        result = head_val(*args)
        log.debug("_eval callable result=%r", result)
        # For equality: if direct comparison fails on formal (list) args,
        # try axiom rewriting — e.g. commutativity can't be checked structurally
        if result is False and head == EQ and any(isinstance(a, list) for a in args):
            left_rw = self._rewrite(args[0], axiom_scope=axiom_scope)
            right_rw = self._rewrite(args[1], axiom_scope=axiom_scope)
            log.debug("_eval EQ rewrite fallback: left_rw=%r right_rw=%r args=%r", left_rw, right_rw, args)
            if left_rw == right_rw or left_rw == args[1] or right_rw == args[0]:
                return True
        return result

    # ----------------------------------------------------------
    # Validation
    # ----------------------------------------------------------

    def _check_wff(self, expr):
        """Check that an expression is well-formed in the current system."""
        if isinstance(expr, Symbol):
            if expr in self.env or str(expr) in self.terms:
                return
            if expr in SPECIAL_FORMS:
                return
            if len(expr) == 1 and expr.isalpha():
                return
            if expr.startswith("?"):
                return
            raise NameError(f"Symbol '{expr}' not in current system. Introduce it first.")
        if isinstance(expr, list):
            for sub in expr:
                self._check_wff(sub)

    def _check_consistency(self, new_wff):
        """Check that adding this WFF doesn't create contradiction."""
        try:
            result = self.evaluate(new_wff)
            for name, ax in self.axioms.items():
                try:
                    existing = self.evaluate(ax.wff)
                    if isinstance(result, bool) and isinstance(existing, bool):
                        if to_sexp(new_wff) == to_sexp(ax.wff) and result != existing:
                            raise ValueError(f"Contradiction: new axiom contradicts '{name}'")
                except (NameError, TypeError):
                    continue
        except (NameError, TypeError):
            pass

    def _register_if_definition(self, name: str, wff):
        """If the axiom defines a value, register it."""
        if isinstance(wff, list) and len(wff) == 3 and wff[0] == EQ and isinstance(wff[1], Symbol):
            try:
                val = self.evaluate(wff[2])
                self.env[wff[1]] = val
            except (NameError, TypeError):
                pass

    # ----------------------------------------------------------
    # Derivation
    # ----------------------------------------------------------

    def _check_sources_grounded(self, using: list[str]) -> list[str]:
        """Check if any source in `:using` has unverified evidence.

        Returns list of ungrounded source names.
        """
        ungrounded = []
        for src_name in using:
            origin = None
            if src_name in self.facts:
                origin = self.facts[src_name].origin
            if src_name in self.axioms:
                origin = self.axioms[src_name].origin
            if src_name in self.theorems:
                origin = self.theorems[src_name].origin
            if src_name in self.terms:
                origin = self.terms[src_name].origin

            if isinstance(origin, Evidence) and not origin.is_grounded:
                ungrounded.append(src_name)
            # If origin is "potential fabrication" string from a prior derive
            if isinstance(origin, str) and "potential fabrication" in origin:
                ungrounded.append(src_name)

        return ungrounded

    @staticmethod
    def _expr_symbols(expr) -> set[str]:
        """Extract all non-?-prefixed symbol names from an expression."""
        if isinstance(expr, Symbol) and not str(expr).startswith("?"):
            return {str(expr)}
        if isinstance(expr, list):
            result: set[str] = set()
            for sub in expr:
                result |= Engine._expr_symbols(sub)
            return result
        return set()

    def _expand_using(self, using: list[str]) -> list[str]:
        """Transitively expand :using by pulling in symbols referenced by axioms/terms."""
        resolved: set[str] = set()
        pending = set(using)
        while pending:
            name = pending.pop()
            if name in resolved:
                continue
            resolved.add(name)
            # Collect symbols from axiom/theorem WFFs
            if name in self.axioms:
                deps = self._expr_symbols(self.axioms[name].wff)
                pending |= deps - resolved
            if name in self.theorems:
                deps = self._expr_symbols(self.theorems[name].wff)
                pending |= deps - resolved
            # Collect symbols from term definitions
            if name in self.terms and self.terms[name].definition is not None:
                deps = self._expr_symbols(self.terms[name].definition)
                pending |= deps - resolved
        return list(resolved)

    def _build_restricted_env(self, using: list[str]) -> dict:
        """Build an evaluation environment restricted to :using sources.

        Transitively expands :using — symbols referenced in axiom WFFs
        and term definitions are automatically included.
        """
        expanded = self._expand_using(using)
        log.debug("_build_restricted_env: %r expanded to %r", using, expanded)
        env: dict = {}
        # Include callable operators (arithmetic, comparison, logic)
        for sym, val in self.env.items():
            if callable(val):
                env[sym] = val
        for src_name in expanded:
            if src_name in self.facts:
                env[Symbol(src_name)] = self.facts[src_name].wff
            elif src_name in self.terms:
                term = self.terms[src_name]
                if term.definition is not None:
                    try:
                        env[Symbol(src_name)] = self.evaluate(term.definition)
                    except (NameError, TypeError):
                        env[Symbol(src_name)] = Symbol(src_name)
                else:
                    # Forward-declared: resolve to own symbol for rewriting
                    env[Symbol(src_name)] = Symbol(src_name)
            elif src_name in self.theorems:
                env[Symbol(src_name)] = self.evaluate(self.theorems[src_name].wff)
        return env

    def _collect_using_rules(self, using: list[str]) -> list[Axiom | Theorem]:
        """Collect axiom/theorem objects from :using (expanded transitively)."""
        expanded = self._expand_using(using)
        rules: list[Axiom | Theorem] = []
        for src_name in expanded:
            if src_name in self.axioms:
                rules.append(self.axioms[src_name])
            if src_name in self.theorems:
                rules.append(self.theorems[src_name])
        return rules

    def derive(self, name: str, wff, using: list[str]) -> Theorem:
        """Derive a theorem from existing axioms/terms.

        Evaluation is restricted to facts/terms listed in :using.
        Axiom rewrite rules are scoped to axioms/theorems in :using.
        If any source has unverified evidence, the theorem is
        marked as 'potential fabrication' with a trace to the unverified sources.
        """
        from .lang import parse

        if isinstance(wff, str):
            wff = parse(wff)

        for ax_name in using:
            if (
                ax_name not in self.axioms
                and ax_name not in self.facts
                and ax_name not in self.terms
                and ax_name not in self.theorems
            ):
                raise ValueError(f"Unknown axiom, fact, term, or theorem: {ax_name}")

        # Evaluate: restricted (strict) or global (legacy) mode
        if self.strict_derive:
            restricted_env = self._build_restricted_env(using)
            axiom_scope = self._collect_using_rules(using)
            try:
                result = self._eval(wff, restricted_env, axiom_scope=axiom_scope, restricted=True)
            except NameError as e:
                raise NameError(f"Derivation '{name}' references symbols not in :using: {e}") from e
        else:
            result = self.evaluate(wff)
        does_not_hold = result is False or result is None

        if does_not_hold:
            log.warning("Derivation '%s' does not hold: %s evaluated to False", name, to_sexp(wff))

        # Check fabrication propagation
        ungrounded = self._check_sources_grounded(using)
        issues = []
        if does_not_hold:
            issues.append("does not hold (evaluated to False)")
        if ungrounded:
            issues.append(f"derived from unverified: {', '.join(ungrounded)}")
            log.warning(
                "Derivation '%s' marked as potential fabrication (unverified sources: %s)",
                name,
                ", ".join(ungrounded),
            )

        if issues:
            origin = f"potential fabrication — {'; '.join(issues)}"
        else:
            origin = "derived"

        thm = Theorem(name=name, wff=wff, derivation=using, origin=origin)
        self.theorems[name] = thm
        return thm

    # ----------------------------------------------------------
    # Diff
    # ----------------------------------------------------------

    @staticmethod
    def _expr_references(expr, name: str) -> bool:
        """Check if an expression tree contains a Symbol matching name."""
        if isinstance(expr, Symbol):
            return str(expr) == name
        if isinstance(expr, list):
            return any(Engine._expr_references(sub, name) for sub in expr)
        return False

    def _dependents(self, symbol_name: str, exclude_diff: str | None = None) -> list[tuple[str, str]]:
        """Find all definitions that transitively reference a symbol.

        Returns a list of (name, kind) tuples where kind is one of
        'term', 'fact', 'axiom', 'theorem', or 'diff'.

        Args:
            exclude_diff: diff name to exclude (the calling diff itself).
        """
        references = self._expr_references

        def _all_named_exprs():
            for n, t in self.terms.items():
                yield n, "term", t.definition
            for n, f in self.facts.items():
                yield n, "fact", f.wff
            for n, a in self.axioms.items():
                yield n, "axiom", a.wff
            for n, th in self.theorems.items():
                yield n, "theorem", th.wff
            for n, d in self.diffs.items():
                if n != exclude_diff:
                    yield n, "diff", [Symbol(d["replace"]), Symbol(d["with"])]

        def _mentions(name_to_find, n, kind, expr):
            """Check if a definition mentions name_to_find — via expression
            symbols OR via the theorem's derivation (`:using`) list.

            Theorems whose WFF was evaluated to a literal at derive-time
            no longer contain Symbol references, but their .derivation
            records the names they depended on.
            """
            if references(expr, name_to_find):
                return True
            if kind == "theorem" and name_to_find in self.theorems[n].derivation:
                return True
            return False

        direct: set[tuple[str, str]] = set()
        for n, kind, expr in _all_named_exprs():
            if _mentions(symbol_name, n, kind, expr):
                direct.add((n, kind))

        result: set[tuple[str, str]] = set()
        frontier = direct
        while frontier:
            result |= frontier
            frontier_names = {n for n, _ in frontier}
            next_frontier: set[tuple[str, str]] = set()
            for n, kind, expr in _all_named_exprs():
                if (n, kind) not in result and any(_mentions(fn, n, kind, expr) for fn in frontier_names):
                    next_frontier.add((n, kind))
            frontier = next_frontier
        return list(result)

    def register_diff(self, name: str, replace: str, with_: str):
        """Register a diff — a lazy comparison between two symbols.

        Stores only the parameters. The result is computed fresh on
        every call to eval_diff() or consistency().
        """
        self.diffs[name] = {"replace": replace, "with": with_}
        self.diff_refs.setdefault(replace, set()).add(name)
        self.diff_refs.setdefault(with_, set()).add(name)
        log.debug("Diff registered '%s': %s vs %s", name, replace, with_)

    def _resolve_value(self, name: str):
        """Resolve a symbol to its value (evaluated) or definition (formal)."""
        if Symbol(name) in self.env:
            return self.env[Symbol(name)]
        if name in self.terms:
            defn = self.terms[name].definition
            if defn is None:
                return Symbol(name)
            try:
                return self.evaluate(defn)
            except (NameError, TypeError):
                return defn
        if name in self.facts:
            return self.facts[name].wff
        if name in self.theorems:
            try:
                return self.evaluate(self.theorems[name].wff)
            except (NameError, TypeError):
                return self.theorems[name].wff
        if name in self.axioms:
            return self.axioms[name].wff
        raise KeyError(f"Unknown symbol: {name}")

    def eval_diff(self, name: str) -> DiffResult:
        """Evaluate a registered diff against current system state.

        Transitively scans dependencies via _dependents, following not
        just direct references but also theorem derivation chains.
        Excludes itself from its own dependency scan to avoid circular
        self-contamination.  Dependent diffs that reference the replaced
        symbol are flagged as contaminated.  Theorems whose derivation
        chain used the replaced symbol — even when their WFF is a literal
        — are flagged as contaminated.
        """
        if name not in self.diffs:
            raise KeyError(f"Unknown diff: {name}")

        params = self.diffs[name]
        replace = params["replace"]
        with_ = params["with"]

        original = self._resolve_value(replace)
        substitute_val = self._resolve_value(with_)

        affected = self._dependents(replace, exclude_diff=name)

        divergences = {}
        for dep_name, dep_kind in affected:
            if dep_kind == "term":
                defn = self.terms[dep_name].definition
            elif dep_kind == "fact":
                defn = self.facts[dep_name].wff
            elif dep_kind == "axiom":
                defn = self.axioms[dep_name].wff
            elif dep_kind == "theorem":
                defn = self.theorems[dep_name].wff
            elif dep_kind == "diff":
                # The dependent diff references the replaced symbol
                # in its :replace or :with — flag as contaminated.
                dep_params = self.diffs[dep_name]
                divergences[dep_name] = [
                    f"diff({dep_params['replace']} vs {dep_params['with']})",
                    f"<contaminated: references {replace}>",
                ]
                continue
            else:
                continue

            # For theorems found via .derivation whose WFF is already
            # evaluated to a literal: substitution into the WFF won't
            # change anything, but the derivation *used* the replaced
            # symbol so the result is contaminated.  Flag as divergent
            # since re-derivation with different input could change
            # the outcome.
            if (
                dep_kind == "theorem"
                and not self._expr_references(defn, replace)
                and replace in self.theorems[dep_name].derivation
            ):
                divergences[dep_name] = [defn, f"<contaminated: uses {replace}>"]
                continue

            try:
                result_a = self.evaluate(defn)
                result_b = self.evaluate(defn, {Symbol(replace): substitute_val})
            except (NameError, TypeError):
                # Formal expressions — compare structurally via substitution
                result_a = defn
                result_b = substitute(defn, {Symbol(replace): substitute_val})
            if result_a != result_b:
                divergences[dep_name] = [result_a, result_b]

        return DiffResult(
            name=name,
            replace=replace,
            with_=with_,
            value_a=original,
            value_b=substitute_val,
            divergences=divergences,
        )

    # ----------------------------------------------------------
    # Retract / Rederive
    # ----------------------------------------------------------

    def retract(self, name: str):
        """Remove a fact, axiom, term, theorem, or diff from the system."""
        removed = False
        if name in self.facts:
            del self.facts[name]
            removed = True
        if name in self.axioms:
            del self.axioms[name]
            removed = True
        if name in self.theorems:
            del self.theorems[name]
            removed = True
        if name in self.terms:
            del self.terms[name]
            removed = True
        if name in self.diffs:
            params = self.diffs[name]
            for ref in (params["replace"], params["with"]):
                if ref in self.diff_refs:
                    self.diff_refs[ref].discard(name)
                    if not self.diff_refs[ref]:
                        del self.diff_refs[ref]
            del self.diffs[name]
            removed = True
        if Symbol(name) in self.env:
            del self.env[Symbol(name)]
        if not removed:
            raise KeyError(f"Unknown: {name}")
        log.info("'%s' retracted from system", name)

    def rederive(self, name: str):
        """Re-run a derivation to refresh its fabrication status.

        Useful after overriding evidence on a source that was previously
        flagged, which made derived theorems stale.
        """
        if name not in self.theorems:
            raise KeyError(f"Unknown theorem: {name}")
        thm = self.theorems[name]

        # Re-derive: re-check sources and replace with updated origin
        ungrounded = self._check_sources_grounded(thm.derivation)
        if ungrounded:
            new_origin = f"potential fabrication — derived from unverified: {', '.join(ungrounded)}"
            log.warning("Rederive '%s': still has unverified sources: %s", name, ", ".join(ungrounded))
        else:
            new_origin = "derived"
            log.info("Rederive '%s': sources now verified — cleared", name)
        self.theorems[name] = replace(thm, origin=new_origin)

    # ----------------------------------------------------------
    # Consistency
    # ----------------------------------------------------------

    def _check_evidence(self) -> tuple[list[ConsistencyIssue], list[ConsistencyWarning]]:
        """Check evidence grounding and fabrication propagation."""
        issues: list[ConsistencyIssue] = []
        warnings: list[ConsistencyWarning] = []

        # 1. Evidence grounding
        unverified = []
        manually_verified = []
        no_evidence = []
        for store in [self.facts, self.axioms, self.theorems, self.terms]:
            for name, item in store.items():  # type: ignore[attr-defined]
                origin = item.origin
                if isinstance(origin, Evidence):
                    if not origin.verified and origin.verify_manual:
                        manually_verified.append(name)
                    elif not origin.is_grounded:
                        unverified.append((name, origin.quotes))
                elif isinstance(origin, str):
                    if (
                        origin not in ("unknown", "derived")
                        and not origin.startswith("diff ")
                        and "potential fabrication" not in origin
                    ):
                        no_evidence.append((name, origin))

        if unverified:
            issues.append(ConsistencyIssue(IssueType.UNVERIFIED_EVIDENCE, sorted(unverified, key=lambda x: x[0])))
        if no_evidence:
            issues.append(ConsistencyIssue(IssueType.NO_EVIDENCE, sorted(no_evidence, key=lambda x: x[0])))
        if manually_verified:
            manual_details = {}
            for name in manually_verified:
                stores: list[dict] = [self.facts, self.axioms, self.theorems, self.terms]
                for store in stores:
                    if name in store:
                        origin = store[name].origin
                        if isinstance(origin, Evidence):
                            manual_details[name] = (
                                f"document={origin.document}, "
                                f"quotes={origin.quotes}, "
                                f"explanation={origin.explanation}"
                            )
                        elif origin:
                            manual_details[name] = str(origin)
                        else:
                            manual_details[name] = "no origin provided"
                        break
                else:
                    manual_details[name] = "no origin provided"
            warnings.append(
                ConsistencyWarning(WarningType.MANUALLY_VERIFIED, sorted(manually_verified), manual_details)
            )

        # 2. Fabrication propagation
        fabrications = sorted(
            name
            for name, thm in self.theorems.items()
            if isinstance(thm.origin, str) and "potential fabrication" in thm.origin
        )
        if fabrications:
            issues.append(ConsistencyIssue(IssueType.POTENTIAL_FABRICATION, fabrications))

        return issues, warnings

    def _check_diffs(
        self, diff_names: set[str] | None = None
    ) -> tuple[list[ConsistencyIssue], list[ConsistencyWarning]]:
        """Evaluate diffs and return issues/warnings.

        If diff_names is given, only those diffs are evaluated.
        If None, all diffs are evaluated.
        """
        issues: list[ConsistencyIssue] = []
        warnings: list[ConsistencyWarning] = []

        names = diff_names if diff_names is not None else set(self.diffs)
        all_diffs = sorted((self.eval_diff(n) for n in names), key=lambda d: d.name)
        downstream_divergent = [d for d in all_diffs if not d.empty and not d.diff_contamination_only]
        diff_contamination = [d for d in all_diffs if d.diff_contamination_only]
        value_divergent = [d for d in all_diffs if d.values_diverge and d.empty]
        if downstream_divergent:
            issues.append(ConsistencyIssue(IssueType.DIFF_DIVERGENCE, downstream_divergent))
        if value_divergent:
            issues.append(ConsistencyIssue(IssueType.DIFF_VALUE_DIVERGENCE, value_divergent))
        if diff_contamination:
            contam_details = {}
            for d in diff_contamination:
                contam_details[d.name] = "; ".join(f"{k}: {v[1]}" for k, v in sorted(d.divergences.items()))
            warnings.append(
                ConsistencyWarning(WarningType.DIFF_CONTAMINATION, [d.name for d in diff_contamination], contam_details)
            )

        return issues, warnings

    def consistency(self, suppress_log: bool = True) -> ConsistencyReport:
        """Check full consistency state of the system.

        Checks three layers:
          1. Evidence grounding — are all quotes verified?
          2. Fabrication propagation — any derived axioms tainted?
          3. Diff agreement — do cross-checked values agree?
        """
        issues, warnings = self._check_evidence()
        diff_issues, diff_warnings = self._check_diffs()
        issues.extend(diff_issues)
        warnings.extend(diff_warnings)

        report = ConsistencyReport(
            consistent=len(issues) == 0,
            issues=issues,
            warnings=warnings,
        )

        if not suppress_log:
            log.info("%s", report) if report.consistent else log.warning("%s", report)
        return report

    # ----------------------------------------------------------
    # Axiom / Term / Fact introduction (engine-level)
    # ----------------------------------------------------------

    def introduce_axiom(self, name: str, wff, origin) -> Axiom:
        """Introduce a new axiom. Validates WFF and checks consistency."""
        from .lang import parse

        if isinstance(wff, str):
            wff = parse(wff)

        if isinstance(origin, Evidence):
            origin = self._verify_evidence(origin, caller=name)

        if not free_vars(wff):
            raise ValueError(
                f"Axiom '{name}' has no ?-variables — it is a ground statement. "
                f"Use (fact ...) for ground values or (derive ...) for provable claims."
            )

        self._check_wff(wff)
        self._check_consistency(wff)

        ax = Axiom(name=name, wff=wff, origin=origin)
        self.axioms[name] = ax
        self._register_if_definition(name, wff)
        return ax

    def introduce_term(self, name: str, definition, origin) -> Term:
        """Introduce a new term/concept."""
        from .lang import parse

        if isinstance(definition, str):
            definition = parse(definition)

        if isinstance(origin, Evidence):
            origin = self._verify_evidence(origin, caller=name)

        term = Term(name=name, definition=definition, origin=origin)
        self.terms[name] = term
        return term

    def set_fact(self, name: str, value: Any, origin):
        """Set a ground truth value with evidence."""
        if isinstance(origin, Evidence):
            origin = self._verify_evidence(origin, caller=name)

        if name in self.facts:
            if not self.overridable:
                raise ValueError(
                    f"Fact '{name}' already exists. Use retract() first, or create System(overridable=True)"
                )
            log.info("Overwriting fact '%s': %s → %s", name, self.facts[name].wff, value)

        self.facts[name] = Fact(name=name, wff=value, origin=origin)
        self.env[Symbol(name)] = value

    def instantiate(self, name: str, bindings: dict):
        """Look up a parameterized axiom or term, substitute ?-vars, return concrete expression."""
        if name in self.axioms:
            template = self.axioms[name].wff
        elif name in self.theorems:
            template = self.theorems[name].wff
        elif name in self.terms:
            template = self.terms[name].definition
        else:
            raise KeyError(f"Unknown axiom, theorem, or term: {name}")

        return substitute(template, bindings)


# ============================================================
# DSL Loader
# ============================================================


def load_source(engine: Engine, source: str):
    tokens = tokenize(source)
    while tokens:
        expr = read_tokens(tokens)
        _execute_directive(engine, expr)


def _resolve_origin(expr) -> "str | Evidence":
    evidence_raw = get_keyword(expr, KW_EVIDENCE, None)
    if evidence_raw is not None:
        return parse_evidence(evidence_raw)
    return get_keyword(expr, KW_ORIGIN, "unknown")


def _parse_bindings(bind_raw):
    bindings = {}
    for pair in bind_raw:
        if not isinstance(pair, list) or len(pair) < 2:
            log.warning("Skipping malformed bind pair: %s", pair)
            continue
        bindings[pair[0]] = pair[1]
    return bindings


def _execute_directive(engine: Engine, expr):
    if not isinstance(expr, list) or not expr:
        return

    head = expr[0]

    if head == AXIOM:
        name = str(expr[1])
        bind_raw = get_keyword(expr, KW_BIND, None)
        if bind_raw is not None:
            ref = str(expr[2])
            bindings = _parse_bindings(bind_raw)
            wff = engine.instantiate(ref, bindings)
        else:
            wff = expr[2]
        engine.introduce_axiom(name, wff, _resolve_origin(expr))

    elif head == DEFTERM:
        name = str(expr[1])
        bind_raw = get_keyword(expr, KW_BIND, None)
        if bind_raw is not None:
            ref = str(expr[2])
            bindings = _parse_bindings(bind_raw)
            defn = engine.instantiate(ref, bindings)
        elif len(expr) < 3 or (isinstance(expr[2], str) and expr[2].startswith(":")):
            defn = None
        else:
            defn = expr[2]
        engine.introduce_term(name, defn, _resolve_origin(expr))

    elif head == FACT:
        engine.set_fact(str(expr[1]), expr[2], _resolve_origin(expr))

    elif head == DERIVE:
        name = str(expr[1])
        using = get_keyword(expr, KW_USING, [])
        if isinstance(using, list):
            using = [str(s) for s in using]
        bind_raw = get_keyword(expr, KW_BIND, None)
        if bind_raw is not None:
            ref = str(expr[2])
            bindings = _parse_bindings(bind_raw)
            if not bindings:
                log.warning("Empty :bind in derive '%s' — expanding axiom '%s' directly", name, ref)
                wff = engine.axioms[ref].wff if ref in engine.axioms else expr[2]
            else:
                wff = engine.instantiate(ref, bindings)
        else:
            wff = expr[2]
            if isinstance(wff, Symbol) and str(wff) in engine.axioms:
                axiom_name = str(wff)
                log.warning("Derive '%s' used axiom name '%s' as WFF — auto-expanding", name, axiom_name)
                wff = engine.axioms[axiom_name].wff
            # Check: non-rewrite axioms in :using without :bind is an error.
            # Rewrite-eligible axioms have form (= <list-pattern> <rhs>) and fire
            # automatically during evaluation. All other axioms (implies, etc.)
            # can only be used via :bind.
            for u in using:
                if u in engine.axioms:
                    ax = engine.axioms[u]
                    w = ax.wff
                    is_rewrite = isinstance(w, list) and len(w) == 3 and w[0] == EQ and isinstance(w[1], list)
                    if not is_rewrite:
                        ax_vars = free_vars(w)
                        raise ValueError(
                            f"Derive '{name}' references axiom '{u}' in :using without :bind. "
                            f"Axiom has ?-variables {{{', '.join(str(v) for v in ax_vars)}}} "
                            f"that must be bound via :bind. "
                            f"(Rewrite-rule axioms with form (= <pattern> <rhs>) are allowed "
                            f"in :using without :bind.)"
                        )
        engine.derive(name, wff, using)

    elif head == DIFF:
        engine.register_diff(str(expr[1]), str(get_keyword(expr, KW_REPLACE)), str(get_keyword(expr, KW_WITH)))

    else:
        engine.evaluate(expr)
