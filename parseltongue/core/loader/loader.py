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

from ..atoms import Symbol
from ..engine import _execute_directive
from ..system import System
from .loader_engine import LoaderEngine
from .loader_morphism import ModuleSource

log = logging.getLogger("parseltongue")


class PltgError(Exception):
    """Error with .pltg source location and import stack."""

    def __init__(
        self,
        message: str,
        file: str = "",
        line: int = 0,
        stack: list[str] | None = None,
        cause: Exception | None = None,
    ):
        self.file = file
        self.line = line
        self.stack = stack or []
        self.cause = cause
        super().__init__(message)

    def __str__(self):
        from .lazy_loader import format_loc

        loc = format_loc(self.file, self.line)
        parts = [f"{loc}: {super().__str__()}"]
        for frame in self.stack:
            parts.append(f"  imported from {format_loc(frame)}")
        return "\n".join(parts)


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

    def __init__(self, lib_paths: list[str] | None = None):
        self.main_ctx: LoaderContext = None  # type: ignore[assignment]
        self.modules_contexts: dict[str, ModuleContext] = {}
        self._current: ModuleContext = None  # type: ignore[assignment]
        self._file_stack: list[str] = []
        self._imported: set[str] = set()
        self._path_to_module: dict[str, str] = {}
        self._module_aliases: dict[str, str] = {}
        self.names_to_modules: dict[str, str] = {}
        self.names_to_lines: dict[str, int] = {}
        self._lib_paths: list[str] = lib_paths or []
        self._engine: LoaderEngine = None  # type: ignore[assignment]  # created in load_main

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
        self._path_to_module[abs_path] = module_name
        return md_ctx

    def resolve_md_ctx(self, module_name):
        """Look up a module's context by name."""
        return self.modules_contexts[module_name]

    # ----------------------------------------------------------
    # Source loading with definition tracking which we patch
    # ----------------------------------------------------------

    #
    def _patch_context(self, expr):
        """Recursively patch (context :key) → (context "module.:key")."""
        self._engine.patch_context_expr(expr, module_name=self._current.module_name)

    def _patch_symbols(self, expr, engine, skip_index=None):
        """Recursively namespace bare symbols in expression bodies."""
        self._engine.patch_expr(expr, module_name=self._current.module_name)

    def _load_source(self, system, source):
        """Parse and execute directives, namespacing definitions and context keys."""
        ms = ModuleSource(
            source="",
            source_file=self._current.current_file,
            module_name=self._current.module_name,
            is_main=self._current.is_main,
        )
        result = self._engine.evaluate(source, local_env=ms)
        if result.parse_errors:
            line, err = result.parse_errors[0]
            raise PltgError(
                str(err),
                file=self._current.current_file,
                line=line,
                stack=list(self._file_stack),
                cause=err,
            )
        ctx = result.context
        for lad in result.directives:
            try:
                self._engine.patch_one(lad, ctx)
                self._engine.delegate_one(lad)
            except PltgError as e:
                raise PltgError(
                    e.args[0] if e.args else str(e),
                    file=self._current.current_file,
                    line=lad.directive.sentence.line,
                    stack=list(self._file_stack),
                    cause=e,
                ) from e
            except Exception as e:
                raise PltgError(
                    str(e),
                    file=self._current.current_file,
                    line=lad.directive.sentence.line,
                    stack=list(self._file_stack),
                    cause=e,
                ) from e

    # ----------------------------------------------------------
    # Effects
    # ----------------------------------------------------------

    def _make_loader_effects(self):
        """Create loader-specific effects that close over this Loader."""

        def import_effect(system: System, module_sym) -> bool:
            """Effect: (import (quote some.module))

            Supports Python-style relative imports with leading dots:
              (import (quote .sibling))       →  ./sibling.pltg
              (import (quote ..std.counting)) →  ../std/counting.pltg
              (import (quote ...pkg.mod))     →  ../../pkg/mod.pltg
            Without leading dots, resolves relative to current directory.
            """
            from .loader_engine import module_to_path, parse_module_name

            raw_name = str(module_sym)
            module_name, dots = parse_module_name(raw_name)
            abs_path = module_to_path(module_name, dots, self._current.current_dir)

            # Circular check MUST come before _path_to_module check:
            # a module currently being loaded is in _path_to_module
            # (registered by create_md_ctx) but not yet finished.
            if abs_path in self._file_stack:
                chain = " -> ".join(self._file_stack + [abs_path])
                raise ImportError(f"Circular import detected: {chain}")

            if abs_path in self._path_to_module:
                original = self._path_to_module[abs_path]
                if self._engine.register_or_alias(module_name, original):
                    if module_name != original:
                        log.debug(
                            "Module '%s' already imported as '%s', registered alias",
                            module_name,
                            original,
                        )
                    else:
                        log.debug("Module '%s' already imported, skipping", module_name)
                return True

            from .loader_engine import resolve_module_path

            lib_dirs = [
                os.path.dirname(os.path.abspath(lp)) if os.path.isfile(lp) else os.path.abspath(lp)
                for lp in self._lib_paths
            ]
            abs_path = resolve_module_path(module_name, abs_path, lib_dirs)

            # Mark as lib if resolved from a lib path
            lib_dirs = [
                os.path.dirname(os.path.abspath(lp)) if os.path.isfile(lp) else os.path.abspath(lp)
                for lp in self._lib_paths
            ]
            if any(abs_path.startswith(ld) for ld in lib_dirs):
                self._engine.register_lib_module(module_name)

            # Register module + auto-alias dotted names (may qualify name for lib sub-modules)
            module_name, _ = self._engine.register_module(module_name, parent=self._current.module_name)

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
            module = self._engine.names_to_modules.get(key_str)
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
            try:
                report = system.consistency()
            except KeyError as e:
                # Resolve the failing symbol to its .pltg source location
                sym = str(e).strip("'\"").removeprefix("Unknown symbol: ")
                file, line = self._current.current_file, 0
                for diff_name, diff_def in system.engine.diffs.items():
                    if diff_def["replace"] == sym or diff_def["with"] == sym:
                        mod = self._engine.names_to_modules.get(diff_name)
                        if mod:
                            file = self.modules_contexts[mod].current_file
                        line = self._engine.names_to_lines.get(diff_name, 0)
                        break
                raise PltgError(
                    str(e),
                    file=file,
                    line=line,
                    stack=list(self._file_stack),
                    cause=e,
                ) from e
            mode = str(args[0]) if args else None
            if mode == ":raise":
                print(report)
                if not report.consistent:
                    raise SystemError(f"System inconsistent:\n{report}") from SystemError(
                        f"System inconsistent:\n{report}"
                    )
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

        def dangerously_eval_effect(system: System, *args):
            """Effect: (dangerously-eval code) — execute arbitrary Python string.

            Returns the result of exec/eval. The code runs with 'system'
            available in its namespace.
            """
            code = " ".join(str(a) for a in args)
            ns = {"system": system, "__builtins__": __builtins__, "_ctx": self._current}
            try:
                log.warning("DANGEROUS EVAL '%s'", str(args))
                return eval(code, ns)
            except SyntaxError:
                exec(code, ns)
                return ns.get("result", True)

        return {
            "import": import_effect,
            "run-on-entry": run_on_entry_effect,
            "load-document": load_document_effect,
            "context": context_effect,
            "print": print_effect,
            "consistency": consistency_effect,
            "verify-manual": verify_manual_effect,
            "dangerously-eval": dangerously_eval_effect,
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

    def load_main(
        self, path: str, effects: dict[str, Any] | None = None, strict: bool = False, **system_kwargs
    ) -> System:
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
        self._engine = LoaderEngine(inner=system.engine)
        self._engine.register_module(module_name)  # main module, no parent

        # Auto-load lib entry points before main
        for lib_path in self._lib_paths:
            lib_abs = os.path.abspath(lib_path)
            if os.path.isfile(lib_abs):
                lib_name = os.path.splitext(os.path.basename(lib_abs))[0]
                self._engine.register_lib_module(lib_name)
                self._engine.register_module(lib_name)
                lib_ctx = self.create_md_ctx(lib_abs, lib_name)
                saved = self._current
                self._current = lib_ctx
                try:
                    self._file_stack.append(lib_abs)
                    with open(lib_abs) as f:
                        lib_source = f.read()
                    self._load_source(system, lib_source)
                    self._imported.add(lib_abs)
                finally:
                    self._current = saved
                    self._file_stack.pop()

        with open(abs_path) as f:
            source = f.read()

        self._file_stack.append(abs_path)
        try:
            self._load_source(system, source)
        finally:
            self._file_stack.pop()
        self._imported.add(abs_path)

        # Sync name→module mapping from engine so callers (TUI, etc.) can see it
        self.names_to_modules = self._engine.names_to_modules

        return system

    def prepare_script(self, expr, system: "System"):
        """Patch a parsed expression for evaluation in the given system.

        Resolves module aliases (counting.X → std.counting.X) and
        namespaces bare symbols to their registered names.
        """
        if isinstance(expr, (list, tuple)):
            self._engine.patch_expr(expr, module_name=self._current.module_name if self._current else "")
        return expr

    def load_module(self, system: "System", module_name: str):
        """Import a module into an existing system (post-load_main).

        Resolves via lib_paths, same as (import (quote module_name)).
        """

        effects = self._make_loader_effects()
        import_effect = effects["import"]
        import_effect(system, Symbol(module_name))


def load_pltg(path: str, effects: dict[str, Any] | None = None, **system_kwargs) -> System:
    """Convenience function — creates a Loader and loads the file.

    Returns:
        The loaded System with all modules resolved.
    """
    loader = Loader()
    system = loader.load_main(path, effects=effects, **system_kwargs)
    return system
