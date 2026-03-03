# Download Initiator — Formal Spec (Agent S)

## PURPOSE

The Download Initiator is a routing and streaming layer that enables authenticated browser users to download geospatial data subsets from the DDHGeo platform. It acts as an authorized proxy: resolving internal storage resources from STAC asset references, delegating processing to specialized services (TiTiler for raster, PostGIS for vector), and streaming results back to the browser as downloadable files.

The system formalizes the dominant download use case — "give me the data for this bounding box" rather than "give me the entire file" — across both raster and vector data types, so users with only a browser can obtain what they need without Python, QGIS, or direct storage access.

---

## BOUNDARIES

### In Scope

- **Raster crop download**: Bounding-box extraction from Cloud-Optimized GeoTIFFs (COGs) via delegation to TiTiler, streamed to the browser as a downloadable file.
- **Vector subset download**: Spatial queries against PostGIS collections, serialized to GeoJSON or CSV, streamed to the browser as a downloadable file.
- **Full asset download**: Proxied streaming of complete blob assets from Azure Blob Storage, using the app's own identity.
- **STAC asset href resolution**: Translating STAC item `asset.href` values into authenticated internal resource access.
- **Output size enforcement**: Hard limits on vector feature count and raster crop area/size to prevent unbounded resource consumption.
- **Actionable error responses**: Every failed request returns a structured error with enough information for the user to take corrective action.

### Out of Scope

- **User authentication**: Handled by Azure Easy Auth at the platform level before requests reach the application.
- **Raster processing**: Handled by TiTiler. This component delegates via HTTP, never processes rasters directly.
- **Vector tile serving**: Handled by TiPG. This component serves downloadable files, not map tiles.
- **ETL pipeline operations**: Data ingestion is a separate Azure Functions system.
- **STAC catalog management**: pgSTAC is read-only from this component's perspective.
- **Collection-level authorization**: Per-collection access control via Azure AD security group membership. Deferred — adds complexity (security group → collection mapping, asset_href → collection resolution) that is independent of the download machinery. Can be added as a middleware layer without changing endpoint logic.
- **GPKG export format**: Deferred to P2.
- **GeoParquet export format**: Deferred beyond P2.
- **Async job infrastructure**: Deferred to P2/P3 (needed for GPKG export, Zarr slicing).
- **Zarr/NetCDF slicing**: Deferred to P2/P3.

---

## CONTRACTS

### 1. Raster Crop Download

**Endpoint**: `GET /api/download/raster/crop`

**Input**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `asset_href` | `str` | Yes | STAC asset href pointing to a COG in blob storage |
| `bbox` | `str` | Yes | Bounding box as `"minx,miny,maxx,maxy"` in EPSG:4326 |
| `format` | `str` | No (default: `"tif"`) | Output raster format. P1: `"tif"` only |
| `filename` | `str` | No | Override auto-generated filename |

**Output (success)**:

- `StreamingResponse`
- `Content-Type: image/tiff`
- `Content-Disposition: attachment; filename="<generated_or_override>"`
- `X-Source-Asset: <sanitized identifier — no tokens, no storage paths>`
- `X-Byte-Count: <total bytes streamed>`

**Errors**:

| Status | Condition | Body |
|--------|-----------|------|
| `400` | bbox exceeds max area/size limit | `{"detail": "Bounding box exceeds maximum crop area. Use the full asset download endpoint.", "asset_download_url": "/api/download/asset/download", "asset_href": "<original href>"}` |
| `400` | Invalid bbox format | `{"detail": "Invalid bounding box format. Expected minx,miny,maxx,maxy in EPSG:4326."}` |
| `404` | asset_href not resolvable | `{"detail": "Asset not found."}` |
| `422` | GDAL/TiTiler processing error | `{"detail": "<upstream error message>"}` |

**Promises**:

- The response is streamed. The full raster is never buffered in memory by this component.
- Either a complete file is streamed or an error is returned before any bytes are sent. No partial files.
- The raw blob URI is never included in the response or headers.

**Requirements**:

- Caller must be authenticated (Easy Auth, platform-enforced).

---

### 2. Vector Subset Download

**Endpoint**: `GET /api/download/vector/subset`

