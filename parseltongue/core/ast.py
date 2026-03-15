"""
Parseltongue AST — directive nodes with dependency metadata and navigable trees.

Three concerns, layered:

1. **DirectiveNode** — name, kind, deps, source provenance, DAG links.
   Built from AnnotatedSentence via ``parse_directive`` or ``ASTMorphism``.

2. **Parent refs** — every sub-expression in a mutable sentence carries
   ``_parent`` (the containing list) and ``_index`` (its position).
   Enables direct patching: ``node._parent[node._index] = new_value``.

3. **ASTMorphism** — ``Morphism[str, list[AnnotatedDirective]]``.
   Wraps ``SentenceMorphism``, adds parent refs + directive extraction
   in one pass.  The loader and inspector consume this artifact.

Standalone helpers (``parse_directive``, ``resolve_graph``) remain for
callers that don't need the full morphism pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .atoms import Symbol
from .grammar import Grammar
from .lang import (
    AXIOM,
    DEFTERM,
    DERIVE,
    DIFF,
    FACT,
    KW_BIND,
    KW_REPLACE,
    KW_USING,
    KW_WITH,
    AnnotatedSentence,
    SentenceMorphism,
    _sm,
    get_keyword,
)
from .morphism import Morphism

# ============================================================
# Directive metadata
# ============================================================


class DirectiveKind(StrEnum):
    FACT = "fact"
    AXIOM = "axiom"
    DEFTERM = "defterm"
    DERIVE = "derive"
    DIFF = "diff"
    EFFECT = "effect"
    ERROR = "error"


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
    kind: DirectiveKind
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


# ============================================================
# Parent refs — navigable mutable sentences
# ============================================================


class NavList(list):
    """A list that carries parent ref and position for navigable patching.

    After ``attach_parents``, every NavList sub-expression ``child`` can be
    patched in place via: ``child.parent[child.pos] = new_value``
    """

    __slots__ = ("parent", "pos")

    def __init__(self, *args):
        super().__init__(*args)
        self.parent: NavList | None = None
        self.pos: int = 0


def _to_nav(expr) -> NavList | Any:
    """Recursively convert plain lists to NavLists."""
    if not isinstance(expr, list):
        return expr
    nav = NavList(expr)
    for i, item in enumerate(nav):
        if isinstance(item, list):
            nav[i] = _to_nav(item)
    return nav


def attach_parents(expr: NavList, parent: NavList | None = None, index: int = 0) -> None:
    """Walk a NavList sentence, setting parent ref and position on every sub-list.

    After this, any sub-expression ``child`` can be patched in place via:
        ``child.parent[child.pos] = new_value``
    """
    if not isinstance(expr, NavList):
        return
    expr.parent = parent
    expr.pos = index
    for i, item in enumerate(expr):
        if isinstance(item, NavList):
            attach_parents(item, parent=expr, index=i)


# ============================================================
# Symbol extraction
# ============================================================


def extract_symbols(expr: Any, out: set[str]) -> None:
    """Recursively collect all non-keyword, non-variable Symbol references."""
    if isinstance(expr, Symbol):
        s = str(expr)
        if not s.startswith(("?", ":")):
            out.add(s)
    elif isinstance(expr, (list, tuple)):
        for item in expr:
            extract_symbols(item, out)


# ============================================================
# Directive parsing (standalone — works without morphism)
# ============================================================


def parse_directive(expr: Any, order: int = 0) -> DirectiveNode:
    """Extract a DirectiveNode from a parsed S-expression."""
    if not isinstance(expr, (list, tuple)) or not expr:
        return DirectiveNode(name=None, expr=expr, dep_names=set(), kind=DirectiveKind.EFFECT, source_order=order)

    head = expr[0]
    deps: set[str] = set()

    if head == FACT:
        name = str(expr[1])
        if len(expr) > 2:
            extract_symbols(expr[2], deps)
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind=DirectiveKind.FACT, source_order=order)

    elif head == AXIOM:
        name = str(expr[1])
        if len(expr) > 2:
            extract_symbols(expr[2], deps)
        if get_keyword(expr, KW_BIND, None) is not None:
            deps.add(str(expr[2]))
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind=DirectiveKind.AXIOM, source_order=order)

    elif head == DEFTERM:
        name = str(expr[1])
        if get_keyword(expr, KW_BIND, None) is not None:
            deps.add(str(expr[2]))
        elif len(expr) >= 3 and not (isinstance(expr[2], str) and expr[2].startswith(":")):
            extract_symbols(expr[2], deps)
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind=DirectiveKind.DEFTERM, source_order=order)

    elif head == DERIVE:
        name = str(expr[1])
        if len(expr) > 2:
            extract_symbols(expr[2], deps)
        using = get_keyword(expr, KW_USING, [])
        if isinstance(using, (list, tuple)):
            for s in using:
                deps.add(str(s))
        bind_raw = get_keyword(expr, KW_BIND, None)
        if bind_raw is not None:
            deps.add(str(expr[2]))
            extract_symbols(bind_raw, deps)
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind=DirectiveKind.DERIVE, source_order=order)

    elif head == DIFF:
        name = str(expr[1])
        replace_sym = get_keyword(expr, KW_REPLACE)
        with_sym = get_keyword(expr, KW_WITH)
        if replace_sym:
            deps.add(str(replace_sym))
        if with_sym:
            deps.add(str(with_sym))
        return DirectiveNode(name=name, expr=expr, dep_names=deps, kind=DirectiveKind.DIFF, source_order=order)

    else:
        return DirectiveNode(name=None, expr=expr, dep_names=set(), kind=DirectiveKind.EFFECT, source_order=order)


# ============================================================
# Graph resolution (standalone)
# ============================================================


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


# ============================================================
# AnnotatedDirective — the T for ASTMorphism
# ============================================================


@dataclass
class AnnotatedDirective:
    """A directive with full provenance, navigability, and dependency metadata.

    Combines AnnotatedSentence (mutable expr, line, order, structural index)
    with DirectiveNode (name, kind, deps, DAG links) and parent refs
    on every sub-expression.
    """

    sentence: AnnotatedSentence
    node: DirectiveNode


# ============================================================
# ASTMorphism — Morphism[str, list[AnnotatedDirective]]
# ============================================================


class ASTMorphism(Morphism[str, list[AnnotatedDirective]]):
    """AST-level morphism: str → list[AnnotatedDirective].

    Wraps a SentenceMorphism.  For each AnnotatedSentence:
      1. Attaches parent refs to every sub-list in the mutable expr
      2. Extracts a DirectiveNode (name, kind, deps) from the expr
      3. Copies line/order provenance into the DirectiveNode

    The result is a navigable, patchable, dependency-aware AST.
    """

    def __init__(self, base: SentenceMorphism):
        self._base = base

    @property
    def grammar_str(self) -> Grammar[str]:
        return self._base.grammar

    def transform(self, source: str) -> list[AnnotatedDirective]:
        annotated_sentences = self._base.transform(source)
        result: list[AnnotatedDirective] = []
        for a in annotated_sentences:
            a.expr = _to_nav(a.expr)
            attach_parents(a.expr)
            node = parse_directive(a.expr, order=a.order)
            node.source_line = a.line
            result.append(AnnotatedDirective(sentence=a, node=node))
        return result

    def inverse(self, target: list[AnnotatedDirective]) -> str:
        return "\n".join(self.grammar.encode(ad.sentence.wff) for ad in target)


# ============================================================
# Parseltongue AST Morphism — singleton + static access
# ============================================================


_am = ASTMorphism(base=_sm)


class ParseltongueAST:
    """Parseltongue AST morphism — navigable directives with parent refs."""

    morphism = _am

    @staticmethod
    def transform(source: str) -> list[AnnotatedDirective]:
        return _am.transform(source)

    @staticmethod
    def inverse(target: list[AnnotatedDirective]) -> str:
        return _am.inverse(target)
