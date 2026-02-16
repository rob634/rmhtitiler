"""FastAPI routers for health probes and custom endpoints."""

from geotiler.routers import health, admin, vector, stac, diagnostics, h3_explorer

__all__ = ["health", "admin", "vector", "stac", "diagnostics", "h3_explorer"]
