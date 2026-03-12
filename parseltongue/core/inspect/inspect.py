"""Lens — backwards-compatible re-export from optics package.

The implementation now lives in ``parseltongue.core.inspect.optics.lens``.
This module re-exports everything so existing imports keep working.
"""

from parseltongue.core.loader.lazy_loader import LazyLoader

from .optics.lens import Lens
from .perspective import Perspective
from .perspectives.markdown import MarkdownPerspective
from .probe_core_to_consequence import CoreToConsequenceStructure


def inspect(probe: CoreToConsequenceStructure, perspectives: list[Perspective] | None = None):
    return Lens(probe, perspectives if perspectives else [MarkdownPerspective()])


def _all_names(engine) -> set[str]:
    """Deprecated: use Lens.find() instead."""
    cache = getattr(engine, '_all_names_cache', None)
    if cache is not None:
        return cache
    names = set()
    for store in [engine.facts, engine.axioms, engine.theorems, engine.terms]:
        names.update(store.keys())
    engine._all_names_cache = names
    return names


def find(pattern: str, engine, max_results: int = 50) -> list[str]:
    """Deprecated: use Lens.find() instead."""
    import re

    rx = re.compile(pattern)
    return sorted(name for name in _all_names(engine) if rx.search(name))[:max_results]


def _fuzzy_matches(query: str, engine, max_results: int = 10) -> list[str]:
    """Deprecated: use Lens.fuzzy() instead."""
    query_lower = query.lower()
    scored = []
    for name in _all_names(engine):
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


def inspect_loaded(term: str, loader: LazyLoader, perspectives: list[Perspective] | None = None) -> "Lens | list[str]":
    """Probe a term using a LazyLoader and wrap in a Lens."""
    from .perspectives.md_debugger import MDebuggerPerspective
    from .probe_core_to_consequence import probe as _probe

    result = loader.last_result
    if result is None:
        raise RuntimeError("Loader has no result. Call loader.load() first.")
    engine = result.system.engine
    stores: list[dict] = [engine.facts, engine.axioms, engine.theorems, engine.terms]
    found = any(term in store for store in stores)
    if not found:
        return _fuzzy_matches(term, engine)

    structure = _probe(term, engine)
    if perspectives is None:
        perspectives = [MDebuggerPerspective(loader)]
    return Lens(structure, perspectives)
