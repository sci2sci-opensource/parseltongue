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
    name = "hologram"

    def __init__(self, hologram: "Hologram | None" = None, engine=None):
        log.info("HologramSystem init: hologram=%s engine=%s", hologram is not None, engine is not None)
        self._hologram = hologram
        self._engine = engine
        self._lens_systems: list[LensSearchSystem] = []
        self._all_names: set[str] = set()
        self._names_per_lens: list[set[str]] = []

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

        def _dissect(diff_name, *args):
            """(dissect "diff-name") — dissect a diff into 2 lenses."""
            from ..optics.hologram import Hologram
            from ..optics.lens import Lens
            from ..probe_core_to_consequence import probe as _probe

            eng = sys._engine
            if eng is None:
                log.warning("dissect: no engine available")
                return {}
            diff_name = str(diff_name)
            log.info("dissect: diff_name=%s diffs=%s", diff_name, list(eng.diffs.keys())[:10])
            diff = eng.diffs[diff_name]
            log.info("dissect: replace=%s with=%s", diff["replace"], diff["with"])
            left = Lens(_probe(diff["replace"], eng))
            right = Lens(_probe(diff["with"], eng))
            holo = Hologram([left, right], name=diff_name, labels=[diff["replace"], diff["with"]])
            sys._init_from_hologram(holo)
            log.info("dissect: %d lenses, %d total names", len(sys._lens_systems), len(sys._all_names))
            if args:
                return sys._system.evaluate(args[0] if len(args) == 1 else list(args))
            return _divergent()

        def _compose(*args):
            """(compose name1 name2 ...) — compose N names into N lenses."""
            from ..optics.hologram import Hologram
            from ..optics.lens import Lens
            from ..probe_core_to_consequence import probe as _probe

            eng = sys._engine
            if eng is None:
                return {}
            names = [str(a) for a in args]
            lenses = [Lens(_probe(n, eng)) for n in names]
            holo = Hologram(lenses, labels=names)
            sys._init_from_hologram(holo)
            return _divergent()

        ops = {
            Symbol("left"): _left,
            Symbol("right"): _right,
            Symbol("lens"): _lens,
            Symbol("divergent"): _divergent,
            Symbol("common"): _common,
            Symbol("only"): _only,
            Symbol("dissect"): _dissect,
            Symbol("compose"): _compose,
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

    def find(self, pattern: str, max_results: int = 50) -> list[str]:
        import re as _re

        rx = _re.compile(pattern)
        seen: set[str] = set()
        for ls in self._lens_systems:
            for name in ls.index.documents:
                if name not in seen and rx.search(name):
                    seen.add(name)
        return sorted(seen)[:max_results]

    def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        query_lower = query.lower()
        scored = []
        seen: set[str] = set()
        for ls in self._lens_systems:
            for name in ls.index.documents:
                if name in seen:
                    continue
                seen.add(name)
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
        return [name for _, _, name in scored[:max_results]]

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
        return self.posting_morphism.transform(posting)

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
