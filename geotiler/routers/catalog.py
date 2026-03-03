"""
Catalog router for geotiler.

Serves the unified catalog page and type-specific sub-pages for
STAC collections and Vector (OGC Features) collections.
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(prefix="/catalog", tags=["Catalog"], include_in_schema=False)


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def unified_catalog(request: Request):
    """Render the unified catalog page with all collection types."""
    return render_template(request, "pages/catalog/unified.html", nav_active="/catalog")


@router.get("/stac", include_in_schema=False)
async def stac_catalog(request: Request):
    """Render the STAC collections catalog page."""
    return render_template(request, "pages/catalog/stac.html", nav_active="/catalog")


@router.get("/vector", include_in_schema=False)
async def vector_catalog(request: Request):
    """Render the vector collections catalog page."""
    return render_template(request, "pages/catalog/vector.html", nav_active="/catalog")
