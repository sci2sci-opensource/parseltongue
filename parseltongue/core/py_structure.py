"""The structure of a Python source, as values — what the ``py-ast`` effect returns.

A quote can say that a line exists; it cannot say how many members an enum has
without restating them, and a restated count keeps matching after the code
grows. ``py_structure`` reads the source with Python's own parser and returns the
names a structural query asks for, in source order, so a count derived from it
changes when the code does.

Queries (``kind``, ``name``):

- ``members``  NAME — names assigned in class NAME's body (an enum's members)
- ``fields``   NAME — annotated names in class NAME's body (a dataclass's fields)
- ``methods``  NAME — functions defined in class NAME's body
- ``functions``     — functions defined at module level
- ``classes``       — classes defined at module level
- ``keys``     NAME — keys of the dict literal assigned to NAME, as source text
- ``items``    NAME — elements of the tuple or list literal assigned to NAME, as source text
"""

from __future__ import annotations

import ast

KINDS = ("members", "fields", "methods", "functions", "classes", "keys", "items")


def py_structure(source: str, kind: str, name: "str | None" = None) -> list[str]:
    """The names ``kind`` (of ``name``) asks for in ``source``. Raises ``ValueError``
    for an unknown query or a name the source does not define."""
    if kind not in KINDS:
        raise ValueError(f"unknown query {kind!r}: one of {', '.join(KINDS)}")
    tree = ast.parse(source)
    if kind == "functions":
        return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if kind == "classes":
        return [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    if name is None:
        raise ValueError(f"query {kind!r} needs a name")
    if kind in ("members", "fields", "methods"):
        cls = _find(tree.body, ast.ClassDef, name)
        if kind == "members":
            return [t.id for n in cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        if kind == "fields":
            return [n.target.id for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
        return [n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    value = _assigned(tree.body, name)
    if kind == "keys":
        if not isinstance(value, ast.Dict):
            raise ValueError(f"{name} is not assigned a dict literal")
        return [ast.unparse(k) for k in value.keys if k is not None]
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise ValueError(f"{name} is not assigned a tuple or list literal")
    return [ast.unparse(e) for e in value.elts]


def _find(body: list[ast.stmt], node_type: type, name: str):
    for n in body:
        if isinstance(n, node_type) and getattr(n, "name", None) == name:
            return n
    raise ValueError(f"no {node_type.__name__} named {name!r}")


def _assigned(body: list[ast.stmt], name: str) -> ast.expr:
    for n in body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return n.value
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name and n.value:
            return n.value
    raise ValueError(f"no module-level assignment to {name!r}")
