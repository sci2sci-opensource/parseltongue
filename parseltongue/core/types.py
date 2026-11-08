"""Parseltongue types — built-in types, type expressions, user-defined (nominal) types, the static check.

Every node has a type known before it is evaluated.

**Built-in types.** ``Bool``, ``Num``, ``Sym``, ``Str``, ``Outcome`` and ``Any``
(host values at an explicit boundary). ``Bool`` and ``Num`` are disjoint:
``true`` is not ``1``.

**Type expressions.** A type is written as an s-expression wherever one is
accepted (``:type``, ``:types``, a ``deftype`` base):

- ``(List T)`` — a list of ``T`` (``List`` alone is a list of ``Any``); covariant
- ``(-> A B R)`` — a function of ``A`` and ``B`` returning ``R``; contravariant
  in its parameters, covariant in its result
- ``(union A B)`` — a value of ``A`` or of ``B``
- ``(-> A (Rest T) R)`` — a variadic function: after ``A``, any number of ``T``
- ``?T`` — a type variable, bound by unification where a function is applied

**User-defined types** (``deftype``) are nominal and come in four shapes:

- an **enumeration**, a closed set of members, optionally ordered:
  ``(deftype Severity (one-of note warning error) :order (note < warning < error))``
- a **subset enumeration** of another, whose members are the same values:
  ``(deftype Serious (one-of warning error :of Severity))``
- a **refinement**, a base type with a predicate over ``?x``:
  ``(deftype Count Num :where (>= ?x 0))``
- a **wrapper**, a base type with a different meaning:
  ``(deftype CodeProperty Bool)``

**Gradual typing.** A node whose type was declared (``:type``) is nominal: it is
assignable to its own type and its supertypes only. A node whose type was
inferred carries a structural type, assignable to any declared type whose
representation admits it, so untyped files keep loading and typed ones are
checked strictly.

A type mismatch never stops a load: it is recorded against the node it occurs in
and reported as a ``type_error`` issue by the engine's consistency check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any as _Any

from .atoms import Symbol

LIST_C, FN_C, UNION_C, REST_C = "List", "->", "union", "Rest"


@dataclass(frozen=True)
class Type:
    """A type.

    A built-in or user-defined type has a ``name``; a user-defined one has the
    ``base`` it derives from. An applied constructor (``List``, ``->``,
    ``union``) has its constructor as ``name`` and its parameters as ``args``.
    A type variable has ``var`` set. Types compare by name, arguments and
    variable-ness; a user-defined type is identified by its name.
    """

    name: str
    base: "Type | None" = field(default=None, compare=False)
    members: "tuple[str, ...] | None" = field(default=None, compare=False)  # an enumeration's closed members
    order: "tuple[str, ...] | None" = field(default=None, compare=False)  # ascending member order
    where: _Any = field(default=None, compare=False)  # a refinement's predicate over ?x
    builtin: bool = field(default=False, compare=False)
    args: "tuple[Type, ...]" = ()
    var: bool = False

    def __str__(self) -> str:
        if self.args:
            return f"({self.name} {' '.join(str(a) for a in self.args)})"
        return self.name

    def __hash__(self) -> int:
        return hash((self.name, self.args, self.var))

    @property
    def is_list(self) -> bool:
        return self.name == LIST_C and not self.var

    @property
    def is_fn(self) -> bool:
        return self.name == FN_C and bool(self.args)

    @property
    def is_union(self) -> bool:
        return self.name == UNION_C and bool(self.args)

    @property
    def representation(self) -> "Type":
        """The structural type this type is represented by."""
        t = self
        while t.base is not None:
            t = t.base
        return t


ANY = Type("Any", builtin=True)
BOOL = Type("Bool", builtin=True)
NUM = Type("Num", builtin=True)
SYM = Type("Sym", builtin=True)
STR = Type("Str", builtin=True)
LIST = Type(LIST_C, builtin=True)
OUTCOME = Type("Outcome", base=SYM, members=("fired", "vacuous", "violated"), builtin=True)

BUILTINS: dict[str, Type] = {t.name: t for t in (ANY, BOOL, NUM, SYM, STR, LIST, OUTCOME)}

FIRED, VACUOUS, VIOLATED = "fired", "vacuous", "violated"


def list_of(t: Type) -> Type:
    return Type(LIST_C, args=(t,))


def fn(params: "tuple[Type, ...] | list[Type]", ret: Type) -> Type:
    return Type(FN_C, args=(*params, ret))


def union(*members: Type) -> Type:
    flat: list[Type] = []
    for m in members:
        for x in m.args if m.is_union else (m,):
            if x not in flat:
                flat.append(x)
    return flat[0] if len(flat) == 1 else Type(UNION_C, args=tuple(flat))


def tvar(name: str) -> Type:
    return Type(name, var=True)


def element(t: Type) -> Type:
    """A list type's element type (``Any`` for a bare ``List``)."""
    rep = t.representation
    return rep.args[0] if rep.is_list and rep.args else ANY


