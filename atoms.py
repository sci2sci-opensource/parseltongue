"""
Parseltongue DSL — Atoms.

Pure types, s-expression reader/printer.
No domain knowledge, no state.
"""

from dataclasses import dataclass, field
from typing import Any
import re


# ============================================================
# S-Expression Reader
# ============================================================

class Symbol(str):
    """A symbol in Parseltongue. Just a string with a distinct type."""
    def __repr__(self):
        return f"'{self}"


def tokenize(source: str) -> list[str]:
    """Tokenize s-expression source into atoms and parens."""
    source = re.sub(r';.*$', '', source, flags=re.MULTILINE)
    tokens = []
    in_string = False
    current = []
    for char in source:
        if char == '"' and not in_string:
            in_string = True
            current.append(char)
        elif char == '"' and in_string:
            in_string = False
            current.append(char)
            tokens.append(''.join(current))
            current = []
        elif in_string:
            current.append(char)
        elif char in '()':
            if current:
                tokens.append(''.join(current))
                current = []
            tokens.append(char)
        elif char in ' \t\n\r':
            if current:
                tokens.append(''.join(current))
                current = []
        else:
            current.append(char)
    if current:
        tokens.append(''.join(current))
    return tokens


def read_tokens(tokens: list[str]) -> Any:
    """Recursively parse token list into nested Python structures."""
    if not tokens:
        raise SyntaxError("Unexpected EOF")

    token = tokens.pop(0)

    if token == '(':
        expr = []
        while tokens and tokens[0] != ')':
            expr.append(read_tokens(tokens))
        if not tokens:
            raise SyntaxError("Missing closing )")
        tokens.pop(0)
        return expr
    elif token == ')':
        raise SyntaxError("Unexpected )")
    else:
        return atom(token)


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
    if token == 'true':
        return True
    if token == 'false':
        return False
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    if token.startswith(':'):
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
        return '(' + ' '.join(to_sexp(x) for x in obj) + ')'
    elif isinstance(obj, bool):
        return 'true' if obj else 'false'
    elif isinstance(obj, str) and not isinstance(obj, Symbol):
        return f'"{obj}"'
    else:
        return str(obj)


# ============================================================
# Data Structures
# ============================================================

@dataclass
class Evidence:
    """Structured evidence with verifiable quotes from a source document."""
    document: str               # registered document name
    quotes: list[str]           # exact quotes from the document
    explanation: str = ""       # why these quotes support the claim
    verification: list = field(default_factory=list)  # filled by verifier
    verified: bool = False      # all quotes verified?
    verify_manual: bool = False # manually verified by user?

    @property
    def is_grounded(self) -> bool:
        """Evidence is grounded if verified or manually verified."""
        return self.verified or self.verify_manual


@dataclass
class Axiom:
    """An axiom: a WFF with evidence."""
    name: str
    wff: Any
    origin: 'str | Evidence'
    derived: bool = False
    derivation: list = field(default_factory=list)


@dataclass
class Term:
    """A term/concept introduced into the system."""
    name: str
    definition: Any
    origin: 'str | Evidence'


# ============================================================
# DSL Helpers
# ============================================================

def get_keyword(expr, keyword, default=None):
    """Extract a keyword argument from an expression."""
    for i, item in enumerate(expr):
        if item == keyword and i + 1 < len(expr):
            return expr[i + 1]
    return default
