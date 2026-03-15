"""
Parseltongue Loader Engine — namespace-aware Rewriter + Executor.

Two engines collaborate during loading:

    LoaderEngine   (this)   evaluate: (source, module) → LoaderTranslationResult  (pure, cached)
                            execute:  LoaderTranslationResult → Silence            (patch + delegate)
    Core Engine             execute:  Sentence → Silence                           (register facts/axioms/etc.)

The LoaderEngine manages translators — builds one per module context from
shared state (env, aliases, name registries) and caches them.  evaluate()
is pure: reuses or creates a translator, translates, returns frozen analysis
+ patch context.  execute() applies the patches and delegates to the inner engine.
"""

import os

from ..atoms import SILENCE, Silence
from ..lang import Executor, Sentence
from .loader_morphism import (
    LoaderAnnotatedDirective,
    LoaderMorphismV2,
    ModuleSource,
    MorphismReport,
    PatchContext,
    _lm_v2,
    patch_context,
    patch_definition_name,
    patch_symbols,
)
from .loader_translator import (
    EngineKnown,
    LoaderTranslationResult,
    LoaderTranslatorV2,
)


class _UnionKnown:
    """Combines two known-name sources for ``in`` checks."""

    __slots__ = ("_a", "_b")

    def __init__(self, a, b):
        self._a = a
        self._b = b

    def __contains__(self, name):
        return name in self._a or name in self._b


# ============================================================
# Module ↔ File protocol
# ============================================================


def parse_module_name(raw_name: str) -> tuple[str, int]:
    """Parse a raw import name into (canonical_name, dot_count).

    Leading dots indicate relative traversal (Python convention):
        .sibling       → ("sibling", 1)
        ..std.counting → ("std.counting", 2)
        ...pkg.mod     → ("pkg.mod", 3)
        plain.module   → ("plain.module", 0)
    """
    dots = 0
    while dots < len(raw_name) and raw_name[dots] == ".":
        dots += 1
    return raw_name[dots:], dots


def module_to_path(module_name: str, dots: int, current_dir: str) -> str:
    """Convert a canonical module name + dot count to a relative file path.

    First dot = current dir, each additional dot = one parent.
    """
    if dots > 0:
        ups = ".." + os.sep
        prefix = ups * (dots - 1)
    else:
        prefix = ""
    rel_path = prefix + module_name.replace(".", os.sep) + ".pltg"
    return os.path.normpath(os.path.join(current_dir, rel_path))


def resolve_module_path(module_name: str, abs_path: str, module_paths: list[str]) -> str:
    """Resolve a module to a file, falling back to module paths (lib dirs).

    Returns the resolved absolute path, or raises FileNotFoundError.
    """
    if os.path.isfile(abs_path):
        return abs_path
    for root in module_paths:
        candidate = os.path.normpath(os.path.join(root, module_name.replace(".", os.sep) + ".pltg"))
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(f"Module '{module_name}' not found at {abs_path}")


def short_alias(module_name: str) -> str | None:
    """Extract short alias for dotted module names.

    "std.counting" → "counting"
    "plain" → None
    """
    if "." in module_name:
        return module_name.rsplit(".", 1)[-1]
    return None


