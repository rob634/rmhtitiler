# Greenfield Pipeline Briefing: Browser Download Initiator

## Tier 1: System Context

_Facts about the environment. Goes to S → A, C, O._

---

### What This Component Does

The Browser Download Initiator is a routing and streaming layer within the DDHGeo platform that enables authenticated browser users to download geospatial data subsets. It acts as an authorized proxy: resolving internal storage resources, delegating processing to specialized services (TiTiler for raster, PostGIS for vector), and streaming results back to the browser as downloadable files.

The key insight is that 90% of download use cases are not "give me the entire 5 GB file" — they are "give me the flood extent for this bounding box." This component formalizes that pattern across both raster and vector data, so users with only a browser can get what they need without Python, QGIS, or direct blob access.

### What It Connects To

**Upstream (sends requests to this component):**
- Browser clients authenticated via Azure Easy Auth (JWT). Easy Auth is enforced at the platform level before requests reach the application.

**Downstream (this component sends requests to):**
- **TiTiler** — Dynamic raster tile server. Deployed as a container app in the same environment. Exposes `/cog/crop/{bbox}.tif` for bounding-box raster extraction from Cloud-Optimized GeoTIFFs (COGs) in Azure Blob Storage. TiTiler reads COGs directly from private blob storage using GDAL, which authenticates via a bearer token in `os.environ`.
- **PostGIS** (Azure Database for PostgreSQL Flexible Server, external instance: `itses-gddatahub-ext-pgsqlsvr-qa`) — Holds authoritative vector datasets loaded by the ETL pipeline. Queried via `asyncpg` using managed identity authentication. Also exposed as OGC API Features collections via TiPG.
- **Azure Blob Storage** (ADLS Gen2 with HNS) — Stores COGs and other raster assets. Accessed by TiTiler/GDAL transparently via bearer token in environment variables. Also accessed directly by this component for SAS URL generation.
- **PostgreSQL jobs table** — For async job tracking. Same PostgreSQL instance, existing job/task state management pattern from the ETL pipeline.

### What Already Exists

- **DDHGeo ETL pipeline** — Azure Functions-based ETL that processes vector files (CSV, GPKG, KML, KMZ, Shapefile, GeoJSON) into PostGIS tables, and raster files into COGs in blob storage. Uses Service Bus orchestration with PostgreSQL state management ("accidental durable functions" pattern with advisory locks).
- **STAC catalog** (pgSTAC on external PostgreSQL) — Catalogs processed ETL outputs. STAC items contain `asset.href` values pointing to COG blob URIs and OGC API Features endpoints. The download initiator resolves these hrefs.
- **TiPG** — OGC API Features server that exposes PostGIS tables as feature collections. Deployed as a container app. Provides collection metadata and feature serving.
- **Azure Easy Auth** — Platform-enforced authentication. Validates Azure AD JWTs before requests reach the application. All users hitting the download endpoints are pre-authenticated.
- **Managed identities:**
  - System-assigned MI on the container app — for blob storage access (Storage Blob Data Contributor).
  - User-assigned MI (`migeoeextdbadminqa`) — for PostgreSQL access via `azure_ad` plugin. No passwords.
- **Existing job/task tables in PostgreSQL** — The ETL pipeline already uses PostgreSQL tables for job state management with advisory locks for distributed coordination.

### What It Must Guarantee

1. **No direct blob access for browser users.** The raw blob URI is never exposed to the client. All data flows through the app as proxy. No SAS tokens are generated — the app streams blob content using its own RBAC identity.
2. **Credential isolation.** Managed identity tokens are never sent to the browser. No temporary access tokens (SAS or otherwise) are exposed to the client under any circumstances.
3. **Authorization via security group membership.** Collection-level access is controlled by Azure AD security group membership. No ACLs — ACLs are an explicitly forbidden anti-pattern.
4. **Bounded output size.** Vector exports enforce a hard feature cap (configurable via environment variable, default 100,000). Raster crops enforce a max bbox area or estimated output size (configurable via environment variable); oversized requests return a 400 with an actionable error body directing the user to the full asset download endpoint. The system must not allow unbounded memory consumption from a single request.
5. **Every download request must either complete with a streamed file or return an actionable error.** No silent failures, no hung connections. Oversized raster crop requests return a 400 with the `/asset/download` URL and the user's original `asset_href`.
6. **STAC asset hrefs are the canonical reference.** The download initiator resolves the same `asset_href` values stored in STAC items — it does not maintain a separate asset registry.

