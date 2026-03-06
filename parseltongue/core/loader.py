"""
Parseltongue Loader — file-based loading for .pltg files.

Provides Loader as the main class and load_pltg() as a convenience entry
point for loading .pltg files with import resolution, run-on-entry gating,
document loading, and runtime context.

Context follows an onion model: each file gets its own immutable
ModuleContext, linked to its parent LoaderContext. A registry maps module
names to their contexts so any definition can resolve back to its file's
context — even under lazy evaluation.

DSL usage::

    (load-document "report" "data/report.txt")
    (import (quote utils.math))
    (run-on-entry (quote (fact demo true :origin "standalone")))
    (context :file)
"""

import logging
import os
from abc import ABC
from dataclasses import dataclass
from typing import Any

from .atoms import Symbol, read_tokens, tokenize
from .engine import _execute_directive
from .lang import DSL_KEYWORDS, SPECIAL_FORMS
from .system import System

log = logging.getLogger("parseltongue")


class Context(ABC):
    """Base class for loader contexts."""

    pass


@dataclass(frozen=True)
class LoaderContext(Context):
    """Root context for the loader entry point."""

    current_file: str
    current_dir: str
    module_name: str


@dataclass(frozen=True)
class ModuleContext(Context):
    """Immutable per-module context, created once per file load."""

    current_file: str
    current_dir: str
    module_name: str
    is_main: bool
    parent: "Context | None" = None


