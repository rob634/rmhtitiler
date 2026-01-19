"""
COG Landing Page.

Provides an interactive landing page for exploring Cloud Optimized GeoTIFFs.
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(tags=["Landing Pages"])


@router.get("/cog/", include_in_schema=False)
async def cog_landing(request: Request):
    """
    COG Explorer landing page.

    Provides an interface to explore Cloud Optimized GeoTIFFs with:
    - URL input form
    - Quick action buttons (info, viewer, tilejson, statistics)
    - Sample COG URLs
    - Endpoint reference
    """
    return render_template(
        request,
        "pages/cog/landing.html",
        nav_active="/cog/"
    )
