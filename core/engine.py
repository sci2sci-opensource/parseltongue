"""
Parseltongue DSL — Runtime Engine.

Stateful system: evaluation, axiom store, document registry,
quote verification, derivation with fabrication propagation.

Building a System — Step by Step
---------------------------------

1. Create a System::

    s = System()                          # default operators loaded
    s = System(initial_env={})            # empty — introduce everything yourself
    s = System(overridable=True)          # allow fact overwriting

2. Register source documents for quote verification::

    s.load_document("Q3 Report", "path/to/q3_report.txt")
    s.register_document("Notes", "inline text...")

3. Build statements via load_source() — five directives:

  fact — ground truth value::

    (fact revenue-q3 15.0
        :evidence (evidence "Q3 Report"
          :quotes ("Q3 revenue was $15M")
          :explanation "Dollar revenue figure from Q3 report"))

  defterm — named concept (forward declaration, computed, or conditional)::

    ;; Forward declaration (primitive symbol)
    (defterm zero
        :evidence (evidence "Counting Observations"
          :quotes ("An empty basket contains zero apples")
          :explanation "Zero: the count of an empty collection"))

    ;; Computed expression
    (defterm morning-total (+ eve-morning adam-morning)
        :evidence (evidence "Eden Inventory"
          :quotes ("Combined morning harvest was 8 apples")
          :explanation "Sum of Eve and Adam's morning picks"))

    ;; Conditional
    (defterm bonus-amount
        (if (> revenue-q3-growth growth-target)
            (* base-salary bonus-rate)
            0)
        :evidence (evidence "Bonus Policy Doc"
          :quotes ("Bonus is 20% of base salary if growth target is exceeded")
          :explanation "Bonus calculation formula"))

  axiom — well-formed formula (may use ?-variables for parameterisation)::

    (axiom add-commutative (= (+ ?a ?b) (+ ?b ?a))
        :evidence (evidence "Counting Observations"
          :quotes ("The order of combining does not matter")
          :explanation "Commutativity: a + b = b + a"))

  derive — theorem from existing statements; use :bind to instantiate::

    ;; Direct derivation
    (derive target-exceeded
        (> revenue-q3-growth growth-target)
        :using (revenue-q3-growth growth-target))

    ;; Instantiate a parameterised axiom via :bind
    (derive morning-commutes add-commutative
        :bind ((?a eve-morning) (?b adam-morning))
        :using (add-commutative))

  diff — lazy what-if comparison::

    (diff growth-check
        :replace revenue-q3-growth
        :with revenue-q3-growth-computed)

4. Inspect the system::

    s.consistency()           # full consistency report
    s.provenance("name")      # trace evidence chain
    s.eval_diff("name")       # evaluate a diff
    s.doc()                   # generated documentation

Key Concepts
~~~~~~~~~~~~~

- **Evidence grounding**: every statement traces back to quoted text from a
  registered source document.  Unverified quotes are flagged, not rejected.
- **Fabrication propagation**: if a derivation depends on unverified evidence,
  the theorem inherits the taint as "potential fabrication".
- **Diff divergence**: register a diff to compare what happens when one
  symbol is swapped for another across all dependent terms.
- **Overridable facts**: System(overridable=True) lets facts be overwritten;
  dependent diffs are recomputed automatically.
"""

from dataclasses import dataclass, field
from typing import Any
import logging
import operator

log = logging.getLogger('parseltongue')

from .atoms import Symbol, match, free_vars, substitute
from .lang import (
    Axiom, Theorem, Term, Evidence,
    parse, tokenize, read_tokens, to_sexp,
    get_keyword, parse_evidence,
    # Special forms
    IF, LET, SPECIAL_FORMS,
    # DSL keywords
    AXIOM, DEFTERM, FACT, DERIVE, DIFF,
    # Keyword arguments
    KW_ORIGIN, KW_EVIDENCE, KW_USING, KW_REPLACE, KW_WITH, KW_BIND,
    # Documentation
    LANG_DOCS,
)
from .quote_verifier import QuoteVerifier


# ============================================================
# Operator Constants (engine-level)
# ============================================================

# Arithmetic
ADD = Symbol('+')
SUB = Symbol('-')
MUL = Symbol('*')
DIV = Symbol('/')
MOD = Symbol('mod')

# Comparison
GT  = Symbol('>')
LT  = Symbol('<')
GE  = Symbol('>=')
LE  = Symbol('<=')
EQ  = Symbol('=')
NE  = Symbol('!=')

# Logic
AND     = Symbol('and')
OR      = Symbol('or')
NOT     = Symbol('not')
IMPLIES = Symbol('implies')

