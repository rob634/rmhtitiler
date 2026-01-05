"""
DEPRECATED: This file is maintained for backwards compatibility.

Use `rmhtitiler.app:app` instead:
    uvicorn rmhtitiler.app:app --host 0.0.0.0 --port 8000

This shim will be removed in a future version.
"""

import warnings

warnings.warn(
    "custom_pgstac_main is deprecated. Use 'rmhtitiler.app:app' instead. "
    "Example: uvicorn rmhtitiler.app:app --host 0.0.0.0 --port 8000",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export app from new location
from rmhtitiler.app import app
from rmhtitiler import __version__

__all__ = ["app", "__version__"]
