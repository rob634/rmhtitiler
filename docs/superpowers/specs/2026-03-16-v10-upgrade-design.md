# v0.10.0.0 Upgrade: titiler-pgstac 2.1.0

**Date**: 2026-03-16
**Status**: Approved
**Approach**: Surgical upgrade (Approach A) — fix known breaking changes, let ACR build validate the rest

## Context

The cloud team onboarded the `ghcr.io/stac-utils/titiler-pgstac:2.1.0` Docker image in QA. This upgrade moves the tile server from the 0.9.x line (titiler-pgstac 1.9.0, titiler-core 0.24.x) to the 0.10.x line (titiler-pgstac 2.1.0, titiler-core 1.2.x).

**Impetus**: xarray/Zarr v3 support via titiler.xarray 1.2.x, plus the major version update of the base image.

**Scope**: The app is in development — large revisions are acceptable. No B2B consumers of any endpoint. No locked URL contracts.

## Base Image: titiler-pgstac 2.1.0

Pre-installed in the base image (we do NOT install these):

| Package | Version |
|---------|---------|
| titiler-core | 1.2.0 |
| titiler-mosaic | 1.2.0 |
| titiler-extensions | 1.2.0 |
| rio-tiler | 8.0.5 |
| rasterio | 1.4.4 / 1.5.0 |
| fastapi | 0.135.1 |
| pydantic | 2.12.5 |
| pydantic-settings | 2.13.1 |
| psycopg / psycopg-binary | 3.3.3 |
| psycopg-pool | 3.3.0 |
| numpy | 2.4.2 |
| stac-pydantic | 3.5.0 |
| Python | **3.14** |

**Notable**: asyncpg is NOT in the base image. We must install it explicitly.

## Database: No Changes

pgstac SQL schema stays at **0.9.8**. titiler-pgstac 2.1.0 supports `pypgstac>=0.9.8,<=0.10`. No ETL app (rmhgeoapi) changes needed. No database migration.

Latest pgstac is 0.9.10 (non-breaking partition fixes). We may revisit later but not as part of this upgrade.

## requirements-v10.txt Changes

### Remove

| Package | Reason |
|---------|--------|
| `icechunk>=1.1.9` | Feature scrapped — not imported anywhere in codebase |
| `pydantic-settings>=2.0.0` | Already in base image (2.13.1 via titiler-pgstac) |

### Add

| Package | Pin | Reason |
|---------|-----|--------|
| `asyncpg>=0.29.0` | Needed by tipg and stac-fastapi-pgstac for async connection pools; NOT in base image. Also fix the header comment in requirements-v10.txt which incorrectly claims asyncpg is provided by the base image. |

### Bump

| Package | Old Pin | New Pin | Reason |
|---------|---------|---------|--------|
| `stac-fastapi.pgstac` | `>=4.0.0` | `>=5.0.0,<7.0` | 4.x is 2 majors behind; existing code already uses 5.x/6.x field naming conventions |

### Keep Unchanged

| Package | Pin | Notes |
|---------|-----|-------|
| `azure-identity` | `>=1.16.1` | CVE-2024-35255 already covered, 3.14 confirmed |
| `azure-keyvault-secrets` | `>=4.8.0` | No CVEs, used for key_vault auth mode |
| `titiler.xarray[minimal]` | `>=1.2.0,<2.0` | 2.0.0 requires titiler-core 2.0 + rio-tiler 9.x — incompatible with base image |
| `xarray` | `>=2024.10.0` | Required for Zarr v3 dimension_names support |
| `adlfs` | `>=2024.4.1` | fsspec driver for abfs:// scheme, 3.14 confirmed |
| `psutil` | `>=5.9.0` | 3.14 confirmed, no CVEs at this pin |
| `azure-monitor-opentelemetry` | `>=1.6.0` | No CVEs |
| `tipg` | `>=1.3.1` | Latest release, needed for tipg 1.x API |
| `duckdb` | `>=1.1.0` | CVE-2024-41672 already covered, 3.14 confirmed |

### Security Audit

All known CVEs (azure-identity CVE-2024-35255, psutil CVE-2019-18874, duckdb CVE-2024-41672) are already resolved by the current minimum pins. No action needed.

## Python Code Changes

### Definite Changes

**`geotiler/__init__.py`** — Version bump:
```python
__version__ = "0.10.0.0"
```

**`geotiler/app.py`** — xarray extension swap:
```python
# OLD (line 51)
from titiler.xarray.extensions import VariablesExtension

# NEW
from titiler.xarray.extensions import DatasetMetadataExtension
```
```python
# OLD (lines 232-236)
xarray_tiler = XarrayTilerFactory(
    router_prefix="/xarray",
    extensions=[VariablesExtension()]
)

# NEW
xarray_tiler = XarrayTilerFactory(
    router_prefix="/xarray",
    extensions=[DatasetMetadataExtension()]
)
```

