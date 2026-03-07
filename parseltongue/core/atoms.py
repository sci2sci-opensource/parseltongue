"""
Parseltongue DSL — Atoms.

Pure types, s-expression reader/printer.
No domain knowledge, no state.
"""

from dataclasses import dataclass, field
from typing import Any

# ============================================================
# S-Expression Reader
# ============================================================


class Symbol(str):
    """A symbol in Parseltongue. Just a string with a distinct type."""

    def __repr__(self):
        return f"'{self}"


def tokenize(source: str) -> list[str]:
    """Tokenize s-expression source into atoms and parens."""
    tokens = []
    in_string = False
    in_comment = False
    escaped = False
    current: list[str] = []
    for char in source:
        if char == "\n":
            in_comment = False
            escaped = False
            if not in_string and current:
                tokens.append("".join(current))
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
                tokens.append("".join(current))
                current = []
            else:
                current.append(char)
            continue
        if char == ";":
            in_comment = True
            if current:
                tokens.append("".join(current))
                current = []
            continue
        if char == '"':
            in_string = True
            current.append(char)
        elif char in "()":
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(char)
        elif char in " \t\n\r":
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def read_tokens(tokens: list[str]) -> Any:
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
        return expr
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


def parse(source: str) -> Any:
    """Parse a source string into an s-expression."""
    tokens = tokenize(source)
    return read_tokens(tokens)


def parse_all(source: str) -> list:
    """Parse all top-level s-expressions from source."""
    tokens = tokenize(source)
    exprs = []
    while tokens:
        exprs.append(read_tokens(tokens))
    return exprs


def to_sexp(obj) -> str:
    """Pretty-print a Python object back to s-expression string."""
    if isinstance(obj, list):
        return "(" + " ".join(to_sexp(x) for x in obj) + ")"
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif isinstance(obj, str) and not isinstance(obj, Symbol):
        escaped = obj.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'
    else:
        return str(obj)


# ============================================================
# Data Structures
# ============================================================


def _origin_tag(origin) -> str:
    if isinstance(origin, Evidence):
        return str(origin)
    return f"[origin: {origin}]"


@dataclass(frozen=True)
class Evidence:
    """Structured evidence with verifiable quotes from a source document."""

    document: str  # registered document name
    quotes: list[str]  # exact quotes from the document
    explanation: str = ""  # why these quotes support the claim
    verification: list = field(default_factory=list)  # filled by verifier
    verified: bool = False  # all quotes verified?
    verify_manual: bool = False  # manually verified by user?

    @property
    def is_grounded(self) -> bool:
        """Evidence is grounded if verified or manually verified."""
        return self.verified or self.verify_manual

    def __str__(self):
        status = "grounded" if self.is_grounded else "UNVERIFIED"
        return f"[evidence: {self.document} ({status})]"


@dataclass(frozen=True)
class Axiom:
    """An axiom: a foundational WFF assumed true, with evidence.

    Every axiom carries a wff (never None).
    """

    name: str
    wff: Any
    origin: "str | Evidence"

    def __str__(self):
        return f"{self.name}: {to_sexp(self.wff)} {_origin_tag(self.origin)}"


@dataclass(frozen=True)
class Theorem:
    """A theorem: a WFF derived from facts, axioms, terms, or other theorems.

    Every theorem carries a wff (never None).
    """

    name: str
    wff: Any
    derivation: list = field(default_factory=list)
    origin: "str | Evidence" = "derived"

    def __str__(self):
        tag = f"[derived from: {', '.join(self.derivation)}]"
        return f"{self.name}: {to_sexp(self.wff)} {tag}"


@dataclass(frozen=True)
class Term:
    """A term/concept/primitive introduced into the system.

    Has two modes: primitive (definition is None) or computed (definition is not None).
    """

    name: str
    definition: Any
    origin: "str | Evidence"

    def __str__(self):
        defn = to_sexp(self.definition) if self.definition is not None else "(primitive)"
        return f"{self.name}: {defn} {_origin_tag(self.origin)}"


# ============================================================
# DSL Helpers
# ============================================================


def get_keyword(expr, keyword, default=None):
    """Extract a keyword argument from an expression."""
    for i, item in enumerate(expr):
        if item == keyword and i + 1 < len(expr):
            return expr[i + 1]
    return default


def match(pattern, expr, bindings=None):
    """Match pattern against expr. ?-prefixed symbols are pattern variables.

    A ``?...name`` symbol as the last element of a list pattern matches
    zero or more remaining elements, bound as a list.
    """
    if bindings is None:
        bindings = {}
    if isinstance(pattern, Symbol) and str(pattern).startswith("?"):
        if pattern in bindings:
            return bindings if bindings[pattern] == expr else None
        return {**bindings, pattern: expr}
    if isinstance(pattern, list) and isinstance(expr, list):
        # Splat: ?...name as last element matches remaining items
        if pattern and isinstance(pattern[-1], Symbol) and str(pattern[-1]).startswith("?..."):
            splat = pattern[-1]
            fixed = pattern[:-1]
            if len(expr) < len(fixed):
                return None
            for p, e in zip(fixed, expr[: len(fixed)]):
                bindings = match(p, e, bindings)
                if bindings is None:
                    return None
            rest = expr[len(fixed) :]
            if splat in bindings:
                return bindings if bindings[splat] == rest else None
            return {**bindings, splat: rest}
        if len(pattern) != len(expr):
            return None
        for p, e in zip(pattern, expr):
            bindings = match(p, e, bindings)
            if bindings is None:
                return None
        return bindings
    if pattern == expr:
        return bindings
    return None


def free_vars(expr) -> set:
    """Extract all ?-prefixed symbols from an expression."""
    if isinstance(expr, Symbol) and str(expr).startswith("?"):
        return {expr}
    if isinstance(expr, list):
        result = set()
        for sub in expr:
            result |= free_vars(sub)
        return result
    return set()


def substitute(expr, bindings: dict):
    """Replace symbols with their bound values in an expression tree.

    ``?...name`` bindings are spliced into the parent list rather than
    inserted as a nested list.
    """
    if isinstance(expr, Symbol) and expr in bindings:
        return bindings[expr]
    if isinstance(expr, list):
        result = []
        for sub in expr:
            if isinstance(sub, Symbol) and str(sub).startswith("?...") and sub in bindings:
                val = bindings[sub]
                if isinstance(val, list):
                    result.extend(val)
                else:
                    result.append(val)
            else:
                result.append(substitute(sub, bindings))
        return result
    return expr
