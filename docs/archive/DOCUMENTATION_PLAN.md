# TiTiler Documentation Plan

**Date**: 16 JAN 2026
**Status**: Active - Phase 1

---

## Overview

Consumer-facing documentation for the TiTiler/TiPG geospatial tile server. Two audiences, one simple auth model.

---

## Authentication Model

### The Simple Rule

> **If you're in our tenant, you have access.**

No groups, no roles, no complicated permissions. Tenant membership = data access.

### For Data Scientists (Browser → Notebook)

```
1. Log in via browser (Entra ID)
2. Get token from browser dev tools
3. Include token in API requests
```

```python
import requests

# Token from browser (Application tab → Cookies/Storage)
token = "eyJ0eXAiOiJKV1Q..."

# Use in requests
response = requests.get(
    "https://titiler.example.com/cog/info",
    params={"url": "https://storage.../file.tif"},
    headers={"Authorization": f"Bearer {token}"}
)
```

### For Web Apps (Internal)

Internal apps authenticate via Entra ID. Same rule applies: if the app is in our tenant, it has access. Configuration details are handled by platform team.

---

## Documentation Structure

```
docs/
├── index.md                      # Landing page
├── getting-started/
│   ├── authentication.md         # Auth flow (browser + app-to-app)
│   └── quick-start.md            # First API call in 5 minutes
├── endpoints/
│   ├── cog.md                    # COG tiles, info, statistics
│   ├── xarray.md                 # Zarr/NetCDF endpoints
│   ├── stac.md                   # STAC catalog + pgSTAC searches
│   ├── vector.md                 # TiPG OGC Features + Vector Tiles
│   └── custom/                   # Future custom endpoints
│       ├── raster-query.md       # [PLACEHOLDER] Custom raster queries
│       └── xarray-query.md       # [PLACEHOLDER] Custom xarray queries
├── guides/
│   ├── data-scientists/
│   │   ├── point-queries.md      # Extract values at coordinates
│   │   ├── batch-queries.md      # Query multiple points
│   │   ├── windowed-reads.md     # COG partial reads with rasterio
│   │   └── stac-search.md        # pystac-client examples
│   └── web-developers/
│       ├── maplibre-tiles.md     # Display tiles in MapLibre
│       ├── vector-features.md    # Query and display vector data
│       └── leaflet-integration.md # Leaflet examples
├── reference/
│   └── api.md                    # Links to /docs and /redoc
└── roadmap/
    └── arcgis-migration.md       # [FUTURE] ArcGIS migration guide
```

---

## Phase 1: Current Endpoints (Now)

Document what exists today:

### COG Endpoints (`/cog/*`)

| Endpoint | Purpose |
|----------|---------|
| `GET /cog/info` | COG metadata (bounds, CRS, bands) |
| `GET /cog/statistics` | Band statistics |
| `GET /cog/tiles/{tms}/{z}/{x}/{y}` | XYZ tiles |
| `GET /cog/{tms}/tilejson.json` | TileJSON for web maps |
| `GET /cog/{tms}/map` | Interactive viewer |
| `GET /cog/point/{lon},{lat}` | Value at point |
| `GET /cog/preview` | Static preview image |

### XArray Endpoints (`/xarray/*`)

| Endpoint | Purpose |
|----------|---------|
| `GET /xarray/variables` | List variables in Zarr/NetCDF |
| `GET /xarray/info` | Variable metadata |
| `GET /xarray/tiles/{tms}/{z}/{x}/{y}` | XYZ tiles |
| `GET /xarray/{tms}/tilejson.json` | TileJSON |
| `GET /xarray/{tms}/map` | Interactive viewer |
| `GET /xarray/point/{lon},{lat}` | Value at point |

### STAC Endpoints (`/stac/*`)

| Endpoint | Purpose |
|----------|---------|
| `GET /stac` | Root catalog |
| `GET /stac/collections` | List collections |
| `GET /stac/collections/{id}` | Collection metadata |
| `GET /stac/collections/{id}/items` | Items in collection |
| `GET /stac/search` | Search items |

### pgSTAC Search Endpoints (`/searches/*`)

| Endpoint | Purpose |
|----------|---------|
| `GET /searches/list` | List registered searches |
| `POST /searches/register` | Create mosaic from search |
| `GET /searches/{id}/tiles/{tms}/{z}/{x}/{y}` | Mosaic tiles |
| `GET /searches/{id}/{tms}/map` | Interactive viewer |

### TiPG Vector Endpoints (`/vector/*`)

| Endpoint | Purpose |
|----------|---------|
| `GET /vector/collections` | List PostGIS tables |
| `GET /vector/collections/{id}/items` | Query features (GeoJSON) |
| `GET /vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}` | Vector tiles (MVT) |

---

## Phase 2: Custom Endpoints (Planned)

### Custom Raster Query API

**Purpose**: Simplified batch point queries, zonal statistics, time series extraction

```
POST /api/raster/point-query
POST /api/raster/zonal-stats
POST /api/raster/timeseries
```

**Status**: Placeholder - design pending

### Custom XArray Query API

**Purpose**: Multidimensional queries, dimension slicing, aggregations

```
POST /api/xarray/slice
POST /api/xarray/aggregate
POST /api/xarray/extract
```

**Status**: Placeholder - design pending

---

## Phase 3: ArcGIS Migration Guide (Future)

**Priority**: Next up after Phase 1 & 2

**Content to include**:
- Concept mapping (Feature Service → TiPG, Map Service → TiTiler)
- Code migration examples (ArcGIS JS SDK → MapLibre)
- Cost comparison
- Skills transfer guide

**Separate document**: `docs/roadmap/arcgis-migration.md`

---

## Content Priority

### Must Have (Phase 1)
1. ✅ Landing pages for each endpoint group (done - `/cog/`, `/xarray/`, `/searches/`, `/stac/`)
2. Authentication guide (browser + app-to-app)
3. Quick start guide
4. Data scientist: Point queries example
5. Web developer: MapLibre tiles example

### Should Have (Phase 1)
6. Data scientist: Batch queries
7. Data scientist: STAC search with pystac-client
8. Web developer: Vector features with TiPG

### Future (Phase 2+)
9. Custom raster query API docs
10. Custom xarray query API docs
11. ArcGIS migration guide

---

## Implementation Approach

### Option A: MkDocs Material (Recommended)
- Python-based, matches stack
- Build static site, serve from `/guide`
- Excellent code highlighting

### Option B: In-App HTML Pages (Current)
- Already have landing pages at `/cog/`, `/xarray/`, etc.
- Extend with more detailed content
- No additional tooling required

### Recommendation
Start with **Option B** (extend existing landing pages) for quick wins, then add **MkDocs** for comprehensive guides when content grows.

---

## Next Steps

1. [ ] Create `docs/getting-started/authentication.md` content
2. [ ] Add auth examples to landing pages
3. [ ] Create data scientist quick start (point query example)
4. [ ] Create web developer quick start (MapLibre tiles)
5. [ ] Add placeholder pages for custom endpoints
