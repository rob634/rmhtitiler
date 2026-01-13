# TODO - rmhtitiler

> Outstanding issues and future work items

---

## Dependency Versions: Analysis Complete

**Status:** Understood - acceptable for current use cases
**Date:** 2026-01-05
**Discovered during:** ACR build of v0.5.0-test

### What Happened

Installing `titiler.xarray>=0.18.0` on base image `titiler-pgstac:1.9.0` upgrades core libraries:

```
Base Image Ships:           After pip install:
├── titiler-core 0.24.x  →  titiler-core 1.0.2 ✨ (released Dec 17, 2025!)
├── rio-tiler 7.x        →  rio-tiler 8.0.5 ✨
├── cogeo-mosaic 8.2.0   →  cogeo-mosaic 8.2.0 (unchanged)
├── titiler-pgstac 1.9.0 →  titiler-pgstac 1.9.0 (unchanged)
└── titiler-mosaic 0.24.0→  titiler-mosaic 0.24.0 (unchanged)
```

### Why pip Complains

The older packages (cogeo-mosaic, titiler-pgstac, titiler-mosaic) were compiled against
the older APIs (rio-tiler 7.x, titiler-core 0.24.x). pip warns about version constraints
but installs anyway.

### Actual Impact

| Endpoint | Package | Status | Notes |
|----------|---------|--------|-------|
| `/cog/*` | rio-tiler 8.x | ✅ Works | rio-tiler 8.x reads COGs fine |
| `/xarray/*` | titiler.xarray | ✅ Works | Uses its own rio-tiler 8.x |
| `/searches/*` | titiler-pgstac | ✅ Works | Tested in production, forwards-compatible |
| `/vector/*` | tipg | ✅ Works | OGC Features + Vector Tiles (v0.7.0+) |

### Version Summary

We are running **more advanced versions** of core libraries:
- `titiler-core 1.0.2` - Major version, latest (Dec 2025)
- `rio-tiler 8.0.5` - Latest

The warning packages in the base image have not been updated yet:
- `titiler-pgstac 1.9.0` - Released Sep 2024, written for titiler-core 0.24.x
- `cogeo-mosaic 8.2.0` - Requires rio-tiler 7.x (unused, in base image only)

### Future: Watch for Updates

- **titiler-pgstac 2.x** - Expected to officially support titiler-core 1.x

### Notes

