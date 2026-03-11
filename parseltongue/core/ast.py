"""
Parseltongue AST — directive nodes with dependency metadata.

Parses raw S-expressions into DirectiveNode objects that carry:
- The defined name (if any)
- The raw expression for later execution
- The set of symbol dependency names (unresolved)
- The directive kind (fact, axiom, defterm, derive, diff, effect)
- The source file path that defined the directive
- The source order (parse position within the file)
- Resolved child node references (nodes this directive depends on)
- Resolved dependent node references (nodes that depend on this one)

After parsing, call ``resolve_graph`` to link nodes by name into
a DAG of DirectiveNode references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .atoms import Symbol
from .lang import AXIOM, DEFTERM, DERIVE, DIFF, FACT, KW_BIND, KW_REPLACE, KW_USING, KW_WITH, get_keyword


@dataclass
class DirectiveNode:
    """A parsed directive with dependency metadata.

    ``dep_names`` holds the raw symbol names extracted during parsing.
    ``children`` is populated later by ``resolve_graph`` — it contains
    references to the DirectiveNode objects this node depends on.
    ``dependents`` is the reverse: nodes that depend on this one.
    """

    name: str | None
    expr: list
    dep_names: set[str]
    kind: str  # "fact", "axiom", "defterm", "derive", "diff", "effect"
    source_file: str = ""
    source_order: int = 0
    source_line: int = 0
    children: list[DirectiveNode] = field(default_factory=list, repr=False)
    dependents: list[DirectiveNode] = field(default_factory=list, repr=False)

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    def walk_dependents(self) -> list[DirectiveNode]:
        """All transitive dependents (the subtree that breaks if this fails)."""
        result: list[DirectiveNode] = []
        seen: set[str] = set()
        stack = list(self.dependents)
        while stack:
            node = stack.pop()
            if node.name and node.name not in seen:
                seen.add(node.name)
                result.append(node)
                stack.extend(node.dependents)
        return result


def extract_symbols(expr: Any, out: set[str]) -> None:
    """Recursively collect all non-keyword, non-variable Symbol references."""
    if isinstance(expr, Symbol):
        s = str(expr)
        if not s.startswith(("?", ":")):
            out.add(s)
    elif isinstance(expr, list):
        for item in expr:
            extract_symbols(item, out)


def parse_directive(expr: Any, order: int = 0) -> DirectiveNode:
    """Extract a DirectiveNode from a parsed S-expression."""
    if not isinstance(expr, list) or not expr:
        return DirectiveNode(name=None, expr=expr, dep_names=set(), kind="effect", source_order=order)

    head = expr[0]
    deps: set[str] = set()

    if head == FACT:
        name = str(expr[1])
        if len(expr) > 2:
            extract_symbols(expr[2], deps)
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind="fact", source_order=order)

    elif head == AXIOM:
        name = str(expr[1])
        if len(expr) > 2:
            extract_symbols(expr[2], deps)
        if get_keyword(expr, KW_BIND, None) is not None:
            deps.add(str(expr[2]))
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind="axiom", source_order=order)

    elif head == DEFTERM:
        name = str(expr[1])
        if get_keyword(expr, KW_BIND, None) is not None:
            deps.add(str(expr[2]))
        elif len(expr) >= 3 and not (isinstance(expr[2], str) and expr[2].startswith(":")):
            extract_symbols(expr[2], deps)
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind="defterm", source_order=order)

    elif head == DERIVE:
        name = str(expr[1])
        if len(expr) > 2:
            extract_symbols(expr[2], deps)
        using = get_keyword(expr, KW_USING, [])
        if isinstance(using, list):
            for s in using:
                deps.add(str(s))
        bind_raw = get_keyword(expr, KW_BIND, None)
        if bind_raw is not None:
            deps.add(str(expr[2]))
            extract_symbols(bind_raw, deps)
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind="derive", source_order=order)

    elif head == DIFF:
        name = str(expr[1])
        replace_sym = get_keyword(expr, KW_REPLACE)
        with_sym = get_keyword(expr, KW_WITH)
        if replace_sym:
            deps.add(str(replace_sym))
        if with_sym:
            deps.add(str(with_sym))
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind="diff", source_order=order)

    else:
        return DirectiveNode(name=None, expr=expr, dep_names=set(), kind="effect", source_order=order)


def resolve_graph(nodes: list[DirectiveNode]) -> dict[str, DirectiveNode]:
    """Link parsed nodes into a DAG by resolving dep_names to children/dependents.

    Returns the name->node index. External dependencies (names not in
    the node list) are silently ignored — they're assumed available
    from another module or the environment.
    """
    index: dict[str, DirectiveNode] = {}
    for node in nodes:
        if node.name is not None:
            index[node.name] = node

    for node in nodes:
        for dep_name in node.dep_names:
            dep_node = index.get(dep_name)
            if dep_node is not None:
                node.children.append(dep_node)
                dep_node.dependents.append(node)

    return index
