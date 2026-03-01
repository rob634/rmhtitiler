"""
Download service — orchestrates download workflows.

Validates inputs, enforces limits, delegates to specialized clients
(TiTiler, VectorQuery, BlobStream), and constructs streaming responses.

Spec: Component 3 — Download Service
"""

import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional, TYPE_CHECKING

import httpx
from fastapi import HTTPException

from geotiler.auth.cache import storage_token_cache
from geotiler.config import get_settings
from geotiler.services.asset_resolver import AssetResolver
from geotiler.services.blob_stream import BlobStreamClient
from geotiler.services.download_clients import TiTilerClient
from geotiler.services.filename_gen import (
    build_content_disposition,
    generate_filename,
    sanitize_filename,
)
from geotiler.services.serializers import serialize_csv, serialize_geojson
from geotiler.services.vector_query import VectorQueryService

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def _wrap_stream_with_db_error_logging(
    stream: AsyncIterator[bytes],
    endpoint: str,
) -> AsyncIterator[bytes]:
    """Catch database errors during streaming iteration and log them.

    Async generators are lazy — exceptions raised during iteration are
    unreachable by the router's try/except. This wrapper ensures they
    are logged before re-raising.
    """
    import asyncpg as _asyncpg

    try:
        async for chunk in stream:
            yield chunk
    except (_asyncpg.PostgresError, _asyncpg.InterfaceError) as e:
        logger.error(
            f"Database error during stream: {type(e).__name__}: {e}",
            extra={
                "event": "stream_db_error",
                "endpoint": endpoint,
                "error_type": type(e).__name__,
            },
        )
        raise


# Supported output formats by endpoint
RASTER_FORMATS = {"tif", "png"}
VECTOR_FORMATS = {"geojson", "csv"}

# Minimum token TTL before triggering refresh concern
_MIN_TOKEN_TTL_SEC = 260


@dataclass(frozen=True)
class ParsedBbox:
    """
    Validated bounding box with area calculation.

    Spec: Component 3 — ParsedBbox dataclass
    """

    minx: float
    miny: float
    maxx: float
    maxy: float

    @property
    def area_degrees_sq(self) -> float:
        """
        Bounding box area in square degrees.

        Spec: Component 3 — ParsedBbox.area_degrees_sq
        """
        return abs(self.maxx - self.minx) * abs(self.maxy - self.miny)

    def validate(self) -> None:
        """
        Validate bounding box coordinate ranges.

        Raises:
            ValueError: If coordinates are out of WGS84 range or inverted.

        Spec: Component 3 — ParsedBbox.validate
        """
        if not (-180 <= self.minx <= 180 and -180 <= self.maxx <= 180):
            raise ValueError(
                f"Longitude out of range [-180, 180]: minx={self.minx}, maxx={self.maxx}"
            )
        if not (-90 <= self.miny <= 90 and -90 <= self.maxy <= 90):
            raise ValueError(
                f"Latitude out of range [-90, 90]: miny={self.miny}, maxy={self.maxy}"
            )
        if self.minx >= self.maxx:
            raise ValueError(
                f"minx ({self.minx}) must be less than maxx ({self.maxx})"
            )
        if self.miny >= self.maxy:
            raise ValueError(
                f"miny ({self.miny}) must be less than maxy ({self.maxy})"
            )

    def to_str(self) -> str:
        """
        Return comma-separated bbox string.

        Spec: Component 3 — ParsedBbox.to_str
        """
        return f"{self.minx},{self.miny},{self.maxx},{self.maxy}"


@dataclass(frozen=True)
class DownloadResult:
    """
    Result of a download operation, ready for StreamingResponse.

    Spec: Component 3 — DownloadResult dataclass
    """

    stream: AsyncIterator[bytes]
    content_type: str
    filename: str
    headers: dict