@dataclass(frozen=True)
class NodeType:
    """A node's type, and whether it was declared (nominal) or inferred (structural)."""

    type: Type
    declared: bool = False

    def __str__(self) -> str:
        return f"{self.type}" if self.declared else f"{self.type} (inferred)"


# ============================================================
# Subtyping and assignability
# ============================================================


def is_subtype(a: Type, b: Type) -> bool:
    """Whether every value of ``a`` is a value of ``b``."""
    if a == b or b == ANY or a.var or b.var:
        return True
    if b.is_union:
        return any(is_subtype(a, m) for m in b.args)
    if a.is_union:
        return all(is_subtype(m, b) for m in a.args)
    if a.is_list and b.is_list:
        return is_subtype(element(a), element(b))
    if a.is_fn and b.is_fn:
        if len(a.args) != len(b.args):
            return False
        params_ok = all(is_subtype(pb, pa) for pa, pb in zip(a.args[:-1], b.args[:-1]))
        return params_ok and is_subtype(a.args[-1], b.args[-1])
    return a.base is not None and is_subtype(a.base, b)


def assignable(value: NodeType, target: Type) -> bool:
    """Whether a value of ``value``'s type may stand where ``target`` is expected."""
    if target == ANY or value.type == ANY or target.var or value.type.var:
        return True
    if target.is_union:
        return any(assignable(value, m) for m in target.args)
    if value.declared:
        return is_subtype(value.type, target)
    # Inferred: admitted by the target's representation
    rep = target.representation
    if rep == ANY:
        return True
    if value.type.is_list and rep.is_list:
        return assignable(NodeType(element(value.type)), element(rep))
    return is_subtype(value.type, rep)


def comparable(a: NodeType, b: NodeType) -> bool:
    """Whether two values may be compared with ``=`` / ``!=``."""
    if ANY in (a.type, b.type):
        return True
    if a.declared and b.declared:
        return is_subtype(a.type, b.type) or is_subtype(b.type, a.type)
    return assignable(a, b.type) or assignable(b, a.type)


def ordering(t: Type) -> "tuple[str, ...] | None":
    """The member order a type compares by: its own, or the enumeration it derives from."""
    u: "Type | None" = t
    while u is not None:
        if u.order is not None:
            return u.order
        u = u.base
    return None


def enumeration(t: Type) -> "Type | None":
    """The enumeration a type's members belong to: the root enumeration it derives from."""
    found = None
    u: "Type | None" = t
    while u is not None:
        if u.members is not None:
            found = u
        u = u.base
    return found


class EnumMember(Symbol):
    """A member of a declared enumeration, as a value: the symbol, its enumeration and its rank.

    Two members of one ordered enumeration compare by rank; members of different
    enumerations do not compare at all. As a ``Symbol`` it equals its name, so
    everything that reads symbols reads it unchanged.
    """

    enum: str
    rank: "int | None"

    def __new__(cls, name: str, enum: str, rank: "int | None") -> "EnumMember":
        member = super().__new__(cls, name)
        member.enum = enum
        member.rank = rank
        return member


def type_of_value(value: object) -> Type:
    """The structural type of a ground value, as the evaluator produces it."""
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, (int, float)):
        return NUM
    if isinstance(value, Symbol):
        return SYM
    if isinstance(value, str):
        return STR
    if isinstance(value, (list, tuple)):
        items = [type_of_value(v) for v in value]
        return list_of(items[0] if items and all(i == items[0] for i in items) else ANY)
    return ANY


# ============================================================
# Type expressions
# ============================================================


