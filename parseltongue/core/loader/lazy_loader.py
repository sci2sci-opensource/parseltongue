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


def format_loc(file: str | None, line: int = 0, col: int = 1) -> str:
    """Format source location as a clickable file:// link with URL-encoded path."""
    if not file:
        return "?"
    from urllib.parse import quote

    loc = "file://" + quote(file, safe="/")
    if line:
        loc += f":{line}:{col}"
    return loc


@dataclass
class LocatedItem:
    """A consistency item enriched with source location."""

    name: str
    source_file: str | None
    source_line: int
    item: Any  # original item from ConsistencyIssue/ConsistencyWarning
    kind: str | None = None  # directive kind: fact, axiom, defterm, derive, diff, etc.

    @property
    def loc(self) -> str:
        return format_loc(self.source_file, self.source_line)


@dataclass
class LocatedConsistencyReport:
    """Wraps a ConsistencyReport with source locations from the loader AST."""

    report: Any  # ConsistencyReport
    _node_index: dict[str, DirectiveNode] = field(default_factory=dict, repr=False)
    _engine: Any = field(default=None, repr=False)  # Engine

    def _locate(self, name: str) -> tuple[str | None, int, str | None]:
        node = self._node_index.get(name)
        if node:
            return node.source_file, node.source_line, node.kind
        return None, 0, None

    def located_issues(self) -> list[tuple[Any, list[LocatedItem]]]:
        """Return (issue, [LocatedItem, ...]) for each issue."""
        from ..engine import IssueType

        result = []
        for issue in self.report.issues:
            located = []
            for item in issue.items:
                if issue.type in (IssueType.DIFF_DIVERGENCE, IssueType.DIFF_VALUE_DIVERGENCE):
                    name = item.name
                elif isinstance(item, tuple):
                    name = item[0]
                else:
                    name = str(item)
                sf, sl, kind = self._locate(name)
                located.append(LocatedItem(name=name, source_file=sf, source_line=sl, item=item, kind=kind))
            result.append((issue, located))
        return result

    def danglings(self) -> list[LocatedItem]:
        """Find definitions referenced by nothing (not consumed by diffs, theorems, or terms)."""
        if self._engine is None:
            return []
        engine = self._engine

        referenced_by: dict[str, set[str]] = {}
        for name in list(engine.facts) + list(engine.axioms) + list(engine.terms):
            referenced_by.setdefault(name, set())

        for thm_name, thm in engine.theorems.items():
            for dep in thm.derivation:
                referenced_by.setdefault(dep, set()).add(thm_name)
            referenced_by.setdefault(thm_name, set())

        for diff_name, params in engine.diffs.items():
            referenced_by.setdefault(params["replace"], set()).add(diff_name)
            referenced_by.setdefault(params["with"], set()).add(diff_name)

        for term_name, term in engine.terms.items():
            if term.definition is not None:
                for sym in self._collect_symbols(term.definition):
                    referenced_by.setdefault(sym, set()).add(term_name)

        for ax_name, ax in engine.axioms.items():
            for sym in self._collect_symbols(ax.wff):
                if sym in engine.terms or sym in engine.facts or sym in engine.axioms or sym in engine.theorems:
                    referenced_by.setdefault(ax_name, set()).add(sym)

        diff_names = set(engine.diffs.keys())
        all_names = set(engine.facts) | set(engine.axioms) | set(engine.terms) | set(engine.theorems)
        dangling_names = sorted(name for name in all_names if not referenced_by.get(name) and name not in diff_names)

        result = []
        for name in dangling_names:
            sf, sl, kind = self._locate(name)
            result.append(LocatedItem(name=name, source_file=sf, source_line=sl, item=name, kind=kind))
        return result

    @staticmethod
    def _collect_symbols(expr) -> set[str]:
        from ..atoms import Symbol

        if isinstance(expr, Symbol):
            return {str(expr)}
        if isinstance(expr, list):
            result: set[str] = set()
            for item in expr:
                result |= LocatedConsistencyReport._collect_symbols(item)
            return result
        return set()

    def located_warnings(self) -> list[tuple[Any, list[LocatedItem]]]:
        """Return (warning, [LocatedItem, ...]) for each warning."""
        result = []
        for warning in self.report.warnings:
            located = []
            for item in warning.items:
                name = str(item)
                sf, sl, kind = self._locate(name)
                located.append(LocatedItem(name=name, source_file=sf, source_line=sl, item=item, kind=kind))
            result.append((warning, located))
        return result

    @property
    def consistent(self) -> bool:
        return self.report.consistent

    def __str__(self) -> str:
        if self.consistent and not self.report.warnings:
            return "System is fully consistent"
        lines = []
        if not self.consistent:
            lines.append(f"System inconsistent: {len(self.report.issues)} issue(s)")
        for issue, items in self.located_issues():
            lines.append(f"  {issue.type.value}:")
            for li in items:
                lines.append(f"    {li.name} @ {li.loc}")
        for warning, items in self.located_warnings():
            lines.append(f"  [warning] {warning.type.value}:")
            for li in items:
                lines.append(f"    {li.name} @ {li.loc}")
        return "\n".join(lines)


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
    loader_warnings: list[tuple[str, str | None, int]] = field(default_factory=list, repr=False)
    _all_nodes: list[DirectiveNode] = field(default_factory=list, repr=False)

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

    @staticmethod
    def _loc(node: DirectiveNode) -> str:
        """Format source location as a clickable file:// link."""
        return format_loc(node.source_file, node.source_line)

    def summary(self) -> str:
        lines = [f"Loaded: {len(self.loaded)}, Errors: {len(self.errors)}, Skipped: {len(self.skipped)}"]
        for error_node, cascade in self.error_trees().items():
            loc = self._loc(error_node)
            lines.append(f"  ERROR {error_node.name} ({error_node.kind}) at {loc}: {self.errors[error_node]}")
            for skipped_node in sorted(cascade, key=lambda n: n.source_order):
                loc = self._loc(skipped_node)
                lines.append(f"    SKIP {skipped_node.name} ({skipped_node.kind}) at {loc}")
        return "\n".join(lines)

    def roots(self) -> list[str]:
        """Names not consumed by any other directive — the roots for a full probe."""
        if hasattr(self, '_roots_cache'):
            return self._roots_cache  # type: ignore[has-type]
        engine = self.system.engine
        referenced: set[str] = set()
        for thm in engine.theorems.values():
            referenced.update(thm.derivation)
        for term in engine.terms.values():
            if term.definition is not None:
                referenced.update(LocatedConsistencyReport._collect_symbols(term.definition))
        # Don't count diff sides as referenced — probe doesn't walk diffs
        all_names = [n.name for n in self._all_nodes if n.name and n.kind != "diff"]
        self._roots_cache = [n for n in all_names if n not in referenced]
        return self._roots_cache

    def _build_node_index(self) -> dict[str, DirectiveNode]:
        if not hasattr(self, '_node_index_cache'):
            self._node_index_cache = {node.name: node for node in self._all_nodes if node.name}
        return self._node_index_cache

    def consistency(self) -> LocatedConsistencyReport:
        """Run consistency check and enrich with source locations from AST."""
        report = self.system.engine.consistency()
        return LocatedConsistencyReport(report=report, _node_index=self._build_node_index(), _engine=self.system.engine)

    def consistency_incremental(self, diffs_to_patch: set[str]) -> LocatedConsistencyReport:
        """Run evidence checks (full) + diff checks (only diffs_to_patch)."""
        from ..engine import ConsistencyReport

        engine = self.system.engine
        issues, warnings = engine._check_evidence()
        diff_issues, diff_warnings = engine._check_diffs(diffs_to_patch)
        issues.extend(diff_issues)
        warnings.extend(diff_warnings)
        report = ConsistencyReport(consistent=len(issues) == 0, issues=issues, warnings=warnings)
        return LocatedConsistencyReport(report=report, _node_index=self._build_node_index(), _engine=engine)


