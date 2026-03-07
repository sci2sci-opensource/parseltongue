"""
Parseltongue Engine — evaluation core.

Accepts an env dict and provides: evaluation, rewriting, derivation,
diffs, consistency checking, document management, evidence verification,
and DSL loading.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from .atoms import Evidence, Symbol, free_vars, match, substitute
from .lang import (
    AXIOM,
    DEFTERM,
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
    QUOTE,
    SPECIAL_FORMS,
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
# Result Types
# ============================================================


@dataclass
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

    type: str
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
            "unverified_evidence": "Unverified evidence",
            "no_evidence": "No evidence provided",
            "potential_fabrication": "Potential fabrication",
            "diff_divergence": "Diff divergence",
            "diff_value_divergence": "Diff value divergence",
        }
        label = labels.get(self.type, self.type)
        parts = [f"{label}:"]
        if self.type in ("diff_divergence", "diff_value_divergence"):
            for d in self.items:
                for i, line in enumerate(str(d).splitlines()):
                    parts.append(f"    {line}" if i else f"  {line}")
        elif self.type == "no_evidence":
            for item in self.items:
                if isinstance(item, tuple):
                    name, origin = item
                    parts.append(f"  {name} (origin: {origin})")
                else:
                    parts.append(f"  {item}")
        else:
            for item in self.items:
                parts.append(f"  {item}")
        return "\n".join(parts)


@dataclass
class ConsistencyWarning:
    """A single consistency warning."""

    type: str
    items: list[str]

    def to_dict(self) -> dict:
        from .serialization import serialize_consistency_warning

        return serialize_consistency_warning(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConsistencyWarning":
        from .serialization import deserialize_consistency_warning

        return deserialize_consistency_warning(data)

    def __str__(self):
        if self.type == "manually_verified":
            return f"Manually verified: {', '.join(self.items)}"
        return f"{self.type}: {', '.join(self.items)}"


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


# ============================================================
# Engine
# ============================================================


class Engine:
    """Pure evaluation engine with document management. No serialization."""

    def __init__(self, env: dict, overridable: bool = False, strict_derive: bool = True):
        self.axioms: dict[str, Axiom] = {}
        self.theorems: dict[str, Theorem] = {}
        self.terms: dict[str, Term] = {}
        self.facts: dict[str, Fact] = {}
        self.env: dict = dict(env)
        self.diffs: dict[str, dict] = {}
        self.documents: dict[str, str] = {}
        self._verifier = QuoteVerifier()
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

    def _verify_evidence(self, evidence: Evidence) -> Evidence:
        if evidence.document not in self.documents:
            log.warning("Document '%s' not registered — skipping verification", evidence.document)
            return evidence

        results = self._verifier.verify_indexed_quotes(evidence.document, evidence.quotes)
        evidence.verification = results

        all_verified = True
        for r in results:
            if r["verified"]:
                conf = r.get("confidence", {})
                log.info('Quote verified: "%s" (confidence: %s)', r["quote"], conf.get("level", "?"))
            else:
                all_verified = False
                reason = r.get("reason", "unknown")
                log.warning('Quote NOT verified: "%s" (%s)', r["quote"], reason)

        evidence.verified = all_verified
        return evidence

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
            origin.verify_manual = True
        else:
            item.origin = Evidence(
                document="manual",
                quotes=[],
                explanation=origin if isinstance(origin, str) else str(origin),
                verify_manual=True,
            )

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

        head_val = self._eval(head, env, axiom_scope, restricted)
        args = [self._eval(arg, env, axiom_scope, restricted) for arg in expr[1:]]
        log.debug("_eval head_val=%r callable=%s args=%r", head_val, callable(head_val), args)

        if callable(head_val):
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

        # Formal: rewrite then re-evaluate if the head becomes callable
        formal_expr = [head_val] + args
        rewritten = self._rewrite(formal_expr, axiom_scope=axiom_scope)
        if rewritten != formal_expr and isinstance(rewritten, list) and rewritten:
            new_head = rewritten[0]
            # Resolve head symbol if needed
            if isinstance(new_head, Symbol) and new_head in env:
                new_head = env[new_head]
            if callable(new_head):
                log.debug("_eval formal rewrite %r -> %r, re-evaluating", formal_expr, rewritten)
                return self._eval(rewritten, env, axiom_scope, restricted)
        log.debug("_eval formal result=%r", rewritten)
        return rewritten

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

    def _dependents(self, symbol_name: str) -> list[str]:
        """Find all terms whose definitions transitively reference a symbol."""

        def references(expr, name):
            if isinstance(expr, Symbol):
                return str(expr) == name
            if isinstance(expr, list):
                return any(references(sub, name) for sub in expr)
            return False

        direct = {n for n, t in self.terms.items() if references(t.definition, symbol_name)}
        result = set()
        frontier = direct
        while frontier:
            result |= frontier
            frontier = {
                n
                for n, t in self.terms.items()
                if n not in result and any(references(t.definition, r) for r in frontier)
            }
        return list(result)

    def register_diff(self, name: str, replace: str, with_: str):
        """Register a diff — a lazy comparison between two symbols.

        Stores only the parameters. The result is computed fresh on
        every call to eval_diff() or consistency().
        """
        self.diffs[name] = {"replace": replace, "with": with_}
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
        """Evaluate a registered diff against current system state."""
        if name not in self.diffs:
            raise KeyError(f"Unknown diff: {name}")

        params = self.diffs[name]
        replace = params["replace"]
        with_ = params["with"]

        original = self._resolve_value(replace)
        substitute_val = self._resolve_value(with_)

        affected = self._dependents(replace)

        divergences = {}
        for term_name in affected:
            defn = self.terms[term_name].definition
            try:
                result_a = self.evaluate(defn)
                result_b = self.evaluate(defn, {Symbol(replace): substitute_val})
            except (NameError, TypeError):
                # Formal terms — compare structurally via substitution
                result_a = defn
                result_b = substitute(defn, {Symbol(replace): substitute_val})
            if result_a != result_b:
                divergences[term_name] = [result_a, result_b]

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

        # Re-derive: re-check sources and update origin
        ungrounded = self._check_sources_grounded(thm.derivation)
        if ungrounded:
            thm.origin = f"potential fabrication — derived from unverified: {', '.join(ungrounded)}"
            log.warning("Rederive '%s': still has unverified sources: %s", name, ", ".join(ungrounded))
        else:
            thm.origin = "derived"
            log.info("Rederive '%s': sources now verified — cleared", name)

    # ----------------------------------------------------------
    # Consistency
    # ----------------------------------------------------------

    def consistency(self) -> ConsistencyReport:
        """Check full consistency state of the system.

        Checks three layers:
          1. Evidence grounding — are all quotes verified?
          2. Fabrication propagation — any derived axioms tainted?
          3. Diff agreement — do cross-checked values agree?
        """
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
                        unverified.append(name)
                elif isinstance(origin, str):
                    if (
                        origin not in ("unknown", "derived")
                        and not origin.startswith("diff ")
                        and "potential fabrication" not in origin
                    ):
                        no_evidence.append((name, origin))

        if unverified:
            issues.append(ConsistencyIssue("unverified_evidence", sorted(unverified)))
        if no_evidence:
            issues.append(ConsistencyIssue("no_evidence", sorted(no_evidence, key=lambda x: x[0])))
        if manually_verified:
            warnings.append(ConsistencyWarning("manually_verified", sorted(manually_verified)))

        # 2. Fabrication propagation
        fabrications = sorted(
            name
            for name, thm in self.theorems.items()
            if isinstance(thm.origin, str) and "potential fabrication" in thm.origin
        )
        if fabrications:
            issues.append(ConsistencyIssue("potential_fabrication", fabrications))

        # 3. Diff divergences — evaluated live
        all_diffs = sorted((self.eval_diff(n) for n in self.diffs), key=lambda d: d.name)
        downstream_divergent = [d for d in all_diffs if not d.empty]
        value_divergent = [d for d in all_diffs if d.values_diverge and d.empty]
        if downstream_divergent:
            issues.append(ConsistencyIssue("diff_divergence", downstream_divergent))
        if value_divergent:
            issues.append(ConsistencyIssue("diff_value_divergence", value_divergent))

        report = ConsistencyReport(
            consistent=len(issues) == 0,
            issues=issues,
            warnings=warnings,
        )

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
            self._verify_evidence(origin)

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
            self._verify_evidence(origin)

        term = Term(name=name, definition=definition, origin=origin)
        self.terms[name] = term
        return term

    def set_fact(self, name: str, value: Any, origin):
        """Set a ground truth value with evidence."""
        if isinstance(origin, Evidence):
            self._verify_evidence(origin)

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
