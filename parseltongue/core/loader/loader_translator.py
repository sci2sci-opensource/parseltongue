"""
Parseltongue Loader Translator — stateful wrapper for progressive loading.

Accumulates context across morphism calls so the loader can delegate
its patching methods one at a time without changing signatures.

    LoaderMorphism:    stateless — one transform() per source string
    LoaderTranslator:  stateful — accumulates known names, aliases, mappings
                       across multiple transform() calls

Each method mirrors a loader method signature for drop-in replacement.
"""

from ..lang import Translator
from .loader_morphism import (
    LoaderMorphism,
    MorphismReport,
    PatchContext,
    _lm,
)
from .loader_morphism import (
    patch_context as _patch_context,
)
from .loader_morphism import (
    patch_symbols as _patch_symbols,
)

# ============================================================
# Live engine view
# ============================================================


class EngineKnown:
    """A dict-like live view over engine registries for ``in`` checks.

    The engine grows as directives execute, so this is always current.
    """

    __slots__ = ("_engine",)

    def __init__(self, engine):
        self._engine = engine

    def __contains__(self, name):
        e = self._engine
        return name in e.terms or name in e.axioms or name in e.facts or name in e.theorems


# ============================================================
# LoaderTranslator
# ============================================================


class LoaderTranslator:
    """Stateful translator that accumulates context across morphism calls.

    Wraps LoaderMorphism with persistent state matching what the loader
    tracks: known names, module aliases, name→module mappings, name→line mappings.

    Each method mirrors a loader method signature so the loader can delegate
    one method at a time without changing its own interface.
    """

    def __init__(self, morphism: LoaderMorphism | None = None):
        self._morphism = morphism or _lm
        self._report = MorphismReport()

    def patch_context(self, expr, module_name: str, names_to_modules: dict[str, str]):
        """Drop-in for Loader._patch_context."""
        ctx = PatchContext(
            module_name=module_name,
            names_to_modules=names_to_modules,
            report=self._report,
        )
        _patch_context(expr, ctx)

    def patch_symbols_against_engine(
        self,
        expr,
        engine,
        module_name: str,
        module_aliases: dict[str, str],
        skip_index: int | None = None,
    ):
        """Drop-in for Loader._patch_symbols(expr, engine, skip_index)."""
        ctx = PatchContext(
            module_name=module_name,
            known_names=EngineKnown(engine),
            aliases=module_aliases,
            report=self._report,
        )
        _patch_symbols(expr, ctx, skip_index=skip_index)

    def patch_symbols_against_names(
        self,
        expr,
        known_names: set[str],
        module_name: str,
        module_aliases: dict[str, str],
        skip_index: int | None = None,
    ):
        """Drop-in for LazyLoader._patch_symbols_from_names(expr, known_names, skip_index)."""
        ctx = PatchContext(
            module_name=module_name,
            known_names=known_names,
            aliases=module_aliases,
            report=self._report,
        )
        _patch_symbols(expr, ctx, skip_index=skip_index)

    @property
    def report(self) -> MorphismReport:
        return self._report


# ============================================================
# LoaderTranslatorV2 — translate via LoaderMorphismV2
# ============================================================


from dataclasses import dataclass as _dataclass
from dataclasses import field as _dataclass_field

from .loader_morphism import (
    LoaderAnnotatedDirective,
    LoaderMorphismV2,
    ModuleSource,
    _lm_v2,
)


@_dataclass(frozen=True)
class LoaderTranslationResult:
    """Output of LoaderTranslatorV2.translate().

    Bundles the morphism's frozen analysis (what each directive IS)
    with the translator's live context (how to patch it).
    """

    directives: list[LoaderAnnotatedDirective]
    context: PatchContext
    parse_errors: list[tuple[int, SyntaxError]] = _dataclass_field(default_factory=list)


class LoaderTranslatorV2(Translator):
    """Translator: str → LoaderTranslationResult.

    Holds a ModuleSource (module identity) and live env state (known names,
    aliases, name registries).  translate() calls the pure morphism for
    structural analysis, then bundles it with a PatchContext built from
    the translator's accumulated knowledge.

    The morphism says what each directive IS.
    The translator says how to patch it, given what it knows right now.
    """

    def __init__(
        self,
        ms: ModuleSource,
        env: "EngineKnown | set[str] | dict | None" = None,
        *,
        aliases: dict[str, str] | None = None,
        names_to_modules: dict[str, str] | None = None,
        report: MorphismReport | None = None,
        morphism: LoaderMorphismV2 | None = None,
        engine_name: str = "",
    ):
        self._ms = ms
        self._morphism = morphism or _lm_v2
        self.env = env or set()
        self.aliases = aliases or {}
        self.names_to_modules = names_to_modules if names_to_modules is not None else {}
        self._report = report or MorphismReport()
        self._engine_name = engine_name

    def translate(self, source: str) -> LoaderTranslationResult:
        """Parse, analyze, and bundle with patch context."""
        from dataclasses import replace

        ms = replace(self._ms, source=source)
        directives = self._morphism.transform(ms)
        parse_errors = self._morphism.parse_errors
        ctx = PatchContext(
            module_name=self._ms.module_name,
            source_file=self._ms.source_file,
            known_names=self.env,
            aliases=self.aliases,
            names_to_modules=self.names_to_modules,
            report=self._report,
            engine_name=self._engine_name,
        )
        return LoaderTranslationResult(directives=directives, context=ctx, parse_errors=parse_errors)

    @property
    def module_source(self) -> ModuleSource:
        return self._ms

    @property
    def report(self) -> MorphismReport:
        return self._report
