"""BenchSystem — base class and protocols for bench subsystems.

BenchSubsystem protocol: a Rewriter with a PostingMorphism and a tag.
Each subsystem (Lens, Screen, Hologram search systems) implements
BenchSubsystem so the Search layer can dispatch tagged forms back to
postings by head symbol.

OpsMorphism protocol: key extraction for fast pointer/vectorized ops.
Subsystems implement this to tell ops how to identify their forms.
OpsView: lazy batch view over tagged forms — pointer and vectorized regimes.

BenchSystem: base class for frozen/live bench systems with scope registration.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import TYPE_CHECKING, Protocol

from parseltongue.core.atoms import Symbol

if TYPE_CHECKING:
    from parseltongue.core.system import System


# Posting dict: {(doc_name, line_num): {document, line, column, context, callers, total_callers}}
Posting = dict[tuple[str, int], dict]

# DocSet: Posting with line_num=0 — doc-level entries from match_docs / 1-arg (in)
DocSet = Posting


class PostingMorphism(Protocol):
    """Bidirectional map between posting dicts and tagged forms.

    transform:  posting → tagged forms (for pltg-native output)
    inverse:    tagged forms → posting (for display/ranking)
    """

    def transform(self, posting: Posting) -> list: ...
    def inverse(self, forms: list) -> Posting: ...


class OpsMorphism(Protocol):
    """Key extraction for fast operations over tagged forms.

    Subsystems implement this to define identity for their forms.
    Ops never touches the body — just the key. The subsystem decides
    what constitutes identity (name, (doc, line), etc.).

    Two regimes use this:
    - Pointer: set ops (and/not/or) on key sets, bodies untouched.
    - Vectorized: count/limit/future aggregation on the list itself.
    """

    def key(self, form: Sequence) -> Hashable:
        """Extract identity key from a single tagged form."""
        ...


class OpsView:
    """Lazy indexed view over tagged forms for fast batch operations.

    Pointer regime: extract keys, do set ops, reconstruct from winners.
    Bodies are never copied or inspected — only indices and keys.

    Vectorized regime: len/slice on the underlying list.
    Future: columnar decomposition for numeric aggregation.
    """

    __slots__ = ("forms", "_key_fn", "_keys", "_key_set")

    def __init__(self, forms: list, key_fn: Callable[[Sequence], Hashable]):
        self.forms = forms
        self._key_fn = key_fn
        self._keys: list[Hashable] | None = None
        self._key_set: set[Hashable] | None = None

    @property
    def keys(self) -> list[Hashable]:
        if self._keys is None:
            self._keys = [self._key_fn(f) for f in self.forms]
        return self._keys

    def key_set(self) -> set[Hashable]:
        if self._key_set is None:
            self._key_set = set(self.keys)
        return self._key_set

    # ── Pointer regime: set operations ──

    def intersect(self, other: OpsView) -> list:
        """AND: forms from self whose key appears in other."""
        keep = other.key_set()
        return [f for f, k in zip(self.forms, self.keys) if k in keep]

    def difference(self, other: OpsView) -> list:
        """NOT: forms from self whose key does NOT appear in other."""
        exclude = other.key_set()
        return [f for f, k in zip(self.forms, self.keys) if k not in exclude]

    def union(self, other: OpsView) -> list:
        """OR: all from self, plus forms from other whose key is new."""
        seen = self.key_set()
        return self.forms + [f for f, k in zip(other.forms, other.keys) if k not in seen]

    # ── Vectorized regime ──

    def __len__(self) -> int:
        return len(self.forms)

    def limit(self, n: int) -> list:
        return self.forms[:n]


class BenchSubsystem(Protocol):
    """A bench subsystem: evaluates expressions and maps results to/from postings.

    tag:               head Symbol that identifies this subsystem's forms (ln, dx, hn, sr)
    posting_morphism:  bidirectional map between posting dicts and tagged forms
    evaluate:          Rewriter — evaluates s-expressions
    """

    tag: Symbol
    posting_morphism: PostingMorphism

    @property
    def data_tags(self) -> list[Symbol]:
        """All Symbol tags that appear as data markers in this subsystem's forms.

        Includes the head tag and any sub-tags (e.g. ln-ev for evidence sublists).
        Collected on scope registration so the parent engine can self-quote them.
        """
        return [self.tag]

    def evaluate(self, expr: Sentence, local_env: dict | None = None) -> Sentence: ...

    @staticmethod
    def matches_tag(head: Symbol, tag: Symbol) -> bool:
        """Check if head symbol matches tag, accounting for canonical namespacing.

        Matches both bare (ln) and canonical (specialized_ops.lens.ln) forms.
        """
        return head == tag or str(head).endswith("." + str(tag))


class BenchSystem:
    """Base for bench systems. Provides scope and perspective registration.

    Perspectives are keyed by name ("md", "ascii", "viz", ...). The ``fmt``
    callable in the engine env rewrites a bench form into a display form
    (via view.pltg axioms) then dispatches to the named perspective's
    ``render_form`` / ``render_form_list``.
    """

    system: System

    def __init_perspectives__(self):
        if not hasattr(self, "_perspectives"):
            self._perspectives: dict[str, "Perspective"] = {}

    def register_scope(self, name: str, scope_system):
        """Register a scope system as a callable in engine env.

        Calls scope_system.evaluate(expr) which returns raw pltg results
        (posting sets, scalars, lists — whatever the system produces).
        """

        def _scope_fn(_name, *args):
            result = None
            for arg in args:
                result = scope_system.evaluate(arg)
            return result

        self.system.engine.env[Symbol(name)] = _scope_fn

        # Data tags from scope results must be self-quoting in the engine.
        for tag in getattr(scope_system, "data_tags", [getattr(scope_system, "tag", None)]):
            if tag is not None and tag not in self.system.engine.env:
                self.system.engine.env[tag] = tag

    def register_hologram_scope(self, engine=None):
        """Register (scope hologram (dissect ...) | (compose ...)).

        HologramSystem owns dissect/compose as operators in its own
        System — the engine never sees them. register_scope passes args
        unevaluated through to hs.evaluate().

        engine: the sample engine (has diffs). Falls back to self.system.engine.
        """
        from parseltongue.core.inspect.systems.hologram import HologramSystem

        hs = HologramSystem(engine=engine or self.system.engine)
        self.register_scope("hologram", hs)

    def register_renderer(self, name: str, renderer: "FormRenderer"):
        """Register a FormRenderer for (fmt "name" value)."""
        self.__init_perspectives__()
        self._perspectives[name] = renderer
        self._ensure_fmt()

    def get_renderer(self, name: str) -> "FormRenderer | None":
        """Get a registered FormRenderer by name."""
        self.__init_perspectives__()
        return self._perspectives.get(name)

    def _ensure_fmt(self):
        """Install fmt callable + -fmt tag callables.

        (fmt "viz" single-form) → axiom rewrite → (ln-fmt "viz" ...) → renderer
        (fmt "viz" list-of-forms) → iterate, rewrite each, collect → renderer

        The fmt callable handles both single forms and lists.
        The -fmt tag callables dispatch to the registered renderer.
        """
        if getattr(self, "_fmt_installed", False):
            return
        self._fmt_installed = True
        bench_sys = self

        _BENCH_TAGS = {"sr", "ln", "dx", "hn"}
        _FMT_TAGS = {"sr-fmt", "ln-fmt", "dx-fmt", "hn-fmt"}

        def _bare_tag(item):
            if isinstance(item, (list, tuple)) and item and isinstance(item[0], Symbol):
                return str(item[0]).rsplit(".", 1)[-1]
            return None

        # Rewrite map mirrors view.pltg axioms:
        #   (fmt ?p (sr ?doc ?line ?col ?ctx ?callers)) → (sr-fmt ?p ?doc ?line ?ctx ?callers)
        #   (fmt ?p (ln ?name ?kind ?val ?depth ?inputs)) → (ln-fmt ?p ?name ?kind ?val ?depth ?inputs)
        #   (fmt ?p (dx ?name ?cat ?kind ?type ?detail)) → (dx-fmt ?p ?name ?cat ?kind ?type ?detail)
        #   (fmt ?p (hn ?name ?kind ?val ?lenses)) → (hn-fmt ?p ?name ?kind ?val ?lenses)
        _TAG_TO_FMT = {
            "sr": "sr-fmt",
            "ln": "ln-fmt",
            "dx": "dx-fmt",
            "hn": "hn-fmt",
        }

        def _rewrite_one(perspective_name, form):
            """Apply view.pltg axiom rewrite in Python — no engine call."""
            tag = _bare_tag(form)
            fmt_tag = _TAG_TO_FMT.get(tag)
            if not fmt_tag:
                return form
            fields = list(form[1:])
            # sr drops column (index 2): (sr doc line col ctx callers) → (sr-fmt p doc line ctx callers)
            if tag == "sr" and len(fields) >= 5:
                fields = [fields[0], fields[1]] + fields[3:]
            return [Symbol(fmt_tag), perspective_name] + fields

        def _fmt(renderer_name, *args):
            bench_sys.__init_perspectives__()
            r = bench_sys._perspectives.get(str(renderer_name))
            if not args:
                return []
            val = args[0]
            if r is None:
                return val
            tag = _bare_tag(val)
            # Single bench form
            if tag in _BENCH_TAGS:
                fmt_result = _rewrite_one(renderer_name, val)
                if fmt_result and _bare_tag(fmt_result) in _FMT_TAGS:
                    return r.fmt(fmt_result)
                return r.fmt(val)
            # Already a -fmt form
            if tag in _FMT_TAGS:
                return r.fmt(val)
            # List of bench forms
            if isinstance(val, (list, tuple)) and val and _bare_tag(val[0]) in _BENCH_TAGS:
                fmt_forms = []
                for item in val:
                    fmt_result = _rewrite_one(renderer_name, item)
                    if fmt_result and _bare_tag(fmt_result) in _FMT_TAGS:
                        fmt_forms.append(fmt_result)
                    else:
                        fmt_forms.append(item)
                return r.fmt(fmt_forms)
            # List of -fmt forms
            if isinstance(val, (list, tuple)) and val and _bare_tag(val[0]) in _FMT_TAGS:
                return r.fmt(val)
            # Non-form value
            return r.fmt(val)

        # Override the defterm — callable takes priority in env
        self.system.engine.env[Symbol("fmt")] = _fmt
        self.system.engine.env[Symbol("bench_pg.view.fmt")] = _fmt

        # Also install -fmt tags as callables for direct use
        for tag_name in _FMT_TAGS:

            def _make_fmt_callable(t):
                def _fmt_tag(perspective_name, *args):
                    bench_sys.__init_perspectives__()
                    r = bench_sys._perspectives.get(str(perspective_name))
                    if r is None:
                        return [Symbol(t), perspective_name] + list(args)
                    form = [Symbol(t), perspective_name] + list(args)
                    return r.fmt(form)

                return _fmt_tag

            callable_fn = _make_fmt_callable(tag_name)
            self.system.engine.env[Symbol(tag_name)] = callable_fn
            self.system.engine.env[Symbol(f"bench_pg.view.{tag_name}")] = callable_fn
