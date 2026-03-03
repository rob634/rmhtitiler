# Download Initiator — Tier 2 Design Constraints

Settled architectural decisions held back from A, C, O. Given only to M and B.

## Settled Architectural Patterns

**Authentication:**
- Azure Easy Auth enforced at platform level. App trusts `X-MS-CLIENT-PRINCIPAL` headers.
- Blob storage auth: System MI fetches bearer token from IMDS → `os.environ["GDAL_HTTP_BEARER_TOKEN"]`. Refreshed every 45min via APScheduler. Cache in `geotiler/auth/cache.py`.
- PostgreSQL auth: User-assigned MI (`migeoeextdbadminqa`) authenticates via `azure_ad` plugin. Token passed as password to asyncpg.

**Data access:**
- Vector: asyncpg connection pool, raw SQL, parameterized queries. No ORM.
- Raster: TiTiler handles all raster I/O via GDAL. Download initiator delegates, never opens rasters directly.
- STAC: pgSTAC on external PostgreSQL. Asset hrefs are canonical.

**CRITICAL: TiTiler is in-process.** Despite the briefing describing a "separate container app," TiTiler is embedded in the app (`app.py` imports `TilerFactory`). HTTP loopback to localhost will deadlock (single uvicorn worker). Use ASGI transport for in-process HTTP-like delegation.

**Configuration:**
- `GEOTILER_COMPONENT_SETTING` convention, `env_prefix="GEOTILER_"` in Pydantic Settings.
- Boolean flags: `GEOTILER_ENABLE_*`. Time values: `_SEC`, `_MS`.

**Error handling:**
- `{"detail": "...", "status": <code>}` shape.
- GDAL errors → 422.
- Structured logging via Python `logging` with JSON formatter.

**Existing modules:**
- `geotiler/auth/cache.py` — storage_token_cache
- `geotiler/services/database.py` — DB pool management
- `geotiler/config.py` — GeoTilerSettings (Pydantic Settings)
- `geotiler/app.py` — Main app, router mounting, lifespan

## Private Design Constraints (Developer Directives)

- **SAS tokens are negotiable.** Short-lived, scoped, read-only User Delegation SAS tokens (signed by MI) are acceptable if proxy proves untenable. Deferred to P2.
- **Proxy download size limit required.** Configurable max file size for proxied full-asset downloads.
- **Collection-level authorization deferred.** No security group checks in P1.

## Multi-Instance Deployment Context

The application runs on Azure Container Apps with horizontal auto-scaling (multiple replicas). Design implications:

- **All download endpoints are stateless.** No coordination between instances required.
- **`asyncio.Semaphore` is per-instance.** This is intentional — each instance protects its own memory/connections. Global concurrency = `N instances × semaphore_limit`.
- **Aggregate database connections = N instances × pool_size.** Monitor against PostgreSQL `max_connections`. With 5+ instances at pool_size=20, total connections approach 100+.
- **SAS tokens (P2) scale better than proxy.** Proxy ties up instance bandwidth/memory for entire download duration. SAS frees the instance in milliseconds (auth check + token generation + redirect). Multi-instance amplifies this advantage.

## Anti-Patterns

- Never expose raw blob URIs to browser
- Never use ACLs
- Never use passwords/client secrets for DB access
- Never hold entire raster in memory
- Never use synchronous database calls

## Conventions

- Pydantic v2 models for request/response validation
- Snake_case Python, kebab-case URLs
- Collection IDs match TiPG/PostGIS table names
- Custom `X-` headers for traceability
