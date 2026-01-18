# Application Review - rmhtitiler

**Review Date:** 2026-01-18
**Reviewer:** Claude Code Analysis
**Version Reviewed:** 0.7.11.0

---

## Overview

**rmhtitiler** is a production-ready geospatial tile server built on TiTiler, designed for Azure App Service deployment. It integrates multiple data access patterns:

| Component | Purpose |
|-----------|---------|
| **COG Tiles** | Cloud Optimized GeoTIFF serving via GDAL |
| **Zarr/NetCDF** | Multidimensional array tiles via xarray |
| **pgSTAC Mosaics** | Dynamic tiling from STAC catalog searches |
| **TiPG** | OGC Features API + Vector Tiles from PostGIS |
| **STAC API** | STAC catalog browsing and search |
| **Planetary Computer** | Climate data integration |

The architecture is solid overall, with proper lifespan management, health endpoints, and background token refresh for Azure Managed Identity.

---

## Issues Identified

### 1. Synchronous Blocking in Async Context

**Severity:** High
**Location:** `geotiler/middleware/azure_auth.py:37`

```python
async def dispatch(self, request: Request, call_next):
    token = get_storage_oauth_token()  # Synchronous call!
```

**Explanation:**
The `get_storage_oauth_token()` function makes synchronous HTTP calls to Azure's token endpoint, but it's called from within an async middleware. When a token needs to be refreshed, this blocks the entire event loop, preventing all other requests from being processed. In a high-traffic scenario, this can cause request queuing and timeouts. The function should either be made async using `aiohttp` or run in a thread pool using `asyncio.to_thread()`.

---

### 2. Global Mutable State Singletons

**Severity:** Medium
**Locations:**
- `geotiler/services/background.py:20` - `_app: "FastAPI" = None`
- `geotiler/services/database.py:17` - `_app_state: Optional[Any] = None`
- `geotiler/routers/vector.py:97` - `tipg_startup_state = TiPGStartupState()`

**Explanation:**
Multiple modules use module-level global variables that are mutated at runtime. This pattern creates several problems:

1. **Testing difficulty** - Unit tests can't run in isolation because global state persists between tests
2. **Hidden dependencies** - Functions depend on global state being set correctly by other code
3. **Race conditions** - In multi-worker deployments, each worker has its own copy, but within a worker, concurrent requests could see inconsistent state
4. **Initialization order** - Code must be called in a specific order or it fails silently

A better approach would be dependency injection via FastAPI's dependency system or storing state exclusively in `app.state`.

---

### 3. Environment Variable Mutation

**Severity:** Medium
**Location:** `geotiler/auth/storage.py:101-102`

```python
os.environ["AZURE_STORAGE_ACCOUNT"] = settings.azure_storage_account
os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
```

**Explanation:**
Directly mutating `os.environ` is a global side effect that affects all code in the process. This is problematic because:

1. **Process-wide impact** - All threads and async tasks see the same environment
2. **Race conditions** - If two requests try to configure different storage accounts simultaneously, they'll overwrite each other
3. **No cleanup** - Old values persist if not explicitly removed
4. **Testing pollution** - Environment changes leak between tests

For GDAL specifically, consider using `rasterio.Env()` context managers which provide thread-local configuration, or pass credentials via the URL/path itself.

---

### 4. Threading Lock in Async Code

**Severity:** Medium
**Location:** `geotiler/auth/cache.py:34`

```python
@dataclass
class TokenCache:
    _lock: Lock = field(default_factory=Lock, repr=False)
```

**Explanation:**
The `TokenCache` class uses `threading.Lock` for synchronization, but the application is primarily async. While this works because the lock operations are very fast (just reading/writing memory), there are subtle issues:

1. **Blocking potential** - If any operation inside the lock becomes slow, it blocks the event loop
2. **Inconsistent model** - Mixing threading primitives with async code is confusing
3. **Deadlock risk** - If async code yields while holding the lock and the same coroutine tries to reacquire it, deadlock occurs

