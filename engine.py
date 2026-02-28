"""
Parseltongue DSL — Runtime Engine.

Stateful system: evaluation, axiom store, document registry,
quote verification, derivation with fabrication propagation.
"""

from typing import Any
import logging
import operator

log = logging.getLogger('parseltongue')

from atoms import Symbol
from lang import (
    Axiom, Term, Evidence,
    parse, tokenize, read_tokens, to_sexp,
    get_keyword, parse_evidence,
    # Special forms
    IF, LET, QUOTE,
    # DSL keywords
    AXIOM, DEFTERM, FACT, DERIVE, DIFF,
    # Keyword arguments
    KW_ORIGIN, KW_EVIDENCE, KW_USING, KW_REPLACE, KW_WITH,
    # Documentation
    LANG_DOCS,
)
from quote_verifier import QuoteVerifier


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
        'description': 'Add two numbers.',
        'example': '(+ 2 3)',
        'expected': 5,
    },
    SUB: {
        'category': 'arithmetic',
        'description': 'Subtract second from first.',
        'example': '(- 10 4)',
        'expected': 6,
    },
    MUL: {
        'category': 'arithmetic',
        'description': 'Multiply two numbers.',
        'example': '(* 3 7)',
        'expected': 21,
    },
    DIV: {
        'category': 'arithmetic',
        'description': 'Divide first by second (true division).',
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
        'description': 'True if first is strictly greater than second.',
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
        'description': 'True if both values are equal.',
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
        'description': 'Logical AND. True only if both operands are true.',
        'example': '(and true false)',
        'expected': False,
    },
    OR: {
        'category': 'logic',
        'description': 'Logical OR. True if at least one operand is true.',
        'example': '(or false true)',
        'expected': True,
    },
    NOT: {
        'category': 'logic',
        'description': 'Logical NOT. Negates a boolean.',
        'example': '(not true)',
        'expected': False,
    },
    IMPLIES: {
        'category': 'logic',
        'description': 'Logical implication. False only when antecedent '
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


class System:
    """The Parseltongue formal system. Grows via axiom introduction."""

    def __init__(self, overridable: bool = False,
                 initial_env: dict | None = None):
        self.axioms: dict[str, Axiom] = {}
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
            if src_name in self.terms:
                origin = self.terms[src_name].origin

            if isinstance(origin, Evidence) and not origin.is_grounded:
                ungrounded.append(src_name)
            # If origin is "potential fabrication" string from a prior derive
            if isinstance(origin, str) and 'potential fabrication' in origin:
                ungrounded.append(src_name)

        return ungrounded

    def derive(self, name: str, wff, using: list[str]) -> Axiom:
        """Derive a new statement from existing axioms.

        If any source has unverified evidence, the derived axiom is
        marked as 'potential fabrication' with a trace to the unverified sources.
        """
        if isinstance(wff, str):
            wff = parse(wff)

        for ax_name in using:
            if ax_name not in self.axioms and ax_name not in self.facts:
                raise ValueError(f"Unknown axiom or fact: {ax_name}")

        result = self.evaluate(wff)
        if result is False:
            raise ValueError(
                f"Derivation '{name}' does not hold: "
                f"{to_sexp(wff)} evaluated to False"
            )

        # Check fabrication propagation
        ungrounded = self._check_sources_grounded(using)
        if ungrounded:
            origin = (f"potential fabrication — derived from unverified: "
                      f"{', '.join(ungrounded)}")
            log.warning("Derivation '%s' marked as potential fabrication "
                        "(unverified sources: %s)", name, ', '.join(ungrounded))
        else:
            origin = "derived"

        ax = Axiom(name=name, wff=wff, origin=origin, derived=True, derivation=using)
        self.axioms[name] = ax
        return ax

    # ----------------------------------------------------------
    # Evaluator
    # ----------------------------------------------------------

    def evaluate(self, expr, local_env=None) -> Any:
        """Evaluate an s-expression in the current system."""
        env = {**self.env, **(local_env or {})}
        return self._eval(expr, env)

    def _eval(self, expr, env) -> Any:
        if isinstance(expr, Symbol):
            if expr in env:
                return env[expr]
            # Auto-resolve terms: evaluate their definition inline
            name = str(expr)
            if name in self.terms:
                return self._eval(self.terms[name].definition, env)
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

        if head == QUOTE:
            return expr[1]

        fn = self._eval(head, env)
        args = [self._eval(arg, env) for arg in expr[1:]]
        return fn(*args)

    # ----------------------------------------------------------
    # Validation
    # ----------------------------------------------------------

    def _check_wff(self, expr):
        """Check that an expression is well-formed in the current system."""
        if isinstance(expr, Symbol):
            if expr in self.env or str(expr) in self.terms:
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

    def eval_diff(self, name: str) -> dict:
        """Evaluate a registered diff against current system state."""
        if name not in self.diffs:
            raise KeyError(f"Unknown diff: {name}")

        params = self.diffs[name]
        replace = params['replace']
        with_ = params['with']

        if Symbol(replace) in self.env:
            original = self.env[Symbol(replace)]
        elif replace in self.terms:
            original = self.evaluate(self.terms[replace].definition)
        else:
            raise KeyError(f"Unknown symbol: {replace}")

        if Symbol(with_) in self.env:
            substitute = self.env[Symbol(with_)]
        elif with_ in self.terms:
            substitute = self.evaluate(self.terms[with_].definition)
        else:
            raise KeyError(f"Unknown symbol: {with_}")

        affected = self._dependents(replace)

        divergences = {}
        for term_name in affected:
            defn = self.terms[term_name].definition
            result_a = self.evaluate(defn)
            result_b = self.evaluate(defn, {Symbol(replace): substitute})
            if result_a != result_b:
                divergences[term_name] = [result_a, result_b]

        return {
            'name': name,
            'replace': replace,
            'with': with_,
            'value_a': original,
            'value_b': substitute,
            'divergences': divergences,
            'empty': len(divergences) == 0,
        }

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
        flagged, which made derived axioms stale.
        """
        if name not in self.axioms:
            raise KeyError(f"Unknown axiom: {name}")
        ax = self.axioms[name]
        if not ax.derived:
            raise ValueError(f"'{name}' is not a derived axiom")

        # Re-derive: re-check sources and update origin
        ungrounded = self._check_sources_grounded(ax.derivation)
        if ungrounded:
            ax.origin = (f"potential fabrication — derived from unverified: "
                         f"{', '.join(ungrounded)}")
            log.warning("Rederive '%s': still has unverified sources: %s",
                        name, ', '.join(ungrounded))
        else:
            ax.origin = "derived"
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

        if name not in self.axioms:
            raise KeyError(f"Unknown: {name}")

        ax = self.axioms[name]
        result = {
            'name': name,
            'wff': to_sexp(ax.wff),
            'origin': self._format_origin(ax.origin),
            'derived': ax.derived,
        }

        if ax.derived:
            result['derivation_chain'] = [
                self.provenance(dep) for dep in ax.derivation
            ]

        return result

    def _origin_tag(self, origin) -> str:
        """Format an origin as a short status tag."""
        if isinstance(origin, Evidence):
            status = "grounded" if origin.is_grounded else "UNVERIFIED"
            return f"[evidence: {origin.document} ({status})]"
        return f"[origin: {origin}]"

    def list_axioms(self) -> list[dict]:
        """Return all axioms in the system."""
        results = []
        for name, ax in self.axioms.items():
            entry = {
                'name': name,
                'wff': to_sexp(ax.wff),
                'derived': ax.derived,
                'origin': self._format_origin(ax.origin),
            }
            if ax.derived:
                entry['derivation'] = ax.derivation
            results.append(entry)
            tag = (f"[derived from: {', '.join(ax.derivation)}]"
                   if ax.derived else self._origin_tag(ax.origin))
            log.info("%s: %s %s", name, to_sexp(ax.wff), tag)
        return results

    def list_terms(self) -> list[dict]:
        """Return all terms in the system."""
        results = []
        for name, term in self.terms.items():
            results.append({
                'name': name,
                'definition': to_sexp(term.definition),
                'origin': self._format_origin(term.origin),
            })
            log.info("%s: %s %s", name, to_sexp(term.definition),
                     self._origin_tag(term.origin))
        return results

    def list_facts(self) -> list[dict]:
        """Return all ground facts."""
        results = []
        for name, info in self.facts.items():
            origin = info.get('origin', '')
            results.append({
                'name': name,
                'value': info['value'],
                'origin': self._format_origin(origin),
            })
            log.info("%s = %s %s", name, info['value'],
                     self._origin_tag(origin))
        return results

    def consistency(self) -> dict:
        """Display full consistency state of the system.

        Checks three layers:
          1. Evidence grounding — are all quotes verified?
          2. Fabrication propagation — any derived axioms tainted?
          3. Diff agreement — do cross-checked values agree?

        Returns a summary dict with a top-level 'consistent' flag.
        """
        issues = []
        warnings = []

        # 1. Evidence grounding
        unverified = []
        manually_verified = []
        no_evidence = []
        for store in [self.facts, self.axioms, self.terms]:
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
                    # Plain :origin string = no evidence = unverified
                    # Skip diff-generated and derived origins
                    if (origin not in ('unknown', 'derived')
                            and not origin.startswith('diff ')
                            and 'potential fabrication' not in origin):
                        no_evidence.append(name)

        if unverified:
            issues.append({
                'type': 'unverified_evidence',
                'items': unverified,
            })

        if no_evidence:
            issues.append({
                'type': 'no_evidence',
                'items': no_evidence,
            })

        if manually_verified:
            warnings.append({
                'type': 'manually_verified',
                'items': manually_verified,
            })

        # 2. Fabrication propagation
        fabrications = []
        for name, ax in self.axioms.items():
            if isinstance(ax.origin, str) and 'potential fabrication' in ax.origin:
                fabrications.append(name)

        if fabrications:
            issues.append({
                'type': 'potential_fabrication',
                'items': fabrications,
            })

        # 3. Diff divergences — evaluated live
        divergent_diffs = []
        for diff_name in self.diffs:
            result = self.eval_diff(diff_name)
            if not result['empty']:
                divergent_diffs.append(result)

        if divergent_diffs:
            issues.append({
                'type': 'diff_divergence',
                'items': divergent_diffs,
            })

        consistent = len(issues) == 0

        # Log results
        if consistent:
            log.info("System is fully consistent")
        else:
            log.warning("System inconsistent: %d issue(s) found", len(issues))
            for issue in issues:
                if issue['type'] == 'unverified_evidence':
                    log.warning("Unverified evidence: %s",
                                ', '.join(issue['items']))
                elif issue['type'] == 'no_evidence':
                    log.warning("No evidence provided: %s",
                                ', '.join(issue['items']))
                elif issue['type'] == 'potential_fabrication':
                    log.warning("Potential fabrication: %s",
                                ', '.join(issue['items']))
                elif issue['type'] == 'diff_divergence':
                    for d in issue['items']:
                        log.warning("Diff '%s': %s (%s) vs %s (%s)",
                                    d['name'], d['replace'], d['value_a'],
                                    d['with'], d['value_b'])
                        for t, (a, b) in d['divergences'].items():
                            log.warning("  %s: %s → %s", t, a, b)

        for w in warnings:
            if w['type'] == 'manually_verified':
                log.info("Manually verified: %s", ', '.join(w['items']))

        return {'consistent': consistent, 'issues': issues, 'warnings': warnings}

    def doc(self) -> str:
        """Generate documentation for the system based on its current state.

        Reflects the actual symbols loaded into this system instance,
        grouped by category with descriptions and examples.
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

        # Add special forms (not in env but part of the language)
        for sym, doc in all_docs.items():
            if doc['category'] == 'special' and sym not in documented:
                categories.setdefault('special', []).append((sym, doc))
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
                lines.append(f"      {doc['description']}")
                lines.append(f"      Example: {doc['example']}")
                if 'expected' in doc:
                    lines.append(f"      => {doc['expected']}")

        # User-defined symbols (facts, terms)
        user_symbols = []
        for sym in self.env:
            if isinstance(sym, Symbol) and sym not in documented:
                user_symbols.append(sym)

        if user_symbols or self.terms:
            lines.append("")
            lines.append("  User-Defined")
            lines.append("  " + "-" * 12)
            for sym in user_symbols:
                val = self.env[sym]
                lines.append(f"    {sym} = {val}")
            for name, term in self.terms.items():
                lines.append(f"    {name} := {to_sexp(term.definition)}")

        return "\n".join(lines)

    def __repr__(self):
        return (
            f"System({len(self.axioms)} axioms, "
            f"{len(self.terms)} terms, "
            f"{len(self.facts)} facts, "
            f"{len(self.diffs)} diffs, "
            f"{len(self.documents)} docs)")


# ============================================================
# DSL Loader
# ============================================================

def load_source(system: System, source: str):
    """Load a multi-expression source into the system.

    Supports:
      (axiom name wff :origin "..." | :evidence (...))
      (defterm name definition :origin "..." | :evidence (...))
      (fact name value :origin "..." | :evidence (...))
      (derive name wff :using (ax1 ax2 ...))
      (diff name :replace symbol :with symbol)
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


def _execute_directive(system: System, expr):
    """Execute a single top-level directive."""
    if not isinstance(expr, list) or not expr:
        return

    head = expr[0]

    if head == AXIOM:
        name = str(expr[1])
        wff = expr[2]
        origin = _resolve_origin(expr)
        system.introduce_axiom(name, wff, origin)

    elif head == DEFTERM:
        name = str(expr[1])
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
        wff = expr[2]
        using = get_keyword(expr, KW_USING, [])
        if isinstance(using, list):
            using = [str(s) for s in using]
        system.derive(name, wff, using)

    elif head == DIFF:
        name = str(expr[1])
        replace = str(get_keyword(expr, KW_REPLACE))
        with_ = str(get_keyword(expr, KW_WITH))
        system.register_diff(name, replace, with_)
