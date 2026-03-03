I now have a complete picture of the existing codebase. Let me write the final build plan.

---

# ARCHITECTURE REVIEW BOARD -- FINAL BUILD PLAN

## CONFLICTS RESOLVED

### Conflict 1: D's S6 Parallel Placement vs R's DF-2 (S6 bundling concern)

**What the conflict is:** D places S6 (Reference + System) in Phase 3 as a single run alongside S3. R flags (DF-2) that Reference and System are unrelated concerns bundled into one run. R suggests splitting them.

**Decision:** Keep S6 as a single run. At ~1,500 lines and 6 files, it is well within the safe zone. The two pages share the same structural pattern (extend base.html, import macros, call same-origin APIs, render server-side data). Splitting into two ~750-line runs adds coordination overhead with no safety benefit.

**Tradeoff:** If the System page grows (e.g., adding live log streaming or admin controls), it may need extraction later, but that is speculative.

---

### Conflict 2: D's Phase 4 (S4+S5 parallel) vs R's SE-3 and DF-3 (shared map init, H3 divergence)

**What the conflict is:** D places S4 and S5 in Phase 4 in parallel, both estimated at ~2,500 lines (flagged as approaching the ceiling). R flags (DF-3) that both share an unowned MapLibre initialization pattern, and (SE-3) that H3 diverges significantly from Vector (deck.gl dark mode vs. standard MapLibre). I identifies that no shared map init contract exists.

**Decision:** Accept D's Phase 4 parallelism but adopt R's suggestion to split S5 into two runs: S5a (Vector Viewer, ~1,200 lines) and S5b (H3 Viewer, ~1,300 lines). Both still run in Phase 4 in parallel. Additionally, adopt R's DF-3 fix: Phase 1 (S1) will produce a `map_base` CSS class and a documented CDN include pattern for MapLibre. This gives S4, S5a, and S5b a shared convention without requiring a separate shared JS file (which would be premature -- the map init code is 10-15 lines per viewer and diverges per use case).

**Tradeoff:** Three parallel runs in Phase 4 instead of two. Each is smaller and safer. The cost is one additional Greenfield pipeline invocation.

---

### Conflict 3: R's SF-2 (no scaffold run for app.py) vs D's sequence and Tier 2 constraints

**What the conflict is:** R warns (SF-2) that multiple subsystems modify `app.py` independently, risking merge conflicts. R suggests S1 creates stub router files and all `include_router` calls upfront. D's sequence has each subsystem adding its own `include_router` call.

**Decision:** S1 will produce a scaffolded `app.py` addition block with clearly commented insertion points, but will NOT pre-register routers for subsystems that do not yet exist. Each subsequent run will add its own `include_router` call at the designated insertion point. The Tier 2 input for each run will include the exact app.py registration pattern and the location (after which existing line) to insert.

**Tradeoff:** This means each downstream run modifies `app.py`, creating a sequential dependency on that file. However, since we already have a sequential Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 chain, and parallel runs within a phase do not both modify `app.py` in conflicting locations, this is manageable. The alternative (pre-registering all routers in Phase 1) would couple S1 to implementation decisions not yet made.

**TENSION WITH DESIGN CONSTRAINT:** Tier 2 says "Routers added to app via `app.include_router()` in `geotiler/app.py`". The existing `app.py` already has a complex, ordered router registration section (lines 329-410). Pre-stubbing would conflict with this established pattern of "register when the module exists". Enforcing the existing pattern.

---

### Conflict 4: R's SF-1 (URL contract unvalidated before S3) vs D's build sequence

