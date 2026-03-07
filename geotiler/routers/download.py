"""
Download router — thin routing layer for raster, vector, and asset downloads.

Validates parameters, enforces concurrency semaphore, dispatches to the
download service, and constructs streaming responses.

The /api prefix is in the AzureAuthMiddleware skip list, so download
endpoints acquire storage tokens explicitly from storage_token_cache.

Spec: Component 2 — Download Router
"""

import asyncio
import logging
import time
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Query, Request
from starlette.responses import StreamingResponse

from geotiler.errors import error_response, CAPACITY_EXCEEDED
from geotiler.services.download import (
    handle_asset_download,
    handle_raster_crop,
    handle_vector_subset,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/download", tags=["Download"])


async def _guarded_stream(
    stream: AsyncIterator[bytes],
    semaphore: asyncio.Semaphore,
    endpoint: str,
) -> AsyncIterator[bytes]:
    """
    Wrap a stream to hold the semaphore for the FULL duration of streaming,
    releasing only when iteration completes or the client disconnects.
    """
    t0 = time.monotonic()
    try:
        async for chunk in stream:
            yield chunk
    finally:
        semaphore.release()
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        logger.debug(
            "Stream completed, semaphore released",
            extra={
                "event": "stream_complete",
                "endpoint": endpoint,
                "stream_ms": elapsed,
            },
        )


@router.get("/raster/crop")
async def download_raster_crop(
    request: Request,
    asset_href: str = Query(..., description="Full URL or /vsiaz/ path to the raster asset (COG)"),
    bbox: str = Query(..., description="Bounding box: minx,miny,maxx,maxy (WGS84 degrees)"),
    format: str = Query("tif", description="Output format: tif or png"),
    filename: Optional[str] = Query(None, description="Custom filename for the download"),
) -> StreamingResponse:
    """
    Download a raster crop (bounding box subset) of a Cloud Optimized GeoTIFF.

    Delegates to TiTiler's /cog/bbox endpoint via in-process ASGI transport.

    Spec: Component 2 — /raster/crop endpoint
    Handles: R1 (bbox area limit enforced by download service)
    """
    t0 = time.monotonic()
    semaphore = _get_semaphore(request)
    acquired = False

    try:
        if not await _try_acquire_semaphore(semaphore):
            return error_response(
                "Download capacity exceeded",
                503,
                CAPACITY_EXCEEDED,
                retry_after_seconds=10,
            )
        acquired = True

        result = await handle_raster_crop(
            app=request.app,
            asset_href=asset_href,
            bbox=bbox,
            format=format,
            filename=filename,
        )

        elapsed = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "Raster crop download served",
            extra={
                "event": "download_complete",
                "endpoint": "raster/crop",
                "elapsed_ms": elapsed,
            },
        )

        guarded = _guarded_stream(result.stream, semaphore, endpoint="raster/crop")
        return StreamingResponse(
            guarded,
            media_type=result.content_type,
            headers=result.headers,
        )

    except Exception:
        if acquired:
            semaphore.release()
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "Download error",
            extra={
                "event": "download_error",
                "endpoint": "raster/crop",
                "elapsed_ms": elapsed,
            },
        )
        raise


