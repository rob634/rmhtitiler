# ============================================================================
# PLATFORM ERROR RESPONSE UTILITIES
# ============================================================================
# STATUS: Infrastructure - Standardized error responses for custom endpoints
# PURPOSE: Single error shape across all non-upstream TiTiler endpoints
# CREATED: 06 MAR 2026
# ============================================================================
"""
Standardized error response utilities for geotiler custom endpoints.

All custom endpoints (downloads, H3 explorer, admin, diagnostics) should use
``error_response()`` to return errors in a consistent shape::

    {"error": "Human-readable message", "status": 503, "error_code": "CAPACITY_EXCEEDED"}

TiTiler upstream endpoints (tiles, STAC search, pgSTAC) are left unchanged —
clients expect their native FastAPI/TiTiler error shapes.
"""

from fastapi.responses import JSONResponse

# ============================================================================
# ERROR CODE CONSTANTS
# ============================================================================

CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
NOT_FOUND = "NOT_FOUND"
BAD_REQUEST = "BAD_REQUEST"
TIMEOUT = "TIMEOUT"
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
UPSTREAM_ERROR = "UPSTREAM_ERROR"
AUTH_UNAVAILABLE = "AUTH_UNAVAILABLE"
QUERY_FAILED = "QUERY_FAILED"
TIPG_DISABLED = "TIPG_DISABLED"
POOL_NOT_INITIALIZED = "POOL_NOT_INITIALIZED"


# ============================================================================
# ERROR RESPONSE BUILDER
# ============================================================================

def error_response(
    message: str,
    status_code: int,
    error_code: str = None,
    **context,
) -> JSONResponse:
    """
    Build a standardized error JSONResponse.

    Args:
        message: Human-readable error description.
        status_code: HTTP status code (e.g. 400, 404, 500, 503).
        error_code: Machine-readable error code constant (e.g. CAPACITY_EXCEEDED).
        **context: Additional key-value pairs merged into the response body
                   (e.g. retry_after_seconds=10, hint="...").

    Returns:
        JSONResponse with body ``{"error": ..., "status": ..., ...}``.
    """
    body = {"error": message, "status": status_code}
    if error_code:
        body["error_code"] = error_code
    if context:
        body.update(context)
    return JSONResponse(body, status_code=status_code)
