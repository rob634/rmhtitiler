# Service Layer API Design

**Purpose:** Design document for implementing convenience wrapper endpoints and time-series extraction in a separate Azure Function App service layer.

**Date:** December 18, 2025

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Service Layer (Function App)                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Convenience    │  │   Time-Series   │  │     Batch       │             │
│  │  Wrapper API    │  │   Extraction    │  │   Processing    │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
└───────────┼─────────────────────┼─────────────────────┼─────────────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│     TiTiler       │  │   OGC Features    │  │     STAC API      │
│   (Raster Tiles   │  │    (PostGIS)      │  │    (pgSTAC)       │
│   & Extraction)   │  │                   │  │                   │
└───────────────────┘  └───────────────────┘  └───────────────────┘
```

### Service Responsibilities

| Service | Responsibility |
|---------|---------------|
| **TiTiler** | Raster tile serving, single-band extraction, point queries |
| **OGC Features** | Vector data from PostGIS tables |
| **STAC API** | Metadata catalog, search, asset discovery |
| **Service Layer** | Orchestration, convenience endpoints, time-series, batching |

---

## Part B: Convenience Wrapper API

### Problem Statement

TiTiler's raw endpoints require:
- Full blob storage URLs
- Knowledge of `bidx`, `decode_times`, `variable` parameters
- URL construction for each request

### Solution: Simplified Endpoints

The service layer provides intuitive endpoints that:
1. Look up asset URLs from STAC catalog
2. Apply sensible defaults
3. Handle parameter translation
4. Support friendly identifiers instead of raw URLs

---

### Proposed Endpoints

#### 1. Extract by STAC Item ID

```
GET /api/extract/{collection}/{item_id}
    ?bbox={minx},{miny},{maxx},{maxy}
    &format=tif|png|npy
    &asset=visual|data|zarr
    &time_index=1
    &colormap=turbo
    &rescale=auto
```

**Example:**
```bash
# Instead of:
curl "https://titiler.../xarray/bbox/-125,25,-65,50.tif?url=https://rmhazuregeo.blob.core.windows.net/silver-cogs/test-zarr/cmip6-tasmax-sample.zarr&variable=tasmax&decode_times=false&bidx=1"

# Use:
curl "https://api.../extract/cmip6/tasmax-ssp585?bbox=-125,25,-65,50&format=tif&time_index=1"
```

**Implementation:**
```python
@app.route("/api/extract/{collection}/{item_id}")
async def extract_by_item(
    collection: str,
    item_id: str,
    bbox: str,
    format: str = "tif",
    asset: str = "data",
    time_index: int = 1,
    colormap: str = None,
    rescale: str = None
):
    # 1. Look up STAC item
    item = await stac_client.get_item(collection, item_id)

    # 2. Get asset URL
    asset_url = item["assets"][asset]["href"]
    media_type = item["assets"][asset].get("type", "")

    # 3. Determine if COG or Zarr
    is_zarr = "zarr" in media_type.lower()

    # 4. Build TiTiler URL
    if is_zarr:
        variable = item["properties"].get("cube:variables", {}).keys()[0]
        titiler_url = f"{TITILER_BASE}/xarray/bbox/{bbox}.{format}"
        params = {
            "url": asset_url,
            "variable": variable,
            "decode_times": "false",
            "bidx": time_index
        }
    else:
        titiler_url = f"{TITILER_BASE}/cog/bbox/{bbox}.{format}"
        params = {"url": asset_url}

    if colormap:
        params["colormap_name"] = colormap
    if rescale:
        params["rescale"] = rescale

    # 5. Proxy request to TiTiler
    response = await http_client.get(titiler_url, params=params)
    return Response(content=response.content, media_type=response.headers["content-type"])
```

---

#### 2. Point Query by Location Name

```
GET /api/point/{collection}/{item_id}
    ?location={name}|{lon},{lat}
    &time_index=1
```

**Example:**
```bash
# Query temperature at a named location
curl "https://api.../point/cmip6/tasmax-ssp585?location=washington_dc&time_index=1"