**Input**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `collection_id` | `str` | Yes | Collection identifier (matches PostGIS table / TiPG collection) |
| `bbox` | `str` | No | Bounding box as `"minx,miny,maxx,maxy"` in EPSG:4326 |
| `format` | `str` | No (default: `"geojson"`) | `"geojson"` or `"csv"` |
| `filename` | `str` | No | Override auto-generated filename |
| `limit` | `int` | No | Feature limit, capped at system maximum |

**Output (success)**:

- `StreamingResponse`
- GeoJSON: `Content-Type: application/geo+json`
- CSV: `Content-Type: text/csv`
- `Content-Disposition: attachment; filename="<generated_or_override>"`
- `X-Feature-Count: <features in response>`
- `X-Truncated: true|false`
- `X-Byte-Count: <total bytes streamed>`

**Errors**:

| Status | Condition | Body |
|--------|-----------|------|
| `400` | Invalid bbox format | `{"detail": "Invalid bounding box format."}` |
| `400` | Unsupported format | `{"detail": "Unsupported format. Supported: geojson, csv."}` |
| `404` | collection_id not found | `{"detail": "Collection not found."}` |

**Promises**:

- Feature count is capped at a configurable system maximum (default: 100,000). If the query returns more features than the cap, the response is truncated and `X-Truncated: true` is set.
- The response is streamed; features are serialized incrementally, not buffered in full.
- Either a complete file is streamed or an error is returned. No partial files, no hung connections.

**Requirements**:

- Caller must be authenticated (Easy Auth, platform-enforced).

---

### 3. Full Asset Download

**Endpoint**: `GET /api/download/asset/download`

**Input**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `asset_href` | `str` | Yes | STAC asset href pointing to a blob in storage |
| `filename` | `str` | No | Override auto-generated filename |

**Output (success)**:

- `StreamingResponse`
- `Content-Type` inferred from file extension (e.g., `image/tiff`, `application/octet-stream`)
- `Content-Disposition: attachment; filename="<generated_or_override>"`
- `X-Byte-Count: <total bytes streamed>`

**Errors**:

| Status | Condition | Body |
|--------|-----------|------|
| `404` | asset_href not resolvable | `{"detail": "Asset not found."}` |

**Promises**:

- The blob is streamed through the app using the app's own storage identity. The raw blob URI and all credentials are never exposed to the client.
- No SAS tokens are generated under any circumstances.
- Either a complete file is streamed or an error is returned.

**Requirements**:

- Caller must be authenticated (Easy Auth, platform-enforced).

---

## INVARIANTS

1. **No credential exposure.** Managed identity tokens, bearer tokens, and storage credentials are never included in HTTP responses, response headers, error messages, or client-visible logs.

2. **No SAS tokens.** The system never generates Shared Access Signature URLs. All blob access is proxied through the application using its RBAC identity.

3. **No raw blob URIs to the browser.** Internal blob storage URIs (e.g., `https://<account>.blob.core.windows.net/...`) are never included in any client-facing response, including error messages and response headers.

4. **Bounded output.** Every download request has an enforced output size limit. Vector exports enforce a feature count cap. Raster crops enforce a maximum bbox area or estimated output size. Requests exceeding limits receive a `400` with actionable guidance.

5. **Terminal completion.** Every download request reaches a terminal state — either a fully streamed file or a structured error response. No silent failures, no partial files, no hung connections.

6. **STAC href canonicality.** The `asset_href` parameter accepted by download endpoints is the same value stored in STAC item assets. The system does not maintain a separate asset registry.

---

## NON-FUNCTIONAL REQUIREMENTS

### Performance

- Responses are streamed. The application does not buffer entire files (raster or vector) in memory.
- Raster crop is always synchronous (no job queue). The max bbox/size limit ensures bounded processing time within the 240-second request timeout.
- Vector subset queries should leverage spatial indexes in PostGIS for bbox filtering.

### Reliability

- Downstream service failures (TiTiler unavailable, PostgreSQL unreachable, blob storage errors) must produce structured error responses with identifiable error categories — not generic 500s with stack traces.
- The 240-second Container Apps request timeout is the hard upper bound on request duration. The system should fail gracefully before this limit rather than letting the platform kill the connection.

### Security

- All download endpoints require authentication (enforced by platform via Easy Auth).
- No temporary credentials, tokens, or signed URLs are ever generated or exposed.

### Observability

- Every completed download: log collection ID, bbox (if applicable), output format, byte count, feature count (vector), request duration.
- Every error: log error category, originating downstream service, request parameters.
- Threshold breaches (approaching feature cap, large bbox approaching limit): log at WARNING.
- Logs must enable production debugging by an operator without access to source code.

