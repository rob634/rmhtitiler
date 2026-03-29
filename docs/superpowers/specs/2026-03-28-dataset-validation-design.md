# Dataset Validation Endpoints

**Date**: 2026-03-28
**Status**: Approved
**Approach**: Thin validators (Approach 1) — plain check functions, per-data-type endpoints, feature-flagged

## Context

The tile server (rmhtitiler) sits downstream of the ETL pipeline (rmhgeoapi). Currently there is no validation layer between ETL output and what the serving layer expects. Bad data manifests as blank tiles, empty results, 500 errors, or silent data gaps — with no diagnostic feedback about *why*.

This design adds **data validation endpoints** to the tile server. The tile server knows best what "serveable" means for each data type, so it should be able to articulate that knowledge on demand.

**Two-app validation architecture:**

| Concern | Owner | How |
|---------|-------|-----|
| Data validation ("is this well-formed?") | rmhtitiler | New `/validate/*` endpoints (this spec) |
| Functional validation ("can I serve this?") | rmhgeoapi | Calls existing tile server endpoints post-ingest (brief spec below) |

The tile server is stateless and read-only — it returns JSON reports but does not persist results, schedule checks, or trigger alerts. The ETL app owns scheduling (cron, off-peak), result storage (database table), and alerting.

## Endpoints

```
GET /validate/vector/{collection}?depth=metadata|sample|full
GET /validate/cog?url={blob_url}&depth=metadata|sample|full
GET /validate/zarr?url={blob_url}&variable={name}&depth=metadata|sample|full
GET /validate/stac/{collection}?depth=metadata|sample|full
GET /validate/all?depth=metadata|sample|full
```