For async-first code, `asyncio.Lock` is the appropriate primitive. Alternatively, since Python's GIL makes simple attribute access atomic, the locks may be unnecessary for this use case.

---

### 5. ~~Overly Permissive CORS Configuration~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-18

**Resolution:** CORS middleware removed from FastAPI. CORS is now handled by infrastructure:
- **External traffic**: Cloudflare WAF + CDN
- **Internal traffic**: Azure APIM

The application no longer needs to manage cross-origin access since it runs behind reverse proxies that handle security policies at the infrastructure level.

---

### 6. Error Swallowing in Query Helpers

**Severity:** Medium
**Location:** `geotiler/routers/diagnostics.py:32-39`

```python
async def _run_query(pool, query: str, *args) -> list[dict]:
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return []  # Silent failure
```

**Explanation:**
Returning an empty list on query failure makes it impossible for callers to distinguish between "query succeeded but returned no rows" and "query failed completely." This leads to:

1. **Silent failures** - Errors are logged but not surfaced to users
2. **Incorrect diagnostics** - A failed permission check looks like "no tables found"
3. **Debugging difficulty** - Users see empty results with no indication something went wrong

Better approaches:
- Return `Optional[list[dict]]` with `None` indicating failure
- Raise exceptions and let callers handle them
- Return a result object with success/failure status

---

### 7. God Function - Verbose Diagnostics

**Severity:** Low
**Location:** `geotiler/routers/diagnostics.py:445-1000`

**Explanation:**
The `verbose_diagnostics` endpoint is approximately 550 lines long and executes 15+ sequential database queries. This violates the Single Responsibility Principle and creates several problems:

1. **Timeout risk** - Sequential queries on a slow database could exceed HTTP timeouts
2. **Untestable** - Can't unit test individual diagnostic checks
3. **Hard to maintain** - Changes to one query risk breaking others
4. **All-or-nothing** - Can't get partial results if one query fails

Consider breaking this into smaller functions, each responsible for one diagnostic category (permissions, geometry registration, schema info, etc.). The endpoint could then orchestrate these and potentially run them in parallel.

---

### 8. Duplicated CSS Across Landing Pages

**Severity:** Low
**Location:**
- `geotiler/routers/cog_landing.py:16-174`
- `geotiler/routers/xarray_landing.py`
- `geotiler/routers/searches_landing.py`

