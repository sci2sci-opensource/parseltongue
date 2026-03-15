"""
Parseltongue Loader Translator — stateful wrapper for progressive loading.

LoaderTranslatorV2 wraps LoaderMorphismV2 with persistent state (known names,
aliases, name registries).  translate() calls the pure morphism for structural
analysis, then bundles it with a PatchContext built from accumulated knowledge.
"""

from dataclasses import dataclass as _dataclass
from dataclasses import field as _dataclass_field

from ..lang import Translator
from .loader_morphism import (
    LoaderAnnotatedDirective,
    LoaderMorphismV2,
    ModuleSource,
    MorphismReport,
    PatchContext,
    _lm_v2,
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
# LoaderTranslatorV2 — translate via LoaderMorphismV2
# ============================================================


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
