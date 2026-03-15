"""
Parseltongue DSL — Grammar.

How atoms are written and read: tokenization, parsing, and serialization.
No meaning, no evaluation — just structure.
"""

import logging
from typing import Callable, Literal, Protocol, TypeVar, overload

from .atoms import SILENCE, WFF, Symbol

log = logging.getLogger("parseltongue.grammar")

R = TypeVar("R")

# ============================================================
# Grammar Protocol
# ============================================================


class Grammar(Protocol[R]):
    """Codec between atoms and a representation."""

    def encode(self, wff: WFF) -> R: ...
    def decode(self, source: R) -> WFF: ...


# ============================================================
# String Grammar — Grammar[str] with pluggable encode/decode
# ============================================================


class StringGrammar(Grammar[str]):
    """Grammar[str] — instantiated with encode/decode callables."""

    def __init__(self, encode: Callable[[WFF], str], decode: Callable[[str], WFF]):
        self._encode = encode
        self._decode = decode

    def encode(self, wff: WFF) -> str:
        return self._encode(wff)

    def decode(self, source: str) -> WFF:
        return self._decode(source)


# ============================================================
# Tokenizer
# ============================================================


@overload
def tokenize(source: str, *, track_lines: Literal[False] = ...) -> list[str]: ...
@overload
def tokenize(source: str, *, track_lines: Literal[True]) -> tuple[list[str], list[int]]: ...
def tokenize(source: str, *, track_lines: bool = False) -> list[str] | tuple[list[str], list[int]]:
    """Tokenize s-expression source into atoms and parens.

    If *track_lines* is True, returns ``(tokens, token_lines)`` where
    ``token_lines[i]`` is the 1-based line number of ``tokens[i]``.
    """
    tokens = []
    token_lines: list[int] = []
    line_no = 1
    in_string = False
    in_comment = False
    escaped = False
    current: list[str] = []
    current_start_line = 1
    for char in source:
        if char == "\n":
            in_comment = False
            escaped = False
            if not in_string and current:
                tokens.append("".join(current))
                token_lines.append(current_start_line)
                current = []
            elif in_string:
                current.append(char)
            line_no += 1
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
                tokens.append("".join(current))
                token_lines.append(current_start_line)
                current = []
            else:
                current.append(char)
            continue
        if char == ";":
            in_comment = True
            if current:
                tokens.append("".join(current))
                token_lines.append(current_start_line)
                current = []
            continue
        if char == '"':
            if not current:
                current_start_line = line_no
            in_string = True
            current.append(char)
        elif char in "()":
            if current:
                tokens.append("".join(current))
                token_lines.append(current_start_line)
                current = []
            tokens.append(char)
            token_lines.append(line_no)
        elif char in " \t\n\r":
            if current:
                tokens.append("".join(current))
                token_lines.append(current_start_line)
                current = []
        else:
            if not current:
                current_start_line = line_no
            current.append(char)
    if current:
        tokens.append("".join(current))
        token_lines.append(current_start_line)
    if track_lines:
        return tokens, token_lines
    return tokens


# ============================================================
# Reader
# ============================================================


def read_tokens(tokens: list[str]) -> WFF:
    """Recursively parse token list into nested Python structures."""
    if not tokens:
        raise SyntaxError("Unexpected EOF")

    token = tokens.pop(0)

    if token == "(":
        expr = []
        while tokens and tokens[0] != ")":
            expr.append(read_tokens(tokens))
        if not tokens:
            raise SyntaxError("Missing closing )")
        tokens.pop(0)
        return tuple(expr)
    elif token == ")":
        raise SyntaxError("Unexpected )")
    else:
        return atom(token)


_ESCAPE_MAP = {'"': '"', '\\': '\\', 'n': '\n', 't': '\t'}


def _unescape(s: str) -> str:
    """Single-pass string unescape: \\n → newline, \\\\ → \\, \\" → "."""
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s) and s[i + 1] in _ESCAPE_MAP:
            out.append(_ESCAPE_MAP[s[i + 1]])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def atom(token: str):
    """Convert a token string to a typed value."""
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    if token == "true":
        return True
    if token == "false":
        return False
    if token.startswith('"') and token.endswith('"'):
        return _unescape(token[1:-1])
    if token.startswith(":"):
        return token
    return Symbol(token)


# ============================================================
# Printer
# ============================================================


def to_sexp(obj) -> str:
    """Pretty-print a Python object back to s-expression string."""
    if isinstance(obj, (list, tuple)):
        return "(" + " ".join(to_sexp(x) for x in obj) + ")"
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif isinstance(obj, str) and not isinstance(obj, Symbol):
        escaped = obj.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'
    else:
        return str(obj)


# ============================================================
# S-Expression Grammar — implements Grammar protocol
# ============================================================


def _decode_sexp(source: str) -> WFF:
    tokens = tokenize(source)
    if not tokens:
        return SILENCE
    return read_tokens(tokens)


_pg = StringGrammar(encode=to_sexp, decode=_decode_sexp)


class ParseltongueGrammar:
    """S-expression grammar for Parseltongue."""

    grammar: Grammar[str] = _pg

    @staticmethod
    def enc(wff: WFF) -> str:
        return _pg.encode(wff)

    @staticmethod
    def dec(source: str) -> WFF:
        return _pg.decode(source)