def parse_bbox(bbox_str: str) -> ParsedBbox:
    """
    Parse a comma-separated bbox string into a validated ParsedBbox.

    Args:
        bbox_str: Comma-separated string 'minx,miny,maxx,maxy'.

    Returns:
        Validated ParsedBbox instance.

    Raises:
        ValueError: If string cannot be parsed or coordinates are invalid.

    Spec: Component 3 — parse_bbox function
    """
    parts = [p.strip() for p in bbox_str.split(",")]
    if len(parts) != 4:
        raise ValueError(
            f"bbox must have 4 comma-separated values (minx,miny,maxx,maxy), "
            f"got {len(parts)}"
        )

    try:
        values = [float(p) for p in parts]
    except (ValueError, TypeError) as e:
        raise ValueError(f"bbox values must be numeric: {e}")

    bbox = ParsedBbox(minx=values[0], miny=values[1], maxx=values[2], maxy=values[3])
    bbox.validate()
    return bbox


def _get_storage_token() -> str:
    """
    Get a valid storage token, raising HTTPException if unavailable.

    Download endpoints skip AzureAuthMiddleware (via /api prefix),
    so they must acquire tokens explicitly from storage_token_cache.

    Spec: Component 3 — explicit token acquisition
    Handles: R2 (token freshness check before operations)
    """
    token = storage_token_cache.get_if_valid(min_ttl_seconds=_MIN_TOKEN_TTL_SEC)
    if not token:
        # Try with lower TTL — token may still be usable
        token = storage_token_cache.get_if_valid(min_ttl_seconds=30)
        if token:
            logger.warning(
                "Storage token TTL below threshold, download may fail mid-stream",
                extra={"event": "token_low_ttl"},
            )
        else:
            raise HTTPException(
                status_code=503,
                detail="Storage authentication unavailable — no valid token",
            )
    return token


def _build_asset_resolver(app: "FastAPI") -> AssetResolver:
    """
    Build an AssetResolver from app settings.

    Spec: Component 3 — asset resolver construction
    """
    s = get_settings()
    return AssetResolver(
        allowed_hosts=s.download_allowed_host_list,
        storage_account=s.storage_account,
    )


