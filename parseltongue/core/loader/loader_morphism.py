"""
Parseltongue Loader Morphism — file-aware morphism for namespace patching.

    ASTMorphism        (ast):     str → list[AnnotatedDirective]   per-string
    LoaderMorphismV2   (loader):  ModuleSource → list[LoaderAnnotatedDirective]
                                  pure analysis — no patching

Patching functions (patch_symbols, patch_context, patch_definition_name) are
standalone — the engine calls them with a PatchContext after analysis.
NavList parent refs give O(1) positional writes.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from ..ast import (
    AnnotatedDirective,
    ASTMorphism,
    NavList,
    _am,
)
from ..atoms import Symbol
from ..lang import DSL_KEYWORDS, SPECIAL_FORMS

log = logging.getLogger("parseltongue.loader")


# ============================================================
# Reporting
# ============================================================


@dataclass
class MorphismWarning:
    """A warning produced during loader morphism transform."""

    message: str
    file: str = ""
    line: int = 0
    symbol: str = ""


@dataclass
class MorphismResolution:
    """A symbol resolution event — what was resolved and how."""

    original: str
    resolved: str
    via: str  # "module", "alias", "definition", "context"
    file: str = ""
    line: int = 0


@dataclass
class MorphismReport:
    """Collected warnings and resolution log from a transform."""

    warnings: list[MorphismWarning] = field(default_factory=list)
    resolutions: list[MorphismResolution] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def warn(self, message: str, file: str = "", line: int = 0, symbol: str = ""):
        self.warnings.append(MorphismWarning(message, file, line, symbol))

    def resolved(self, original: str, resolved: str, via: str, file: str = "", line: int = 0):
        self.resolutions.append(MorphismResolution(original, resolved, via, file, line))


# ============================================================
# PatchContext — shared state for all patching functions
# ============================================================


@dataclass
class PatchContext:
    """Everything the patching functions need, in one place."""

    module_name: str = ""
    source_file: str = ""
    known_names: Any = field(default_factory=set)  # set[str] | dict | EngineKnown — anything with __contains__
    aliases: dict[str, str] = field(default_factory=dict)
    names_to_modules: dict[str, str] = field(default_factory=dict)
    report: MorphismReport | None = None
    engine_name: str = ""

    def log_resolution(self, original: str, resolved: str, via: str, line: int = 0):
        if self.report is not None:
            self.report.resolved(original, resolved, via, self.source_file, line)
        log.debug("[%s] Resolved %s → %s (%s)", self.engine_name, original, resolved, via)

    def log_warning(self, message: str, line: int = 0, symbol: str = ""):
        if self.report is not None:
            self.report.warn(message, self.source_file, line, symbol)
        log.warning("[%s] %s at %s:%d", self.engine_name, message, self.source_file, line)


# ============================================================
# Namespace patching via NavList
# ============================================================


def _patch_in_parent(expr: Any, index: int, value: Any) -> None:
    """Replace expr[index] with value. If expr is a tuple, rebuild and replace in parent."""
    if isinstance(expr, list):
        expr[index] = value
    elif isinstance(expr, tuple):
        parent = getattr(expr, 'parent', None)
        if parent is not None:
            pos = getattr(expr, 'pos', None)
            new = expr[:index] + (value,) + expr[index + 1 :]
            parent[pos] = new


def patch_context(expr, ctx: PatchContext, line: int = 0) -> None:
    """Recursively patch (context :key) → (context "module.:key")."""
    if not isinstance(expr, (list, tuple)) or not expr:
        return
    if expr[0] == Symbol("context") and len(expr) >= 2:
        old = str(expr[1])
        patched = f"{ctx.module_name}.{old}"
        _patch_in_parent(expr, 1, patched)
        ctx.names_to_modules[patched] = ctx.module_name
        ctx.log_resolution(old, patched, "context", line)
        return
    for item in expr:
        if isinstance(item, (NavList, list, tuple)):
            patch_context(item, ctx, line)


def _resolve_dotted(s: str, ctx: PatchContext, line: int) -> str | None:
    """Try to resolve a dotted symbol via aliases. Returns resolved name or None."""
    for alias, canonical in ctx.aliases.items():
        prefix = alias + "."
        if s.startswith(prefix):
            target = canonical + s[len(alias) :]
            if target in ctx.known_names:
                ctx.log_resolution(s, target, f"alias:{alias}->{canonical}", line)
                return target
    return None


def _resolve_bare(s: str, ctx: PatchContext, line: int) -> str | None:
    """Try to resolve a bare symbol via module namespace or aliases. Returns resolved name or None."""
    # Direct: module_name.symbol
    candidate = f"{ctx.module_name}.{s}"
    if candidate in ctx.known_names:
        ctx.log_resolution(s, candidate, "module", line)
        return candidate
    # Via aliases (e.g. imported std: bare "count" → "std.counting.count")
    for alias, canonical in ctx.aliases.items():
        target = f"{canonical}.{s}"
        if target in ctx.known_names:
            ctx.log_resolution(s, target, f"alias:{alias}->{canonical}", line)
            return target
    return None


def patch_symbols(expr, ctx: PatchContext, line: int = 0, skip_index: int | None = None) -> None:
    """Recursively namespace symbols using NavList for direct patching."""
    if not isinstance(expr, (list, tuple)):
        return
    # Don't patch quoted args of import — module names are not symbols
    head_is_import = expr and expr[0] == Symbol("import")
    for i, item in enumerate(expr):
        if i == skip_index:
            continue
        if isinstance(item, Symbol) and not str(item).startswith(("?", ":")):
            s = str(item)
            if "." in s:
                resolved = _resolve_dotted(s, ctx, line)
                if resolved:
                    _patch_in_parent(expr, i, Symbol(resolved))
                else:
                    ctx.log_warning(f"Dotted symbol '{s}' did not resolve", line, s)
            else:
                resolved = _resolve_bare(s, ctx, line)
                if resolved:
                    _patch_in_parent(expr, i, Symbol(resolved))
        elif isinstance(item, (NavList, list, tuple)):
            if head_is_import and item and item[0] == Symbol("quote"):
                continue
            patch_symbols(item, ctx, line)


def patch_definition_name(ad: AnnotatedDirective, ctx: PatchContext) -> None:
    """Namespace the definition name at index.name for non-main modules."""
    idx = ad.sentence.index
    expr = ad.sentence.expr
    if idx.name is not None and isinstance(expr, (list, tuple)):
        old_name = str(expr[idx.name])
        new_name = f"{ctx.module_name}.{old_name}"
        _patch_in_parent(expr, idx.name, new_name)
        ad.node.name = new_name
        ctx.names_to_modules[new_name] = ctx.module_name
        ctx.log_resolution(old_name, new_name, "definition", ad.sentence.line)


# ============================================================
# LoaderMorphismV2 — proper Morphism protocol (pure, no mutation)
# ============================================================


@dataclass(frozen=True)
class ModuleSource:
    """Input R for LoaderMorphismV2: source string + module context."""

    source: str
    source_file: str = ""
    module_name: str = ""
    is_main: bool = True


@dataclass(frozen=True)
class LoaderAnnotatedDirective:
    """Output T for LoaderMorphismV2: directive + full module analysis.

    Carries everything the engine needs to know to patch and execute,
    without having done any patching.  The morphism analyzes; the engine acts.
    """

    directive: AnnotatedDirective
    source_file: str
    module_name: str
    is_main: bool
    is_definition: bool  # head in DSL_KEYWORDS or SPECIAL_FORMS
    needs_namespace: bool  # not is_main and is_definition
    skip_index: int | None  # index to skip during symbol patching


class LoaderMorphismV2:
    """Morphism[ModuleSource, list[LoaderAnnotatedDirective]].  Pure.

    Wraps ASTMorphism.  transform() parses source, tags with file provenance,
    and analyzes each directive: is it a definition? does it need namespacing?
    what's the skip index for symbol patching?

    No mutation.  The engine reads the analysis and applies patches.
    """

    def __init__(self, base: ASTMorphism):
        self._base = base

    @property
    def grammar(self):
        return self._base.grammar

    @property
    def parse_errors(self) -> list[tuple[int, SyntaxError]]:
        """Walk the morphism chain to find parse errors from the last transform."""
        m: Any = self._base
        while hasattr(m, '_base'):
            m = m._base
        return getattr(m, 'parse_errors', [])

    def transform(self, source: ModuleSource) -> list[LoaderAnnotatedDirective]:
        """Parse, tag, and analyze.  Pure — no patching."""
        directives = self._base.transform(source.source)
        result: list[LoaderAnnotatedDirective] = []

        for ad in directives:
            ad.node.source_file = source.source_file
            ad.node.source_line = ad.sentence.line

            expr = ad.sentence.expr
            idx = ad.sentence.index

            # Analyze: is this a definition?
            is_def = False
            skip = None
            if isinstance(expr, (list, tuple)) and len(expr) >= 2:
                head = expr[0] if idx.head is not None else None
                if head in DSL_KEYWORDS or head in SPECIAL_FORMS:
                    is_def = True
                    skip = idx.name

            result.append(
                LoaderAnnotatedDirective(
                    directive=ad,
                    source_file=source.source_file,
                    module_name=source.module_name,
                    is_main=source.is_main,
                    is_definition=is_def,
                    needs_namespace=not source.is_main and is_def,
                    skip_index=skip,
                )
            )

        return result

    def inverse(self, target: list[LoaderAnnotatedDirective]) -> str:
        return self._base.inverse([lad.directive for lad in target])


_lm_v2 = LoaderMorphismV2(base=_am)
