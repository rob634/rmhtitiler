"""
H3 Crop Production & Drought Risk Explorer.

Interactive browser-based explorer using DuckDB-WASM to query
H3 Level 5 GeoParquet data directly from Azure Blob Storage.

No server-side compute required — DuckDB runs entirely in the browser
and reads only the columns needed via HTTP range requests (~3-5 MB
per query from the 160 MB parquet file).

Authentication: When Azure Storage OAuth is enabled, the server passes
its cached bearer token to the browser. DuckDB-WASM uses this token
via CREATE SECRET to authenticate HTTP range requests. A /h3/token
endpoint allows the browser to refresh the token before expiry.

Stack: DuckDB-WASM + deck.gl (PolygonLayer) + MapLibre + h3-js
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from geotiler.config import settings
from geotiler.auth.cache import storage_token_cache
from geotiler.auth.storage import get_storage_oauth_token
from geotiler.templates_utils import templates, get_template_context

router = APIRouter(tags=["H3 Explorer"])


def _get_storage_token() -> str | None:
    """Get storage bearer token, acquiring a fresh one if cache is empty."""
    if not settings.use_azure_auth:
        return None
    cached = storage_token_cache.get_if_valid(min_ttl_seconds=60)
    if cached:
        return cached
    # Cache miss — acquire a fresh token (also populates the cache)
    return get_storage_oauth_token()


@router.get("/h3", response_class=HTMLResponse, include_in_schema=False)
async def h3_explorer(request: Request):
    """
    H3 Crop Production & Drought Risk Explorer.

    Interactive bivariate choropleth showing production intensity
    crossed with SPEI-12 drought projections at H3 Level 5 resolution.

    Features:
    - 46 crops, 3 technology levels, 6 climate scenarios
    - Bivariate view (3x3 production x drought grid)
    - Risk segmented view (safe/drought zone color ramps)
    - DuckDB-WASM queries parquet via HTTP range requests (zero backend compute)
    """
    context = get_template_context(
        request,
        nav_active="/h3",
        h3_parquet_url=settings.h3_parquet_url,
        h3_storage_token=_get_storage_token() or "",
        h3_auth_enabled=settings.use_azure_auth,
    )
    return templates.TemplateResponse("pages/h3/explorer.html", context)


@router.get("/h3/token", include_in_schema=False)
async def h3_token(request: Request):
    """
    Return current storage bearer token for DuckDB-WASM.

    Called by the browser every 30 minutes to refresh the token
    before the ~60-minute Azure AD expiry.

    Minimal guard: rejects requests without a same-origin Referer header.
    This is NOT real security — just prevents casual direct access.
    Will be removed when server-side DuckDB replaces browser-WASM.
    """
    referer = request.headers.get("referer", "")
    if not referer or "/h3" not in referer:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    token = _get_storage_token()
    if not token:
        return JSONResponse({"token": None}, status_code=200)
    return JSONResponse({"token": token})
