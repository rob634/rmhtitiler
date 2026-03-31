# Handoff: Add /preview/* Endpoint to GeoTiler

**Date**: 31 MAR 2026
**Source Spec**: `rmhgeoapi/docs/superpowers/specs/2026-03-31-preview-url-migration-design.md`

---

## What and Why

The rmhgeoapi ETL pipeline returns viewer URLs to clients when they poll job status during the approval stage. These currently point at rmhgeoapi's self-hosted Leaflet viewers. We're migrating them to point at GeoTiler's MapLibre viewers instead.

GeoTiler already has `/viewer/raster`, `/viewer/vector`, `/viewer/zarr`. We need a parallel `/preview/*` prefix that:

1. Serves the **exact same pages** as `/viewer/*`
2. Sets **iframe-permissive HTTP headers** (so front-end devs can embed these in iframes cross-origin)
3. Will later be **auth-gated** separately from `/viewer/*`

That's it. No new templates, no new JavaScript, no new config.

---

## Implementation

### File 1: `geotiler/routers/preview.py` (NEW)

Create this file. Model it on the existing viewer router:

```python
# Existing viewer router for reference (geotiler/routers/viewer.py):

from fastapi import APIRouter, Request
from geotiler.templates_utils import render_template

router = APIRouter(prefix="/viewer", tags=["Viewers"], include_in_schema=False)

@router.get("/raster", include_in_schema=False)
async def raster_viewer(request: Request):
    return render_template(request, "pages/viewer/raster.html", nav_active="/catalog")

@router.get("/zarr", include_in_schema=False)
async def zarr_viewer(request: Request):
    return render_template(request, "pages/viewer/zarr.html", nav_active="/catalog")

@router.get("/vector", include_in_schema=False)
async def vector_viewer(request: Request):
    return render_template(request, "pages/viewer/vector.html", nav_active="/catalog")
```

The preview router is identical except:
- **Prefix** is `/preview` instead of `/viewer`
- **Tag** is `"Preview"` instead of `"Viewers"`
- Each response gets **iframe-permissive headers** added

For the headers, wrap the template response to set:
```
Content-Security-Policy: frame-ancestors *
X-Frame-Options: ALLOWALL
```

The cleanest approach: call `render_template()` to get the `Response` object, then set headers on it before returning. Or use a middleware/dependency scoped to this router. Your call on implementation — the requirement is just that all `/preview/*` responses include those two headers.

Do NOT include the H3 viewer redirect that exists in the viewer router — only raster, vector, zarr.

### File 2: `geotiler/app.py` (MODIFY)

**Add import**: Add `preview` to the router imports. Current import line is:
```python
from geotiler.routers import health, admin, vector, stac, diagnostics, home, catalog, reference, system, viewer
```

**Mount the router** near the viewer router mount. Current mounting:
```python
    # Map viewers
    app.include_router(viewer.router)
```

Add:
```python
    # Preview viewers (iframe-embeddable, auth-gated later)
    app.include_router(preview.router)
```

---

## Query Parameter Passthrough

The `/preview/*` routes don't need to parse any query parameters. The JavaScript in the viewer templates reads query params client-side via `getQueryParam()` from `static/js/common.js`. So a URL like:

```
/preview/raster?url=%2Fvsiaz%2Fsilver-cogs%2Ffile.tif
```

...renders the raster viewer HTML, and the JavaScript picks up `url` from the query string on page load. The server just serves the template — params flow through automatically.

---

## Expected URLs After Implementation

| Route | Example URL | Iframe-able |
|---|---|---|
| `GET /preview/raster` | `/preview/raster?url=%2Fvsiaz%2Fsilver-cogs%2Fdem.tif` | Yes |
| `GET /preview/vector` | `/preview/vector?collection=flood_zones` | Yes |
| `GET /preview/zarr` | `/preview/zarr?url=abfs%3A%2F%2Fsilver-zarr%2Fstore.zarr&variable=temperature` | Yes |

---

## Verification

After implementation, confirm:

1. `GET /preview/raster` returns 200 with the same HTML as `GET /viewer/raster`
2. `GET /preview/raster?url=/vsiaz/test/file.tif` loads the map with tiles (same as viewer)
3. Response headers include `Content-Security-Policy: frame-ancestors *`
4. Response headers include `X-Frame-Options: ALLOWALL`
5. `/preview/vector` and `/preview/zarr` work the same way
6. No `/preview/h3` route exists

---

## What NOT to Do

- Do not create new templates — reuse `pages/viewer/*.html`
- Do not modify the existing `/viewer/*` routes or their headers
- Do not add config flags — this is always enabled
- Do not add any approval workflow UI (approve/reject buttons) — this is a pure viewer
- Do not add fallback logic to any other viewer
