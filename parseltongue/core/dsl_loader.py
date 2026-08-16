"""DslLoader — the engine's small DSL loader, as its own object.

Owns the language surface: how an :evidence form parses and which
directives exist. Both engine implementations hold one (``engine.dsl``)
and drive every directive through it; derived languages subclass it and
point their engine at the subclass via ``Engine.dsl_loader_cls`` — the
same one-line swappable-default pattern as ``System.engine_cls`` and
``Loader.system_cls``. Defaults reproduce the core language exactly.
"""

import logging

from .lang import (
    AXIOM,
    DEFTERM,
    DERIVE,
    DIFF,
    EQ,
    FACT,
    KW_BIND,
    KW_EVIDENCE,
    KW_ORIGIN,
    KW_REPLACE,
    KW_USING,
    KW_WITH,
    SILENCE,
    Evidence,
    PGStringParser,
    Silence,
    Symbol,
    free_vars,
    get_keyword,
    parse_evidence,
)

log = logging.getLogger("parseltongue")


def _parse_bindings(bind_raw):
    bindings = {}
    for pair in bind_raw:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            log.warning("Skipping malformed bind pair: %s", pair)
            continue
        bindings[pair[0]] = pair[1]
    return bindings


class DslLoader:
    """Parses and executes directives against one engine.

    Override points for derived languages:
      - parse_evidence — expand the evidence grammar (new keywords/types)
      - execute_directive — add directives (new language functions)
    """

    def __init__(self, engine):
        self._engine = engine

    def load_source(self, source: str) -> Silence:
        """Parse source text and execute every directive in it."""
        result = PGStringParser.translate(source)
        if isinstance(result, (list, tuple)) and result and isinstance(result[0], (list, tuple)):
            for expr in result:
                self.execute_directive(expr)
        elif isinstance(result, (list, tuple)) and result:
            self.execute_directive(result)
        return SILENCE

    def parse_evidence(self, expr) -> "str | Evidence":
        """Parse an :evidence form. Override to expand the evidence grammar."""
        return parse_evidence(expr)

    def resolve_origin(self, expr) -> "str | Evidence":
        """Resolve a directive's :evidence / :origin into its origin value."""
        evidence_raw = get_keyword(expr, KW_EVIDENCE, None)
        if evidence_raw is not None:
            return self.parse_evidence(evidence_raw)
        return get_keyword(expr, KW_ORIGIN, "unknown")

    def execute_directive(self, expr):
        """Execute one parsed directive. Override to add directives."""
        if not isinstance(expr, (list, tuple)) or not expr:
            return

        engine = self._engine
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
            engine.introduce_axiom(name, wff, self.resolve_origin(expr))

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
            engine.introduce_term(name, defn, self.resolve_origin(expr))

        elif head == FACT:
            engine.set_fact(str(expr[1]), expr[2], self.resolve_origin(expr))

        elif head == DERIVE:
            name = str(expr[1])
            using = get_keyword(expr, KW_USING, [])
            if isinstance(using, (list, tuple)):
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
                        is_rewrite = (
                            isinstance(w, (list, tuple))
                            and len(w) == 3
                            and w[0] == EQ
                            and isinstance(w[1], (list, tuple))
                        )
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
