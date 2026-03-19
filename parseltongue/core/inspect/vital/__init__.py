"""Vital — live probing of engine runtime dependencies.

Stain wraps an engine to capture runtime resolution edges.
live_probe merges stained traces with static structure.
"""

from .live_probe import live_probe
from .stain import Edge, Stain, Trace

__all__ = ["Edge", "Stain", "Trace", "live_probe"]