### Infrastructure Profile

- **Runtime:** Azure Container Apps (Linux containers). The DDHGeo application runs as a Python container app.
- **Scaling:** Container Apps support automatic horizontal scaling based on HTTP request concurrency. Minimum 1 replica, scales to configured maximum.
- **Cold starts:** Container Apps have warm instances; cold start is possible but mitigated by minimum replica count.
- **Memory:** Container app memory is configurable per revision (typically 1–4 GB per replica). GDAL raster operations and large vector serialization are memory-intensive.
- **Network:** Container app has outbound connectivity to blob storage, PostgreSQL, and TiTiler (all within the same VNET or accessible via private endpoints). TiTiler is a separate container app in the same environment.
- **Token lifecycle:** Azure IMDS bearer tokens for blob storage expire after 60 minutes. PostgreSQL tokens also expire and must be refreshed.
- **Request timeout:** Container Apps default HTTP request timeout is 240 seconds. Long-running raster crops or large vector exports can approach this.
- **Blob storage:** ADLS Gen2 with hierarchical namespace. COGs stored with internal tiling and overviews. Private access only (no anonymous read).
- **PostgreSQL:** Azure Database for PostgreSQL Flexible Server. External instance for STAC/vector serving. Extensions: PostGIS, pgSTAC. Connection pooling via asyncpg.
- **Existing environments:** QA environment is active. Resources follow naming convention: `gddatahubext*qa` for external-facing, `gddatahubetl*qa` for ETL.

---

## Tier 2: Design Constraints

_Settled architectural decisions. Held back from A, C, O. Goes ONLY to M and B._

---

### Settled Architectural Patterns

**Authentication:**
- Azure Easy Auth enforced at the platform level. The app never validates JWTs itself — it trusts the platform layer. By the time a request reaches application code, `X-MS-CLIENT-PRINCIPAL` headers are populated.
- Blob storage auth: System-assigned managed identity fetches a bearer token from IMDS, written to `os.environ` as `GDAL_HTTP_BEARER_TOKEN` (and `AZURE_STORAGE_ACCESS_TOKEN`). Refreshed every 45 minutes via a background scheduler (APScheduler). All GDAL operations (TiTiler, rasterio) authenticate transparently.
- PostgreSQL auth: User-assigned managed identity (`migeoeextdbadminqa`) authenticates via the `azure_ad` plugin. Token fetched from IMDS at connection pool creation, passed as password to asyncpg.

**Data access:**
- Vector data: All vector queries go through `asyncpg` connection pool to the external PostgreSQL instance. No ORM — raw SQL with parameterized queries.
- Raster data: TiTiler handles all raster I/O via GDAL. The download initiator delegates to TiTiler's HTTP endpoints (internal container-to-container call), never opens raster files directly.
- STAC metadata: pgSTAC functions on the external PostgreSQL instance. Asset hrefs in STAC items are the canonical source for blob URIs.

**Configuration:**
- Environment variables for all connection strings, hostnames, and feature flags. No hardcoded values.
- Managed identity client IDs configured as environment variables where needed.
- Token refresh intervals, size thresholds, and feature limits are configuration values, not code constants.

**Error handling:**
- Standard HTTP status codes with JSON error bodies. The existing pattern uses `{"detail": "...", "status": <code>}` shape.
- GDAL errors are caught and translated to 422 Unprocessable Entity with the GDAL error message in the `detail` field.
- All errors are logged with structured logging (Python `logging` module with JSON formatter).

### Integration Rules

- **TiTiler delegation is HTTP-based.** The download initiator constructs TiTiler URLs and makes internal HTTP calls (container-to-container within the Container Apps environment). It does not import TiTiler as a library or call its functions directly.
- **Job state uses the existing PostgreSQL jobs pattern.** The ETL pipeline already has job/task state tables with status tracking. Async downloads should use the same pattern (or a compatible extension of it), not a separate queue or state store.
- **Full asset download is a proxied stream, not a SAS redirect.** The app reads the blob using `azure-storage-blob` SDK with system MI credentials and streams the bytes to the browser response via `StreamingResponse`. No SAS generation, no token exposure.
- **All blob URIs follow the STAC asset href format.** The `asset_href` parameter in download requests is the same value stored in STAC item assets. The app resolves it to a full authenticated URL internally.
- **Vector export formats are GeoJSON and CSV (P1), GPKG (P2).** GeoParquet is deferred to a future phase beyond P2.

