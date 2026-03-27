"""Vital — live probing of engine runtime dependencies.

Tracer (stack engine): native tracing via express/suppress.
Stain (recursive engine): monkey-patch tracing via apply/remove.
trace_engine: auto-detect and trace.
live_probe merges traced edges with static structure.
"""

from .live_probe import live_probe, probe_diffs_to_possibilities, trace_engine
from .stain import Edge, Stain, Trace
from .tracer import Tracer

__all__ = ["Edge", "Stain", "Trace", "Tracer", "live_probe", "probe_diffs_to_possibilities", "trace_engine"]
