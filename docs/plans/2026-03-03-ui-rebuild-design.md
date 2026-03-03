# UI Rebuild Design: Geospatial Data Catalog

**Date**: 2026-03-03
**Status**: Design
**Pipeline**: ARB (Architecture Review Board) → Greenfield (per subsystem)

---

## 1. Purpose

Replace the existing kludge UI with a properly designed, from-scratch implementation. The current UI is 27 Jinja2 templates, ~1,300 lines of CSS, and ~364 lines of vanilla JS that grew organically. The new UI will be built through the ARB pipeline to produce a sequenced plan of Greenfield runs, each generating production-quality code with adversarial design review.

The UI is NOT a formal application — it is a helpful exploratory tool for admins, B2B clients, and B2C clients to browse and visualize geospatial data served by the TiTiler stack.

---

## 2. Architecture Decisions

### Stack
- **Server-rendered Jinja2 templates** — no frontend build step, no JS framework
- **Vanilla JavaScript** — modular per-page scripts + shared utility module
- **MapLibre GL JS** (CDN) — standardized map library for all viewers, replacing Leaflet
- **deck.gl** (CDN) — retained for H3 hexagonal overlay on MapLibre
- **HTMX** (CDN) — for admin health polling and any progressive enhancement
- **CSS custom properties** — design system with tokens, component classes, responsive breakpoints

### Principles
- Minimal complexity — server-rendered pages, CDN libs, zero build tooling
- Separate viewers per data type — each has distinct controls and behavior
- Client-side catalog merge — UI fetches from existing `/stac/collections` and `/vector/collections` separately, combines client-side
- Foundation-first build order — design system → catalog → viewers → docs

---

## 3. Route Map

All routes verified conflict-free against existing API endpoints (`/cog`, `/xarray`, `/searches`, `/stac`, `/vector`, `/docs`, `/admin`, `/h3`, `/guide`, `/map`, `/static`).

| Page | Route | Purpose | Data Sources |
|------|-------|---------|--------------|
| Homepage | `/` | Splash, entry to catalog | None (static) |
| Unified Catalog | `/catalog` | Joint STAC + OGC collection browser | `/stac/collections`, `/vector/collections` |
| STAC Catalog | `/catalog/stac` | STAC-specific collection/item browser | `/stac/collections`, `/stac/search` |
| OGC Features Catalog | `/catalog/vector` | OGC Features collection browser | `/vector/collections` |
| Raster Viewer | `/viewer/raster` | COG tile viewer | `/cog/info`, `/cog/tiles/{z}/{x}/{y}` |
| Zarr Viewer | `/viewer/zarr` | Zarr/NetCDF variable viewer | `/xarray/info`, `/xarray/tiles/{z}/{x}/{y}` |
| Vector Viewer | `/viewer/vector` | OGC Features on MapLibre map | `/vector/collections/{id}/items`, `/vector/collections/{id}/tiles` |
| H3 Viewer | `/viewer/h3` | H3 choropleth with deck.gl | `/h3/query` |
| Reference | `/reference` | Consolidated API docs + guides | Static content + iframe Swagger/ReDoc |
| System | `/system` | Admin diagnostics, health polling | `/health`, `/readyz`, HTMX fragment |

### URL Contract: Catalog → Viewer

Catalog pages link to viewers via query parameters:

```
/viewer/raster?url={cog_url}
/viewer/zarr?url={zarr_url}&variable={var_name}
/viewer/vector?collection={collection_id}
/viewer/h3?region={region_id}
```

---

## 4. Current UI Inventory (to be replaced)

### Templates (27 files)
- `base.html`, `base_guide.html` — base layouts
- `components/` — navbar, footer, guide_sidebar, macros
- `pages/admin/` — admin dashboard + health fragment
- `pages/cog/`, `pages/xarray/`, `pages/searches/` — landing pages
- `pages/h3/` — H3 choropleth (standalone HTML)
- `pages/map/` — MapLibre map viewer
- `pages/stac/` — STAC explorer (Leaflet)
- `pages/guide/` — 11 documentation pages

### Static Assets
- `static/css/styles.css` — 1,309 lines, design tokens + component styles
- `static/js/common.js` — 364 lines, utility functions

