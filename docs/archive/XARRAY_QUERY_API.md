# Custom XArray Query API

**Status**: PLANNED
**Priority**: Phase 2

---

## Overview

Custom endpoints for multidimensional data queries on Zarr/NetCDF datasets.

---

## Planned Endpoints

### Dimension Slice

```
POST /api/xarray/slice
```

Extract a slice along one or more dimensions.

```json
{
  "url": "https://storage.../data.zarr",
  "variable": "temperature",
  "slices": {
    "time": "2024-01-15",
    "level": 1000
  },
  "bbox": [29.0, -2.5, 30.0, -1.5]
}
```

### Aggregate

```
POST /api/xarray/aggregate
```

Compute aggregations across dimensions.

```json
{
  "url": "https://storage.../data.zarr",
  "variable": "precipitation",
  "aggregation": {
    "dimension": "time",
    "method": "sum",
    "range": ["2024-01-01", "2024-12-31"]
  },
  "bbox": [29.0, -2.5, 30.0, -1.5]
}
```

### Point/Region Extract

```
POST /api/xarray/extract
```

Extract time series or profiles at specific locations.

```json
{
  "url": "https://storage.../data.zarr",
  "variable": "temperature",
  "location": {"lon": 29.87, "lat": -1.94},
  "dimensions": {
    "time": "all",
    "level": [1000, 850, 500]
  }
}
```

**Response**:
```json
{
  "coordinates": {"lon": 29.87, "lat": -1.94},
  "dimensions": {
    "time": ["2024-01-01", "2024-01-02", "..."],
    "level": [1000, 850, 500]
  },
  "values": [
    [295.5, 290.2, 275.1],
    [296.0, 291.0, 276.0],
    ...
  ]
}
```

---

## Implementation Notes

- Built on titiler-xarray foundation
- Leverage xarray's lazy loading
- Dask integration for large queries
- Consider zarr-python direct access for performance

---

## Design Decisions (TBD)

- [ ] Output formats (JSON, NetCDF, CSV)
- [ ] Maximum query size limits
- [ ] Async processing thresholds
- [ ] Caching strategy for repeated queries
