"""
Admin console and API info endpoints.

Provides:
- GET / - HTML admin dashboard with health visualization
- GET /api - JSON API information
- GET /_health-fragment - HTMX partial for auto-refresh
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from geotiler import __version__
from geotiler.config import settings
from geotiler.routers.health import health as get_health_data
from geotiler.templates_utils import templates, get_template_context

router = APIRouter(tags=["Admin"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_console(request: Request):
    """
    Admin console dashboard with health visualization.

    Displays:
    - System status with memory/CPU stats
    - Service status cards (COG, XArray, pgSTAC, TiPG, STAC API)
    - Dependency status (database, OAuth tokens)
    - Configuration flags
    - Issues list (if any)

    Auto-refreshes every 30 seconds via HTMX.
    """
    response = Response()
    health_data = await get_health_data(request, response)

    context = get_template_context(request, health=health_data, nav_active="/")
    return templates.TemplateResponse("pages/admin/index.html", context)


@router.get("/_health-fragment", response_class=HTMLResponse, include_in_schema=False)
async def health_fragment(request: Request):
    """
    HTMX partial for health status auto-refresh.

    Returns only the health content section (no navbar/footer).
    Called every 30 seconds when auto-refresh is enabled.
    """
    response = Response()
    health_data = await get_health_data(request, response)

    context = get_template_context(request, health=health_data)
    return templates.TemplateResponse("pages/admin/_health_fragment.html", context)


@router.get("/api")
async def api_info():
    """
    JSON API information endpoint.

    Returns API metadata and available endpoints.
    """
    return {
        "title": "geotiler - TiTiler with Azure OAuth",
        "description": "Geospatial tile server with Azure Managed Identity authentication",
        "version": __version__,
        "auth_type": "OAuth Bearer Token (Managed Identity)",
        "endpoints": {
            "admin": "/",
            "liveness": "/livez",
            "readiness": "/readyz",
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc",
            "cog_info": "/cog/info",
            "cog_tiles": "/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "xarray_info": "/xarray/info",
            "xarray_tiles": "/xarray/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "search_list": "/searches",
            "search_register": "/searches/register",
            "search_tiles": "/searches/{search_id}/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "search_info": "/searches/{search_id}/info",
            "vector_collections": "/vector/collections",
            "vector_items": "/vector/collections/{collection_id}/items",
            "vector_tiles": "/vector/collections/{collection_id}/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "stac_root": "/stac",
            "stac_collections": "/stac/collections",
            "stac_search": "/stac/search",
        },
        "config": {
            "local_mode": settings.local_mode,
            "azure_auth": settings.use_azure_auth,
            "tipg_enabled": settings.enable_tipg,
            "stac_api_enabled": settings.enable_stac_api,
            "planetary_computer_enabled": settings.enable_planetary_computer,
        },
    }
