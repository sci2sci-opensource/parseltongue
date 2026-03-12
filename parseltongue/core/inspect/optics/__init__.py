"""Optics — optical instruments for viewing provenance structures.

Lens views a single structure. Hologram views N structures combined via Bias.
Both inherit from Optics ABC and the Searchable mixin.
"""

from .base import Optics
from .hologram import Bias, Hologram
from .lens import Lens

__all__ = ["Optics", "Lens", "Hologram", "Bias"]