# Or by coordinates
curl "https://api.../point/cmip6/tasmax-ssp585?location=-77.0,38.9&time_index=1"
```

**Implementation:**
```python
# Named locations from PostGIS or config
NAMED_LOCATIONS = {
    "washington_dc": (-77.0369, 38.9072),
    "new_york": (-74.006, 40.7128),
    "los_angeles": (-118.2437, 34.0522),
    # Or query from OGC Features service
}

@app.route("/api/point/{collection}/{item_id}")
async def point_query(
    collection: str,
    item_id: str,
    location: str,
    time_index: int = 1
):
    # 1. Resolve location
    if "," in location:
        lon, lat = map(float, location.split(","))
    else:
        lon, lat = await resolve_location(location)  # From PostGIS or lookup

    # 2. Get STAC item and build TiTiler request
    item = await stac_client.get_item(collection, item_id)
    asset_url = item["assets"]["data"]["href"]

    # 3. Query TiTiler
    response = await http_client.get(
        f"{TITILER_BASE}/xarray/point/{lon},{lat}",
        params={
            "url": asset_url,
            "variable": get_variable(item),
            "decode_times": "false",
            "bidx": time_index
        }
    )

    # 4. Enrich response
    result = response.json()
    result["location_name"] = location
    result["item_id"] = item_id
    result["timestamp"] = get_timestamp_for_bidx(item, time_index)

    return result
```

---

#### 3. Clip by Admin Boundary

```
GET /api/clip/{collection}/{item_id}
    ?boundary_type=country|state|county
    &boundary_id={id}
    &format=tif|png
    &time_index=1
```

**Example:**
```bash
# Extract temperature for Virginia
curl "https://api.../clip/cmip6/tasmax-ssp585?boundary_type=state&boundary_id=VA&format=tif&time_index=1"
```

**Implementation:**
```python
@app.route("/api/clip/{collection}/{item_id}")
async def clip_by_boundary(
    collection: str,
    item_id: str,
    boundary_type: str,
    boundary_id: str,
    format: str = "tif",
    time_index: int = 1
):
    # 1. Get boundary geometry from OGC Features
    boundary = await ogc_client.get_feature(
        collection=f"admin_{boundary_type}",
        feature_id=boundary_id
    )
    geometry = boundary["geometry"]

    # 2. Get STAC item
    item = await stac_client.get_item(collection, item_id)
    asset_url = item["assets"]["data"]["href"]

    # 3. POST to TiTiler feature endpoint
    response = await http_client.post(
        f"{TITILER_BASE}/xarray/feature.{format}",
        params={
            "url": asset_url,
            "variable": get_variable(item),
            "decode_times": "false",
            "bidx": time_index,
            "max_size": 2048
        },
        json={
            "type": "Feature",
            "properties": {},
            "geometry": geometry
        }
    )

    return Response(content=response.content, media_type=f"image/{format}")
```

---

## Part D: Time-Series Extraction

### Problem Statement

TiTiler's `bidx` parameter selects a single time step. For time-series analysis, users need:
- Values across multiple time steps
- Temporal aggregations (mean, max, min over time)
- Time-range extractions

### Solution: Service Layer Orchestration

The service layer:
1. Queries multiple `bidx` values from TiTiler
2. Aggregates results
3. Returns combined time-series data

---

### Proposed Endpoints

#### 1. Time-Series Point Query

```
GET /api/timeseries/point/{collection}/{item_id}
    ?location={lon},{lat}
    &start_time={iso_date}
    &end_time={iso_date}
    &aggregation=none|daily|monthly|yearly
