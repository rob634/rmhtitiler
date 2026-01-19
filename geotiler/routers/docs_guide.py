"""
Documentation Guide Pages.

Serves narrative documentation for TiTiler/TiPG APIs.
Complements the auto-generated /docs (Swagger) and /redoc endpoints.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from geotiler.templates_utils import templates, get_template_context

router = APIRouter(tags=["Documentation"])


def _render_guide(request: Request, template_name: str, guide_active: str):
    """Render a guide page with standard context."""
    context = get_template_context(
        request,
        guide_active=guide_active,
        nav_active="/guide/"
    )
    return templates.TemplateResponse(template_name, context)


# =============================================================================
# GUIDE INDEX
# =============================================================================

@router.get("/guide/", response_class=HTMLResponse, include_in_schema=False)
async def guide_index(request: Request):
    """Documentation landing page."""
    return _render_guide(request, "pages/guide/index.html", "/guide/")


# =============================================================================
# GETTING STARTED
# =============================================================================

@router.get("/guide/authentication", response_class=HTMLResponse, include_in_schema=False)
async def guide_authentication(request: Request):
    """Authentication guide."""
    return _render_guide(request, "pages/guide/authentication.html", "/guide/authentication")


@router.get("/guide/quick-start", response_class=HTMLResponse, include_in_schema=False)
async def guide_quick_start(request: Request):
    """Quick start guide."""
    return _render_guide(request, "pages/guide/quick-start.html", "/guide/quick-start")


# =============================================================================
# DATA SCIENTISTS
# =============================================================================

@router.get("/guide/data-scientists/", response_class=HTMLResponse, include_in_schema=False)
async def guide_data_scientists(request: Request):
    """Data scientists overview."""
    return _render_guide(request, "pages/guide/data-scientists/index.html", "/guide/data-scientists/")


@router.get("/guide/data-scientists/point-queries", response_class=HTMLResponse, include_in_schema=False)
async def guide_point_queries(request: Request):
    """Point queries guide."""
    return _render_guide(request, "pages/guide/data-scientists/point-queries.html", "/guide/data-scientists/point-queries")


@router.get("/guide/data-scientists/batch-queries", response_class=HTMLResponse, include_in_schema=False)
async def guide_batch_queries(request: Request):
    """Batch queries guide."""
    return _render_guide(request, "pages/guide/data-scientists/batch-queries.html", "/guide/data-scientists/batch-queries")


@router.get("/guide/data-scientists/stac-search", response_class=HTMLResponse, include_in_schema=False)
async def guide_stac_search(request: Request):
    """STAC search guide."""
    return _render_guide(request, "pages/guide/data-scientists/stac-search.html", "/guide/data-scientists/stac-search")


# =============================================================================
# WEB DEVELOPERS
# =============================================================================

@router.get("/guide/web-developers/", response_class=HTMLResponse, include_in_schema=False)
async def guide_web_developers(request: Request):
    """Web developers overview."""
    return _render_guide(request, "pages/guide/web-developers/index.html", "/guide/web-developers/")


@router.get("/guide/web-developers/maplibre-tiles", response_class=HTMLResponse, include_in_schema=False)
async def guide_maplibre_tiles(request: Request):
    """MapLibre tiles guide."""
    return _render_guide(request, "pages/guide/web-developers/maplibre-tiles.html", "/guide/web-developers/maplibre-tiles")


@router.get("/guide/web-developers/vector-features", response_class=HTMLResponse, include_in_schema=False)
async def guide_vector_features(request: Request):
    """Vector features guide."""
    return _render_guide(request, "pages/guide/web-developers/vector-features.html", "/guide/web-developers/vector-features")
