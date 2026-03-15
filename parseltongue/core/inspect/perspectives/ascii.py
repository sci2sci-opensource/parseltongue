"""ASCII perspective — renders structure parts as plain text with box-drawing tables."""

from parseltongue.core.atoms import Symbol
from parseltongue.core.lang import to_sexp

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
from .shared import fmt_dsl as _fmt_dsl
from .shared import fmt_value as _fmt_value

MAX_TABLE_WIDTH = 120


def _wrap_cell(text: str, width: int) -> list[str]:
    """Wrap text to fit within width, breaking at commas or spaces."""
    if len(text) <= width:
        return [text]
    chunks = []
    while text:
        if len(text) <= width:
            chunks.append(text)
            break
        # Try to break at ", " near the limit
        cut = text.rfind(", ", 0, width)
        if cut == -1:
            cut = text.rfind(" ", 0, width)
        if cut == -1:
            cut = width
        else:
            cut += 2 if text[cut] == "," else 1
        chunks.append(text[:cut])
        text = text[cut:]
    return chunks


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a box-drawing table."""
    if not rows:
        return "┌───────┐\n│ empty │\n└───────┘"

    cols = len(headers)
    # Natural widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    # Shrink if total exceeds MAX_TABLE_WIDTH
    # overhead: cols+1 separators + 2 padding per col
    overhead = cols + 1 + cols * 2
    total = sum(widths) + overhead
    if total > MAX_TABLE_WIDTH:
        budget = MAX_TABLE_WIDTH - overhead
        # Give each column at least header width, shrink the widest
        min_widths = [len(h) for h in headers]
        # Sort columns by width descending, shrink greedily
        while sum(widths) > budget:
            i_max = max(range(cols), key=lambda i: widths[i])
            widths[i_max] = max(min_widths[i_max], widths[i_max] - 1)
            if all(widths[i] <= min_widths[i] for i in range(cols)):
                break

    def hline(left, mid, right, fill="─"):
        return left + mid.join(fill * (w + 2) for w in widths) + right

    def dataline(cells):
        parts = []
        for i, cell in enumerate(cells):
            parts.append(f" {cell:<{widths[i]}} ")
        return "│" + "│".join(parts) + "│"

    def datalines(cells):
        """Wrap cells and produce multiple lines if needed."""
        wrapped = [_wrap_cell(cells[i], widths[i]) for i in range(cols)]
        n_lines = max(len(w) for w in wrapped)
        result = []
        for ln in range(n_lines):
            row_cells = []
            for i in range(cols):
                row_cells.append(wrapped[i][ln] if ln < len(wrapped[i]) else "")
            result.append(dataline(row_cells))
        return result

    lines = []
    lines.append(hline("┌", "┬", "┐"))
    lines.append(dataline(headers))
    lines.append(hline("├", "┼", "┤"))
    for row in rows:
        lines.extend(datalines(row))
    lines.append(hline("└", "┴", "┘"))
    return "\n".join(lines)


def _kv_table(title: str, pairs: list[tuple[str, str]]) -> str:
    """Render a key-value box with a title row spanning full width."""
    if not pairs:
        return title
    key_w = max(len(k) for k, _ in pairs)
    val_w = max(len(v) for _, v in pairs)
    title_w = key_w + val_w + 3  # key + " │ " + val
    title_w = max(title_w, len(title))

    # Cap total width
    max_inner = MAX_TABLE_WIDTH - 4  # borders + min padding
    if title_w > max_inner:
        title_w = max_inner
    val_w = max(val_w, title_w - key_w - 3)
    # If still too wide, shrink val_w
    if key_w + val_w + 3 > max_inner:
        val_w = max_inner - key_w - 3
        val_w = max(val_w, 10)

    def hline(left, mid, right):
        return left + "─" * (key_w + 2) + mid + "─" * (val_w + 2) + right

    total_inner = key_w + 2 + 1 + val_w + 2

    lines = []
    lines.append("┌" + "─" * total_inner + "┐")
    lines.append("│" + f" {title:<{total_inner - 1}}" + "│")
    lines.append(hline("├", "┬", "┤"))
    for k, v in pairs:
        wrapped = _wrap_cell(v, val_w)
        lines.append(f"│ {k:<{key_w}} │ {wrapped[0]:<{val_w}} │")
        for continuation in wrapped[1:]:
            lines.append(f"│ {'':<{key_w}} │ {continuation:<{val_w}} │")
    lines.append(hline("└", "┴", "┘"))
    return "\n".join(lines)


class Ascii:
    """ASCII view object. Wraps rendered text content."""

    def __init__(self, content: str):
        self._content = content

    def __str__(self):
        return self._content

    def __repr__(self):
        lines = self._content.splitlines()
        n = len(lines)
        width = max((len(ln) for ln in lines), default=0)
        return f"<Ascii: {n} lines, {width} wide>"

    @property
    def lines(self) -> list[str]:
        return self._content.splitlines()

    @property
    def width(self) -> int:
        return max((len(ln) for ln in self.lines), default=0)


class AsciiPerspective(Perspective[Ascii]):

    def render_structure(self, structure: CoreToConsequenceStructure) -> Ascii:
        return Ascii(render_ascii(structure))

    def render_layer(self, layer: Layer) -> Ascii:
        rows = []
        for c in layer.consumers:
            val_s = _fmt_value(c.value) if c.value else ""
            rows.append([c.name, str(c.kind), val_s])
        header = f"Layer {layer.depth}: {len(layer.consumers)} consumers"
        table = _table(["name", "kind", "value"], rows)
        return Ascii(f"{header}\n{table}")

    def render_consumer(self, consumer: Consumer) -> Ascii:
        val_s = _fmt_value(consumer.value) if consumer.value else ""
        pairs = [
            ("kind", str(consumer.kind)),
            ("value", val_s),
        ]
        if consumer.node.atom is not None:
            origin = getattr(consumer.node.atom, "origin", None)
            if origin:
                pairs.append(("origin", str(origin)))
        kv = _kv_table(consumer.name, pairs)

        parts = [kv]
        if consumer.uses or consumer.declares or consumer.pulls:
            inputs = consumer.uses + consumer.declares + consumer.pulls
            parts.append(self._inputs_table(inputs))
        return Ascii("\n".join(parts))

    def render_node(self, node: Node) -> Ascii:
        dsl = _fmt_dsl(node)
        val_s = _fmt_value(node.value) if node.value else ""
        pairs = [
            ("kind", str(node.kind)),
            ("value", val_s),
        ]
        kv = _kv_table("summary", pairs)
        return Ascii(f"{dsl}\n{kv}")

    def render_inputs(self, inputs: list[ConsumerInput]) -> Ascii:
        return Ascii(self._inputs_table(inputs))

    def render_subgraph(self, nodes: dict[str, Node]) -> Ascii:
        # Find tip nodes: those not referenced as input by any other node in the subgraph
        referenced = set()
        for node in nodes.values():
            for inp in node.inputs:
                if inp in nodes:
                    referenced.add(inp)
        tips = [n for n in nodes if n not in referenced]
        if not tips:
            tips = sorted(nodes)  # cycle fallback

        visited = set()
        lines = [f"Subgraph: {len(nodes)} nodes"]

        def _node_label(name):
            if name not in nodes:
                return f"{name} (external)"
            node = nodes[name]
            val_s = f" = {_fmt_value(node.value)}" if node.value else ""
            return f"{name} [{node.kind}]{val_s}"

        def walk(name, prefix, is_last):
            label = _node_label(name)
            connector = "└── " if is_last else "├── "
            if not prefix:
                connector = ""  # top-level, no connector
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

        return Ascii("\n".join(lines))

    def render_kinds(self, kinds: dict[NodeKind, list[str]]) -> Ascii:
        rows = []
        for kind in sorted(kinds):
            names = sorted(kinds[kind])
            rows.append([str(kind), str(len(names)), ", ".join(names)])
        return Ascii(_table(["kind", "count", "names"], rows))

    def render_roots(self, layer: Layer) -> Ascii:
        rows = []
        for c in layer.consumers:
            rows.append([c.name, str(c.kind)])
        header = f"Roots: {len(layer.consumers)}"
        table = _table(["name", "kind"], rows)
        return Ascii(f"{header}\n{table}")

    def render_form(self, form: list) -> "Ascii":
        """Render a single display form (sr-fmt, ln-fmt, dx-fmt, hn-fmt)."""
        tag = str(form[0]).rsplit(".", 1)[-1] if "." in str(form[0]) else str(form[0])
        fields = form[1:]
        if tag == "sr-fmt":
            # (sr-fmt doc line ctx callers)
            doc, line = str(fields[0]), str(fields[1])
            ctx = str(fields[2]) if len(fields) > 2 else ""
            callers = fields[3] if len(fields) > 3 else []
            caller_names = []
            for c in callers:
                if isinstance(c, list) and c:
                    caller_names.append(str(c[0]))
                else:
                    caller_names.append(str(c))
            prefix = f"[{', '.join(caller_names)}] " if caller_names else ""
            return Ascii(f"{doc}:{line}  {prefix}{ctx}")
        if tag == "ln-fmt":
            # (ln-fmt name kind value depth inputs)
            pairs = [("kind", str(fields[1]))]
            if len(fields) > 2:
                pairs.append(("value", str(fields[2])))
            if len(fields) > 3:
                pairs.append(("depth", str(fields[3])))
            if len(fields) > 4 and fields[4]:
                pairs.append(("inputs", ", ".join(str(i) for i in fields[4])))
            return Ascii(_kv_table(str(fields[0]), pairs))
        if tag == "dx-fmt":
            # (dx-fmt name category kind type detail)
            pairs = [("category", str(fields[1]))]
            if len(fields) > 2:
                pairs.append(("kind", str(fields[2])))
            if len(fields) > 3:
                pairs.append(("type", str(fields[3])))
            if len(fields) > 4:
                pairs.append(("detail", str(fields[4])))
            return Ascii(_kv_table(str(fields[0]), pairs))
        if tag == "hn-fmt":
            # (hn-fmt name kind value lenses)
            pairs = [("kind", str(fields[1]))]
            if len(fields) > 2:
                pairs.append(("value", str(fields[2])))
            if len(fields) > 3 and isinstance(fields[3], list):
                pairs.append(("lenses", ", ".join(str(x) for x in fields[3])))
            return Ascii(_kv_table(str(fields[0]), pairs))
        return Ascii(str(form))

    def render_form_list(self, forms: list[list]) -> "Ascii":
        """Render a list of display forms as a table."""
        if not forms:
            return Ascii("(empty)")
        tag = str(forms[0][0]).rsplit(".", 1)[-1] if "." in str(forms[0][0]) else str(forms[0][0])
        if tag == "sr-fmt":
            rows = []
            for f in forms:
                fields = f[1:]
                doc, line = str(fields[0]), str(fields[1])
                ctx = str(fields[2]) if len(fields) > 2 else ""
                callers = fields[3] if len(fields) > 3 else []
                caller_strs = []
                for c in callers:
                    if isinstance(c, list) and c:
                        caller_strs.append(str(c[0]))
                    else:
                        caller_strs.append(str(c))
                rows.append([f"{doc}:{line}", ", ".join(caller_strs), ctx])
            return Ascii(_table(["location", "callers", "context"], rows))
        if tag == "ln-fmt":
            rows = []
            for f in forms:
                fields = f[1:]
                name = str(fields[0])
                kind = str(fields[1]) if len(fields) > 1 else ""
                value = str(fields[2]) if len(fields) > 2 else ""
                depth = str(fields[3]) if len(fields) > 3 else ""
                inputs = ", ".join(str(i) for i in fields[4]) if len(fields) > 4 and fields[4] else ""
                rows.append([name, kind, value, depth, inputs])
            return Ascii(_table(["name", "kind", "value", "depth", "inputs"], rows))
        if tag == "dx-fmt":
            rows = []
            for f in forms:
                fields = f[1:]
                name = str(fields[0])
                cat = str(fields[1]) if len(fields) > 1 else ""
                kind = str(fields[2]) if len(fields) > 2 else ""
                typ = str(fields[3]) if len(fields) > 3 else ""
                detail = str(fields[4]) if len(fields) > 4 else ""
                rows.append([name, cat, kind, typ, detail])
            return Ascii(_table(["name", "category", "kind", "type", "detail"], rows))
        if tag == "hn-fmt":
            rows = []
            for f in forms:
                fields = f[1:]
                name = str(fields[0])
                kind = str(fields[1]) if len(fields) > 1 else ""
                value = str(fields[2]) if len(fields) > 2 else ""
                lenses = ", ".join(str(x) for x in fields[3]) if len(fields) > 3 and isinstance(fields[3], list) else ""
                rows.append([name, kind, value, lenses])
            return Ascii(_table(["name", "kind", "value", "lenses"], rows))
        # Fallback: render each individually
        parts = [str(self.render_form(f)) for f in forms]
        return Ascii("\n\n".join(parts))

    @staticmethod
    def _inputs_table(inputs: list[ConsumerInput]) -> str:
        rows = []
        for inp in inputs:
            depth = str(inp.source_depth) if inp.input_type == InputType.PULL else ""
            rows.append([str(inp.input_type), inp.name, depth])
        return _table(["type", "name", "depth"], rows)


"""Core-to-consequence diagram renderer.