- `depth` defaults to `metadata`
- `depth=full` returns **403** when `GEOTILER_ENABLE_VALIDATION_FULL_SCAN` is `false`
- All endpoints return the standard response shape (see below)
- `/validate/all` discovers datasets from existing app state: vector collections from `app.state.collection_catalog`, STAC collections from `pgstac.collections`, and any COG/Zarr URLs referenced by STAC item assets. Aggregates results with cross-referencing between data types (e.g., STAC collection references COGs that fail validation). Does NOT accept ad-hoc COG/Zarr URLs — those must be validated individually via their per-type endpoints.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GEOTILER_ENABLE_VALIDATION` | `false` | Feature flag — mounts `/validate/*` router |
| `GEOTILER_ENABLE_VALIDATION_FULL_SCAN` | `false` | Gates `depth=full` (expensive, internal-only instances) |

Both follow existing `GEOTILER_ENABLE_*` convention. No auth gating initially — feature flag controls visibility. Auth via roles will be added later when the role system matures.

## Response Contract

Every validation endpoint returns this shape:

```json
{
  "target": "geo.floods_jakarta_2024",
  "target_type": "vector",
  "depth": "sample",
  "timestamp": "2026-03-28T14:30:00Z",
  "status": "warn",
  "summary": "2 of 8 checks passed with warnings",
  "checks": [
    {
      "name": "geometry_not_null",
      "status": "pass",
      "message": "All 10 sampled rows have non-null geometry"
    },
    {
      "name": "geometry_valid",
      "status": "warn",
      "message": "1 of 10 sampled geometries is invalid (ST_IsValid)",
      "details": {"sampled": 10, "invalid": 1}
    },
    {
      "name": "srid_consistent",
      "status": "pass",
      "message": "All geometries use SRID 4326"
    }
  ]
}
```

- `status` is the worst of all check statuses: `pass` < `warn` < `fail`
- Each check has `name`, `status` (`pass`|`warn`|`fail`), `message` (human-readable), and optional `details` (dict for machine consumption)
- `/validate/all` returns an array of these reports plus a top-level summary:

```json
{
  "timestamp": "2026-03-28T14:30:00Z",
  "depth": "sample",
  "status": "warn",
  "summary": "14 datasets validated: 12 pass, 2 warn, 0 fail",
  "datasets": [ ...individual reports... ]
}
```

## Checks Per Data Type

### Vector (PostGIS via TiPG)

Implementation: TiPG catalog for existence checks + raw asyncpg queries on the existing TiPG pool (`app.state.pool`).

| Check | metadata | sample | full | Implementation |
|-------|:--------:|:------:|:----:|----------------|
| `table_exists` | x | x | x | Lookup in `app.state.collection_catalog` + `SELECT 1 FROM {table} LIMIT 0` |
| `geometry_column` | x | x | x | Catalog entry has geometry type and SRID registered |
| `permissions` | x | x | x | `has_table_privilege(current_user, '{table}', 'SELECT')` |
| `primary_key` | x | x | x | Catalog entry has PK (TiPG requires this) |
| `srid_consistent` | | x | x | `SELECT DISTINCT ST_SRID(geom) FROM {table} LIMIT 10` / full scan |
| `geometry_not_null` | | x | x | `SELECT count(*) FILTER (WHERE geom IS NULL)` — 10 rows / all rows |
| `geometry_valid` | | x | x | `SELECT count(*) FILTER (WHERE NOT ST_IsValid(geom))` — 10 rows / all rows |
| `row_count` | | x | x | `SELECT count(*) FROM {table}` (sample: `reltuples` estimate; full: exact) |

Sample depth uses `TABLESAMPLE SYSTEM_ROWS(10)` or `LIMIT 10` for the sampling checks. Full depth scans all rows.

### COG (Cloud Optimized GeoTIFF)

Implementation: `rasterio.open()` directly with the existing GDAL env/auth configured by the storage middleware. Header reads use HTTP range requests — cheap.

| Check | metadata | sample | full | Implementation |
|-------|:--------:|:------:|:----:|----------------|
| `accessible` | x | x | x | HEAD request or `rasterio.open()` succeeds |
| `is_tiled` | | x | x | `src.is_tiled` |
| `has_overviews` | | x | x | `len(src.overviews(1)) > 0` |
| `crs_defined` | | x | x | `src.crs is not None` |
| `nodata_defined` | | x | x | `src.nodata is not None` |
| `band_count` | | x | x | `src.count >= 1` |
| `readable_tile` | | | x | `src.read(window=small_window)` succeeds without error |

Note: `sample` depth for COGs reads headers only (rasterio does this via range requests without downloading the full file). The `full` depth `readable_tile` check reads a small window of actual pixel data.

### Zarr/NetCDF

Implementation: `xarray.open_zarr()` directly with the same fsspec/obstore auth. Metadata reads are lazy (no data loaded until `.values` is called).

| Check | metadata | sample | full | Implementation |
|-------|:--------:|:------:|:----:|----------------|
| `accessible` | x | x | x | `xarray.open_zarr(store)` succeeds |
| `variable_exists` | x | x | x | `variable in ds.data_vars` |
| `crs_defined` | | x | x | CRS in attrs or `grid_mapping` variable present |
| `dimensions` | | x | x | Has spatial dims (`x`/`y` or `lat`/`lon` or `latitude`/`longitude`) |
| `chunk_structure` | | x | x | `ds[variable].encoding.get("chunks") is not None` |
| `time_dim_indexed` | | x | x | If time dim exists, `len(ds.time) > 0` |
| `readable_slice` | | | x | `ds[variable].isel(x=0, y=0).values` loads without error |

### STAC (pgSTAC)

Implementation: raw asyncpg on the STAC pool (`app.state.readpool`) querying `pgstac.collections` and `pgstac.items` directly.

| Check | metadata | sample | full | Implementation |
|-------|:--------:|:------:|:----:|----------------|
| `collection_exists` | x | x | x | `SELECT 1 FROM pgstac.collections WHERE id = $1` |
| `item_count` | x | x | x | `SELECT count FROM pgstac.collections WHERE id = $1` (pgstac tracks this) |
| `assets_have_href` | | x | x | Items have `assets` with at least one `href` — 10 items / all items |
| `bounds_valid` | | x | x | bbox within WGS84 range (-180,-90,180,90) — 10 items / all items |
| `datetime_valid` | | x | x | `datetime` or `start_datetime`/`end_datetime` present and parseable — 10 items / all items |
| `asset_accessible` | | | x | HEAD request against sampled asset URLs (up to 10 even in full mode to avoid hammering storage) |

### `/validate/all` — Cross-Referencing

Individual per-type endpoints are independent. The `/validate/all` endpoint runs all per-type checks and then performs cross-type correlation:

- STAC items reference COG asset URLs → report if any referenced COGs fail data validation
- STAC collections should correspond to items → flag empty collections
- Vector collections in TiPG catalog should be queryable → flag permission/structure issues

Cross-references only run at `sample` or `full` depth (metadata is too shallow to correlate meaningfully).

## File Structure

```
geotiler/
├── routers/
│   └── validate.py              # Router: endpoint definitions, depth gating, response assembly
├── services/
│   └── validate/
│       ├── __init__.py           # Shared types (CheckResult, ValidationReport, depth enum)
│       ├── vector.py             # Vector check functions
│       ├── cog.py                # COG check functions
│       ├── zarr.py               # Zarr check functions
│       └── stac.py               # STAC check functions
```

Each service file exports a single async entry point:

```python
async def validate_vector(collection_id: str, depth: Depth, app: FastAPI) -> ValidationReport:
    ...

async def validate_cog(url: str, depth: Depth, app: FastAPI) -> ValidationReport:
    ...
```

Check functions are plain async functions within each file — no classes, no registry, no plugin system. Each returns a `CheckResult` (name, status, message, details).

## Implementation Approach

**Bypass the serving layer, use the same underlying libraries and connections:**

| Data Type | Uses | Does NOT use |
|-----------|------|--------------|
| Vector | TiPG catalog (read-only) + raw asyncpg on `app.state.pool` | TiPG rendering/query engine |
| COG | `rasterio.open()` with existing GDAL env/auth | TiTiler COG factory |
| Zarr | `xarray.open_zarr()` with existing fsspec auth | titiler-xarray |
| STAC | Raw asyncpg on `app.state.readpool` against pgstac schema | stac-fastapi |

This means validation works even when the serving layer has a bug — which is exactly when you need it most.

**COG and Zarr checks run in `asyncio.to_thread()`** since rasterio and xarray are synchronous. This follows the existing pattern used by the DuckDB service.

**SQL identifiers** in vector checks use the same `_validate_identifier()` regex from `vector_query.py` to prevent injection. Parameterized queries (`$1`) for all values.

## Error Handling

- If a check itself errors (e.g., asyncpg pool unavailable), that check returns `status: "fail"` with the error in `message` and `details`. The endpoint still returns 200 — the report documents the failure.
- If the target doesn't exist at all (collection not found, URL 404), the endpoint returns 404.
- If `depth=full` is requested but `GEOTILER_ENABLE_VALIDATION_FULL_SCAN` is false, return 403 with a clear message.
- If the validation feature is disabled, the router is not mounted — requests to `/validate/*` return 404 naturally.

## Dependencies

No new packages. Everything uses existing dependencies:

- `rasterio` — already installed (GDAL/COG access)
- `xarray` — already installed (Zarr access)
- `asyncpg` — already installed (PostgreSQL access)
- `httpx` — already installed (HEAD requests for asset accessibility)

---

## Brief Spec: ETL Functional Validation (rmhgeoapi)

> This section is a contract specification for the ETL app. Implementation lives in rmhgeoapi, not here.

### Purpose

After ETL creates or updates a dataset, verify that the tile server can actually serve it. This is the ETL checking its own work — the passing condition is that the tile server's existing API responds as expected.

### Functional Checks

| After ETL creates... | Call to tile server | Pass condition |
|---|---|---|
| PostGIS table | `POST /admin/refresh-collections` | 200 |
| PostGIS table | `GET /validate/vector/{id}?depth=sample` | 200 + status != "fail" |
| PostGIS table | `GET /vector/collections/{id}/items?limit=1` | 200 + at least 1 feature returned |
| PostGIS table | `GET /vector/collections/{id}/tiles/WebMercatorQuad/0/0/0` | 200 + non-empty response body |
| COG upload | `GET /validate/cog?url=...&depth=sample` | 200 + status != "fail" |
| COG upload | `GET /cog/info?url=...` | 200 + valid band/CRS info in response |
| COG upload | `GET /cog/tiles/0/0/0?url=...` | 200 + image bytes in response |
| Zarr upload | `GET /validate/zarr?url=...&variable=...&depth=sample` | 200 + status != "fail" |
| Zarr upload | `GET /xarray/info?url=...&variable=...` | 200 + variable metadata in response |
| STAC ingest | `GET /validate/stac/{id}?depth=sample` | 200 + status != "fail" |
| STAC ingest | `GET /stac/collections/{id}` | 200 + collection exists |
| STAC + COG mosaic | `POST /searches/register` → `GET /searches/{hash}/tiles/0/0/0` | 200 + mosaic renders |

### Scheduling & Storage

- ETL runs functional checks **immediately after each ingest job** (inline, not cron)
- ETL runs data validation checks (`/validate/*`) on a **daily cron during off-peak hours** against all registered datasets
- Results stored in ETL's own database (e.g., `etl.validation_results` table) with: dataset ID, check name, status, timestamp, response body
- Alerting: ETL's concern — tile server is not involved

### Tile Server Contract

The tile server makes no promises beyond what its existing API already guarantees. The validation endpoints are additive — they provide richer diagnostic information but are not required for the functional checks to work. If `/validate/*` is disabled on an instance, ETL can still run all functional checks using the existing serving endpoints.
