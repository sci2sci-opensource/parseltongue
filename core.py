"""
Parseltongue DSL — backward-compatible re-export.

Language core: lang.py
Runtime engine: engine.py
"""

try:
    from lang import *        # noqa: F401,F403
    from engine import *      # noqa: F401,F403
except ImportError:
    from .lang import *       # noqa: F401,F403
    from .engine import *     # noqa: F401,F403