### Routers (8 files serving UI)
- `admin.py`, `cog_landing.py`, `xarray_landing.py`, `searches_landing.py`
- `map_viewer.py`, `stac_explorer.py`, `h3_explorer.py`, `docs_guide.py`

### What to Keep
- **Design token values** — the color palette, spacing scale, and typography are good
- **H3 deck.gl pattern** — the hexagonal rendering approach works well
- **HTMX health polling** — clean pattern for admin auto-refresh
- **`templates_utils.py`** — `render_template()` and `get_template_context()` pattern is clean

### What to Discard
- All current templates (rebuild from scratch with proper component macros)
- `common.js` monolith (replace with modular per-page JS)
- Leaflet dependency (replaced by MapLibre)
- Ad-hoc inline styles and page-specific CSS overrides

---

## 5. Subsystem Map (ARB Input)

### SUBSYSTEM 1: Design System & Base Shell

**PURPOSE**: CSS design system (tokens, components, layouts, responsive), base HTML template, navbar, footer, and Jinja2 macro library for reusable UI components.

**SCOPE ESTIMATE**: ~1,500 lines across 6 files

**OWNS**: All visual styling, layout structure, component primitives

**DEPENDS ON**: Nothing (Phase 1 — foundation)

**EXPOSES**:
- `base.html` — all pages extend this
- `components/macros.html` — card, badge, map-container, sidebar-panel, form-group, data-table, status-indicator, empty-state macros
- `components/navbar.html` — navigation with conditional links based on enabled features
- `components/footer.html` — footer with version and links
- CSS class vocabulary — all other subsystems use these classes

**CONSUMES**: Nothing

**GREENFIELD TIER 1 SEED**:
- Design system with CSS custom properties for colors, spacing, typography, shadows, radii
- Responsive breakpoints at 768px and 480px
- Base HTML5 template with charset, viewport, stylesheet link, script defer
- Navbar with links: Home, Catalog, Reference, System (conditionally visible based on feature flags)
- Footer with version number, attribution
- Jinja2 macros: card(title, subtitle, body, footer, href), badge(text, variant), map_container(id, height), sidebar_panel(title, collapsible), form_group(label, input_html), data_table(headers, rows), status_indicator(status), empty_state(message, icon)
- All macros must be self-contained — no implicit CSS dependencies outside the design system

**FILES**:
- `geotiler/static/css/styles.css`
- `geotiler/templates/base.html`
- `geotiler/templates/components/navbar.html`
- `geotiler/templates/components/footer.html`
- `geotiler/templates/components/macros.html`
- `geotiler/templates_utils.py` (update if needed)

---

### SUBSYSTEM 2: Homepage & Shared JS Utilities

**PURPOSE**: Homepage/splash page ("Geospatial Data Catalog" entry point) and shared JavaScript utility module used by all interactive pages.

**SCOPE ESTIMATE**: ~800 lines across 4 files

**OWNS**: Homepage content, JS utility functions

**DEPENDS ON**: Subsystem 1 (base shell, macros, CSS)

**EXPOSES**:
- `static/js/utils.js` — API fetch helpers (with error handling), URL parameter parsing, clipboard, debounce/throttle, date/byte formatters
- Homepage as the root `/` route

**CONSUMES**:
- Subsystem 1's base.html and macros

**GREENFIELD TIER 1 SEED**:
- Homepage at `/` titled "Geospatial Data Catalog"
- Hero section with brief description of the platform
- Card grid linking to: Catalog (browse collections), Reference (API docs), System (admin)
- Cards should use the macro library from Subsystem 1
- Feature cards conditionally shown based on `stac_api_enabled` and `tipg_enabled` template context vars
- JS utility module (`utils.js`):
  - `fetchJSON(url, options)` — wrapper around fetch with JSON parsing, error handling, timeout
  - `getQueryParam(name)`, `setQueryParam(name, value)` — URL parameter helpers
  - `copyToClipboard(text)` — clipboard with fallback
  - `debounce(fn, ms)`, `throttle(fn, ms)` — timing utilities
  - `formatBytes(n)`, `formatDate(iso)`, `formatLatLng(lat, lng)` — formatters
  - `showNotification(message, type)` — toast-style notification (success/error/info)

**FILES**:
- `geotiler/templates/pages/home.html`
- `geotiler/routers/home.py`
- `geotiler/static/js/utils.js`
- Update to `geotiler/app.py` (register home router, redirect `/` to homepage)

