# TiTiler-pgSTAC Application Wiki

**Version:** 0.3.1
**Status:** Production-Ready
**Last Updated:** December 2024

---

## Table of Contents

1. [Overview](#overview)
2. [Component Glossary](#component-glossary)
3. [Architecture](#architecture)
4. [Authentication](#authentication)
5. [API Endpoints](#api-endpoints)
   - [Health & Status](#health--status-endpoints)
   - [COG Endpoints](#cog-endpoints)
   - [Xarray/Zarr Endpoints](#xarrayzarr-endpoints)
   - [Planetary Computer Endpoints](#planetary-computer-endpoints)
   - [pgSTAC Search Endpoints](#pgstac-search-endpoints)
   - [Data Extraction Endpoints](#data-extraction-endpoints)
6. [URL Formats](#url-formats)
7. [Query Parameters](#query-parameters)
8. [Test Data](#test-data)
9. [Error Reference](#error-reference)
10. [Documentation Index](#documentation-index)

---

## Overview

**TiTiler-pgSTAC** is a dynamic tile server built on [TiTiler](https://developmentseed.org/titiler/) that serves geospatial data as map tiles. It supports:

| Feature | Description |
|---------|-------------|
| **COG Tiles** | Cloud Optimized GeoTIFFs via GDAL |
| **Zarr/NetCDF** | Multidimensional data via xarray |
| **STAC Integration** | Query-based mosaics via pgSTAC |
| **Planetary Computer** | Access to public climate datasets |
| **Azure Authentication** | OAuth via Managed Identity (no secrets) |

### Key Capabilities

- **Dynamic Tiling**: No pre-generated tiles needed
- **Multi-Container Access**: RBAC-based access to any Azure container
- **Temporal Data**: Time-series visualization with band selection
- **Data Extraction**: GeoTIFF export, point queries, regional statistics

---

## Component Glossary

This document uses **logical names** instead of Azure resource names. See [WIKI_COMPONENTS.md](../rmhgeoapi/WIKI_COMPONENTS.md) for the full platform glossary.

### Storage Components

| Logical Name | Purpose | TiTiler Access |
|--------------|---------|----------------|
| **Silver Storage Account** | Processed COGs, validated vectors, Zarr stores | Read (primary data source) |
| **External Storage Account** | Public-facing approved datasets | Read (CDN-protected) |

### Compute Components

| Logical Name | Purpose |
|--------------|---------|
| **TiTiler Raster Service** | This application - dynamic tile serving for COGs and Zarr |
| **ETL Function App** | Writes data to Silver Storage that TiTiler reads |

### Database Components

| Logical Name | Purpose |
|--------------|---------|
| **Business Database** | PostgreSQL with pgSTAC catalog (`pgstac` schema) |
| **App Reader Identity** | Managed identity for read-only database access |

### URL Placeholders Used in Examples

| Placeholder | Description |
|-------------|-------------|
| `{silver-storage-account}` | Silver Storage Account name |
| `{titiler-service-url}` | TiTiler Raster Service base URL |
| `{container}` | Azure Blob Storage container name |
| `{path}` | Path to file within container |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TiTiler Raster Service                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐     │
│  │   /cog/*    │   │  /xarray/*  │   │    /pc/*    │   │ /searches/* │     │
│  │   (COGs)    │   │   (Zarr)    │   │  (Climate)  │   │  (pgSTAC)   │     │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘     │
│         │                 │                 │                 │             │
│         ▼                 ▼                 ▼                 ▼             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Azure Auth Middleware                           │   │
│  │         OAuth Token Acquisition + Environment Configuration          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│         │                 │                 │                 │             │
│         ▼                 ▼                 ▼                 ▼             │
│  ┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐       │
│  │   GDAL    │     │  fsspec/  │     │  obstore  │     │  asyncpg  │       │
│  │  /vsiaz/  │     │   adlfs   │     │ + PC SAS  │     │  pgSTAC   │       │
│  └─────┬─────┘     └─────┬─────┘     └─────┬─────┘     └─────┬─────┘       │
│        │                 │                 │                 │              │
└────────┼─────────────────┼─────────────────┼─────────────────┼──────────────┘
         │                 │                 │                 │
         ▼                 ▼                 ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Silver Storage  │ │ Silver Storage  │ │ Planetary       │ │ Business        │
│ Account (COGs)  │ │ Account (Zarr)  │ │ Computer        │ │ Database        │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
```

### Internal Components

| Component | Purpose | Library |
|-----------|---------|---------|
| **TilerFactory** | COG tile serving | `titiler.core` |
| **XarrayTilerFactory** | Zarr/NetCDF tile serving | `titiler.xarray` |
| **MosaicTilerFactory** | pgSTAC search-based mosaics | `titiler.pgstac` |
| **AzureAuthMiddleware** | OAuth token injection | Custom |
| **PC Credential Provider** | Planetary Computer SAS tokens | `obstore` |

### Storage Account Compatibility

TiTiler works with **both** Azure storage account types:

| Storage Type | HNS Enabled | Works with TiTiler | Notes |
|--------------|-------------|-------------------|-------|
| **Standard Blob Storage** | `false` | ✅ Yes | Default for most accounts |
| **Data Lake Gen2** | `true` | ✅ Yes | Hierarchical Namespace enabled |

**Why both work:** The `adlfs` library (fsspec's Azure filesystem) defaults to the `blob.core.windows.net` endpoint, not the DFS endpoint. HNS only enables the DFS API as an additional option - but adlfs doesn't require it.

**Architecture implication:** You can serve Zarr/NetCDF data from **either** storage type without code changes. Choose based on other factors (e.g., Data Lake analytics needs, cost, existing infrastructure).

---

## Authentication

### Three Authentication Mechanisms

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Authentication Mechanisms                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. AZURE MANAGED IDENTITY (Silver Storage Account)                         │
│     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━                         │
│     • Uses OAuth bearer tokens                                              │
│     • TiTiler's identity has RBAC permissions on Silver Storage             │
│     • Works with any container the identity can access                      │
│     • Endpoints: /cog/*, /xarray/*, /searches/*                             │
│                                                                             │
│  2. POSTGRESQL MANAGED IDENTITY (Business Database)                         │
│     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━                          │
│     • OAuth tokens for Azure Database for PostgreSQL                        │
│     • Uses App Reader Identity for read-only access                         │
│     • Also supports Key Vault or password-based auth                        │
│     • Endpoints: /searches/*, /mosaic/*                                     │
│                                                                             │
│  3. PLANETARY COMPUTER CREDENTIAL PROVIDER (External Climate Data)          │
│     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━           │
│     • Gets temporary SAS tokens from PC's API                               │
│     • Grants read access to THEIR public storage accounts                   │
│     • Tokens are cached and auto-refreshed                                  │
│     • Endpoints: /pc/*                                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `USE_AZURE_AUTH` | Enable Azure OAuth | `true` |
| `AZURE_STORAGE_ACCOUNT` | **Silver Storage Account** name | `{silver-storage-account}` |
| `LOCAL_MODE` | Use Azure CLI (dev) vs MI (prod) | `true` / `false` |
| `ENABLE_PLANETARY_COMPUTER` | Enable Planetary Computer integration | `true` |
| `POSTGRES_AUTH_MODE` | DB auth: `managed_identity`, `key_vault`, `password` | `managed_identity` |
| `POSTGRES_HOST` | **Business Database** server FQDN | `{db-server}.postgres.database.azure.com` |
| `POSTGRES_DB` | Database name | `geoapp` |
| `POSTGRES_USER` | DB username (**App Reader Identity** name) | `{reader-identity-name}` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_MI_CLIENT_ID` | User-assigned MI client ID (for `managed_identity` mode) | `{client-id-guid}` |
| `POSTGRES_PASSWORD` | DB password (for `password` mode only) | `{password}` |
| `KEY_VAULT_NAME` | Key Vault name (for `key_vault` mode only) | `{keyvault-name}` |
| `KEY_VAULT_SECRET_NAME` | Secret name in Key Vault (for `key_vault` mode) | `postgres-password` |

#### Observability Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights connection string (enables telemetry) | *(none)* |
| `OBSERVABILITY_MODE` | Enable detailed request/latency logging | `false` |
| `SLOW_REQUEST_THRESHOLD_MS` | Slow request threshold in milliseconds | `2000` |
| `APP_NAME` | Service name for log correlation | `rmhtitiler` |
| `ENVIRONMENT` | Deployment environment (dev/qa/prod) | `dev` |

---

## API Endpoints

### Base URL

```
https://{titiler-service-url}
```

---

### Health & Status Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API info and endpoint list |
| `/healthz` | GET | Readiness probe with DB status |
| `/livez` | GET | Liveness probe (simple OK) |
| `/docs` | GET | Interactive OpenAPI documentation |
| `/openapi.json` | GET | OpenAPI specification |

**Health Response Example:**
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "local_mode": false,
  "storage_account": "{silver-storage-account}",
  "token_expires_in_seconds": 3245,
  "database": "connected"
}
```

---

### COG Endpoints

**Prefix:** `/cog`

Cloud Optimized GeoTIFF endpoints using GDAL's `/vsiaz/` virtual filesystem.

#### URL Format for COGs
```
/vsiaz/{container}/{path/to/file.tif}
```

#### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/cog/info` | GET | Get COG metadata (bounds, bands, dtype) |
| `/cog/info.geojson` | GET | Get bounds as GeoJSON Feature |
| `/cog/statistics` | GET | Get band statistics (min, max, mean, std) |
| `/cog/tiles/{tms}/{z}/{x}/{y}.{format}` | GET | Get XYZ tile |
| `/cog/{tms}/tilejson.json` | GET | Get TileJSON for map libraries |
| `/cog/{tms}/map.html` | GET | Interactive map viewer |
| `/cog/preview.{format}` | GET | Generate preview image |
| `/cog/{tms}/WMTSCapabilities.xml` | GET | OGC WMTS capabilities |
| `/cog/bbox/{minx},{miny},{maxx},{maxy}.{format}` | GET | Extract by bounding box |
| `/cog/point/{lon},{lat}` | GET | Get value at point |
| `/cog/feature.{format}` | POST | Clip to GeoJSON polygon |
| `/cog/statistics` | POST | Statistics for GeoJSON region |

#### Example URLs

```bash
# Get metadata (reading from Silver Storage Account)
/cog/info?url=/vsiaz/silver-cogs/dem.tif

# Get tile (WebMercator, zoom 10, x=512, y=384)
/cog/tiles/WebMercatorQuad/10/512/384.png?url=/vsiaz/silver-cogs/dem.tif

# Get TileJSON for Leaflet/MapLibre
/cog/WebMercatorQuad/tilejson.json?url=/vsiaz/silver-cogs/dem.tif

# Interactive map viewer
/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/dem.tif

# Generate thumbnail
/cog/preview.png?url=/vsiaz/silver-cogs/dem.tif&max_size=256
```

---

### Xarray/Zarr Endpoints

**Prefix:** `/xarray`

Multidimensional data endpoints using xarray + fsspec/adlfs.

#### URL Formats for Zarr

| Format | Pattern | Notes |
|--------|---------|-------|
| **HTTPS** (recommended) | `https://{silver-storage-account}.blob.core.windows.net/{container}/{path}.zarr` | Works with OAuth |
| **ABFS (full)** | `abfs://{container}@{silver-storage-account}.dfs.core.windows.net/{path}.zarr` | Works with OAuth |
| **ABFS (simple)** | `abfs://{container}/{path}.zarr` | Requires `AZURE_STORAGE_ACCOUNT_NAME` env var |

#### Critical Parameters

> **WARNING:** For temporal data (time-series), you **MUST** specify `bidx` to select a time step. Without `bidx`, the renderer aggregates ALL time steps, producing meaningless static noise instead of actual data.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `url` | **Yes** | Zarr store URL |
| `variable` | **Yes** | Variable name to render |
| `bidx` | **Yes** (temporal) | Band/time index (1-based). **Without this, temporal data is aggregated into noise!** |
| `decode_times` | **Yes** (CMIP6) | Set to `false` for noleap calendars |

**Example - WRONG vs RIGHT:**
```bash
# WRONG - No bidx = aggregates all 730 time steps = static noise
/xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=...&variable=tasmax

# RIGHT - bidx=1 selects first time step = actual data
/xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=...&variable=tasmax&bidx=1
```

#### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/xarray/variables` | GET | List all variables in Zarr store |
| `/xarray/info` | GET | Get variable metadata |
| `/xarray/tiles/{tms}/{z}/{x}/{y}@{scale}x.{format}` | GET | Get XYZ tile |
| `/xarray/{tms}/tilejson.json` | GET | Get TileJSON |
| `/xarray/{tms}/map.html` | GET | Interactive map viewer |
| `/xarray/bbox/{minx},{miny},{maxx},{maxy}.{format}` | GET | Extract by bounding box |
| `/xarray/point/{lon},{lat}` | GET | Get value at point |
| `/xarray/feature.{format}` | POST | Clip to GeoJSON polygon |
| `/xarray/statistics` | POST | Statistics for GeoJSON region |

#### Example URLs

```bash
# List variables (reading from Silver Storage Account)
/xarray/variables?url=https://{silver-storage-account}.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&decode_times=false

# Get variable info
/xarray/info?url=https://{silver-storage-account}.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false

# Get tile (MUST include bidx for temporal data!)
/xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=https://{silver-storage-account}.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false&bidx=1

# Tile with colormap and rescaling
/xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=...&variable=tasmax&decode_times=false&bidx=1&colormap_name=turbo&rescale=250,320

# Interactive map viewer
/xarray/WebMercatorQuad/map.html?url=...&variable=tasmax&decode_times=false&bidx=1&colormap_name=turbo&rescale=250,320

# Point query
/xarray/point/-77.0,38.9?url=...&variable=tasmax&decode_times=false&bidx=1
```

---

### Planetary Computer Endpoints

**Prefix:** `/pc`

Access to Microsoft Planetary Computer's public climate datasets with automatic SAS token handling.

> **Note:** Planetary Computer is an **external** data source (not part of our platform). These endpoints fetch data from Microsoft's public storage accounts, not from **Silver Storage Account**.

#### Known Planetary Computer Storage Accounts

| Storage Account | Default Collection | Description |
|-----------------|-------------------|-------------|
| `rhgeuwest` | `cil-gdpcir-cc0` | Climate Impact Lab CMIP6 downscaled projections |
| `ai4edataeuwest` | `daymet-daily-na` | gridMET and Daymet meteorological data |

#### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pc/collections` | GET | List known PC storage accounts |
| `/pc/variables` | GET | List variables in PC Zarr dataset |
| `/pc/info` | GET | Get dataset/variable metadata |
| `/pc/tiles/{z}/{x}/{y}.png` | GET | Get tile from PC data |
| `/pc/{tms}/tilejson.json` | GET | Get TileJSON |
| `/pc/{tms}/map.html` | GET | Interactive map viewer |

#### Example URLs

```bash
# List collections
/pc/collections

# List variables in CMIP6 dataset (external Planetary Computer data)
/pc/variables?url=https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmax/v1.1.zarr

# Get info
/pc/info?url=https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmax/v1.1.zarr&variable=tasmax

# Get tile
/pc/tiles/0/0/0.png?url=https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmax/v1.1.zarr&variable=tasmax
```

#### CMIP6 Dataset URLs (Planetary Computer)

```
# Maximum Temperature (SSP585)
https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmax/v1.1.zarr

# Minimum Temperature
https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmin/v1.1.zarr

# Precipitation
https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/pr/v1.1.zarr
```

---

### pgSTAC Search Endpoints

**Prefix:** `/searches`

STAC catalog search-based tile serving via pgSTAC (reads from **Business Database**).

#### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/searches/register` | POST | Register a new search |
| `/searches/list` | GET | List registered searches |
| `/searches/{search_id}/info` | GET | Get search info |
| `/searches/{search_id}/tiles/{tms}/{z}/{x}/{y}` | GET | Get tile from search results |
| `/searches/{search_id}/{tms}/tilejson.json` | GET | Get TileJSON |
| `/searches/{search_id}/{tms}/map.html` | GET | Interactive map viewer |

#### Register Search Example

```bash
curl -X POST "https://{titiler-service-url}/searches/register" \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["my-collection"],
    "filter": {
      "op": "=",
      "args": [{"property": "datetime"}, "2024-01-01"]
    }
  }'
```

#### Get Tiles from Search

```bash
/searches/{search_id}/tiles/WebMercatorQuad/10/512/384.png?assets=visual
```

---

### Data Extraction Endpoints

Available for both `/cog` and `/xarray` prefixes.

#### Bounding Box Extraction

```bash
# Extract as GeoTIFF
/{prefix}/bbox/{minx},{miny},{maxx},{maxy}.tif?url=...

# Extract with specific dimensions
/{prefix}/bbox/{minx},{miny},{maxx},{maxy}/{width}x{height}.tif?url=...

# Extract as PNG with colormap
/{prefix}/bbox/{minx},{miny},{maxx},{maxy}.png?url=...&colormap_name=viridis&rescale=0,255
```

#### Point Query

```bash
/{prefix}/point/{lon},{lat}?url=...
```

**Response:**
```json
{
  "coordinates": [-77.0, 38.9],
  "values": [279.81634521484375],
  "band_names": ["b1"]
}
```

#### GeoJSON Feature Extraction (POST)

```bash
curl -X POST "/{prefix}/feature.tif?url=...&max_size=512" \
  -H "Content-Type: application/json" \
  -d '{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-80,35],[-75,35],[-75,40],[-80,40],[-80,35]]]}}'
```

#### Regional Statistics (POST)

```bash
curl -X POST "/{prefix}/statistics?url=..." \
  -H "Content-Type: application/json" \
  -d '{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-80,35],[-75,35],[-75,40],[-80,40],[-80,35]]]}}'
```

**Response:**
```json
{
  "type": "Feature",
  "properties": {
    "statistics": {
      "b1": {
        "min": 271.48,
        "max": 293.18,
        "mean": 282.13,
        "std": 5.35,
        "count": 400,
        "median": 282.16,
        "valid_percent": 100.0
      }
    }
  }
}
```

---

## URL Formats

### COG URLs (GDAL Virtual Filesystem)

| Format | Pattern | Example |
|--------|---------|---------|
| **Azure Blob** | `/vsiaz/{container}/{path}` | `/vsiaz/silver-cogs/dem.tif` |
| **AWS S3** | `/vsis3/{bucket}/{path}` | `/vsis3/mybucket/dem.tif` |
| **HTTP/HTTPS** | `/vsicurl/{url}` | `/vsicurl/https://example.com/dem.tif` |

### Zarr URLs

| Format | Pattern | Recommended |
|--------|---------|-------------|
| **HTTPS** | `https://{storage-account}.blob.core.windows.net/{container}/{path}.zarr` | Yes |
| **ABFS (full)** | `abfs://{container}@{storage-account}.dfs.core.windows.net/{path}.zarr` | Yes |
| **ABFS (simple)** | `abfs://{container}/{path}.zarr` | Needs env var |

---

## Query Parameters

### Common Parameters (All Endpoints)

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `url` | string | **Required.** Data source URL | `/vsiaz/container/file.tif` |

### Tile Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `bidx` | int/list | Band index(es), 1-based | `1` or `1,2,3` |
| `colormap_name` | string | Named colormap | `viridis`, `turbo`, `plasma` |
| `rescale` | string | Min,max rescaling | `0,255` or `250,320` |
| `nodata` | float | NoData value | `-9999` |
| `return_mask` | bool | Include alpha mask | `true` |

### Xarray-Specific Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `variable` | string | **Required.** Variable name | `tasmax`, `precipitation` |
| `decode_times` | bool | Decode time coordinates | `false` for CMIP6 |
| `time` | string | Time slice (ISO format) | `2050-01-01` |

### Output Format Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `format` | string | Output format | `png`, `jpg`, `webp`, `tif`, `npy` |
| `width` | int | Output width | `512` |
| `height` | int | Output height | `512` |
| `max_size` | int | Max dimension | `1024` |

### Available Colormaps

```
viridis, plasma, inferno, magma, cividis,
turbo, rainbow, jet, hot, cool,
spring, summer, autumn, winter,
gray, bone, copper, pink,
terrain, ocean, gist_earth
```

---

## Test Data

### CMIP6 Sample Zarr (Silver Storage Account)

| Property | Value |
|----------|-------|
| **Storage** | **Silver Storage Account** |
| **Container** | `silver-cogs` |
| **Path** | `test-zarr/cmip6-tasmax-sample.zarr` |
| **Variable** | `tasmax` (Daily Max Temperature, Kelvin) |
| **Time Steps** | 730 (2 years daily, 2004-2005) |
| **Coverage** | Global (0.25 degree resolution) |

**URL Pattern:**
```
https://{silver-storage-account}.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr
```

### ERA5 Sample Zarr (Silver Storage Account)

| Property | Value |
|----------|-------|
| **Storage** | **Silver Storage Account** |
| **Container** | `silver-cogs` |
| **Path** | `test-zarr/era5-global-sample.zarr/era5-global-sample.zarr` |
| **Variables** | 9 meteorological variables (see below) |
| **Time Steps** | Multiple (hourly, starting Jan 1, 2020) |
| **Coverage** | Global (0.25 degree resolution) |

**Available Variables:**
- `air_temperature_at_2_metres` - 2m air temperature (K)
- `air_pressure_at_mean_sea_level` - Sea level pressure (Pa)
- `dew_point_temperature_at_2_metres` - 2m dewpoint (K)
- `sea_surface_temperature` - SST (K)
- `surface_air_pressure` - Surface pressure (Pa)
- `eastward_wind_at_10_metres` / `northward_wind_at_10_metres` - 10m wind (m/s)
- `eastward_wind_at_100_metres` / `northward_wind_at_100_metres` - 100m wind (m/s)

**URL Pattern:**
```
https://{silver-storage-account}.blob.core.windows.net/silver-cogs/test-zarr/era5-global-sample.zarr/era5-global-sample.zarr
```

**Example - ERA5 temperature tile:**
```bash
/xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=https://{silver-storage-account}.blob.core.windows.net/silver-cogs/test-zarr/era5-global-sample.zarr/era5-global-sample.zarr&variable=air_temperature_at_2_metres&decode_times=false&bidx=1&colormap_name=turbo&rescale=220,320
```

### Planetary Computer Public Data (External)

| Dataset | URL |
|---------|-----|
| **gridMET** | `https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr` |
| **Daymet Hawaii** | `https://daymeteuwest.blob.core.windows.net/daymet-zarr/daily/hi.zarr` |
| **Daymet PR** | `https://daymeteuwest.blob.core.windows.net/daymet-zarr/daily/pr.zarr` |

---

## Error Reference

### Common Errors

| Error / Symptom | Cause | Solution |
|-----------------|-------|----------|
| **Static noise / meaningless image** | Missing `bidx` - all time steps aggregated | Add `&bidx=1` to select a time step |
| `Maximum array limit reached` | Missing `bidx` for temporal Zarr | Add `&bidx=1` |
| `unable to decode time units` | CMIP6 noleap calendar | Add `&decode_times=false` |
| `403 Forbidden` | OAuth token expired | Check `/healthz`, restart app |
| `404 Not Found` | Invalid URL path | Verify blob/container exists |
| `500 Internal Server Error` | Various | Check logs, verify URL format |

### HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process response |
| 400 | Bad Request | Check query parameters |
| 403 | Forbidden | Authentication issue |
| 404 | Not Found | Check URL path |
| 500 | Server Error | Check logs, retry |
| 504 | Gateway Timeout | Data too large, increase timeout |

---

## Documentation Index

### Getting Started
| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Project overview |
| [ONBOARDING.md](ONBOARDING.md) | New developer guide |
| [README-LOCAL.md](README-LOCAL.md) | Local development setup |

### API & Implementation
| Document | Purpose |
|----------|---------|
| [docs/TITILER-API-REFERENCE.md](docs/TITILER-API-REFERENCE.md) | Complete API reference |
| [xarray.md](xarray.md) | Xarray/Zarr implementation guide |
| [SERVICE-LAYER-API-DESIGN.md](SERVICE-LAYER-API-DESIGN.md) | Future service layer design |

### Deployment
| Document | Purpose |
|----------|---------|
| [CLAUDE.md](CLAUDE.md) | Deployment resume guide |
| [QA_DEPLOYMENT.md](QA_DEPLOYMENT.md) | QA environment deployment |
| [NEW_TENANT_DEPLOYMENT.md](NEW_TENANT_DEPLOYMENT.md) | Multi-tenant deployment |
| [docs/AZURE-CONFIGURATION-REFERENCE.md](docs/AZURE-CONFIGURATION-REFERENCE.md) | Azure settings reference |
| [docs/DEPLOYMENT-TROUBLESHOOTING.md](docs/DEPLOYMENT-TROUBLESHOOTING.md) | Troubleshooting guide |

### Architecture
| Document | Purpose |
|----------|---------|
| [docs/OAUTH-TOKEN-APPROACH.md](docs/OAUTH-TOKEN-APPROACH.md) | OAuth authentication design |
| [docs/PGSTAC-IMPLEMENTATION.md](docs/PGSTAC-IMPLEMENTATION.md) | pgSTAC integration details |
| [docs/implementation/OAUTH-ARCHITECTURE.md](docs/implementation/OAUTH-ARCHITECTURE.md) | OAuth architecture deep-dive |

---

## Quick Reference Card

### COG Tile URL Template
```
/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=/vsiaz/{container}/{path}.tif
```

### Zarr Tile URL Template
```
/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url=https://{silver-storage-account}.blob.core.windows.net/{container}/{path}.zarr&variable={var}&decode_times=false&bidx=1
```

### Health Check
```bash
curl https://{titiler-service-url}/healthz
```

### Interactive Viewers
```
# COG Viewer
/cog/WebMercatorQuad/map.html?url=/vsiaz/{container}/{path}.tif

# Zarr Viewer
/xarray/WebMercatorQuad/map.html?url={zarr_url}&variable={var}&decode_times=false&bidx=1&colormap_name=turbo&rescale=250,320
```

---

## Environment Mapping (Reference Only)

**Work items should use logical names, not these resource names.**

| Logical Name | QA Environment Resource |
|--------------|-------------------------|
| **Silver Storage Account** | See deployment docs |
| **TiTiler Raster Service** | See deployment docs |
| **Business Database** | See deployment docs |
| **App Reader Identity** | See deployment docs |

For current environment mappings, see environment-specific deployment documentation.

---

**Maintained by:** Geospatial Data Hub Team
**Repository:** rmhtitiler
