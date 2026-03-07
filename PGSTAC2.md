# Base Image Migration: titiler-pgstac 1.9.0 → 2.1.0

**Goal:** Upgrade the base Docker image from `titiler-pgstac:1.9.0` to `titiler-pgstac:2.1.0`, bringing titiler-core from 0.24.x to 1.2.0, rio-tiler from 7.x to 8.x, and titiler.xarray from 0.24.x to 1.2.0.

**Branch:** `upgrade/pgstac-2.1`
**Target version after merge:** v0.10.0.0 (minor bump — new base image)

---

## Why Upgrade

1. **rio-tiler version conflict resolved.** Currently the base image ships rio-tiler 7.x but titiler.xarray pulls rio-tiler 8.x. pip warns about this on every build. titiler-pgstac 2.1.0 uses rio-tiler 8.x natively — no more conflict.

2. **titiler-core 1.2.0 features.** Built-in `/map` viewer on all TilerFactory endpoints, algorithm support (hillshade, NDVI, etc.), improved point statistics model.

3. **titiler.xarray version ceiling removed.** Currently pinned `<0.25.0` to match the old base. With the new base, we can use titiler.xarray 1.2.0 which aligns natively.

4. **Security and maintenance.** The 1.9.0 image is from September 2024. The 2.1.0 image (March 2025) has container security improvements and UV package management.

---

## Compatibility Verification (Done)

API compatibility between 1.9.0 and 2.1.0 was verified by inspecting the 2.1.0 package source:

| Symbol | Status | Notes |
|--------|--------|-------|
| `PostgresSettings(database_url=...)` | **Unchanged** | Still accepts `database_url` parameter |
| `connect_to_db(app, settings=...)` | **Unchanged** | Same signature |
| `close_db_connection(app)` | **Unchanged** | Same signature |
| `SearchIdParams` | **Unchanged** | Still in `titiler.pgstac.dependencies` |
| `MosaicTilerFactory` | **Unchanged** | Same init params, same dependency attributes |
| `add_search_register_route` | **Unchanged** | Same signature with `tile_dependencies` |
| `add_search_list_route` | **Unchanged** | Same signature |
| `DEFAULT_STATUS_CODES` | **Unchanged** | Still in `titiler.core.errors` |
| `add_exception_handlers` | **Unchanged** | Still in `titiler.core.errors` |
| `TilerFactory` | **Unchanged** | Same in `titiler.core.factory` |
| `XarrayTilerFactory` | **Unchanged** | Same in `titiler.xarray.factory` |
| `VariablesExtension` | **Unchanged** | Same in `titiler.xarray.extensions` |
| All `.xxx_dependency` attrs on MosaicTilerFactory | **Unchanged** | `layer_dependency`, `dataset_dependency`, `pixel_selection_dependency`, `process_dependency`, `render_dependency`, `assets_accessor_dependency`, `reader_dependency`, `backend_dependency` all present |

**Breaking changes in 2.x that do NOT affect us:**
- `TileParams` → `TmsTileParams` — we don't import this
- `ItemPathParams` → `ItemIdParams` — we don't import this
- `db_max_inactive_conn_lifetime` → `db_max_idle` — we don't set this (use defaults)
- `reader_connection_string` / `writer_connection_string` removed — we use `database_url` directly
- `reverse` option removed from PGSTACBackend — we don't use this
- Band names prefixed with `b` in info/statistics — behavioral change, no code impact (frontend may need awareness)

---

## Implementation Plan

### Task 1: Create branch and update Dockerfile

**Files:**
- Modify: `Dockerfile` (line 3)
- Modify: `Dockerfile.local` (line 3)

**Changes:**

```dockerfile
# Dockerfile — line 3
# OLD:
FROM ghcr.io/stac-utils/titiler-pgstac:1.9.0

# NEW:
FROM ghcr.io/stac-utils/titiler-pgstac:2.1.0
```

Same change in `Dockerfile.local` line 3.

Also update the JFrog comment in `Dockerfile` line 5:
```dockerfile
#FROM artifactory.worldbank.org/itsdt-docker-virtual/titiler-pgstac:2.1.0
```

**Commit:** `build: upgrade base image to titiler-pgstac 2.1.0`

---

### Task 2: Update requirements.txt version pins

**Files:**
- Modify: `requirements.txt`

**Changes:**

```
# OLD (line 24):
titiler.xarray[minimal]>=0.24.0,<0.25.0

# NEW:
titiler.xarray[minimal]>=1.2.0,<2.0
```

Update the comment block above it (lines 19-23):
```
# Multidimensional data support (Zarr, NetCDF)
# NOTE: [minimal] DOES include zarr transitively via xarray. Do NOT add zarr
# as a separate dependency — it is already installed. Pinned to 1.2.x to
# match base image titiler-pgstac:2.1.0 (titiler-core 1.2.x).
titiler.xarray[minimal]>=1.2.0,<2.0
```

**Commit:** `build: update titiler.xarray pin for titiler-core 1.2.x compatibility`

---

### Task 3: Update Dockerfile.local dependencies

**Files:**
- Modify: `Dockerfile.local` (lines 6-13)

The local Dockerfile has a stale, loose pin `"titiler.xarray>=0.18.0"` and is missing several production dependencies. Update to use requirements.txt like the production Dockerfile:

```dockerfile
# OLD:
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0 \
    azure-keyvault-secrets>=4.7.0 \
    "titiler.xarray>=0.18.0" \
    adlfs>=2024.4.1 \
    psutil>=5.9.0 \
    pydantic-settings>=2.0.0 \
    azure-monitor-opentelemetry>=1.6.0

# NEW:
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory for DuckDB parquet cache
RUN mkdir -p /app/data
```