def parse_type(expr: object, types: "dict[str, Type]") -> "Type | str":
    """A type expression as a ``Type``, or the reason it is not one."""
    if isinstance(expr, Symbol):
        s = str(expr)
        if s.startswith("?"):
            return tvar(s)
        found = types.get(s)
        return found if found is not None else f"{s} names no type"
    if isinstance(expr, (list, tuple)) and expr and isinstance(expr[0], Symbol):
        head = str(expr[0])
        parsed = [parse_type(a, types) for a in expr[1:]]
        for p in parsed:
            if isinstance(p, str):
                return p
        args = tuple(p for p in parsed if isinstance(p, Type))
        if head == LIST_C and len(args) == 1:
            return list_of(args[0])
        if head == FN_C and len(args) >= 1:
            if any(a.name == REST_C for a in args[:-2]) or args[-1].name == REST_C:
                return "(Rest T) is only the last parameter of a function type"
            return fn(args[:-1], args[-1])
        if head == REST_C and len(args) == 1:
            return Type(REST_C, args=args)
        if head == UNION_C and len(args) >= 2:
            return union(*args)
        return f"({head} …) is not a type constructor (List, ->, union)"
    return f"{expr!r} is not a type expression"


def type_to_sexp(t: Type) -> object:
    """A type as the expression that writes it."""
    if t.args:
        return [Symbol(t.name), *[type_to_sexp(a) for a in t.args]]
    return Symbol(t.name)


# ============================================================
# Inference
# ============================================================

_LOGIC = frozenset({"and", "or", "not", "implies"})
_ARITH = frozenset({"+", "-", "*", "/", "%"})
_ORDER = frozenset({">", "<", ">=", "<="})
_EQUALITY = frozenset({"=", "!="})


@dataclass
class TypeEnv:
    """What inference reads: node types, and the types bound to ?-variables."""

    nodes: dict[str, NodeType]
    vars: dict[str, Type] = field(default_factory=dict)


def substitute_type(t: Type, subst: "dict[str, Type]") -> Type:
    if t.var:
        return subst.get(t.name, t)
    if t.args:
        return Type(t.name, args=tuple(substitute_type(a, subst) for a in t.args))
    return t


def unify(param: Type, arg: NodeType, subst: "dict[str, Type]") -> bool:
    """Bind ``param``'s type variables from ``arg``; whether ``arg`` fits ``param``."""
    if param.var:
        bound = subst.get(param.name)
        if bound is None:
            subst[param.name] = arg.type
            return True
        if assignable(arg, bound):
            return True
        if assignable(NodeType(bound, declared=True), arg.type):
            subst[param.name] = arg.type  # widen to the more general of the two
            return True
        return False
    if param.is_list and arg.type.representation.is_list:
        return unify(element(param), NodeType(element(arg.type), arg.declared), subst)
    if param.is_fn and arg.type.is_fn and arg.type.args[:-1] and arg.type.args[-2].name == REST_C:
        # A variadic argument function accepts any arity: each parameter meets its rest element
        rest = arg.type.args[-2].args[0]
        for p in param.args[:-1]:
            if p.var:
                unify(p, NodeType(rest, True), subst)
            elif not is_subtype(substitute_type(p, subst), rest):
                return False
        return unify(param.args[-1], NodeType(arg.type.args[-1], True), subst)
    if param.is_fn and arg.type.is_fn and len(param.args) == len(arg.type.args):
        # Contravariant in the parameters: the argument function must accept what the parameter's would
        for p, a in zip(param.args[:-1], arg.type.args[:-1]):
            if p.var or a.var:
                unify(p, NodeType(a, True), subst)
            elif not is_subtype(substitute_type(p, subst), a):
                return False
        return unify(param.args[-1], NodeType(arg.type.args[-1], True), subst)
    return assignable(arg, substitute_type(param, subst))


def infer(expr: object, env: TypeEnv, errors: list[str]) -> NodeType:
    """The type of an expression, appending every mismatch found in it to ``errors``."""
    if isinstance(expr, bool):
        return NodeType(BOOL)
    if isinstance(expr, (int, float)):
        return NodeType(NUM)
    if isinstance(expr, Symbol):
        s = str(expr)
        if s.startswith("?"):
            vt = env.vars.get(s)
            return NodeType(vt, declared=True) if vt is not None else NodeType(ANY)
        if s in ("true", "false"):
            return NodeType(BOOL)
        return env.nodes.get(s, NodeType(ANY))
    if isinstance(expr, str):
        return NodeType(STR)
    if not isinstance(expr, (list, tuple)) or not expr:
        return NodeType(ANY)

    head = str(expr[0]) if isinstance(expr[0], Symbol) else None
    args = expr[1:]
    if head == "quote":
        return NodeType(ANY)
    if head == "strict" and len(args) == 1:
        return infer(args[0], env, errors)
    if head == "if" and len(args) == 3:
        _expect(args[0], infer(args[0], env, errors), BOOL, "if", errors)
        a, b = infer(args[1], env, errors), infer(args[2], env, errors)
        return a if a == b else NodeType(union(a.type, b.type))

    types = [infer(a, env, errors) for a in args]
    if head in _LOGIC:
        for a, at in zip(args, types):
            _expect(a, at, BOOL, head, errors)
        return NodeType(BOOL)
    if head in _ARITH:
        for a, at in zip(args, types):
            _expect(a, at, NUM, head, errors)
        return NodeType(NUM)
    if head in _ORDER:
        for a, at in zip(args, types):
            if ordering(at.type) is None:
                _expect(a, at, NUM, head, errors)
        _all_comparable(head, args, types, errors)
        return NodeType(BOOL)
    if head in _EQUALITY:
        _all_comparable(head, args, types, errors)
        return NodeType(BOOL)
    if head is not None:
        callee = env.nodes.get(head)
        if callee is not None and callee.type.is_fn:
            return _apply(head, callee.type, args, types, errors)
    return NodeType(ANY)