class LazyLoader(Loader):
    """Extends Loader with fault-tolerant, dependency-aware loading.

    Overrides _load_source to:
    1a. Parse all directives and collect defined names
    1b. Execute effects by priority rank (imports first, prints last)
    1c. Patch bare symbols against collected names, build DirectiveNodes
    2. Resolve the dependency graph (children/dependents)
    3. Separate and execute remaining effects
    4. Topological execution of named directives; on error skip dependents
    """

    # Effects that must run before directives, ranked by priority.
    # Lower rank = runs first.  Stable sort preserves source order within rank.
    # Effects that must run before directives (sorted by rank within this group).
    PRE_DIRECTIVE_EFFECTS: list[list[str]] = [
        ["context"],
        ["load-document"],
        ["import"],
    ]
    # Effects that run after all directives have executed.
    POST_DIRECTIVE_EFFECTS: list[list[str]] = [
        ["run-on-entry"],
        ["verify-manual"],
        ["print", "consistency", "dangerously-eval"],
    ]

    def _effect_rank(self, head: str, ranking: list[list[str]]) -> int:
        for rank, names in enumerate(ranking):
            if head in names:
                return rank
        return len(ranking)

    def _is_pre_directive(self, head: str) -> bool:
        return any(head in names for names in self.PRE_DIRECTIVE_EFFECTS)

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
        tokens, token_lines = tokenize(source, track_lines=True)
        order = len(self._all_nodes)

        # Phase 1a: Parse all expressions, namespace definition names,
        # but DON'T patch body symbols yet (engine is empty).
        raw_exprs: list[tuple[list, int, int]] = []  # (expr, order, line)
        defined_names: set[str] = set()

        while tokens:
            expr_line: int = token_lines[0] if token_lines else 0
            try:
                pre_len = len(tokens)
                expr = read_tokens(tokens)
                consumed = pre_len - len(tokens)
                del token_lines[:consumed]
            except SyntaxError as e:
                err_node = DirectiveNode(
                    name=None,
                    expr=[],
                    dep_names=set(),
                    kind="error",
                    source_file=self._current.current_file,
                    source_order=order,
                    source_line=expr_line,
                )
                if self._result:
                    self._result.errors[err_node] = e
                log.warning("Parse error at %s:%d: %s", self._current.current_file, expr_line, e)
                order += 1
                continue

            if isinstance(expr, list) and len(expr) >= 2:
                head = expr[0]
                if head in DSL_KEYWORDS or head in SPECIAL_FORMS:
                    if not self._current.is_main:
                        expr[1] = f"{self._current.module_name}.{expr[1]}"
                        self.names_to_modules[str(expr[1])] = self._current.module_name
                    name = str(expr[1])
                    if name in defined_names:
                        log.warning("Duplicate name '%s' at %s:%d", name, self._current.current_file, expr_line)
                        if self._result:
                            self._result.loader_warnings.append(
                                (f"Duplicate name '{name}'", self._current.current_file, expr_line)
                            )
                    defined_names.add(name)
                self._patch_context(expr)

            raw_exprs.append((expr, order, expr_line))
            order += 1

        # Phase 1b: Separate effects into pre/post-directive, execute pre now.
        directive_exprs: list[tuple[list, int, int]] = []
        pre_effects: list[tuple[list, int, int]] = []
        post_effects: list[tuple[list, int, int]] = []
        for expr, ord_idx, line in raw_exprs:
            if not isinstance(expr, list) or len(expr) < 2:
                continue
            head = expr[0]
            is_named = head in DSL_KEYWORDS or head in SPECIAL_FORMS
            if is_named:
                directive_exprs.append((expr, ord_idx, line))
            elif self._is_pre_directive(str(head)):
                pre_effects.append((expr, ord_idx, line))
            else:
                post_effects.append((expr, ord_idx, line))

        pre_effects.sort(key=lambda e: self._effect_rank(str(e[0][0]), self.PRE_DIRECTIVE_EFFECTS))

        for expr, ord_idx, line in pre_effects:
            try:
                _execute_directive(system.engine, expr)
            except Exception as e:
                log.warning("Effect at %s:%d failed: %s", self._current.current_file, line, e)
                if self._result:
                    node = parse_directive(expr, ord_idx)
                    node.source_file = self._current.current_file
                    node.source_line = line
                    self._result.errors[node] = e

        # Phase 1c: Now patch body symbols using collected names + aliases,
        # then build DirectiveNodes.
        nodes: list[DirectiveNode] = []
        for expr, ord_idx, line in directive_exprs:
            if isinstance(expr, list) and len(expr) >= 2:
                if not self._current.is_main:
                    self._patch_symbols_from_names(expr, defined_names, skip_index=1)
                elif self._module_aliases:
                    # Main module: still resolve aliases (e.g. counting.X → std.counting.X)
                    self._patch_symbols_from_names(expr, defined_names)
            node = parse_directive(expr, ord_idx)
            node.source_file = self._current.current_file
            node.source_line = line
            nodes.append(node)

        # Phase 2: Resolve the dependency graph
        resolve_graph(nodes)

        # Phase 3: Named directives only (effects already executed in Phase 1b)
        named_nodes = [n for n in nodes if n.name is not None]

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

        # Phase 5: Post-directive effects (print, verify-manual, consistency, etc.)
        # Engine is populated — patch symbols against it before executing.
        post_effects.sort(key=lambda e: self._effect_rank(str(e[0][0]), self.POST_DIRECTIVE_EFFECTS))
        for expr, ord_idx, line in post_effects:
            self._patch_symbols(expr, system.engine)
            try:
                _execute_directive(system.engine, expr)
            except Exception as e:
                log.warning("Effect at %s:%d failed: %s", self._current.current_file, line, e)
                if self._result:
                    node = parse_directive(expr, ord_idx)
                    node.source_file = self._current.current_file
                    node.source_line = line
                    self._result.errors[node] = e

        self._all_nodes.extend(nodes)

    def load_main(
        self, path: str, effects: dict[str, Any] | None = None, strict: bool = False, **system_kwargs
    ) -> System:
        """Load with fault tolerance. Access result via .last_result.

        Args:
            strict: If True, raise on first error with full traceback.
        """
        self._result = LazyLoadResult(system=System())
        system = super().load_main(path, effects=effects, **system_kwargs)
        self._result.system = system
        self._result._all_nodes = self._all_nodes
        if strict and self._result.errors:
            import os
            import traceback
            from urllib.parse import quote

            parts = []
            for node, exc in self._result.errors.items():
                src = (node.source_file or "(unknown)").replace("\\", "/")
                rel = os.path.relpath(src) if node.source_file else "(unknown)"
                line = max(node.source_line, 1)
                uri = f"file://{quote(src, safe='/')}:{line}:1"
                tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                parts.append(
                    f"\n{'='*60}\n"
                    f"ERROR in {node.name or '(unnamed)'} at {rel}:{line}\n"
                    f"  {exc}\n"
                    f"{uri}\n"
                    f"\n{tb}"
                )
            raise SystemError(f"{len(self._result.errors)} error(s) during load:\n{''.join(parts)}")
        return system

    @property
    def last_result(self) -> LazyLoadResult | None:
        return self._result

    @property
    def ast(self) -> list[DirectiveNode]:
        """All parsed DirectiveNodes from the most recent load."""
        return self._all_nodes


def lazy_load_pltg(
    path: str, effects: dict[str, Any] | None = None, strict: bool = False, **system_kwargs
) -> LazyLoadResult:
    """Load a .pltg file with fault tolerance.

    Unlike load_pltg which fails on first error, this parses all
    directives, builds a dependency graph, and executes what it can.
    Failed directives and their dependents are recorded but don't
    block the rest.

    Args:
        strict: If True, raise on first error with full traceback.

    Returns:
        LazyLoadResult with system, errors, skipped, and loaded.
        Use ``result.error_trees()`` to see each failure and its
        skipped subtree.  Use ``node.walk_dependents()`` to see
        everything downstream of a specific node.
    """
    loader = LazyLoader()
    loader.load_main(path, effects=effects, strict=strict, **system_kwargs)
    assert loader.last_result is not None
    return loader.last_result
