"""
Searches Landing Page.

Provides an interactive landing page for pgSTAC dynamic mosaic searches.
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(tags=["Landing Pages"])


@router.get("/searches/", include_in_schema=False)
async def searches_landing(request: Request):
    """
    pgSTAC Searches landing page.

    Provides an interface to browse and visualize registered mosaic searches:
    - Lists all registered searches
    - Quick links to viewer, info, and tilejson for each search
    - Documentation on how to register new searches
    - Example search registration payload
    """
    return render_template(
        request,
        "pages/searches/landing.html",
        nav_active="/searches/"
    )