- Base image is in JFROG Artifactory (QA) - no changes needed
- pip warnings about cogeo-mosaic are harmless (we don't use it)
- All supported endpoints work correctly despite version warnings

---

## Completed: Codebase Restructuring

**Status:** Complete
**Date:** 2026-01-05

Restructured from single 1,663-line `custom_pgstac_main.py` to modular `rmhtitiler/` package.

See `RESTRUCTURE.md` for full details.

### New Structure

```
rmhtitiler/
├── __init__.py          # v0.5.0
├── app.py               # FastAPI factory with lifespan
├── config.py            # Pydantic Settings
├── auth/                # TokenCache, storage, postgres auth
├── routers/             # health, planetary_computer, root
├── middleware/          # AzureAuthMiddleware
├── services/            # database, background refresh
└── templates/           # HTML templates
```

### Archived

- `archive/custom_pgstac_main.py` - Original monolithic file (preserved for reference)

---

## Future Work

- [ ] Add unit tests for `TokenCache` class
- [ ] Add unit tests for health probe helpers
- [ ] Add integration tests for auth flows
- [ ] Consider adding `py.typed` marker for type checking
- [ ] Review and update CLAUDE.md with new structure

---

## TiPG Integration - OGC Features + Vector Tiles

**Status:** Planned
**Date:** 2026-01-12
**Priority:** High

### Overview

Integrate [TiPG](https://github.com/developmentseed/tipg) (Development Seed) to add OGC Features API and Vector Tiles alongside existing raster tile capabilities. TiPG complements TiTiler - same organization, proven integration patterns.

### Why TiPG

| Feature | Current (TiTiler) | With TiPG |
|---------|-------------------|-----------|
| Raster tiles (COG) | ✅ | ✅ |
| STAC mosaics | ✅ | ✅ |
| OGC Features API | ❌ | ✅ |
| Vector tiles (MVT) | ❌ | ✅ |
| PostGIS table access | ❌ | ✅ |
| CQL2 filtering | ❌ | ✅ |

### Architecture

```
rmhtitiler (single FastAPI app)
├── app.state.dbpool    → titiler-pgstac (psycopg)
├── app.state.pool      → TiPG (asyncpg)
│
├── /health, /cog, /xarray, /searches  → existing routes
└── /vector/*                          → NEW TiPG routes
    ├── /vector/collections
    ├── /vector/collections/{id}/items
    └── /vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}
```

### Key Design Decision

**Token-synchronized pool refresh:** Both connection pools use the same Managed Identity token. When token refreshes (every 45 min), both pools are recreated atomically. No passwords.

### Implementation Tasks

#### Phase 1: Dependencies & Configuration
- [ ] Add `tipg>=0.12.0` to `requirements.txt`
- [ ] Verify dependency compatibility (asyncpg, pydantic, fastapi versions)
- [ ] Add TiPG-specific settings to `config.py`:
  - `TIPG_SCHEMAS` - PostGIS schemas to expose (default: `["geo", "public"]`)
  - `TIPG_ENABLE` - Feature flag to enable/disable TiPG routes

#### Phase 2: Database Integration
- [ ] Create `rmhtitiler/routers/vector.py`:
  - Helper to build TiPG PostgresSettings from existing auth
  - TiPG endpoint factory configuration
- [ ] Extend `app.py` lifespan handler:
  - Initialize TiPG connection pool (`app.state.pool`)
  - Register collection catalog from PostGIS schemas
  - Close TiPG pool on shutdown
- [ ] Extend `services/background.py` `_refresh_postgres_with_pool_recreation()`:
  - Close and recreate TiPG pool alongside titiler-pgstac pool
  - Re-register collection catalog after pool recreation

#### Phase 3: Router Integration
- [ ] Mount TiPG endpoints in `create_app()`:
  ```python
  from tipg.factory import Endpoints as TiPGEndpoints
  tipg = TiPGEndpoints(with_tiles_viewer=True)
  app.include_router(tipg.router, prefix="/vector", tags=["OGC Vector"])
  ```
- [ ] Update `/health` endpoint to report TiPG pool status
- [ ] Update root endpoint to include vector API links

#### Phase 4: Testing & Documentation
- [ ] Test OGC Features endpoints against `geo` schema tables
- [ ] Test vector tile rendering (MVT format)
- [ ] Test token refresh cycle (verify both pools recreate)
- [ ] Update CLAUDE.md with new endpoints
- [ ] Update WIKI.md with TiPG configuration

### New Endpoints (after integration)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /vector/` | GET | OGC landing page |
| `GET /vector/conformance` | GET | OGC conformance classes |
| `GET /vector/collections` | GET | List PostGIS tables |
| `GET /vector/collections/{id}` | GET | Collection metadata + extent |
| `GET /vector/collections/{id}/queryables` | GET | Filterable properties |
| `GET /vector/collections/{id}/items` | GET | Query features (GeoJSON) |
| `GET /vector/collections/{id}/items/{fid}` | GET | Single feature |
| `GET /vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}` | GET | Vector tile (MVT) |
| `GET /vector/collections/{id}/tilejson.json` | GET | MapLibre TileJSON |
| `GET /vector/collections/{id}/map` | GET | Interactive viewer |

### Dependencies to Add

```
# requirements.txt additions
tipg>=0.12.0
buildpg>=0.3
pygeofilter>=0.2.0,<0.3.0
ciso8601~=2.3
starlette-cramjam>=0.4,<0.6
```

### Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Dependency conflicts | Test in isolated venv first |
| Pool recreation downtime | ~100-500ms acceptable; could add health check grace period |
| asyncpg vs psycopg complexity | Separate pools, separate state attributes |
| Token refresh timing | Existing 45-min refresh well within 60-min token TTL |

### Alternative Considered

**rmhgeoapi/ogc_features** - Custom Azure Functions implementation already in production. Rejected because:
- Azure Functions architecture (not FastAPI native)
- No vector tiles support
- Would require significant refactoring to integrate
- TiPG provides superset of features with less code

### References

- [TiPG GitHub](https://github.com/developmentseed/tipg)
- [TiPG Documentation](https://developmentseed.org/tipg/)
- [eoAPI Architecture](https://eoapi.dev/services/) - TiTiler + TiPG + STAC
- [OGC API - Features](https://ogcapi.ogc.org/features/)
