"""
Map Viewer - Interactive map viewer for geotiler services.

Provides a unified MapLibre-based viewer for:
- TiPG vector collections (MVT tiles)
- COG raster tiles
- XArray raster tiles
- pgSTAC mosaic searches

Features:
- Three-panel layout (catalog, map, active layers)
- Add/remove layers from map
- Layer styling controls
- No persistent state (configure and forget)
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from geotiler.config import settings
from geotiler.templates_utils import templates, get_template_context

router = APIRouter(tags=["Map Viewer"])


@router.get("/map", response_class=HTMLResponse, include_in_schema=False)
async def map_viewer(request: Request):
    """
    Interactive map viewer for geotiler services.

    Displays:
    - Left panel: Available data sources (Vector, COG, XArray, Searches)
    - Center: MapLibre GL JS map
    - Right panel: Active layers with controls

    Uses MapLibre GL JS for vector tiles (MVT) and raster tiles.
    """
    context = get_template_context(
        request,
        nav_active="/map",
        tipg_enabled=settings.enable_tipg,
        stac_enabled=settings.enable_stac_api and settings.enable_tipg,
    )
    return templates.TemplateResponse("pages/map/viewer.html", context)
