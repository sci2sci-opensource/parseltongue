"""HologramSystem — S-expression query language over a Hologram (N lenses).

Wraps N LensSearchSystems. Operators select, filter, and compare across lenses.

Operators (after dissect/compose creates a hologram)::

    (left ...)              — evaluate in the first lens
    (right ...)             — evaluate in the last lens
    (lens N ...)            — evaluate in the Nth lens (0-based)
    (divergent)             — nodes present in some lenses but not all
    (common)                — nodes present in all lenses
    (only N)                — nodes only in lens N

Scope operators (create hologram from engine)::

    (dissect "diff-name")   — dissect a diff into 2 lenses
    (compose name1 name2)   — compose N names into N lenses

Registered as ``(scope hologram ...)`` in the main search system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from parseltongue.core.atoms import Symbol
from parseltongue.core.system import System

from .bench_system import BenchSubsystem
from .lens import LensSearchSystem

log = logging.getLogger("parseltongue.holograms")

if TYPE_CHECKING:
    from ..optics.hologram import Hologram


class HologramSystem:
    """Parseltongue System with operators over N lenses combined.

    Can be created with a Hologram (direct use) or with an engine
    (scope use — dissect/compose create holograms lazily).
    """

    tag = Symbol("hn")
    diff_tag = Symbol("df")
    name = "hologram"

    def __init__(self, hologram: "Hologram | None" = None, engine=None, result=None):
        log.info("HologramSystem init: hologram=%s engine=%s", hologram is not None, engine is not None)
        self._hologram = hologram
        self._engine = engine
        self._lens_systems: list[LensSearchSystem] = []
        self._all_names: set[str] = set()
        self._names_per_lens: list[set[str]] = []
        self._diff_meta: list | None = None

        if result is not None:
            from ..probe_core_to_consequence import probe_diffs

            self._diff_meta = probe_diffs(result)
            if engine is None:
                self._engine = result.system.engine

        if hologram is not None:
            self._init_from_hologram(hologram)

        sys = self  # capture

        # ── Hologram query operators (work after _init_from_hologram) ──

        def _posting_from_lens(lens_idx: int, names):
            ls = sys._lens_systems[lens_idx]
            result = {}
            for n in names:
                doc = ls._idx.documents.get(n)
                if doc:
                    result[(n, 1)] = {
                        "document": n,
                        "line": 1,
                        "column": 1,
                        "context": doc.original_text.splitlines()[0] if doc.original_text else "",
                        "callers": [],
                        "total_callers": 0,
                    }
            return result

        def _left(*args):
            if not sys._lens_systems:
                return {}
            if args:
                return sys._lens_systems[0]._system.evaluate(args[0] if len(args) == 1 else list(args))
            return _posting_from_lens(0, sys._names_per_lens[0])

        def _right(*args):
            if not sys._lens_systems:
                return {}
            last = len(sys._lens_systems) - 1
            if args:
                return sys._lens_systems[last]._system.evaluate(args[0] if len(args) == 1 else list(args))
            return _posting_from_lens(last, sys._names_per_lens[last])

        def _lens(n, *args):
            n = int(n)
            if n < 0 or n >= len(sys._lens_systems):
                raise IndexError(f"Lens index {n} out of range (0-{len(sys._lens_systems) - 1})")
            if args:
                return sys._lens_systems[n]._system.evaluate(args[0] if len(args) == 1 else list(args))
            return _posting_from_lens(n, sys._names_per_lens[n])

        def _divergent():
            if not sys._names_per_lens:
                return {}
            shared = set.intersection(*sys._names_per_lens) if sys._names_per_lens else set()
            diff = sys._all_names - shared
            result = {}
            for n in diff:
                for i, names in enumerate(sys._names_per_lens):
                    if n in names:
                        result.update(_posting_from_lens(i, [n]))
                        break
            return result

        def _neutral():
            """All nodes from all lenses, side by side (no subtraction)."""
            if not sys._names_per_lens:
                return {}
            result = {}
            for i, names in enumerate(sys._names_per_lens):
                result.update(_posting_from_lens(i, names))
            return result

        def _common():
            if not sys._names_per_lens:
                return {}
            shared = set.intersection(*sys._names_per_lens)
            return _posting_from_lens(0, shared)

        def _only(n):
            n = int(n)
            if n < 0 or n >= len(sys._names_per_lens):
                raise IndexError(f"Lens index {n} out of range")
            exclusive = sys._names_per_lens[n] - set.union(*(s for i, s in enumerate(sys._names_per_lens) if i != n))
            return _posting_from_lens(n, exclusive)

        # ── Scope operators (create hologram from engine) ──

        def _is_stained(val):
            """Check if val is a stain-tagged value."""
            return isinstance(val, (list, tuple)) and val and val[0] == _STAIN_TAG

        def _unwrap_stain(val):
            """Unwrap stain tag, return (inner_value, use_live)."""
            if _is_stained(val):
                inner = val[1] if len(val) == 2 else val[1:]
                return inner, True
            return val, False

        def _do_probe(name, eng, live):
            """Probe a name — live if requested, static otherwise."""
            if live:
                from ..vital import live_probe, trace_engine

                traced = trace_engine(eng, names=[name])
                return live_probe(name, eng, traced, store="names")
            from ..probe_core_to_consequence import probe as _probe

            return _probe(name, eng)

        def _dissect(diff_name, *args):
            """(dissect "diff-name") or (dissect (stain "diff-name"))."""
            from ..optics.hologram import Hologram
            from ..optics.lens import Lens

            eng = sys._engine
            if eng is None:
                log.warning("dissect: no engine available")
                return {}
            diff_name, live = _unwrap_stain(diff_name)
            diff_name = str(diff_name)
            log.info("dissect: diff_name=%s live=%s", diff_name, live)
            diff = eng.diffs[diff_name]
            left = Lens(_do_probe(diff["replace"], eng, live))
            right = Lens(_do_probe(diff["with"], eng, live))
            diff_result = eng.eval_diff(diff_name)
            holo = Hologram(
                [left, right],
                name=diff_name,
                labels=[diff["replace"], diff["with"]],
                diff_result=diff_result,
            )
            sys._init_from_hologram(holo)
            if args:
                return sys._system.evaluate(args[0] if len(args) == 1 else list(args))
            return _divergent()

        def _compose(*args):
            """(compose name1 name2 ...) or (compose (stain "n1") (stain "n2") ...)."""
            from ..optics.hologram import Hologram
            from ..optics.lens import Lens

            eng = sys._engine
            if eng is None:
                return {}
            lenses = []
            labels = []
            for a in args:
                name, live = _unwrap_stain(a)
                name = str(name)
                labels.append(name)
                lenses.append(Lens(_do_probe(name, eng, live)))
            holo = Hologram(lenses, labels=labels)
            sys._init_from_hologram(holo)
            return _divergent()

        _STAIN_TAG = Symbol("__stain__")

        def _stain(*args):
            """(stain expr) — marker: tag expr for live probing.

            Returns [__stain__, expr] — a tagged value that dissect/compose
            recognize and handle by using live_probe instead of static probe.
            Pure: no side effects.
            """
            if len(args) == 1:
                return [_STAIN_TAG, args[0]]
            return [_STAIN_TAG] + list(args)

        ops = {
            Symbol("left"): _left,
            Symbol("right"): _right,
            Symbol("lens"): _lens,
            Symbol("neutral"): _neutral,
            Symbol("divergent"): _divergent,
            Symbol("common"): _common,
            Symbol("only"): _only,
            Symbol("dissect"): _dissect,
            Symbol("compose"): _compose,
            Symbol("stain"): _stain,
        }
        self._system = System(initial_env=ops, docs={}, strict_derive=False, name="HologramSearch")
        self.posting_morphism = self._HnPostingMorphism(self)
        self.ops_morphism = self._HnOpsMorphism()

        # Wrap evaluate: internal operators use posting sets,
        # but the system produces s-expressions (hn forms) at the boundary
        _raw_eval = self._system.evaluate
        _to_hn = self._posting_to_hn

        def _sexp_evaluate(expr):
            result = _raw_eval(expr)
            if isinstance(result, dict):
                return _to_hn(result)
            return result

        self._system.evaluate = _sexp_evaluate  # type: ignore[method-assign, assignment]

    def _init_from_hologram(self, hologram: "Hologram"):
        """(Re-)initialize lens systems from a hologram."""
        self._hologram = hologram
        self._lens_systems = [LensSearchSystem(lens._structure) for lens in hologram._lenses]
        self._all_names = set()
        self._names_per_lens = []
        for ls in self._lens_systems:
            names = set(ls._structure.graph.keys()) - {"__output__"}
            self._names_per_lens.append(names)
            self._all_names |= names

    def _diff_names(self) -> set[str]:
        """All diff names from the engine (available even without a hologram)."""
        if self._engine is not None and hasattr(self._engine, "diffs"):
            return set(self._engine.diffs)
        return set()

    def _diff_meta_by_name(self) -> dict:
        """Index probe_diffs metadata by name."""
        if self._diff_meta is None:
            return {}
        return {dm.name: dm for dm in self._diff_meta}

    def _enrich(self, name: str) -> str:
        """Enrich a name with metadata from probe_diffs."""
        meta = self._diff_meta_by_name()
        if name in meta:
            dm = meta[name]
            loc = f"{dm.source_file}:{dm.source_line}" if dm.source_file else ""
            return f"{name}  diff  {dm.replace} ({dm.replace_kind}) → {dm.with_} ({dm.with_kind})  {loc}"
        return name

    def find(self, pattern: str, max_results: int = 50) -> list[str]:
        import re as _re

        rx = _re.compile(pattern)
        pool = self._all_names | self._diff_names()
        matches = sorted(n for n in pool if rx.search(n))
        return [self._enrich(n) for n in matches[:max_results]]

    def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        query_lower = query.lower()
        scored = []
        for name in self._all_names | self._diff_names():
            name_lower = name.lower()
            if query_lower not in name_lower:
                continue
            if name_lower == query_lower:
                score = 0
            elif name_lower.endswith(query_lower):
                score = 1
            elif name_lower.startswith(query_lower):
                score = 2
            else:
                score = 3
            scored.append((score, len(name), name))
        scored.sort()
        return [self._enrich(name) for _, _, name in scored[:max_results]]

    class _HnOpsMorphism:
        __slots__ = ()

        def key(self, form):
            return form[1]

    class _HnPostingMorphism:
        """PostingMorphism: posting <-> hn forms.

        hn form: (hn <biased_lens0_ln> <biased_lens1_ln> ...)
        Each biased lens is the ln form after structural bias subtraction.
        Bias operates element-wise on the homoiconic ln form lists:
          neutral  — no subtraction, full forms
          left     — left unchanged, right = right - left
          right    — right unchanged, left = left - right
          divergent — both keep only differing fields, skip if identical
        Markers (tag, name, kind) are always preserved.
        """

        _MARKERS = {0, 1, 2}  # tag, name, kind — always kept

        def __init__(self, parent, bias_name="neutral"):
            self._parent = parent
            self._bias_name = bias_name

        def with_bias(self, bias_name):
            return HologramSystem._HnPostingMorphism(self._parent, bias_name)

        @staticmethod
        def _subtract(a, b):
            if not a:
                return a
            if not b:
                return a
            result = list(a)
            for i in range(len(result)):
                if i in HologramSystem._HnPostingMorphism._MARKERS:
                    continue
                if i < len(b) and result[i] == b[i]:
                    result[i] = [] if isinstance(result[i], list) else ""
            return result

        def _apply_bias(self, lens_lns):
            bias = self._bias_name
            if bias == "left":
                return [lens_lns[0]] + [self._subtract(ln, lens_lns[0]) for ln in lens_lns[1:]]
            if bias == "right":
                right = lens_lns[-1]
                return [self._subtract(ln, right) for ln in lens_lns[:-1]] + [right]
            if bias == "divergent":
                if all(ln == lens_lns[0] for ln in lens_lns[1:]):
                    return None
                result = []
                for i, ln in enumerate(lens_lns):
                    others = [lens_lns[j] for j in range(len(lens_lns)) if j != i]
                    diffed = list(ln) if ln else []
                    for j in range(len(diffed)):
                        if j in self._MARKERS:
                            continue
                        if all(j < len(o) and diffed[j] == o[j] for o in others if o):
                            diffed[j] = [] if isinstance(diffed[j], list) else ""
                    result.append(diffed)
                return result
            # neutral
            return lens_lns

        def transform(self, posting: dict) -> list:
            forms = []
            seen = set()
            p = self._parent
            for (name, _line), data in posting.items():
                if name in seen:
                    continue
                seen.add(name)
                lens_lns = []
                for i, ls in enumerate(p._lens_systems):
                    if name in p._names_per_lens[i]:
                        single = {(name, 1): data}
                        ln_forms = ls.posting_morphism.transform(single)
                        lens_lns.append(ln_forms[0] if ln_forms else [])
                    else:
                        lens_lns.append([])
                biased = self._apply_bias(lens_lns)
                if biased is None:
                    continue
                forms.append([Symbol("hn")] + biased)
            return forms

        def inverse(self, forms: list) -> dict:
            tag = Symbol("hn")
            posting: dict = {}
            for item in forms:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                if not (isinstance(item[0], Symbol) and BenchSubsystem.matches_tag(item[0], tag)):
                    continue
                # Delegate to first lens that can inverse the sub-forms
                for ls in self._parent._lens_systems:
                    result = ls.posting_morphism.inverse(item[1:])
                    if result:
                        posting.update(result)
                        break
            return posting

    def _posting_to_hn(self, posting: dict) -> list:
        forms = self.posting_morphism.transform(posting)
        # Append diff head form when hologram was created via dissect
        holo = self._hologram
        if holo is not None and getattr(holo, "_diff_result", None) is not None:
            dr = holo._diff_result
            d = dr.to_dict()
            forms.append(
                [
                    self.diff_tag,
                    holo._name,
                    d.get("replace", ""),
                    d.get("with", ""),
                    d.get("value_a", ""),
                    d.get("value_b", ""),
                    d.get("divergences", {}),
                ]
            )
        return forms

    def evaluate(self, expr, local_env=None):
        """Evaluate a query — string or s-expression."""
        log.info("evaluate: expr=%s type=%s", repr(expr)[:100], type(expr).__name__)
        if isinstance(expr, str):
            from parseltongue.core.lang import PGStringParser

            parsed = PGStringParser.translate(expr)
            if isinstance(parsed, str):
                # Plain text search across all lenses
                merged: dict = {}
                for ls in self._lens_systems:
                    results = ls.index.search(parsed)
                    for r in results:
                        key = (r["document"], r["line"])
                        if key not in merged:
                            merged[key] = r
                return self._posting_to_hn(merged)
            return self._system.evaluate(parsed)

        return self._system.evaluate(expr)