---

## INFRASTRUCTURE CONTEXT

- **Runtime**: Azure Container Apps (Linux containers). Python application.
- **Scaling**: Automatic horizontal scaling based on HTTP concurrency. Minimum 1 replica.
- **Memory**: 1–4 GB per replica. GDAL raster operations and large vector serialization are memory-intensive.
- **Network**: Outbound connectivity to blob storage, PostgreSQL, and TiTiler within the same VNET or via private endpoints. TiTiler is a separate container app in the same environment.
- **Request timeout**: 240 seconds (Container Apps default). Long-running raster crops or large vector exports can approach this.
- **Token lifecycle**: Bearer tokens for blob storage expire after 60 minutes. PostgreSQL tokens also expire and must be refreshed.
- **Blob storage**: ADLS Gen2 with hierarchical namespace. COGs with internal tiling and overviews. Private access only (no anonymous read).
- **PostgreSQL**: Azure Database for PostgreSQL Flexible Server. Extensions: PostGIS, pgSTAC. Managed identity authentication (no passwords).
- **Environments**: QA is active. Naming convention: `gddatahubext*qa` (external-facing), `gddatahubetl*qa` (ETL).

---

## EXISTING SYSTEM CONTEXT

### TiTiler
Dynamic raster tile server running as a separate container app. Exposes HTTP endpoints for bounding-box raster extraction from COGs (e.g., `/cog/crop`). Reads COGs directly from private blob storage using GDAL with bearer token authentication. The download initiator delegates raster crop operations to TiTiler via internal HTTP calls — it never opens raster files directly.

### PostGIS
Azure Database for PostgreSQL Flexible Server hosting authoritative vector datasets loaded by the ETL pipeline. Contains spatial tables with PostGIS geometry columns and spatial indexes. Authenticated via managed identity (no passwords).

### pgSTAC
STAC catalog on the same PostgreSQL instance. Stores STAC items whose `asset.href` values point to COG blob URIs and OGC API Features endpoints. These hrefs are the canonical reference that the download initiator resolves.

### TiPG
OGC API Features server exposing PostGIS tables as feature collections. Provides collection metadata (table names, schemas, spatial extents). The download initiator's `collection_id` values match TiPG collection identifiers.

### Azure Blob Storage
ADLS Gen2 with hierarchical namespace. Stores COGs and other raster assets. Private access only — requires managed identity with Storage Blob Data Contributor role.

### Azure Easy Auth
Platform-enforced authentication. Validates Azure AD JWTs before requests reach the application. Populates `X-MS-CLIENT-PRINCIPAL` headers with user identity and group membership claims.

### Managed Identities
- System-assigned MI on the container app — for blob storage access (Storage Blob Data Contributor).
- User-assigned MI — for PostgreSQL access via Azure AD authentication.

### ETL Pipeline
Azure Functions-based ETL that processes source files into PostGIS tables and COGs in blob storage. Uses PostgreSQL job/task tables for state management. The download initiator reads ETL outputs but does not interact with the ETL directly.

### Existing Job/Task Tables
PostgreSQL tables used by the ETL pipeline for job state management with advisory locks. Available for async job tracking if needed in future phases.

---

## OPEN QUESTIONS

1. **Filename convention.** Auto-generated filenames for `Content-Disposition` headers need a sensible default. Should encode collection_id, human-readable bbox approximation (not full precision coords), generation date. No UUIDs, no spaces, no special characters. User can override via `filename` parameter. What is the right convention that makes files identifiable in a Downloads folder weeks later without being absurdly long?

2. **TiTiler crop endpoint specifics.** What is the exact TiTiler endpoint signature for bounding-box crop, including query parameters for CRS, resolution, and the source asset URL? Does TiTiler return a streaming response or a buffered response? This affects whether the download initiator can truly stream end-to-end or must buffer TiTiler's response.

3. **CSV geometry handling.** For vector subset download with `format=csv`, how should geometry columns be represented? Options: WKT column, separate lat/lon columns (points only), centroid lat/lon (non-points), or geometry omission. Different downstream consumers have different expectations.

4. **Concurrent download limits.** Should there be per-user or global rate limiting on downloads to prevent a single user from saturating outbound bandwidth or database connection pools? If so, what are reasonable thresholds?

