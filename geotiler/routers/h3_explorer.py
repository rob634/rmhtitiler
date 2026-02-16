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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from geotiler.templates_utils import templates, get_template_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["H3 Explorer"])

# Region definitions for parameterized H3 views
REGIONS = {
    "global": {
        "name": "Global",
        "title": "Crop Production & Drought Risk",
        "center": [20, 15],
        "zoom": 2.5,
        "country_codes": [],
        "exclude_codes": [],
    },
    "menaap": {
        "name": "MENAAP",
        "title": "MENAAP — Crop Production & Drought Risk",
        "center": [30, 27],
        "zoom": 3.5,
        "country_codes": [
            "004", "012", "262", "818", "364", "368", "400",
            "422", "434", "504", "586", "682", "760", "788", "275", "887",
        ],
        "exclude_codes": ["732"],  # Western Sahara
    },
    "sar": {
        "name": "SAR",
        "title": "SAR — Crop Production & Drought Risk",
        "center": [80, 23],
        "zoom": 4,
        "country_codes": ["356", "144", "524", "064", "050"],
        "exclude_codes": [],
    },
    "lac": {
        "name": "LAC",
        "title": "LAC — Crop Production & Drought Risk",
        "center": [-72, 2],
        "zoom": 3,
        "country_codes": [
            "032", "068", "076", "170", "152", "188", "214", "218",  # AR BO BR CO CL CR DO EC
            "222", "320", "332", "340", "388", "484", "558", "591",  # SV GT HT HN JM MX NI PA
            "600", "604", "534", "740", "858", "862", "780", "308",  # PY PE SX SR UY VE TT GD
            "662", "052", "670", "212", "028", "192", "084",         # LC BB VC DM AG CU BZ
        ],
        "exclude_codes": [],
    },
}


def _is_duckdb_ready(request: Request) -> bool:
    """Check if server-side DuckDB is initialized and healthy."""
    state = getattr(request.app.state, "duckdb_state", None)
    return state is not None and state.init_success


@router.get("/h3", response_class=HTMLResponse, include_in_schema=False)
async def h3_explorer(request: Request):
    """
    H3 Crop Production & Drought Risk Explorer (global view).

    Interactive choropleth showing production intensity crossed with
    SPEI-12 drought projections at H3 Level 5 resolution.
    Uses the region template with no country filter (shows all data).
    """
    region = REGIONS["global"]
    server_side = _is_duckdb_ready(request)
    context = get_template_context(request, h3_server_side=server_side, **region)
    return templates.TemplateResponse("pages/h3/region.html", context)


@router.get("/h3/menaap", response_class=HTMLResponse, include_in_schema=False)
async def h3_menaap_redirect(request: Request):
    """Redirect legacy /h3/menaap to /h3/region/menaap."""
    return RedirectResponse(url="/h3/region/menaap", status_code=302)


@router.get("/h3/region/{region_id}", response_class=HTMLResponse, include_in_schema=False)
async def h3_region(request: Request, region_id: str):
    """
    Parameterized regional H3 explorer.

    Renders the bivariate/trivariate choropleth filtered to the
    specified region's country set.
    """
    region = REGIONS.get(region_id)
    if not region:
        return JSONResponse({"error": f"Unknown region: {region_id}"}, status_code=404)

    server_side = _is_duckdb_ready(request)
    context = get_template_context(request, h3_server_side=server_side, **region)
    return templates.TemplateResponse("pages/h3/region.html", context)


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
