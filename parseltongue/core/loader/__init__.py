"""
Parseltongue Loader package.

Re-exports the standard loader API for backward compatibility,
plus the lazy loader and AST types.
"""

from .lazy_loader import LazyLoader, LazyLoadResult, lazy_load_pltg  # noqa: F401
from .loader import Context, Loader, LoaderContext, ModuleContext, load_pltg  # noqa: F401
