# TiTiler API Reference for STAC Integration

**Date:** November 7, 2025
**Production Endpoint:** `https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net`
**Storage Account:** `rmhazuregeo`
**Container:** `silver-cogs`

---

## Overview

This document provides the complete TiTiler API reference for integration with the Geospatial ETL Pipeline and STAC catalog. All endpoints are verified working in production with Azure Managed Identity authentication.

---

## Base URL Pattern

```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/{endpoint}
```

---

## COG URL Format

All endpoints accept a `url` parameter pointing to the COG file in Azure Blob Storage:

```
url=/vsiaz/{container}/{path/to/file.tif}
```

**Example:**
```
url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif
```

**Important:** The `/vsiaz/` prefix is GDAL's virtual file system for Azure Blob Storage. TiTiler uses GDAL internally and expects this format.

---

## Core Endpoints for STAC Integration

### 1. COG Metadata (Info)

**Purpose:** Get detailed metadata about the COG including bounds, CRS, bands, and data type.

**Endpoint:** `/cog/info`

**Method:** `GET`

**Parameters:**
- `url` (required): GDAL-compatible path to COG

**URL Pattern:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/{container}/{blob_path}
```

**Example:**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"
```

**Response Schema:**
```json
{
  "bounds": [minx, miny, maxx, maxy],
  "minzoom": 0,
  "maxzoom": 24,
  "band_metadata": [
    ["b1", {}],
    ["b2", {}],
    ["b3", {}]
  ],
  "band_descriptions": [
    ["b1", ""],
    ["b2", ""],
    ["b3", ""]
  ],
  "dtype": "uint8",
  "nodata_type": "Nodata",
  "colorinterp": ["red", "green", "blue"],
  "driver": "GTiff",
  "count": 3,
  "width": 12288,
  "height": 12288,
  "overviews": [2, 4, 8, 16, 32]
}
```

**STAC Integration:**
- Use `bounds` for STAC item bbox
- Use `band_metadata` for asset bands
- Use `dtype` for data type
- Use `width`/`height` for dimensions

---

### 2. Band Statistics

**Purpose:** Get statistical information (min, max, mean, stddev) for each band.

**Endpoint:** `/cog/statistics`

**Method:** `GET`

**Parameters:**
- `url` (required): GDAL-compatible path to COG

**URL Pattern:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/statistics?url=/vsiaz/{container}/{blob_path}
```

**Example:**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/statistics?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"
```

**Response Schema:**
```json
{
  "b1": {
    "min": 0.0,
    "max": 255.0,
    "mean": 127.5,
    "count": 150994944.0,
    "sum": 19251905280.0,
    "std": 73.7,
    "median": 128.0,
    "majority": 255.0,
    "minority": 0.0,
    "unique": 256.0,
    "histogram": [[...], [...]]
  },
  "b2": { ... },
  "b3": { ... }
}
```

**STAC Integration:**
- Add to STAC item properties under `raster:bands`
- Use for data quality metrics

---

### 3. GeoJSON Bounds

**Purpose:** Get the geographic bounds as a GeoJSON feature.

**Endpoint:** `/cog/info.geojson`

**Method:** `GET`

**Parameters:**
- `url` (required): GDAL-compatible path to COG

**URL Pattern:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info.geojson?url=/vsiaz/{container}/{blob_path}
```

**Example:**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info.geojson?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"
```

**Response Schema:**
```json
{
  "type": "Feature",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[...]]
  },
  "properties": {
    "bounds": [minx, miny, maxx, maxy],
    "minzoom": 0,
    "maxzoom": 24
  }
}
```

**STAC Integration:**
- Use directly as STAC item geometry
- Simplifies geometry extraction

---

### 4. Tile Endpoints (XYZ)

**Purpose:** Get raster tiles for visualization.

**Endpoint:** `/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}.{format}`

**Method:** `GET`

**Parameters:**
- `tileMatrixSetId`: `WebMercatorQuad` or `WorldCRS84Quad`
- `z`: Zoom level (0-24)
- `x`: Tile column
- `y`: Tile row
- `format`: `png`, `jpg`, `webp`, `npy` (default: png)
- `url` (query param, required): GDAL-compatible path to COG