---

### SUBSYSTEM 3: Catalog Pages

**PURPOSE**: Unified catalog (`/catalog`), STAC catalog (`/catalog/stac`), and OGC Features catalog (`/catalog/vector`). Browse, search, and navigate to viewers.

**SCOPE ESTIMATE**: ~2,000 lines across 6 files

**OWNS**: Collection browsing, search/filter, catalog-to-viewer navigation

**DEPENDS ON**: Subsystems 1 (macros, CSS), 2 (JS utils, homepage)

**EXPOSES**:
- URL contract for catalog → viewer navigation (query params)
- Collection card pattern (reusable across catalog variants)

**CONSUMES**:
- `/stac/collections` — STAC collection list
- `/vector/collections` — OGC Features collection list (TiPG)
- Subsystem 1 macros (cards, badges, data tables, empty states)
- Subsystem 2 JS utils (fetchJSON, URL params)

**GREENFIELD TIER 1 SEED**:
- **Unified catalog** (`/catalog`):
  - Fetches both `/stac/collections` and `/vector/collections` client-side
  - Merges into single list with type badge (Raster/Vector/Multidimensional)
  - Search/filter by name, type, keyword
  - Collection cards showing: title, description, type badge, spatial extent (bounding box text), temporal extent, link to appropriate viewer
  - Empty state when no collections found or when endpoints are disabled
- **STAC catalog** (`/catalog/stac`):
  - Fetches `/stac/collections`, displays with STAC-specific metadata
  - Collection detail: click to expand and see items via `/stac/search` (POST with collection filter)
  - Item cards: thumbnail (if available), asset links, datetime, geometry bbox
  - Links to raster viewer or zarr viewer based on asset media type
- **OGC Features catalog** (`/catalog/vector`):
  - Fetches `/vector/collections`, displays with OGC-specific metadata (geometry type, CRS, item count)
  - Collection cards link to vector viewer
  - Show feature count, geometry type badge, schema summary
- All catalog pages extend base.html, use macro card components
- Responsive grid layout for collection cards
- Client-side search is text filtering (no server-side search endpoint needed)

**FILES**:
- `geotiler/templates/pages/catalog/unified.html`
- `geotiler/templates/pages/catalog/stac.html`
- `geotiler/templates/pages/catalog/vector.html`
- `geotiler/routers/catalog.py`
- `geotiler/static/js/catalog.js`
- Update to `geotiler/app.py` (register catalog router)

---

### SUBSYSTEM 4: Raster & Zarr Viewers

**PURPOSE**: Raster viewer (`/viewer/raster`) for COGs and Zarr viewer (`/viewer/zarr`) for NetCDF/Zarr. Both use MapLibre with raster tile overlay and type-specific sidebar controls.

**SCOPE ESTIMATE**: ~2,500 lines across 6 files

**OWNS**: Raster tile visualization, band/colormap selection, variable selection, map interaction

**DEPENDS ON**: Subsystems 1 (macros, CSS), 2 (JS utils), 3 (URL contract)

**EXPOSES**: Nothing (leaf pages)

**CONSUMES**:
- `/cog/info?url={url}` — COG metadata (bands, stats, bounds)
- `/cog/tiles/{z}/{x}/{y}?url={url}&bidx={bands}&colormap_name={cmap}` — raster tiles
- `/xarray/info?url={url}` — Zarr metadata (variables, dimensions)
- `/xarray/tiles/{z}/{x}/{y}?url={url}&variable={var}` — Zarr tiles
- Subsystem 1 macros (sidebar_panel, form_group, map_container)
- Subsystem 2 JS utils (fetchJSON, URL params, formatters)
- Subsystem 3 URL contract (receives `?url=` from catalog links)

**GREENFIELD TIER 1 SEED**:
- **Raster viewer** (`/viewer/raster?url={cog_url}`):
  - Layout: sidebar (controls) + map (full remaining width)
  - On load: fetch `/cog/info?url={url}`, populate sidebar with band list and statistics
  - Sidebar controls: band selector (single or RGB composite), colormap dropdown (viridis, terrain, etc.), rescale min/max inputs, opacity slider
  - Map: MapLibre base map + raster tile layer from `/cog/tiles/...`
  - Tile URL updates dynamically when controls change
  - Show COG bounds as a GeoJSON outline on the map
  - Fit map to COG bounds on load
  - Display metadata panel: CRS, resolution, dimensions, data type