**Explanation:**
The exact same ~170 lines of CSS are copy-pasted into three separate landing page files. This violates the DRY (Don't Repeat Yourself) principle:

1. **Maintenance burden** - Style changes must be made in 3 places
2. **Inconsistency risk** - Easy to update one file and forget others
3. **Code bloat** - Unnecessary duplication inflates codebase size

Solutions:
- Extract CSS to a shared module/constant
- Use Jinja2 templates with a base template
- Serve CSS as a static file and reference it

---

### 9. Mixed Sync/Async Database Access

**Severity:** Low
**Location:** `geotiler/services/database.py:56-79`

```python
def ping_database() -> Tuple[bool, Optional[str]]:  # Synchronous!
    pool = get_db_pool()
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
```

**Explanation:**
The `ping_database()` function is synchronous while most other database code in the application uses async/await. This inconsistency:

1. **Blocks event loop** - Health checks block all other requests while executing
2. **Confusing API** - Developers must remember which functions are sync vs async
3. **Different connection pools** - Uses psycopg sync pool while TiPG uses asyncpg

The function exists because titiler-pgstac uses psycopg (sync) while TiPG uses asyncpg (async). Consider using the async pool for health checks, or documenting why two pools are necessary.

---

### 10. Excessive Logging Noise

**Severity:** Low
**Location:** Throughout codebase

```python
logger.info("=" * 60)
logger.info("Acquiring Azure Storage OAuth token...")
logger.info("=" * 60)
```

**Explanation:**
Banner-style logging with separator lines appears dozens of times throughout the codebase. While helpful during development and debugging, this creates problems in production:

1. **Log volume** - Increases storage costs and makes log analysis slower
2. **Signal-to-noise** - Important messages get lost in decorative banners
3. **Parsing difficulty** - Multi-line log entries are harder to parse with log aggregators
4. **Inconsistent levels** - Many INFO logs would be better as DEBUG

Consider:
- Moving verbose logs to DEBUG level
- Using structured logging (JSON) for machine parsing
- Reserving banners for truly exceptional events (startup/shutdown only)

---

### 11. Hardcoded Sample URLs

**Severity:** Low
**Location:** `geotiler/routers/cog_landing.py:266-272`

```python
<code onclick="setUrl('https://data.geo.admin.ch/...')">
    Swiss Terrain (SRTM) - data.geo.admin.ch
</code>
```

**Explanation:**
Sample URLs for demo purposes are hardcoded directly in the HTML templates. Issues:

1. **Brittleness** - External URLs can change or become unavailable
2. **No customization** - Can't configure different samples per environment
3. **Maintenance** - Must redeploy to update sample URLs

Consider loading sample URLs from configuration or a separate data file that can be updated without code changes.

---

### 12. Missing Type Annotations

**Severity:** Low
**Location:** `geotiler/services/database.py:17, 44`

```python
_app_state: Optional[Any] = None

def get_db_pool() -> Optional[Any]:
```

**Explanation:**
Using `Any` as a type annotation provides no type safety - it's essentially opting out of type checking. This makes it harder for IDEs to provide autocomplete and for type checkers to catch bugs.

The actual types are known:
- `_app_state` is `starlette.datastructures.State`
- `get_db_pool()` returns `psycopg_pool.ConnectionPool`

Adding proper types improves code documentation and catches errors at development time rather than runtime.

---

## Positive Patterns

The codebase demonstrates several good practices worth preserving:

| Pattern | Location | Notes |
|---------|----------|-------|
| **Pydantic Settings** | `config.py` | Clean configuration with validation and defaults |
| **Health Endpoint Stratification** | `routers/health.py` | Proper `/livez`, `/readyz`, `/health` Kubernetes pattern |
| **Degraded Mode** | `app.py:165-176` | App starts even if database connection fails |
| **Token Caching** | `auth/cache.py` | Proactive refresh prevents mid-request expiration |
| **Lifespan Context Manager** | `app.py:60-111` | Modern FastAPI pattern for startup/shutdown |
| **Comprehensive Diagnostics** | `routers/diagnostics.py` | Excellent for debugging without direct DB access |
| **Feature Flags** | `config.py:90-116` | Clean enable/disable for optional components |

---

## Summary Table

| # | Issue | Severity | Effort to Fix | Impact |
|---|-------|----------|---------------|--------|
| 1 | Sync blocking in async | **High** | Medium | Event loop blocking |
| 2 | Global mutable state | Medium | High | Testing, race conditions |
| 3 | Environment mutation | Medium | Medium | Race conditions |
| 4 | Threading lock in async | Medium | Low | Potential deadlocks |
| 5 | ~~CORS misconfiguration~~ | ~~Medium~~ | ✅ Fixed | ~~Security~~ |
| 6 | Error swallowing | Medium | Low | Debugging difficulty |
| 7 | God function | Low | Medium | Maintainability |
| 8 | CSS duplication | Low | Low | Maintainability |
| 9 | Mixed sync/async DB | Low | Medium | Consistency |
| 10 | Excessive logging | Low | Low | Log noise |
| 11 | Hardcoded URLs | Low | Low | Brittleness |
| 12 | Missing types | Low | Low | Type safety |

---

## Recommended Priority

Based on severity and effort, suggested order of fixes:

1. ~~**CORS misconfiguration** (#5)~~ ✅ Fixed - Removed, handled by infrastructure
2. **Sync blocking in async** (#1) - Highest impact on performance
3. **Error swallowing** (#6) - Improves debugging significantly
4. **Threading lock** (#4) - Low effort, prevents subtle bugs
5. **Environment mutation** (#3) - Medium effort, improves correctness
6. **Global mutable state** (#2) - Larger refactor, but improves testability
7. **CSS duplication** (#8) - Extract shared styles for maintainability

Items 9-12 can be addressed opportunistically during other work.