@router.get("/vector/subset")
async def download_vector_subset(
    request: Request,
    collection_id: str = Query(..., description="TiPG collection ID (PostGIS table name)"),
    bbox: Optional[str] = Query(None, description="Bounding box filter: minx,miny,maxx,maxy (WGS84)"),
    format: str = Query("geojson", description="Output format: geojson or csv"),
    filename: Optional[str] = Query(None, description="Custom filename for the download"),
    limit: Optional[int] = Query(None, description="Maximum features to return", ge=1),
) -> StreamingResponse:
    """
    Download a spatial subset of a PostGIS vector collection.

    Queries via asyncpg and streams results as GeoJSON FeatureCollection or CSV.

    Spec: Component 2 — /vector/subset endpoint
    Handles: R3 (pool starvation — semaphore + statement_timeout)
    """
    t0 = time.monotonic()

    semaphore = _get_semaphore(request)
    acquired = False
    try:
        if not await _try_acquire_semaphore(semaphore):
            return error_response(
                "Download capacity exceeded",
                503,
                CAPACITY_EXCEEDED,
                retry_after_seconds=10,
            )
        acquired = True

        result = await handle_vector_subset(
            app=request.app,
            collection_id=collection_id,
            bbox=bbox,
            format=format,
            filename=filename,
            limit=limit,
        )

        elapsed = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "Vector subset download served",
            extra={
                "event": "download_complete",
                "endpoint": "vector/subset",
                "collection": collection_id,
                "elapsed_ms": elapsed,
            },
        )

        guarded = _guarded_stream(result.stream, semaphore, endpoint="vector/subset")
        return StreamingResponse(
            guarded,
            media_type=result.content_type,
            headers=result.headers,
        )

    except Exception:
        if acquired:
            semaphore.release()
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "Download error",
            extra={
                "event": "download_error",
                "endpoint": "vector/subset",
                "elapsed_ms": elapsed,
            },
        )
        raise


@router.get("/asset/full")
async def download_asset_full(
    request: Request,
    asset_href: str = Query(..., description="Full URL to the asset in Azure Blob Storage"),
    filename: Optional[str] = Query(None, description="Custom filename for the download"),
) -> StreamingResponse:
    """
    Download a full asset file via streaming proxy.

    Streams blob data through the server, avoiding direct browser-to-blob
    access (no SAS tokens exposed). Subject to proxy size limit.

    Spec: Component 2 — /asset/full endpoint
    Handles: T2 (proxy with size limit instead of SAS tokens)
    """
    t0 = time.monotonic()

    semaphore = _get_semaphore(request)
    acquired = False
    try:
        if not await _try_acquire_semaphore(semaphore):
            return error_response(
                "Download capacity exceeded",
                503,
                CAPACITY_EXCEEDED,
                retry_after_seconds=10,
            )
        acquired = True

        result = await handle_asset_download(
            app=request.app,
            asset_href=asset_href,
            filename=filename,
        )

        elapsed = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "Asset download served",
            extra={
                "event": "download_complete",
                "endpoint": "asset/full",
                "elapsed_ms": elapsed,
            },
        )

        guarded = _guarded_stream(result.stream, semaphore, endpoint="asset/full")
        return StreamingResponse(
            guarded,
            media_type=result.content_type,
            headers=result.headers,
        )

    except Exception:
        if acquired:
            semaphore.release()
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "Download error",
            extra={
                "event": "download_error",
                "endpoint": "asset/full",
                "elapsed_ms": elapsed,
            },
        )
        raise


_fallback_semaphore: asyncio.Semaphore | None = None


def _get_semaphore(request: Request) -> asyncio.Semaphore:
    """
    Get the download concurrency semaphore from app state.

    Spec: Component 2 — semaphore retrieval
    Handles: R3 (concurrency control per replica)
    """
    global _fallback_semaphore
    semaphore = getattr(request.app.state, "download_semaphore", None)
    if semaphore is None:
        # Fallback: reuse a single module-level semaphore if not initialized
        # (should not happen in production — lifespan initializes it)
        logger.warning(
            "Download semaphore not found on app.state, using fallback",
            extra={"event": "semaphore_fallback"},
        )
        if _fallback_semaphore is None:
            _fallback_semaphore = asyncio.Semaphore(100)
        return _fallback_semaphore
    return semaphore


async def _try_acquire_semaphore(semaphore: asyncio.Semaphore) -> bool:
    """
    Try to acquire the semaphore without blocking.

    Returns True if acquired, False if capacity is exhausted.

    Spec: Component 2 — non-blocking semaphore acquisition
    Handles: Operator concern — fail-fast when at capacity
    """
    # asyncio.Semaphore doesn't have a try_acquire, so we use a zero-timeout wait
    try:
        # Use wait_for with tiny timeout to simulate try_acquire
        await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
        return True
    except asyncio.TimeoutError:
        return False