**URL Pattern:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}.png?url=/vsiaz/{container}/{blob_path}
```

**Example:**
```bash
# WebMercator tile (most common for web maps)
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/15/9373/12532.png?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif" --output tile.png
```

**Tile Matrix Sets:**
- `WebMercatorQuad` - EPSG:3857 (standard web maps)
- `WorldCRS84Quad` - EPSG:4326 (geographic coordinates)

**STAC Integration:**
- Add tile endpoint URL template to STAC item assets
- Enable dynamic visualization without pre-generating tiles

---

### 5. TileJSON

**Purpose:** Get TileJSON specification for tile endpoints (compatible with Mapbox GL, Leaflet).

**Endpoint:** `/cog/{tileMatrixSetId}/tilejson.json`

**Method:** `GET`

**Parameters:**
- `tileMatrixSetId`: `WebMercatorQuad` or `WorldCRS84Quad`
- `url` (query param, required): GDAL-compatible path to COG

**URL Pattern:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/{tileMatrixSetId}/tilejson.json?url=/vsiaz/{container}/{blob_path}
```

**Example:**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/tilejson.json?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"
```

**Response Schema:**
```json
{
  "tilejson": "2.2.0",
  "name": "rmhtitiler",
  "version": "1.0.0",
  "scheme": "xyz",
  "tiles": [
    "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"
  ],
  "minzoom": 0,
  "maxzoom": 24,
  "bounds": [minx, miny, maxx, maxy],
  "center": [centerx, centery, zoom]
}
```

**STAC Integration:**
- Add TileJSON URL to STAC item links with `rel: "tilejson"`
- Enables easy map integration

---

### 6. Interactive Map Viewer

**Purpose:** Interactive HTML map viewer with pan/zoom.

**Endpoint:** `/cog/{tileMatrixSetId}/map.html`

**Method:** `GET`

**Parameters:**
- `tileMatrixSetId`: `WebMercatorQuad` or `WorldCRS84Quad`
- `url` (query param, required): GDAL-compatible path to COG

**URL Pattern:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/{tileMatrixSetId}/map.html?url=/vsiaz/{container}/{blob_path}
```

**Example:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif
```

**STAC Integration:**
- Add viewer URL to STAC item links with `rel: "preview"`
- Provides instant visualization for users

---

### 7. Preview Image

**Purpose:** Generate a static preview image of the entire COG.

**Endpoint:** `/cog/preview.{format}`

**Method:** `GET`

**Parameters:**
- `format`: `png`, `jpg`, `webp`, `npy` (default: png)
- `url` (query param, required): GDAL-compatible path to COG
- `width` (optional): Output width in pixels
- `height` (optional): Output height in pixels
- `max_size` (optional): Maximum dimension (default: 1024)

**URL Pattern:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/preview.png?url=/vsiaz/{container}/{blob_path}
```

**Example:**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/preview.png?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif&max_size=512" --output preview.png
```

**STAC Integration:**
- Generate thumbnail for STAC item assets
- Add to assets with role `thumbnail`

---

### 8. WMTS Capabilities

**Purpose:** Get OGC WMTS capabilities XML document.

**Endpoint:** `/cog/{tileMatrixSetId}/WMTSCapabilities.xml`

**Method:** `GET`

**Parameters:**
- `tileMatrixSetId`: `WebMercatorQuad` or `WorldCRS84Quad`
- `url` (query param, required): GDAL-compatible path to COG

**URL Pattern:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/{tileMatrixSetId}/WMTSCapabilities.xml?url=/vsiaz/{container}/{blob_path}
```

**STAC Integration:**
- Add WMTS capabilities URL for OGC-compatible clients
- Link with `rel: "wmts"`

---

## Python Code Examples for STAC Catalog Integration

### Generate STAC Item with TiTiler Links

