"""
H3 Crop Production & Drought Risk Explorer.

Serves the H3 explorer page and provides a server-side query endpoint
backed by DuckDB (when ENABLE_H3_DUCKDB=true).

When server-side DuckDB is active:
- /h3/query returns JSON data, browser only handles rendering
- No storage tokens are passed to the browser
- No CORS configuration needed on storage accounts

When server-side DuckDB is disabled (fallback):
- DuckDB-WASM runs in the browser, querying parquet directly
- Storage tokens are passed to the browser for auth
- /h3/token endpoint provides token refresh

Stack: deck.gl (PolygonLayer) + MapLibre + h3-js
"""

import time
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from geotiler.config import settings
from geotiler.auth.cache import storage_token_cache
from geotiler.auth.storage import get_storage_oauth_token
from geotiler.templates_utils import templates, get_template_context

logger = logging.getLogger(__name__)

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


def _is_duckdb_ready(request: Request) -> bool:
    """Check if server-side DuckDB is initialized and healthy."""
    state = getattr(request.app.state, "duckdb_state", None)
    return state is not None and state.init_success


@router.get("/h3", response_class=HTMLResponse, include_in_schema=False)
async def h3_explorer(request: Request):
    """
    H3 Crop Production & Drought Risk Explorer.

    Interactive bivariate choropleth showing production intensity
    crossed with SPEI-12 drought projections at H3 Level 5 resolution.
    """
    server_side = _is_duckdb_ready(request)

    # When server-side DuckDB is active, don't leak tokens to the browser
    if server_side:
        storage_token = ""
        auth_enabled = False
    else:
        storage_token = _get_storage_token() or ""
        auth_enabled = settings.use_azure_auth

    context = get_template_context(
        request,
        nav_active="/h3",
        h3_parquet_url=settings.h3_parquet_url,
        h3_storage_token=storage_token,
        h3_auth_enabled=auth_enabled,
        h3_server_side=server_side,
    )
    return templates.TemplateResponse("pages/h3/explorer.html", context)


@router.get("/h3/query", include_in_schema=False)
async def h3_query(
    request: Request,
    crop: str = Query(..., description="4-letter crop code"),
    tech: str = Query(..., description="Technology: a, i, or r"),
    scenario: str = Query(..., description="SPEI scenario column"),
):
    """
    Server-side H3 query endpoint.

    Returns production and drought data for the given crop/tech/scenario
    combination. Requires ENABLE_H3_DUCKDB=true.
    """
    if not _is_duckdb_ready(request):
        return JSONResponse(
            {"error": "H3 DuckDB not available"},
            status_code=503,
        )

    # Import here to avoid import error when duckdb is not installed
    from geotiler.services.duckdb import query_h3_data

    try:
        t0 = time.monotonic()
        data, from_cache = await query_h3_data(request.app, crop, tech, scenario)
        query_ms = round((time.monotonic() - t0) * 1000, 1)

        return JSONResponse({
            "data": data,
            "count": len(data),
            "query_ms": query_ms,
            "cached": from_cache,
        })

    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"H3 query error: {e}")
        return JSONResponse({"error": "Query failed"}, status_code=500)


@router.get("/h3/token", include_in_schema=False)
async def h3_token(request: Request):
    """
    Return current storage bearer token for DuckDB-WASM fallback.

    Only used when server-side DuckDB is disabled. Called by the browser
    every 30 minutes to refresh the token before expiry.

    Minimal guard: rejects requests without a same-origin Referer header.
    """
    referer = request.headers.get("referer", "")
    if not referer or "/h3" not in referer:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    token = _get_storage_token()
    if not token:
        return JSONResponse({"token": None}, status_code=200)
    return JSONResponse({"token": token})