ARITHMETIC_OPS = (ADD, SUB, MUL, DIV, MOD)
COMPARISON_OPS = (GT, LT, GE, LE, EQ, NE)
LOGIC_OPS      = (AND, OR, NOT, IMPLIES)


# ============================================================
# Engine Documentation
# ============================================================

ENGINE_DOCS = {
    # Arithmetic
    ADD: {
        'category': 'arithmetic',
        'description': 'Add two numbers.  Also used symbolically in '
                       'formal terms: (+ eve-morning adam-morning).',
        'example': '(+ 2 3)',
        'expected': 5,
    },
    SUB: {
        'category': 'arithmetic',
        'description': 'Subtract second from first.  Useful for computing '
                       'differences between terms: (- morning-total afternoon-total).',
        'example': '(- 10 4)',
        'expected': 6,
    },
    MUL: {
        'category': 'arithmetic',
        'description': 'Multiply two numbers.  Used in computed terms like '
                       'bonus calculations: (* base-salary bonus-rate).',
        'example': '(* 3 7)',
        'expected': 21,
    },
    DIV: {
        'category': 'arithmetic',
        'description': 'Divide first by second (true division).  Used for '
                       'computing ratios: (/ (- q3 q2) q2).',
        'example': '(/ 10 2)',
        'expected': 5.0,
    },
    MOD: {
        'category': 'arithmetic',
        'description': 'Remainder of first divided by second.',
        'example': '(mod 10 3)',
        'expected': 1,
    },

    # Comparison
    GT: {
        'category': 'comparison',
        'description': 'True if first is strictly greater than second.  '
                       'Common in term definitions: (> sensitivity 90).',
        'example': '(> 5 3)',
        'expected': True,
    },
    LT: {
        'category': 'comparison',
        'description': 'True if first is strictly less than second.',
        'example': '(< 2 8)',
        'expected': True,
    },
    GE: {
        'category': 'comparison',
        'description': 'True if first is greater than or equal to second.',
        'example': '(>= 5 5)',
        'expected': True,
    },
    LE: {
        'category': 'comparison',
        'description': 'True if first is less than or equal to second.',
        'example': '(<= 3 5)',
        'expected': True,
    },
    EQ: {
        'category': 'comparison',
        'description': 'True if both values are equal.  Also the core of '
                       'rewrite rules — axioms of the form (= LHS RHS) are '
                       'applied as left-to-right rewrites during evaluation.',
        'example': '(= 5 5)',
        'expected': True,
    },
    NE: {
        'category': 'comparison',
        'description': 'True if values are not equal.',
        'example': '(!= 5 6)',
        'expected': True,
    },

    # Logic
    AND: {
        'category': 'logic',
        'description': 'Logical AND.  True only if both operands are true.  '
                       'Used in compound conditions: '
                       '(and reliable-marker standalone-diagnostic).',
        'example': '(and true false)',
        'expected': False,
    },
    OR: {
        'category': 'logic',
        'description': 'Logical OR.  True if at least one operand is true.',
        'example': '(or false true)',
        'expected': True,
    },
    NOT: {
        'category': 'logic',
        'description': 'Logical NOT.  Negates a boolean.  Used in derivations: '
                       '(not (> specificity 90)).',
        'example': '(not true)',
        'expected': False,
    },
    IMPLIES: {
        'category': 'logic',
        'description': 'Logical implication.  False only when antecedent '
                       'is true and consequent is false.',
        'example': '(implies true false)',
        'expected': False,
    },
}


# ============================================================
# Default Operator Mapping
# ============================================================

DEFAULT_OPERATORS: dict[Symbol, Any] = {
    # Arithmetic
    ADD: operator.add,
    SUB: operator.sub,
    MUL: operator.mul,
    DIV: operator.truediv,
    MOD: operator.mod,

    # Comparison
    GT:  operator.gt,
    LT:  operator.lt,
    GE:  operator.ge,
    LE:  operator.le,
    EQ:  operator.eq,
    NE:  operator.ne,

    # Logic
    AND:     lambda a, b: a and b,
    OR:      lambda a, b: a or b,
    NOT:     lambda a: not a,
    IMPLIES: lambda a, b: (not a) or b,
}