This replaces `/xarray/variables` with `/xarray/metadata`. No B2B consumers affected.

**`geotiler/templates/pages/xarray/landing.html`** — Update endpoint table and JS action from `/xarray/variables` to `/xarray/metadata` (lines 101, 187).

**`geotiler/templates/pages/guide/data-scientists/index.html`** — Update endpoint reference from `/xarray/variables` to `/xarray/metadata` (line 62).

### Build-Validated Changes ("Fix What Breaks")

These changes are likely needed but exact fixes depend on what the actual installed packages expose. The ACR build + app startup will surface them:

1. **`geotiler/app.py` — MosaicTilerFactory tile_dependencies** (lines 260-269): The `add_search_register_route` dependency list references factory attributes that may have been renamed in the attrs refactor (1.5.0+) or removed in the render_func change (1.6.0+). Specifically `assets_accessor_dependency`, `reader_dependency`, `backend_dependency`.

2. **`geotiler/routers/stac.py` — stac-fastapi-pgstac imports**: Import paths from `stac_fastapi.pgstac.config` (Settings, PostgresSettings, ServerSettings) and `stac_fastapi.pgstac.db` (connect_to_db, close_db_connection) may have moved in 5.x/6.x. The constructor field names (`pguser`, `pgpassword`, etc.) already match 6.x conventions.

3. **`geotiler/routers/vector.py` — tipg Endpoints constructor**: `with_tiles_viewer=True` may have been renamed (tipg 1.3.0 renamed `/viewer` to `/map.html`).

4. **`geotiler/services/background.py` — titiler-pgstac imports** (lines 94-95): Imports `titiler.pgstac.db.connect_to_db`, `titiler.pgstac.settings.PostgresSettings` for pool recreation during token refresh. If these APIs changed in 2.1.0, this file breaks too.

5. **`azure-monitor-opentelemetry` on Python 3.14**: OpenTelemetry has historically been slow to adopt new Python versions due to native extensions. If the ACR build fails on this package, we may need to bump the pin or temporarily disable telemetry.

## Dockerfile Changes

Change default `BASE_TAG` to 2.1.0 (v10 is now the primary build target):
```dockerfile
ARG BASE_TAG=2.1.0
```

Since the default is now 2.1.0, the build command no longer needs the `BASE_TAG` override:
```bash
az acr build --registry rmhazureacr --resource-group rmhazure_rg \
  --image rmhtitiler:v0.10.0.0 \
  --build-arg REQUIREMENTS=requirements-v10.txt .
```

To build a legacy v9 image (if ever needed):
```bash
az acr build ... --build-arg BASE_TAG=1.9.0 --build-arg REQUIREMENTS=requirements.txt .
```

## Rollback Plan

If the v10 image fails in ways that can't be quickly fixed, redeploy the last known good image:
```bash
az webapp config container set --name rmhtitiler --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:v0.9.6.0
az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

## Build & Validation Strategy

1. **Code changes** (local): Apply all definite changes, commit
2. **ACR build** (remote): Validates pip resolution on Python 3.14, surfaces import errors
3. **Deploy to dev**: `az webapp config container set` + `az webapp restart`
4. **Health check**: `/health` exercises all pools, catalogs, OAuth — comprehensive startup validation
5. **Fix what breaks**: Iterate on build-validated items until `/health` is green
6. **Functional smoke test**:
   - `/cog/info?url=/vsiaz/...` — COG metadata
   - `/xarray/WebMercatorQuad/tilejson.json?url=abfs://...&variable=...&bidx=1&rescale=...` — Zarr v3
   - `/vector/collections` — TiPG discovery
   - `/stac/collections` — STAC catalog
   - `/stac/search` — STAC search

## STAC API Schema Note

stac-fastapi-pgstac does NOT schema-qualify pgstac function calls in any version (4.x, 5.x, 6.x). All SQL is bare `SELECT * FROM search(...)`, never `SELECT * FROM pgstac.search(...)`. The `search_path=pgstac,public` server_settings workaround is the intended design. Our code already handles this correctly via `StacServerSettings` passed to `PostgresSettings`. This continues to work in 5.x/6.x.

## Out of Scope

- pgstac SQL schema upgrade (stays at 0.9.8)
- ETL app (rmhgeoapi) changes
- Icechunk / VirtualiZarr (scrapped)
- titiler.xarray 2.0.0 (requires titiler-core 2.0 + rio-tiler 9.x, incompatible with base image)
- pgstac 1.0.0 (does not exist)