This aligns `Dockerfile.local` with `Dockerfile` — both now install from `requirements.txt`. The `COPY requirements.txt .` line must come before `COPY geotiler /app/geotiler`.

**Commit:** `build: align Dockerfile.local with production (use requirements.txt)`

---

### Task 4: Update version metadata in __init__.py

**Files:**
- Modify: `geotiler/__init__.py`

Update the docstring to reflect the new base image version:

```python
# OLD (line 16-19):
Dependency Versions (as of v0.8.19)
-----------------------------------
This package installs titiler.xarray>=0.24.0,<0.25.0 which is pinned
to match the base image (titiler-pgstac:1.9.0, built against titiler-core 0.24.x).
Upgrading to titiler.xarray 1.x requires migrating to titiler-pgstac 2.0.0.

# NEW:
Dependency Versions (as of v0.10.0)
------------------------------------
Base image: titiler-pgstac:2.1.0 (titiler-core 1.2.x, rio-tiler 8.x).
titiler.xarray pinned to >=1.2.0,<2.0 to match.
```

Do NOT bump `__version__` yet — that happens after merge to master.

**Commit:** `docs: update dependency version notes in __init__.py`

---

### Task 5: Update app.py docstring

**Files:**
- Modify: `geotiler/app.py` (line 6)

```python
# OLD:
- TiTiler-core (COG tiles via rio-tiler 8.x)

# This is actually already correct. Verify no other stale version refs exist.
```

Search `geotiler/app.py` for any references to `0.24`, `1.9.0`, or old version strings and update.

**Commit:** (only if changes needed)

---

### Task 6: Build and test in ACR

**Commands:**

```bash
# Build from the branch
az acr build --registry rmhazureacr --resource-group rmhazure_rg \
  --image rmhtitiler:pgstac2-test .
```

Watch for:
1. **pip dependency resolution errors** — the key risk. If titiler.xarray 1.2.0 conflicts with the new base image, pip will fail here.
2. **The rio-tiler conflict warning should be GONE** — that's the primary success indicator.
3. **Build completes without error** — image pushed to ACR.

---

### Task 7: Deploy test image and run SIEGE

Deploy the test image to the live app (since it's a single environment):

```bash
# Deploy test image
az webapp config container set --name rmhtitiler --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:pgstac2-test

az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

**Verification checklist (manual or SIEGE):**

1. `GET /health` — all 6 services healthy, version unchanged (0.9.2.2)
2. `GET /cog/info?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif` — 200, bounds correct
3. `GET /xarray/variables?url=abfs://silver-zarr/cmip6-tasmax-sample.zarr` — 200, `["tasmax"]`
4. `GET /xarray/info?url=abfs://silver-zarr/era5-global-sample.zarr&variable=air_temperature_at_2_metres` — 200, 1440x721
5. `GET /vector/collections` — 200, collections list
6. `GET /stac/collections` — 200, collections list
7. `GET /stac/search?limit=3` — 200, items returned
8. `GET /cog/tiles/WebMercatorQuad/14/4686/6266?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif` — 200, image/png
9. `GET /livez` — 200
10. `GET /readyz` — 200

**Band name format check (new behavior):**
11. `GET /cog/statistics?url=...` — verify band names are `b1, b2, b3` (was `1, 2, 3`)
12. `GET /cog/info?url=...` — verify band_metadata uses `b1` prefix

If any frontend code parses band names from statistics/info responses, it will need updating. The built-in map viewers are served by titiler-core and will work automatically.

**If tests fail:** Roll back immediately:
```bash
az webapp config container set --name rmhtitiler --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:v0.9.2.2
az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

---

### Task 8: Merge and version bump

After successful verification:

```bash
# On the upgrade branch
git checkout master
git merge upgrade/pgstac-2.1
```

Bump version in `geotiler/__init__.py`:
```python
__version__ = "0.10.0.0"
```

Build and deploy the final tagged image:
```bash
az acr build --registry rmhazureacr --resource-group rmhazure_rg \
  --image rmhtitiler:v0.10.0.0 .

az webapp config container set --name rmhtitiler --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:v0.10.0.0

az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

Final health check to confirm v0.10.0.0 is live.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| pip dependency conflict during build | Low | Blocks deploy | Pin exact versions, test build first |
| API breakage in titiler-pgstac 2.x | **Very low** | Broken endpoints | Verified all imports are compatible (see table above) |
| Band name format change breaks consumers | Medium | Cosmetic | Document in release notes; doesn't affect tile rendering |
| TiPG/stac-fastapi incompatibility | Low | Broken vector/STAC | These are installed independently, not from base image |
| Xarray tile rendering regression | Low | Broken Zarr tiles | Test ERA5 and CMIP6 datasets explicitly |

## Rollback Plan

At any point, redeploy the previous image:
```bash
az webapp config container set --name rmhtitiler --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:v0.9.2.2
az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

---

## Sources

- [titiler-pgstac releases](https://github.com/stac-utils/titiler-pgstac/releases)
- [titiler-pgstac CHANGES.md](https://github.com/stac-utils/titiler-pgstac/blob/main/CHANGES.md)
- [titiler CHANGES.md](https://github.com/developmentseed/titiler/blob/main/CHANGES.md)
- [titiler-pgstac v0.8→v1.0 migration guide](https://stac-utils.github.io/titiler-pgstac/1.2.3/migrations/v1_migration/)
- [tipg release notes](https://developmentseed.org/tipg/release-notes/)
