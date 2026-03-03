Now I have a comprehensive understanding of the codebase. Let me produce the full mediation analysis.

---

# AGENT M -- MEDIATION REPORT: Download Initiator

## CONFLICTS FOUND

### A's Design vs O's Infrastructure Constraints

**CONFLICT 1: TiTiler HTTP loopback blocking the single worker**

A proposed: `TiTilerClient` makes HTTP calls to `http://localhost:8000/cog/bbox/...` via httpx.AsyncClient, treating TiTiler as an HTTP service.

O's constraint: The Dockerfile runs `uvicorn ... --workers 1`. A single-worker process cannot serve an incoming request while simultaneously dispatching an internal HTTP request to itself -- the loopback call would deadlock because the one worker is already occupied handling the download request.

Resolution: The TiTiler crop endpoint (`/cog/bbox/{minx},{miny},{maxx},{maxy}.{format}`) is mounted in-process as a FastAPI router. Rather than HTTP loopback, invoke the TiTiler `TilerFactory` endpoint function directly via ASGI test client or by calling the underlying `titiler.core` Python API. Specifically, use `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))` to make an "internal" ASGI call that does not go through the network stack but runs within the same process. This preserves the HTTP delegation pattern semantically (the download service still constructs an HTTP request and receives an HTTP response), avoids deadlock on the single worker, and does not require importing TiTiler internals directly. The ASGI transport approach was designed for exactly this scenario.

Tradeoff: This is slightly more complex than a plain `httpx.get()`, but avoids the fundamental deadlock and preserves the HTTP contract boundary for future extraction of TiTiler to a separate service.

**CONFLICT 2: Full asset proxy streaming through a 1-4 GB container**

A proposed: `BlobStreamClient.stream_blob()` proxies complete blob assets through the container, streaming chunks via AsyncIterator.

O's constraint: Container memory is 1-4 GB, shared with GDAL, DuckDB, and connection pools. Proxying multi-GB files (COGs can be hundreds of MB to several GB) risks OOMKill. O recommends max 5 concurrent downloads per replica.

Resolution: Enforce a configurable maximum file size for proxied downloads (`GEOTILER_DOWNLOAD_PROXY_MAX_SIZE_MB`, default 500 MB). Before streaming, issue a HEAD request / `get_blob_properties()` to check `content_length`. If the blob exceeds the limit, return 400 with an actionable error: `{"detail": "File exceeds maximum download size of 500 MB", "status": 400, "blob_size_mb": <actual>, "limit_mb": 500}`. Additionally, implement a per-replica `asyncio.Semaphore` (configurable, default 3) to bound concurrent download streams across all three endpoints. The PRIVATE DESIGN CONSTRAINT notes that User Delegation SAS tokens can be reconsidered if proxy proves untenable -- record this as a DEFERRED DECISION for P2.

Tradeoff: Users cannot download files larger than the configured limit via proxy. This is acceptable for P1; the SAS fallback path provides an escape hatch for P2.

**CONFLICT 3: 240-second hard timeout vs long-running streams**

A proposed: 240-second request timeout as a hard bound, with no differentiation by endpoint.

O's constraint: The 240-second timeout is a platform-level hard kill with no signal. Internal timeouts must be set lower (O recommends internal timeout < 240s) to allow structured error responses before the platform kills the connection.