# ============================================================
# Result Types
# ============================================================

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

    def __str__(self):
        va = to_sexp(self.value_a) if isinstance(self.value_a, (list, Symbol)) else self.value_a
        vb = to_sexp(self.value_b) if isinstance(self.value_b, (list, Symbol)) else self.value_b
        header = f"{self.name}: {self.replace} ({va}) vs {self.with_} ({vb})"
        if self.empty:
            return f"{header} — no divergences"
        lines = [header]
        for term, (a, b) in self.divergences.items():
            a_s = to_sexp(a) if isinstance(a, (list, Symbol)) else a
            b_s = to_sexp(b) if isinstance(b, (list, Symbol)) else b
            lines.append(f"  {term}: {a_s} → {b_s}")
        return '\n'.join(lines)


@dataclass
class ConsistencyIssue:
    """A single consistency issue."""
    type: str
    items: list

    def __str__(self):
        labels = {
            'unverified_evidence': 'Unverified evidence',
            'no_evidence': 'No evidence provided',
            'potential_fabrication': 'Potential fabrication',
            'diff_divergence': 'Diff divergence',
        }
        label = labels.get(self.type, self.type)
        if self.type == 'diff_divergence':
            return '\n'.join(f"  {d}" for d in self.items)
        return f"{label}: {', '.join(str(i) for i in self.items)}"


@dataclass
class ConsistencyWarning:
    """A single consistency warning."""
    type: str
    items: list[str]

    def __str__(self):
        if self.type == 'manually_verified':
            return f"Manually verified: {', '.join(self.items)}"
        return f"{self.type}: {', '.join(self.items)}"


@dataclass
class ConsistencyReport:
    """Full consistency report for the system."""
    consistent: bool
    issues: list[ConsistencyIssue] = field(default_factory=list)
    warnings: list[ConsistencyWarning] = field(default_factory=list)

    def __str__(self):
        if self.consistent and not self.warnings:
            return "System is fully consistent"
        lines = []
        if self.consistent:
            lines.append("System is consistent")
        else:
            lines.append(f"System inconsistent: {len(self.issues)} issue(s)")
            for issue in self.issues:
                lines.append(f"  {issue}")
        for w in self.warnings:
            lines.append(f"  [warning] {w}")
        return '\n'.join(lines)


