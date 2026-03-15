"""Lens — backwards-compatible re-export from optics package.

The implementation now lives in ``parseltongue.core.inspect.optics.lens``.
This module re-exports everything so existing imports keep working.
"""

from parseltongue.core.loader.lazy_loader import LazyLoader

from .optics.lens import Lens
from .perspective import Perspective
from .perspectives.markdown import MarkdownPerspective
from .probe_core_to_consequence import CoreToConsequenceStructure, Node, NodeKind


def inspect(probe: CoreToConsequenceStructure, perspectives: list[Perspective] | None = None):
    return Lens(probe, perspectives if perspectives else [MarkdownPerspective()])


def inspect_loaded(term: str, loader: LazyLoader, perspectives: list[Perspective] | None = None) -> "Lens | list[str]":
    """Probe a term using a LazyLoader and wrap in a Lens."""
    from .perspectives.md_debugger import MDebuggerPerspective
    from .probe_core_to_consequence import probe as _probe
    from .systems.lens import LensSearchSystem

    result = loader.last_result
    if result is None:
        raise RuntimeError("Loader has no result. Call loader.load() first.")
    engine = result.system.engine
    stores: list[dict] = [engine.facts, engine.axioms, engine.theorems, engine.terms]
    found = any(term in store for store in stores)
    if not found:
        graph = {}
        for store in stores:
            for name in store:
                graph[name] = Node(name=name, kind=NodeKind.FACT, value="", inputs=[])
        structure = CoreToConsequenceStructure(layers=[], graph=graph, depths={}, max_depth=0)
        return LensSearchSystem(structure).fuzzy(term)

    structure = _probe(term, engine)
    if perspectives is None:
        perspectives = [MDebuggerPerspective(loader)]
    return Lens(structure, perspectives)
