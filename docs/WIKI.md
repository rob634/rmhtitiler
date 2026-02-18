# TiTiler-pgSTAC Application Wiki

**Status:** Production-Ready
**Last Updated:** February 2026

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
   - [pgSTAC Search Endpoints](#pgstac-search-endpoints)
   - [STAC API Endpoints](#stac-api-endpoints)
   - [OGC Vector Endpoints](#ogc-vector-endpoints-tipg)
   - [H3 Explorer Endpoints](#h3-explorer-endpoints)
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
| **STAC Search** | Query-based mosaics via pgSTAC |
| **STAC Catalog** | Browsing and search via stac-fastapi-pgstac |
| **OGC Vector** | OGC Features API + Vector Tiles via TiPG |
| **H3 Explorer** | Crop Production & Drought Risk via DuckDB + Parquet |
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
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                              geotiler Tile Service                                    │
├──────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ /cog/*   │  │/xarray/* │  │/searches/│  │ /stac/*  │  │/vector/* │  │  /h3/*   │ │
│  │ (COGs)   │  │ (Zarr)   │  │ (pgSTAC) │  │ (STAC)   │  │ (TiPG)   │  │(DuckDB)  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘ │
│       │              │             │             │             │             │        │
│       ▼              ▼             ▼             ▼             ▼             ▼        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         Azure Auth Middleware                                    │ │
│  │            OAuth Token Acquisition + Environment Configuration                   │ │
│  └──────────────────────────────────────────────────────────────────────────────────┘ │
│       │              │             │             │             │             │        │
│       ▼              ▼             ▼             ▼             ▼             ▼        │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────────────┐  ┌──────────┐  ┌──────────┐│
│  │  GDAL    │  │ fsspec/  │  │       asyncpg           │  │  TiPG    │  │ DuckDB   ││
│  │ /vsiaz/  │  │  adlfs   │  │  pgSTAC + stac-fastapi  │  │          │  │          ││
│  └────┬─────┘  └────┬─────┘  └────────────┬────────────┘  └────┬─────┘  └────┬─────┘│
│       │              │                     │                    │             │       │
└───────┼──────────────┼─────────────────────┼────────────────────┼─────────────┼───────┘
        │              │                     │                    │             │
        ▼              ▼                     ▼                    ▼             ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌──────────┐
│ Silver Storage │ │ Silver Storage │ │ Business       │ │ Business       │ │ Parquet  │
│ Account (COGs) │ │ Account (Zarr) │ │ Database       │ │ Database       │ │ (Blob)   │
└────────────────┘ └────────────────┘ │ (pgSTAC)       │ │ (PostGIS)      │ └──────────┘
                                      └────────────────┘ └────────────────┘
```

### Internal Components

| Component | Purpose | Library |
|-----------|---------|---------|
| **TilerFactory** | COG tile serving | `titiler.core` |
| **XarrayTilerFactory** | Zarr/NetCDF tile serving | `titiler.xarray` |
| **MosaicTilerFactory** | pgSTAC search-based mosaics | `titiler.pgstac` |
| **StacApi** | STAC catalog browsing and search | `stac-fastapi-pgstac` |
| **TiPG Endpoints** | OGC Features API + Vector Tiles | `tipg` |
| **DuckDB Service** | H3 server-side parquet queries | `duckdb` |
| **AzureAuthMiddleware** | OAuth token injection | Custom |

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

### Authentication Mechanisms

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
│     • Endpoints: /searches/*, /stac/*, /vector/*                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Environment Variables

All app variables use the `GEOTILER_COMPONENT_SETTING` naming convention.

| Variable | Purpose | Example |
|----------|---------|---------|
| `GEOTILER_ENABLE_STORAGE_AUTH` | Enable Azure OAuth for blob storage | `true` |
| `GEOTILER_AUTH_USE_CLI` | Use Azure CLI (dev) vs MI (prod) | `true` / `false` |
| `GEOTILER_PG_AUTH_MODE` | DB auth: `managed_identity`, `key_vault`, `password` | `managed_identity` |
| `GEOTILER_PG_HOST` | **Business Database** server FQDN | `{db-server}.postgres.database.azure.com` |
| `GEOTILER_PG_DB` | Database name | `geoapp` |
| `GEOTILER_PG_USER` | DB username (**App Reader Identity** name) | `{reader-identity-name}` |
| `GEOTILER_PG_PORT` | PostgreSQL port | `5432` |
| `GEOTILER_PG_MI_CLIENT_ID` | User-assigned MI client ID (for `managed_identity` mode) | `{client-id-guid}` |
| `GEOTILER_PG_PASSWORD` | DB password (for `password` mode only) | `{password}` |
| `GEOTILER_KEY_VAULT_NAME` | Key Vault name (for `key_vault` mode only) | `{keyvault-name}` |
| `GEOTILER_KEY_VAULT_SECRET_NAME` | Secret name in Key Vault (for `key_vault` mode) | `postgres-password` |
| `GEOTILER_ENABLE_TIPG` | Enable TiPG OGC Features + Vector Tiles | `true` |
| `GEOTILER_TIPG_SCHEMAS` | Comma-separated PostGIS schemas | `geo` |
| `GEOTILER_TIPG_PREFIX` | URL prefix for TiPG routes | `/vector` |
| `GEOTILER_ENABLE_STAC_API` | Enable STAC API (requires TiPG) | `true` |
| `GEOTILER_STAC_PREFIX` | URL prefix for STAC routes | `/stac` |
| `GEOTILER_ENABLE_H3_DUCKDB` | Enable H3 server-side DuckDB queries | `false` |
| `GEOTILER_H3_PARQUET_URL` | Parquet file URL for H3 DuckDB | *(required if DuckDB enabled)* |
| `AZURE_TENANT_ID` | Azure AD tenant ID (third-party, not prefixed) | `{tenant-guid}` |

#### Observability Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights connection string (enables telemetry) | *(none)* |
| `GEOTILER_ENABLE_OBSERVABILITY` | Enable detailed request/latency logging | `false` |
| `GEOTILER_OBS_SLOW_REQUEST_THRESHOLD_MS` | Slow request threshold in milliseconds | `2000` |

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
| `/` | GET | Admin dashboard (HTML) |
| `/api` | GET | JSON API information and endpoint list |
| `/livez` | GET | Liveness probe (simple OK) |
| `/readyz` | GET | Readiness probe with DB connectivity |
| `/health` | GET | Detailed health with version, hardware, dependencies |
| `/docs` | GET | Interactive OpenAPI documentation (Swagger UI) |
| `/openapi.json` | GET | OpenAPI specification |

**Health Response Example:**
```json
{
  "status": "healthy",
  "version": "0.8.18.0",
  "database": { "status": "connected", "latency_ms": 12 },
  "storage_auth": { "enabled": true, "token_expires_in_sec": 3245 },
  "tipg": { "status": "ok", "collections": 7 },
  "stac_api": { "enabled": true },
  "system": { "cpu_count": 4, "memory_mb": 3500 }
}
```

---

### Admin Endpoints

**Prefix:** `/admin`

Endpoints for operational management and ETL pipeline integration.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/refresh-collections` | POST | Refresh TiPG collection catalog (picks up new PostGIS tables) |

**Authentication:** When `GEOTILER_ENABLE_ADMIN_AUTH=true`, requires an Azure AD Bearer token. The calling app's Managed Identity client ID must be listed in `GEOTILER_ADMIN_ALLOWED_APP_IDS`.

**Refresh Collections Response:**
```json
{
  "status": "success",
  "collections_before": 5,
  "collections_after": 7,
  "new_collections": ["geo.new_layer_1", "geo.new_layer_2"],
  "removed_collections": [],
  "refresh_time": "2026-02-04T22:00:00Z"
}
```

**Usage - Local development (no auth):**
```bash
curl -X POST http://localhost:8000/admin/refresh-collections
```

**Usage - Production (Azure AD auth):**
```python
from azure.identity import DefaultAzureCredential
import requests

credential = DefaultAzureCredential()
token = credential.get_token("https://management.azure.com/.default")

response = requests.post(
    f"{geotiler_url}/admin/refresh-collections",
    headers={"Authorization": f"Bearer {token.token}"}
)
```

**Environment Variables:**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEOTILER_ENABLE_ADMIN_AUTH` | No | `false` | Enable Azure AD auth for /admin/* endpoints |
| `GEOTILER_ADMIN_ALLOWED_APP_IDS` | If auth enabled | - | Comma-separated MI client IDs allowed to call /admin/* |
| `AZURE_TENANT_ID` | If auth enabled | - | Azure AD tenant ID for token validation |
| `GEOTILER_ENABLE_TIPG_CATALOG_TTL` | No | `false` | Enable automatic catalog refresh on a timer |
| `GEOTILER_TIPG_CATALOG_TTL_SEC` | No | `60` | Auto-refresh interval in seconds (when TTL enabled) |

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

### STAC API Endpoints

**Prefix:** `/stac`

STAC catalog browsing and search via stac-fastapi-pgstac. Requires TiPG to be enabled (shared asyncpg pool).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/stac` | GET | STAC API landing page |
| `/stac/conformance` | GET | OGC conformance classes |
| `/stac/collections` | GET | List all STAC collections |
| `/stac/collections/{collection_id}` | GET | Get collection metadata |
| `/stac/collections/{collection_id}/items` | GET | List items in a collection |
| `/stac/collections/{collection_id}/items/{item_id}` | GET | Get a single item |
| `/stac/search` | GET/POST | Search items by spatial/temporal/property filters |
| `/stac/queryables` | GET | List queryable properties (cross-collection) |
| `/stac/collections/{collection_id}/queryables` | GET | List queryable properties (per-collection) |

#### Example URLs

```bash
# List collections
curl https://{titiler-service-url}/stac/collections | jq

# Search items by bounding box
curl -X POST "https://{titiler-service-url}/stac/search" \
  -H "Content-Type: application/json" \
  -d '{"bbox": [-80, 35, -75, 40], "limit": 10}'

# Get items from a collection
curl "https://{titiler-service-url}/stac/collections/my-collection/items?limit=5" | jq
```

---

### OGC Vector Endpoints (TiPG)

**Prefix:** `/vector`

OGC Features API + Vector Tiles for PostGIS tables via TiPG.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/vector/collections` | GET | List PostGIS collections |
| `/vector/collections/{collection_id}` | GET | Get collection metadata |
| `/vector/collections/{collection_id}/items` | GET | Query features (GeoJSON) |
| `/vector/collections/{collection_id}/items/{item_id}` | GET | Get a single feature |
| `/vector/collections/{collection_id}/tiles/{tms}/{z}/{x}/{y}` | GET | Get vector tile (MVT) |
| `/vector/collections/{collection_id}/tilejson.json` | GET | Get TileJSON for vector tiles |
| `/vector/conformance` | GET | OGC API conformance classes |
| `/vector/diagnostics` | GET | TiPG table-discovery diagnostics |
| `/vector/diagnostics/verbose` | GET | Verbose database diagnostics |
| `/vector/diagnostics/table/{table_name}` | GET | Deep diagnostics for a specific table |

#### Example URLs

```bash
# List vector collections
curl https://{titiler-service-url}/vector/collections | jq

# Query features from a collection
curl "https://{titiler-service-url}/vector/collections/my_table/items?limit=10" | jq

# Get vector tile
curl "https://{titiler-service-url}/vector/collections/my_table/tiles/WebMercatorQuad/10/512/384"

# Run diagnostics
curl https://{titiler-service-url}/vector/diagnostics | jq
```

---

### H3 Explorer Endpoints

**Prefix:** `/h3`

H3 Crop Production & Drought Risk Explorer with optional server-side DuckDB queries.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/h3` | GET | Interactive H3 Explorer map (HTML) |
| `/h3/query` | GET | Server-side DuckDB query (when `GEOTILER_ENABLE_H3_DUCKDB=true`) |

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

---

## Error Reference

### Common Errors

| Error / Symptom | Cause | Solution |
|-----------------|-------|----------|
| **Static noise / meaningless image** | Missing `bidx` - all time steps aggregated | Add `&bidx=1` to select a time step |
| `Maximum array limit reached` | Missing `bidx` for temporal Zarr | Add `&bidx=1` |
| `unable to decode time units` | CMIP6 noleap calendar | Add `&decode_times=false` |
| `403 Forbidden` | OAuth token expired | Check `/health`, restart app |
| `404 Not Found` | Invalid URL path | Verify blob/container exists |
| `500 Internal Server Error` | Various | Check logs, verify URL format |
| `permission denied for table X` | Missing SELECT grant | See note below on `ALTER DEFAULT PRIVILEGES` |
| **New tables not visible in /vector** | ETL creates tables, reader can't access | `ALTER DEFAULT PRIVILEGES` is per-grantor - see [QA_DEPLOYMENT.md](QA_DEPLOYMENT.md#issue-tables-created-by-etl-dont-have-permissions) |

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
| [README.md](../README.md) | Project overview |
| [README-LOCAL.md](README-LOCAL.md) | Local development setup |

### API & Implementation
| Document | Purpose |
|----------|---------|
| [TITILER-API-REFERENCE.md](TITILER-API-REFERENCE.md) | Complete API reference |
| [xarray.md](xarray.md) | Xarray/Zarr implementation guide |

### Deployment
| Document | Purpose |
|----------|---------|
| [CLAUDE.md](../CLAUDE.md) | Project overview and resume guide |
| [QA_DEPLOYMENT.md](QA_DEPLOYMENT.md) | QA environment deployment |
| [NEW_TENANT_DEPLOYMENT.md](NEW_TENANT_DEPLOYMENT.md) | Multi-tenant deployment |
| [AZURE-CONFIGURATION-REFERENCE.md](AZURE-CONFIGURATION-REFERENCE.md) | Azure settings reference |

### Architecture
| Document | Purpose |
|----------|---------|
| [OAUTH-TOKEN-APPROACH.md](OAUTH-TOKEN-APPROACH.md) | OAuth authentication design |
| [PGSTAC-IMPLEMENTATION.md](PGSTAC-IMPLEMENTATION.md) | pgSTAC integration details |

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
curl https://{titiler-service-url}/health
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
**Repository:** geotiler