- **Zarr viewer** (`/viewer/zarr?url={zarr_url}&variable={var}`):
  - Same sidebar + map layout as raster
  - On load: fetch `/xarray/info?url={url}`, populate variable dropdown
  - Sidebar controls: variable selector, colormap dropdown, rescale, opacity
  - If multidimensional: dimension sliders (e.g., time step)
  - Tile layer from `/xarray/tiles/...`
  - Metadata panel: variables, dimensions, coordinate reference
- Both viewers:
  - MapLibre with light basemap (no dark mode needed)
  - Responsive — sidebar collapses to top panel on mobile
  - URL updates as controls change (shareable state via query params)
  - Error states: invalid URL, failed info fetch, no tiles available

**FILES**:
- `geotiler/templates/pages/viewer/raster.html`
- `geotiler/templates/pages/viewer/zarr.html`
- `geotiler/routers/viewer.py` (or split into viewer_raster.py/viewer_zarr.py)
- `geotiler/static/js/viewer-raster.js`
- `geotiler/static/js/viewer-zarr.js`
- Update to `geotiler/app.py` (register viewer router)

---

### SUBSYSTEM 5: Vector & H3 Viewers

**PURPOSE**: Vector viewer (`/viewer/vector`) for OGC Features on MapLibre and H3 viewer (`/viewer/h3`) for hexagonal choropleth with deck.gl overlay.

**SCOPE ESTIMATE**: ~2,500 lines across 6 files

**OWNS**: Vector feature visualization, H3 hexagonal rendering, style controls

**DEPENDS ON**: Subsystems 1 (macros, CSS), 2 (JS utils), 3 (URL contract)

**EXPOSES**: Nothing (leaf pages)

**CONSUMES**:
- `/vector/collections/{id}` — collection metadata
- `/vector/collections/{id}/items?limit={n}` — GeoJSON features
- `/vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}` — MVT vector tiles
- `/h3/query?crop={crop}&tech={tech}&scenario={scenario}` — H3 DuckDB query
- Subsystem 1 macros, Subsystem 2 JS utils, Subsystem 3 URL contract

**GREENFIELD TIER 1 SEED**:
- **Vector viewer** (`/viewer/vector?collection={collection_id}`):
  - Layout: sidebar + MapLibre map
  - On load: fetch collection metadata from `/vector/collections/{id}`
  - Two loading modes (sidebar toggle):
    - **Vector tiles** (default): add MVT source to MapLibre, render as fill/line/circle based on geometry type
    - **GeoJSON features**: fetch from `/vector/collections/{id}/items` with pagination controls (limit, offset, "load more")
  - Sidebar controls: loading mode toggle, feature limit (for GeoJSON mode), basic style controls (fill color, stroke color, opacity)
  - Feature click: popup with property table
  - Metadata panel: geometry type, CRS, feature count, schema/properties list
  - Style controls are lower priority — basic defaults are fine initially
- **H3 viewer** (`/viewer/h3?region={region_id}`):
  - Retain current deck.gl + h3-js + MapLibre integration pattern
  - Layout: MapLibre map (full width) + floating control panel (top-right)
  - Controls: crop selector, technology selector, scenario selector, palette selector (7 palettes from current implementation)
  - Data fetched from `/h3/query` endpoint (server-side DuckDB)
  - Region variants: global (default), menaap, sar, lac
  - deck.gl PolygonLayer overlaid on MapLibre
  - Color scale legend
  - Country boundaries from TopoJSON CDN
- Both viewers:
  - Responsive layout
  - Error handling for missing collections or failed queries
  - URL state for shareability

**FILES**:
- `geotiler/templates/pages/viewer/vector.html`
- `geotiler/templates/pages/viewer/h3.html`
- `geotiler/routers/viewer_vector.py` (or extend viewer.py)
- `geotiler/static/js/viewer-vector.js`
- `geotiler/static/js/viewer-h3.js`
- Update to `geotiler/app.py` if new router

---

### SUBSYSTEM 6: Reference & System Pages

**PURPOSE**: Reference page (`/reference`) consolidating API documentation, and System page (`/system`) with admin diagnostics and health monitoring.