```

**Example:**
```bash
# Get daily max temperature for 2015 at Washington DC
curl "https://api.../timeseries/point/cmip6/tasmax-ssp585?location=-77,38.9&start_time=2015-01-01&end_time=2015-12-31"
```

**Response:**
```json
{
  "location": [-77, 38.9],
  "item_id": "tasmax-ssp585",
  "variable": "tasmax",
  "unit": "K",
  "time_series": [
    {"time": "2015-01-01", "value": 279.8, "bidx": 1},
    {"time": "2015-01-02", "value": 281.2, "bidx": 2},
    {"time": "2015-01-03", "value": 278.5, "bidx": 3},
    // ... 365 values
  ],
  "statistics": {
    "min": 265.2,
    "max": 312.4,
    "mean": 289.1,
    "std": 12.3
  }
}
```

**Implementation:**
```python
@app.route("/api/timeseries/point/{collection}/{item_id}")
async def timeseries_point(
    collection: str,
    item_id: str,
    location: str,
    start_time: str,
    end_time: str,
    aggregation: str = "none"
):
    lon, lat = map(float, location.split(","))

    # 1. Get STAC item and time metadata
    item = await stac_client.get_item(collection, item_id)
    asset_url = item["assets"]["data"]["href"]
    variable = get_variable(item)

    # 2. Calculate bidx range from dates
    time_coords = await get_time_coordinates(item)
    start_bidx, end_bidx = get_bidx_range(time_coords, start_time, end_time)

    # 3. Query TiTiler for each time step (parallel requests)
    async def query_point(bidx):
        response = await http_client.get(
            f"{TITILER_BASE}/xarray/point/{lon},{lat}",
            params={
                "url": asset_url,
                "variable": variable,
                "decode_times": "false",
                "bidx": bidx
            }
        )
        return {
            "bidx": bidx,
            "time": time_coords[bidx - 1],
            "value": response.json()["values"][0]
        }

    # Parallel requests (batch to avoid overload)
    tasks = [query_point(bidx) for bidx in range(start_bidx, end_bidx + 1)]
    results = await asyncio.gather(*tasks)

    # 4. Apply aggregation if requested
    if aggregation != "none":
        results = aggregate_timeseries(results, aggregation)

    # 5. Calculate statistics
    values = [r["value"] for r in results]
    stats = {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0
    }

    return {
        "location": [lon, lat],
        "item_id": item_id,
        "variable": variable,
        "unit": item["properties"].get("cube:variables", {}).get(variable, {}).get("unit"),
        "time_series": results,
        "statistics": stats
    }
```

---

#### 2. Time-Series Statistics for Region

```
GET /api/timeseries/statistics/{collection}/{item_id}
    ?bbox={minx},{miny},{maxx},{maxy}
    &start_time={iso_date}
    &end_time={iso_date}
    &stat=mean|max|min|sum
```

**Example:**
```bash
# Get mean temperature statistics over US for each month of 2015
curl "https://api.../timeseries/statistics/cmip6/tasmax-ssp585?bbox=-125,25,-65,50&start_time=2015-01-01&end_time=2015-12-31&aggregation=monthly"
```

**Response:**
```json
{
  "bbox": [-125, 25, -65, 50],
  "item_id": "tasmax-ssp585",
  "variable": "tasmax",
  "aggregation": "monthly",
  "time_series": [
    {
      "period": "2015-01",
      "spatial_mean": 275.3,
      "spatial_min": 245.2,
      "spatial_max": 298.4,
      "valid_pixels": 12400
    },
    {
      "period": "2015-02",
      "spatial_mean": 278.1,
      // ...
    }
    // ... 12 months
  ]
}
```

---

#### 3. Temporal Aggregation Export

```
GET /api/timeseries/aggregate/{collection}/{item_id}
    ?bbox={minx},{miny},{maxx},{maxy}
    &start_time={iso_date}
    &end_time={iso_date}
    &temporal_agg=mean|max|min
    &format=tif|png