class System:
    """The Parseltongue formal system. Grows via axiom introduction."""

    def __init__(self, overridable: bool = False,
                 initial_env: dict | None = None):
        self.axioms: dict[str, Axiom] = {}
        self.theorems: dict[str, Theorem] = {}
        self.terms: dict[str, Term] = {}
        self.facts: dict[str, Any] = {}
        self.env: dict[str, Any] = {}
        self.documents: dict[str, str] = {}
        self.overridable = overridable
        self.diffs: dict[str, dict] = {}  # name -> {replace, with} — evaluated lazily
        self._verifier = QuoteVerifier()

        if initial_env is not None:
            self.env.update(initial_env)
        else:
            self.env.update(DEFAULT_OPERATORS)

    # ----------------------------------------------------------
    # Document Registry
    # ----------------------------------------------------------

    def register_document(self, name: str, text: str):
        """Register a source document by name for quote verification."""
        self.documents[name] = text
        self._verifier.index.add(name, text)

    def load_document(self, name: str, path: str):
        """Load a source document from a file path."""
        with open(path) as f:
            text = f.read()
        self.documents[name] = text
        self._verifier.index.add(name, text)

    # ----------------------------------------------------------
    # Quote Verification
    # ----------------------------------------------------------

    def _verify_evidence(self, evidence: Evidence) -> Evidence:
        """Verify all quotes in an Evidence object against the registered document.

        Does NOT reject on failure — flags mismatches via logging.
        Sets evidence.verified and populates evidence.verification.
        """
        if evidence.document not in self.documents:
            log.warning("Document '%s' not registered — skipping verification",
                        evidence.document)
            return evidence

        results = self._verifier.verify_indexed_quotes(
            evidence.document, evidence.quotes)
        evidence.verification = results

        all_verified = True
        for r in results:
            if r['verified']:
                conf = r.get('confidence', {})
                log.info('Quote verified: "%s" (confidence: %s)',
                         r['quote'], conf.get('level', '?'))
            else:
                all_verified = False
                reason = r.get('reason', 'unknown')
                log.warning('Quote NOT verified: "%s" (%s)',
                            r['quote'], reason)

        evidence.verified = all_verified
        return evidence

    def verify_manual(self, name: str):
        """Manually verify evidence for a fact, axiom, or term.

        Use when the LLM paraphrased correctly but didn't quote exactly.
        """
        origin = None
        if name in self.facts:
            origin = self.facts[name].get('origin')
        if name in self.axioms:
            origin = self.axioms[name].origin
        if name in self.theorems:
            origin = self.theorems[name].origin
        if name in self.terms:
            origin = self.terms[name].origin

        if origin is None:
            raise KeyError(f"Unknown: {name}")

        if isinstance(origin, Evidence):
            origin.verify_manual = True
        else:
            # Plain string origin — wrap in Evidence and mark manually verified
            ev = Evidence(
                document="manual",
                quotes=[],
                explanation=origin if isinstance(origin, str) else str(origin),
                verify_manual=True,
            )
            if name in self.facts:
                self.facts[name]['origin'] = ev
            if name in self.axioms:
                self.axioms[name].origin = ev
            if name in self.theorems:
                self.theorems[name].origin = ev
            if name in self.terms:
                self.terms[name].origin = ev

        log.info("'%s' manually marked as grounded", name)

    # ----------------------------------------------------------
    # Axiom Introduction
    # ----------------------------------------------------------

    def introduce_axiom(self, name: str, wff, origin: 'str | Evidence') -> Axiom:
        """Introduce a new axiom from evidence. Extends the system."""
        if isinstance(wff, str):
            wff = parse(wff)

        self._check_wff(wff)
        self._check_consistency(wff)

        if isinstance(origin, Evidence):
            self._verify_evidence(origin)

        ax = Axiom(name=name, wff=wff, origin=origin)
        self.axioms[name] = ax
        self._register_if_definition(name, wff)
        return ax

    def introduce_term(self, name: str, definition, origin: 'str | Evidence') -> Term:
        """Introduce a new term/concept. Extends the grammar."""
        if isinstance(definition, str):
            definition = parse(definition)

        if isinstance(origin, Evidence):
            self._verify_evidence(origin)

        term = Term(name=name, definition=definition, origin=origin)
        self.terms[name] = term
        return term

    def set_fact(self, name: str, value: Any, origin: 'str | Evidence'):
        """Set a ground truth value with evidence.

        If the fact already exists:
          - overridable=False (default): raises ValueError, use retract first
          - overridable=True: overwrites and auto-recomputes dependent diffs
        """
        if name in self.facts:
            if not self.overridable:
                raise ValueError(
                    f"Fact '{name}' already exists. Use retract() first, "
                    f"or create System(overridable=True)")
            log.info("Overwriting fact '%s': %s → %s",
                     name, self.facts[name]['value'], value)

        if isinstance(origin, Evidence):
            self._verify_evidence(origin)

        self.facts[name] = {'value': value, 'origin': origin}
        self.env[Symbol(name)] = value

    # ----------------------------------------------------------
    # Instantiation
    # ----------------------------------------------------------

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
                origin = self.facts[src_name].get('origin')
            if src_name in self.axioms:
                origin = self.axioms[src_name].origin
            if src_name in self.theorems:
                origin = self.theorems[src_name].origin
            if src_name in self.terms:
                origin = self.terms[src_name].origin

            if isinstance(origin, Evidence) and not origin.is_grounded:
                ungrounded.append(src_name)
            # If origin is "potential fabrication" string from a prior derive
            if isinstance(origin, str) and 'potential fabrication' in origin:
                ungrounded.append(src_name)

        return ungrounded

    def derive(self, name: str, wff, using: list[str]) -> Theorem:
        """Derive a theorem from existing axioms/terms.

        If any source has unverified evidence, the theorem is
        marked as 'potential fabrication' with a trace to the unverified sources.
        """
        if isinstance(wff, str):
            wff = parse(wff)

        for ax_name in using:
            if (ax_name not in self.axioms
                    and ax_name not in self.facts
                    and ax_name not in self.terms
                    and ax_name not in self.theorems):
                raise ValueError(f"Unknown axiom, fact, term, or theorem: {ax_name}")

        result = self.evaluate(wff)
        does_not_hold = result is False

        if does_not_hold:
            log.warning("Derivation '%s' does not hold: %s evaluated to False",
                        name, to_sexp(wff))

        # Check fabrication propagation
        ungrounded = self._check_sources_grounded(using)
        issues = []
        if does_not_hold:
            issues.append("does not hold (evaluated to False)")
        if ungrounded:
            issues.append(f"derived from unverified: {', '.join(ungrounded)}")
            log.warning("Derivation '%s' marked as potential fabrication "
                        "(unverified sources: %s)", name, ', '.join(ungrounded))

        if issues:
            origin = f"potential fabrication — {'; '.join(issues)}"
        else:
            origin = "derived"

        thm = Theorem(name=name, wff=wff, derivation=using, origin=origin)
        self.theorems[name] = thm
        return thm

    # ----------------------------------------------------------
    # Evaluator
    # ----------------------------------------------------------

    def evaluate(self, expr, local_env=None) -> Any:
        """Evaluate an s-expression in the current system."""
        env = {**self.env, **(local_env or {})}
        return self._eval(expr, env)

    def _rewrite(self, expr, depth=0):
        """Reduce an expression by applying axioms as rewrite rules.

        Axioms of the form (= LHS RHS) are used left-to-right:
        if expr matches LHS, substitute to get RHS.
        """
        if depth > 100:
            return expr
        if not isinstance(expr, list):
            return expr

        # Reduce subexpressions first (innermost-first)
        expr = [self._rewrite(sub, depth + 1) for sub in expr]

        # Try axioms and theorems as rewrite rules
        for rule in list(self.axioms.values()) + list(self.theorems.values()):
            wff = rule.wff
            if not (isinstance(wff, list) and len(wff) == 3
                    and wff[0] == EQ):
                continue
            lhs, rhs = wff[1], wff[2]
            if not isinstance(lhs, list):
                continue
            # Skip symmetric rules (all args are bare ?-vars → would loop)
            if all(isinstance(a, Symbol) and str(a).startswith('?')
                   for a in lhs[1:]):
                continue
            bindings = match(lhs, expr)
            if bindings is not None:
                result = substitute(rhs, bindings)
                return self._rewrite(result, depth + 1)

        return expr

    def _eval(self, expr, env) -> Any:
        if isinstance(expr, Symbol):
            if expr in env:
                return env[expr]
            name = str(expr)
            if name in self.terms:
                defn = self.terms[name].definition
                if defn is not None:
                    return self._eval(defn, env)
                return expr  # forward-declared / primitive term
            raise NameError(f"Unresolved symbol: {expr} — not in current system")
        if not isinstance(expr, list):
            return expr

        if not expr:
            return None

        head = expr[0]

        if head == IF:
            _, cond, then, else_ = expr
            return self._eval(then, env) if self._eval(cond, env) else self._eval(else_, env)

        if head == LET:
            _, bindings, body = expr
            new_env = env.copy()
            for binding in bindings:
                new_env[binding[0]] = self._eval(binding[1], new_env)
            return self._eval(body, new_env)

        head_val = self._eval(head, env)
        args = [self._eval(arg, env) for arg in expr[1:]]

        if callable(head_val):
            return head_val(*args)

        # Formal: use axiom rewriting
        formal_expr = [head_val] + args
        if head_val == EQ:
            left = self._rewrite(args[0])
            right = self._rewrite(args[1])
            return left == right
        return self._rewrite(formal_expr)

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
            if expr.startswith('?'):
                return
            raise NameError(
                f"Symbol '{expr}' not in current system. Introduce it first.")
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
                            raise ValueError(
                                f"Contradiction: new axiom contradicts '{name}'"
                            )
                except (NameError, TypeError):
                    continue
        except (NameError, TypeError):
            pass

    def _register_if_definition(self, name: str, wff):
        """If the axiom defines a value, register it."""
        if (isinstance(wff, list) and len(wff) == 3
                and wff[0] == EQ and isinstance(wff[1], Symbol)):
            try:
                val = self.evaluate(wff[2])
                self.env[wff[1]] = val
            except (NameError, TypeError):
                pass

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

        direct = {n for n, t in self.terms.items()
                  if references(t.definition, symbol_name)}
        result = set()
        frontier = direct
        while frontier:
            result |= frontier
            frontier = {n for n, t in self.terms.items()
                        if n not in result
                        and any(references(t.definition, r) for r in frontier)}
        return list(result)

    def register_diff(self, name: str, replace: str, with_: str):
        """Register a diff — a lazy comparison between two symbols.

        Stores only the parameters. The result is computed fresh on
        every call to eval_diff() or consistency().
        """
        self.diffs[name] = {'replace': replace, 'with': with_}
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
        raise KeyError(f"Unknown symbol: {name}")

    def eval_diff(self, name: str) -> DiffResult:
        """Evaluate a registered diff against current system state."""
        if name not in self.diffs:
            raise KeyError(f"Unknown diff: {name}")

        params = self.diffs[name]
        replace = params['replace']
        with_ = params['with']

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
                from .atoms import substitute as subst
                result_a = defn
                result_b = subst(defn, {Symbol(replace): substitute_val})
            if result_a != result_b:
                divergences[term_name] = [result_a, result_b]

        return DiffResult(
            name=name, replace=replace, with_=with_,
            value_a=original, value_b=substitute_val,
            divergences=divergences,
        )

    # ----------------------------------------------------------
    # Retract / Rederive
    # ----------------------------------------------------------

    def retract(self, name: str):
        """Remove a fact, axiom, term, or diff from the system."""
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
            thm.origin = (f"potential fabrication — derived from unverified: "
                          f"{', '.join(ungrounded)}")
            log.warning("Rederive '%s': still has unverified sources: %s",
                        name, ', '.join(ungrounded))
        else:
            thm.origin = "derived"
            log.info("Rederive '%s': sources now verified — cleared", name)

    # ----------------------------------------------------------
    # Introspection
    # ----------------------------------------------------------

    def _format_origin(self, origin) -> dict | str:
        """Format an origin for display/serialization."""
        if isinstance(origin, Evidence):
            result = {
                'document': origin.document,
                'quotes': origin.quotes,
                'explanation': origin.explanation,
                'verified': origin.verified,
                'verify_manual': origin.verify_manual,
                'grounded': origin.is_grounded,
            }
            if origin.verification:
                result['verification'] = origin.verification
            return result
        return origin

    def provenance(self, name: str) -> dict:
        """Trace the full provenance chain of a statement."""
        if name in self.facts:
            return {
                'name': name,
                'type': 'fact',
                'origin': self._format_origin(self.facts[name].get('origin', '')),
            }

        if name in self.axioms:
            ax = self.axioms[name]
            return {
                'name': name,
                'type': 'axiom',
                'wff': to_sexp(ax.wff),
                'origin': self._format_origin(ax.origin),
            }

        if name in self.terms:
            term = self.terms[name]
            defn = to_sexp(term.definition) if term.definition is not None else "(forward declaration)"
            return {
                'name': name,
                'type': 'term',
                'definition': defn,
                'origin': self._format_origin(term.origin),
            }

        if name in self.theorems:
            thm = self.theorems[name]
            return {
                'name': name,
                'type': 'theorem',
                'wff': to_sexp(thm.wff),
                'origin': self._format_origin(thm.origin),
                'derivation_chain': [
                    self.provenance(dep) for dep in thm.derivation
                ],
            }

        if name in self.diffs:
            diff = self.diffs[name]
            result = self.eval_diff(name)
            return {
                'name': name,
                'type': 'diff',
                'replace': diff['replace'],
                'with': diff['with'],
                'value_a': result.value_a,
                'value_b': result.value_b,
                'divergences': result.divergences,
                'provenance_a': self.provenance(diff['replace']),
                'provenance_b': self.provenance(diff['with']),
            }

        raise KeyError(f"Unknown: {name}")

    def list_axioms(self) -> list[Axiom]:
        """Return all axioms in the system."""
        result = list(self.axioms.values())
        for ax in result:
            log.info("%s", ax)
        return result

    def list_theorems(self) -> list[Theorem]:
        """Return all theorems in the system."""
        result = list(self.theorems.values())
        for thm in result:
            log.info("%s", thm)
        return result

    def list_terms(self) -> list[Term]:
        """Return all terms in the system."""
        result = list(self.terms.values())
        for term in result:
            log.info("%s", term)
        return result

    def list_facts(self) -> list[dict]:
        """Return all ground facts."""
        result = []
        for name, info in self.facts.items():
            origin = info.get('origin', '')
            entry = {'name': name, 'value': info['value'], 'origin': origin}
            if isinstance(origin, Evidence):
                tag = str(origin)
            else:
                tag = f"[origin: {origin}]"
            log.info("%s = %s %s", name, info['value'], tag)
            result.append(entry)
        return result

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
            for name, item in store.items():
                if isinstance(item, dict):
                    origin = item.get('origin')
                else:
                    origin = item.origin
                if isinstance(origin, Evidence):
                    if not origin.verified and origin.verify_manual:
                        manually_verified.append(name)
                    elif not origin.is_grounded:
                        unverified.append(name)
                elif isinstance(origin, str):
                    if (origin not in ('unknown', 'derived')
                            and not origin.startswith('diff ')
                            and 'potential fabrication' not in origin):
                        no_evidence.append(name)

        if unverified:
            issues.append(ConsistencyIssue('unverified_evidence', unverified))
        if no_evidence:
            issues.append(ConsistencyIssue('no_evidence', no_evidence))
        if manually_verified:
            warnings.append(ConsistencyWarning('manually_verified', manually_verified))

        # 2. Fabrication propagation
        fabrications = [name for name, thm in self.theorems.items()
                        if isinstance(thm.origin, str)
                        and 'potential fabrication' in thm.origin]
        if fabrications:
            issues.append(ConsistencyIssue('potential_fabrication', fabrications))

        # 3. Diff divergences — evaluated live
        divergent = [self.eval_diff(n) for n in self.diffs]
        divergent = [d for d in divergent if not d.empty]
        if divergent:
            issues.append(ConsistencyIssue('diff_divergence', divergent))

        report = ConsistencyReport(
            consistent=len(issues) == 0,
            issues=issues,
            warnings=warnings,
        )

        log.info("%s", report) if report.consistent else log.warning("%s", report)
        return report

    def doc(self) -> str:
        """Generate DSL documentation: syntax reference and available operators.

        Shows the language constructs (directives, keywords, special forms)
        and the operators loaded into this system's environment.
        Does NOT include runtime state — use state() for that.
        """
        all_docs = {**LANG_DOCS, **ENGINE_DOCS}
        lines = []
        lines.append("Parseltongue System Documentation")
        lines.append("=" * 40)

        # Group env symbols by category
        categories: dict[str, list] = {}
        documented = set()
        for sym in self.env:
            if isinstance(sym, Symbol) and sym in all_docs:
                doc = all_docs[sym]
                cat = doc['category']
                categories.setdefault(cat, []).append((sym, doc))
                documented.add(sym)

        # Add special forms and directives (not in env but part of the language)
        for sym, doc in all_docs.items():
            if sym not in documented and doc['category'] in ('special', 'directive', 'structural', 'keyword'):
                categories.setdefault(doc['category'], []).append((sym, doc))
                documented.add(sym)

        # Category display order
        order = ['special', 'arithmetic', 'comparison', 'logic',
                 'directive', 'structural', 'keyword']
        titles = {
            'special': 'Special Forms',
            'arithmetic': 'Arithmetic Operators',
            'comparison': 'Comparison Operators',
            'logic': 'Logic Operators',
            'directive': 'DSL Directives',
            'structural': 'Structural',
            'keyword': 'Keyword Arguments',
        }

        for cat in order:
            entries = categories.get(cat, [])
            if not entries:
                continue
            lines.append("")
            lines.append(f"  {titles.get(cat, cat)}")
            lines.append(f"  {'-' * len(titles.get(cat, cat))}")
            for sym, doc in entries:
                lines.append(f"    {sym}")
                # First line of description only for compact display
                desc = doc['description']
                first_line = desc.split('\n')[0]
                lines.append(f"      {first_line}")
                lines.append(f"      Example: {doc['example']}")
                if 'expected' in doc:
                    lines.append(f"      => {doc['expected']}")
                # Show patterns if available
                if 'patterns' in doc:
                    lines.append(f"      Patterns:")
                    for pattern in doc['patterns']:
                        for pline in pattern.split('\n'):
                            lines.append(f"        {pline}")
                        lines.append("")

        return "\n".join(lines)

    def state(self) -> str:
        """Show the current runtime state: facts, terms, axioms, theorems, diffs."""
        lines = []

        if self.facts:
            lines.append("  Facts")
            lines.append("  " + "-" * 5)
            for name, info in self.facts.items():
                lines.append(f"    {name} = {info['value']}")

        if self.terms:
            lines.append("")
            lines.append("  Terms")
            lines.append("  " + "-" * 5)
            for name, term in self.terms.items():
                defn = to_sexp(term.definition) if term.definition is not None else "(forward declaration)"
                lines.append(f"    {name} := {defn}")

        if self.axioms:
            lines.append("")
            lines.append("  Axioms")
            lines.append("  " + "-" * 6)
            for name, ax in self.axioms.items():
                lines.append(f"    {name}: {to_sexp(ax.wff)}")

        if self.theorems:
            lines.append("")
            lines.append("  Theorems")
            lines.append("  " + "-" * 8)
            for name, thm in self.theorems.items():
                sources = ', '.join(thm.derivation)
                lines.append(f"    {name}: {to_sexp(thm.wff)}  [from: {sources}]")

        if self.diffs:
            lines.append("")
            lines.append("  Diffs")
            lines.append("  " + "-" * 5)
            for name, params in self.diffs.items():
                lines.append(f"    {name}: {params['replace']} vs {params['with']}")

        if not lines:
            return "  (empty)"

        return "\n".join(lines)

    def __repr__(self):
        return (
            f"System({len(self.axioms)} axioms, "
            f"{len(self.theorems)} theorems, "
            f"{len(self.terms)} terms, "
            f"{len(self.facts)} facts, "
            f"{len(self.diffs)} diffs, "
            f"{len(self.documents)} docs)")


