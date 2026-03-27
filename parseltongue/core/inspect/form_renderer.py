"""FormRenderer — fmt entry point for rendering bench forms and values.

Registered by name on the bench system. (fmt "md" value) dispatches here.

A FormRenderer can:
- Stand alone (e.g. VizRenderer produces HTML without a Perspective)
- Wrap a Perspective (e.g. MdRenderer delegates form layout to MDebuggerPerspective)
- Be a Perspective via inheritance
"""

from __future__ import annotations

from typing import Any


def _to_sexp(val: Any) -> str:
    """Fallback: render any value as an s-expression string."""
    if val is None:
        return "nil"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return val
    if isinstance(val, (list, tuple)):
        if not val:
            return "()"
        return "(" + " ".join(_to_sexp(x) for x in val) + ")"
    if isinstance(val, dict):
        if not val:
            return "(empty)"
        items = list(val.items())[:20]
        return "(" + " ".join(f"({_to_sexp(k)} {_to_sexp(v)})" for k, v in items) + ")"
    return str(val)


#: Tags recognized as bench forms.
FORM_TAGS = frozenset({"sr", "ln", "dx", "hn", "df", "sr-fmt", "ln-fmt", "dx-fmt", "hn-fmt"})


def _is_form(val) -> bool:
    """Check if val is a tagged bench form."""
    from ..atoms import Symbol

    return (
        isinstance(val, (list, tuple))
        and len(val) >= 2
        and isinstance(val[0], Symbol)
        and str(val[0]).rsplit(".", 1)[-1] in FORM_TAGS
    )


class FormRenderer:
    """Base class for fmt renderers.

    Subclass and override render_form / render_form_list / fmt_value.
    """

    def fmt(self, val: Any) -> Any:
        """Format any value. Dispatches forms, lists of forms, or scalars."""
        if _is_form(val):
            return self.render_form(val)
        if isinstance(val, (list, tuple)) and val and _is_form(val[0]):
            return self.render_form_list(list(val))
        return self.fmt_value(val)

    def render_form(self, form: list) -> Any:
        """Render a single tagged form."""
        return _to_sexp(form)

    def render_form_list(self, forms: list[list]) -> Any:
        """Render a list of tagged forms."""
        return "\n".join(str(self.render_form(f)) for f in forms)

    def fmt_value(self, val: Any) -> Any:
        """Render a non-form value. Default: s-expression string."""
        return _to_sexp(val)
