"""MDebugger perspective — Markdown with file:line annotations from the loader."""

import os

from ...loader.lazy_loader import LazyLoader
from ..perspective import Perspective
from ..probe_core_to_consequence import (
    Consumer,
    ConsumerInput,
    CoreToConsequenceStructure,
    InputType,
    Layer,
    Node,
    NodeKind,
)
from .markdown import Markdown, _code_block, _md_table, _pltg_title
from .shared import fmt_dsl, fmt_origin_rows, fmt_value


def _pltg_block_located(content: str, title: str = "", loc: str = "") -> str:
    header = ";; pltg"
    if title:
        header += f" {title}"
    if loc:
        header += f"\n;; @ {loc}"
    return f"```scheme\n{header}\n{content}\n```"


class MDebuggerPerspective(Perspective[Markdown]):
    """Markdown perspective that annotates nodes with source file:line from the loader AST."""

    def __init__(self, loader: LazyLoader):
        self._loader = loader
        self._index = {node.name: node for node in loader.ast if node.name}

    def _loc(self, name: str) -> str:
        dn = self._index.get(name)
        if not dn:
            return ""
        parts = []
        if dn.source_file:
            parts.append(os.path.relpath(dn.source_file))
        if dn.source_line:
            parts.append(str(dn.source_line))
        return ":".join(parts)

    def render_structure(self, structure: CoreToConsequenceStructure) -> Markdown:
        emitted = set()
        ordered = []

        def visit(name):
            if name in emitted or name not in structure.graph:
                return
            node = structure.graph[name]
            for inp in node.inputs:
                visit(inp)
            emitted.add(name)
            ordered.append(node)

        for layer in structure.layers:
            for c in layer.consumers:
                visit(c.name)

        parts = []
        for node in ordered:
            loc = self._loc(node.name)
            code = fmt_dsl(node, brief=True)
            if loc:
                code = f";; @ {loc}\n{code}"
            parts.append(code)

        block = "```scheme\n;; pltg\n" + "\n\n".join(parts) + "\n```"
        return Markdown(block)

    def render_layer(self, layer: Layer) -> Markdown:
        rows = []
        for c in layer.consumers:
            val_s = fmt_value(c.value) if c.value else ""
            loc = self._loc(c.name)
            rows.append([c.name, str(c.kind), val_s, loc])
        header = f"### Layer {layer.depth} ({len(layer.consumers)} consumers)\n\n"
        table = _md_table(["name", "kind", "value", "location"], rows)
        return Markdown(f"{header}{table}")

    def render_consumer(self, consumer: Consumer) -> Markdown:
        loc = self._loc(consumer.name)
        parts = [f"### {consumer.name}\n"]
        parts.append(_pltg_block_located(fmt_dsl(consumer.node), _pltg_title(consumer.node), loc))
        parts.append("")

        rows = [["kind", str(consumer.kind)]]
        if loc:
            rows.append(["location", loc])
        rows.extend(fmt_origin_rows(consumer.node.atom, detailed=True))
        parts.append(_md_table(["", ""], rows))

        if consumer.uses or consumer.declares or consumer.pulls:
            parts.append("")
            parts.append(str(self.render_inputs(consumer.uses + consumer.declares + consumer.pulls)))
        return Markdown("\n".join(parts))

    def render_node(self, node: Node) -> Markdown:
        loc = self._loc(node.name)
        parts = [f"### {node.name}\n"]
        parts.append(_pltg_block_located(fmt_dsl(node), _pltg_title(node), loc))
        parts.append("")

        rows = [["kind", str(node.kind)]]
        if loc:
            rows.append(["location", loc])
        rows.extend(fmt_origin_rows(node.atom, detailed=True))
        parts.append(_md_table(["", ""], rows))
        return Markdown("\n".join(parts))

    def render_inputs(self, inputs: list[ConsumerInput]) -> Markdown:
        rows = []
        for inp in inputs:
            depth = str(inp.source_depth) if inp.input_type == InputType.PULL else ""
            loc = self._loc(inp.name)
            rows.append([str(inp.input_type), inp.name, depth, loc])
        return Markdown(_md_table(["type", "name", "depth", "location"], rows))

    def render_subgraph(self, nodes: dict[str, Node]) -> Markdown:
        referenced = set()
        for node in nodes.values():
            for inp in node.inputs:
                if inp in nodes:
                    referenced.add(inp)
        tips = [n for n in nodes if n not in referenced]
        if not tips:
            tips = sorted(nodes)

        visited = set()
        lines = [f"Subgraph: {len(nodes)} nodes"]

        def _node_label(name):
            loc = self._loc(name)
            loc_s = f" @ {loc}" if loc else ""
            if name not in nodes:
                return f"{name} (external){loc_s}"
            node = nodes[name]
            val_s = f" = {fmt_value(node.value)}" if node.value else ""
            return f"{name} [{node.kind}]{val_s}{loc_s}"

        def walk(name, prefix, is_last):
            label = _node_label(name)
            connector = "└── " if is_last else "├── "
            if not prefix:
                connector = ""
            if name in visited:
                lines.append(f"{prefix}{connector}{label} ↑")
                return
            lines.append(f"{prefix}{connector}{label}")
            if name not in nodes:
                return
            visited.add(name)
            deps = [i for i in nodes[name].inputs if i in nodes]
            child_prefix = prefix + ("    " if (is_last or not prefix) else "│   ")
            for idx, dep in enumerate(deps):
                walk(dep, child_prefix, idx == len(deps) - 1)

        for idx, tip in enumerate(sorted(tips)):
            if idx > 0:
                lines.append("")
            walk(tip, "", True)

        return Markdown(_code_block("\n".join(lines)))

    def render_kinds(self, kinds: dict[NodeKind, list[str]]) -> Markdown:
        rows = []
        for kind in sorted(kinds):
            names = sorted(kinds[kind])
            rows.append([str(kind), str(len(names)), ", ".join(names)])
        return Markdown(_md_table(["kind", "count", "names"], rows))

    def render_roots(self, layer: Layer) -> Markdown:
        rows = []
        for c in layer.consumers:
            loc = self._loc(c.name)
            rows.append([c.name, str(c.kind), loc])
        header = f"**Roots: {len(layer.consumers)}**\n\n"
        table = _md_table(["name", "kind", "location"], rows)
        return Markdown(f"{header}{table}")