**What the conflict is:** R warns that the catalog-to-viewer URL contract (I's Interface 5, rated VOLATILE) is consumed by S3 but not validated until S4/S5 are built. D's sequence has S3 before S4/S5.

**Decision:** Resolve by defining the URL contract as a SHARED DEFINITION (Phase 0 artifact) before any run begins. The contract will be written into Tier 2 input for both S3 and S4/S5a/S5b. This does not change D's sequence -- it front-loads the decision.

**Tradeoff:** The URL contract is decided upfront rather than discovered during implementation. If a viewer discovers it needs additional parameters, it can add them without breaking the catalog (additive change). The risk is low because the parameter set is well-understood from the existing app.

---

### Conflict 5: R's SF-3 (utils.js filename) and I's Interface 4 (utils.js API)

**What the conflict is:** R flags that base.html must reference the JS file before S2 creates it. The existing codebase uses `common.js` (confirmed in base.html line 19). The subsystem map calls it `utils.js`. I defines the API surface for `utils.js`.

**Decision:** Keep the existing filename `common.js`. The file already exists with substantial utility functions (363 lines). S2 will EXTEND `common.js` with new functions rather than creating a new file. S1 will not change the `<script>` tag (it already references `common.js`).

**TENSION WITH DESIGN CONSTRAINT:** The subsystem map specifies `utils.js` but the existing codebase uses `common.js`. Enforcing the existing convention. The subsystem map's intent is achieved by extending the existing file. All downstream Tier 1 inputs will reference `common.js` not `utils.js`.

**Tradeoff:** The file is named `common.js` which is less descriptive than `utils.js`, but changing the filename would break all existing pages that reference it. Renaming is a separate, low-priority task.

---

### Conflict 6: I's missing interface gap #3 (navbar route ownership) vs R's IF-2 (feature flag consistency)

**What the conflict is:** I identifies that navbar route items are not formally owned -- the existing navbar hardcodes links. R flags that feature flags should use Jinja2 conditionals consistently. The new design calls for a simplified 4-item navbar (Home, Catalog, Reference, System) with conditional visibility.

**Decision:** S1 owns the navbar definition. The new navbar will use `nav_active` pattern (already established) and Jinja2 `{% if %}` conditionals for feature-flag-dependent items. The navbar links will be:
- Home (`/`) -- always visible
- Catalog (`/catalog`) -- always visible (page itself conditionally shows STAC/Vector sections)
- Reference (`/reference`) -- always visible
- System (`/system`) -- always visible

This simplification means NO navbar items need feature-flag conditionality, resolving R's IF-2 concern at the navbar level. Feature flags affect content within pages, not navigation structure.

**Tradeoff:** Users always see all nav items even if underlying services are disabled. The individual pages handle degraded states with appropriate messaging. This is simpler and more predictable than conditional navigation.

---

### Conflict 7: D flags S3 at upper edge (~2,000 lines) vs R's SE-1 (S3 likely underestimated at 3,000+)

**What the conflict is:** D rates S3 at the upper edge of safe zone. R believes three catalog pages with search, filter, pagination, and empty states will exceed 3,000 lines.

**Decision:** Split S3 into S3a (Unified Catalog + Router, ~1,200 lines) and S3b (STAC + Vector Catalog Pages, ~1,200 lines). S3a builds the unified `/catalog` page and the shared catalog router with search infrastructure. S3b builds the type-specific `/catalog/stac` and `/catalog/vector` pages that extend the patterns established by S3a.

**Tradeoff:** Two sequential runs instead of one parallel-safe run. S3b depends on S3a. But both are well within the safe zone, and the split is natural: unified page first, then type-specific pages.

---

## SHARED DEFINITIONS

These artifacts must be written before any Greenfield run begins. They are provided as Tier 2 input to every run that needs them.

### SD-1: Catalog-to-Viewer URL Contract

```
VIEWER URL CONTRACT (v1)
========================
All catalog pages link to viewers using these URL patterns:

  Raster COG: /viewer/raster?url={encodeURIComponent(asset_href)}
  Zarr/NetCDF: /viewer/zarr?url={encodeURIComponent(zarr_href)}&variable={variable_name}
  Vector:      /viewer/vector?collection={collection_id}
  H3:          /viewer/h3

Parameter rules:
- All URL values MUST be encodeURIComponent()-encoded
- `variable` is optional for Zarr (viewer shows variable picker if omitted)
- `collection` is the TiPG collection ID (schema.table_name format)
- H3 viewer has no query params (standalone)

JavaScript helper (to be added to common.js in S2):
  function buildViewerUrl(type, params) {
    const base = '/viewer/' + type;
    const qs = new URLSearchParams(params).toString();
    return qs ? base + '?' + qs : base;
  }
```

### SD-2: nav_active Route Prefixes

```
NAV_ACTIVE VALUES (used by all routers)
========================================
  Homepage:    nav_active="/"
  Catalog:     nav_active="/catalog"
  Reference:   nav_active="/reference"
  System:      nav_active="/system"
  Viewers:     nav_active="/catalog"  (viewers are children of catalog conceptually)
```

### SD-3: Template Block Contract

```
BASE.HTML BLOCKS (extends "base.html")
=======================================
  {% block title %}Page Title{% endblock %}
  {% block head %}<!-- extra CSS/CDN links -->{% endblock %}
  {% block main_class %}container{% endblock %}  {# override with '' for full-bleed maps #}
  {% block content %}<!-- page content -->{% endblock %}
  {% block scripts %}<!-- page JS -->{% endblock %}
```

### SD-4: MapLibre CDN Include Pattern

```
MAP PAGE PATTERN (for any page with a MapLibre map)
====================================================
{% block head %}
<link href="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css" rel="stylesheet">
{% endblock %}

{% block main_class %}{% endblock %}  {# empty = full-bleed #}

{% block scripts %}
<script src="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js"></script>
<!-- page-specific JS -->
{% endblock %}

CSS class for map containers: .map-full { width: 100%; height: calc(100vh - 52px); }
CSS class for sidebar+map layout: .viewer-layout { display: grid; grid-template-columns: 340px 1fr; height: calc(100vh - 52px); }
```

---

## INTERFACE CONTRACTS (AUTHORITATIVE)

### IC-1: Base Template Inheritance

**Provider:** Phase 1 (S1)
**Consumers:** All subsequent phases
**Stability:** FROZEN after Phase 1 completes

Contract: `{% extends "base.html" %}` with blocks `title`, `head`, `main_class`, `content`, `scripts`. The `main_class` block defaults to `container`; override with empty string for full-bleed layouts.

### IC-2: Macro Library

**Provider:** Phase 1 (S1)
**Consumers:** All subsequent phases
**Stability:** STABLE (additive-only changes permitted)

Contract: `{% from "components/macros.html" import ... %}` with these macros:

| Macro | Signature | Purpose |
|-------|-----------|---------|
| `card` | `(title, subtitle='', body='', footer='', href='')` | Generic content card |
| `badge` | `(text, variant='default')` | Status/label badge. Variants: `healthy`, `warning`, `error`, `info`, `get`, `post` |
| `status_badge` | `(status)` | Existing macro, retained for backward compat |
| `map_container` | `(id='map', height='calc(100vh - 52px)')` | Map div with proper sizing |
| `sidebar_panel` | `(title, collapsible=false)` | Panel in sidebar layout, wraps `caller()` content |
| `form_group` | `(label, id, type='text', placeholder='')` | Label + input pair |
| `data_table` | `(headers, rows)` | Table from header list and row list-of-lists |
| `status_indicator` | `(status)` | Colored dot + text |
| `empty_state` | `(message, icon='')` | Centered empty-state callout |
| `loading_state` | `(message='Loading...')` | Spinner with message |
| `service_card` | `(name, service)` | Existing, retained |
| `dependency_card` | `(name, dep)` | Existing, retained |

Existing macros (`sample_url_card`, `guide_card`, `url_input`, `button`, `callout*`, `code_block`, `endpoint_table`, `sidebar_section`) are RETAINED unchanged.

### IC-3: CSS Class Vocabulary

**Provider:** Phase 1 (S1)
**Consumers:** All subsequent phases
**Stability:** STABLE (additive-only)

Design tokens: All existing `--ds-*`, `--spacing-*`, `--font-*`, `--radius-*`, `--shadow-*` variables retained. New additions:
- `.viewer-layout` -- grid layout for sidebar+map viewers
- `.viewer-sidebar` -- scrollable sidebar panel in viewer layout
- `.map-full` -- full-viewport map container
- `.search-bar` -- search input styling for catalog
- `.collection-card` -- standardized collection card in catalog
- `.filter-group` -- filter controls group
- `.pagination` -- pagination controls
- `.toast` -- toast notification container
- `.toast-success`, `.toast-error`, `.toast-info` -- toast variants

### IC-4: JavaScript Utility Module (common.js)

**Provider:** Phase 2 (S2)
**Consumers:** S3a, S3b, S4, S5a, S5b, S6
**Stability:** EVOLVING (additive changes only; existing functions never removed or signature-changed)

Existing functions retained as-is. New functions added by S2:

| Function | Signature | Returns |
|----------|-----------|---------|
| `fetchJSON` | `(url, options?)` | `Promise<{ok, data?, error?}>` |
| `getQueryParam` | `(name)` | `string \| null` |
| `setQueryParam` | `(name, value)` | `void` (updates URL without reload) |
| `buildViewerUrl` | `(type, params)` | `string` |
| `formatLatLng` | `(lat, lng)` | `string` (e.g., "12.34, -56.78") |
| `showNotification` | `(message, type)` | `void` (toast notification) |

Existing `copyToClipboard`, `debounce`, `throttle`, `formatBytes`, `formatDate`, `escapeHtml` are unchanged.

### IC-5: Catalog-to-Viewer Navigation Protocol

**Provider:** Phase 3 (S3a)
**Consumers:** S4, S5a, S5b
**Stability:** VOLATILE (but front-loaded via SD-1)

See SD-1 above. The `buildViewerUrl()` function in `common.js` (from IC-4) is the programmatic interface. Catalog pages generate links using this function. Viewer pages read parameters using `getQueryParam()`.

### IC-6: Template Context (Server-Side)

**Provider:** `geotiler/templates_utils.py` (existing, not modified)
**Consumers:** All routers
**Stability:** FROZEN

`get_template_context(request)` returns: `request`, `version`, `stac_api_enabled`, `tipg_enabled`, `sample_zarr_urls`. Additional kwargs passed by each router.

### IC-7: Backend API Contracts (Pre-existing)

These are STABLE, pre-existing APIs consumed by the UI:

| API | Consumer(s) | Shape |
|-----|-------------|-------|
| `GET /stac/collections` | S3a, S3b | `{"collections": [...], "links": [...]}` |
| `GET /vector/collections` | S3a, S3b | `{"collections": [...], "links": [...]}` |
| `GET /cog/info?url=` | S4 | `{"bounds": [...], "minzoom": N, "maxzoom": N, "band_metadata": [...], ...}` |
| `GET /cog/tiles/{z}/{x}/{y}?url=` | S4 | PNG/WebP tile image |
| `GET /xarray/info?url=` | S4 | `{"bounds": [...], "variables": [...], ...}` |
| `GET /xarray/tiles/{z}/{x}/{y}?url=` | S4 | PNG/WebP tile image |
| `GET /vector/collections/{id}/items` | S5a | GeoJSON FeatureCollection |
| `GET /vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}` | S5a | MVT (Mapbox Vector Tile) |
| `GET /h3/query` | S5b | `{"data": [{"h3_index": "...", "value": N}, ...], "count": N}` |
| `GET /health` | S6 | See health.py -- `{status, version, timestamp, uptime_seconds, services, dependencies, hardware, issues, config}` |
| `GET /_health-fragment` | S6 | HTML fragment (existing HTMX endpoint) |

---

## FINAL BUILD PLAN

### PHASE 1: Foundation

#### RUN 1.1: Design System & Base Shell

**Purpose:** Establish the CSS design system, base HTML template, navbar, footer, and Jinja2 macro library that all subsequent pages extend.

**Scope:** ~1,500 lines across 6 files

**Depends on:** Nothing (foundation phase)

**Produces:** IC-1 (base template), IC-2 (macro library), IC-3 (CSS vocabulary)

**Greenfield Tier 1 Input:**

```
SYSTEM: Design System & Base Shell for geotiler

You are building the CSS design system, base HTML template, navigation, footer,
and Jinja2 macro library for a geospatial tile server UI.

IMPORTANT: You are REPLACING existing files. The current files exist but are being
redesigned. You must produce complete, working replacements.

FILES TO PRODUCE:
1. geotiler/static/css/styles.css (~800 lines)
2. geotiler/templates/base.html
3. geotiler/templates/components/navbar.html
4. geotiler/templates/components/footer.html
5. geotiler/templates/components/macros.html (~300 lines)

FILE 1 — styles.css:
Complete CSS design system. Must include:

CSS Custom Properties (design tokens):
  Colors: --color-primary (#0071BC), --color-primary-dark (#245AAD), --color-navy (#053657),
          --color-cyan (#00A3DA), --color-gold (#FFC14D), --color-gray (#626F86),
          --color-gray-light (#e9ecef), --color-bg (#f8f9fa), --color-white (#ffffff)
  Status: --color-success (#059669), --color-warning (#d97706), --color-error (#dc2626)
  Code: --color-code-bg (#1e1e1e), --color-code-text (#d4d4d4)
  Spacing: --space-xs (4px), --space-sm (8px), --space-md (16px), --space-lg (24px), --space-xl (40px)
  Typography: --font-sans ("Open Sans", system stack), --font-mono (monospace stack)
  Radius: --radius-sm (4px), --radius-md (6px), --radius-lg (8px)
  Shadows: --shadow-sm, --shadow-md

  NOTE: ALSO keep the existing token names (--ds-blue-primary, --ds-navy, etc.) as aliases
  pointing to the new tokens, so existing pages that have not been migrated continue to work.
  Example: --ds-blue-primary: var(--color-primary);

Reset & base styles (box-sizing, body font, links, headings, paragraphs, lists)

Layout classes:
  .container — max-width 1200px, centered, padded
  .grid — CSS grid with auto-fit columns, minmax(280px, 1fr), gap
  .viewer-layout — grid: 340px 1fr, height calc(100vh - 52px), for sidebar+map pages
  .viewer-sidebar — overflow-y auto, padding, background white, border-right
  .map-full — width 100%, height calc(100vh - 52px)
  .page-header — white background, border-left accent, shadow
  .sidebar-layout (existing .layout-sidebar) — retained for guide pages

Navbar:
  .navbar — flex, space-between, sticky top, white bg, blue bottom border (3px)
  .navbar-brand — bold, navy
  .navbar-links — flex, gap, with .active state (blue bg, white text)

Footer:
  .footer — centered, gray text, top border, small font

Cards:
  .card — white bg, rounded, border, hover lift+shadow
  .card-grid — grid auto-fit columns
  .card-link — unstyled anchor wrapping card
  .collection-card — variant for catalog collection items
  All existing card variants RETAINED: .sample-card, .service-card, .dependency-card, etc.

Badges:
  .badge — inline pill. Variants: -healthy/-ok (green), -warning (amber), -error (red),
           -info (blue), -get (green), -post (amber), -put (blue), -delete (red)

Forms:
  .form-section, .form-group, .form-row, .form-label, .form-input, .form-select
  .form-hint — small gray hint text
  .btn, .btn-primary, .btn-secondary, .btn-sm
  .btn-group — flex row of buttons
  .search-bar — full-width input with icon placeholder

Tables:
  table, th, td base styles. .data-table variant.
  All existing table styles retained.

Code blocks: pre, code, inline code styles. Retained as-is.

Callouts: .callout, .callout-info, .callout-warning, .callout-success, .callout-error

Sidebar (docs): .sidebar, .sidebar-section, .sidebar-title, .sidebar-nav — retained

Viewer-specific:
  .filter-group — flex wrap group for filter controls
  .pagination — flex centered pagination

Toast notifications:
  .toast-container — fixed bottom-right, flex column, z-index 1000
  .toast — padded, rounded, shadow, slide-in animation
  .toast-success, .toast-error, .toast-info — colored left border

Loading/empty states:
  .loading-state — centered spinner + message
  .empty-state — centered icon + message, muted

Utility classes:
  .text-center, .text-right, .text-muted, .text-success, .text-warning, .text-error
  .mt-0, .mb-0, .mt-lg, .mb-lg
  .hidden, .sr-only (screen reader only)
  .truncate — single-line text ellipsis

ALL EXISTING admin-specific styles retained (.status-banner, .resources-section,
.resource-grid, .resource-card, .dep-card, .config-grid, .issues-section, .spinner, etc.)
These must be included so existing admin pages continue working.

Responsive breakpoints:
  @media (max-width: 768px): stack navbar, sidebar, collapse grids to 1-col
  @media (max-width: 480px): reduce base font, tighter padding

FILE 2 — base.html:
  DOCTYPE html5, lang="en"
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}geotiler{% endblock %} — geotiler v{{ version }}</title>
  <link rel="stylesheet" href="{{ url_for('static', path='css/styles.css') }}">
  {% block head %}{% endblock %}
  <body>
    {% include "components/navbar.html" %}
    <main class="{% block main_class %}container{% endblock %}">
      {% block content %}{% endblock %}
    </main>
    {% include "components/footer.html" %}
    <div id="toast-container" class="toast-container"></div>
    <script src="{{ url_for('static', path='js/common.js') }}"></script>
    {% block scripts %}{% endblock %}
  </body>

FILE 3 — navbar.html:
  <nav class="navbar">
    <a href="/" class="navbar-brand">geotiler <span class="version">v{{ version }}</span></a>
    <div class="navbar-links">
      <a href="/" class="{{ 'active' if nav_active == '/' else '' }}">Home</a>
      <a href="/catalog" class="{{ 'active' if nav_active == '/catalog' else '' }}">Catalog</a>
      <a href="/reference" class="{{ 'active' if nav_active == '/reference' else '' }}">Reference</a>
      <a href="/system" class="{{ 'active' if nav_active == '/system' else '' }}">System</a>
    </div>
  </nav>

FILE 4 — footer.html:
  <footer class="footer">
    <p>geotiler v{{ version }} |
       <a href="/docs">API Docs</a> |
       <a href="/health">Health</a>
    </p>
    <p class="powered-by">
      Powered by <a href="https://developmentseed.org/titiler/" target="_blank">TiTiler</a>,
      <a href="https://developmentseed.org/tipg/" target="_blank">TiPG</a>, and
      <a href="https://stac-utils.github.io/stac-fastapi/" target="_blank">stac-fastapi</a>
    </p>
  </footer>

FILE 5 — macros.html:
  RETAIN all existing macros (status_badge, http_badge, sample_url_card, guide_card,
  service_card, dependency_card, callout*, code_block, url_input, button,
  endpoint_table, sidebar_section).

  ADD these new macros:

  {% macro card(title, subtitle='', body='', footer='', href='') %}
  Renders a .card optionally wrapped in <a> if href provided.
  Shows title as <h3>, subtitle as <p class="text-muted">, body as content, footer.

  {% macro badge(text, variant='default') %}
  Renders <span class="badge badge-{{ variant }}">{{ text }}</span>

  {% macro map_container(id='map', height='calc(100vh - 52px)') %}
  Renders <div id="{{ id }}" style="width:100%;height:{{ height }}"></div>

  {% macro sidebar_panel(title, collapsible=false) %}
  Renders a panel div with title header. Uses {% call %} pattern for body content.

  {% macro form_group(label, id, type='text', placeholder='') %}
  Renders label + input with proper form-group wrapper.

  {% macro data_table(headers, rows) %}
  Renders a <table> with <thead> from headers list and <tbody> from rows (list of lists).

  {% macro status_indicator(status) %}
  Renders a colored dot (CSS pseudo-element) + status text.

  {% macro empty_state(message, icon='') %}
  Renders centered empty state with optional icon and message.

  {% macro loading_state(message='Loading...') %}
  Renders centered spinner animation with message text.
```

**Greenfield Tier 2 Input:**

```
DESIGN CONSTRAINTS:
1. Template rendering uses render_template() from geotiler/templates_utils.py
2. Feature flags: stac_api_enabled, tipg_enabled available in template context
3. Static files served from geotiler/static/ mounted at /static
4. No build step — all CSS is plain, no preprocessor
5. CDN libraries are loaded per-page in {% block head %} and {% block scripts %}, not globally
6. Version displayed via {{ version }} from template context
7. nav_active pattern: each router passes nav_active="/route_prefix" to render_template()
8. The existing file common.js is referenced in base.html — DO NOT rename or remove it
9. BACKWARD COMPATIBILITY: Existing pages (admin, guide, COG landing, etc.) extend base.html
   and use existing CSS classes. All existing class names and design tokens MUST be retained
   as aliases even if new naming is introduced.
10. The existing base_guide.html template extends base.html for guide pages — do not break it.
```

**Special Instructions:** This is the highest SPOF in the system (R's SPF-1). Every downstream subsystem inherits from these files. The macro signatures, CSS class names, and template block names are FROZEN API after this run completes. Prioritize correctness and completeness over cleverness. Test mentally that: (a) existing admin dashboard still renders correctly, (b) existing guide pages still render, (c) new navbar does not break any page that passes nav_active.

**Post-Run Validation:**
- Verify base.html has all 5 blocks (title, head, main_class, content, scripts)
- Verify navbar.html uses nav_active for 4 routes (/, /catalog, /reference, /system)
- Verify macros.html contains all macros from IC-2
- Verify styles.css retains all existing --ds-* token aliases
- Verify styles.css includes .viewer-layout, .map-full, .toast-container, .empty-state, .loading-state
- Verify responsive breakpoints at 768px and 480px
- Confirm existing admin and guide page patterns would not break

#### PHASE EXIT CRITERIA:
- base.html renders valid HTML5 with all blocks
- All existing pages (admin, guide, COG landing, xarray landing, H3, STAC explorer) would still render with the new base template (backward compat check)
- Macro library includes all IC-2 macros with correct signatures
- CSS includes all IC-3 classes
- Navbar shows 4 navigation items with correct nav_active highlighting

---

### PHASE 2: Shared JS & Entry Point

#### RUN 2.1: Homepage & Shared JS Utilities

**Purpose:** Build the homepage at `/` and extend `common.js` with shared utility functions used by all interactive pages.

**Scope:** ~800 lines across 4 files

**Depends on:** Phase 1 (base.html, macros, CSS)

**Produces:** IC-4 (common.js utilities), homepage route

**Greenfield Tier 1 Input:**

```
SYSTEM: Homepage & Shared JS Utilities for geotiler

You are building the main homepage and extending the shared JavaScript utility
module for a geospatial tile server UI.

FILES TO PRODUCE:
1. geotiler/templates/pages/home.html (~80 lines)
2. geotiler/routers/home.py (~30 lines)
3. geotiler/static/js/common.js — EXTEND existing file (~150 lines added)
4. geotiler/app.py — ADD router registration (small edit)

FILE 1 — pages/home.html:
  {% extends "base.html" %}
  {% from "components/macros.html" import card %}

  {% block title %}Geospatial Data Catalog{% endblock %}

  {% block content %}
  <div class="page-header">
    <h1>Geospatial Data Catalog</h1>
    <p class="page-description">Browse, visualize, and download geospatial datasets.
    Cloud-optimized raster tiles, multidimensional arrays, vector features, and STAC catalog search.</p>
  </div>

  <div class="card-grid">
    <a href="/catalog" class="card-link">
      {{ card("Catalog", subtitle="Browse Collections",
              body="Explore STAC collections, vector datasets, and raster archives. Search by type, extent, or keyword.") }}
    </a>

    <a href="/reference" class="card-link">
      {{ card("Reference", subtitle="API Documentation",
              body="Interactive API explorer, endpoint reference, and integration guides.") }}
    </a>

    <a href="/system" class="card-link">
      {{ card("System", subtitle="Health & Diagnostics",
              body="Service status, dependency health, configuration, and hardware monitoring.") }}
    </a>

    {% if stac_api_enabled %}
    <a href="/catalog/stac" class="card-link">
      {{ card("STAC Search", subtitle="Spatiotemporal Search",
              body="Search STAC items by collection, bounding box, datetime range, and properties.") }}
    </a>
    {% endif %}

    {% if tipg_enabled %}
    <a href="/catalog/vector" class="card-link">
      {{ card("Vector Data", subtitle="OGC Features",
              body="Query PostGIS collections via OGC Features API. View on map or download as GeoJSON.") }}
    </a>
    {% endif %}
  </div>
  {% endblock %}

FILE 2 — routers/home.py:
  from fastapi import APIRouter, Request
  from geotiler.templates_utils import render_template

  router = APIRouter(tags=["Home"], include_in_schema=False)

  @router.get("/home", include_in_schema=False)
  async def homepage(request: Request):
      return render_template(request, "pages/home.html", nav_active="/")

  NOTE: The existing app.py already has "/" mapped to the admin console.
  We will NOT override "/" yet. Instead, register /home as the new homepage.
  A future change will swap the root route. For now, the homepage is at /home
  and linked from the navbar "Home" button.

  ACTUALLY: Looking at the existing code, "/" is the admin dashboard. The new
  design wants "/" to be the homepage and the admin dashboard to move to /system.
  However, this is a breaking change that should happen when /system is built (Phase 3).
  For now: register /home as a new route. Phase 3 will reassign routes.

FILE 3 — common.js ADDITIONS:
  Add these functions AFTER the existing code (do not modify existing functions):

  // ============================================================================
  // API Fetch Helper
  // ============================================================================
  /**
   * Fetch JSON from an API endpoint with error handling
   * @param {string} url - URL to fetch
   * @param {object} [options] - Fetch options (method, body, timeout)
   * @returns {Promise<{ok: boolean, data?: any, error?: string}>}
   */
  async function fetchJSON(url, options = {}) {
      const { method = 'GET', body = null, timeout = 30000 } = options;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);

      try {
          const fetchOptions = {
              method,
              signal: controller.signal,
              headers: { 'Content-Type': 'application/json' },
          };
          if (body) fetchOptions.body = JSON.stringify(body);

          const response = await fetch(url, fetchOptions);
          const data = await response.json();

          if (!response.ok) {
              return { ok: false, error: data.detail || `HTTP ${response.status}` };
          }
          return { ok: true, data };
      } catch (err) {
          if (err.name === 'AbortError') return { ok: false, error: 'Request timed out' };
          return { ok: false, error: err.message };
      } finally {
          clearTimeout(timer);
      }
  }

  // ============================================================================
  // URL Parameter Helpers
  // ============================================================================
  function getQueryParam(name) {
      return new URLSearchParams(window.location.search).get(name);
  }

  function setQueryParam(name, value) {
      const url = new URL(window.location);
      if (value === null || value === undefined || value === '') {
          url.searchParams.delete(name);
      } else {
          url.searchParams.set(name, value);
      }
      window.history.replaceState({}, '', url);
  }

  // ============================================================================
  // Viewer URL Builder
  // ============================================================================
  function buildViewerUrl(type, params) {
      const base = '/viewer/' + type;
      const qs = new URLSearchParams(params).toString();
      return qs ? base + '?' + qs : base;
  }

  // ============================================================================
  // Formatters
  // ============================================================================
  function formatLatLng(lat, lng) {
      return lat.toFixed(4) + ', ' + lng.toFixed(4);
  }

  // ============================================================================
  // Toast Notifications
  // ============================================================================
  function showNotification(message, type = 'info') {
      const container = document.getElementById('toast-container');
      if (!container) return;

      const toast = document.createElement('div');
      toast.className = 'toast toast-' + type;
      toast.textContent = message;
      container.appendChild(toast);

      // Auto-remove after 4 seconds
      setTimeout(() => {
          toast.style.opacity = '0';
          setTimeout(() => toast.remove(), 300);
      }, 4000);
  }

FILE 4 — app.py modification:
  Add at top of file with other router imports:
    from geotiler.routers import home

  Add in the Routers section (after health router, before TiTiler):
    # Homepage
    app.include_router(home.router)
```

**Greenfield Tier 2 Input:**

```
DESIGN CONSTRAINTS:
1. Use render_template() from geotiler.templates_utils with nav_active="/home"
2. Router pattern: APIRouter(tags=["Home"], include_in_schema=False)
3. Static JS file is geotiler/static/js/common.js — EXTEND, do not replace
4. No build step — vanilla JS only, no modules, no imports
5. All functions are global (attached to window scope implicitly)
6. base.html already includes <script src="common.js"> — no additional script tag needed
7. base.html already includes <div id="toast-container"> — notifications render there
8. Feature flags: stac_api_enabled and tipg_enabled available as Jinja2 template vars
9. App registration: add include_router in geotiler/app.py Routers section
10. The "/" route is currently the admin dashboard — do NOT override it in this run
```

**Special Instructions:** The common.js extensions are critical shared infrastructure (R's SPF-2). Every interactive page downstream will call `fetchJSON`, `getQueryParam`, `showNotification`. Test the function signatures carefully. The `fetchJSON` function MUST return `{ok, data?, error?}` consistently -- never throw exceptions. The toast notification function must handle the case where `toast-container` div does not exist (graceful degradation for pages that do not use new base.html yet).

**Post-Run Validation:**
- Verify common.js has fetchJSON, getQueryParam, setQueryParam, buildViewerUrl, formatLatLng, showNotification
- Verify fetchJSON returns {ok: true, data} on success and {ok: false, error} on failure
- Verify homepage template extends base.html and uses card macro
- Verify home router passes nav_active="/"
- Verify app.py registers home.router
- Verify existing common.js functions (setUrl, getCogInfo, etc.) are unchanged

#### PHASE EXIT CRITERIA:
- Homepage renders at `/home` with card grid
- common.js API surface matches IC-4
- Existing pages (admin at `/`, COG landing, guide) continue to work
- No JavaScript errors in browser console when loading any existing page

---

### PHASE 3: Catalog & Structural Pages

#### RUN 3.1: Unified Catalog & Router Infrastructure

**Purpose:** Build the unified catalog page at `/catalog`, the catalog router with collection-fetching infrastructure, and the catalog JavaScript module.

**Scope:** ~1,200 lines across 4 files

**Depends on:** Phase 1 (macros, CSS), Phase 2 (common.js utilities)

**Produces:** Catalog router, unified catalog page, catalog JS module, collection card pattern

**Greenfield Tier 1 Input:**

```
SYSTEM: Unified Catalog Page for geotiler

Build the unified catalog page that lists all available collections (STAC + Vector)
in a searchable, filterable grid.

FILES TO PRODUCE:
1. geotiler/templates/pages/catalog/unified.html (~150 lines)
2. geotiler/routers/catalog.py (~100 lines)
3. geotiler/static/js/catalog.js (~250 lines)
4. geotiler/app.py — ADD catalog router registration

FILE 1 — pages/catalog/unified.html:
  {% extends "base.html" %}
  {% from "components/macros.html" import card, badge, empty_state, loading_state %}

  {% block title %}Catalog{% endblock %}

  {% block content %}
  <div class="page-header">
    <h1>Data Catalog</h1>
    <p class="page-description">Browse all available geospatial datasets.</p>
  </div>

  <!-- Search and filter bar -->
  <div class="filter-group">
    <input type="text" id="catalog-search" class="form-input search-bar"
           placeholder="Search collections by name or description...">
    <div class="btn-group">
      <button class="btn btn-secondary btn-sm" data-filter="all" onclick="filterCatalog('all')">All</button>
      <button class="btn btn-secondary btn-sm" data-filter="raster" onclick="filterCatalog('raster')">Raster</button>
      <button class="btn btn-secondary btn-sm" data-filter="vector" onclick="filterCatalog('vector')">Vector</button>
    </div>
  </div>

  <!-- Collection grid (populated by JS) -->
  <div id="catalog-grid" class="card-grid">
    {{ loading_state("Loading collections...") }}
  </div>

  <!-- Empty state (hidden by default) -->
  <div id="catalog-empty" class="hidden">
    {{ empty_state("No collections match your search.", "") }}
  </div>

  <!-- Tab links to type-specific catalogs -->
  <div style="margin-top: var(--space-xl); text-align: center;">
    {% if stac_api_enabled %}
    <a href="/catalog/stac" class="btn btn-secondary">STAC Collections</a>
    {% endif %}
    {% if tipg_enabled %}
    <a href="/catalog/vector" class="btn btn-secondary">Vector Collections</a>
    {% endif %}
  </div>
  {% endblock %}

  {% block scripts %}
  <script src="{{ url_for('static', path='js/catalog.js') }}"></script>
  <script>
    document.addEventListener('DOMContentLoaded', () => {
      loadUnifiedCatalog({{ stac_api_enabled | tojson }}, {{ tipg_enabled | tojson }});
    });
  </script>
  {% endblock %}

FILE 2 — routers/catalog.py:
  from fastapi import APIRouter, Request
  from geotiler.templates_utils import render_template
  from geotiler.config import settings

  router = APIRouter(prefix="/catalog", tags=["Catalog"], include_in_schema=False)

  @router.get("", include_in_schema=False)
  @router.get("/", include_in_schema=False)
  async def unified_catalog(request: Request):
      return render_template(request, "pages/catalog/unified.html", nav_active="/catalog")

  @router.get("/stac", include_in_schema=False)
  async def stac_catalog(request: Request):
      """Placeholder — built in Run 3.2"""
      return render_template(request, "pages/catalog/stac.html", nav_active="/catalog")

  @router.get("/vector", include_in_schema=False)
  async def vector_catalog(request: Request):
      """Placeholder — built in Run 3.2"""
      return render_template(request, "pages/catalog/vector.html", nav_active="/catalog")

FILE 3 — catalog.js:
  Client-side catalog logic.

  async function loadUnifiedCatalog(stacEnabled, tipgEnabled) {
    const grid = document.getElementById('catalog-grid');
    const emptyEl = document.getElementById('catalog-empty');
    let collections = [];

    // Fetch STAC collections
    if (stacEnabled) {
      const result = await fetchJSON('/stac/collections');
      if (result.ok && result.data.collections) {
        collections = collections.concat(
          result.data.collections.map(c => ({
            id: c.id,
            title: c.title || c.id,
            description: c.description || '',
            type: 'raster',  // STAC collections are raster
            extent: c.extent,
            href: buildViewerUrl('raster', { url: '' }),  // placeholder
            source: 'stac',
          }))
        );
      }
    }

    // Fetch Vector collections
    if (tipgEnabled) {
      const result = await fetchJSON('/vector/collections');
      if (result.ok && result.data.collections) {
        collections = collections.concat(
          result.data.collections
            .filter(c => c.id !== 'public.spatial_ref_sys')  // exclude system tables
            .map(c => ({
              id: c.id,
              title: c.title || c.id,
              description: c.description || '',
              type: 'vector',
              extent: c.extent,
              href: buildViewerUrl('vector', { collection: c.id }),
              source: 'tipg',
            }))
        );
      }
    }

    // Render collection cards
    renderCollections(collections);

    // Wire up search
    const searchInput = document.getElementById('catalog-search');
    searchInput.addEventListener('input', debounce(() => {
      const query = searchInput.value.toLowerCase();
      const filtered = collections.filter(c =>
        c.title.toLowerCase().includes(query) ||
        c.description.toLowerCase().includes(query) ||
        c.id.toLowerCase().includes(query)
      );
      renderCollections(filtered);
    }, 300));

    // Store for filter buttons
    window._catalogCollections = collections;
  }

  function filterCatalog(type) {
    const collections = window._catalogCollections || [];
    const filtered = type === 'all' ? collections : collections.filter(c => c.type === type);
    renderCollections(filtered);
    // Update active button
    document.querySelectorAll('[data-filter]').forEach(btn => {
      btn.classList.toggle('btn-primary', btn.dataset.filter === type);
      btn.classList.toggle('btn-secondary', btn.dataset.filter !== type);
    });
  }

  function renderCollections(collections) {
    const grid = document.getElementById('catalog-grid');
    const emptyEl = document.getElementById('catalog-empty');

    if (collections.length === 0) {
      grid.innerHTML = '';
      emptyEl.classList.remove('hidden');
      return;
    }
    emptyEl.classList.add('hidden');

    grid.innerHTML = collections.map(c => `
      <a href="${escapeHtml(c.href)}" class="card-link">
        <div class="card collection-card">
          <div class="card-header">
            <h3>${escapeHtml(c.title)}</h3>
            <span class="badge badge-${c.type === 'raster' ? 'info' : 'healthy'}">${c.type}</span>
          </div>
          <p>${escapeHtml(c.description).substring(0, 150)}</p>
        </div>
      </a>
    `).join('');
  }

FILE 4 — app.py addition:
  Import: from geotiler.routers import catalog
  Registration: app.include_router(catalog.router)
  Place AFTER the homepage router registration.
```

**Greenfield Tier 2 Input:**

```
DESIGN CONSTRAINTS:
1. Use render_template() with nav_active="/catalog"
2. Router prefix: /catalog. Use APIRouter(prefix="/catalog", ...)
3. catalog.js uses functions from common.js (fetchJSON, debounce, escapeHtml, buildViewerUrl)
4. No CDN libraries needed for catalog pages (no maps)
5. Feature flags passed as Jinja2 context (stac_api_enabled, tipg_enabled)
6. Viewer URL Contract (SD-1): Raster=/viewer/raster?url=..., Vector=/viewer/vector?collection=...
7. STAC collections API: GET /stac/collections returns {collections: [...], links: [...]}
8. Vector collections API: GET /vector/collections returns {collections: [...], links: [...]}
9. The STAC and Vector catalog sub-pages are placeholders in this run — they will be built in Run 3.2
```

**Post-Run Validation:**
- Verify /catalog renders with search bar, filter buttons, and collection grid
- Verify catalog.js calls fetchJSON for both STAC and Vector collections
- Verify filter buttons toggle correctly
- Verify collection cards link to correct viewer URLs per SD-1
- Verify app.py registers catalog.router

---

#### RUN 3.2: STAC & Vector Catalog Sub-Pages

**Purpose:** Build the type-specific STAC catalog and Vector catalog pages with detailed collection information and navigation to viewers.

**Scope:** ~1,200 lines across 3 files (2 templates + catalog.js extension)

**Depends on:** Phase 1, Phase 2, Run 3.1 (catalog router already exists)

**Produces:** STAC catalog page, Vector catalog page, extended catalog.js

**Greenfield Tier 1 Input:**

```
SYSTEM: STAC & Vector Catalog Sub-Pages for geotiler

Build the type-specific catalog pages for STAC collections and Vector collections.
These extend the catalog router created in Run 3.1.

FILES TO PRODUCE:
1. geotiler/templates/pages/catalog/stac.html (~150 lines)
2. geotiler/templates/pages/catalog/vector.html (~150 lines)
3. geotiler/static/js/catalog.js — EXTEND with stac/vector specific functions (~200 lines added)

FILE 1 — pages/catalog/stac.html:
  {% extends "base.html" %}
  {% from "components/macros.html" import card, badge, data_table, empty_state, loading_state %}

  {% block title %}STAC Collections{% endblock %}

  {% block content %}
  <div class="page-header">
    <h1>STAC Collections</h1>
    <p class="page-description">Browse spatiotemporal asset catalogs. Click a collection to explore items on the map.</p>
  </div>

  <input type="text" id="stac-search" class="form-input search-bar"
         placeholder="Search STAC collections...">

  <div id="stac-grid" class="card-grid">
    {{ loading_state("Loading STAC collections...") }}
  </div>

  <div id="stac-empty" class="hidden">
    {{ empty_state("No STAC collections available.") }}
  </div>

  <!-- Collection detail panel (shown when a collection is selected) -->
  <div id="collection-detail" class="hidden">
    <div class="page-header">
      <h2 id="detail-title"></h2>
      <p id="detail-description"></p>
    </div>
    <div id="detail-metadata"></div>
    <div class="btn-group">
      <a id="detail-viewer-link" href="#" class="btn btn-primary">Open in Viewer</a>
      <a id="detail-api-link" href="#" class="btn btn-secondary" target="_blank">View API JSON</a>
    </div>
  </div>
  {% endblock %}

  {% block scripts %}
  <script src="{{ url_for('static', path='js/catalog.js') }}"></script>
  <script>
    document.addEventListener('DOMContentLoaded', () => loadStacCatalog());
  </script>
  {% endblock %}

  Each STAC collection card shows: title, description (truncated), temporal extent,
  spatial extent summary, item count (if available), badge for collection type.
  Click navigates to /viewer/raster?url= (for the first item's asset).
  "View items" link to /stac/collections/{id}/items.

FILE 2 — pages/catalog/vector.html:
  Similar structure to stac.html but for TiPG/OGC vector collections.
  Each collection card shows: title/id, description, geometry type badge,
  schema name. Click navigates to /viewer/vector?collection={id}.

FILE 3 — catalog.js additions:
  async function loadStacCatalog() — fetches /stac/collections, renders STAC-specific cards
  async function loadVectorCatalog() — fetches /vector/collections, renders vector-specific cards
  function showCollectionDetail(collection) — populates detail panel
  function formatExtent(extent) — formats spatial/temporal extent for display

NOTE: The catalog.py router already has /stac and /vector routes from Run 3.1.
No router changes needed.
```

**Greenfield Tier 2 Input:**

```
DESIGN CONSTRAINTS:
1. Templates extend base.html, use macros from macros.html
2. nav_active="/catalog" for both sub-pages
3. catalog.js is EXTENDED — existing functions from Run 3.1 must not be modified
4. STAC collection API: GET /stac/collections → {collections: [{id, title, description, extent, links}]}
5. Vector collection API: GET /vector/collections → {collections: [{id, title, description, links}]}
6. Viewer URL Contract: /viewer/raster?url=..., /viewer/vector?collection=...
7. Feature flags: stac_api_enabled and tipg_enabled used for conditional rendering
8. catalog.js uses common.js functions (fetchJSON, debounce, escapeHtml, buildViewerUrl, getQueryParam)
```

**Post-Run Validation:**
- Verify /catalog/stac renders STAC collections
- Verify /catalog/vector renders vector collections
- Verify collection cards link to correct viewer URLs
- Verify search filtering works on both pages
- Verify catalog.js does not break unified catalog page from Run 3.1

---

#### RUN 3.3: Reference & System Pages

**Purpose:** Build the Reference page (API documentation hub) and System page (health monitoring dashboard), replacing the existing admin console at `/`.

**Scope:** ~1,500 lines across 6 files

**Depends on:** Phase 1 (macros, CSS), Phase 2 (common.js)

**Produces:** Reference page, System page with health monitoring

**Greenfield Tier 1 Input:**

```
SYSTEM: Reference & System Pages for geotiler

Build the Reference page consolidating API documentation and the System page
with health monitoring and diagnostics.

IMPORTANT: The existing admin dashboard at "/" (geotiler/routers/admin.py,
templates/pages/admin/*) will continue to exist. The System page is a NEW page
at /system that REUSES the existing /_health-fragment HTMX endpoint. Do NOT
modify admin.py or admin templates.

FILES TO PRODUCE:
1. geotiler/templates/pages/reference/index.html (~120 lines)
2. geotiler/templates/pages/system/index.html (~200 lines)
3. geotiler/templates/pages/system/_health_fragment.html (~100 lines)
4. geotiler/routers/reference.py (~40 lines)
5. geotiler/routers/system.py (~60 lines)
6. geotiler/app.py — ADD router registrations

FILE 1 — pages/reference/index.html:
  {% extends "base.html" %}
  {% from "components/macros.html" import card %}

  {% block title %}Reference{% endblock %}

  {% block content %}
  <div class="page-header">
    <h1>API Reference</h1>
    <p class="page-description">Documentation, API explorer, and integration guides.</p>
  </div>

  <div class="card-grid">
    <a href="/docs" class="card-link">
      {{ card("Swagger UI", subtitle="Interactive API Explorer",
              body="Try API endpoints directly. Supports COG, XArray, STAC, Vector, and Search APIs.") }}
    </a>

    <a href="/guide/" class="card-link">
      {{ card("User Guide", subtitle="Getting Started",
              body="Tutorials for data scientists and web developers. Authentication, queries, and map integration.") }}
    </a>

    <a href="/health" class="card-link">
      {{ card("Health API", subtitle="JSON Health Check",
              body="Machine-readable health status for monitoring integration.") }}
    </a>

    {{ card("Endpoint Overview", body="
      <table>
        <tr><td><code>GET /cog/*</code></td><td>Cloud Optimized GeoTIFF tiles</td></tr>
        <tr><td><code>GET /xarray/*</code></td><td>Zarr / NetCDF tiles</td></tr>
        <tr><td><code>GET /searches/*</code></td><td>pgSTAC mosaic searches</td></tr>
        <tr><td><code>GET /stac/*</code></td><td>STAC catalog API</td></tr>
        <tr><td><code>GET /vector/*</code></td><td>OGC Features + Vector Tiles</td></tr>
        <tr><td><code>GET /h3/*</code></td><td>H3 Explorer</td></tr>
      </table>
    ") }}
  </div>
  {% endblock %}

FILE 2 — pages/system/index.html:
  {% extends "base.html" %}
  {% from "components/macros.html" import status_indicator, badge %}

  {% block title %}System{% endblock %}

  {% block head %}
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  {% endblock %}

  {% block content %}
  <div class="page-header">
    <h1>System Status</h1>
    <p class="page-description">Service health, dependency status, and runtime diagnostics.</p>
  </div>

  <!-- Health content loaded via HTMX (auto-refreshes every 30s) -->
  <div id="health-content"
       hx-get="/system/_health-fragment"
       hx-trigger="load, every 30s"
       hx-swap="innerHTML">
    <div class="loading-state">Loading system status...</div>
  </div>

  <div style="margin-top: var(--space-xl);">
    <a href="/health" class="btn btn-secondary">View Raw JSON</a>
    <a href="/" class="btn btn-secondary">Admin Dashboard</a>
  </div>
  {% endblock %}

FILE 3 — pages/system/_health_fragment.html:
  Renders the health data as an HTMX fragment (no base template).

  <!-- Status banner -->
  <div class="status-banner" style="border-left-color: var(--color-{{ 'success' if health.status == 'healthy' else 'error' }});">
    <div class="status-banner-header">
      <div class="status-banner-title">
        {{ health.status | upper }}
        {{ status_indicator(health.status) }}
      </div>
      <span class="text-muted">v{{ health.version }} | {{ health.response_time_ms }}ms</span>
    </div>
  </div>

  <!-- Services grid -->
  <h2 class="section-header">Services</h2>
  <div class="cards-grid">
    {% for name, svc in health.services.items() %}
    <div class="card" style="border-left: 4px solid var(--color-{{ 'success' if svc.available else 'error' }});">
      <div class="card-header">
        <h3>{{ name }}</h3>
        {{ badge(svc.status, svc.status) }}
      </div>
      <p class="card-description">{{ svc.description }}</p>
    </div>
    {% endfor %}
  </div>

  <!-- Dependencies -->
  <h2 class="section-header">Dependencies</h2>
  <div class="cards-grid">
    {% for name, dep in health.dependencies.items() %}
    <div class="dep-card dep-{{ dep.status }}">
      <div class="dep-header">
        <span class="dep-name">{{ name }}</span>
        {{ badge(dep.status, dep.status) }}
      </div>
      {% if dep.ping_time_ms %}<div class="dep-detail">Ping: {{ "%.1f" | format(dep.ping_time_ms) }}ms</div>{% endif %}
      {% if dep.expires_in_seconds %}<div class="dep-detail">TTL: {{ (dep.expires_in_seconds / 60) | int }}min</div>{% endif %}
    </div>
    {% endfor %}
  </div>

  <!-- Issues -->
  {% if health.issues %}
  <div class="issues-section">
    <div class="issues-header">Issues Detected</div>
    <ul class="issues-list">
      {% for issue in health.issues %}
      <li>{{ issue }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

FILE 4 — routers/reference.py:
  from fastapi import APIRouter, Request
  from geotiler.templates_utils import render_template

  router = APIRouter(tags=["Reference"], include_in_schema=False)

  @router.get("/reference", include_in_schema=False)
  async def reference_page(request: Request):
      return render_template(request, "pages/reference/index.html", nav_active="/reference")

FILE 5 — routers/system.py:
  from fastapi import APIRouter, Request, Response
  from fastapi.responses import HTMLResponse
  from geotiler.templates_utils import render_template, templates, get_template_context
  from geotiler.routers.health import health as get_health_data

  router = APIRouter(tags=["System"], include_in_schema=False)

  @router.get("/system", include_in_schema=False)
  async def system_page(request: Request):
      return render_template(request, "pages/system/index.html", nav_active="/system")

  @router.get("/system/_health-fragment", response_class=HTMLResponse, include_in_schema=False)
  async def system_health_fragment(request: Request):
      response = Response()
      health_data = await get_health_data(request, response)
      context = get_template_context(request, health=health_data)
      return templates.TemplateResponse("pages/system/_health_fragment.html", context)

FILE 6 — app.py additions:
  Import: from geotiler.routers import reference, system
  Registration (after catalog router):
    app.include_router(reference.router)
    app.include_router(system.router)
```

**Greenfield Tier 2 Input:**

```
DESIGN CONSTRAINTS:
1. Use render_template() for full pages, templates.TemplateResponse for HTMX fragments
2. nav_active="/reference" for reference, nav_active="/system" for system
3. System page uses HTMX 1.9.10 for auto-refresh (CDN in head block)
4. Health data shape: {status, version, timestamp, uptime_seconds, response_time_ms,
   services: {name: {status, available, description, endpoints, details?}},
   dependencies: {name: {status, ...}}, hardware: {...}, issues: [...], config: {...}}
5. The existing admin.py and admin templates are NOT modified — they continue to work at /
6. The /_health-fragment at root is the EXISTING admin HTMX endpoint — system page uses
   its OWN /system/_health-fragment endpoint
7. HTMX loaded from CDN — not installed globally (only on pages that need it)
8. Reference page is purely static content — no JS required
```

**Special Instructions:** The System page's `_health_fragment.html` must match the structure of the existing `/health` JSON response exactly (R's IF-3). Reference the `_build_service_status()` function in health.py for the exact field names. The fragment template renders the same data that the existing admin dashboard renders, but with the new design system classes.

**Post-Run Validation:**
- Verify /reference renders with API documentation cards
- Verify /system renders and HTMX loads health fragment
- Verify /system/_health-fragment returns HTML with service/dependency cards
- Verify existing admin dashboard at / still works unchanged
- Verify app.py registers both new routers

#### PHASE EXIT CRITERIA:
- /catalog renders with collection grid, search, and filter
- /catalog/stac and /catalog/vector render type-specific collections
- /reference renders with documentation links
- /system renders with live health monitoring via HTMX
- All pages use nav_active correctly (catalog pages highlight "Catalog", etc.)
- Homepage at /home still renders
- Existing admin dashboard at / still renders
- No JavaScript errors on any page

---

### PHASE 4: Viewers

#### RUN 4.1: Raster & Zarr Viewers

**Purpose:** Build the COG raster viewer and Zarr/NetCDF viewer with MapLibre tile overlays and sidebar controls.

**Scope:** ~2,500 lines across 6 files

**Depends on:** Phase 1 (macros, CSS), Phase 2 (common.js), Phase 3 (URL contract)

**Produces:** Raster viewer page, Zarr viewer page

**Greenfield Tier 1 Input:**

```
SYSTEM: Raster & Zarr Viewers for geotiler

Build two map-based viewers: one for Cloud Optimized GeoTIFFs and one for
Zarr/NetCDF multidimensional arrays. Both use MapLibre GL JS with raster tile
overlays from the existing /cog and /xarray APIs.

FILES TO PRODUCE:
1. geotiler/templates/pages/viewer/raster.html (~100 lines)
2. geotiler/templates/pages/viewer/zarr.html (~120 lines)
3. geotiler/routers/viewer.py (~80 lines)
4. geotiler/static/js/viewer-raster.js (~500 lines)
5. geotiler/static/js/viewer-zarr.js (~600 lines)
6. geotiler/app.py — ADD viewer router registration

FILE 1 — pages/viewer/raster.html:
  {% extends "base.html" %}
  {% from "components/macros.html" import map_container, sidebar_panel, form_group, badge, loading_state %}

  {% block title %}Raster Viewer{% endblock %}
  {% block head %}
  <link href="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css" rel="stylesheet">
  {% endblock %}

  {% block main_class %}{% endblock %}  {# full-bleed for map #}

  {% block content %}
  <div class="viewer-layout">
    <!-- Sidebar -->
    <div class="viewer-sidebar">
      <h2>Raster Viewer</h2>

      <!-- URL input -->
      <div class="form-group">
        <label class="form-label" for="cog-url">COG URL</label>
        <input type="text" id="cog-url" class="form-input"
               placeholder="https://storage.blob.core.windows.net/container/file.tif">
        <div class="form-hint">Paste a Cloud Optimized GeoTIFF URL</div>
      </div>
      <button class="btn btn-primary" onclick="loadRaster()">Load</button>

      <!-- Info panel (populated after load) -->
      <div id="raster-info" class="hidden" style="margin-top: var(--space-lg);">
        <h3>Dataset Info</h3>
        <div id="raster-metadata"></div>

        <!-- Band selection -->
        <div class="form-group">
          <label class="form-label">Bands</label>
          <div id="band-controls"></div>
        </div>

        <!-- Colormap selection -->
        <div class="form-group">
          <label class="form-label" for="colormap-select">Colormap</label>
          <select id="colormap-select" class="form-select" onchange="updateTiles()">
            <option value="">Default</option>
            <option value="viridis">Viridis</option>
            <option value="plasma">Plasma</option>
            <option value="inferno">Inferno</option>
            <option value="magma">Magma</option>
            <option value="terrain">Terrain</option>
            <option value="rdylgn">Red-Yellow-Green</option>
          </select>
        </div>

        <!-- Rescale -->
        <div class="form-row">
          <div class="form-group">
            <label class="form-label" for="rescale-min">Min</label>
            <input type="number" id="rescale-min" class="form-input" placeholder="Auto">
          </div>
          <div class="form-group">
            <label class="form-label" for="rescale-max">Max</label>
            <input type="number" id="rescale-max" class="form-input" placeholder="Auto">
          </div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="updateTiles()">Apply</button>
      </div>
    </div>

    <!-- Map -->
    <div id="map" class="map-full"></div>
  </div>
  {% endblock %}

  {% block scripts %}
  <script src="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js"></script>
  <script src="{{ url_for('static', path='js/viewer-raster.js') }}"></script>
  <script>
    document.addEventListener('DOMContentLoaded', () => initRasterViewer());
  </script>
  {% endblock %}

FILE 2 — pages/viewer/zarr.html:
  Similar structure but with:
  - Variable selector dropdown (populated from /xarray/info?url=...)
  - Time step selector (if temporal dimension exists)
  - Colormap selector
  - No band selection (Zarr uses named variables)

FILE 3 — routers/viewer.py:
  from fastapi import APIRouter, Request
  from geotiler.templates_utils import render_template

  router = APIRouter(prefix="/viewer", tags=["Viewers"], include_in_schema=False)

  @router.get("/raster", include_in_schema=False)
  async def raster_viewer(request: Request):
      return render_template(request, "pages/viewer/raster.html", nav_active="/catalog")

  @router.get("/zarr", include_in_schema=False)
  async def zarr_viewer(request: Request):
      return render_template(request, "pages/viewer/zarr.html", nav_active="/catalog")

FILE 4 — viewer-raster.js:
  Core functions:
  - initRasterViewer(): Initialize MapLibre map, read URL from getQueryParam('url'),
    auto-load if URL present
  - loadRaster(): Read URL from input, call fetchJSON('/cog/info?url=...'),
    display metadata, add tile layer
  - addTileLayer(url, bounds, options): Add raster tile source+layer to map,
    fit bounds
  - updateTiles(): Rebuild tile URL with current colormap/rescale/bands, swap source
  - displayMetadata(info): Render bounds, bands, CRS, dtype info in sidebar

  MapLibre tile source pattern:
    map.addSource('raster-tiles', {
      type: 'raster',
      tiles: ['/cog/tiles/{z}/{x}/{y}?url=' + encodeURIComponent(url)
              + '&colormap_name=' + colormap
              + '&rescale=' + min + ',' + max],
      tileSize: 256,
      bounds: [west, south, east, north],
    });

FILE 5 — viewer-zarr.js:
  Similar pattern to raster but:
  - loadZarr(): Calls /xarray/info?url=... to get variable list
  - Variable selector populates from info response
  - Tile URL: /xarray/tiles/{z}/{x}/{y}?url=...&variable=...
  - Time slider if temporal dimension detected

FILE 6 — app.py addition:
  Import: from geotiler.routers import viewer
  Registration: app.include_router(viewer.router)
```

**Greenfield Tier 2 Input:**

```
DESIGN CONSTRAINTS:
1. MapLibre GL JS 4.x loaded from CDN (unpkg.com/maplibre-gl@4)
2. Map pages use {% block main_class %}{% endblock %} for full-bleed layout
3. Viewer URLs read query params on load: getQueryParam('url'), getQueryParam('variable')
4. nav_active="/catalog" (viewers are conceptual children of catalog)
5. COG tile URL pattern: /cog/tiles/{z}/{x}/{y}?url={encoded_url}&colormap_name={cm}&rescale={min},{max}
6. XArray tile URL pattern: /xarray/tiles/{z}/{x}/{y}?url={encoded_url}&variable={var}
7. COG info API: GET /cog/info?url={url} → {bounds, minzoom, maxzoom, band_metadata, dtype, ...}
8. XArray info API: GET /xarray/info?url={url} → {bounds, variables, dims, ...}
9. Use fetchJSON from common.js, showNotification for errors
10. No module bundling — all JS is vanilla with global functions
11. Viewer layout: .viewer-layout CSS grid with .viewer-sidebar and .map-full
12. MapLibre initialization: center [0, 20], zoom 2, style: demotiles.maplibre.org
```

**Special Instructions:** The raster viewer is the most complex single JS file in the project. Keep the code well-organized with clear function boundaries. The tile layer swap pattern (remove old source, add new source when parameters change) must handle MapLibre's async source loading correctly. Test the `updateTiles()` flow mentally: user changes colormap -> JS rebuilds tile URL -> old layer/source removed -> new source/layer added -> map re-renders.

**Post-Run Validation:**
- Verify /viewer/raster renders with sidebar + full-bleed map
- Verify /viewer/zarr renders with sidebar + full-bleed map
- Verify URL auto-load: /viewer/raster?url=... pre-fills input and loads data
- Verify tile layer renders on map after loading a COG URL
- Verify colormap and rescale controls update tiles
- Verify zarr variable selector populates from /xarray/info

---

#### RUN 4.2: Vector Viewer

**Purpose:** Build the OGC Features vector viewer with MapLibre for displaying GeoJSON features and MVT vector tiles.

**Scope:** ~1,200 lines across 3 files

**Depends on:** Phase 1 (macros, CSS), Phase 2 (common.js), Phase 3 (URL contract)

**Produces:** Vector viewer page

**Greenfield Tier 1 Input:**

```
SYSTEM: Vector Viewer for geotiler

Build a map-based viewer for OGC Features (TiPG) vector data. Uses MapLibre GL JS
to display GeoJSON features and MVT (Mapbox Vector Tile) layers.

FILES TO PRODUCE:
1. geotiler/templates/pages/viewer/vector.html (~100 lines)
2. geotiler/static/js/viewer-vector.js (~500 lines)
3. geotiler/routers/viewer.py — EXTEND with vector route (or verify it exists in viewer.py)

FILE 1 — pages/viewer/vector.html:
  {% extends "base.html" %}
  {% from "components/macros.html" import map_container, sidebar_panel, form_group, badge, loading_state, empty_state, data_table %}

  {% block title %}Vector Viewer{% endblock %}
  {% block head %}
  <link href="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css" rel="stylesheet">
  {% endblock %}

  {% block main_class %}{% endblock %}

  {% block content %}
  <div class="viewer-layout">
    <div class="viewer-sidebar">
      <h2>Vector Viewer</h2>

      <!-- Collection selector -->
      <div class="form-group">
        <label class="form-label" for="collection-select">Collection</label>
        <select id="collection-select" class="form-select" onchange="loadCollection(this.value)">
          <option value="">Select a collection...</option>
        </select>
      </div>

      <!-- Collection info (populated after selection) -->
      <div id="collection-info" class="hidden">
        <h3 id="collection-title"></h3>
        <p id="collection-description" class="text-muted"></p>

        <!-- Feature count -->
        <div id="feature-count" class="text-muted"></div>

        <!-- Feature properties table (first feature) -->
        <div id="feature-properties"></div>
      </div>

      <!-- Render mode toggle -->
      <div class="form-group" style="margin-top: var(--space-lg);">
        <label class="form-label">Render Mode</label>
        <div class="btn-group">
          <button class="btn btn-primary btn-sm" id="mode-mvt" onclick="setRenderMode('mvt')">Vector Tiles (MVT)</button>
          <button class="btn btn-secondary btn-sm" id="mode-geojson" onclick="setRenderMode('geojson')">GeoJSON</button>
        </div>
        <div class="form-hint">MVT is faster for large datasets. GeoJSON enables feature popups.</div>
      </div>

      <!-- Style controls -->
      <div class="form-group">
        <label class="form-label" for="fill-color">Fill Color</label>
        <input type="color" id="fill-color" value="#0071BC" onchange="updateStyle()">
      </div>
      <div class="form-group">
        <label class="form-label" for="fill-opacity">Opacity</label>
        <input type="range" id="fill-opacity" min="0" max="1" step="0.1" value="0.5" onchange="updateStyle()">
      </div>
    </div>

    <div id="map" class="map-full"></div>
  </div>
  {% endblock %}

  {% block scripts %}
  <script src="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js"></script>
  <script src="{{ url_for('static', path='js/viewer-vector.js') }}"></script>
  <script>
    document.addEventListener('DOMContentLoaded', () => initVectorViewer({{ tipg_enabled | tojson }}));
  </script>
  {% endblock %}

FILE 2 — viewer-vector.js:
  Functions:
  - initVectorViewer(tipgEnabled): Init map, populate collection dropdown from /vector/collections,
    read getQueryParam('collection') and auto-select if present
  - loadCollection(collectionId): Fetch collection metadata, display info, add layer
  - addMvtLayer(collectionId): Add vector tile source from /vector/collections/{id}/tiles/WebMercatorQuad/{z}/{x}/{y}
  - addGeoJsonLayer(collectionId): Fetch /vector/collections/{id}/items?limit=1000 as GeoJSON,
    add as GeoJSON source
  - setRenderMode(mode): Toggle between MVT and GeoJSON rendering
  - updateStyle(): Update fill color and opacity from controls
  - setupPopups(): Click handler for GeoJSON mode showing feature properties

  MVT source pattern:
    map.addSource('vector-tiles', {
      type: 'vector',
      tiles: ['/vector/collections/' + id + '/tiles/WebMercatorQuad/{z}/{x}/{y}'],
    });

FILE 3 — routers/viewer.py:
  The viewer.py from Run 4.1 should already exist. Add vector route:

  @router.get("/vector", include_in_schema=False)
  async def vector_viewer(request: Request):
      return render_template(request, "pages/viewer/vector.html", nav_active="/catalog")

  If viewer.py was fully produced in Run 4.1, this is just adding one route.
```

**Greenfield Tier 2 Input:**

```
DESIGN CONSTRAINTS:
1. MapLibre GL JS 4.x from CDN
2. Vector tile URL: /vector/collections/{id}/tiles/WebMercatorQuad/{z}/{x}/{y}
3. GeoJSON URL: /vector/collections/{id}/items?limit=1000
4. Collection list: GET /vector/collections → {collections: [{id, title, description, links}]}
5. nav_active="/catalog"
6. Query param: getQueryParam('collection') for auto-selection
7. Use fetchJSON, showNotification, escapeHtml from common.js
8. .viewer-layout CSS grid, .viewer-sidebar, .map-full
9. Feature popup on click (GeoJSON mode only) using MapLibre Popup API
```

**Post-Run Validation:**
- Verify /viewer/vector renders with sidebar + map
- Verify collection dropdown populates from /vector/collections
- Verify MVT tile layer renders
- Verify GeoJSON mode works with feature click popups
- Verify style controls (color, opacity) update layer
- Verify auto-selection from query param

---

#### RUN 4.3: H3 Viewer

**Purpose:** Build the H3 hexagonal choropleth viewer using deck.gl overlay on MapLibre.

**Scope:** ~1,300 lines across 3 files

**Depends on:** Phase 1 (macros, CSS), Phase 2 (common.js)

**Produces:** H3 viewer page

**Greenfield Tier 1 Input:**

```
SYSTEM: H3 Hexagonal Viewer for geotiler

Build the H3 hexagonal choropleth viewer for crop production and drought risk data.
Uses deck.gl 9.x with H3HexagonLayer overlaid on MapLibre GL JS.

IMPORTANT: An existing H3 explorer already exists at /h3 (geotiler/routers/h3_explorer.py).
This new viewer at /viewer/h3 is a REDESIGNED version using the new design system.
The existing /h3 route and router are NOT modified.

FILES TO PRODUCE:
1. geotiler/templates/pages/viewer/h3.html (~120 lines)
2. geotiler/static/js/viewer-h3.js (~600 lines)
3. geotiler/routers/viewer.py — EXTEND with h3 route

FILE 1 — pages/viewer/h3.html:
  {% extends "base.html" %}
  {% from "components/macros.html" import sidebar_panel, form_group, badge, loading_state %}

  {% block title %}H3 Explorer{% endblock %}
  {% block head %}
  <link href="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css" rel="stylesheet">
  {% endblock %}

  {% block main_class %}{% endblock %}

  {% block content %}
  <div class="viewer-layout">
    <div class="viewer-sidebar">
      <h2>H3 Crop & Drought Explorer</h2>
      <p class="text-muted">Hexagonal grid at H3 resolution 5.</p>

      <!-- Crop selector -->
      <div class="form-group">
        <label class="form-label" for="crop-select">Crop</label>
        <select id="crop-select" class="form-select" onchange="queryH3()">
          <option value="wheat">Wheat</option>
          <option value="rice">Rice</option>
          <option value="maize">Maize</option>
          <option value="soybean">Soybean</option>
          <option value="barley">Barley</option>
          <option value="sorghum">Sorghum</option>
          <option value="millet">Millet</option>
        </select>
      </div>

      <!-- Technology selector -->
      <div class="form-group">
        <label class="form-label" for="tech-select">Technology</label>
        <select id="tech-select" class="form-select" onchange="queryH3()">
          <option value="irrigated">Irrigated</option>
          <option value="rainfed">Rainfed</option>
        </select>
      </div>

      <!-- Scenario selector -->
      <div class="form-group">
        <label class="form-label" for="scenario-select">Drought Scenario</label>
        <select id="scenario-select" class="form-select" onchange="queryH3()">
          <option value="baseline">Baseline</option>
          <option value="drought_mild">Mild Drought</option>
          <option value="drought_severe">Severe Drought</option>
          <option value="drought_extreme">Extreme Drought</option>
        </select>
      </div>

      <!-- Color palette -->
      <div class="form-group">
        <label class="form-label" for="palette-select">Color Palette</label>
        <select id="palette-select" class="form-select" onchange="updatePalette()">
          <option value="emergency_red">Emergency Red</option>
          <option value="viridis">Viridis</option>
          <option value="plasma">Plasma</option>
          <option value="ylgnbu">Yellow-Green-Blue</option>
          <option value="rdylgn">Red-Yellow-Green</option>
          <option value="spectral">Spectral</option>
          <option value="hot">Hot</option>
        </select>
      </div>

      <!-- Stats panel -->
      <div id="h3-stats" class="hidden" style="margin-top: var(--space-lg);">
        <h3>Query Results</h3>
        <div id="h3-count" class="text-muted"></div>
        <div id="h3-legend"></div>
      </div>
    </div>

    <div id="map" class="map-full"></div>
  </div>
  {% endblock %}

  {% block scripts %}
  <script src="https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js"></script>
  <script src="https://unpkg.com/deck.gl@9/dist.min.js"></script>
  <script src="https://unpkg.com/h3-js@4"></script>
  <script src="{{ url_for('static', path='js/viewer-h3.js') }}"></script>
  <script>
    document.addEventListener('DOMContentLoaded', () => initH3Viewer());
  </script>
  {% endblock %}

FILE 2 — viewer-h3.js:
  Functions:
  - initH3Viewer(): Init MapLibre map (dark basemap for choropleth contrast),
    create deck.gl overlay, auto-query on load
  - queryH3(): Read crop/tech/scenario from selectors, call fetchJSON('/h3/query?crop=...&tech=...&scenario=...'),
    render hexagons
  - renderHexagons(data): Create deck.gl H3HexagonLayer from data array
    [{h3_index, value}, ...], apply color scale
  - updatePalette(): Switch color palette, re-render
  - buildColorScale(palette, values): Map values to RGB colors using selected palette
  - renderLegend(palette, min, max): Draw gradient legend in sidebar

  Palette definitions (frozen sets matching server-side VALID_CROPS, VALID_TECHS, VALID_SCENARIOS):
  PALETTES = {
    emergency_red: [[255,255,204], [255,237,160], [254,178,76], [253,141,60], [240,59,32], [189,0,38]],
    viridis: [[68,1,84], [72,40,120], [62,74,137], [49,104,142], [38,130,142], [53,183,121], [253,231,37]],
    ...
  }

  deck.gl overlay pattern:
    const deckOverlay = new deck.MapboxOverlay({
      layers: [
        new deck.H3HexagonLayer({
          id: 'h3-layer',
          data: hexData,
          getHexagon: d => d.h3_index,
          getFillColor: d => colorScale(d.value),
          extruded: false,
          pickable: true,
        })
      ]
    });
    map.addControl(deckOverlay);

FILE 3 — viewer.py addition:
  @router.get("/h3", include_in_schema=False)
  async def h3_viewer(request: Request):
      return render_template(request, "pages/viewer/h3.html", nav_active="/catalog")
```

**Greenfield Tier 2 Input:**

```
DESIGN CONSTRAINTS:
1. deck.gl 9.x from CDN (unpkg.com/deck.gl@9/dist.min.js)
2. h3-js 4.x from CDN (unpkg.com/h3-js@4)
3. MapLibre 4.x from CDN
4. H3 query API: GET /h3/query?crop={crop}&tech={tech}&scenario={scenario}
   Returns: {data: [{h3_index, value}, ...], count: N, query_ms: N}
5. Valid crops: wheat, rice, maize, soybean, barley, sorghum, millet
6. Valid techs: irrigated, rainfed
7. Valid scenarios: baseline, drought_mild, drought_severe, drought_extreme
8. nav_active="/catalog"
9. Dark basemap for choropleth: use "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
10. H3 resolution 5 (server-side — viewer does not need to know)
11. Existing /h3 route (h3_explorer.py) is NOT modified or removed
12. Use fetchJSON and showNotification from common.js
```

**Special Instructions:** The H3 viewer diverges from the standard light-theme design system (R's SE-3). The dark basemap is intentional for choropleth readability. The sidebar still uses standard light-theme classes. Make sure the sidebar and map coexist visually -- the sidebar uses `.viewer-sidebar` (white background) while the map uses the dark CARTO basemap. The deck.gl overlay API changed between 8.x and 9.x -- use the `MapboxOverlay` pattern (compatible with MapLibre).

**Post-Run Validation:**
- Verify /viewer/h3 renders with sidebar + dark-basemap map
- Verify crop/tech/scenario selectors trigger API query
- Verify H3 hexagons render on map via deck.gl overlay
- Verify palette switching updates hexagon colors
- Verify legend renders in sidebar
- Verify existing /h3 route still works unchanged

#### PHASE EXIT CRITERIA:
- /viewer/raster, /viewer/zarr, /viewer/vector, /viewer/h3 all render correctly
- Each viewer reads query parameters and auto-loads data when params present
- Tile layers render on map for all viewer types
- Sidebar controls (colormap, bands, style, palette) update the visualization
- Feature popups work in vector GeoJSON mode
- All viewers use nav_active="/catalog"
- No JavaScript errors on any viewer page
- Catalog collection cards link to correct viewer URLs and viewers load from those links

---

## CROSS-CUTTING STRATEGY

### CC-1: Error Handling

**Strategy:** Convention in Tier 2 (independent per subsystem).

**Specification:**
- API errors: Use `fetchJSON()` which returns `{ok: false, error: string}`. Call `showNotification(error, 'error')` to display toast.
- Form/input validation: Use inline callout (`.callout-warning`) below the input.
- Empty states: Use `empty_state()` macro for "no data" scenarios.
- Loading states: Use `loading_state()` macro while data is being fetched. Replace with content or error when done.

Included in every Greenfield run's Tier 2.

### CC-2: Feature Flags

**Strategy:** Convention in Tier 2 (enforced in Phase 1).

**Specification:** Feature flags are ALWAYS checked via Jinja2 template conditionals (`{% if stac_api_enabled %}`, `{% if tipg_enabled %}`). JavaScript NEVER re-reads flags from the server. If JS needs flag state, it is passed via a `<script>` block in the template: `loadCatalog({{ stac_api_enabled | tojson }})`.

Enforced in S1 (base template) and documented in every Tier 2.

### CC-3: Loading/Empty State Patterns

**Strategy:** Shared macros in Phase 1 (IC-2).

**Specification:** `loading_state(message)` and `empty_state(message, icon)` macros in `macros.html`. All downstream subsystems import and use these macros. JS replaces the loading state with content when data arrives.

### CC-4: nav_active Pattern

**Strategy:** Convention in Tier 2 (enforced per router).

**Specification:** Every router passes `nav_active="/route_prefix"` to `render_template()`. The navbar template uses `{% if nav_active == '/prefix' %}` for highlighting. Values: `/` (home), `/catalog` (catalog + viewers), `/reference`, `/system`.

Explicitly called out in every Greenfield Tier 1.

### CC-5: CDN Version Pinning

**Strategy:** Convention in Tier 2.

**Specification:** All CDN libraries use major-version pinning:
- MapLibre: `unpkg.com/maplibre-gl@4`
- deck.gl: `unpkg.com/deck.gl@9`
- h3-js: `unpkg.com/h3-js@4`
- HTMX: `unpkg.com/htmx.org@1.9.10`

Loaded per-page in `{% block head %}` and `{% block scripts %}`, not globally.

---

## RISK REGISTER

### RR-1: S1 Macro Signature Drift

**Description:** Macro signatures defined in Phase 1 may not match what downstream subsystems actually need. A Phase 3 or 4 run may discover it needs a parameter the macro does not support.

**Phase affected:** Phase 3, Phase 4

**Likelihood:** MEDIUM

**Impact:** MEDIUM (requires editing macros.html and re-testing earlier pages)

**Mitigation:** Macros designed with optional kwargs and `caller()` block pattern where possible. New macros can be added (additive change) without breaking existing callers.

**Trigger:** A Greenfield run's Adversarial Review identifies that a macro call requires a parameter not in the signature.

---

### RR-2: common.js fetchJSON API Mismatch

**Description:** Downstream viewers may need fetchJSON to support additional options (e.g., custom headers, blob responses) not in the Phase 2 implementation.

**Phase affected:** Phase 4

**Likelihood:** LOW (the API surface is well-understood)

**Impact:** LOW (fetchJSON can be extended with additional options without breaking existing callers)

**Mitigation:** fetchJSON accepts an `options` object that can be extended. Downstream callers that need raw fetch can fall back to native `fetch()`.

**Trigger:** A viewer JS file needs to fetch binary data (tiles) through fetchJSON.

---

### RR-3: MapLibre Source/Layer ID Collision

**Description:** Multiple viewers use MapLibre with source IDs like `raster-tiles`. If viewer JS is accidentally loaded on the wrong page, IDs could collide.

**Phase affected:** Phase 4

**Likelihood:** LOW (each viewer has its own page and JS file)

**Impact:** LOW (JS error on wrong page, no data corruption)

**Mitigation:** Each viewer uses a unique source ID prefix: `cog-tiles`, `zarr-tiles`, `vector-tiles`, `h3-hexagons`.

**Trigger:** Browser dev tools show "Source already exists" error.

---

### RR-4: Existing Pages Break After Phase 1 CSS Changes

**Description:** Phase 1 replaces styles.css. Existing pages (admin dashboard, guide, COG landing, H3 explorer, STAC explorer) use CSS classes that may be renamed or removed.

**Phase affected:** Phase 1 (immediate)

**Likelihood:** MEDIUM

**Impact:** HIGH (multiple existing pages break visually)

**Mitigation:** Phase 1 Tier 1 explicitly requires ALL existing CSS classes to be retained, either directly or as aliases. Post-run validation includes backward compatibility check. The Adversarial Review after Phase 1 must specifically verify existing page rendering.

**Trigger:** Any existing page (admin, guide, H3) renders with broken layout after Phase 1 deployment.

---

### RR-5: Catalog Page Performance with Large Collection Counts

**Description:** The unified catalog fetches ALL collections from both STAC and TiPG APIs client-side. If there are hundreds of collections, the page may be slow.

**Phase affected:** Phase 3

**Likelihood:** LOW (current deployment has ~20 collections)

**Impact:** MEDIUM (slow page load, poor UX)

**Mitigation:** Client-side filtering is fine for <100 collections. If collection count grows, add server-side pagination as a future enhancement. The catalog.js is structured to support this refactor.

**Trigger:** Catalog page load exceeds 3 seconds.

---

### RR-6: HTMX Version Conflict on System Page

**Description:** System page loads HTMX 1.9.10 from CDN. The existing admin dashboard also uses HTMX (loaded in its own template). If both pages load different versions, cached scripts could conflict.

**Phase affected:** Phase 3

**Likelihood:** LOW

**Impact:** LOW (both pages use the same version)

**Mitigation:** Pin exact same HTMX version (1.9.10) in both templates.

**Trigger:** HTMX requests fail on system page with JavaScript error.

---

### RR-7: Route Conflict Between New Routes and Existing Routes

**Description:** The new route `/viewer/vector` could conflict with TiPG's `/vector/*` prefix if TiPG's router catches the path. Similarly, `/system` could conflict with future routes.

**Phase affected:** Phase 3, Phase 4

**Likelihood:** LOW (FastAPI matches routes in registration order; custom routes registered before TiPG)

**Impact:** HIGH (wrong handler serves the request)

**Mitigation:** Register new routers BEFORE TiPG router in app.py. The `/viewer/*` prefix is distinct from `/vector/*`. Verify in post-run testing that routes resolve correctly.

**Trigger:** Navigating to /viewer/vector returns a TiPG 404 instead of the viewer page.

---

## REWORK BUDGET

### Phase 1 Rework (CSS/Template Foundation)

**Trigger:** Downstream Phase 3 or Phase 4 run discovers that a CSS class, macro signature, or template block does not support a needed pattern.

**Estimated rework scope:** Small -- typically adding a new CSS class or a new macro parameter. ~50-100 lines changed in styles.css or macros.html.

**Downstream impact:** All downstream phases consume Phase 1 artifacts, so a Phase 1 rework must be validated against ALL completed pages. However, since the design is additive-only (no removals), the risk of breaking existing pages is low.

**Likelihood:** MEDIUM (most likely rework point in the plan)

### Phase 2 Rework (common.js)

**Trigger:** A viewer in Phase 4 needs a utility function with a different signature than what was built.

**Estimated rework scope:** Small -- adding a new function or extending an options parameter. ~20-50 lines.

**Downstream impact:** Only affects the specific viewer that triggered the rework. Existing callers unaffected (additive change).

**Likelihood:** LOW

### Phase 3 Rework (Catalog URL Contract)

**Trigger:** A viewer in Phase 4 discovers that the URL contract (SD-1) needs additional parameters.

**Estimated rework scope:** Medium -- updating catalog.js links, buildViewerUrl function, and the viewer's getQueryParam calls. ~100-200 lines across 3-4 files.

**Downstream impact:** Catalog pages must update their link generation. Other viewers unaffected.

**Likelihood:** LOW (the URL contract is front-loaded and well-understood)

### Phase 4 Rework (Viewer Integration)

**Trigger:** Viewers work individually but the end-to-end flow (catalog -> viewer -> map render) fails.

**Estimated rework scope:** Medium -- debugging API URL construction, query parameter encoding, or tile layer configuration. ~100-300 lines.

**Downstream impact:** None (Phase 4 is terminal).

**Likelihood:** MEDIUM (highest integration risk per D's assessment)

---

## SUMMARY: BUILD SEQUENCE

```
PHASE 1 (Foundation)
  RUN 1.1: Design System & Base Shell .............. ~1,500 lines, 6 files

PHASE 2 (Shared JS & Entry Point)
  RUN 2.1: Homepage & Shared JS Utilities .......... ~800 lines, 4 files

PHASE 3 (Catalog & Structural Pages) — Runs 3.1→3.2 sequential, 3.3 parallel with 3.1/3.2
  RUN 3.1: Unified Catalog & Router ................ ~1,200 lines, 4 files
  RUN 3.2: STAC & Vector Catalog Sub-Pages ......... ~1,200 lines, 3 files  [depends on 3.1]
  RUN 3.3: Reference & System Pages ................ ~1,500 lines, 6 files  [parallel with 3.1]

PHASE 4 (Viewers) — All parallel
  RUN 4.1: Raster & Zarr Viewers ................... ~2,500 lines, 6 files
  RUN 4.2: Vector Viewer ........................... ~1,200 lines, 3 files
  RUN 4.3: H3 Viewer ............................... ~1,300 lines, 3 files

TOTAL: 8 Greenfield runs, ~11,200 lines, ~35 files
```

Phase 3 note: Run 3.3 (Reference & System) can run in parallel with Run 3.1 because it depends only on Phase 1 and Phase 2 artifacts, not on the catalog router. Run 3.2 must wait for Run 3.1 (it extends catalog.js and uses the catalog router's placeholder routes).

Phase 4 note: All three viewer runs are independent and can execute in parallel. Each depends only on Phase 1 + Phase 2 artifacts and the URL contract from SD-1. Run 4.2 adds a route to `viewer.py` created by Run 4.1, but this is a file-level dependency that can be resolved by the developer merging Run 4.1's output first. If strictly parallel execution is needed, Run 4.2 can create its own `viewer_vector.py` router file instead.