**SCOPE ESTIMATE**: ~1,500 lines across 6 files

**OWNS**: Documentation navigation, API doc embedding, health monitoring display

**DEPENDS ON**: Subsystems 1 (macros, CSS), 2 (JS utils)

**EXPOSES**: Nothing (leaf pages)

**CONSUMES**:
- `/docs` (Swagger UI) — embedded or linked
- `/health` — health data for system page
- `/_health-fragment` or equivalent — HTMX polling target
- Subsystem 1 macros, Subsystem 2 JS utils

**GREENFIELD TIER 1 SEED**:
- **Reference page** (`/reference`):
  - Landing page with cards linking to API doc sections
  - Sections: TiTiler COG API, TiTiler XArray API, pgSTAC Searches API, STAC API, TiPG Vector API, Custom Endpoints
  - Each section: brief description + link to Swagger/ReDoc filtered view or direct endpoint table
  - Quick-start guide content (migrated from current `/guide/quick-start`)
  - Authentication guide (migrated from current `/guide/authentication`)
  - Sidebar navigation for jumping between sections
  - Code examples with copy-to-clipboard (using Subsystem 2 clipboard util)
- **System page** (`/system`):
  - Relocate current admin dashboard content
  - Health status cards: app version, uptime, database connectivity, storage auth status
  - HTMX auto-refresh (30-second polling for health fragment)
  - Service dependency cards: PostgreSQL, Azure Blob Storage, STAC API, TiPG
  - Configuration flags display (enabled features)
  - Resource info: CPU, memory (from `/health` endpoint)
  - Clear "this is for QA/UAT" messaging — will be hidden in production
- Both pages extend base.html, use component macros

**FILES**:
- `geotiler/templates/pages/reference/index.html`
- `geotiler/templates/pages/system/index.html`
- `geotiler/templates/pages/system/_health_fragment.html`
- `geotiler/routers/reference.py`
- `geotiler/routers/system.py`
- Update to `geotiler/app.py` (register routers)

---

## 6. ARB Execution Plan

### Phase 1: Design System & Base Shell (Subsystem 1)

**Pipeline**: Greenfield
**Depends on**: Nothing
**Estimated scope**: ~1,500 lines, 6 files
**Post-run validation**:
- base.html renders with navbar, footer, correct CSS
- All macros produce valid HTML
- Responsive breakpoints work at 768px and 480px
- CSS variables are defined and used consistently

### Phase 2: Homepage & JS Utilities (Subsystem 2)

**Pipeline**: Greenfield
**Depends on**: Phase 1
**Estimated scope**: ~800 lines, 4 files
**Post-run validation**:
- Homepage renders at `/` with feature cards
- Conditional cards respect `stac_api_enabled` and `tipg_enabled` flags
- `utils.js` functions work independently (fetchJSON, URL params, clipboard)
- Homepage uses macros from Phase 1

### Phase 3: Catalog Pages (Subsystem 3)

**Pipeline**: Greenfield
**Depends on**: Phases 1, 2
**Estimated scope**: ~2,000 lines, 6 files
**Post-run validation**:
- Unified catalog fetches and merges STAC + OGC collections
- Type badges correctly identify raster/vector/multidimensional
- Search/filter works client-side
- Links to viewers use correct URL contract
- Empty states display when endpoints disabled or no data
- Graceful degradation when one API endpoint is unavailable

### Phase 4a: Raster & Zarr Viewers (Subsystem 4) — PARALLEL with 4b

**Pipeline**: Greenfield
**Depends on**: Phases 1, 2, 3
**Estimated scope**: ~2,500 lines, 6 files
**Post-run validation**:
- Raster viewer loads COG info and displays tiles on MapLibre
- Band selector and colormap controls update tiles dynamically
- Zarr viewer loads variable list and renders selected variable
- Both viewers fit to data bounds on load
- URL state is preserved and shareable
- Error states display for invalid URLs

### Phase 4b: Vector & H3 Viewers (Subsystem 5) — PARALLEL with 4a

**Pipeline**: Greenfield
**Depends on**: Phases 1, 2, 3
**Estimated scope**: ~2,500 lines, 6 files
**Post-run validation**:
- Vector viewer renders MVT tiles on MapLibre
- GeoJSON mode loads features with pagination
- Feature click shows property popup
- H3 viewer renders deck.gl hexagonal choropleth
- Palette and filter controls work
- Region variants (global, menaap, sar, lac) load correctly

