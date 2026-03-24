"""VizRenderer — re-export from visualisation module.

The implementation lives in parseltongue/core/inspect/perspectives/visualisation/.
This shim preserves backwards-compatible imports.
"""

from .visualisation import VizRenderer

__all__ = ["VizRenderer"]