```python
import requests
from datetime import datetime

# Configuration
TITILER_BASE = "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"
CONTAINER = "silver-cogs"
BLOB_NAME = "copy47_of_dctest3_R1C2_cog_analysis.tif"
COG_URL = f"/vsiaz/{CONTAINER}/{BLOB_NAME}"

def create_stac_item_with_titiler(blob_name: str, container: str = "silver-cogs") -> dict:
    """
    Create a STAC item with TiTiler visualization links.

    Args:
        blob_name: Name of the COG file in Azure Blob Storage
        container: Container name (default: silver-cogs)

    Returns:
        STAC item dictionary
    """
    cog_url = f"/vsiaz/{container}/{blob_name}"

    # Get COG metadata from TiTiler
    info_url = f"{TITILER_BASE}/cog/info?url={cog_url}"
    info_response = requests.get(info_url)
    info = info_response.json()

    # Get GeoJSON bounds
    geojson_url = f"{TITILER_BASE}/cog/info.geojson?url={cog_url}"
    geojson_response = requests.get(geojson_url)
    geojson = geojson_response.json()

    # Get statistics (optional but recommended)
    stats_url = f"{TITILER_BASE}/cog/statistics?url={cog_url}"
    stats_response = requests.get(stats_url)
    stats = stats_response.json()

    # Create STAC item
    stac_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": blob_name.replace(".tif", ""),
        "geometry": geojson["geometry"],
        "bbox": info["bounds"],
        "properties": {
            "datetime": datetime.utcnow().isoformat() + "Z",
            "proj:epsg": None,  # Extract from info if available
            "proj:shape": [info["height"], info["width"]],
        },
        "assets": {
            "cog": {
                "href": f"https://rmhazuregeo.blob.core.windows.net/{container}/{blob_name}",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data"],
                "raster:bands": [
                    {
                        "data_type": info["dtype"],
                        "statistics": {
                            "minimum": stats[band]["min"],
                            "maximum": stats[band]["max"],
                            "mean": stats[band]["mean"],
                            "stddev": stats[band]["std"]
                        }
                    }
                    for band in stats.keys()
                ]
            },
            "thumbnail": {
                "href": f"{TITILER_BASE}/cog/preview.png?url={cog_url}&max_size=256",
                "type": "image/png",
                "roles": ["thumbnail"]
            }
        },
        "links": [
            {
                "rel": "self",
                "href": f"https://your-stac-api.com/collections/cogs/items/{blob_name.replace('.tif', '')}"
            },
            {
                "rel": "collection",
                "href": "https://your-stac-api.com/collections/cogs"
            },
            {
                "rel": "tilejson",
                "href": f"{TITILER_BASE}/cog/WebMercatorQuad/tilejson.json?url={cog_url}",
                "type": "application/json",
                "title": "TileJSON for visualization"
            },
            {
                "rel": "preview",
                "href": f"{TITILER_BASE}/cog/WebMercatorQuad/map.html?url={cog_url}",
                "type": "text/html",
                "title": "Interactive map viewer"
            },
            {
                "rel": "wmts",
                "href": f"{TITILER_BASE}/cog/WebMercatorQuad/WMTSCapabilities.xml?url={cog_url}",
                "type": "application/xml",
                "title": "WMTS capabilities"
            }
        ]
    }

    return stac_item

# Example usage
stac_item = create_stac_item_with_titiler("copy47_of_dctest3_R1C2_cog_analysis.tif")
print(json.dumps(stac_item, indent=2))
```

---

### Bulk Processing for ETL Pipeline

```python
from typing import List
from azure.storage.blob import BlobServiceClient
import concurrent.futures

def process_cog_for_stac(blob_name: str, container: str = "silver-cogs") -> dict:
    """Process a single COG and create STAC item."""
    try:
        return create_stac_item_with_titiler(blob_name, container)
    except Exception as e:
        print(f"Error processing {blob_name}: {e}")
        return None

def batch_create_stac_items(container: str = "silver-cogs", pattern: str = "*.tif") -> List[dict]:
    """
    Process all COGs in a container and create STAC items.

    Args:
        container: Azure Blob Storage container name
        pattern: Glob pattern for COG files

    Returns:
        List of STAC item dictionaries
    """
    # Connect to Azure Blob Storage
    blob_service_client = BlobServiceClient(
        account_url="https://rmhazuregeo.blob.core.windows.net",
        credential=DefaultAzureCredential()
    )

    container_client = blob_service_client.get_container_client(container)

    # List all COG files
    blobs = [blob.name for blob in container_client.list_blobs() if blob.name.endswith('.tif')]

    print(f"Found {len(blobs)} COG files to process")

    # Process in parallel
    stac_items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_cog_for_stac, blob, container): blob for blob in blobs}

        for future in concurrent.futures.as_completed(futures):
            blob = futures[future]
            try:
                stac_item = future.result()
                if stac_item:
                    stac_items.append(stac_item)
                    print(f"✓ Processed {blob}")
            except Exception as e:
                print(f"✗ Failed {blob}: {e}")

    return stac_items

# Example usage
stac_items = batch_create_stac_items("silver-cogs")
print(f"Created {len(stac_items)} STAC items")
```

