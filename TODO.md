# TODO - rmhtitiler

> Outstanding issues and future work items

---

## Critical: Dependency Version Conflicts

**Status:** Unresolved - needs investigation before production
**Date:** 2026-01-05
**Discovered during:** ACR build of v0.5.0-test

### Problem

When installing `titiler.xarray>=0.18.0` on top of base image `titiler-pgstac:1.9.0`, pip reports version conflicts:

```
cogeo-mosaic 8.2.0 requires rio-tiler<8.0,>=7.0, but you have rio-tiler 8.0.5 which is incompatible.
titiler-pgstac 1.9.0 requires titiler.core<0.25,>=0.24, but you have titiler-core 1.0.2 which is incompatible.
titiler-mosaic 0.24.0 requires titiler.core==0.24.0, but you have titiler-core 1.0.2 which is incompatible.
```

### Root Cause

- Base image (`ghcr.io/stac-utils/titiler-pgstac:1.9.0`) ships with `titiler.core 0.24.x` and `rio-tiler 7.x`
- `titiler.xarray>=0.18.0` depends on newer `titiler-core 1.0.2` and `rio-tiler 8.0.5`
- These newer versions are incompatible with `cogeo-mosaic`, `titiler-pgstac`, and `titiler-mosaic`

### Affected Endpoints (Potentially)

| Endpoint | Package | Risk |
|----------|---------|------|
| `/mosaicjson/*` | cogeo-mosaic | Medium |
| `/searches/*` | titiler-pgstac | Medium |
| `/cog/*` | rio-tiler | Medium |

### Solutions to Investigate

1. **Pin titiler.xarray version** - Find version compatible with titiler.core 0.24.x
   ```dockerfile
   RUN pip install "titiler.xarray>=0.15.0,<0.18.0"
   ```

2. **Upgrade base image** - Check if newer titiler-pgstac exists with updated deps
   ```dockerfile
   FROM ghcr.io/stac-utils/titiler-pgstac:latest
   ```

3. **Build custom base image** - Create image with all compatible versions pinned

4. **Test current build** - The conflicts may not cause runtime issues for our use cases

### Notes

- Base image is in JFROG Artifactory (QA) - changing it requires approval process
- Current build (`v0.5.0-test`) completed successfully despite warnings
- Need to test all endpoints before promoting to production

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