# ============================================================
# DSL Loader
# ============================================================

def load_source(system: System, source: str):
    """Load a multi-expression source string into the system.

    Parses and executes directives sequentially.  Comments start with ``;``.

    Directive reference::

      (fact name value
          :origin "string"                        ;; plain origin
          | :evidence (evidence "Doc"             ;; or structured evidence
              :quotes ("exact quote" ...)
              :explanation "why"))

      (defterm name                               ;; forward declaration
          :evidence (...))
      (defterm name expression                    ;; computed term
          :evidence (...))
      (defterm name (if cond then else)           ;; conditional term
          :origin "...")

      (axiom name wff                             ;; concrete
          :evidence (...))
      (axiom name (= (+ ?a ?b) (+ ?b ?a))        ;; parameterised (with ?-vars)
          :evidence (...))

      (derive name wff                            ;; direct derivation
          :using (source1 source2 ...))
      (derive name template-name                  ;; instantiation
          :bind ((?var value) ...)
          :using (template-name ...))

      (diff name
          :replace symbol
          :with symbol)
    """
    tokens = tokenize(source)
    while tokens:
        expr = read_tokens(tokens)
        _execute_directive(system, expr)


def _resolve_origin(expr) -> 'str | Evidence':
    """Extract origin from an expression — either :origin string or :evidence."""
    evidence_raw = get_keyword(expr, KW_EVIDENCE, None)
    if evidence_raw is not None:
        return parse_evidence(evidence_raw)

    origin = get_keyword(expr, KW_ORIGIN, 'unknown')
    return origin


