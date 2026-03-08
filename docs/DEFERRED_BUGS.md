# ETL Claude API Test Report — Bug Triage & Resolution

Bugs identified by ETL Claude's API test report (2026-03-07), triaged and resolved 2026-03-08.

Source: `https://github.com/rob634/geoetl/blob/main/GEOTILER_API_TEST_REPORT.md`

---

## Resolved Bugs

### BUG-001: Landing pages return 500 (swagger_ui_html route missing) — FIXED

**Severity:** CRITICAL
**Affected:** `/vector/`, `/stac/`
**Fix:** Added `name="swagger_ui_html"` to the custom `/docs` route in `app.py:426`.
**Root cause:** FastAPI was initialized with `docs_url=None` (to use a custom Swagger UI with a `requestInterceptor` for double-encoding fixes). This prevented registration of the default route name `swagger_ui_html`. TiPG and stac-fastapi landing page templates call `url_for('swagger_ui_html')` to generate the API documentation link, which threw `NoMatchFound`.
**Deployed:** v0.9.3.0, verified `/vector/` and `/stac/` return HTTP 200 with proper OGC/STAC landing page JSON.

### BUG-002: bbox filtering returns 500 on all collections — FIXED

**Severity:** CRITICAL
**Affected:** `GET /vector/collections/{id}/items?bbox=...` — every collection, every geometry type
**Fix:** Dropped unused `postgis_raster` extension from Azure PostgreSQL Flexible Server.
**Root cause:** See [TIPG_BBOX_ISSUE.md](TIPG_BBOX_ISSUE.md) for full analysis. TiPG 1.3.1's bbox SQL calls `ST_Transform()` without explicit type casting. When both `postgis` and `postgis_raster` extensions are installed, PostgreSQL has two `ST_Transform` overloads (`geometry` and `raster` variants) and cannot disambiguate `ST_Transform(unknown, integer)`.
**Upstream:** This is a TiPG bug — `TIPG_BBOX_ISSUE.md` documents the issue for submission to `developmentseed/tipg`.
**Deployed:** Extension dropped, verified bbox returns HTTP 200 with correct spatial filtering (387 features matched for Mexico/Central America bbox).

### BUG-006: `/api` metadata fields are null — FIXED

**Severity:** LOW
**Affected:** `GET /api`
**Fix:** Added `openapi_url` and `docs_url` fields to the `/api` response in `admin.py`.
**Deployed:** v0.9.3.0, verified fields return `/openapi.json` and `/docs`.

---

## Open Bugs

### BUG-003: Item not found returns 500 instead of 404

**Severity:** MEDIUM
**Affects:** `GET /vector/collections/{id}/items/{itemId}` when item doesn't exist

Response body correctly says `"code":"NotFound"` but HTTP status is 500 instead of 404.

**Root cause:** TiPG raises exceptions that are not caught by TiTiler's `add_exception_handlers(app, DEFAULT_STATUS_CODES)`. TiPG has its own exception hierarchy that needs separate handler registration.

**Investigation needed:**
1. Identify TiPG's exception classes: `python3 -c "import tipg.errors; print(dir(tipg.errors))"`
2. Check if TiPG provides its own `add_exception_handlers` utility
3. Register TiPG exception handlers alongside TiTiler's in `app.py:323`

### BUG-004: Client errors return 500 instead of 4xx

**Severity:** MEDIUM
**Affects:** Multiple TiPG endpoints (CQL parse errors, invalid collections)

**Examples:**
- CQL parse error -> 500 (should be 400)
- Non-existent collection -> 422 (should be 404)

**Root cause:** Same as BUG-003 — TiPG exceptions not registered with FastAPI's exception handler system. A single fix (registering TiPG exception handlers) likely resolves both.

### PERF-001: Intermittent timeouts on data-fetching endpoints

**Severity:** MEDIUM (operational)
**Affects:** COG point queries, COG preview, COG bbox image, vector diagnostics

**Observations:**
- RAM at 92.6% utilization on Premium0V3 (4.68GB)
- COG tiles at z=8 and z=11 work; z=9 and z=10 timeout
- Point queries, preview, and bbox image endpoints timeout

**Not a code bug** — infrastructure/scaling concern. Consider:
1. Upgrading SKU if memory pressure is confirmed
2. Adding request timeout configuration to TiTiler
3. Caching frequently accessed COG overviews

---

## Not a Bug

### BUG-005: xarray empty responses

**Reported as:** xarray endpoints return empty responses when tested with public HTTPS URLs

**Actual behavior:** By design. The xarray endpoints require `abfs://` URLs for authenticated Azure Blob Storage access. Public `https://` URLs route to anonymous HTTPFileSystem which cannot access private containers. The ETL test report tested with a public Pangeo URL that may have been unreachable or incompatible.

**No fix needed.** Documented in `ZARR_NOTES.md` in the rmhgeoapi project.
