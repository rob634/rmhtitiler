# ============================================================================
# SERVICE LATENCY TRACKING
# ============================================================================
# STATUS: Infrastructure - Tile rendering and service call instrumentation
# PURPOSE: Track latency for tile endpoints and identify bottlenecks
# ============================================================================
"""
Service Layer Latency Tracking for geotiler.

Provides conditional instrumentation for tile rendering and service operations
to diagnose slow requests and identify whether delays are from network I/O
(fetching COG data) or CPU time (tile rendering).

Key Design:
-----------
- Zero overhead when OBSERVABILITY_MODE=false (early return, no timing)
- Full timing + structured logging when enabled
- Slow operation alerting (configurable threshold)
- Designed for Application Insights Kusto queries

Environment Variables:
----------------------
OBSERVABILITY_MODE: Enable latency tracking (default: false)
SLOW_REQUEST_THRESHOLD_MS: Threshold for slow warnings (default: 2000)

Usage:
------
```python
from geotiler.infrastructure.latency import track_latency, timed_section

@track_latency("cog.render_tile")
def render_tile(url: str, z: int, x: int, y: int):
    # ... tile rendering
    pass

# For timing sub-operations:
with timed_section("fetch_cog_data", {"url": url}):
    data = fetch_data(url)

with timed_section("encode_png"):
    result = encode_tile(data)
```

Application Insights Queries:
-----------------------------
```kusto
-- Find slow tile renders
traces
| where message contains "[TILE_LATENCY]"
| extend duration_ms = todouble(customDimensions.duration_ms)
| where duration_ms > 1000
| project timestamp, customDimensions.endpoint, duration_ms

-- P95 latency by endpoint
traces
| where message contains "[TILE_LATENCY]"
| extend endpoint = tostring(customDimensions.endpoint)
| extend duration_ms = todouble(customDimensions.duration_ms)
| summarize p95=percentile(duration_ms, 95) by endpoint
```

Exports:
    track_latency: Decorator for service operations
    timed_section: Context manager for code sections
    SLOW_THRESHOLD_MS: Current slow threshold value
"""

import logging
import os
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Slow operation threshold (milliseconds) - configurable via env var
SLOW_THRESHOLD_MS = int(os.environ.get("SLOW_REQUEST_THRESHOLD_MS", "2000"))


def _is_observability_enabled() -> bool:
    """
    Check if observability mode is enabled.

    Checks OBSERVABILITY_MODE env var. When false, all latency tracking
    has zero overhead (early return before any timing).

    Returns:
        bool: True if observability features should be active
    """
    val = os.environ.get("OBSERVABILITY_MODE", "").lower()
    return val in ("true", "1", "yes")