def _parse_bindings(system, bind_raw):
    """Convert ((?var val) ...) into {Symbol('?var'): val}.

    Substitution is symbolic — binding values are expression trees,
    not evaluated results.

    Skips malformed pairs (empty lists, singletons, non-list items).
    """
    bindings = {}
    for pair in bind_raw:
        if not isinstance(pair, list) or len(pair) < 2:
            log.warning("Skipping malformed bind pair: %s", pair)
            continue
        bindings[pair[0]] = pair[1]
    return bindings


def _execute_directive(system: System, expr):
    """Execute a single top-level directive."""
    if not isinstance(expr, list) or not expr:
        return

    head = expr[0]

    if head == AXIOM:
        name = str(expr[1])
        bind_raw = get_keyword(expr, KW_BIND, None)
        if bind_raw is not None:
            ref = str(expr[2])
            bindings = _parse_bindings(system, bind_raw)
            wff = system.instantiate(ref, bindings)
        else:
            wff = expr[2]
        origin = _resolve_origin(expr)
        system.introduce_axiom(name, wff, origin)

    elif head == DEFTERM:
        name = str(expr[1])
        bind_raw = get_keyword(expr, KW_BIND, None)
        if bind_raw is not None:
            ref = str(expr[2])
            bindings = _parse_bindings(system, bind_raw)
            defn = system.instantiate(ref, bindings)
        elif len(expr) < 3 or (isinstance(expr[2], str) and expr[2].startswith(':')):
            # Forward declaration — no definition body
            defn = None
        else:
            defn = expr[2]
        origin = _resolve_origin(expr)
        system.introduce_term(name, defn, origin)

    elif head == FACT:
        name = str(expr[1])
        value = expr[2]
        origin = _resolve_origin(expr)
        system.set_fact(name, value, origin)

    elif head == DERIVE:
        name = str(expr[1])
        using = get_keyword(expr, KW_USING, [])
        if isinstance(using, list):
            using = [str(s) for s in using]
        bind_raw = get_keyword(expr, KW_BIND, None)
        if bind_raw is not None:
            ref = str(expr[2])
            bindings = _parse_bindings(system, bind_raw)
            if not bindings:
                # Empty :bind — treat as direct axiom reference
                log.warning("Empty :bind in derive '%s' — expanding axiom '%s' directly", name, ref)
                if ref in system.axioms:
                    wff = system.axioms[ref].wff
                else:
                    wff = expr[2]
            else:
                wff = system.instantiate(ref, bindings)
        else:
            wff = expr[2]
            # Auto-expand axiom names used as bare WFF
            if isinstance(wff, Symbol) and str(wff) in system.axioms:
                axiom_name = str(wff)
                log.warning("Derive '%s' used axiom name '%s' as WFF — auto-expanding to axiom body", name, axiom_name)
                wff = system.axioms[axiom_name].wff
        system.derive(name, wff, using)

    elif head == DIFF:
        name = str(expr[1])
        replace = str(get_keyword(expr, KW_REPLACE))
        with_ = str(get_keyword(expr, KW_WITH))
        system.register_diff(name, replace, with_)