### Anti-Patterns

- **Never expose raw blob URIs to the browser.** Even in error messages or response headers. The `X-Source-Asset` header must be sanitized (no tokens, no SAS, no full storage paths).
- **Never generate SAS tokens.** No SAS URLs of any kind — OIS (InfoSec) will not accept exposed tokens. All blob downloads are proxied through the app using RBAC identity. The `/asset/sas` endpoint from early designs is eliminated; replaced by `/asset/download` which streams via the app.
- **Never use ACLs.** Authorization is exclusively via Azure AD security group membership. ACLs are an explicitly forbidden pattern in this system.
- **Never import TiTiler as a Python library.** Always delegate via HTTP. TiTiler runs as its own container app with its own scaling.
- **Never use passwords or client secrets for database access.** Only managed identity tokens.
- **Never hold an entire raster file in memory.** GDAL and TiTiler stream COG tiles; the download initiator streams the response. No `BytesIO` accumulating a full file.
- **Never use synchronous database calls.** All PostgreSQL access is via asyncpg (async).

### Conventions

- **Data contracts:** Pydantic v2 models for request/response validation.
- **Naming:** Snake_case for Python, kebab-case for URL paths. Collection IDs match PostGIS table names as exposed by TiPG.
- **Logging:** Python `logging` with structured JSON output. Log levels: DEBUG for request tracing, INFO for completed downloads with metadata (collection, bbox, format, byte count), WARNING for threshold breaches (approaching limits), ERROR for failures.
- **Response headers:** Custom `X-` headers for traceability (source asset, feature count, truncation status, byte count). Standard `Content-Disposition` for downloads.
- **Filename convention (open):** Auto-generated filenames should encode `{collection_id}_{bbox_hash}_{timestamp}.{ext}`. Exact convention TBD — the open question from the design doc.

---

## Open Questions (Carried from Design Doc)

These are unresolved decisions that M should address or explicitly defer:

1. **Collection-level authorization: RESOLVED.** Security group membership via Azure AD. No ACLs anywhere in the system — ACLs are explicitly forbidden as an anti-pattern.
2. **Async output staging: RESOLVED.** Repos and existing codebase for container/blob management are available. Dedicated temp blob container with TTL policy for staged async outputs — infra creation is assumed available.
3. **Hard limit on vector export: RESOLVED.** Configurable via environment variable. Default 100,000 features. Not per-collection — single global env var.
4. **Parquet streaming: DEFERRED (future-future).** GeoParquet export is out of scope for this build and the next. Remove from P1 vector export formats. Supported formats are GeoJSON and CSV only (GPKG remains P2).
5. **Full asset download: REDESIGNED.** No SAS token generation — InfoSec (OIS) will not accept exposed tokens. Instead, the app proxies the full blob download using its system MI RBAC access (Storage Blob Data Contributor). The app reads the blob via Azure SDK and streams bytes directly to the browser response. The blob URI never leaves the server, no temporary tokens are created. This is architecturally consistent with the raster crop pattern (app-as-authorized-proxy). Tradeoff: bytes flow through the app, adding load, but security posture is clean. The `/asset/download` endpoint replaces `/asset/sas`.
6. **Sync/async size estimation for raster: RESOLVED.** Raster crop is always synchronous. A max bbox area or estimated output size is enforced via environment variable. Requests exceeding the threshold return a 400 with an actionable error body that includes the `/api/download/asset/download` URL and the user's original `asset_href`, directing them to the full asset download endpoint. No async job infrastructure is needed for raster crops. Async jobs are deferred to P2/P3 use cases (GPKG export, Zarr slicing).
7. **Filename conventions: OPEN.** Auto-generated filenames for `Content-Disposition` headers need a sensible default. User can override via `filename` parameter. The convention should make files identifiable in a Downloads folder weeks later without being absurdly long. Agents should propose a convention. Considerations: collection_id, human-readable bbox approximation (not full precision coords), generation date, no UUIDs, no spaces or special characters.