async def handle_raster_crop(
    app: "FastAPI",
    asset_href: str,
    bbox: str,
    format: str,
    filename: Optional[str],
) -> DownloadResult:
    """
    Handle raster crop download request.

    Validates inputs, delegates to TiTiler for crop, returns buffered result
    as a streaming response.

    Spec: Component 3 — handle_raster_crop
    Handles: R1 (TiTiler crop memory — bbox area limit)
    """
    s = get_settings()

    # Validate format
    if format not in RASTER_FORMATS:
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "Unsupported format",
                "status": 400,
                "supported": sorted(RASTER_FORMATS),
            },
        )

    # Parse and validate bbox
    try:
        parsed_bbox = parse_bbox(bbox)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"detail": str(e), "status": 400},
        )

    # Enforce area limit
    area = parsed_bbox.area_degrees_sq
    if area > s.download_raster_max_bbox_area_deg:
        raise HTTPException(
            status_code=400,
            detail={
                "detail": f"Bounding box area ({area:.2f} sq deg) exceeds limit ({s.download_raster_max_bbox_area_deg} sq deg)",
                "status": 400,
                "area_deg_sq": round(area, 2),
                "limit_deg_sq": s.download_raster_max_bbox_area_deg,
            },
        )

    # Validate asset href
    resolver = _build_asset_resolver(app)
    try:
        resolved = resolver.resolve(asset_href)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"detail": str(e), "status": 400},
        )

    # Build the asset URL that TiTiler will use (it needs the full https:// URL)
    asset_url = resolved.blob_url

    # Generate filename
    if filename:
        safe_name = sanitize_filename(filename)
    else:
        source_name = resolved.blob_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        safe_name = generate_filename(
            prefix="crop",
            source_name=source_name,
            bbox=parsed_bbox.to_str(),
            format_ext=format,
        )

    # Ensure extension matches format
    if not safe_name.endswith(f".{format}"):
        safe_name = f"{safe_name.rsplit('.', 1)[0]}.{format}" if "." in safe_name else f"{safe_name}.{format}"

    # Execute TiTiler crop via ASGI transport
    client = TiTilerClient(app=app, timeout_sec=s.download_timeout_sec)

    try:
        content_bytes, titiler_headers = await client.crop(
            asset_url=asset_url,
            bbox=parsed_bbox,
            format=format,
        )
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        body = e.response.text[:500]
        if 400 <= status < 500:
            raise HTTPException(
                status_code=422,
                detail={
                    "detail": f"Raster processing error: {body}",
                    "status": 422,
                },
            )
        else:
            raise HTTPException(
                status_code=502,
                detail={
                    "detail": f"Raster processing server error: {body}",
                    "status": 502,
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail={
                "detail": f"Raster crop timed out after {s.download_timeout_sec}s",
                "status": 504,
            },
        )

    # Determine content type
    content_type_map = {
        "tif": "image/tiff",
        "png": "image/png",
    }
    content_type = titiler_headers.get(
        "content-type", content_type_map.get(format, "application/octet-stream")
    )

    # Return buffered content as single-chunk async iterator
    async def _iter_bytes():
        yield content_bytes

    headers = {
        "Content-Disposition": build_content_disposition(safe_name),
        "Content-Length": str(len(content_bytes)),
    }

    logger.info(
        f"Raster crop complete: {len(content_bytes)} bytes, format={format}",
        extra={
            "event": "download_complete",
            "endpoint": "raster/crop",
            "format": format,
            "size_bytes": len(content_bytes),
            "bbox_area_deg": round(area, 2),
        },
    )

    return DownloadResult(
        stream=_iter_bytes(),
        content_type=content_type,
        filename=safe_name,
        headers=headers,
    )


async def handle_vector_subset(
    app: "FastAPI",
    collection_id: str,
    bbox: Optional[str],
    format: str,
    filename: Optional[str],
    limit: Optional[int],
) -> DownloadResult:
    """
    Handle vector subset download request.

    Validates inputs, queries PostGIS via VectorQueryService,
    serializes results to streaming GeoJSON or CSV.

    Spec: Component 3 — handle_vector_subset
    Handles: R3 (asyncpg pool starvation — semaphore + statement_timeout)
    """
    import asyncpg as _asyncpg

    s = get_settings()

    # Validate format
    if format not in VECTOR_FORMATS:
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "Unsupported format",
                "status": 400,
                "supported": sorted(VECTOR_FORMATS),
            },
        )

    # Parse bbox if provided
    parsed_bbox = None
    if bbox:
        try:
            parsed_bbox = parse_bbox(bbox)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={"detail": str(e), "status": 400},
            )

    # Get asyncpg pool and catalog from app state
    pool = getattr(app.state, "pool", None)
    catalog = getattr(app.state, "collection_catalog", None)

    if not pool:
        raise HTTPException(
            status_code=503,
            detail={"detail": "Database busy", "status": 503},
        )

    # Build query service
    query_service = VectorQueryService(pool=pool, catalog=catalog, settings=s)

    # Validate collection exists (RuntimeError = catalog not initialized = 503)
    try:
        if not query_service.collection_exists(collection_id):
            raise HTTPException(
                status_code=404,
                detail={"detail": "Collection not found", "status": 404},
            )
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail={"detail": "Vector catalog not available", "status": 503},
        )

    # Generate filename
    if filename:
        safe_name = sanitize_filename(filename)
    else:
        ext = "geojson" if format == "geojson" else "csv"
        safe_name = generate_filename(
            prefix="subset",
            source_name=collection_id,
            bbox=parsed_bbox.to_str() if parsed_bbox else None,
            format_ext=ext,
        )

    # Query features
    include_centroid = format == "csv"

    try:
        features = query_service.query_features(
            collection_id=collection_id,
            bbox=parsed_bbox,
            limit=limit,
            include_centroid=include_centroid,
        )

        # Serialize to streaming format
        if format == "geojson":
            stream = serialize_geojson(features)
            content_type = "application/geo+json"
        else:
            stream = serialize_csv(features)
            content_type = "text/csv"

        # Wrap stream to catch DB errors during lazy iteration
        stream = _wrap_stream_with_db_error_logging(stream, endpoint="vector/subset")

    except _asyncpg.InterfaceError:
        raise HTTPException(
            status_code=503,
            detail={"detail": "Database busy", "status": 503},
        )
    except _asyncpg.QueryCanceledError:
        raise HTTPException(
            status_code=504,
            detail={"detail": "Query timed out", "status": 504},
        )
    except _asyncpg.UndefinedTableError:
        raise HTTPException(
            status_code=404,
            detail={"detail": "Collection not found", "status": 404},
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"detail": str(e), "status": 400},
        )

    headers = {
        "Content-Disposition": build_content_disposition(safe_name),
    }

    logger.info(
        f"Vector subset started: collection={collection_id}, format={format}",
        extra={
            "event": "download_started",
            "endpoint": "vector/subset",
            "collection": collection_id,
            "format": format,
        },
    )

    return DownloadResult(
        stream=stream,
        content_type=content_type,
        filename=safe_name,
        headers=headers,
    )


