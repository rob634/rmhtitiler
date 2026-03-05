# Custom Raster Query API

**Status**: PLANNED
**Priority**: Phase 2

---

## Overview

Custom endpoints for simplified raster data queries beyond standard TiTiler capabilities.

---

## Planned Endpoints

### Point Query (Batch)

```
POST /api/raster/point-query
```

Query multiple points in a single request.

```json
{
  "url": "https://storage.../file.tif",
  "points": [
    {"lon": 29.87, "lat": -1.94},
    {"lon": 29.88, "lat": -1.95},
    {"lon": 29.89, "lat": -1.96}
  ]
}
```

**Response**:
```json
{
  "results": [
    {"lon": 29.87, "lat": -1.94, "values": [2.5]},
    {"lon": 29.88, "lat": -1.95, "values": [1.8]},
    {"lon": 29.89, "lat": -1.96, "values": [0.0]}
  ]
}
```

### Zonal Statistics

```
POST /api/raster/zonal-stats
```

Calculate statistics for a polygon region.

```json
{
  "url": "https://storage.../file.tif",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[29.8, -2.0], [29.9, -2.0], [29.9, -1.9], [29.8, -1.9], [29.8, -2.0]]]
  },
  "statistics": ["min", "max", "mean", "std", "count"]
}
```

### Time Series Extraction

```
POST /api/raster/timeseries
```

Extract values across multiple time steps (for multi-temporal COGs or Zarr).

---

## Implementation Notes

- Will leverage TiTiler's existing COG reader
- Async processing for batch queries
- Consider caching for repeated queries
- Rate limiting for large batch requests

---

## Design Decisions (TBD)

- [ ] Batch size limits
- [ ] Async vs sync for large queries
- [ ] Response format (GeoJSON vs custom)
- [ ] Authentication requirements
