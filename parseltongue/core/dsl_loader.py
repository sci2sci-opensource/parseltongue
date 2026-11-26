"""DslLoader — the engine's small DSL loader, as its own object.

Owns the language surface: how an :evidence form parses and which
directives exist. Both engine implementations hold one (``engine.dsl``)
and drive every directive through it; derived languages subclass it,
point their engine at the subclass via the ``dsl_loader_cls``
constructor default, and hand the composed engine to a system via its
``engine`` constructor argument. Defaults reproduce the core language
exactly.

The loader also owns typing (``self.typing``, a ``TypeState``): it registers
``deftype`` types, records every node's type as the node is introduced,
checks formulas and bindings against those types, and classifies each
rule application's outcome. What it finds is reported by the engine's
consistency check; nothing here stops a load.
"""

import logging
from dataclasses import replace
from typing import Any

from .lang import (
    AXIOM,
    DEFTERM,
    DEFTYPE,
    DERIVE,
    DIFF,
    EQ,
    FACT,
    KW_BIND,
    KW_EVIDENCE,
    KW_EXPECT,
    KW_OF,
    KW_ORDER,
    KW_ORIGIN,
    KW_REPLACE,
    KW_TYPE,
    KW_TYPES,
    KW_USING,
    KW_WHERE,
    KW_WITH,
    ONE_OF,
    SILENCE,
    Evidence,
    PGStringParser,
    Silence,
    Symbol,
    free_vars,
    get_keyword,
    parse_evidence,
    substitute,
)
from .types import (
    ANY,
    FIRED,
    REST_C,
    SYM,
    VACUOUS,
    VIOLATED,
    EnumMember,
    NodeType,
    Type,
    TypeState,
    _keyword_list,
    _show,
    assignable,
    element,
    fn,
    infer,
    infer_signature,
    type_of_value,
)

IMPLIES = Symbol("implies")
OUTCOMES = (FIRED, VACUOUS, VIOLATED)

log = logging.getLogger("parseltongue")


def _shown(value: object) -> str:
    """A part of a value as written: a string quoted, so it is told from a symbol."""
    if isinstance(value, str) and not isinstance(value, Symbol):
        return f'"{value}"'
    return _show(value)


def _parse_bindings(bind_raw):
    bindings = {}
    for pair in bind_raw:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            log.warning("Skipping malformed bind pair: %s", pair)
            continue
        bindings[pair[0]] = pair[1]
    return bindings


def _written_sources(engine, *forms) -> list[str]:
    """The sources a derive names in its own form: every fact, term and theorem its formula
    or a :bind value mentions, once each, in the order written. They are sources without
    being listed; :using lists the rest (what only a rule's body mentions, the rewrite rules
    evaluation leans on). A written name is never a rewrite rule: the engine applies only the
    rules :using lists, so naming a node never brings another world's rules into scope."""
    known = (engine.facts, engine.terms, engine.theorems)
    names: dict[str, None] = {}

    def walk(value):
        if isinstance(value, Symbol):
            if any(str(value) in table for table in known):
                names.setdefault(str(value))
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    for form in forms:
        walk(form)
    return list(names)


