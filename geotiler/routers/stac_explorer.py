"""
STAC Explorer GUI.

Provides an interactive web interface for browsing STAC collections and items,
with integrated map visualization and JSON viewer.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from geotiler.config import settings
from geotiler.templates_utils import templates, get_template_context

router = APIRouter(tags=["STAC Explorer"])


@router.get("/stac-explorer", response_class=HTMLResponse, include_in_schema=False)
async def stac_explorer(request: Request):
    """
    STAC Explorer GUI.

    Interactive web interface for browsing STAC collections and items:
    - Collection sidebar with search/filter
    - Map view with item footprints (Leaflet)
    - Item details with JSON viewer
    - Asset list with "View on Map" for COG assets
    """
    stac_enabled = settings.enable_stac_api and settings.enable_tipg

    context = get_template_context(
        request,
        stac_enabled=stac_enabled,
        nav_active="/stac-explorer"
    )
    return templates.TemplateResponse("pages/stac/explorer.html", context)