---

### Generate Tile URL Template for STAC

```python
def get_tile_url_template(container: str, blob_name: str, tile_matrix: str = "WebMercatorQuad") -> str:
    """
    Generate XYZ tile URL template for STAC item.

    Args:
        container: Azure Blob Storage container
        blob_name: COG filename
        tile_matrix: Tile matrix set (WebMercatorQuad or WorldCRS84Quad)

    Returns:
        URL template with {z}/{x}/{y} placeholders
    """
    cog_url = f"/vsiaz/{container}/{blob_name}"
    return f"{TITILER_BASE}/cog/tiles/{tile_matrix}/{{z}}/{{x}}/{{y}}.png?url={cog_url}"

# Example
tile_template = get_tile_url_template("silver-cogs", "copy47_of_dctest3_R1C2_cog_analysis.tif")
print(tile_template)
# Output: https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif
```

---

## URL Encoding Considerations

When constructing URLs programmatically, ensure proper URL encoding:

```python
from urllib.parse import quote

container = "silver-cogs"
blob_name = "path/to/my file with spaces.tif"
cog_url = f"/vsiaz/{container}/{blob_name}"

# URL encode the cog_url parameter
encoded_cog_url = quote(cog_url, safe='')
info_url = f"{TITILER_BASE}/cog/info?url={encoded_cog_url}"
```

---

## Health Check

**Endpoint:** `/healthz`

**Purpose:** Verify TiTiler service is running and SAS token authentication is working.

**URL:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz
```

**Example Response:**
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "use_sas_token": true,
  "local_mode": false,
  "storage_account": "rmhazuregeo",
  "sas_token_expires_in_seconds": 3585
}
```

**Use in ETL Pipeline:**
- Check before processing batch
- Monitor SAS token expiration
- Verify service availability

---

## Rate Limiting and Performance

### Current Configuration:
- **Workers:** 1 (can scale to 2-4 for production)
- **App Service Tier:** B1 Basic (can upgrade to P1V2 for production)
- **SAS Token Refresh:** Every 55 minutes (1 hour expiry, 5 min buffer)

### Recommendations for ETL Integration:
1. **Batch Processing:** Process COGs in parallel but limit concurrent TiTiler requests to 10-20
2. **Caching:** Cache TiTiler metadata responses to reduce API calls
3. **Retry Logic:** Implement exponential backoff for failed requests
4. **Health Checks:** Check `/healthz` before batch operations

---

## Error Handling

### Common HTTP Status Codes:

| Status Code | Meaning | Action |
|-------------|---------|--------|
| 200 | Success | Process response |
| 404 | COG not found or invalid path | Check blob exists and path is correct |
| 403 | Authentication failure | Check SAS token is valid (check /healthz) |
| 500 | Server error | Retry with exponential backoff |
| 504 | Gateway timeout | COG may be too large, retry or increase timeout |

### Example Error Response:
```json
{
  "detail": "GDAL signalled an error: err_no=11, msg='HTTP response code: 403'"
}
```

---

## OpenAPI Documentation

**Interactive API Docs:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/docs
```

**OpenAPI JSON Spec:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/openapi.json
```

---

## Quick Reference: Essential URLs for STAC

| Purpose | URL Pattern | Example |
|---------|-------------|---------|
| **Metadata** | `/cog/info?url={cog_url}` | [Info](https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif) |
| **GeoJSON** | `/cog/info.geojson?url={cog_url}` | [GeoJSON](https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info.geojson?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif) |
| **Statistics** | `/cog/statistics?url={cog_url}` | [Stats](https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/statistics?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif) |
| **Tiles (XYZ)** | `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={cog_url}` | [Tile](https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/15/9373/12532.png?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif) |
| **TileJSON** | `/cog/WebMercatorQuad/tilejson.json?url={cog_url}` | [TileJSON](https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/tilejson.json?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif) |
| **Viewer** | `/cog/WebMercatorQuad/map.html?url={cog_url}` | [Viewer](https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif) |
| **Thumbnail** | `/cog/preview.png?url={cog_url}&max_size=256` | [Preview](https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/preview.png?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif&max_size=256) |

