"""
Parseltongue Lazy Loader — fault-tolerant loading for .pltg files.

Unlike the standard Loader which aborts on first error, LazyLoader
parses all directives into an AST, builds a dependency graph, and
executes in topological order.  When a directive fails, only its
dependents are skipped — everything else continues loading.

Usage::

    from parseltongue.core.loader import lazy_load_pltg

    result = lazy_load_pltg("demo.pltg")
    result.system       # the (partially) loaded System
    result.errors       # {node: exception} for failed directives
    result.skipped      # {node: failed_dep_node} — the skip subtree
    result.loaded       # set of successfully loaded nodes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..ast import DirectiveNode, parse_directive, resolve_graph
from ..atoms import Symbol, read_tokens, tokenize
from ..engine import _execute_directive
from ..lang import DSL_KEYWORDS, SPECIAL_FORMS
from ..system import System
from .loader import Loader

log = logging.getLogger("parseltongue")


@dataclass
class LazyLoadResult:
    """Result of a lazy load — partial success is possible.

    ``errors``  maps failed DirectiveNode -> Exception (root causes).
    ``skipped`` maps skipped DirectiveNode -> the DirectiveNode whose
                failure caused the skip (walk .children to trace).
    ``loaded``  is the set of DirectiveNodes that executed successfully.
    """

    system: System
    errors: dict[DirectiveNode, Exception] = field(default_factory=dict)
    skipped: dict[DirectiveNode, DirectiveNode] = field(default_factory=dict)
    loaded: set[DirectiveNode] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def partial(self) -> bool:
        return bool(self.errors) and bool(self.loaded)

    def root_cause(self, node: DirectiveNode) -> DirectiveNode | None:
        """Trace a skipped node back to the root error node."""
        seen: set[int] = set()
        current = node
        while current in self.skipped and id(current) not in seen:
            seen.add(id(current))
            current = self.skipped[current]
        return current if current in self.errors else None

    def error_trees(self) -> dict[DirectiveNode, list[DirectiveNode]]:
        """Map each root error node to the list of nodes it caused to skip."""
        trees: dict[DirectiveNode, list[DirectiveNode]] = {n: [] for n in self.errors}
        for node in self.skipped:
            root = self.root_cause(node)
            if root is not None:
                trees[root].append(node)
        return trees

    def summary(self) -> str:
        lines = [f"Loaded: {len(self.loaded)}, Errors: {len(self.errors)}, Skipped: {len(self.skipped)}"]
        for error_node, cascade in self.error_trees().items():
            lines.append(f"  ERROR {error_node.name} ({error_node.kind}): {self.errors[error_node]}")
            for skipped_node in sorted(cascade, key=lambda n: n.source_order):
                lines.append(f"    SKIP {skipped_node.name} ({skipped_node.kind})")
        return "\n".join(lines)


class LazyLoader(Loader):
    """Extends Loader with fault-tolerant, dependency-aware loading.

    Overrides _load_source to:
    1a. Parse all directives and collect defined names
    1b. Execute effects in source order (import, load-document, print)
    1c. Patch bare symbols against collected names, build DirectiveNodes
    2. Resolve the dependency graph (children/dependents)
    3. Separate and execute remaining effects
    4. Topological execution of named directives; on error skip dependents
    """

    def __init__(self):
        super().__init__()
        self._all_nodes: list[DirectiveNode] = []
        self._result: LazyLoadResult | None = None
        self._failed_names: dict[str, DirectiveNode] = {}  # global across modules

    def _patch_symbols_from_names(self, expr, known_names, skip_index=None):
        """Like _patch_symbols but resolves against a set of known names
        instead of checking the engine. Used during lazy parsing when
        the engine hasn't registered anything yet.

        Also resolves module aliases (e.g. pass1.X → sources.pass1.X)
        for cross-module references."""
        if not isinstance(expr, list):
            return
        for i, item in enumerate(expr):
            if i == skip_index:
                continue
            if isinstance(item, Symbol) and not str(item).startswith(("?", ":")):
                s = str(item)
                candidate = f"{self._current.module_name}.{s}"
                if candidate in known_names:
                    expr[i] = Symbol(candidate)
                else:
                    for alias, canonical in self._module_aliases.items():
                        prefix = alias + "."
                        if s.startswith(prefix):
                            expr[i] = Symbol(canonical + s[len(alias) :])
                            break
            elif isinstance(item, list):
                self._patch_symbols_from_names(item, known_names)

    def _load_source(self, system, source):
        """Parse all directives, build dep graph, execute with fault tolerance."""
        tokens = tokenize(source)
        order = len(self._all_nodes)

        # Phase 1a: Parse all expressions, namespace definition names,
        # but DON'T patch body symbols yet (engine is empty).
        raw_exprs: list[tuple[list, int]] = []
        defined_names: set[str] = set()

        while tokens:
            try:
                expr = read_tokens(tokens)
            except SyntaxError as e:
                err_node = DirectiveNode(
                    name=None,
                    expr=[],
                    dep_names=set(),
                    kind="error",
                    source_file=self._current.current_file,
                    source_order=order,
                )
                if self._result:
                    self._result.errors[err_node] = e
                log.warning("Parse error at position %d: %s", order, e)
                order += 1
                continue

            if isinstance(expr, list) and len(expr) >= 2:
                head = expr[0]
                if head in DSL_KEYWORDS or head in SPECIAL_FORMS:
                    if not self._current.is_main:
                        expr[1] = f"{self._current.module_name}.{expr[1]}"
                        self.names_to_modules[str(expr[1])] = self._current.module_name
                    defined_names.add(str(expr[1]))
                self._patch_context(expr)

            raw_exprs.append((expr, order))
            order += 1

        # Phase 1b: Execute all effects (load-document, import, print, etc.)
        # in source order BEFORE symbol patching, so that:
        # - documents are loaded for evidence verification
        # - module aliases are registered (e.g. pass1 → sources.pass1)
        directive_exprs: list[tuple[list, int]] = []
        for expr, ord_idx in raw_exprs:
            if not isinstance(expr, list) or len(expr) < 2:
                continue
            head = expr[0]
            is_named = head in DSL_KEYWORDS or head in SPECIAL_FORMS
            if not is_named:
                # Effect expression — execute immediately
                try:
                    _execute_directive(system.engine, expr)
                except Exception as e:
                    log.warning("Effect at position %d failed: %s", ord_idx, e)
                    if self._result:
                        node = parse_directive(expr, ord_idx)
                        node.source_file = self._current.current_file
                        self._result.errors[node] = e
            else:
                directive_exprs.append((expr, ord_idx))

        # Phase 1c: Now patch body symbols using collected names + aliases,
        # then build DirectiveNodes.
        nodes: list[DirectiveNode] = []
        for expr, ord_idx in directive_exprs:
            if isinstance(expr, list) and len(expr) >= 2:
                if not self._current.is_main:
                    self._patch_symbols_from_names(expr, defined_names, skip_index=1)
            node = parse_directive(expr, ord_idx)
            node.source_file = self._current.current_file
            nodes.append(node)

        # Phase 2: Resolve the dependency graph
        resolve_graph(nodes)

        # Phase 3: Separate effects from named directives
        effect_nodes = [n for n in nodes if n.name is None]
        named_nodes = [n for n in nodes if n.name is not None]

        # Execute effects in order (print, import, load-document, etc.)
        for node in effect_nodes:
            try:
                _execute_directive(system.engine, node.expr)
            except Exception as e:
                log.warning("Effect at position %d failed: %s", node.source_order, e)
                if self._result:
                    self._result.errors[node] = e

        # Phase 4: Topological execution of named directives
        executed: set[str] = set()

        def _execute_node(node: DirectiveNode) -> bool:
            assert node.name is not None
            if node.name in executed:
                return True
            if node.name in self._failed_names:
                return False

            # Check intra-module children (graph-linked dependencies)
            for child in node.children:
                if not _execute_node(child):
                    self._failed_names[node.name] = node
                    if self._result:
                        self._result.skipped[node] = child
                    log.info("Skipping '%s': dependency '%s' failed", node.name, child.name)
                    return False

            # Check cross-module dependencies (not graph-linked)
            for dep_name in node.dep_names:
                if dep_name in self._failed_names:
                    failed_dep = self._failed_names[dep_name]
                    self._failed_names[node.name] = node
                    if self._result:
                        self._result.skipped[node] = failed_dep
                    log.info("Skipping '%s': cross-module dependency '%s' failed", node.name, dep_name)
                    return False

            try:
                _execute_directive(system.engine, node.expr)
                executed.add(node.name)
                if self._result:
                    self._result.loaded.add(node)
                return True
            except Exception as e:
                self._failed_names[node.name] = node
                if self._result:
                    self._result.errors[node] = e
                log.warning("Directive '%s' failed: %s", node.name, e)
                return False

        # Execute all named nodes in source order
        for node in named_nodes:
            _execute_node(node)

        self._all_nodes.extend(nodes)

    def load_main(self, path: str, effects: dict[str, Any] | None = None, **system_kwargs) -> System:
        """Load with fault tolerance. Access result via .last_result."""
        self._result = LazyLoadResult(system=System())
        system = super().load_main(path, effects=effects, **system_kwargs)
        self._result.system = system
        return system

    @property
    def last_result(self) -> LazyLoadResult | None:
        return self._result

    @property
    def ast(self) -> list[DirectiveNode]:
        """All parsed DirectiveNodes from the most recent load."""
        return self._all_nodes


def lazy_load_pltg(path: str, effects: dict[str, Any] | None = None, **system_kwargs) -> LazyLoadResult:
    """Load a .pltg file with fault tolerance.

    Unlike load_pltg which fails on first error, this parses all
    directives, builds a dependency graph, and executes what it can.
    Failed directives and their dependents are recorded but don't
    block the rest.

    Returns:
        LazyLoadResult with system, errors, skipped, and loaded.
        Use ``result.error_trees()`` to see each failure and its
        skipped subtree.  Use ``node.walk_dependents()`` to see
        everything downstream of a specific node.
    """
    loader = LazyLoader()
    loader.load_main(path, effects=effects, **system_kwargs)
    assert loader.last_result is not None
    return loader.last_result
