"""Name resolution for exported pass sources.

Handles cross-pass reference namespacing and [[type:name]] ref rewriting
when exporting pipeline runs as project folders.
"""

from __future__ import annotations

import re
from typing import Any


def tokenize_with_positions(source: str) -> list[tuple[str, int, int]]:
    """Tokenize like core.atoms.tokenize but track (token, start, end) positions."""
    tokens: list[tuple[str, int, int]] = []
    in_string = False
    in_comment = False
    escaped = False
    current: list[str] = []
    start = 0

    for i, char in enumerate(source):
        if char == "\n":
            in_comment = False
            escaped = False
            if not in_string and current:
                tokens.append(("".join(current), start, i))
                current = []
            elif in_string:
                current.append(char)
            continue
        if in_comment:
            continue
        if in_string:
            if escaped:
                current.append(char)
                escaped = False
            elif char == "\\":
                current.append(char)
                escaped = True
            elif char == '"':
                in_string = False
                current.append(char)
                tokens.append(("".join(current), start, i + 1))
                current = []
            else:
                current.append(char)
            continue
        if char == ";":
            in_comment = True
            if current:
                tokens.append(("".join(current), start, i))
                current = []
            continue
        if char == '"':
            in_string = True
            start = i
            current.append(char)
        elif char in "()":
            if current:
                tokens.append(("".join(current), start, i))
                current = []
            tokens.append((char, i, i + 1))
        elif char in " \t\r":
            if current:
                tokens.append(("".join(current), start, i))
                current = []
        else:
            if not current:
                start = i
            current.append(char)
    if current:
        tokens.append(("".join(current), start, len(source)))
    return tokens


def resolve_export_names(
    pass_sources: list[tuple[str, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build name resolution for exported pass sources.

    Tokenizes with position tracking, walks the AST to identify which
    token occurrences are cross-pass references (not definitions), then
    does exact position-based replacements in the original source text.

    Args:
        pass_sources: [(module_name, source), ...] in load order.
            module_name is the short sibling name (e.g. "pass1").

    Returns:
        (patched_sources, bare_to_ns):
        - patched_sources: {module_name: original source with cross-refs namespaced}
        - bare_to_ns: {bare_name: module_name} ownership map (latest wins)
    """
    from parseltongue.core.atoms import Symbol
    from parseltongue.core.grammar import read_tokens, tokenize
    from parseltongue.core.lang import DSL_KEYWORDS, SPECIAL_FORMS

    bare_to_ns: dict[str, str] = {}
    patched_sources: dict[str, str] = {}

    def _collect_names(source: str) -> set[str]:
        tokens = tokenize(source)
        names: set[str] = set()
        while tokens:
            try:
                expr = read_tokens(tokens)
            except SyntaxError:
                continue
            if isinstance(expr, (list, tuple)) and len(expr) >= 2:
                if expr[0] in DSL_KEYWORDS or expr[0] in SPECIAL_FORMS:
                    names.add(str(expr[1]))
        return names

    def _find_replacement_positions(source: str, local_names: set[str]) -> list[tuple[int, int, str]]:
        """Walk token stream as AST, return (start, end, replacement) for cross-refs."""
        positioned = tokenize_with_positions(source)
        replacements: list[tuple[int, int, str]] = []

        def _read_and_track(idx: int) -> tuple[Any, int, list[tuple[int, int]]]:
            """Parse one expr from positioned[idx:].

            Returns (parsed_expr, next_idx, [(start, end) for each consumed token]).
            """
            if idx >= len(positioned):
                raise SyntaxError("Unexpected EOF")

            tok, s, e = positioned[idx]

            if tok == "(":
                consumed = [(s, e)]
                idx += 1
                children = []
                while idx < len(positioned) and positioned[idx][0] != ")":
                    child, idx, child_consumed = _read_and_track(idx)
                    children.append((child, child_consumed))
                if idx >= len(positioned):
                    raise SyntaxError("Missing )")
                consumed.append((positioned[idx][1], positioned[idx][2]))  # )
                idx += 1
                return children, idx, consumed
            elif tok == ")":
                raise SyntaxError("Unexpected )")
            else:
                if tok == "true":
                    return (True, idx + 1, [(s, e)])
                if tok == "false":
                    return (False, idx + 1, [(s, e)])
                if tok.startswith('"'):
                    return (
                        tok[1:-1].replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\"),
                        idx + 1,
                        [(s, e)],
                    )
                try:
                    return (int(tok), idx + 1, [(s, e)])
                except ValueError:
                    pass
                try:
                    return (float(tok), idx + 1, [(s, e)])
                except ValueError:
                    pass
                return (Symbol(tok), idx + 1, [(s, e)])

        idx = 0
        while idx < len(positioned):
            try:
                result, idx, _ = _read_and_track(idx)
            except SyntaxError:
                idx += 1
                continue

            if not isinstance(result, list) or len(result) < 2:
                continue

            head_expr, _ = result[0]
            is_definition = head_expr in DSL_KEYWORDS or head_expr in SPECIAL_FORMS

            for child_idx, (child_expr, child_consumed) in enumerate(result):
                if child_idx == 0:
                    continue  # skip head keyword
                if child_idx == 1 and is_definition:
                    continue  # skip definition name

                _collect_replacements(child_expr, child_consumed, local_names, replacements)

        return replacements

    def _collect_replacements(expr, consumed, local_names, replacements):
        """Recursively find symbols that need replacing."""
        if isinstance(expr, Symbol) and not str(expr).startswith(("?", ":")):
            bare = str(expr)
            if bare in bare_to_ns and bare not in local_names:
                if consumed:
                    s, e = consumed[0]
                    replacements.append((s, e, f"{bare_to_ns[bare]}.{bare}"))
        elif isinstance(expr, list):
            for child_expr, child_consumed in expr:
                _collect_replacements(child_expr, child_consumed, local_names, replacements)

    def _apply_positional(source: str, replacements: list[tuple[int, int, str]]) -> str:
        """Apply position-based replacements to source, back to front."""
        result = source
        for start, end, replacement in sorted(replacements, key=lambda r: r[0], reverse=True):
            result = result[:start] + replacement + result[end:]
        return result

    previous_modules: list[str] = []

    for module_name, source in pass_sources:
        local_names = _collect_names(source)
        replacements = _find_replacement_positions(source, local_names)

        patched = _apply_positional(source, replacements)

        # Prepend imports for all earlier passes
        if previous_modules:
            imports = "\n".join(f"(import (quote {mod}))" for mod in previous_modules)
            patched = imports + "\n\n" + patched

        patched_sources[module_name] = patched
        previous_modules.append(module_name)

        # Register this pass's names (later passes override)
        for bare in local_names:
            bare_to_ns[bare] = module_name

    return patched_sources, bare_to_ns


def namespace_refs(text: str, bare_to_ns: dict[str, str], prefix: str = "") -> str:
    """Rewrite [[type:name]] refs to use namespaced names.

    bare_to_ns maps bare_name → module (e.g. "pass1").
    prefix is prepended to the module (e.g. "sources." for pgmd context).
    """

    def _replace(m: re.Match) -> str:
        ref_type, ref_name = m.group(1), m.group(2)
        if ref_name in bare_to_ns:
            ns = f"{prefix}{bare_to_ns[ref_name]}.{ref_name}"
            return f"[[{ref_type}:{ns}]]"
        return m.group(0)

    return re.sub(r"\[\[(\w+):([^\]]+)\]\]", _replace, text)
