# ============================================================================
# REQUEST TIMING MIDDLEWARE (pure ASGI)
# ============================================================================
# STATUS: Infrastructure - HTTP request instrumentation
# PURPOSE: Track request latency, status, and response size for all endpoints
# ============================================================================
"""
Request Timing Middleware for geotiler.

Pure ASGI middleware — avoids Starlette's BaseHTTPMiddleware which swallows
exceptions from downstream handlers (encode/starlette#1012).

Captures metrics for every HTTP request:
- Total request duration
- HTTP status code
- Response size (bytes)
- Endpoint path (with tile coordinates extracted)
- Slow request flagging

Environment Variables:
----------------------
GEOTILER_ENABLE_OBSERVABILITY: Enable request timing (default: false)
GEOTILER_OBS_SLOW_THRESHOLD_MS: Threshold for slow warnings (default: 2000)

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
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Slow threshold from env var
SLOW_THRESHOLD_MS = int(os.environ.get("GEOTILER_OBS_SLOW_THRESHOLD_MS", "2000"))

# Regex to extract tile coordinates from paths like /cog/tiles/10/512/384.png
TILE_PATH_PATTERN = re.compile(
    r"/(cog|xarray|searches/[^/]+|vector|pc)/.*?/(\d+)/(\d+)/(\d+)"
)


def _is_observability_enabled() -> bool:
    """Check if observability mode is enabled."""
    val = os.environ.get("GEOTILER_ENABLE_OBSERVABILITY", "").lower()
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


class RequestTimingMiddleware:
    """
    Pure ASGI middleware to track request timing and metrics.

    Captures for every request:
    - duration_ms: Total request processing time
    - status_code: HTTP response status
    - response_bytes: Response body size
    - endpoint: Normalized path (tiles aggregated)
    - method: HTTP method
    - slow: True if duration > threshold

    Logs are tagged with [REQUEST] prefix for easy filtering in App Insights.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: skip timing if observability disabled
        if not _is_observability_enabled():
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        # Skip timing for health probes (too noisy)
        if path in ("/livez", "/readyz", "/health"):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "?")
        query_string = scope.get("query_string", b"").decode("latin-1")
        query_params = parse_qs(query_string)

        start = time.perf_counter()
        status_code = 500
        response_bytes = 0

        async def send_wrapper(message):
            nonlocal status_code, response_bytes

            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                for name, value in message.get("headers", []):
                    if name == b"content-length":
                        response_bytes = int(value)
                        break

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            logger.exception(f"Request failed: {e}")
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            is_slow = duration_ms > SLOW_THRESHOLD_MS

            endpoint = _normalize_endpoint(path)
            custom_dims = {
                "endpoint": endpoint,
                "method": method,
                "duration_ms": round(duration_ms, 2),
                "status_code": status_code,
                "response_bytes": response_bytes,
                "slow": is_slow,
            }

            tile_info = _extract_tile_info(path)
            if tile_info:
                custom_dims.update(tile_info)

            url_values = query_params.get("url")
            if url_values:
                url = url_values[0]
                custom_dims["source_url"] = url[:200] if len(url) > 200 else url

            format_values = query_params.get("format")
            if format_values:
                custom_dims["format"] = format_values[0]

            extra = {"custom_dimensions": custom_dims}

            if status_code >= 500:
                logger.error(
                    f"[REQUEST] {method} {endpoint} -> {status_code} ({duration_ms:.0f}ms)",
                    extra=extra
                )
            elif is_slow:
                logger.warning(
                    f"[REQUEST] SLOW {method} {endpoint} -> {status_code} ({duration_ms:.0f}ms)",
                    extra=extra
                )
            elif status_code >= 400:
                logger.warning(
                    f"[REQUEST] {method} {endpoint} -> {status_code} ({duration_ms:.0f}ms)",
                    extra=extra
                )
            else:
                logger.info(
                    f"[REQUEST] {method} {endpoint} -> {status_code} ({duration_ms:.0f}ms)",
                    extra=extra
                )


# Export
__all__ = ["RequestTimingMiddleware", "SLOW_THRESHOLD_MS"]