class LoaderEngine(Executor[LoaderTranslationResult]):
    """Namespace-aware engine: translates then patches then delegates.

    Owns the shared namespace state (names_to_modules, names_to_lines,
    aliases) and builds/caches translators per module context.

    evaluate() is pure + cached — same module context reuses its translator.
    execute() mutates — applies patches, delegates to inner engine.
    """

    def __init__(
        self,
        inner: Executor[Sentence],
        morphism: LoaderMorphismV2 | None = None,
        lib_modules: list[str] | None = None,
    ):
        self._inner = inner
        self._morphism = morphism or _lm_v2
        # Propagate engine name for log context
        self.name: str = getattr(inner, "name", "loader")
        self.names_to_modules: dict[str, str] = {}
        self.names_to_lines: dict[str, int] = {}
        self.module_aliases: dict[str, str] = {}
        self._imported: set[str] = set()
        self._lib_modules: set[str] = set(lib_modules or [])
        self._report = MorphismReport()
        self._translators: dict[ModuleSource, LoaderTranslatorV2] = {}

    # ----------------------------------------------------------
    # Module management
    # ----------------------------------------------------------

    def is_imported(self, module_name: str) -> bool:
        """Check if a module has been imported."""
        return module_name in self._imported

    def mark_imported(self, module_name: str) -> None:
        """Mark a module as imported."""
        self._imported.add(module_name)

    def register_module(self, module_name: str, parent: str = "") -> tuple[str, bool]:
        """Register a module. Auto-registers aliases for dotted names.

        For lib modules: plain imports from a lib parent get qualified
        with the parent's name as prefix:
            parent="std", module="higher_order" → "std.higher_order"
        Transitively marks qualified modules as lib too.

        Lib modules get full alias chain:
            std.higher_order → higher_order
        Project modules get single short alias:
            utils.math → math

        Returns (qualified_name, is_new). qualified_name may differ from input
        for lib sub-modules. is_new is False if already known.
        """
        # Qualify plain lib module names with parent's name
        if "." not in module_name and parent and self.is_lib_module(parent):
            module_name = f"{parent}.{module_name}"
            self._lib_modules.add(module_name)

        if module_name in self._imported:
            return module_name, False
        self._imported.add(module_name)
        parts = module_name.split(".")
        if len(parts) > 1:
            if self.is_lib_module(module_name):
                # Full alias chain for lib modules
                for i in range(1, len(parts)):
                    alias = ".".join(parts[i:])
                    self.register_alias(alias, module_name)
            else:
                # Single short alias for project modules
                self.register_alias(parts[-1], module_name)
        return module_name, True

    def register_or_alias(self, module_name: str, existing_name: str) -> bool:
        """A module was found already loaded as existing_name.

        If names differ, registers module_name as alias for existing_name.
        Returns True if the module is already covered (no need to load).
        """
        if module_name != existing_name:
            self.register_alias(module_name, existing_name)
        return True

    def register_alias(self, alias: str, canonical: str) -> None:
        """Register a short alias for a module (e.g. 'counting' → 'std.counting')."""
        if alias not in self.module_aliases:
            self.module_aliases[alias] = canonical

    def is_lib_module(self, module_name: str) -> bool:
        """Check if a module is a lib-level (standard library) module."""
        return module_name in self._lib_modules

    def register_lib_module(self, module_name: str) -> None:
        """Mark a module as a lib-level module."""
        self._lib_modules.add(module_name)

    # ----------------------------------------------------------
    # Translator management
    # ----------------------------------------------------------

    def _get_translator(self, ms: ModuleSource) -> LoaderTranslatorV2:
        """Get or create a cached translator for the given module context."""
        translator = self._translators.get(ms)
        if translator is None:
            translator = LoaderTranslatorV2(
                ms=ms,
                env=EngineKnown(self._inner),
                aliases=self.module_aliases,
                names_to_modules=self.names_to_modules,
                report=self._report,
                morphism=self._morphism,
                engine_name=self.name,
            )
            self._translators[ms] = translator
        return translator

    # ----------------------------------------------------------
    # Rewriter protocol — pure, cached
    # ----------------------------------------------------------

    def evaluate(self, source: str, local_env: ModuleSource | None = None) -> LoaderTranslationResult:
        """Translate source in module context. Pure, translator is cached."""
        ms = local_env or ModuleSource(source="")
        translator = self._get_translator(ms)
        return translator.translate(source)

    # ----------------------------------------------------------
    # Executor protocol — patch + delegate
    # ----------------------------------------------------------

    def patch_one(self, lad: LoaderAnnotatedDirective, ctx: "PatchContext", extra_names=None) -> None:
        """Patch a single directive — namespace names, context keys, symbols.

        Mutates the expression in place. Does NOT delegate to inner engine.
        extra_names adds additional known names on top of ctx.known_names
        (e.g. LazyLoader passes collected names since the engine hasn't
        registered them yet).
        """
        ad = lad.directive
        expr = ad.sentence.expr
        line = ad.sentence.line

        # Sync context with current engine state (imports grow aliases mid-loop)
        ctx.aliases = self.module_aliases
        ctx.names_to_modules = self.names_to_modules
        if extra_names is not None:
            ctx.known_names = _UnionKnown(ctx.known_names, extra_names)

        # Namespace definition name
        if lad.needs_namespace:
            patch_definition_name(ad, ctx)

        # Track name → line
        if ad.node.name:
            self.names_to_lines[ad.node.name] = line

        # Patch context keys
        patch_context(expr, ctx, line)

        # Patch symbols against live engine state
        if not lad.is_main:
            patch_symbols(expr, ctx, line, skip_index=lad.skip_index)
        elif ctx.aliases:
            patch_symbols(expr, ctx, line, skip_index=lad.skip_index)

    def delegate_one(self, lad: LoaderAnnotatedDirective) -> None:
        """Delegate a patched directive to inner engine for registration."""
        self._inner.execute(lad.directive.sentence.expr)

    def execute(self, result: LoaderTranslationResult) -> Silence:
        """Apply patches and delegate each directive to inner engine."""
        ctx = result.context
        for lad in result.directives:
            self.patch_one(lad, ctx)
            self.delegate_one(lad)
        return SILENCE

    def patch_context_expr(self, expr, module_name: str = "") -> None:
        """Patch (context :key) on a pre-parsed expression."""
        from .loader_morphism import PatchContext, patch_context

        ctx = PatchContext(
            module_name=module_name,
            names_to_modules=self.names_to_modules,
            report=self._report,
            engine_name=self.name,
        )
        patch_context(expr, ctx)

    def patch_expr(self, expr, module_name: str = "") -> None:
        """Patch symbols on a pre-parsed expression using current engine state."""
        from .loader_morphism import PatchContext, patch_symbols

        ctx = PatchContext(
            module_name=module_name,
            known_names=EngineKnown(self._inner),
            aliases=self.module_aliases,
            names_to_modules=self.names_to_modules,
            report=self._report,
            engine_name=self.name,
        )
        patch_symbols(expr, ctx)

    @property
    def report(self) -> MorphismReport:
        return self._report