def _apply(head: str, signature: Type, args, types: list[NodeType], errors: list[str]) -> NodeType:
    """A call of a function-typed term: its arguments unify with its parameters."""
    params, ret = signature.args[:-1], signature.args[-1]
    variadic = bool(params) and params[-1].name == REST_C
    fixed = len(params) - 1 if variadic else len(params)
    if (variadic and len(args) < fixed) or (not variadic and len(args) != fixed):
        errors.append(
            f"({head} …): {len(args)} argument(s), its type {signature} takes {fixed}{'+' if variadic else ''}"
        )
        return NodeType(ret)
    subst: dict[str, Type] = {}
    for i, (a, at) in enumerate(zip(args, types)):
        param = params[-1].args[0] if variadic and i >= fixed else params[i]
        if not unify(param, at, subst):
            errors.append(f"({head} …): {_show(a)} is {at}, expected {substitute_type(param, subst)}")
    return NodeType(substitute_type(ret, subst), declared=True)


def _expect(arg: object, t: NodeType, target: Type, where: str, errors: list[str]) -> None:
    if not assignable(t, target):
        errors.append(f"({where} …): {_show(arg)} is {t}, expected {target}")


def _all_comparable(head: str, args, types: list[NodeType], errors: list[str]) -> None:
    for (a, ta), (b, tb) in zip(zip(args, types), list(zip(args, types))[1:]):
        if not comparable(ta, tb):
            errors.append(f"({head} …): {_show(a)} is {ta}, {_show(b)} is {tb}")


def _show(expr: object) -> str:
    if isinstance(expr, bool):
        return "true" if expr else "false"
    if isinstance(expr, (list, tuple)):
        from .grammar import ParseltongueGrammar

        try:
            return str(ParseltongueGrammar.enc(expr))
        except Exception:  # noqa: BLE001 — a display fallback only
            return repr(expr)
    return str(expr)


# The types of the built-in effects, as their call sites see them
EFFECT_TYPES: dict[str, NodeType] = {
    "py-ast": NodeType(fn((STR, STR, Type(REST_C, args=(STR,))), list_of(STR)), declared=True),
}


# ============================================================
# The engine's typing state
# ============================================================


