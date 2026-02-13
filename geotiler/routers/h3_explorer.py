"""
H3 Crop Production & Drought Risk Explorer.

Serves the H3 explorer page and provides a server-side query endpoint
backed by DuckDB (ENABLE_H3_DUCKDB=true required).

- /h3/query returns JSON data, browser only handles rendering
- No storage tokens are passed to the browser
- No CORS configuration needed on storage accounts

Stack: deck.gl (PolygonLayer) + MapLibre + h3-js
"""

import time
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from geotiler.templates_utils import templates, get_template_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["H3 Explorer"])


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

    context = get_template_context(
        request,
        h3_server_side=server_side,
    )
    return templates.TemplateResponse("pages/h3/explorer.html", context)


@router.get("/h3/menaap", response_class=HTMLResponse, include_in_schema=False)
async def h3_menaap(request: Request):
    """
    MENAAP-focused bivariate H3 explorer.

    Continuous SPEI × production bivariate choropleth,
    centered on Middle East, North Africa, Afghanistan & Pakistan.
    """
    server_side = _is_duckdb_ready(request)
    context = get_template_context(request, h3_server_side=server_side)
    return templates.TemplateResponse("pages/h3/menaap.html", context)


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
