"""
Preview router for geotiler.

Serves the same viewer pages as /viewer/* but with iframe-permissive
headers so front-end apps can embed previews cross-origin.
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(prefix="/preview", tags=["Preview"], include_in_schema=False)


def _with_iframe_headers(response):
    """Add iframe-permissive headers to a response."""
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    response.headers["X-Frame-Options"] = "ALLOWALL"
    return response


@router.get("/raster", include_in_schema=False)
async def preview_raster(request: Request):
    """Render the COG raster tile viewer (iframe-embeddable)."""
    return _with_iframe_headers(
        render_template(request, "pages/viewer/raster.html", nav_active="/catalog")
    )


@router.get("/zarr", include_in_schema=False)
async def preview_zarr(request: Request):
    """Render the Zarr/NetCDF multidimensional viewer (iframe-embeddable)."""
    return _with_iframe_headers(
        render_template(request, "pages/viewer/zarr.html", nav_active="/catalog")
    )


@router.get("/vector", include_in_schema=False)
async def preview_vector(request: Request):
    """Render the OGC Features vector viewer (iframe-embeddable)."""
    return _with_iframe_headers(
        render_template(request, "pages/viewer/vector.html", nav_active="/catalog")
    )