Resolution: Set internal timeouts at 200 seconds (matching A's `geotiler_download_titiler_timeout_sec` default). For the TiTiler ASGI call, use httpx timeout of 200s. For vector queries, use asyncpg statement_timeout of 180s. For blob streaming, track elapsed time and abort with a structured error if approaching 200s. The 40-second buffer between internal timeout (200s) and platform kill (240s) allows error response construction and logging.

Tradeoff: Some legitimate long-running operations may be terminated at 200s instead of running to 240s. This is acceptable because receiving a structured error is better than receiving a connection reset.

### C's Edge Cases Affecting A's Design

**CONFLICT 4: Token expiry during long-running stream (C's E1)**

C found: OAuth tokens expire every 60 minutes, refreshed at 45 minutes. A download stream that begins when a token has 16 minutes of TTL remaining could exhaust the token before stream completes, especially for large blob downloads or slow vector queries. Once streaming begins (200 OK sent), a mid-stream auth failure produces a partial file.

How it affects A: A's streaming architecture sends headers before the body is complete. If the underlying Azure SDK call fails mid-stream due to token expiry, the client receives a truncated file with no error indication.

Resolution: Before initiating any stream, check token TTL via `storage_token_cache.ttl_seconds()` (for raster/blob) or `postgres_token_cache.ttl_seconds()` (for vector). If TTL is less than the internal timeout (200s) plus a buffer (60s = 260s total), proactively trigger a token refresh before starting the operation. For blob streaming specifically, the `azure-storage-blob` SDK's `download_blob()` uses the token at call time and handles range requests internally. For vector queries, the asyncpg connection uses the token embedded in the connection string -- but the existing pool refresh cycle already handles this. Document that very large downloads (approaching 200s duration) crossing a token boundary remain a residual risk.

Tradeoff: Adds a token freshness check (~1ms) before each download. Occasional proactive refresh may add latency (2-5s for Azure SDK call). This is justified because partial files are worse than a brief delay.

**CONFLICT 5: X-Byte-Count header impossible on streaming response (C's G5)**

C found: The spec requires `X-Byte-Count` in response headers. But response headers are sent before the body streams. The byte count is unknown until streaming completes.

How it affects A: A's `DownloadResult` includes `headers: dict[str, str]` which would be sent before streaming begins. `X-Byte-Count` cannot be populated.

Resolution: For raster crops, the TiTiler response (even via ASGI transport) may return a `content-length` header if TiTiler buffers the crop result (C's E2 notes this is likely). If present, forward it as `X-Byte-Count`. For vector subsets, omit `X-Byte-Count` from response headers; instead, provide `X-Feature-Count` (known from the COUNT query that runs before streaming) and `X-Truncated` (known from limit comparison). For full asset downloads, use `get_blob_properties().size` to populate `X-Byte-Count` before streaming begins (the blob size is known). Add `X-Byte-Count: unknown` as the default when size cannot be determined pre-stream. This is honest and actionable.

Tradeoff: Vector subset responses will not have byte counts in headers. This is acceptable; feature count is more meaningful for vector data.

**CONFLICT 6: GeoJSON streaming requires custom framing (C's U7)**

C found: Valid GeoJSON requires wrapping features in a FeatureCollection with `{"type": "FeatureCollection", "features": [...]}`. This requires knowing the array boundaries before and after the feature stream.

How it affects A: A's `serialize_geojson` takes an AsyncIterator of feature dicts and must produce valid GeoJSON. Naive streaming would either buffer all features (violating the streaming invariant) or produce invalid JSON.

Resolution: Use a framing approach: emit the opening `{"type": "FeatureCollection", "features": [` as the first chunk, then emit each feature dict as a JSON-encoded line with comma separators (first feature has no leading comma, subsequent features have a leading comma), then emit the closing `]}` as the final chunk. This produces valid GeoJSON without buffering. The serializer tracks whether it has emitted the first feature to handle comma placement. This is the standard approach used by OGC API Features implementations.

Tradeoff: Each feature is individually serialized to JSON, adding CPU overhead proportional to feature count. For 100K features this is negligible compared to the database query time.

**CONFLICT 7: asset_href SSRF vector (C's G3)**

C found: The `asset_href` parameter is user-supplied. Without validation, an attacker could pass `http://169.254.169.254/metadata/identity/oauth2/token` to exfiltrate IMDS tokens, or internal service URLs.

How it affects A: A's `AssetResolver.resolve()` does not specify validation rules beyond "STAC asset href resolution."

Resolution: The `AssetResolver` must enforce an allowlist of URL schemes and host patterns. Specifically: (1) Only `https://` scheme is accepted. (2) The hostname must match a configurable allowlist pattern (`GEOTILER_DOWNLOAD_ALLOWED_HOSTS`, default: the configured storage account, e.g., `*.blob.core.windows.net`). (3) Reject any URL containing `169.254.`, `localhost`, `127.0.0.1`, `10.*`, `172.16.*`-`172.31.*`, `192.168.*` private ranges. (4) Validate the URL parses correctly before any network call. Return 400 with `{"detail": "asset_href must point to an allowed storage host", "status": 400}`.

Tradeoff: Legitimate users with assets on non-standard hosts would need the allowlist expanded. This is the correct security posture -- explicit allow rather than implicit trust.

**CONFLICT 8: Filename parameter header injection (C's E7)**

C found: The `filename` override parameter is user-supplied and placed directly into the `Content-Disposition` header. An attacker could inject CRLF sequences or additional headers.

How it affects A: A's `FilenameGenerator` uses the filename in header construction without sanitization.

Resolution: Sanitize the filename parameter: (1) Strip path components (`/`, `\`). (2) Replace any character outside `[a-zA-Z0-9._-]` with `_`. (3) Limit to 200 characters. (4) If the result is empty after sanitization, fall back to auto-generated filename. (5) Use RFC 6266 `filename*=UTF-8''...` encoding in the Content-Disposition header for safety. Implement as a pure function in the filename generator module.

Tradeoff: Filenames with unicode or special characters will be normalized. This is acceptable and standard practice.

**CONFLICT 9: Collection ID schema qualification (C's E8)**

C found: TiPG exposes tables with qualified names (e.g., `geo.my_table`). A user might pass `my_table` or `geo.my_table` -- the resolution is ambiguous.

How it affects A: A's `VectorQueryService.collection_exists()` and `query_features()` use the `collection_id` to construct SQL queries. Schema-unqualified names could match wrong tables or fail entirely.

Resolution: The `VectorQueryService` must validate the `collection_id` against TiPG's `collection_catalog` (available on `app.state.collection_catalog`). This catalog contains the authoritative set of collection IDs as TiPG exposes them. If the user-supplied `collection_id` is not in the catalog, return 404. This sidesteps the schema qualification problem entirely -- the catalog is the source of truth. For SQL query construction, look up the table's actual schema and table name from the catalog entry's metadata, do not construct SQL from the user-supplied string directly.

Tradeoff: Downloads are limited to tables that TiPG has discovered. A table not in the TiPG catalog cannot be downloaded. This is correct -- download visibility should match API visibility.

### O's Operational Requirements Adding Complexity

**CONFLICT 10: Per-replica concurrency semaphore**

O requires: Max 5 concurrent downloads per replica (semaphore) to prevent memory exhaustion and connection pool starvation.

Cost: Adds a semaphore check to every download request. Requests exceeding the limit must queue or fail.

Resolution: Justified. Implement `asyncio.Semaphore` stored on `app.state.download_semaphore` at startup. Configure via `GEOTILER_DOWNLOAD_MAX_CONCURRENT` (default: 3, conservative given 1-4 GB memory and single worker). Requests that cannot acquire the semaphore within 5 seconds return 503 with `{"detail": "Download capacity exceeded, retry shortly", "status": 503, "retry_after_seconds": 10}`. Include `Retry-After: 10` header.

Tradeoff: Limits throughput to 3 concurrent downloads. Given the single-worker architecture and shared memory budget, this is necessary. Higher-traffic deployments should increase replica count, not concurrent download limit.

**CONFLICT 11: Structured observability for every download**

O requires: Structured logging with event_type, endpoint, collection/asset_hash, bbox, format, byte_count, feature_count, truncated, duration_ms, titiler_duration_ms, db_duration_ms, user_oid, error_category, downstream_service.

Cost: Adds logging instrumentation to every download code path. Requires timing instrumentation in the service layer.

Resolution: Justified for production operations. Implement via a `DownloadMetrics` dataclass that accumulates timings throughout the request lifecycle. Log a single structured JSON event at request completion (success or failure). Use the existing Python `logging` module with JSON formatter (matching the codebase convention). User OID comes from `X-MS-CLIENT-PRINCIPAL-ID` header (populated by Easy Auth). Hash the asset_href for logging (do not log raw blob URIs -- matches Invariant 3).

Tradeoff: Adds ~10 lines of instrumentation per endpoint handler. The operational benefit (debugging, alerting, capacity planning) justifies this.

**CONFLICT 12: Database connection pool contention**

O warns: Large vector queries will contend with TiPG and pgSTAC for the shared asyncpg connection pool.

Cost: Under concurrent load, download queries could starve TiPG tile serving.

Resolution: Partially addressed by the concurrency semaphore (CONFLICT 10). Additionally, vector download queries should use `statement_timeout` (180s) to prevent runaway queries from holding connections indefinitely. The VectorQueryService should acquire a connection from `app.state.pool` (the TiPG asyncpg pool) with an explicit timeout on acquisition (5 seconds). If the pool is exhausted, return 503. This is justified because download queries are a secondary use case -- tile serving latency must be protected.

Tradeoff: Download queries may fail with 503 under heavy TiPG load. This is the correct priority ordering -- interactive tile serving trumps batch downloads.

### C's Concerns Addressed or Worsened by O's Infrastructure

**C's E2 (TiTiler crop likely buffered) -- ADDRESSED by O's memory constraint:**

C noted TiTiler crop responses are likely buffered in memory. O's memory constraint (1-4 GB shared) means a large raster crop could consume significant memory. The ASGI transport approach (CONFLICT 1 resolution) means the TiTiler crop runs in-process and its memory consumption is part of the same budget. The bbox area limit (`GEOTILER_DOWNLOAD_RASTER_MAX_BBOX_AREA_DEG`, default 25 square degrees) caps the maximum crop size, but the actual memory consumption depends on pixel resolution. This remains a residual risk (see RISK REGISTER).

**C's E3 (concurrent large downloads exhaust memory) -- ADDRESSED by O's semaphore:**

The concurrency semaphore (CONFLICT 10) directly addresses this. Max 3 concurrent downloads bounds the worst-case memory consumption to approximately 3x the largest single download's memory footprint.

**C's C2 (asyncpg vs psycopg) -- CLARIFIED by codebase review:**

The existing codebase uses BOTH: psycopg via `ConnectionPool` for titiler-pgstac (sync pool on `app.state.dbpool`), and asyncpg via TiPG's `connect_to_db` (async pool on `app.state.pool`). Vector download queries should use the asyncpg pool (`app.state.pool`) since they need async execution. This is the same pool TiPG uses, confirming CONFLICT 12.

**C's G10 (AzureAuthMiddleware skip list) -- WORSENED by design:**

The existing `AzureAuthMiddleware` skips `/api` paths (line 28 of `azure_auth.py`). The spec routes downloads under `/api/download/*`. This means download endpoints will NOT have storage auth configured by the middleware. For raster and full-asset downloads, the storage token is needed. Resolution: Either (a) remove `/api` from `_SKIP_AUTH_PREFIXES` and add specific sub-paths that should skip, or (b) have the download service explicitly call `get_storage_oauth_token_async()` itself rather than relying on middleware. Option (b) is better because the download service needs the token value explicitly (to pass to the Azure Blob SDK or include in ASGI request context), not just the GDAL environment variable configuration. The download service should call `storage_token_cache.get_if_valid()` directly.

---

## DESIGN TENSIONS

**TENSION 1: HTTP delegation pattern vs in-process TiTiler**

Agent A (and the original spec) proposed HTTP delegation to TiTiler as a separate service. The Design Constraint confirms TiTiler is in-process and says "for P1, call via internal HTTP (localhost)." However, codebase reality and O's single-worker constraint make true HTTP loopback impossible (deadlock). The ASGI transport approach preserves the HTTP contract semantically while running in-process. This is a pragmatic middle ground.

Constraint enforced: TiTiler delegation uses HTTP-like interface (ASGI transport via httpx).

Observation: The existing constraint ("TiTiler delegation is HTTP-based") was written assuming a multi-container architecture that does not exist. The ASGI transport approach respects the intent (loose coupling, testability, HTTP contract boundary) while acknowledging reality. When TiTiler is eventually extracted to its own container (the DESIRED architecture), the only change needed is swapping `ASGITransport(app=app)` for a real HTTP base URL. This validates the approach. However, the constraint should be updated to say "TiTiler delegation uses ASGI transport for in-process, HTTP for extracted service" to prevent future confusion.

**TENSION 2: "No SAS tokens" invariant vs proxy scalability**

Agent O's analysis shows that proxying large blobs (multi-GB) through a 1-4 GB container is not sustainable. The PRIVATE DESIGN CONSTRAINT acknowledges this: "SAS tokens CAN be reconsidered." Agent A's design adheres strictly to the "no SAS tokens" invariant. The constraint enforced is the proxy pattern with a size limit for P1.

Constraint enforced: Proxy pattern with configurable max size (P1). No SAS tokens yet.

Observation: The tension is real. For files above the proxy limit, users currently have no download path. User Delegation SAS tokens (signed by managed identity, scoped to specific blob, short-lived, read-only) would solve this without the security concerns of account-key SAS tokens. This should be revisited for P2 when usage data shows whether the proxy limit is frequently hit.

**TENSION 3: Pydantic v2 models vs raw SQL (vector queries)**

The Design Constraint specifies "Data contracts: Pydantic v2 models for request/response validation." Agent A's vector query service uses raw SQL with asyncpg and returns dicts. This is consistent with the existing codebase pattern (diagnostics.py uses raw SQL extensively) but creates a tension with the Pydantic convention for request/response validation.

Constraint enforced: Pydantic v2 models for request parameter validation (ParsedBbox, download request params). Raw SQL for database queries (matching existing codebase pattern). Response streaming bypasses Pydantic serialization (necessary for streaming).

Observation: The existing codebase uses Pydantic for config and incoming request validation but not for database query results. This is pragmatic -- Pydantic serialization overhead on 100K feature rows would be prohibitive. The convention should be clarified: "Pydantic for API boundaries (request/response schemas), raw dicts for internal data flow."

---

## RESOLVED SPEC

### Component 1: Download Configuration (extend `geotiler/config.py`)

**Responsibility:** Define all download-related configuration as fields on the existing `Settings` class, following the `GEOTILER_COMPONENT_SETTING` convention.

**Interface:**

```python
# Add to existing Settings class in geotiler/config.py

# Feature flag
enable_downloads: bool = False
"""Enable download endpoints at /api/download/*."""

# Raster limits
download_raster_max_bbox_area_deg: float = 25.0
"""Maximum bounding box area in square degrees for raster crops."""

# Vector limits
download_vector_max_features: int = 100_000
"""Maximum features returned per vector subset query."""

download_vector_query_timeout_sec: int = 180
"""PostgreSQL statement_timeout for vector download queries."""

# Blob proxy limits
download_proxy_max_size_mb: int = 500
"""Maximum blob size (MB) for proxied full-asset downloads."""

download_blob_chunk_size: int = 4_194_304  # 4 MB
"""Chunk size in bytes for streaming blob downloads."""

# Timeouts
download_timeout_sec: int = 200
"""Internal timeout for download operations (must be < 240s platform timeout)."""

# Concurrency
download_max_concurrent: int = 3
"""Maximum concurrent download streams per replica."""

# Asset validation
download_allowed_hosts: str = ""
"""Comma-separated allowed hostnames for asset_href (e.g., 'myaccount.blob.core.windows.net').
If empty, defaults to GEOTILER_STORAGE_ACCOUNT + '.blob.core.windows.net'."""

@property
def download_allowed_host_list(self) -> list[str]:
    """Parse comma-separated allowed hosts into list."""
    if self.download_allowed_hosts:
        return [h.strip() for h in self.download_allowed_hosts.split(",") if h.strip()]
    if self.storage_account:
        return [f"{self.storage_account}.blob.core.windows.net"]
    return []
```

**Error handling:** Pydantic validation handles type coercion and defaults. Invalid values raise on startup.

**Operational requirements:** All values logged at startup when `enable_downloads=true`. No secrets in these fields.

**Integration notes:** Extend existing `Settings` class in `/Users/robertharrison/python_builds/rmhtitiler/geotiler/config.py`. Follow existing field naming patterns. Add fields after the H3 section.

---

### Component 2: Download Router (`geotiler/routers/download.py`)

**Responsibility:** Thin routing layer that validates request parameters, enforces the concurrency semaphore, dispatches to the download service, and constructs streaming responses.

**Interface:**

```python
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/download", tags=["Download"])

@router.get("/raster/crop")
async def download_raster_crop(
    request: Request,
    asset_href: str = Query(..., description="STAC asset href pointing to a COG"),
    bbox: str = Query(..., description="Bounding box as 'minx,miny,maxx,maxy' in EPSG:4326"),
    format: str = Query("tif", description="Output format. P1: 'tif' only"),
    filename: str = Query(None, description="Override auto-generated filename"),
) -> StreamingResponse: ...

@router.get("/vector/subset")
async def download_vector_subset(
    request: Request,
    collection_id: str = Query(..., description="TiPG collection ID"),
    bbox: str = Query(None, description="Bounding box as 'minx,miny,maxx,maxy' in EPSG:4326"),
    format: str = Query("geojson", description="'geojson' or 'csv'"),
    filename: str = Query(None, description="Override auto-generated filename"),
    limit: int = Query(None, description="Feature limit, capped at system max"),
) -> StreamingResponse: ...

@router.get("/asset/full")
async def download_asset_full(
    request: Request,
    asset_href: str = Query(..., description="STAC asset href pointing to a blob"),
    filename: str = Query(None, description="Override auto-generated filename"),
) -> StreamingResponse: ...
```

**Error handling strategy:**

| Condition | Status | Body |
|-----------|--------|------|
| Invalid bbox format | 400 | `{"detail": "Invalid bbox format. Expected 'minx,miny,maxx,maxy'", "status": 400}` |
| Bbox exceeds area limit | 400 | `{"detail": "Bbox area exceeds limit", "status": 400, "area_deg_sq": X, "limit_deg_sq": Y}` |
| Asset href fails validation | 400 | `{"detail": "asset_href must point to an allowed storage host", "status": 400}` |
| Asset not found | 404 | `{"detail": "Asset not found", "status": 404}` |
| Collection not found | 404 | `{"detail": "Collection not found in TiPG catalog", "status": 404, "available": [...first 20...]}` |
| Unsupported format | 400 | `{"detail": "Unsupported format", "status": 400, "supported": ["geojson", "csv"]}` |
| Blob exceeds proxy size limit | 400 | `{"detail": "File exceeds download size limit", "status": 400, "size_mb": X, "limit_mb": Y}` |
| Semaphore exhausted (5s timeout) | 503 | `{"detail": "Download capacity exceeded, retry shortly", "status": 503, "retry_after_seconds": 10}` |
| TiTiler/GDAL error | 422 | `{"detail": "Raster processing error: <GDAL message>", "status": 422}` |
| Database query timeout | 504 | `{"detail": "Query timed out", "status": 504}` |
| Pool exhausted | 503 | `{"detail": "Database busy, retry shortly", "status": 503}` |

**Operational requirements:**

- Log a single structured JSON event per request at completion: `{"event": "download_complete", "endpoint": "raster_crop|vector_subset|asset_full", "asset_hash": "<sha256[:12]>", "collection_id": "<id>", "bbox": "<bbox>", "format": "<fmt>", "byte_count": <n>, "feature_count": <n>, "truncated": <bool>, "duration_ms": <n>, "user_oid": "<from X-MS-CLIENT-PRINCIPAL-ID>", "status": <code>}`.
- On error, log: `{"event": "download_error", "endpoint": "...", "error_category": "validation|not_found|upstream|timeout|capacity", "detail": "...", "duration_ms": <n>}`.

**Integration notes:**

- Mount in `app.py` conditionally: `if settings.enable_downloads: app.include_router(download.router)`.
- Add `"/api/download"` tag to `openapi_tags` list in `create_app()`.
- The `/api` prefix is already in `_SKIP_AUTH_PREFIXES` in the AzureAuthMiddleware -- download endpoints do NOT rely on middleware for storage auth. Instead, the download service acquires tokens explicitly.
- Initialize `app.state.download_semaphore = asyncio.Semaphore(settings.download_max_concurrent)` in the lifespan startup block.

---

### Component 3: Download Service (`geotiler/services/download.py`)

**Responsibility:** Orchestrate download workflows: validate inputs, enforce limits, delegate to specialized clients, construct streaming responses.

**Interface:**

```python
from dataclasses import dataclass
from typing import AsyncIterator

@dataclass(frozen=True)
class ParsedBbox:
    minx: float
    miny: float
    maxx: float
    maxy: float

    @property
    def area_degrees_sq(self) -> float:
        return abs(self.maxx - self.minx) * abs(self.maxy - self.miny)

    def validate(self) -> None:
        """Raise ValueError if bbox is invalid."""
        if self.minx >= self.maxx:
            raise ValueError("minx must be less than maxx")
        if self.miny >= self.maxy:
            raise ValueError("miny must be less than maxy")
        if not (-180 <= self.minx <= 180 and -180 <= self.maxx <= 180):
            raise ValueError("Longitude must be between -180 and 180")
        if not (-90 <= self.miny <= 90 and -90 <= self.maxy <= 90):
            raise ValueError("Latitude must be between -90 and 90")

    def to_str(self) -> str:
        return f"{self.minx},{self.miny},{self.maxx},{self.maxy}"


@dataclass(frozen=True)
class DownloadResult:
    stream: AsyncIterator[bytes]
    content_type: str
    filename: str
    headers: dict[str, str]  # Custom X- headers and Content-Disposition


def parse_bbox(bbox_str: str) -> ParsedBbox:
    """Parse and validate bbox string. Raises ValueError."""
    ...

async def handle_raster_crop(
    app: "FastAPI",
    asset_href: str,
    bbox: ParsedBbox,
    format: str,
    filename: str | None,
) -> DownloadResult:
    """Full raster crop workflow. Raises HTTPException on failure."""
    ...

async def handle_vector_subset(
    app: "FastAPI",
    collection_id: str,
    bbox: ParsedBbox | None,
    format: str,
    filename: str | None,
    limit: int | None,
) -> DownloadResult:
    """Full vector subset workflow. Raises HTTPException on failure."""
    ...

async def handle_asset_download(
    app: "FastAPI",
    asset_href: str,
    filename: str | None,
) -> DownloadResult:
    """Full asset download workflow. Raises HTTPException on failure."""
    ...
```

**Error handling:**

- Input validation errors raise `ValueError`, caught by router and converted to 400.
- Upstream service errors (TiTiler, PostGIS, Blob Storage) are caught, logged with structured JSON, and re-raised as `HTTPException` with appropriate status codes.
- Token freshness is checked before each operation; proactive refresh triggered if TTL < 260s.

**Operational requirements:**

- Timing instrumentation: record `start_time` at function entry, `titiler_duration_ms` or `db_duration_ms` for downstream calls, total `duration_ms` at completion.
- All blob URIs are hashed (SHA256, first 12 chars) before logging. Never log raw blob URLs.

**Integration notes:**

- Uses `storage_token_cache` from `geotiler/auth/cache.py` for token freshness checks.
- Uses `app.state.pool` (asyncpg) for vector queries.
- Uses `app` (FastAPI instance) for ASGI transport TiTiler calls.
- Uses settings from `geotiler/config.py`.

---

### Component 4: TiTiler Client (`geotiler/services/download_clients.py`)

**Responsibility:** Execute TiTiler crop operations via ASGI transport, returning the response bytes.

**Interface:**

```python
import httpx

class TiTilerClient:
    """Calls in-process TiTiler via ASGI transport (no network roundtrip)."""

    def __init__(self, app: "FastAPI", timeout_sec: float = 200.0):
        self._transport = httpx.ASGITransport(app=app)
        self._timeout = timeout_sec

    async def crop(
        self,
        asset_url: str,
        bbox: "ParsedBbox",
        format: str = "tif",
    ) -> tuple[bytes, dict[str, str]]:
        """
        Execute raster crop via TiTiler's /cog/bbox endpoint.

        Args:
            asset_url: Full blob URL for the COG asset.
            bbox: Validated bounding box.
            format: Output format (default "tif").

        Returns:
            Tuple of (response_bytes, response_headers).
            NOTE: TiTiler crop responses are buffered (not streamed).

        Raises:
            httpx.HTTPStatusError: If TiTiler returns non-2xx status.
            httpx.TimeoutException: If the crop exceeds timeout.
        """
        ...
```

**Error handling:**

- `httpx.HTTPStatusError` with 4xx: re-raise as 422 with TiTiler's error detail.
- `httpx.HTTPStatusError` with 5xx: re-raise as 502 ("Upstream raster service error").
- `httpx.TimeoutException`: re-raise as 504 ("Raster crop timed out").
- GDAL errors in TiTiler response bodies: extract and include in 422 detail.

**Operational requirements:**

- Log TiTiler call duration (`titiler_duration_ms`).
- Log ASGI response status code.

**Integration notes:**

- The `TilerFactory` mounted at `/cog` exposes `/cog/bbox/{minx},{miny},{maxx},{maxy}.{format}` (confirmed in WIKI.md).
- The ASGI transport requires the `app` instance. Create the client in the download service, passing `request.app`.
- The ASGI transport does not go through the network stack, so it bypasses `AzureAuthMiddleware`. However, GDAL auth is configured via `os.environ` (already set by the storage auth initialization and background refresh), so TiTiler will have valid credentials.
- TiTiler crop likely returns a buffered response (not streaming). Treat the response body as complete bytes and wrap in an async iterator for the `DownloadResult`.

---

### Component 5: Vector Query Service (`geotiler/services/vector_query.py`)

**Responsibility:** Execute spatial queries against PostGIS via the existing asyncpg pool, returning features as an async iterator.

**Interface:**

```python
from typing import AsyncIterator

class VectorQueryService:
    """Queries PostGIS collections via asyncpg pool."""

    def __init__(self, pool, catalog: dict, settings: "Settings"):
        self._pool = pool  # asyncpg pool from app.state.pool
        self._catalog = catalog  # TiPG collection_catalog
        self._settings = settings

    def collection_exists(self, collection_id: str) -> bool:
        """Check if collection_id exists in TiPG catalog."""
        return collection_id in self._catalog

    def get_collection_table_info(self, collection_id: str) -> tuple[str, str, str]:
        """
        Get schema, table, geometry_column from catalog.

        Returns:
            (schema_name, table_name, geometry_column)

        Raises:
            KeyError: If collection not in catalog.
        """
        ...

    async def count_features(
        self,
        collection_id: str,
        bbox: "ParsedBbox | None",
    ) -> int:
        """Count features matching the filter (for X-Feature-Count header)."""
        ...

    async def query_features(
        self,
        collection_id: str,
        bbox: "ParsedBbox | None",
        limit: int,
    ) -> AsyncIterator[dict]:
        """
        Execute spatial query and yield feature dicts.

        Uses server-side cursor for streaming. Each dict contains:
        - All non-geometry columns as key-value pairs
        - "geometry" key with GeoJSON geometry (from ST_AsGeoJSON)

        SQL pattern:
            SELECT *, ST_AsGeoJSON(geom)::json as __geojson
            FROM schema.table
            WHERE ST_Intersects(geom, ST_MakeEnvelope($1,$2,$3,$4, 4326))
            LIMIT $5

        Args:
            collection_id: Validated collection ID (must exist in catalog).
            bbox: Optional spatial filter.
            limit: Maximum features to return.

        Yields:
            Feature dicts suitable for GeoJSON serialization.

        Raises:
            asyncpg.PostgresError: Database errors.
            asyncio.TimeoutError: If statement_timeout exceeded.
        """
        ...
```

**Error handling:**

- `asyncpg.InterfaceError` (pool closed): return 503.
- `asyncpg.PostgresError` with `statement_timeout`: return 504.
- `asyncpg.UndefinedTableError`: return 404 (catalog is stale).
- All SQL uses parameterized queries (`$1, $2, ...`). Schema and table names from the catalog are validated against `^[a-zA-Z_][a-zA-Z0-9_]*$` pattern (matching existing `_validate_sql_identifier` in diagnostics.py).

**Operational requirements:**

- Log `db_duration_ms` for the query execution time.
- Log `feature_count` and `truncated` status.
- Set `statement_timeout` on the connection: `SET statement_timeout = '{timeout_sec * 1000}'` before executing.

**Integration notes:**

- Uses `app.state.pool` (asyncpg pool from TiPG initialization).
- Uses `app.state.collection_catalog` (TiPG's discovered collections).
- Geometry column name comes from the catalog entry, not from `settings.tipg_geometry_column` (the catalog knows the actual column name per table).
- Connection acquisition timeout: 5 seconds (to fail fast under pool pressure).
- CSV geometry handling: For CSV format, output centroid as separate `latitude` and `longitude` columns using `ST_Y(ST_Centroid(geom))` and `ST_X(ST_Centroid(geom))`. Omit the full geometry from CSV output. This addresses C's E5 (mixed geometry types) -- centroids are always points.

---

### Component 6: Blob Stream Client (`geotiler/services/blob_stream.py`)

**Responsibility:** Authenticated streaming reads from Azure Blob Storage using the `azure-storage-blob` SDK with managed identity credentials.

**Interface:**

```python
from typing import AsyncIterator

class BlobStreamClient:
    """Authenticated blob streaming via azure-storage-blob SDK."""

    def __init__(self, settings: "Settings"):
        self._chunk_size = settings.download_blob_chunk_size
        self._max_size_mb = settings.download_proxy_max_size_mb
        self._allowed_hosts = settings.download_allowed_host_list

    async def get_blob_properties(self, blob_url: str) -> dict:
        """
        Get blob metadata without downloading.

        Returns:
            {"size_bytes": int, "content_type": str, "etag": str}

        Raises:
            ResourceNotFoundError: Blob does not exist.
            ValueError: URL fails validation.
        """
        ...

    async def stream_blob(
        self,
        blob_url: str,
        token: str,
    ) -> AsyncIterator[bytes]:
        """
        Stream blob content as chunks.

        Args:
            blob_url: Validated blob URL.
            token: OAuth bearer token for Azure Storage.

        Yields:
            Chunks of blob content.

        Raises:
            ResourceNotFoundError: Blob does not exist.
            HttpResponseError: Azure storage error.
        """
        ...

    def validate_url(self, url: str) -> tuple[str, str, str]:
        """
        Validate and parse blob URL.

        Returns:
            (account_url, container_name, blob_path)

        Raises:
            ValueError: URL invalid or not in allowlist.
        """
        ...
```

**Error handling:**

- `azure.core.exceptions.ResourceNotFoundError`: return 404.
- `azure.core.exceptions.HttpResponseError` with 403: return 502 ("Storage access denied -- credential may be expired").
- `azure.core.exceptions.HttpResponseError` with 429: return 503 ("Storage throttled, retry later") with `Retry-After`.
- URL validation failure: return 400.

**Operational requirements:**

- Log blob size before streaming begins.
- Hash blob URL for log entries.
- Track bytes streamed for completion log event.

**Integration notes:**

- Use `azure.storage.blob.aio.BlobServiceClient` (async version) with `TokenCredential` wrapping the token from `storage_token_cache`.
- The token is passed explicitly, not read from environment variables (since the middleware is skipped for `/api` paths).
- Parse blob URL to extract account, container, and blob path. Azure Blob URLs follow: `https://{account}.blob.core.windows.net/{container}/{path}`.
- Create a fresh `BlobServiceClient` per request (or use a shared one on `app.state` with connection pooling -- evaluate during implementation).

---

### Component 7: Asset Resolver (`geotiler/services/asset_resolver.py`)

**Responsibility:** Validate and normalize STAC asset hrefs, enforcing the URL allowlist.

**Interface:**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ResolvedAsset:
    blob_url: str  # Full https:// URL to the blob
    account_name: str
    container_name: str
    blob_path: str
    content_type_hint: str  # Inferred from extension (e.g., "image/tiff")


class AssetResolver:
    """Validates and resolves STAC asset hrefs to internal blob URLs."""

    def __init__(self, allowed_hosts: list[str]):
        self._allowed_hosts = allowed_hosts
        self._blocked_ranges = [
            "169.254.", "127.0.0.1", "localhost",
            "10.", "192.168.",
        ]  # Plus 172.16-31.x.x range check

    def resolve(self, asset_href: str) -> ResolvedAsset:
        """
        Validate and parse asset_href.

        Accepted formats:
        - Full URL: https://account.blob.core.windows.net/container/path/file.tif
        - GDAL vsi path: /vsiaz/container/path/file.tif (converted using storage_account setting)

        Returns:
            ResolvedAsset with validated, normalized URL.

        Raises:
            ValueError: If URL is invalid, uses blocked host, or not in allowlist.
        """
        ...

    @staticmethod
    def infer_content_type(path: str) -> str:
        """Infer MIME type from file extension."""
        ...
```

**Error handling:**

- All validation is synchronous and raises `ValueError`. The caller (download service) catches and converts to 400.
- No network calls in this component -- it is purely a validation/parsing layer.

**Operational requirements:** None (pure function, no I/O).

**Integration notes:**

- Handles both `https://` URLs and `/vsiaz/` paths (the latter is common in STAC assets for GDAL-based systems). When converting `/vsiaz/container/path`, uses `settings.storage_account` to construct the full URL.
- The GDAL vsi path is NOT returned to the browser (Invariant 3). Only the internal resolved URL is used for server-side operations.

---

### Component 8: Filename Generator (`geotiler/services/filename_gen.py`)

**Responsibility:** Generate and sanitize download filenames for Content-Disposition headers.

**Interface:**

```python
from datetime import date

def generate_filename(
    *,
    prefix: str,  # "raster", "vector", "asset"
    source_name: str,  # Collection ID or sanitized asset path segment
    bbox: "ParsedBbox | None" = None,
    format_ext: str,  # "tif", "geojson", "csv", etc.
    generation_date: date | None = None,  # Defaults to today
) -> str:
    """
    Generate a human-readable filename.

    Pattern: {prefix}_{source_name}_{bbox_summary}_{date}.{ext}
    Example: raster_ndvi_2024_35.2N_1.5W_36.0N_0.5E_20260228.tif
    Example: vector_flood_zones_20260228.geojson

    Returns:
        Sanitized filename string (max 200 chars, [a-zA-Z0-9._-] only).
    """
    ...


def sanitize_filename(user_filename: str) -> str:
    """
    Sanitize user-provided filename override.

    - Strip path components (/, \\)
    - Replace chars outside [a-zA-Z0-9._-] with _
    - Limit to 200 characters
    - Return empty string if nothing remains (caller uses auto-generated)

    Returns:
        Sanitized filename or empty string.
    """
    ...


def build_content_disposition(filename: str) -> str:
    """
    Build RFC 6266 Content-Disposition header value.

    Returns:
        'attachment; filename="<ascii>"; filename*=UTF-8\'\'<encoded>'
    """
    ...
```

**Error handling:** Pure functions, no exceptions. Invalid input produces safe defaults.

**Operational requirements:** None.

**Integration notes:** No external dependencies.

---

### Component 9: Vector Serializers (`geotiler/services/serializers.py`)

**Responsibility:** Convert async iterators of feature dicts into streaming bytes in GeoJSON or CSV format.

**Interface:**

```python
from typing import AsyncIterator

async def serialize_geojson(
    features: AsyncIterator[dict],
    feature_count: int | None = None,
) -> AsyncIterator[bytes]:
    """
    Serialize features to streaming GeoJSON FeatureCollection.

    Framing approach:
    1. Yield: b'{"type":"FeatureCollection","features":['
    2. For each feature: yield JSON-encoded Feature object with comma separator
    3. Yield: b']}'

    No buffering -- each feature is serialized individually.

    Args:
        features: Async iterator of feature dicts (from VectorQueryService).
        feature_count: Optional total count (included in FeatureCollection if provided).

    Yields:
        UTF-8 encoded bytes of valid GeoJSON.
    """
    ...


async def serialize_csv(
    features: AsyncIterator[dict],
    geometry_mode: str = "centroid",  # "centroid" yields lat/lon columns
) -> AsyncIterator[bytes]:
    """
    Serialize features to streaming CSV.

    First feature determines the column headers.
    Geometry is represented as centroid lat/lon columns.

    Yields:
        UTF-8 encoded bytes of CSV content with header row.
    """
    ...
```

**Error handling:**

- If a feature dict cannot be serialized (e.g., non-JSON-serializable value), skip it and log a warning. Do not abort the entire stream for one bad row.
- If the feature iterator raises an exception mid-stream, the stream terminates. The client receives a truncated response (this is an inherent limitation of streaming). Log the error with `error_category: "stream_interrupted"`.

**Operational requirements:** Log count of skipped features (if any).

**Integration notes:** Uses Python `json` module for GeoJSON, `csv` module for CSV. No external dependencies.

---

### Component 10: App Integration (`geotiler/app.py` modifications)

**Responsibility:** Wire the download subsystem into the FastAPI application lifecycle.

**Changes to lifespan:**

```python
# In lifespan startup, after existing initialization:
if settings.enable_downloads:
    import asyncio
    app.state.download_semaphore = asyncio.Semaphore(settings.download_max_concurrent)
    logger.info(
        f"Download endpoints enabled: max_concurrent={settings.download_max_concurrent}, "
        f"proxy_max_size_mb={settings.download_proxy_max_size_mb}"
    )
```

**Changes to create_app:**

```python
# In create_app, after existing router mounts:
if settings.enable_downloads:
    from geotiler.routers import download
    app.include_router(download.router, tags=["Download"])
    logger.info(f"Download router mounted at /api/download")
```

**Changes to openapi_tags:**

```python
# Add to openapi_tags list:
{"name": "Download", "description": "Data subset download (raster crop, vector subset, full asset)."},
```

**Health endpoint integration:**

Add a `download` service entry to `/health` response when downloads are enabled, reporting semaphore availability and configuration.

---

## DEFERRED DECISIONS

**D1: User Delegation SAS tokens for large asset downloads**

What: For blobs exceeding the proxy size limit, generate short-lived, scoped, read-only User Delegation SAS tokens signed by managed identity. Return a redirect or direct download URL.

Why it can wait: P1 enforces a size limit that covers the dominant use case (most useful geospatial subsets are under 500 MB). The proxy pattern works for this range.

Trigger to revisit: (a) Users frequently hit the size limit (monitor via structured logging). (b) Blob egress costs become significant. (c) Multi-GB COG downloads are requested.

**D2: GPKG export format**

What: GeoPackage output format for vector subset downloads.

Why it can wait: GeoJSON and CSV cover browser-based use cases. GPKG requires osgeo/GDAL Python bindings for creation, adding complexity.

Trigger to revisit: User feedback requesting GPKG specifically, or GIS tool integration requirements.

**D3: Async job infrastructure for long-running downloads**

What: Queue-based job system for downloads that exceed sync timeout, with status polling and result retrieval.

Why it can wait: The 200-second timeout with bbox area limits covers the sync use case. Async jobs require persistent job state (database table), a worker process, and a polling API -- significant infrastructure.

Trigger to revisit: (a) Raster crop timeouts become frequent. (b) Zarr/NetCDF slicing is added (P2/P3). (c) Multi-format export pipelines are needed.

**D4: Per-collection authorization**

What: Azure AD security group membership controlling which collections a user can download from.

Why it can wait: Currently all authenticated users can access all data. The spec explicitly defers this.

Trigger to revisit: Multi-tenant deployment or data sensitivity requirements.

**D5: Dedicated download connection pool**

What: A separate asyncpg connection pool for download queries, isolated from TiPG's pool.

Why it can wait: The concurrency semaphore (max 3) and statement_timeout (180s) bound the impact on the shared pool. Under current load, pool contention is manageable.

Trigger to revisit: (a) Pool exhaustion alerts fire. (b) TiPG latency degrades during download traffic. (c) Connection pool utilization consistently above 70%.

**D6: Zarr/NetCDF slicing**

What: Spatial/temporal subsetting of Zarr or NetCDF datasets via xarray.

Why it can wait: The spec explicitly defers this to P2/P3. The download architecture (service layer, streaming response) is compatible with adding a Zarr client alongside the TiTiler client.

Trigger to revisit: User demand for climate/weather data downloads.

---

## RISK REGISTER

**R1: TiTiler crop memory consumption**

Description: TiTiler's `/cog/bbox` endpoint buffers the entire crop result in memory before returning. For high-resolution COGs with large bounding boxes, this could consume hundreds of MB. Combined with the ASGI transport (in-process), this memory is allocated in the same container.

Likelihood: MEDIUM (depends on COG resolution and bbox size)

Impact: HIGH (OOMKill takes down the entire replica)

Mitigation: The bbox area limit (25 sq degrees) caps spatial extent. However, a 25 sq degree bbox on a 10m resolution COG could produce a very large raster. Monitor `process_rss_mb` (already in health endpoint) and raster crop byte counts in download logs. Consider adding a pixel count estimate before crop (requires a pre-flight `/cog/info` call to get resolution) in a future iteration.

**R2: Partial file delivery on mid-stream failure**

Description: Once HTTP 200 and headers are sent, any failure during streaming (token expiry, database disconnect, blob storage error, process kill) produces a truncated file that the browser saves as if it were complete.

Likelihood: LOW (token freshness check mitigates, timeouts are well below platform kill)

Impact: MEDIUM (user downloads corrupt file, may not realize it)

Mitigation: Token freshness check before streaming. `X-Byte-Count` header (when available) allows client-side verification. For vector GeoJSON, truncated JSON will fail to parse, making corruption obvious. For raster TIFF, the file will be structurally invalid. Document in user-facing download UI that users should verify file integrity.

**R3: asyncpg pool starvation under concurrent vector downloads**

Description: Three concurrent vector download queries, each holding a connection for up to 180 seconds, could consume 3 of ~10-20 pool connections for extended periods, degrading TiPG tile serving.

Likelihood: MEDIUM (depends on download frequency and query complexity)

Impact: MEDIUM (TiPG latency increases, may cause tile loading failures in maps)

Mitigation: Concurrency semaphore (max 3), statement_timeout (180s), connection acquisition timeout (5s). Monitor pool utilization in health endpoint. Escalation path: reduce `download_max_concurrent` to 2, or implement D5 (dedicated pool).

**R4: SSRF via crafted asset_href despite allowlist**

Description: DNS rebinding or URL parser differentials could allow a crafted URL to bypass the allowlist and reach internal services.

Likelihood: LOW (allowlist validation + blocked private ranges provide defense in depth)

Impact: HIGH (IMDS token exfiltration, internal service access)

Mitigation: URL validation blocks private IP ranges, only allows `https://` scheme, and checks hostname against explicit allowlist. Use `urllib.parse.urlparse()` for parsing (standard library, well-tested). Do not follow redirects on blob requests (use `allow_redirects=False` or equivalent). The Azure Blob SDK handles its own URL construction, so parsed components are re-assembled rather than passed through.

**R5: Feature gate misconfiguration in production**

Description: If `GEOTILER_ENABLE_DOWNLOADS` is accidentally set to `true` in production without corresponding infrastructure preparation (e.g., increased memory, connection pool size), download traffic could destabilize the existing tile serving workload.

Likelihood: LOW (feature flag defaults to `false`)

Impact: MEDIUM (degraded performance for existing users)

Mitigation: Feature flag defaults to `false`. Production deployment checklist should include: verify memory allocation, verify connection pool size, verify concurrency limit is appropriate for replica count. Health endpoint reports download configuration when enabled.

**R6: Stale TiPG catalog causing 404 for valid collections**

Description: If a PostGIS table is created after TiPG startup but before catalog refresh, the VectorQueryService will return 404 for that collection because it validates against the catalog.

Likelihood: LOW (catalog refresh runs on schedule or via webhook)

Impact: LOW (user retries after catalog refresh succeeds; error message is actionable)

Mitigation: The 404 response includes a hint to check `/vector/collections` for available collections. The admin refresh webhook (`/admin/refresh-collections`) can be triggered manually. CatalogUpdateMiddleware provides automatic refresh when enabled.
