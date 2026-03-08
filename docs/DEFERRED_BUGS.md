# Deferred Bugs — Architecture Review Required

Bugs identified by ETL Claude's API test report (2026-03-07) that require investigation beyond simple code fixes.

Source: `https://github.com/rob634/geoetl/blob/main/GEOTILER_API_TEST_REPORT.md`

---

## BUG-002: bbox filtering returns 500 on all collections

**Severity:** CRITICAL
**Affects:** `GET /vector/collections/{id}/items?bbox=...` — every collection, every geometry type
**Impact:** Blocks spatial queries, map-driven browsing, QGIS viewport filtering

**Error:**
```
function st_transform(unknown, integer) is not unique
HINT: Could not choose a best candidate function. You might need to add explicit type casts.
```

**Root cause:** PostgreSQL cannot disambiguate `ST_Transform()` overloads when both `postgis` (geometry) and `postgis_raster` extensions are installed. TiPG's internal SQL passes parameters with unresolved types.

**Investigation needed:**
1. Check installed extensions: `SELECT extname, extversion, extnamespace::regnamespace FROM pg_extension WHERE extname LIKE 'postgis%';`
2. Check if `postgis_raster` can be dropped (not needed for vector tile serving)
3. If raster extension is needed, check if `search_path` ordering resolves the ambiguity
4. Check TiPG upstream for known issues with Azure PostgreSQL Flexible Server
5. Consider explicit cast in TiPG's bbox SQL: `ST_Transform(geom::geometry, srid)`

**Potential fixes (ordered by preference):**
1. **TiPG upstream fix** — TiPG should cast `ST_MakeEnvelope(...)::geometry` explicitly. Check if newer TiPG versions fix this, or file a GitHub issue at `developmentseed/tipg`
2. Check if `search_path` ordering can resolve the ambiguity (geometry functions in `public` should be found first)
3. Add a database-level wrapper function that forces the geometry overload

---

## BUG-003: Item not found returns 500 instead of 404

**Severity:** MEDIUM
**Affects:** `GET /vector/collections/{id}/items/{itemId}` when item doesn't exist

**Response body correctly says `"code":"NotFound"` but HTTP status is 500 instead of 404.**

**Root cause:** TiPG raises exceptions that are not caught by TiTiler's `add_exception_handlers(app, DEFAULT_STATUS_CODES)`. TiPG has its own exception hierarchy (likely `tipg.errors.NotFoundError` or similar) that needs separate handler registration.

**Investigation needed:**
1. Identify TiPG's exception classes: `python3 -c "import tipg.errors; print(dir(tipg.errors))"`
2. Check if TiPG provides its own `add_exception_handlers` utility
3. Register TiPG exception handlers alongside TiTiler's in `app.py:323`

---

## BUG-004: Client errors return 500 instead of 4xx

**Severity:** MEDIUM
**Affects:** Multiple TiPG endpoints (CQL parse errors, invalid collections)

**Examples:**
- CQL parse error → 500 (should be 400)
- Non-existent collection → 422 (should be 404)

**Root cause:** Same as BUG-003 — TiPG exceptions not registered with FastAPI's exception handler system.

**Investigation needed:** Same as BUG-003. Likely a single fix (registering TiPG exception handlers) resolves both.

---

## PERF-001: Intermittent timeouts on data-fetching endpoints

**Severity:** MEDIUM (operational)
**Affects:** COG point queries, COG preview, COG bbox image, vector diagnostics

**Observations:**
- RAM at 92.6% utilization on Premium0V3 (4.68GB)
- COG tiles at z=8 and z=11 work; z=9 and z=10 timeout
- Point queries, preview, and bbox image endpoints timeout

**Possible causes:**
- Azure App Service front-end timeout (240s default but load balancer may be lower)
- Remote COG overview reads at intermediate zoom levels hitting slow S3 range requests
- Memory pressure causing GC pauses

**Not a code bug** — infrastructure/scaling concern. Consider:
1. Upgrading SKU if memory pressure is confirmed
2. Adding request timeout configuration to TiTiler
3. Caching frequently accessed COG overviews

---

## BUG-005: xarray empty responses (NOT A BUG)

**Reported as:** xarray endpoints return empty responses when tested with public HTTPS URLs

**Actual behavior:** This is by design. The xarray endpoints require `abfs://` URLs for authenticated Azure Blob Storage access. Public `https://` URLs route to anonymous HTTPFileSystem which cannot access private containers. The ETL test report tested with a public Pangeo URL that may have been unreachable or incompatible.

**No fix needed.** Documented in `ZARR_NOTES.md` in the rmhgeoapi project.
