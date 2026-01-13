# ============================================================================
# REQUEST TIMING MIDDLEWARE
# ============================================================================
# STATUS: Infrastructure - HTTP request instrumentation
# PURPOSE: Track request latency, status, and response size for all endpoints
# ============================================================================
"""
Request Timing Middleware for geotiler.

Captures metrics for every HTTP request:
- Total request duration
- HTTP status code
- Response size (bytes)
- Endpoint path (with tile coordinates extracted)
- Slow request flagging

This middleware provides the foundation for understanding overall API
performance. For deeper insights into specific operations, use the
@track_latency decorator on internal functions.

Environment Variables:
----------------------
OBSERVABILITY_MODE: Enable request timing (default: false)
SLOW_REQUEST_THRESHOLD_MS: Threshold for slow warnings (default: 2000)

Application Insights Queries:
-----------------------------
```kusto
-- Request latency by endpoint
traces
| where message contains "[REQUEST]"
| extend endpoint = tostring(customDimensions.endpoint)
| extend duration_ms = todouble(customDimensions.duration_ms)
| summarize
    avg_ms = avg(duration_ms),
    p95_ms = percentile(duration_ms, 95),
    count = count()
  by endpoint
| order by p95_ms desc

-- Slow requests with details
traces
| where message contains "[REQUEST]"
| extend duration_ms = todouble(customDimensions.duration_ms)
| where duration_ms > 2000
| project
    timestamp,
    customDimensions.endpoint,
    duration_ms,
    customDimensions.status_code,
    customDimensions.response_bytes

-- Error rate by endpoint
traces
| where message contains "[REQUEST]"
| extend endpoint = tostring(customDimensions.endpoint)
| extend is_error = toint(customDimensions.status_code) >= 400
| summarize
    total = count(),
    errors = countif(is_error),
    error_rate = round(100.0 * countif(is_error) / count(), 2)
  by endpoint
| where errors > 0
```
"""

import logging
import os
import re
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Slow threshold from env var
SLOW_THRESHOLD_MS = int(os.environ.get("SLOW_REQUEST_THRESHOLD_MS", "2000"))

# Regex to extract tile coordinates from paths like /cog/tiles/10/512/384.png
TILE_PATH_PATTERN = re.compile(
    r"/(cog|xarray|searches/[^/]+|vector|pc)/.*?/(\d+)/(\d+)/(\d+)"
)


def _is_observability_enabled() -> bool:
    """Check if observability mode is enabled."""
    val = os.environ.get("OBSERVABILITY_MODE", "").lower()
    return val in ("true", "1", "yes")


def _normalize_endpoint(path: str) -> str:
    """
    Normalize endpoint path for aggregation.

    Replaces tile coordinates and UUIDs with placeholders so metrics
    can be aggregated by endpoint pattern rather than individual tiles.

    Examples:
        /cog/tiles/10/512/384.png -> /cog/tiles/{z}/{x}/{y}
        /searches/abc123-def456/tiles/8/128/64 -> /searches/{search_id}/tiles/{z}/{x}/{y}
    """
    # Replace tile coordinates
    path = re.sub(r"/(\d+)/(\d+)/(\d+)(\.\w+)?$", r"/{z}/{x}/{y}", path)

    # Replace UUIDs in searches path
    path = re.sub(
        r"/searches/[a-f0-9-]+/",
        "/searches/{search_id}/",
        path
    )

    return path


def _extract_tile_info(path: str) -> dict:
    """
    Extract tile coordinates from path if present.

    Returns:
        dict with z, x, y if path contains tile coordinates, empty dict otherwise
    """
    match = TILE_PATH_PATTERN.search(path)
    if match:
        return {
            "z": int(match.group(2)),
            "x": int(match.group(3)),
            "y": int(match.group(4)),
        }
    return {}


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track request timing and metrics.

    Captures for every request:
    - duration_ms: Total request processing time
    - status_code: HTTP response status
    - response_bytes: Response body size
    - endpoint: Normalized path (tiles aggregated)
    - method: HTTP method
    - slow: True if duration > threshold

    For tile endpoints, also captures:
    - z, x, y: Tile coordinates

    Logs are tagged with [REQUEST] prefix for easy filtering in App Insights.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and log timing metrics."""

        # Fast path: skip timing if observability disabled
        # Still process the request, just don't log metrics
        if not _is_observability_enabled():
            return await call_next(request)

        # Skip timing for health probes (too noisy)
        path = request.url.path
        if path in ("/livez", "/readyz", "/health"):
            return await call_next(request)

        start = time.perf_counter()
        response_bytes = 0
        status_code = 500  # Default in case of unhandled exception

        try:
            response = await call_next(request)
            status_code = response.status_code

            # Get response size if available
            content_length = response.headers.get("content-length")
            if content_length:
                response_bytes = int(content_length)

            return response

        except Exception as e:
            # Log exception but let it propagate
            logger.exception(f"Request failed: {e}")
            raise

        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            is_slow = duration_ms > SLOW_THRESHOLD_MS

            # Build custom dimensions
            endpoint = _normalize_endpoint(path)
            custom_dims = {
                "endpoint": endpoint,
                "method": request.method,
                "duration_ms": round(duration_ms, 2),
                "status_code": status_code,
                "response_bytes": response_bytes,
                "slow": is_slow,
            }

            # Add tile coordinates if present
            tile_info = _extract_tile_info(path)
            if tile_info:
                custom_dims.update(tile_info)

            # Add query params that might be useful (URL, format)
            if "url" in request.query_params:
                # Truncate URL to avoid huge log entries
                url = request.query_params["url"]
                custom_dims["source_url"] = url[:200] if len(url) > 200 else url

            if "format" in request.query_params:
                custom_dims["format"] = request.query_params["format"]

            extra = {"custom_dimensions": custom_dims}

            # Log with appropriate level
            if status_code >= 500:
                logger.error(
                    f"[REQUEST] {request.method} {endpoint} -> {status_code} ({duration_ms:.0f}ms)",
                    extra=extra
                )
            elif is_slow:
                logger.warning(
                    f"[REQUEST] SLOW {request.method} {endpoint} -> {status_code} ({duration_ms:.0f}ms)",
                    extra=extra
                )
            elif status_code >= 400:
                logger.warning(
                    f"[REQUEST] {request.method} {endpoint} -> {status_code} ({duration_ms:.0f}ms)",
                    extra=extra
                )
            else:
                logger.info(
                    f"[REQUEST] {request.method} {endpoint} -> {status_code} ({duration_ms:.0f}ms)",
                    extra=extra
                )


# Export
__all__ = ["RequestTimingMiddleware", "SLOW_THRESHOLD_MS"]
