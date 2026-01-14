"""FastAPI routers for health probes and custom endpoints."""

from geotiler.routers import health, planetary_computer, admin, vector, stac, diagnostics

__all__ = ["health", "planetary_computer", "admin", "vector", "stac", "diagnostics"]
