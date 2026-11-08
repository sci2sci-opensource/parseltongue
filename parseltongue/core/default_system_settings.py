"""
Default operator environment and documentation for Parseltongue systems.
"""

import operator
from typing import Any

from .atoms import Symbol
from .lang import EQ

# ============================================================
# Operator Constants
# ============================================================

# Arithmetic
ADD = Symbol("+")
SUB = Symbol("-")
MUL = Symbol("*")
DIV = Symbol("/")
MOD = Symbol("mod")

# Comparison
GT = Symbol(">")
LT = Symbol("<")
GE = Symbol(">=")
LE = Symbol("<=")
NE = Symbol("!=")

# Logic
AND = Symbol("and")
OR = Symbol("or")
NOT = Symbol("not")
IMPLIES = Symbol("implies")

# Records
GET = Symbol("get")

ARITHMETIC_OPS = (ADD, SUB, MUL, DIV, MOD)
COMPARISON_OPS = (GT, LT, GE, LE, EQ, NE)
LOGIC_OPS = (AND, OR, NOT, IMPLIES)
RECORD_OPS = (GET,)


# ============================================================
# Engine Documentation
# ============================================================

ENGINE_DOCS = {
    # Arithmetic
    ADD: {
        "category": "arithmetic",
        "description": "Add two numbers.  Also used symbolically in formal terms: (+ eve-morning adam-morning).",
        "example": "(+ 2 3)",
        "expected": 5,
    },
    SUB: {
        "category": "arithmetic",
        "description": "Subtract second from first.  Useful for computing "
        "differences between terms: (- morning-total afternoon-total).",
        "example": "(- 10 4)",
        "expected": 6,
    },
    MUL: {
        "category": "arithmetic",
        "description": "Multiply two numbers.  Used in computed terms like "
        "bonus calculations: (* base-salary bonus-rate).",
        "example": "(* 3 7)",
        "expected": 21,
    },
    DIV: {
        "category": "arithmetic",
        "description": "Divide first by second (true division).  Used for computing ratios: (/ (- q3 q2) q2).",
        "example": "(/ 10 2)",
        "expected": 5.0,
    },
    MOD: {
        "category": "arithmetic",
        "description": "Remainder of first divided by second.",
        "example": "(mod 10 3)",
        "expected": 1,
    },
    # Comparison
    GT: {
        "category": "comparison",
        "description": "True if first is strictly greater than second.  "
        "Common in term definitions: (> sensitivity 90).",
        "example": "(> 5 3)",
        "expected": True,
    },
    LT: {
        "category": "comparison",
        "description": "True if first is strictly less than second.",
        "example": "(< 2 8)",
        "expected": True,
    },
    GE: {
        "category": "comparison",
        "description": "True if first is greater than or equal to second.",
        "example": "(>= 5 5)",
        "expected": True,
    },
    LE: {
        "category": "comparison",
        "description": "True if first is less than or equal to second.",
        "example": "(<= 3 5)",
        "expected": True,
    },
    EQ: {
        "category": "comparison",
        "description": "True if both values are equal.  Also the core of "
        "rewrite rules — axioms of the form (= LHS RHS) are "
        "applied as left-to-right rewrites during evaluation.",
        "example": "(= 5 5)",
        "expected": True,
    },
    NE: {
        "category": "comparison",
        "description": "True if values are not equal.",
        "example": "(!= 5 6)",
        "expected": True,
    },
    # Logic
    AND: {
        "category": "logic",
        "description": "Logical AND (variadic).  True only if all operands are true.  "
        "Accepts 2 or more arguments: (and a b), (and a b c d).",
        "example": "(and true true false)",
        "expected": False,
    },
    OR: {
        "category": "logic",
        "description": "Logical OR (variadic).  True if at least one operand is true.  "
        "Accepts 2 or more arguments: (or a b), (or a b c d).",
        "example": "(or false false true)",
        "expected": True,
    },
    NOT: {
        "category": "logic",
        "description": "Logical NOT.  Negates a boolean.  Used in derivations: (not (> specificity 90)).",
        "example": "(not true)",
        "expected": False,
    },
    IMPLIES: {
        "category": "logic",
        "description": "Logical implication.  False only when antecedent is true and consequent is false.",
        "example": "(implies true false)",
        "expected": False,
    },
    # Records
    GET: {
        "category": "record",
        "description": "The value of a record's field.  A record is a keyword list, "
        "(:x 1 :y 2); (get r :x) is the value after :x.  Typed by the "
        "record's type: an unknown field is a type error.",
        "example": "(get (quote (:x 1 :y 2)) :y)",
        "expected": 2,
    },
}


# ============================================================
# Default Operator Mapping
# ============================================================


def typed_equal(a: Any, b: Any) -> bool:
    """Equality that keeps Bool and Num apart: true is not 1."""
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def typed_order(compare: Any) -> Any:
    """An order comparison that orders two members of one enumeration by rank and
    refuses to order members of different enumerations, or a member and a non-member."""

    def ordered(a: Any, b: Any) -> bool:
        ra, rb = getattr(a, "rank", None), getattr(b, "rank", None)
        if ra is None and rb is None:
            return bool(compare(a, b))
        if ra is None or rb is None or getattr(a, "enum", None) != getattr(b, "enum", None):
            raise TypeError(f"{a} and {b} are not members of one ordered enumeration")
        return bool(compare(ra, rb))

    return ordered


def record_get(record: Any, field: Any) -> Any:
    """The value after ``field`` in a keyword list ``(:k v :k v …)``."""
    items = list(record)
    for i in range(0, len(items) - 1, 2):
        if items[i] == field:
            return items[i + 1]
    raise KeyError(f"record has no field {field}")


DEFAULT_OPERATORS: dict[Symbol, Any] = {
    # Special case, eq from lang can act as operator (variadic: all args equal)
    EQ: lambda *args: all(typed_equal(a, args[0]) for a in args[1:]),
    # Arithmetic
    ADD: operator.add,
    SUB: operator.sub,
    MUL: operator.mul,
    DIV: operator.truediv,
    MOD: operator.mod,
    # Comparison
    GT: typed_order(operator.gt),
    LT: typed_order(operator.lt),
    GE: typed_order(operator.ge),
    LE: typed_order(operator.le),
    NE: lambda a, b: not typed_equal(a, b),
    # Logic
    AND: lambda *args: all(args),
    OR: lambda *args: any(args),
    NOT: lambda a: not a,
    IMPLIES: lambda a, b: bool((not a) or b),
    # Records
    GET: record_get,
}
