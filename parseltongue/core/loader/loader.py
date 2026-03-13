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

from ..atoms import Symbol, read_tokens, tokenize
from ..engine import _execute_directive
from ..lang import DSL_KEYWORDS, SPECIAL_FORMS
from ..system import System

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
                s = str(item)
                candidate = f"{self._current.module_name}.{s}"
                eng = engine
                if (
                    candidate in eng.terms
                    or candidate in eng.axioms
                    or candidate in eng.facts
                    or candidate in eng.theorems
                ):
                    expr[i] = Symbol(candidate)
                else:
                    # Resolve module aliases (e.g. "primitives.X" → "src.primitives.X")
                    for alias, canonical in self._module_aliases.items():
                        prefix = alias + "."
                        if s.startswith(prefix):
                            resolved = canonical + s[len(alias) :]
                            if (
                                resolved in eng.terms
                                or resolved in eng.axioms
                                or resolved in eng.facts
                                or resolved in eng.theorems
                            ):
                                expr[i] = Symbol(resolved)
                                break
            elif isinstance(item, list):
                self._patch_symbols(item, engine)

    def _load_source(self, system, source):
        """Parse and execute directives, namespacing definitions and context keys."""
        tokens, token_lines = tokenize(source, track_lines=True)
        while tokens:
            expr_line: int = token_lines[0] if token_lines else 0
            pre_len = len(tokens)
            expr = read_tokens(tokens)
            consumed = pre_len - len(tokens)
            del token_lines[:consumed]
            if isinstance(expr, list) and len(expr) >= 2:
                head = expr[0]
                # Namespace definition names for non-main modules
                if head in DSL_KEYWORDS or head in SPECIAL_FORMS:
                    if not self._current.is_main:
                        expr[1] = f"{self._current.module_name}.{expr[1]}"
                        self.names_to_modules[str(expr[1])] = self._current.module_name
                    self.names_to_lines[str(expr[1])] = expr_line
                # Patch (context :key) everywhere in the expression tree
                self._patch_context(expr)
                # Patch bare symbol references to their namespaced versions
                if not self._current.is_main:
                    skip = 1 if (head in DSL_KEYWORDS or head in SPECIAL_FORMS) else None
                    self._patch_symbols(expr, system.engine, skip_index=skip)
                elif self._module_aliases:
                    # Main module: still resolve aliases (e.g. counting.X → std.counting.X)
                    self._patch_symbols(expr, system.engine)
            try:
                _execute_directive(system.engine, expr)
            except PltgError as e:
                raise PltgError(
                    e.args[0] if e.args else str(e),
                    file=self._current.current_file,
                    line=expr_line,
                    stack=list(self._file_stack),
                    cause=e,
                ) from e
            except Exception as e:
                raise PltgError(
                    str(e),
                    file=self._current.current_file,
                    line=expr_line,
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
            raw_name = str(module_sym)
            # Count leading dots for relative traversal (Python convention)
            dots = 0
            while dots < len(raw_name) and raw_name[dots] == ".":
                dots += 1
            if dots > 0:
                # First dot = current dir, each additional dot = one parent
                ups = ".." + os.sep
                prefix = ups * (dots - 1)
                # Canonical module name strips leading dots
                module_name = raw_name[dots:]
            else:
                prefix = ""
                module_name = raw_name
            rel_path = prefix + module_name.replace(".", os.sep) + ".pltg"
            abs_path = os.path.normpath(os.path.join(self._current.current_dir, rel_path))

            if abs_path in self._imported:
                original = self._path_to_module.get(abs_path)
                if original and original != module_name:
                    self._module_aliases[module_name] = original
                    log.debug(
                        "Module '%s' already imported as '%s', registered alias",
                        module_name,
                        original,
                    )
                else:
                    log.debug("Module '%s' already imported, skipping", module_name)
                return True

            if abs_path in self._file_stack:
                chain = " -> ".join(self._file_stack + [abs_path])
                raise ImportError(f"Circular import detected: {chain}")

            if not os.path.isfile(abs_path):
                # Fall back to lib_paths
                for lib_dir in self._lib_paths:
                    candidate = os.path.normpath(os.path.join(lib_dir, module_name.replace(".", os.sep) + ".pltg"))
                    if os.path.isfile(candidate):
                        abs_path = candidate
                        break
                else:
                    raise FileNotFoundError(f"Module '{module_name}' not found at {abs_path}")

            child_ctx = self.create_md_ctx(abs_path, module_name)

            # Register short-name alias when canonical name is dotted.
            # e.g. importing "..std.counting" → canonical "std.counting"
            #   → alias "counting" → "std.counting"
            # This lets downstream files reference counting.X and have
            # _patch_symbols resolve it to std.counting.X.
            if "." in module_name:
                short = module_name.rsplit(".", 1)[-1]
                if short not in self._module_aliases:
                    self._module_aliases[short] = module_name

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
            try:
                report = system.consistency()
            except KeyError as e:
                # Resolve the failing symbol to its .pltg source location
                sym = str(e).strip("'\"").removeprefix("Unknown symbol: ")
                file, line = self._current.current_file, 0
                for diff_name, diff_def in system.engine.diffs.items():
                    if diff_def["replace"] == sym or diff_def["with"] == sym:
                        mod = self.names_to_modules.get(diff_name)
                        if mod:
                            file = self.modules_contexts[mod].current_file
                        line = self.names_to_lines.get(diff_name, 0)
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

    def prepare_script(self, expr, system: "System"):
        """Patch a parsed expression for evaluation in the given system.

        Resolves module aliases (counting.X → std.counting.X) and
        namespaces bare symbols to their registered names.
        """
        if isinstance(expr, list):
            self._patch_symbols(expr, system.engine)
        return expr

    def load_module(self, system: "System", module_name: str):
        """Import a module into an existing system (post-load_main).

        Resolves via lib_paths, same as (import (quote module_name)).
        """
        from ..atoms import Symbol

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