### Phase 5: Reference & System Pages (Subsystem 6)

**Pipeline**: Greenfield
**Depends on**: Phases 1, 2
**Estimated scope**: ~1,500 lines, 6 files
**Post-run validation**:
- Reference page renders with API doc sections and navigation
- System page shows health status with HTMX auto-refresh
- Code examples have working copy-to-clipboard
- Health fragment polls correctly

### Post-Build: Adversarial Review

After all phases complete, run the **Adversarial Review** pipeline (Split A: Design vs Runtime) on the full UI codebase to catch:
- Architecture issues across subsystems (Alpha)
- Runtime behavior gaps, JS error handling, API failure modes (Beta)
- Blind spots in cross-subsystem integration (Gamma)

---

## 7. Tier 2 Design Constraints

These are settled patterns from the existing codebase that all Greenfield runs must follow:

1. **Template rendering**: Use `render_template()` from `geotiler/templates_utils.py` with `get_template_context()` for standard variables
2. **Configuration**: Feature flags from `geotiler.config.settings` — `enable_stac_api`, `enable_tipg`, `sample_zarr_urls`, etc.
3. **Router registration**: Routers added to app via `app.include_router()` in `geotiler/app.py`
4. **Static files**: Served from `geotiler/static/` mounted at `/static`
5. **Env var naming**: `GEOTILER_COMPONENT_SETTING` convention with `env_prefix="GEOTILER_"`
6. **No build step**: All JS is vanilla, all CSS is plain, all libs from CDN
7. **CDN libraries**: MapLibre GL JS 4.x, deck.gl 9.x, h3-js 4.x, HTMX 1.9.x, TopoJSON client 3.x
8. **Version display**: `__version__` from `geotiler/__init__.py`, available in template context as `{{ version }}`

---

## 8. Infrastructure Profile

- **Runtime**: Docker container on Azure App Service (Linux)
- **App server**: Uvicorn serving FastAPI on port 8000
- **No frontend build step**: Static files served directly by FastAPI/Starlette
- **CDN dependencies**: MapLibre, deck.gl, h3-js, HTMX loaded from unpkg/jsdelivr
- **Backend APIs**: All on same origin (no CORS needed for UI → API calls)
- **Auth**: Azure OAuth for blob storage (transparent to UI), no UI-level auth required
- **Multi-instance**: Azure App Service may run multiple instances — UI is stateless so no concern

---

## 9. Migration Strategy

The rebuild replaces the existing UI entirely. Migration approach:

1. **Build new UI alongside old** — new routes (`/catalog`, `/viewer/*`, `/reference`, `/system`) don't conflict with old routes (`/cog/`, `/xarray/`, `/stac-explorer`, `/guide/*`)
2. **Switch root route** — change `/` from admin dashboard to new homepage
3. **Remove old UI** — delete old templates, routers, and static assets after new UI is validated
4. **Deprecation period** — optionally keep old routes alive with redirects for one release cycle

Old routes that get replaced:
- `/` (admin dashboard) → `/system`
- `/cog/` (landing) → `/catalog/stac` or `/viewer/raster`
- `/xarray/` (landing) → `/catalog/stac` or `/viewer/zarr`
- `/searches/` (landing) → `/catalog/stac`
- `/stac-explorer` → `/catalog/stac`
- `/map` → `/viewer/vector` or `/viewer/raster`
- `/h3` → `/viewer/h3`
- `/guide/*` → `/reference`

---

## 10. Open Questions

1. **Catalog merge complexity**: If client-side merging of STAC + OGC collections becomes complex (different schemas, pagination), revisit whether a backend `/catalog` endpoint is needed
2. **STAC item thumbnails**: Does the STAC API return thumbnail URLs in item assets? If so, the STAC catalog can show visual previews
3. **Vector tile styling**: Should the vector viewer support user-defined MapLibre style JSON, or just basic color/opacity controls?
4. **Guide content migration**: How much of the current `/guide/*` content should move to `/reference` vs be dropped?
5. **Search functionality**: Should catalog search eventually support spatial search (draw a bounding box on a map)?