**Note:** Replace `{cog_url}` with `/vsiaz/{container}/{blob_path}` (URL-encoded if needed)

---

## Support and Troubleshooting

**Documentation:**
- Full deployment troubleshooting: [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md)
- Authentication verification: [AUTHENTICATION-VERIFICATION.md](AUTHENTICATION-VERIFICATION.md)
- Azure configuration: [AZURE-CONFIGURATION-REFERENCE.md](AZURE-CONFIGURATION-REFERENCE.md)

**Common Issues:**
1. **403 Forbidden:** SAS token expired or invalid - check `/healthz` endpoint
2. **404 Not Found:** COG path incorrect - verify blob exists in container
3. **GDAL Error:** Check COG is valid Cloud-Optimized GeoTIFF

---

---

## Xarray/Zarr Endpoints (Multidimensional Data)

TiTiler also supports multidimensional data (Zarr, NetCDF) via the `/xarray/*` endpoints. These endpoints use Azure OAuth authentication just like COG endpoints.

### Zarr URL Formats

| Format | Pattern | Recommended |
|--------|---------|-------------|
| **HTTPS** | `https://{account}.blob.core.windows.net/{container}/{path}.zarr` | ✅ Yes |
| **ABFS (full)** | `abfs://{container}@{account}.dfs.core.windows.net/{path}.zarr` | ✅ Yes |
| **ABFS (simple)** | `abfs://{container}/{path}.zarr` | ⚠️ Requires env var |

### Critical Parameters for Temporal Data

| Parameter | Required | Purpose |
|-----------|----------|---------|
| `variable` | **Yes** | Which variable to render |
| `bidx` | **Yes** (temporal) | Band/time index (1-based) |
| `decode_times` | **Yes** (CMIP6) | Set to `false` for noleap calendars |

### 1. List Variables

**Endpoint:** `/xarray/variables`

**Purpose:** List all variables in a Zarr store.

**URL Pattern:**
```
/xarray/variables?url={zarr_url}&decode_times=false
```

**Example:**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/xarray/variables?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&decode_times=false"
```

**Response:**
```json
["tasmax"]
```

---

### 2. Variable Info

**Endpoint:** `/xarray/info`

**Purpose:** Get metadata for a specific variable.

**URL Pattern:**
```
/xarray/info?url={zarr_url}&variable={var}&decode_times=false
```

**Example:**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/xarray/info?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false"
```

**Response includes:**
- `bounds`: Geographic extent
- `crs`: Coordinate reference system
- `band_metadata`: Metadata for each time step

---

### 3. Tiles (XYZ)

**Endpoint:** `/xarray/tiles/{tileMatrixSetId}/{z}/{x}/{y}@{scale}x.{format}`

**Purpose:** Get raster tiles from Zarr data.

**⚠️ CRITICAL:** For temporal data, you **MUST** include `bidx` parameter or you will get "Maximum array limit reached" error.

**URL Pattern:**
```
/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url={zarr_url}&variable={var}&decode_times=false&bidx=1
```

**Example (basic):**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false&bidx=1" --output tile.png
```

**Example (with colormap and rescaling):**
```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false&bidx=1&colormap_name=turbo&rescale=250,320" --output tile_colored.png
```

---

### 4. Interactive Map Viewer

**Endpoint:** `/xarray/{tileMatrixSetId}/map.html`

**Purpose:** Interactive HTML map viewer for Zarr data.

**URL Pattern:**
```
/xarray/WebMercatorQuad/map.html?url={zarr_url}&variable={var}&decode_times=false&bidx=1&colormap_name=turbo&rescale=250,320
```

**Example:**
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/xarray/WebMercatorQuad/map.html?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false&bidx=1&colormap_name=turbo&rescale=250,320
```

---