```

**Example:**
```bash
# Export mean annual temperature as GeoTIFF
curl "https://api.../timeseries/aggregate/cmip6/tasmax-ssp585?bbox=-125,25,-65,50&start_time=2015-01-01&end_time=2015-12-31&temporal_agg=mean&format=tif" -o annual_mean_2015.tif
```

**Implementation:**
```python
@app.route("/api/timeseries/aggregate/{collection}/{item_id}")
async def timeseries_aggregate(
    collection: str,
    item_id: str,
    bbox: str,
    start_time: str,
    end_time: str,
    temporal_agg: str,  # mean, max, min, sum
    format: str = "tif"
):
    # 1. Get item and calculate bidx range
    item = await stac_client.get_item(collection, item_id)
    time_coords = await get_time_coordinates(item)
    start_bidx, end_bidx = get_bidx_range(time_coords, start_time, end_time)

    # 2. Fetch all time steps as numpy arrays
    arrays = []
    for bidx in range(start_bidx, end_bidx + 1):
        response = await http_client.get(
            f"{TITILER_BASE}/xarray/bbox/{bbox}/256x256.npy",
            params={
                "url": item["assets"]["data"]["href"],
                "variable": get_variable(item),
                "decode_times": "false",
                "bidx": bidx
            }
        )
        arr = np.load(io.BytesIO(response.content))
        arrays.append(arr)

    # 3. Stack and aggregate
    stacked = np.stack(arrays, axis=0)

    if temporal_agg == "mean":
        result = np.nanmean(stacked, axis=0)
    elif temporal_agg == "max":
        result = np.nanmax(stacked, axis=0)
    elif temporal_agg == "min":
        result = np.nanmin(stacked, axis=0)
    elif temporal_agg == "sum":
        result = np.nansum(stacked, axis=0)

    # 4. Convert to output format
    if format == "npy":
        return Response(content=result.tobytes(), media_type="application/octet-stream")
    elif format == "tif":
        # Use rasterio to create GeoTIFF with proper georeferencing
        tif_bytes = create_geotiff(result, bbox)
        return Response(content=tif_bytes, media_type="image/tiff")
    elif format == "png":
        # Render with colormap
        png_bytes = render_png(result, colormap="turbo")
        return Response(content=png_bytes, media_type="image/png")
```

---

## Implementation Recommendations

### Azure Function App Structure

```
service-layer-api/
├── function_app.py           # Main FastAPI/Functions entry
├── routers/
│   ├── extract.py            # Convenience extraction endpoints
│   ├── timeseries.py         # Time-series endpoints
│   └── batch.py              # Batch processing endpoints
├── services/
│   ├── titiler_client.py     # TiTiler HTTP client
│   ├── stac_client.py        # STAC API client
│   ├── ogc_client.py         # OGC Features client
│   └── cache.py              # Redis/memory caching
├── utils/
│   ├── time_utils.py         # Date/bidx conversion
│   ├── geo_utils.py          # Geometry helpers
│   └── aggregation.py        # Temporal aggregation
├── requirements.txt
└── host.json
```

### Key Dependencies

```txt
# requirements.txt
azure-functions
fastapi
httpx[http2]           # Async HTTP client
numpy
pystac-client          # STAC API client
rasterio               # GeoTIFF creation
redis                  # Caching (optional)
```

### Performance Considerations

| Concern | Solution |
|---------|----------|
| Many TiTiler requests | Parallel async requests with batching |
| Large time ranges | Chunk into batches, stream results |
| Repeated queries | Redis cache for STAC lookups and results |
| Memory for aggregation | Stream arrays, don't load all at once |
| Rate limiting | Configurable concurrency limit to TiTiler |

### Caching Strategy

```python
# Cache STAC items (change rarely)
@cache(ttl=3600)
async def get_stac_item(collection, item_id):
    return await stac_client.get_item(collection, item_id)

# Cache time coordinates (static per item)
@cache(ttl=86400)
async def get_time_coordinates(item_id):
    return await fetch_time_coords(item_id)

# Don't cache extraction results (too large, unique queries)
```

---

## API Summary

### Convenience Wrapper (Part B)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/extract/{collection}/{item}` | Extract by STAC item ID |
| `GET /api/point/{collection}/{item}` | Point query with location names |
| `GET /api/clip/{collection}/{item}` | Clip to admin boundary |
| `GET /api/preview/{collection}/{item}` | Quick preview image |

### Time-Series (Part D)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/timeseries/point/{collection}/{item}` | Time-series at a point |
| `GET /api/timeseries/statistics/{collection}/{item}` | Regional stats over time |
| `GET /api/timeseries/aggregate/{collection}/{item}` | Temporal aggregation export |
| `POST /api/timeseries/batch` | Batch time-series queries |

---

## Next Steps

1. **Create Function App** - Set up Azure Function App with FastAPI
2. **Implement STAC client** - Connect to pgSTAC API
3. **Implement TiTiler client** - Async HTTP client with retry/caching
4. **Build Part B endpoints** - Convenience wrappers
5. **Build Part D endpoints** - Time-series extraction
6. **Add caching** - Redis for STAC lookups
7. **Deploy and test** - Verify integration with TiTiler

---

**Author:** Claude + Robert Harrison
**Last Updated:** December 18, 2025
