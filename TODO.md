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
| `/mosaicjson/*` | cogeo-mosaic | ⛔ Unsupported | See below |

### MosaicJSON: Intentionally Unsupported

**Why we don't use `/mosaicjson/*` endpoints:**

MosaicJSON requires **hardcoded, static storage tokens** embedded in the JSON file.
This is incompatible with our security model:

- We use short-lived OAuth tokens (1 hour TTL) via Managed Identity
- Tokens are refreshed automatically in background tasks
- Static tokens are a security risk and operationally brittle

The TiTiler team recognizes this - **titiler-core 1.0.0 removed cogeo-mosaic dependency**
(Dec 17, 2025 release notes). The ecosystem is moving away from static-token mosaics.

**Use `/searches/*` instead:** pgSTAC search registration creates dynamic mosaics from
STAC queries without requiring static tokens.

### Version Summary

We are running **more advanced versions** of core libraries:
- `titiler-core 1.0.2` - Major version, latest (Dec 2025)
- `rio-tiler 8.0.5` - Latest

The warning packages have not been updated yet:
- `titiler-pgstac 1.9.0` - Released Sep 2024, written for titiler-core 0.24.x
- `cogeo-mosaic 8.2.0` - Requires rio-tiler 7.x (we don't use it)

### Future: Watch for Updates

- **titiler-pgstac 2.x** - Expected to officially support titiler-core 1.x
- **cogeo-mosaic** - May be deprecated as ecosystem moves to dynamic mosaics

### Notes

- Base image is in JFROG Artifactory (QA) - no changes needed
- Current build (`v0.5.0-test`) works for all supported use cases
- MosaicJSON endpoints exist but are not part of our supported feature set

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
