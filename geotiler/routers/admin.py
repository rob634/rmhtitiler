"""
Admin console and API info endpoints.

Provides:
- GET / - HTML admin dashboard with health visualization
- GET /api - JSON API information
- GET /_health-fragment - HTMX partial for auto-refresh
- POST /admin/refresh-collections - Webhook to refresh TiPG collection catalog (auth required)
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from geotiler import __version__
from geotiler.config import settings
from geotiler.routers.health import health as get_health_data
from geotiler.templates_utils import templates, get_template_context
from geotiler.auth.admin_auth import require_admin_auth

logger = logging.getLogger(__name__)

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
            "vector_refresh": "/admin/refresh-collections (POST)",
            "stac_root": "/stac",
            "stac_collections": "/stac/collections",
            "stac_search": "/stac/search",
        },
        "config": {
            "auth_use_cli": settings.auth_use_cli,
            "enable_storage_auth": settings.enable_storage_auth,
            "enable_tipg": settings.enable_tipg,
            "enable_tipg_catalog_ttl": settings.enable_tipg_catalog_ttl,
            "tipg_catalog_ttl_sec": settings.tipg_catalog_ttl_sec if settings.enable_tipg_catalog_ttl else None,
            "enable_stac_api": settings.enable_stac_api,
            "enable_planetary_computer": settings.enable_planetary_computer,
        },
    }


@router.post("/admin/refresh-collections", dependencies=[Depends(require_admin_auth)])
async def refresh_collections(request: Request):
    """
    Webhook to refresh TiPG collection catalog.

    **Authentication**: Requires Azure AD Bearer token when GEOTILER_ENABLE_ADMIN_AUTH=true.
    The calling app's Managed Identity client ID must be in GEOTILER_ADMIN_ALLOWED_APP_IDS.

    Call this endpoint after ETL pipelines create new PostGIS tables
    to make them immediately visible in TiPG without waiting for TTL
    or application restart.

    This is the recommended integration point for Orchestrator/ETL apps.

    Returns:
        - status: "success" or "error"
        - collections_before: Number of collections before refresh
        - collections_after: Number of collections after refresh
        - new_collections: List of newly discovered collection IDs
        - refresh_time: ISO timestamp of refresh
    """
    if not settings.enable_tipg:
        return {
            "status": "error",
            "error": "TiPG is not enabled",
            "hint": "Set GEOTILER_ENABLE_TIPG=true to enable vector tile support",
        }

    # Import here to avoid circular imports
    from geotiler.routers.vector import (
        refresh_tipg_pool,
        get_tipg_startup_state_from_app,
    )

    app = request.app

    # Get current state before refresh
    state_before = get_tipg_startup_state_from_app(app)
    collections_before = []
    if state_before:
        collections_before = state_before.collection_ids.copy()

    logger.info("Webhook triggered: refreshing TiPG collection catalog...")

    try:
        # Perform the refresh
        await refresh_tipg_pool(app)

        # Get state after refresh
        state_after = get_tipg_startup_state_from_app(app)
        collections_after = []
        if state_after:
            collections_after = state_after.collection_ids.copy()

        # Calculate diff
        new_collections = [c for c in collections_after if c not in collections_before]
        removed_collections = [c for c in collections_before if c not in collections_after]

        logger.info(
            f"Catalog refresh complete: {len(collections_before)} -> {len(collections_after)} collections "
            f"(+{len(new_collections)}, -{len(removed_collections)})"
        )

        return {
            "status": "success",
            "collections_before": len(collections_before),
            "collections_after": len(collections_after),
            "new_collections": new_collections,
            "removed_collections": removed_collections,
            "refresh_time": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Catalog refresh failed: {e}")
        return JSONResponse(
            {
                "status": "error",
                "error": str(e),
                "refresh_time": datetime.now(timezone.utc).isoformat(),
            },
            status_code=500,
        )