Consumes a CoreToConsequenceStructure and produces layered rail-based ASCII diagrams.
"""


def _fmt_rail_value(v):
    if isinstance(v, (list, Symbol)):
        return to_sexp(v)
    return repr(v)


def render_ascii(structure: CoreToConsequenceStructure) -> str:
    """Render a CoreToConsequenceStructure as an ASCII rail diagram."""

    def snap4(w):
        return ((w + 3) // 4) * 4

    # --- Measure bar column ---
    roots = structure.roots
    bar_col = 0
    if roots:
        for consumer in roots.consumers:
            bar_col = max(bar_col, len(f":{consumer.name} ──"))
    bar_col = snap4(bar_col)

    # --- Index layers by depth ---
    layers_by_depth = {layer.depth: layer for layer in structure.layers}

    # --- Measure input/result widths per depth ---
    input_widths = {}
    result_widths = {}

    for layer in structure.layers:
        d = layer.depth
        if d == 0:
            continue
        max_iw = 0
        for c in layer.consumers:
            for u in c.uses:
                if d == 1:
                    t = f"|── :using {u.name} in :{c.name} ─"
                else:
                    t = f"|── :using {u.name}────"
                max_iw = max(max_iw, len(t))
            for decl in c.declares:
                if d == 1:
                    t = f"|   :{decl.name} ──"
                else:
                    t = f"|── :using {decl.name} ──"
                max_iw = max(max_iw, len(t))
            for p in c.pulls:
                t = f"|── :using {p.name} ──"
                max_iw = max(max_iw, len(t))
            max_iw = max(max_iw, len(f"|   in :{c.name} ──"))
        input_widths[d] = max_iw

        max_rw = 0
        for c in layer.consumers:
            val_s = f" (={_fmt_rail_value(c.value)})" if c.value else ""
            max_rw = max(max_rw, len(f"|── {c.name}{val_s} ──"))
        result_widths[d] = max_rw

    # --- Compute rail positions ---
    ts_map: dict[int, int] = {}
    cv_map: dict[int, int] = {}
    dp_map: dict[int, int] = {}

    active_depths = sorted(layer.depth for layer in structure.layers if layer.depth > 0)

    for d in active_depths:
        layer = layers_by_depth[d]
        if d == active_depths[0]:
            ts_map[d] = bar_col
        else:
            max_inp_d = 0
            for c in layer.consumers:
                for p in c.pulls:
                    if p.source_depth in dp_map:
                        max_inp_d = max(max_inp_d, p.source_depth)
            if max_inp_d > 0:
                ts_map[d] = dp_map[max_inp_d]
            else:
                prev_d = max((pd for pd in active_depths if pd < d), default=None)
                ts_map[d] = cv_map[prev_d] if prev_d else bar_col

        iw = snap4(input_widths.get(d, 20))
        prev_d = max((pd for pd in active_depths if pd < d), default=None)
        if prev_d and ts_map[d] == cv_map.get(prev_d):
            iw = max(iw, snap4(result_widths.get(prev_d, 0)))
        cv_map[d] = ts_map[d] + iw

        rw = snap4(result_widths.get(d, 20))
        next_d = min((nd for nd in active_depths if nd > d), default=None)
        if next_d:
            next_layer = layers_by_depth[next_d]
            next_has_pulls = any(c.pulls for c in next_layer.consumers)
            if not next_has_pulls:
                rw = max(rw, snap4(input_widths.get(next_d, 0)))
        dp_map[d] = cv_map[d] + rw

    # --- Emit lines ---
    lines = []

    def pad(s, target_len, ch="─"):
        return s + ch * max(0, target_len - len(s))

    def spc(s, target_len):
        return s + " " * max(0, target_len - len(s))

    active_rails: set[int] = set()

    def emit(text_pos, text, dash_from=None, trail_rails=True):
        line = ""
        in_dash = False
        for r in sorted(active_rails):
            if r >= text_pos:
                break
            if dash_from is not None and r == dash_from:
                line = spc(line, r) + "|"
                in_dash = True
            elif in_dash:
                line = pad(line, r, "─") + "|"
            elif dash_from is not None and r > dash_from:
                line = pad(line, r, "─") + "|"
                in_dash = True
            else:
                line = spc(line, r) + "|"
        if in_dash:
            line = pad(line, text_pos, "─")
        else:
            line = spc(line, text_pos)
        line += text
        if trail_rails:
            for r in sorted(active_rails):
                if r > len(line) - 1:
                    line = spc(line, r) + "|"
        return line

    # Layer 0: bar headers
    layer0 = structure.roots
    if layer0:
        for consumer in layer0.consumers:
            lines.append(pad(f":{consumer.name} ", bar_col) + "|")
        if layer0.consumers:
            active_rails.add(bar_col)

    # Render each layer (skip layer 0)
    non_zero_layers = [ly for ly in structure.layers if ly.depth > 0]
    for li, layer in enumerate(non_zero_layers):
        d = layer.depth
        ts = ts_map[d]
        cv = cv_map[d]
        dp = dp_map[d]

        for ci, consumer in enumerate(layer.consumers):
            uses = [inp.name for inp in consumer.uses]
            declares = [inp.name for inp in consumer.declares]
            pulls = consumer.pulls

            if d == 1:
                for u in uses:
                    text = f"|── :using {u} in :{consumer.name} "
                    lines.append(emit(ts, pad(text, cv - ts) + "|"))

                for decl in declares:
                    text = f"|   :{decl} "
                    lines.append(emit(ts, pad(text, cv - ts) + "|"))

                val_s = f" (={_fmt_rail_value(consumer.value)})" if consumer.value else ""
                result_text = f"|── {consumer.name}{val_s} "
                lines.append(emit(cv, pad(result_text, dp - cv) + "|"))
                active_rails.add(dp)

                if ci < len(layer.consumers) - 1 or li < len(non_zero_layers) - 1:
                    lines.append(emit(cv, "|"))

            else:
                for u in uses:
                    text = f"|── :using {u}────"
                    lines.append(emit(ts, pad(text, cv - ts) + "|", dash_from=bar_col))
                if uses and d >= structure.last_root_use_depth:
                    active_rails.discard(bar_col)

                for decl in declares:
                    text = f"|   :{decl} "
                    lines.append(emit(ts, pad(text, cv - ts) + "|"))

                for pull in pulls:
                    ref_dp = dp_map[pull.source_depth]
                    text = f"|── :using {pull.name} "
                    lines.append(emit(ts, pad(text, cv - ts) + "|", dash_from=ref_dp))

                val_s = f" (={_fmt_rail_value(consumer.value)})" if consumer.value else ""
                in_text = f"|   in :{consumer.name} "

                remaining_real = any(fl.depth > d for fl in non_zero_layers)
                is_last = not remaining_real and ci == len(layer.consumers) - 1

                if is_last:
                    result_text = f"|── {consumer.name}{val_s}"
                    lines.append(
                        emit(
                            ts,
                            pad(in_text, cv - ts) + pad(result_text, dp - cv) + "|",
                        )
                    )
                    active_rails.add(dp)
                else:
                    result_text = f"|── {consumer.name}{val_s} "
                    lines.append(
                        emit(
                            ts,
                            pad(in_text, cv - ts) + pad(result_text, dp - cv) + "|",
                        )
                    )
                    active_rails.add(dp)

                if ci < len(layer.consumers) - 1 or (remaining_real and ci == len(layer.consumers) - 1):
                    lines.append(emit(0, ""))

    return "\n".join(lines)