class Loader:
    """Loads .pltg files with import resolution and per-module context.

    Each loaded file gets an immutable ModuleContext stored in a registry
    keyed by module name.  The registry allows lazy evaluation of
    (context :key) to resolve back to the correct file's context at any
    time — the definition→module mapping tells us where to look.
    """

    def __init__(self):
        self.main_ctx: LoaderContext = None  # type: ignore[assignment]
        self.modules_contexts: dict[str, ModuleContext] = {}
        self._current: ModuleContext = None  # type: ignore[assignment]
        self._file_stack: list[str] = []
        self._imported: set[str] = set()
        self.names_to_modules: dict[str, str] = {}

    def create_md_ctx(self, abs_path, module_name):
        """Create and register a ModuleContext for a file."""
        md_ctx = ModuleContext(
            current_file=abs_path,
            current_dir=os.path.dirname(abs_path),
            module_name=module_name,
            is_main=(self.main_ctx.current_file == abs_path),
            parent=self.main_ctx,
        )
        self.modules_contexts[module_name] = md_ctx
        return md_ctx

    def resolve_md_ctx(self, module_name):
        """Look up a module's context by name."""
        return self.modules_contexts[module_name]

    # ----------------------------------------------------------
    # Source loading with definition tracking
    # ----------------------------------------------------------

    def _patch_context(self, expr):
        """Recursively patch (context :key) → (context "module.:key")."""
        if not isinstance(expr, list) or not expr:
            return
        if expr[0] == Symbol("context") and len(expr) >= 2:
            patched = f"{self._current.module_name}.{expr[1]}"
            expr[1] = patched
            self.names_to_modules[patched] = self._current.module_name
            return
        for item in expr:
            self._patch_context(item)

    def _patch_symbols(self, expr, engine, skip_index=None):
        """Recursively namespace bare symbols in expression bodies.

        For each Symbol, if ``module.symbol`` is already registered in
        the engine (terms, axioms, facts, theorems), replace it with
        the namespaced version.  *skip_index* can exclude a position
        (e.g. 1 for the definition name which is patched separately).
        """
        if not isinstance(expr, list):
            return
        for i, item in enumerate(expr):
            if i == skip_index:
                continue
            if isinstance(item, Symbol) and not str(item).startswith(("?", ":")):
                candidate = f"{self._current.module_name}.{item}"
                eng = engine
                if (
                    candidate in eng.terms
                    or candidate in eng.axioms
                    or candidate in eng.facts
                    or candidate in eng.theorems
                ):
                    expr[i] = Symbol(candidate)
            elif isinstance(item, list):
                self._patch_symbols(item, engine)

    def _load_source(self, system, source):
        """Parse and execute directives, namespacing definitions and context keys."""
        tokens = tokenize(source)
        while tokens:
            expr = read_tokens(tokens)
            if isinstance(expr, list) and len(expr) >= 2:
                head = expr[0]
                # Namespace definition names for non-main modules
                if head in DSL_KEYWORDS or head in SPECIAL_FORMS:
                    if not self._current.is_main:
                        expr[1] = f"{self._current.module_name}.{expr[1]}"
                        self.names_to_modules[str(expr[1])] = self._current.module_name
                # Patch (context :key) everywhere in the expression tree
                self._patch_context(expr)
                # Patch bare symbol references to their namespaced versions
                if not self._current.is_main:
                    self._patch_symbols(expr, system.engine, skip_index=1)
            _execute_directive(system.engine, expr)

    # ----------------------------------------------------------
    # Effects
    # ----------------------------------------------------------

    def _make_loader_effects(self):
        """Create loader-specific effects that close over this Loader."""

        def import_effect(system: System, module_sym) -> bool:
            """Effect: (import (quote some.module))"""
            module_name = str(module_sym)
            rel_path = module_name.replace(".", os.sep) + ".pltg"
            abs_path = os.path.normpath(os.path.join(self._current.current_dir, rel_path))

            if abs_path in self._imported:
                log.debug("Module '%s' already imported, skipping", module_name)
                return True

            if abs_path in self._file_stack:
                chain = " -> ".join(self._file_stack + [abs_path])
                raise ImportError(f"Circular import detected: {chain}")

            if not os.path.isfile(abs_path):
                raise FileNotFoundError(f"Module '{module_name}' not found at {abs_path}")

            child_ctx = self.create_md_ctx(abs_path, module_name)

            saved = self._current
            self._current = child_ctx
            try:
                self._file_stack.append(abs_path)

                with open(abs_path) as f:
                    source = f.read()

                self._load_source(system, source)
                self._imported.add(abs_path)
            finally:
                self._current = saved
                self._file_stack.pop()

            log.info("Imported module '%s' from %s", module_name, abs_path)
            return True

        def run_on_entry_effect(system: System, *quoted_exprs) -> bool:
            """Effect: (run-on-entry (quote (directive1)) ...)"""
            if not self._current.is_main:
                log.debug("Skipping run-on-entry (not main)")
                return False

            for expr in quoted_exprs:
                _execute_directive(system.engine, expr)
            return True

        def load_document_effect(system: System, name, path) -> bool:
            """Effect: (load-document "name" "relative/path.txt")"""
            resolved = os.path.normpath(os.path.join(self._current.current_dir, str(path)))
            system.load_document(str(name), resolved)
            log.info("Loaded document '%s' from %s", name, resolved)
            return True

        def context_effect(system: System, key) -> Any:
            """Effect: (context :file) / (context :dir) / (context :name) / (context :main)

            Keys are patched by _load_source to carry the module name,
            e.g. "lib.:main".  We split to find the module context and
            the actual property.
            """
            key_str = str(key)
            module = self.names_to_modules.get(key_str)
            if module is not None:
                ctx = self.modules_contexts[module]
                prop = key_str[len(module) + 1 :]  # strip "module." prefix
            else:
                ctx = self._current
                prop = key_str
            if prop == ":file":
                return ctx.current_file
            if prop == ":dir":
                return ctx.current_dir
            if prop == ":name":
                return ctx.module_name
            if prop == ":main":
                return ctx.is_main
            raise ValueError(f"Unknown context key: {prop}")

        def print_effect(_system: System, *args) -> bool:
            """Effect: (print "hello" value ...)"""
            print(*[str(a).replace("\\n", "\n") for a in args])
            return True

        def consistency_effect(system: System, *args) -> Any:
            """Effect: (consistency) — print the full consistency report.

            Optional modes:
                (consistency)        — print report, return True
                (consistency :raise) — print report, raise if inconsistent
                (consistency :bool)  — return True/False without printing
                (consistency :report) — return the ConsistencyReport object
            """
            report = system.consistency()
            mode = str(args[0]) if args else None
            if mode == ":raise":
                print(report)
                if not report.consistent:
                    raise SystemError(f"System inconsistent:\n{report}")
                return True
            elif mode == ":bool":
                return report.consistent
            elif mode == ":report":
                return report
            else:
                print(report)
                return True

        def verify_manual_effect(system: System, name) -> bool:
            """Effect: (verify-manual name) — manually verify a fact/term/axiom."""
            system.verify_manual(str(name))
            return True

        return {
            "import": import_effect,
            "run-on-entry": run_on_entry_effect,
            "load-document": load_document_effect,
            "context": context_effect,
            "print": print_effect,
            "consistency": consistency_effect,
            "verify-manual": verify_manual_effect,
        }

    # ----------------------------------------------------------
    # Context-aware evaluation
    # ----------------------------------------------------------

    # def evaluate(self, system, name):
    #     """Evaluate a definition's wff in its source module's context."""
    #     self._current = self._resolve_definition_ctx(name)
    #     if name in system.facts:
    #         return system.evaluate(system.facts[name].wff)
    #     if name in system.theorems:
    #         return system.evaluate(system.theorems[name].wff)
    #     raise KeyError(f"Unknown definition: {name}")

    # ----------------------------------------------------------
    # Entry point
    # ----------------------------------------------------------

    def load_main(self, path: str, effects: dict[str, Any] | None = None, **system_kwargs) -> System:
        """Load a .pltg file as a standalone entry point.

        Args:
            path: Path to the .pltg file.
            effects: Optional additional effects to register.
            **system_kwargs: Passed through to System() constructor.

        Returns:
            The fully-loaded System.
        """
        abs_path = os.path.abspath(path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")

        module_name = os.path.splitext(os.path.basename(abs_path))[0]

        self.main_ctx = LoaderContext(
            current_file=abs_path,
            current_dir=os.path.dirname(abs_path),
            module_name=module_name,
        )

        root_md = self.create_md_ctx(abs_path, module_name)
        self._current = root_md

        loader_effects = self._make_loader_effects()
        all_effects = {**loader_effects, **(effects or {})}

        system = System(effects=all_effects, **system_kwargs)

        with open(abs_path) as f:
            source = f.read()

        self._load_source(system, source)
        self._imported.add(abs_path)

        return system


def load_pltg(path: str, effects: dict[str, Any] | None = None, **system_kwargs) -> System:
    """Convenience function — creates a Loader and loads the file.

    Returns:
        The loaded System with all modules resolved.
    """
    loader = Loader()
    system = loader.load_main(path, effects=effects, **system_kwargs)
    return system
