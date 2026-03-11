"""Inspection tools for parseltongue engines — structure analysis, perspectives, lenses."""

from parseltongue.core.inspect.lens import Lens, inspect, inspect_loaded
from parseltongue.core.inspect.perspective import Perspective
from parseltongue.core.inspect.probe_core_to_consequence import probe

__all__ = ["probe", "inspect", "inspect_loaded", "Lens", "Perspective"]