def track_latency(operation_name: str, include_args: bool = False):
    """
    Decorator to track latency for tile rendering and service operations.

    Zero overhead when OBSERVABILITY_MODE=false - the original function
    is called directly without any timing or logging.

    When enabled, logs structured JSON with:
    - operation: Operation name for filtering
    - duration_ms: Execution time in milliseconds
    - status: 'success' or 'error'
    - slow: True if duration > SLOW_REQUEST_THRESHOLD_MS

    Args:
        operation_name: Identifier for this operation (e.g., 'cog.render_tile')
        include_args: If True, include function arguments in log (be careful with URLs)

    Returns:
        Decorated function with conditional latency tracking

    Example:
        @track_latency("cog.tiles")
        def get_tile(z: int, x: int, y: int, url: str):
            ...

        @track_latency("pgstac.search", include_args=True)
        def search(collection_id: str, bbox=None):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Fast path: no overhead when disabled
            if not _is_observability_enabled():
                return func(*args, **kwargs)

            # Slow path: full timing when enabled
            start = time.perf_counter()
            status = "success"
            error_msg = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                is_slow = duration_ms > SLOW_THRESHOLD_MS

                # Build custom dimensions
                custom_dims = {
                    "operation": operation_name,
                    "duration_ms": round(duration_ms, 2),
                    "status": status,
                    "slow": is_slow,
                }

                # Optionally include args (useful for debugging but can be verbose)
                if include_args and kwargs:
                    # Filter out potentially large/sensitive values
                    safe_kwargs = {
                        k: v for k, v in kwargs.items()
                        if k in ("z", "x", "y", "collection_id", "search_id", "format")
                    }
                    custom_dims["args"] = safe_kwargs

                if error_msg:
                    custom_dims["error"] = error_msg[:200]

                extra = {"custom_dimensions": custom_dims}

                if is_slow:
                    logger.warning(
                        f"[TILE_LATENCY] SLOW {operation_name}: {duration_ms:.0f}ms",
                        extra=extra
                    )
                else:
                    logger.info(
                        f"[TILE_LATENCY] {operation_name}: {duration_ms:.0f}ms",
                        extra=extra
                    )

        return wrapper
    return decorator


def track_latency_async(operation_name: str, include_args: bool = False):
    """
    Async version of track_latency decorator.

    Same functionality but for async functions.

    Example:
        @track_latency_async("pgstac.search")
        async def search_items(collection_id: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Fast path: no overhead when disabled
            if not _is_observability_enabled():
                return await func(*args, **kwargs)

            # Slow path: full timing when enabled
            start = time.perf_counter()
            status = "success"
            error_msg = None

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                is_slow = duration_ms > SLOW_THRESHOLD_MS

                custom_dims = {
                    "operation": operation_name,
                    "duration_ms": round(duration_ms, 2),
                    "status": status,
                    "slow": is_slow,
                }

                if include_args and kwargs:
                    safe_kwargs = {
                        k: v for k, v in kwargs.items()
                        if k in ("z", "x", "y", "collection_id", "search_id", "format")
                    }
                    custom_dims["args"] = safe_kwargs

                if error_msg:
                    custom_dims["error"] = error_msg[:200]

                extra = {"custom_dimensions": custom_dims}

                if is_slow:
                    logger.warning(
                        f"[TILE_LATENCY] SLOW {operation_name}: {duration_ms:.0f}ms",
                        extra=extra
                    )
                else:
                    logger.info(
                        f"[TILE_LATENCY] {operation_name}: {duration_ms:.0f}ms",
                        extra=extra
                    )

        return wrapper
    return decorator


@contextmanager
def timed_section(section_name: str, context: Optional[Dict[str, Any]] = None):
    """
    Context manager for timing arbitrary code sections.

    Useful for breaking down a large operation into sub-timings to identify
    which specific part is slow (e.g., network fetch vs CPU rendering).

    Args:
        section_name: Identifier for this section
        context: Optional dict of additional context to log

    Yields:
        None - use as context manager

    Example:
        # Break down tile rendering into phases:
        with timed_section("fetch_cog_overview", {"url": url, "z": z}):
            data = fetch_overview(url, z)

        with timed_section("resample_tile"):
            tile_data = resample(data, x, y)

        with timed_section("encode_png"):
            result = encode(tile_data, "png")
    """
    if not _is_observability_enabled():
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        is_slow = duration_ms > SLOW_THRESHOLD_MS

        custom_dims = {
            "section": section_name,
            "duration_ms": round(duration_ms, 2),
            "slow": is_slow,
        }

        if context:
            # Merge context but don't overwrite core fields
            for k, v in context.items():
                if k not in custom_dims:
                    custom_dims[k] = v

        extra = {"custom_dimensions": custom_dims}

        if is_slow:
            logger.warning(
                f"[SECTION_LATENCY] SLOW {section_name}: {duration_ms:.0f}ms",
                extra=extra
            )
        else:
            logger.debug(
                f"[SECTION_LATENCY] {section_name}: {duration_ms:.0f}ms",
                extra=extra
            )


# Export
__all__ = [
    "track_latency",
    "track_latency_async",
    "timed_section",
    "SLOW_THRESHOLD_MS",
]
