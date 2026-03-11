"""Markdown perspective — renders structure parts as .pgmd-flavored markdown."""

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
from .shared import fmt_dsl, fmt_origin_rows, fmt_value


class Markdown:
    """Markdown view object. Wraps rendered markdown content."""

    def __init__(self, content: str):
        self._content = content

    def __str__(self):
        return self._content

    def __repr__(self):
        lines = self._content.splitlines()
        return f"<Markdown: {len(lines)} lines>"


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "*empty*"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells):
        return "| " + " | ".join(f"{c:<{widths[i]}}" for i, c in enumerate(cells)) + " |"

    lines = [line(headers)]
    lines.append("| " + " | ".join("-" * w for w in widths) + " |")
    for row in rows:
        lines.append(line(row))
    return "\n".join(lines)


def _code_block(content: str, lang: str = "") -> str:
    return f"```{lang}\n{content}\n```"


def _pltg_title(node) -> str:
    if node.kind in (NodeKind.AXIOM, NodeKind.TERM_FWD):
        return "= self"
    if not node.value:
        return ""
    return f"= {fmt_value(node.value)}"


def _pltg_block(content: str, title: str = "") -> str:
    marker = f";; pltg {title}" if title else ";; pltg"
    return f"```scheme\n{marker}\n{content}\n```"


class MarkdownPerspective(Perspective[Markdown]):

    def render_structure(self, structure: CoreToConsequenceStructure) -> Markdown:
        # Topological order: emit each node after all its inputs
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

        # Walk by layer depth, then by consumer order within layer
        for layer in structure.layers:
            for c in layer.consumers:
                visit(c.name)

        directives = [fmt_dsl(node) for node in ordered]
        return Markdown(_pltg_block("\n\n".join(directives)))

    def render_layer(self, layer: Layer) -> Markdown:
        rows = []
        for c in layer.consumers:
            val_s = fmt_value(c.value) if c.value else ""
            rows.append([c.name, str(c.kind), val_s])
        header = f"### Layer {layer.depth} ({len(layer.consumers)} consumers)\n\n"
        table = _md_table(["name", "kind", "value"], rows)
        return Markdown(f"{header}{table}")

    def render_consumer(self, consumer: Consumer) -> Markdown:
        parts = [f"### {consumer.name}\n"]
        parts.append(_pltg_block(fmt_dsl(consumer.node), _pltg_title(consumer.node)))
        parts.append("")

        rows = [["kind", str(consumer.kind)]]
        rows.extend(fmt_origin_rows(consumer.node.atom))
        parts.append(_md_table(["", ""], rows))

        if consumer.uses or consumer.declares or consumer.pulls:
            parts.append("")
            parts.append(self._inputs_md(consumer.uses + consumer.declares + consumer.pulls))
        return Markdown("\n".join(parts))

    def render_node(self, node: Node) -> Markdown:
        parts = [f"### {node.name}\n"]
        parts.append(_pltg_block(fmt_dsl(node), _pltg_title(node)))
        parts.append("")

        rows = [["kind", str(node.kind)]]
        rows.extend(fmt_origin_rows(node.atom))
        parts.append(_md_table(["", ""], rows))
        return Markdown("\n".join(parts))

    def render_inputs(self, inputs: list[ConsumerInput]) -> Markdown:
        return Markdown(self._inputs_md(inputs))

    def render_subgraph(self, nodes: dict[str, Node]) -> Markdown:
        # Reuse ascii tree rendering inside a code block
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
            if name not in nodes:
                return f"{name} (external)"
            node = nodes[name]
            val_s = f" = {fmt_value(node.value)}" if node.value else ""
            return f"{name} [{node.kind}]{val_s}"

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
            rows.append([c.name, str(c.kind)])
        header = f"**Roots: {len(layer.consumers)}**\n\n"
        table = _md_table(["name", "kind"], rows)
        return Markdown(f"{header}{table}")

    @staticmethod
    def _inputs_md(inputs: list[ConsumerInput]) -> str:
        rows = []
        for inp in inputs:
            depth = str(inp.source_depth) if inp.input_type == InputType.PULL else ""
            rows.append([str(inp.input_type), inp.name, depth])
        return _md_table(["type", "name", "depth"], rows)
