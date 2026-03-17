"""OperationsSystem v2 — fast Python dispatch over tagged sentence lists.

Replaces pltg rewrite axioms with direct Python set operations.
Collects OpsMorphisms from registered subsystems, builds OpsView
per list, dispatches by regime:

    Pointer (and/not/or): set ops on extracted keys, bodies untouched.
    Vectorized (count/limit): len/slice on the list itself.

When all forms share one tag, that system's morphism decides identity.
Mixed tags: partition by tag, per-tag dispatch, merge.

Falls through to pltg engine for unknown operations.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import Any

from parseltongue.core.atoms import Symbol
from parseltongue.core.lang import DSL_KEYWORDS

from .bench_system import BenchSubsystem, OpsView, Posting


class _OpsPostingMorphism:
    """Dispatch morphism — routes mixed-tag forms to registered subsystem morphisms."""

    def __init__(self):
        self._dispatch: dict[Symbol, BenchSubsystem] = {}

    def register(self, subsystem: BenchSubsystem):
        self._dispatch[subsystem.tag] = subsystem

    def unregister(self, tag: Symbol):
        self._dispatch.pop(tag, None)

    def transform(self, posting: Posting) -> list:
        result = []
        for subsystem in self._dispatch.values():
            result.extend(subsystem.posting_morphism.transform(posting))
        return result

    def inverse(self, forms: list) -> Posting:
        posting: Posting = {}
        by_tag: dict[Symbol, list] = {}
        for item in forms:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], Symbol):
                by_tag.setdefault(item[0], []).append(item)
        for tag, items in by_tag.items():
            subsystem = self._dispatch.get(tag)
            if subsystem is None:
                base = Symbol(str(tag).rsplit(".", 1)[-1])
                subsystem = self._dispatch.get(base)
            if subsystem is not None:
                posting.update(subsystem.posting_morphism.inverse(items))
        return posting


class OperationsSystemV2:
    """Fast operations over tagged sentence lists.

    Two regimes:
    - Pointer: and/or/not — set ops on identity keys, never touch bodies.
    - Vectorized: count/limit — len/slice on the list.

    Subsystems register their OpsMorphism. Ops builds OpsView per list,
    delegates key extraction to the owning morphism. Single-system lists
    use that system's morphism directly. Mixed lists partition by tag.
    """

    tag = Symbol("ops")

    def __init__(self):
        self.posting_morphism = _OpsPostingMorphism()
        self._scopes: dict[str, Any] = {}
        self._ops_morphisms: dict[Symbol, Any] = {}  # tag → OpsMorphism

        # Fast-path dispatch table: symbol name → handler
        self._fast_ops: dict[str, Any] = {
            "and-forms": self._fast_and,
            "or-forms": self._fast_or,
            "not-forms": self._fast_not,
            "count-forms": self._fast_count,
            "limit-forms": self._fast_limit,
            "str": self._fast_str,
            "list": self._fast_list,
            "V": self._fast_v,
        }

        # Pltg fallback — delegates to OperationsSystem (v1) for full namespace resolution
        self._ops_v1 = None

    def _ensure_pltg(self):
        """Delegate to OperationsSystem (v1) for full pltg fallback."""
        if self._ops_v1 is not None:
            return self._ops_v1.system

        from .operations import OperationsSystem

        self._ops_v1 = OperationsSystem()

        # Wire existing scopes into v1
        for name, scope_system in self._scopes.items():
            self._ops_v1.register_scope(name, scope_system)

        return self._ops_v1.system

    # ── Key extraction ──

    def _key_fn(self, form: Sequence) -> Hashable:
        """Extract identity key from any tagged form.

        Dispatches to the registered OpsMorphism for the form's head tag.
        Falls back to object id for unknown tags.
        """
        if isinstance(form, (list, tuple)) and form and isinstance(form[0], Symbol):
            tag = form[0]
            morph = self._ops_morphisms.get(tag)
            if morph is None:
                # Canonical name: specialized_ops.lens.ln → ln
                base = Symbol(str(tag).rsplit(".", 1)[-1])
                morph = self._ops_morphisms.get(base)
            if morph is not None:
                return morph.key(form)
        return id(form)

    def _view(self, forms: list) -> OpsView:
        """Build an OpsView over a list of tagged forms."""
        return OpsView(forms, self._key_fn)

    # ── Pointer regime: set operations ──

    def _fast_and(self, args: list) -> list | None:
        a, b = self._resolve_pair(args)
        if a is None or b is None:
            return None
        return self._view(a).intersect(self._view(b))

    def _fast_or(self, args: list) -> list | None:
        a, b = self._resolve_pair(args)
        if a is None or b is None:
            return None
        return self._view(a).union(self._view(b))

    def _fast_not(self, args: list) -> list | None:
        a, b = self._resolve_pair(args)
        if a is None or b is None:
            return None
        return self._view(a).difference(self._view(b))

    # ── Vectorized regime ──

    def _fast_count(self, args: list) -> int | None:
        if len(args) != 1:
            return None
        xs = self._resolve_arg(args[0])
        if not isinstance(xs, list):
            return None
        return len(xs)

    def _fast_limit(self, args: list) -> list | None:
        if len(args) != 2:
            return None
        n = args[0]
        if not isinstance(n, int):
            try:
                n = int(n)
            except (TypeError, ValueError):
                return None
        xs = self._resolve_arg(args[1])
        if not isinstance(xs, list):
            return None
        return self._view(xs).limit(n)

    def _fast_v(self, args: list) -> list | None:
        """(V expr) — resolve expr and tag result as vectorizable."""
        if len(args) != 1:
            return None
        xs = self._resolve_arg(args[0])
        if not isinstance(xs, (list, tuple)):
            return None
        return [self._V] + list(xs)

    # ── Generic Python bridge ──

    # Aliases for common ops that don't map directly to Python method names
    _METHOD_ALIASES = {"get": "__getitem__", "len": "__len__", "set": "__setitem__"}
    # Builtins that operate on the whole target, not via getattr
    _LIST_BUILTINS = {
        "unique": lambda t, *_: list(dict.fromkeys(t)),
        "flat": lambda t, *_: OperationsSystemV2._deep_flat(t),
        "sorted": lambda t, *_: sorted(t, key=str),
        "truncate": lambda t, n, *_: t[: int(n)],
        "filter": lambda t, *args: [x for x in t if x == args[0]] if args else [x for x in t if x],
    }

    @staticmethod
    def _deep_flat(t):
        """Recursively flatten nested lists, filtering out Symbol artifacts from cons-prepend."""
        out = []
        for item in t:
            if isinstance(item, (list, tuple)):
                out.extend(OperationsSystemV2._deep_flat(item))
            elif isinstance(item, Symbol):
                continue  # skip cons-prepend tag symbols
            else:
                out.append(item)
        return out

    # V marker — explicit vectorization signal
    _V = Symbol("V")

    _DIRECTIVES = frozenset(DSL_KEYWORDS)

    def _should_vectorize(self, val) -> bool:
        """True if val is V-marked, list of registered scope forms, or list of directives."""
        if not isinstance(val, (list, tuple)) or not val:
            return False
        head = val[0]
        # Explicit V marker
        if isinstance(head, Symbol) and str(head) == "V":
            return True
        # List of tagged forms — check first element's head
        if isinstance(head, (list, tuple)) and head and isinstance(head[0], Symbol):
            tag = head[0]
            # Registered scope tags
            if tag in self._ops_morphisms:
                return True
            base = Symbol(str(tag).rsplit(".", 1)[-1])
            if base in self._ops_morphisms:
                return True
            # DSL directives
            if tag in self._DIRECTIVES:
                return True
        return False

    @staticmethod
    def _strip_v(val):
        """Strip V marker if present, return bare list."""
        if isinstance(val, (list, tuple)) and val and isinstance(val[0], Symbol) and str(val[0]) == "V":
            return list(val[1:])
        return val

    @classmethod
    def _bridge(cls, target, method_name: str, extra: list, coerce=None, vectorize: bool = False):
        """Get method, apply. Vectorize ONLY when explicitly flagged."""
        method_name = cls._METHOD_ALIASES.get(method_name, method_name)

        def _apply(t, *ex):
            obj = coerce(t) if coerce else t
            return getattr(obj, method_name)(*ex)

        if vectorize and isinstance(target, (list, tuple)):
            return [_apply(item, *extra) for item in target]
        return _apply(target, *extra)

    def _vectorize_call(self, all_args, apply_fn):
        """Zip-vectorize over any V-marked / registered-scope arguments. Others broadcast."""
        vec_indices = [i for i, a in enumerate(all_args) if self._should_vectorize(a)]
        if not vec_indices:
            return apply_fn(*all_args)
        stripped = [self._strip_v(a) if i in vec_indices else a for i, a in enumerate(all_args)]
        n = len(stripped[vec_indices[0]])
        result = []
        for j in range(n):
            row = [stripped[i][j] if i in vec_indices else stripped[i] for i in range(len(stripped))]
            result.append(apply_fn(*row))
        return result

    def _fast_str(self, args: list) -> Any:
        """(str method target *args) — vectorizes over V-marked or registered scope args."""
        if len(args) < 2:
            return None
        method_name = self._METHOD_ALIASES.get(str(args[0]), str(args[0]))
        resolved = [self._resolve_arg(a) for a in args[1:]]

        def _apply(*a):
            return getattr(str(a[0]), method_name)(*a[1:])

        return self._vectorize_call(resolved, _apply)

    def _fast_list(self, args: list) -> Any:
        """(list method target *args) — vectorizes over V-marked or registered scope args."""
        if len(args) < 2:
            return None
        method_name = str(args[0])
        resolved = [self._resolve_arg(a) for a in args[1:]]
        builtin = self._LIST_BUILTINS.get(method_name)
        if builtin is not None:
            _builtin = builtin  # bind for closure

            def _apply_builtin(*a):
                return _builtin(*a)  # type: ignore[operator]

            return self._vectorize_call(resolved, _apply_builtin)
        real_name = self._METHOD_ALIASES.get(method_name, method_name)

        def _apply(*a):
            return getattr(a[0], real_name)(*a[1:])

        return self._vectorize_call(resolved, _apply)

    # ── Argument resolution ──

    def _resolve_arg(self, arg):
        """Resolve an argument: evaluate scope expressions, fall through to pltg."""
        if isinstance(arg, list) and arg and isinstance(arg[0], Symbol):
            head = str(arg[0])
            # (scope name expr) form
            if head == "scope" and len(arg) >= 3:
                scope_name = str(arg[1])
                return self._scope(scope_name, *arg[2:])
            # Is it a scope call?
            if head in self._scopes:
                return self._scopes[head].evaluate(arg[1:] if len(arg) > 1 else arg)
            # Is it a fast op?
            if head in self._fast_ops:
                result = self._fast_ops[head](arg[1:])
                if result is not None:
                    return result
            # Fall through to pltg for unknown ops (keys, map, etc.)
            return self._ensure_pltg().evaluate(arg)
        return arg

    def _resolve_pair(self, args: list) -> tuple[list | None, list | None]:
        """Resolve a pair of arguments for binary ops."""
        if len(args) != 2:
            return None, None
        a = self._resolve_arg(args[0])
        b = self._resolve_arg(args[1])
        if not isinstance(a, list) or not isinstance(b, list):
            return None, None
        return a, b

    # ── Scope management ──

    def _scope(self, name, *args):
        if name not in self._scopes:
            raise KeyError(f"Unknown scope: {name!r}. Registered: {list(self._scopes)}")
        scope_system = self._scopes[name]
        result = None
        for arg in args:
            if isinstance(arg, (list, tuple)):
                result = scope_system.evaluate(arg)
            else:
                result = arg
        return result

    def register_scope(self, name: str, scope_system):
        """Register a scope. Collects OpsMorphism if available."""
        self._scopes[name] = scope_system
        if hasattr(scope_system, "tag") and hasattr(scope_system, "posting_morphism"):
            self.posting_morphism.register(scope_system)
        if hasattr(scope_system, "ops_morphism") and scope_system.ops_morphism is not None:
            self._ops_morphisms[scope_system.tag] = scope_system.ops_morphism

        # Wire into v1 fallback if it exists (lazy — may not be built yet)
        if self._ops_v1 is not None:
            self._ops_v1.register_scope(name, scope_system)

    # ── Evaluate ──

    def evaluate(self, expr, local_env=None):
        """Evaluate an expression. Fast-path for known ops, pltg fallback."""
        if isinstance(expr, (list, tuple)) and len(expr) >= 2:
            head = expr[0]
            if isinstance(head, Symbol):
                op = str(head)
                handler = self._fast_ops.get(op)
                if handler is not None:
                    result = handler(list(expr[1:]))
                    if result is not None:
                        return result
                    # Fast-path returned None → fall through to pltg

        # Fallback: full pltg rewrite engine
        return self._ensure_pltg().evaluate(expr)