class DslLoader:
    """Parses and executes directives against one engine.

    Override points for derived languages:
      - parse_evidence — expand the evidence grammar (new keywords/types)
      - execute_directive — add directives (new language functions)
    """

    def __init__(self, engine):
        self._engine = engine
        self.typing = TypeState()
        self._derived: dict[str, object] = {}  # a derive's value, handed over by the engine
        self._rules: dict[str, list] = {}  # an undeclared function's rewrite rules, for its inferred type

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
            declared = get_keyword(expr, KW_USING, None)  # the rules its right-hand side resolves with
            engine.introduce_axiom(name, wff, self.resolve_origin(expr), [str(s) for s in declared or ()])
            self._infer_function(wff)  # the rule joins its head's signature before its own body is checked
            self._type_axiom(name, wff, get_keyword(expr, KW_TYPES, None))

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
            self._type_value(name, defn, get_keyword(expr, KW_TYPE, None), primitive=defn is None)

        elif head == FACT:
            name, value = str(expr[1]), expr[2]
            member = engine.env.get(value) if isinstance(value, Symbol) else None
            if isinstance(member, EnumMember) and member == value:
                value = member  # a member symbol is its member value: its enumeration and rank
            engine.set_fact(name, value, self.resolve_origin(expr))
            self._type_value(name, value, get_keyword(expr, KW_TYPE, None))

        elif head == DEFTYPE:
            self._deftype(expr)

        elif head == DERIVE:
            name = str(expr[1])
            using = get_keyword(expr, KW_USING, [])
            if isinstance(using, (list, tuple)):
                using = [str(s) for s in using]
            bind_raw = get_keyword(expr, KW_BIND, None)
            rule = None  # the axiom this derive applies, when it applies one
            if bind_raw is not None:
                ref = str(expr[2])
                bindings = _parse_bindings(bind_raw)
                # The applied axiom is the derive's own rule: a source as if listed
                known = (engine.axioms, engine.facts, engine.terms, engine.theorems)
                if isinstance(using, list) and ref not in using and any(ref in table for table in known):
                    using.append(ref)
                written = _written_sources(engine, *bindings.values())
                if ref in engine.axioms:
                    rule = ref
                    self._check_bindings(name, ref, bindings)
                if not bindings:
                    log.warning("Empty :bind in derive '%s' — expanding axiom '%s' directly", name, ref)
                    wff = engine.axioms[ref].wff if ref in engine.axioms else expr[2]
                else:
                    wff = engine.instantiate(ref, bindings)
            else:
                wff = expr[2]
                written = _written_sources(engine, wff)
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
            self._derived.pop(name, None)
            engine.derive(name, wff, using, written)
            self._type_derive(name, wff, rule, get_keyword(expr, KW_TYPE, None), get_keyword(expr, KW_EXPECT, None))

        elif head == DIFF:
            engine.register_diff(str(expr[1]), str(get_keyword(expr, KW_REPLACE)), str(get_keyword(expr, KW_WITH)))

        else:
            engine.evaluate(expr)

    # ----------------------------------------------------------
    # Typing
    # ----------------------------------------------------------

    def derived(self, name: str, value: object) -> None:
        """The engine hands over a derive's value as it computes it: a ``Bool``
        value makes the derive a theorem, any other value a computation."""
        self._derived[name] = value
        self.typing.judgements[name] = "theorem" if isinstance(value, bool) or value is None else "computation"

    def _declared(self, name: str, type_expr: object) -> "Type | None":
        """The type a ``:type`` writes, recording an error when it writes none."""
        if type_expr is None:
            return None
        t = self.typing.resolve(type_expr)
        if isinstance(t, str):
            self.typing.error(name, f":type {t}")
            return None
        return t

    def _type_value(self, name: str, value: object, type_expr: object, primitive: bool = False) -> None:
        """Record a fact's or term's type: declared, or inferred from its value."""
        existing = self.typing.nodes.get(name)
        declared = self._declared(name, type_expr)
        if declared is None and existing is not None and primitive and (existing.declared or existing.type.is_fn):
            return  # an enumeration member a deftype typed, or a function its rewrite rules define
        if primitive:
            inferred = NodeType(SYM)
        else:
            errors: list[str] = []
            inferred = infer(value, self.typing.env(), errors)
            for message in errors:
                self.typing.error(name, message)
        if declared is None:
            self.typing.nodes[name] = inferred
            return
        if not primitive:
            self._check_member(name, value, inferred, declared)
        self.typing.nodes[name] = NodeType(declared, declared=True)

    @staticmethod
    def _narrows(inferred: NodeType, declared: Type) -> bool:
        """A value of a refinement's or subset enumeration's base type may belong to it:
        whether it does is decided by its value, not its type."""
        narrowing = declared.where is not None or (declared.members is not None and declared.base is not None)
        return narrowing and declared.base is not None and assignable(inferred, declared.base)

    def _check_member(self, name: str, value: object, inferred: NodeType, declared: Type) -> None:
        """Whether a declared node's value belongs to its type: assignable (or of the
        base a refinement or subset narrows), a member of every enumeration on its
        chain, and satisfying every refinement's predicate on its chain; and so is
        every field of a record and every element of a list in it, however deep."""
        if not assignable(inferred, declared) and not self._narrows(inferred, declared):
            self.typing.error(name, f"value {_show(value)} is {inferred}, declared {declared}")
            return
        self._check_chain(name, value, declared, "")
        self._check_parts(name, value, declared, "")

    def _check_chain(self, name: str, value: object, declared: Type, at: str) -> None:
        """A value is a member of every enumeration on its type's chain and satisfies every
        refinement's predicate on it; ``at`` names the field it is, when it is one."""
        prefix = f"field {at}: " if at else ""
        resolved = self._holds(value) if isinstance(value, Symbol) else value
        t: "Type | None" = declared
        while t is not None:
            if t.members is not None and str(resolved) not in t.members:
                self.typing.error(name, f"{prefix}value {value} is not a member of {t} ({', '.join(t.members)})")
            if t.where is not None:
                holds = self._holds(substitute(t.where, {Symbol("?x"): value}))
                if holds is not True:
                    self.typing.error(name, f"{prefix}value {value} does not satisfy {t}'s :where")
            t = t.base

    def _check_parts(self, name: str, value: object, declared: Type, at: str) -> None:
        """A record's fields, each by its field's type, and a list's elements, each by the element type."""
        rep = declared.representation
        if rep.is_record and isinstance(value, (list, tuple)) and _keyword_list(value):
            fields = {str(value[i])[1:]: value[i + 1] for i in range(0, len(value), 2)}
            for label, field_type in zip(rep.labels, rep.args):
                if label in fields:
                    self._check_part(name, fields[label], field_type, f"{at} :{label}".strip())
        elif rep.is_list and isinstance(value, (list, tuple)) and not _keyword_list(value):
            for i, item in enumerate(value):
                self._check_part(name, item, element(rep), f"{at}[{i}]")

    def _check_part(self, name: str, value: object, declared: Type, at: str) -> None:
        """A field or an element, checked as a value of its own; a record or a list in it is
        checked part by part, so what is wrong is named where it is."""
        rep = declared.representation
        if rep.is_record and isinstance(value, (list, tuple)) and _keyword_list(value):
            present = {str(value[i])[1:] for i in range(0, len(value), 2)}
            for label in rep.labels:
                if label not in present:
                    self.typing.error(name, f"field {at}: has no :{label}, declared {declared}")
        elif not (rep.is_list and isinstance(value, (list, tuple)) and not _keyword_list(value)):
            # A member names its enumeration; any other part is the data it is
            known = self.typing.nodes.get(str(value)) if isinstance(value, Symbol) else None
            inferred = known or NodeType(type_of_value(value))
            if not assignable(inferred, declared) and not self._narrows(inferred, declared):
                self.typing.error(name, f"field {at}: value {_shown(value)} is {inferred.type}, declared {declared}")
                return
        self._check_chain(name, value, declared, at)
        self._check_parts(name, value, declared, at)

    def _holds(self, expr: object) -> object:
        try:
            return self._engine.evaluate(expr)
        except Exception as e:  # noqa: BLE001 — a predicate that cannot evaluate does not hold
            return e

    def _type_axiom(self, name: str, wff: object, types_raw: Any) -> None:
        """Record an axiom's declared ?-variable types and check its formula against them."""
        declared: dict[str, Type] = {}
        for pair in types_raw or []:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                self.typing.error(name, f":types entry {pair} is not a (?var Type) pair")
                continue
            vt = self._declared(name, pair[1])
            if vt is not None:
                declared[str(pair[0])] = vt
        self.typing.axiom_vars[name] = declared
        errors: list[str] = []
        infer(wff, self.typing.env(declared), errors)
        for message in errors:
            self.typing.error(name, message)

    def _infer_function(self, wff: object) -> None:
        """A term with no declared type that heads rewrite rules is a function whose
        type is inferred from those rules (``infer_signature``), re-inferred as each
        rule arrives."""
        if not (isinstance(wff, (list, tuple)) and len(wff) == 3 and wff[0] == EQ):
            return
        pattern = wff[1]
        if not (isinstance(pattern, (list, tuple)) and pattern and isinstance(pattern[0], Symbol)):
            return
        head = str(pattern[0])
        if head.startswith("?"):
            return
        existing = self.typing.nodes.get(head)
        if existing is not None and existing.declared:
            return
        rules = self._rules.setdefault(head, [])
        rules.append((list(pattern[1:]), wff[2]))
        self.typing.nodes[head] = NodeType(fn((Type(REST_C, args=(ANY,)),), ANY))  # while its rules infer
        self.typing.nodes[head] = NodeType(infer_signature(rules, self.typing.nodes))

    def _check_bindings(self, name: str, rule: str, bindings: dict) -> None:
        """Every value a :bind gives an axiom's typed ?-variable must be of that type."""
        declared = self.typing.axiom_vars.get(rule, {})
        for var, value in bindings.items():
            target = declared.get(str(var))
            if target is None:
                continue
            errors: list[str] = []
            t = infer(value, self.typing.env(), errors)
            if not assignable(t, target):
                self.typing.error(name, f"{var} of {rule} is {target}, bound to {value}: {t}")

    def _type_derive(self, name: str, wff: Any, rule: "str | None", type_name: object, expect: object) -> None:
        """Type a derive's formula and its value, and classify a rule application's outcome."""
        errors: list[str] = []
        inferred = infer(wff, self.typing.env(), errors)
        for message in errors:
            self.typing.error(name, message)
        declared = self._declared(name, type_name)
        if declared is not None:
            if not assignable(inferred, declared) and not self._narrows(inferred, declared):
                self.typing.error(name, f"formula is {inferred}, declared {declared}")
            elif name in self._derived:
                value = self._derived[name]
                self._check_member(name, value, NodeType(type_of_value(value)), declared)
        self.typing.nodes[name] = NodeType(declared, declared=True) if declared is not None else inferred

        if expect is not None:
            if str(expect) not in OUTCOMES:
                self.typing.error(name, f":expect {expect} is not an outcome ({', '.join(OUTCOMES)})")
            else:
                self.typing.expectations[name] = str(expect)
        is_rule = rule is not None and isinstance(wff, (list, tuple)) and len(wff) == 3 and wff[0] == IMPLIES
        if not is_rule:
            if expect is not None:
                self.typing.error(name, ":expect on a derive that applies no implication rule")
            return
        antecedent = self._holds(wff[1])
        value = self._derived.get(name)
        if isinstance(antecedent, Exception) or not antecedent:
            outcome = VACUOUS
        elif value is False or value is None:
            outcome = VIOLATED
        else:
            outcome = FIRED
        self.typing.outcomes[name] = outcome

    def _deftype(self, expr) -> None:
        """(deftype Name Spec [:order (a < b …)] [:where pred] :evidence …|:origin …)

        Spec is ``(one-of m …)`` (an enumeration), ``(one-of m … :of Parent)`` (a
        subset of Parent's members), or a type expression (a refinement with
        ``:where``, a wrapper without)."""
        name = str(expr[1])
        spec = expr[2] if len(expr) > 2 else None
        origin = self.resolve_origin(expr)
        members: "tuple[str, ...] | None" = None
        base: "Type | None" = ANY
        prefix = name.rsplit(".", 1)[0] + "." if "." in name else ""

        def qualified(m: object) -> str:
            return str(m) if "." in str(m) or not prefix else prefix + str(m)

        if isinstance(spec, (list, tuple)) and spec and spec[0] == ONE_OF:
            parent_expr = get_keyword(spec, KW_OF, None)
            listed = [m for m in spec[1:] if not (isinstance(m, str) and m.startswith(":")) and m is not parent_expr]
            if parent_expr is None:
                members, base = tuple(qualified(m) for m in listed), SYM
            else:
                parent = self.typing.resolve(parent_expr)
                if isinstance(parent, str) or parent.members is None:
                    self.typing.error(name, f":of {parent_expr} is not an enumeration")
                    members, base = tuple(qualified(m) for m in listed), SYM
                else:
                    members, base = tuple(str(m) for m in listed), parent
                    strangers = [m for m in members if m not in parent.members]
                    if strangers:
                        self.typing.error(name, f"{', '.join(strangers)} not members of {parent}")
        elif spec is not None and not (isinstance(spec, str) and spec.startswith(":")):
            resolved = self.typing.resolve(spec)
            if isinstance(resolved, str):
                self.typing.error(name, f"base {resolved}")
            else:
                base = resolved
        else:
            self.typing.error(name, "a deftype needs (one-of …) or a base type")
        order_raw = get_keyword(expr, KW_ORDER, None)
        order = None
        if order_raw is not None:
            order = tuple(qualified(m) for m in order_raw if str(m) != "<")
            if members is None or set(order) != set(members) or base != SYM:
                self.typing.error(name, ":order lists exactly the members of an enumeration that is not a subset")
                order = None
        t = Type(name, base=base, members=members, order=order, where=get_keyword(expr, KW_WHERE, None))
        self.typing.types[name] = t
        self._engine.introduce_term(name, None, origin)
        self.typing.nodes[name] = NodeType(SYM)
        if base == SYM and members is not None:
            self.bind_members(t, self._engine.terms[name].origin)

    def bind_members(self, t: Type, declared_by: object = None) -> None:
        """Bind an enumeration's members to their values: each carries its
        enumeration and rank, so comparisons order it. A member that is not yet a
        node becomes a fact declared by the type; one that is keeps its node and
        is bound to its member value."""
        engine = self._engine
        for member in t.members or ():
            rank = t.order.index(member) if t.order is not None else None
            value = EnumMember(member, t.name, rank)
            if member in engine.facts:
                engine.facts[member] = replace(engine.facts[member], wff=value)
                engine.env[Symbol(member)] = value
            elif member in engine.terms:
                engine.env[Symbol(member)] = value
            else:
                engine.set_fact(member, value, declared_by if declared_by is not None else engine.terms[t.name].origin)
            self.typing.nodes[member] = NodeType(t, declared=True)

    def restore_typing(self, state: TypeState) -> None:
        """Adopt a deserialized typing state and bind its enumerations' members."""
        self.typing = state
        for t in state.types.values():
            if not t.builtin and t.members is not None and t.base == SYM and t.name in self._engine.terms:
                self.bind_members(t)  # a root enumeration; a subset's members are its parent's values
