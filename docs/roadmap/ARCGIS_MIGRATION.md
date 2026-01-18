# ArcGIS Migration Guide

**Status**: PLANNED - Priority: Next Up
**Target Audience**: Web Developers migrating from ArcGIS/GEE

---

## Overview

This guide will help teams migrate from ArcGIS Online, ArcGIS Enterprise, and Google Earth Engine to standards-based alternatives using TiTiler, TiPG, and STAC.

---

## Planned Content

### Concept Mapping

| ArcGIS Concept | Standards-Based Equivalent |
|----------------|---------------------------|
| Feature Service | TiPG OGC API Features (`/vector/collections/{id}/items`) |
| Map Service (tiles) | TiTiler COG tiles (`/cog/tiles/{z}/{x}/{y}`) |
| Image Service | TiTiler + STAC |
| Portal item search | STAC catalog (`/stac/search`) |
| ArcGIS JS SDK (800kb) | MapLibre GL JS (30kb) |
| esriGeometryPolygon | GeoJSON (actual standard) |
| Layer.queryFeatures() | OGC API Features + CQL2 filters |
| ImageServer.identify() | TiTiler point query (`/cog/point/{lon},{lat}`) |

### GEE Concept Mapping

| GEE Concept | Standards-Based Equivalent |
|-------------|---------------------------|
| ImageCollection | STAC Collection + COG assets |
| ee.Image.sample() | TiTiler point query |
| ee.Reducer | Custom xarray/raster query API (planned) |
| Code Editor | Jupyter notebooks + pystac-client |

### Code Migration Examples

- ArcGIS JS SDK → MapLibre GL JS
- Feature Layer queries → OGC API Features
- ArcGIS Python API → requests + pystac-client

### Cost Comparison

- Per-seat licensing vs open source
- Usage tiers vs flat infrastructure cost
- Vendor lock-in implications

### Skills Transfer

- Standards-based skills are portable
- Open source ecosystem knowledge
- No proprietary SDK learning curve

---

## Why This Matters

1. **Cost**: 30-100x savings vs ArcGIS/GEE
2. **Portability**: Standards work everywhere
3. **Performance**: Purpose-built tools
4. **Skills**: Learn once, use anywhere

---

## Implementation Notes

This document will be fleshed out after Phase 1 documentation is complete. Content will be extracted from the original implementation plan provided by ETL Claude.

**Reference**: `/Users/robertharrison/python_builds/rmhgeoapi/docs_titiler/IMPLEMENTATION_PLAN.md`
