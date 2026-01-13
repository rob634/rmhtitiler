"""
Root endpoint with API information.
"""

from fastapi import APIRouter

from geotiler import __version__
from geotiler.config import settings

router = APIRouter(tags=["Info"])


@router.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "title": "TiTiler-pgSTAC with Azure OAuth Auth",
        "description": "STAC catalog tile server with OAuth token support",
        "version": __version__,
        "auth_type": "OAuth Bearer Token (Managed Identity)",
        "endpoints": {
            "liveness": "/livez",
            "readiness": "/readyz",
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc",
            "search_list": "/searches",
            "search_register": "/searches/register",
            "search_tiles": "/searches/{search_id}/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "search_info": "/searches/{search_id}/info",
            "search_tilejson": "/searches/{search_id}/{tileMatrixSetId}/tilejson.json",
        },
        "local_mode": settings.local_mode,
        "azure_auth": settings.use_azure_auth,
        "multi_container_support": True,
        "note": "OAuth token grants access to ALL containers based on RBAC role assignments",
    }