@dataclass
class TypeState:
    """Every type, every node's type, and what the check found, for one engine.

    ``errors`` maps a node to its type mismatches; ``outcomes`` maps a rule
    application to fired / vacuous / violated; ``expectations`` maps it to the
    outcome its ``:expect`` requires; ``judgements`` maps a derive to
    ``theorem`` (it evaluated to a ``Bool``) or ``computation`` (any other value).
    """

    types: dict[str, Type] = field(default_factory=lambda: dict(BUILTINS))
    nodes: dict[str, NodeType] = field(default_factory=lambda: dict(EFFECT_TYPES))
    axiom_vars: dict[str, dict[str, Type]] = field(default_factory=dict)
    errors: dict[str, list[str]] = field(default_factory=dict)
    outcomes: dict[str, str] = field(default_factory=dict)
    expectations: dict[str, str] = field(default_factory=dict)
    judgements: dict[str, str] = field(default_factory=dict)

    def copy(self) -> "TypeState":
        return TypeState(
            types=dict(self.types),
            nodes=dict(self.nodes),
            axiom_vars={k: dict(v) for k, v in self.axiom_vars.items()},
            errors={k: list(v) for k, v in self.errors.items()},
            outcomes=dict(self.outcomes),
            expectations=dict(self.expectations),
            judgements=dict(self.judgements),
        )

    def forget(self, name: str) -> None:
        """Drop everything recorded about a node (it was retracted)."""
        for table in (self.nodes, self.axiom_vars, self.errors, self.outcomes, self.expectations, self.judgements):
            table.pop(name, None)
        if name in self.types and not self.types[name].builtin:
            del self.types[name]

    def env(self, vars: "dict[str, Type] | None" = None) -> TypeEnv:
        return TypeEnv(self.nodes, dict(vars or {}))

    def error(self, name: str, message: str) -> None:
        self.errors.setdefault(name, []).append(message)

    def lookup(self, name: object) -> "Type | None":
        return self.types.get(str(name))

    def references(self) -> dict[str, set[str]]:
        """The declared types each node and each type refers to: a node's ``:type``,
        an axiom's ``:types``, a type's base — every named type in those expressions."""

        def named(t: Type, out: set[str]) -> set[str]:
            if t.args:
                for a in t.args:
                    named(a, out)
            elif not t.var and not t.builtin:
                out.add(t.name)
            return out

        refs: dict[str, set[str]] = {}
        for n, nt in self.nodes.items():
            if nt.declared and n not in EFFECT_TYPES:
                found = named(nt.type, set()) - {n}
                if found and not (nt.type.members and n in (nt.type.members or ())):
                    refs.setdefault(n, set()).update(found)
        for a, vs in self.axiom_vars.items():
            for t in vs.values():
                refs.setdefault(a, set()).update(named(t, set()))
        for name, t in self.types.items():
            if not t.builtin and t.base is not None:
                found = named(t.base, set()) - {name}
                if found:
                    refs.setdefault(name, set()).update(found)
        return {k: v for k, v in refs.items() if v}

    def resolve(self, expr: object) -> "Type | str":
        """A type expression against this state's types."""
        return parse_type(expr, self.types)

    # ----------------------------------------------------------
    # Serialization
    # ----------------------------------------------------------

    def to_dict(self) -> dict:
        from .serialization import serialize_sexp

        def sexp(t: Type) -> object:
            return serialize_sexp(type_to_sexp(t))

        defined = {}
        for name, t in self.types.items():
            if t.builtin:
                continue
            defined[name] = {
                "base": sexp(t.base) if t.base is not None else None,
                "members": list(t.members) if t.members is not None else None,
                "order": list(t.order) if t.order is not None else None,
                "where": serialize_sexp(t.where) if t.where is not None else None,
            }
        return {
            "types": defined,
            "nodes": {n: [sexp(nt.type), nt.declared] for n, nt in self.nodes.items()},
            "axiom_vars": {a: {v: sexp(t) for v, t in vs.items()} for a, vs in self.axiom_vars.items()},
            "errors": {n: list(m) for n, m in self.errors.items()},
            "outcomes": dict(self.outcomes),
            "expectations": dict(self.expectations),
            "judgements": dict(self.judgements),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TypeState":
        from .serialization import deserialize_sexp

        state = cls()
        pending = dict(data.get("types", {}))
        while pending:  # a type is restored once the type it derives from is
            progressed = False
            for name, d in list(pending.items()):
                base: "Type | None" = None
                if d.get("base") is not None:
                    parsed = parse_type(deserialize_sexp(d["base"]), state.types)
                    if isinstance(parsed, str):
                        continue
                    base = parsed
                state.types[name] = Type(
                    name,
                    base=base,
                    members=tuple(d["members"]) if d.get("members") is not None else None,
                    order=tuple(d["order"]) if d.get("order") is not None else None,
                    where=deserialize_sexp(d["where"]) if d.get("where") is not None else None,
                )
                del pending[name]
                progressed = True
            if not progressed:
                raise ValueError(f"types derive from types that are not serialized: {', '.join(sorted(pending))}")

        def typ(raw: object) -> Type:
            t = parse_type(deserialize_sexp(raw), state.types)
            if isinstance(t, str):
                raise ValueError(t)
            return t

        state.nodes = {n: NodeType(typ(t), bool(declared)) for n, (t, declared) in data.get("nodes", {}).items()}
        state.axiom_vars = {a: {v: typ(t) for v, t in vs.items()} for a, vs in data.get("axiom_vars", {}).items()}
        state.errors = {n: list(m) for n, m in data.get("errors", {}).items()}
        state.outcomes = dict(data.get("outcomes", {}))
        state.expectations = dict(data.get("expectations", {}))
        state.judgements = dict(data.get("judgements", {}))
        return state