### Query Parameters Reference

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `url` | string | **Required.** Zarr store URL | `https://account.blob.../store.zarr` |
| `variable` | string | **Required.** Variable name | `tasmax`, `pr` |
| `bidx` | int | **Required for temporal.** Time step (1-based) | `1`, `365` |
| `decode_times` | bool | Disable time decoding | `false` |
| `colormap_name` | string | Named colormap | `viridis`, `turbo`, `plasma` |
| `rescale` | string | Min,max scaling | `250,320` |
| `nodata` | float | NoData value | `-9999` |

---

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Maximum array limit reached` | Missing `bidx` | Add `&bidx=1` |
| `unable to decode time units` | CMIP6 noleap calendar | Add `&decode_times=false` |
| `Internal Server Error` | Wrong URL format | Use HTTPS or full ABFS URL |

---

### Test Data

A sample CMIP6 Zarr is available for testing:

| Property | Value |
|----------|-------|
| Storage Account | `rmhazuregeo` |
| Container | `silver-cogs` |
| Path | `test-zarr/cmip6-tasmax-sample.zarr` |
| Variable | `tasmax` (Daily Max Temperature, Kelvin) |
| Time Steps | 730 (2 years) |
| Coverage | Global (0.25° resolution) |

---

## Quick Reference: Xarray URLs

| Purpose | URL |
|---------|-----|
| **Variables** | `/xarray/variables?url={zarr}&decode_times=false` |
| **Info** | `/xarray/info?url={zarr}&variable={var}&decode_times=false` |
| **Tile** | `/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url={zarr}&variable={var}&decode_times=false&bidx=1` |
| **Viewer** | `/xarray/WebMercatorQuad/map.html?url={zarr}&variable={var}&decode_times=false&bidx=1&colormap_name=turbo&rescale=250,320` |

---

## Data Extraction Endpoints

TiTiler provides several endpoints for extracting raster data as files or values. These work for both COG (`/cog/*`) and Zarr (`/xarray/*`) data.

### Output Formats

| Format | Extension | Description | Use Case |
|--------|-----------|-------------|----------|
| **GeoTIFF** | `.tif` | Georeferenced raster | GIS analysis, further processing |
| **PNG** | `.png` | Rendered image with colormap | Visualization, reports |
| **JPEG** | `.jpg` | Compressed image | Web display |
| **WebP** | `.webp` | Modern compressed format | Web applications |
| **NumPy** | `.npy` | Raw array data | Python/scientific analysis |

---

### 1. Bounding Box Extraction

**Endpoint:** `GET /cog/bbox/{minx},{miny},{maxx},{maxy}.{format}`

**Purpose:** Extract raster data within a geographic bounding box.

**Parameters:**
| Parameter | Required | Description |
|-----------|----------|-------------|
| `minx, miny, maxx, maxy` | Yes | Bounding box coordinates (path) |
| `format` | Yes | Output format: `tif`, `png`, `jpg`, `webp`, `npy` |
| `url` | Yes | Dataset URL |
| `bidx` | For Zarr | Band index (1-based) for temporal data |
| `width`, `height` | No | Output dimensions (alternative path format) |
| `colormap_name` | No | Named colormap for PNG/JPG |
| `rescale` | No | Min,max for scaling |
| `nodata` | No | NoData value override |

**URL Patterns:**
```bash
# Auto-sized output (native resolution within limits)
/cog/bbox/{minx},{miny},{maxx},{maxy}.tif?url={cog_url}

# Specific output dimensions
/cog/bbox/{minx},{miny},{maxx},{maxy}/{width}x{height}.tif?url={cog_url}
```

**Example - Extract US region as GeoTIFF:**
```bash
curl "https://rmhtitiler.../xarray/bbox/-125,25,-65,50.tif?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false&bidx=1" -o us_extract.tif
```

**Example - Extract with specific dimensions and colormap:**
```bash
curl "https://rmhtitiler.../xarray/bbox/-125,25,-65,50/512x256.png?url=...&variable=tasmax&decode_times=false&bidx=1&colormap_name=turbo&rescale=250,320" -o us_temp.png
```

**Response:**
- Binary file in requested format
- GeoTIFF includes full georeference metadata

---

### 2. Point Query

**Endpoint:** `GET /cog/point/{lon},{lat}`

**Purpose:** Get raster value(s) at a specific coordinate.

**Parameters:**
| Parameter | Required | Description |
|-----------|----------|-------------|
| `lon, lat` | Yes | Coordinates (path) |
| `url` | Yes | Dataset URL |
| `bidx` | For Zarr | Band index for temporal data |
| `coord_crs` | No | Input coordinate CRS (default: EPSG:4326) |

**Example:**
```bash
curl "https://rmhtitiler.../xarray/point/-77.0,38.9?url=...&variable=tasmax&decode_times=false&bidx=1"
```

**Response:**
```json
{
  "coordinates": [-77.0, 38.9],
  "values": [279.81634521484375],
  "band_names": ["b1"]
}
```

---

### 3. GeoJSON Feature Extraction (Clip to Polygon)

**Endpoint:** `POST /cog/feature.{format}`

**Purpose:** Clip raster data to an arbitrary GeoJSON polygon.

**Parameters:**
| Parameter | Required | Description |
|-----------|----------|-------------|
| `format` | Yes | Output format: `tif`, `png`, `jpg`, `npy` |
| `url` | Yes | Dataset URL |
| `bidx` | For Zarr | Band index |
| `max_size` | No | Maximum output dimension |
| **Body** | Yes | GeoJSON Feature with geometry |

**Request Body:**
```json
{
  "type": "Feature",
  "properties": {},
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-80, 35], [-75, 35], [-75, 40], [-80, 40], [-80, 35]
    ]]
  }
}
```

**Example:**
```bash
curl -X POST "https://rmhtitiler.../xarray/feature.tif?url=...&variable=tasmax&decode_times=false&bidx=1&max_size=512" \
  -H "Content-Type: application/json" \
  -d '{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-80,35],[-75,35],[-75,40],[-80,40],[-80,35]]]}}' \
  -o clipped.tif
```

**Response:**
- Raster clipped to polygon bounds
- Pixels outside polygon are masked/nodata

---

### 4. Statistics for Region

**Endpoint:** `POST /cog/statistics`

**Purpose:** Calculate statistics for a GeoJSON polygon region.

**Parameters:**
| Parameter | Required | Description |
|-----------|----------|-------------|
| `url` | Yes | Dataset URL |
| `bidx` | For Zarr | Band index |
| **Body** | Yes | GeoJSON Feature with geometry |

**Example:**
```bash
curl -X POST "https://rmhtitiler.../xarray/statistics?url=...&variable=tasmax&decode_times=false&bidx=1" \
  -H "Content-Type: application/json" \
  -d '{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-80,35],[-75,35],[-75,40],[-80,40],[-80,35]]]}}'
```

**Response:**
```json
{
  "type": "Feature",
  "geometry": {...},
  "properties": {
    "statistics": {
      "b1": {
        "min": 271.48,
        "max": 293.18,
        "mean": 282.13,
        "std": 5.35,
        "count": 400,
        "median": 282.16,
        "percentile_2": 271.89,
        "percentile_98": 290.92,
        "histogram": [[27, 26, 42, ...], [271.48, 273.65, ...]],
        "valid_percent": 100.0,
        "valid_pixels": 400,
        "masked_pixels": 0
      }
    }
  }
}
```

---

### Quick Reference: Extraction Endpoints

| Purpose | Method | Endpoint |
|---------|--------|----------|
| **Bbox → GeoTIFF** | GET | `/cog/bbox/{minx},{miny},{maxx},{maxy}.tif?url=...` |
| **Bbox → PNG** | GET | `/cog/bbox/{minx},{miny},{maxx},{maxy}.png?url=...&colormap_name=viridis` |
| **Bbox sized** | GET | `/cog/bbox/{minx},{miny},{maxx},{maxy}/{w}x{h}.tif?url=...` |
| **Point value** | GET | `/cog/point/{lon},{lat}?url=...` |
| **Clip to polygon** | POST | `/cog/feature.tif?url=...` + GeoJSON body |
| **Region statistics** | POST | `/cog/statistics?url=...` + GeoJSON body |

**Note:** Replace `/cog/` with `/xarray/` for Zarr data, adding `&variable=...&decode_times=false&bidx=1`.

---

**Status:** ✅ Production Ready
**Last Updated:** December 18, 2025
**Version:** 1.2.0 (Added Data Extraction endpoints)