async def handle_asset_download(
    app: "FastAPI",
    asset_href: str,
    filename: Optional[str],
) -> DownloadResult:
    """
    Handle full asset (blob) download via streaming proxy.

    Validates asset URL, checks size limits, streams blob data
    through the proxy with explicit token auth.

    Spec: Component 3 — handle_asset_download
    Handles: T2 (proxy with 500MB limit for P1)
    """
    from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

    s = get_settings()

    # Validate asset href
    resolver = _build_asset_resolver(app)
    try:
        resolved = resolver.resolve(asset_href)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"detail": str(e), "status": 400},
        )

    # Get storage token
    token = _get_storage_token()

    # Check blob properties (size, content type)
    blob_client = BlobStreamClient(settings=s)

    try:
        props = await blob_client.get_blob_properties(resolved.blob_url, token)
    except ResourceNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"detail": "Asset not found", "status": 404},
        )
    except HttpResponseError as e:
        status = getattr(e, "status_code", 500)
        if status == 403:
            raise HTTPException(
                status_code=502,
                detail={"detail": "Storage access denied", "status": 502},
            )
        elif status == 429:
            retry_after_raw = (getattr(e, "headers", None) or {}).get("Retry-After", "10")
            try:
                retry_after_sec = int(retry_after_raw)
            except (ValueError, TypeError):
                retry_after_sec = 10
            raise HTTPException(
                status_code=503,
                detail={
                    "detail": "Storage throttled",
                    "status": 503,
                    "retry_after_seconds": retry_after_sec,
                },
            )
        error_msg = getattr(e, "message", None) or str(e)
        raise HTTPException(
            status_code=502,
            detail={"detail": f"Storage error: {error_msg}", "status": 502},
        )

    # Check size limit
    size_mb = props["size_mb"]
    if size_mb > s.download_proxy_max_size_mb:
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "File exceeds download size limit",
                "status": 400,
                "size_mb": size_mb,
                "limit_mb": s.download_proxy_max_size_mb,
            },
        )

    # Generate filename
    if filename:
        safe_name = sanitize_filename(filename)
    else:
        # Use the blob filename
        blob_filename = resolved.blob_path.rsplit("/", 1)[-1]
        safe_name = sanitize_filename(blob_filename)

    # Stream blob data (pass etag for TOCTOU guard against blob replacement)
    stream = blob_client.stream_blob(resolved.blob_url, token, etag=props.get("etag"))

    content_type = props.get("content_type", resolved.content_type_hint)

    headers = {
        "Content-Disposition": build_content_disposition(safe_name),
        "Content-Length": str(props["size_bytes"]),
    }

    logger.info(
        f"Asset download started: {resolved.blob_path} ({size_mb:.1f} MB)",
        extra={
            "event": "download_started",
            "endpoint": "asset/full",
            "size_mb": size_mb,
            "blob_path": resolved.blob_path,
        },
    )

    return DownloadResult(
        stream=stream,
        content_type=content_type,
        filename=safe_name,
        headers=headers,
    )
