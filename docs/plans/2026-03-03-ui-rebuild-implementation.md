# UI Rebuild Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the geotiler UI from scratch as 6 Greenfield pipeline runs across 5 phases, producing ~10,800 lines of production-quality code.

**Architecture:** Server-rendered Jinja2 templates + vanilla JS + MapLibre GL JS (CDN). Each phase is a self-contained Greenfield run that builds on prior phases. Phases 4a and 4b run in parallel.

**Tech Stack:** Python/FastAPI, Jinja2, vanilla JavaScript, MapLibre GL JS 4.x, deck.gl 9.x, HTMX 1.9.x, CSS custom properties.

**Design Doc:** `docs/plans/2026-03-03-ui-rebuild-design.md`

---

## Tier 2 Design Constraints (applies to ALL tasks)

Every file in this plan must follow these settled patterns:

1. **Router pattern**: `APIRouter(tags=[...])` with `include_in_schema=False` for HTML endpoints. Use `render_template(request, "path/to/template.html", nav_active="/route", **kwargs)` from `geotiler.templates_utils`.
2. **App registration**: Add `from geotiler.routers import module` at top of `app.py`, then `app.include_router(module.router, ...)` in the Routers section.
3. **Template context**: `get_template_context(request)` provides `request`, `version`, `stac_api_enabled`, `tipg_enabled`, `sample_zarr_urls`. Pass extra vars via kwargs.
4. **Static files**: All CSS in `geotiler/static/css/`, all JS in `geotiler/static/js/`. Referenced via `{{ url_for('static', path='css/styles.css') }}`.
5. **CDN versions**: MapLibre GL JS `^4.0.0`, deck.gl `^9.0.0`, h3-js `^4.0.0`, HTMX `1.9.10`, TopoJSON client `3`.
6. **No build step**: No npm, no webpack, no bundler. Plain files served by Starlette StaticFiles.

---

## Phase 1: Design System & Base Shell

**Greenfield run 1 of 6. No dependencies. Foundation for all subsequent phases.**

### Task 1.1: CSS Design System

**Files:**
- Create: `geotiler/static/css/styles.css` (replaces existing)

**Step 1: Read existing design tokens**

Read `geotiler/static/css/styles.css` lines 1-55 to capture the current token values (colors, spacing, typography, radii, shadows). These values are good — we keep them.

**Step 2: Write the new CSS file**

The new CSS is organized into these sections, in order:

```css
/* 1. Design Tokens (CSS Custom Properties) */
:root {
    /* Brand Colors — keep existing values */
    --ds-blue-primary: #0071BC;
    --ds-blue-dark: #245AAD;
    --ds-navy: #053657;
    --ds-cyan: #00A3DA;
    --ds-gold: #FFC14D;

    /* Neutral Colors */
    --ds-gray: #626F86;
    --ds-gray-light: #e9ecef;
    --ds-bg: #f8f9fa;
    --ds-white: #ffffff;

    /* Status Colors */
    --ds-success: #059669;
    --ds-warning: #d97706;
    --ds-error: #dc2626;

    /* Code Colors */
    --ds-code-bg: #1e1e1e;
    --ds-code-text: #d4d4d4;

    /* Spacing Scale */
    --spacing-xs: 4px;
    --spacing-sm: 8px;
    --spacing-md: 16px;
    --spacing-lg: 24px;
    --spacing-xl: 40px;

    /* Typography */
    --font-sans: "Open Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    --font-mono: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;

    /* Border Radius */
    --radius-sm: 4px;
    --radius-md: 6px;
    --radius-lg: 8px;

    /* Shadows */
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
}

/* 2. Reset & Base Typography */
/* box-sizing, font-family, line-height, heading scales, link styles, code/pre */

/* 3. Layout Components */
/* .container (max-width: 1200px, centered padding)
   .navbar (flex, sticky top, brand + links, active state)
   .footer (border-top, padding, muted text)
   .sidebar-layout (CSS grid: sidebar 280px + main 1fr, collapses on mobile)
   .card-grid (CSS grid: auto-fill minmax(300px, 1fr), gap) */

/* 4. Component Classes */
/* .card (border, radius, shadow, hover lift)
   .card-header, .card-body, .card-footer
   .badge (inline, small, rounded — variants: default, raster, vector, zarr, success, warning, error)
   .btn (base + variants: primary, secondary, outline, small)
   .form-group (label + input/select stack)
   .data-table (striped, responsive overflow-x)
   .status-indicator (dot + text — healthy/warning/error)
   .empty-state (centered, muted, icon + message)
   .callout (left-border accent — variants: info, warning, error)
   .notification-toast (fixed bottom-right, slide-in animation)
   .code-block (pre with bg, border-radius, overflow, optional copy button position) */

/* 5. Map Components */
/* .map-container (relative, full-height option, border)
   .map-sidebar (absolute or grid column, scrollable, panel groups)
   .map-controls (form groups within sidebar)
   .map-popup (maplibre popup overrides) */

/* 6. Page-Specific Overrides */
/* .hero-section (homepage hero)
   .catalog-filters (search bar + type toggles)
   .viewer-layout (sidebar + map grid)
   .system-dashboard (status card grid)
   .h3-explorer (dark theme full-viewport — self-contained) */

/* 7. Responsive Breakpoints */
/* @media (max-width: 768px): sidebar-layout collapses, card-grid single col, navbar hamburger
   @media (max-width: 480px): reduced padding, smaller text */

/* 8. Utility Classes */
/* .text-muted, .text-success, .text-error, .text-mono
   .mt-sm, .mt-md, .mt-lg, .mb-sm, .mb-md, .mb-lg
   .hidden, .sr-only */
```

Write the full CSS implementing all sections. Target ~800-1000 lines. Each component class must be self-contained (no implicit dependencies between sections).

**Step 3: Verify the CSS file is valid**

Open in browser or use a CSS linter to check for syntax errors.

**Step 4: Commit**

```bash
git add geotiler/static/css/styles.css
git commit -m "feat(ui): rebuild CSS design system with tokens and components"
```

---

### Task 1.2: Jinja2 Macro Library

**Files:**
- Create: `geotiler/templates/components/macros.html`

**Step 1: Write the macro library**

Every macro renders a self-contained HTML snippet using CSS classes from Task 1.1.

```jinja2
{# Component Macro Library
   Import: {% from "components/macros.html" import card, badge, ... %}
#}

{# Card — generic container with optional link wrapper
   Usage: {{ card("Title", subtitle="Sub", body="<p>Content</p>", href="/link", footer="Footer text") }}
#}
{% macro card(title, subtitle="", body="", footer="", href="", css_class="") %}
<div class="card {{ css_class }}">
    {% if href %}<a href="{{ href }}" class="card-link">{% endif %}
    <div class="card-header">
        <h3 class="card-title">{{ title }}</h3>
        {% if subtitle %}<p class="card-subtitle">{{ subtitle }}</p>{% endif %}
    </div>
    {% if body %}
    <div class="card-body">{{ body | safe }}</div>
    {% endif %}
    {% if footer %}
    <div class="card-footer">{{ footer | safe }}</div>
    {% endif %}
    {% if href %}</a>{% endif %}
</div>
{% endmacro %}

{# Badge — inline label with variant
   Variants: default, raster, vector, zarr, success, warning, error
   Usage: {{ badge("COG", "raster") }}
#}
{% macro badge(text, variant="default") %}
<span class="badge badge-{{ variant }}">{{ text }}</span>
{% endmacro %}

{# Map Container — div ready for MapLibre initialization
   Usage: {{ map_container("my-map", height="600px") }}
#}
{% macro map_container(id, height="100%") %}
<div id="{{ id }}" class="map-container" style="height: {{ height }};"></div>
{% endmacro %}

{# Sidebar Panel — collapsible panel within a sidebar
   Usage: {% call sidebar_panel("Metadata", collapsible=true) %}...content...{% endcall %}
#}
{% macro sidebar_panel(title, collapsible=false) %}
<div class="sidebar-panel{% if collapsible %} collapsible{% endif %}">
    <div class="sidebar-panel-header"{% if collapsible %} onclick="this.parentElement.classList.toggle('collapsed')"{% endif %}>
        <h4>{{ title }}</h4>
        {% if collapsible %}<span class="collapse-icon">&#9660;</span>{% endif %}
    </div>
    <div class="sidebar-panel-body">
        {{ caller() }}
    </div>
</div>
{% endmacro %}

{# Form Group — label + input wrapper
   Usage: {{ form_group("Band", '<select id="band-select"><option>1</option></select>') }}
#}
{% macro form_group(label, input_html, help_text="") %}
<div class="form-group">
    <label>{{ label }}</label>
    {{ input_html | safe }}
    {% if help_text %}<small class="form-help">{{ help_text }}</small>{% endif %}
</div>
{% endmacro %}

{# Data Table — responsive table from headers and rows
   Usage: {{ data_table(["Name", "Value"], [["CRS", "EPSG:4326"], ["Bands", "3"]]) }}
#}
{% macro data_table(headers, rows, css_class="") %}
<div class="table-responsive">
    <table class="data-table {{ css_class }}">
        <thead><tr>
            {% for h in headers %}<th>{{ h }}</th>{% endfor %}
        </tr></thead>
        <tbody>
            {% for row in rows %}
            <tr>{% for cell in row %}<td>{{ cell }}</td>{% endfor %}</tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endmacro %}

{# Status Indicator — colored dot + text
   Status: healthy, warning, error, unknown
   Usage: {{ status_indicator("healthy", "Database connected") }}
#}
{% macro status_indicator(status, text) %}
<span class="status-indicator status-{{ status }}">
    <span class="status-dot"></span>
    {{ text }}
</span>
{% endmacro %}

{# Empty State — centered message for empty lists
   Usage: {{ empty_state("No collections found", "Try adjusting your filters") }}
#}
{% macro empty_state(message, hint="") %}
<div class="empty-state">
    <p class="empty-state-message">{{ message }}</p>
    {% if hint %}<p class="empty-state-hint">{{ hint }}</p>{% endif %}
</div>
{% endmacro %}
```

**Step 2: Commit**

```bash
git add geotiler/templates/components/macros.html
git commit -m "feat(ui): add Jinja2 macro library for reusable components"
```

---

### Task 1.3: Base Template & Navigation

**Files:**
- Create: `geotiler/templates/base.html` (replaces existing)
- Create: `geotiler/templates/components/navbar.html` (replaces existing)
- Create: `geotiler/templates/components/footer.html` (replaces existing)

**Step 1: Write base.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Geotiler{% endblock %} — geotiler v{{ version }}</title>
    <link rel="stylesheet" href="{{ url_for('static', path='css/styles.css') }}">
    {% block head %}{% endblock %}
</head>
<body>
    {% include "components/navbar.html" %}

    <main class="{% block main_class %}container{% endblock %}">
        {% block content %}{% endblock %}
    </main>

    {% include "components/footer.html" %}

    {% block scripts %}{% endblock %}
</body>
</html>
```

**Step 2: Write navbar.html**

New navbar links: Home, Catalog, Reference, System. Conditional links for STAC and TiPG features. `nav_active` variable highlights current page.

```html
{# Navigation bar — pass nav_active to highlight current page #}
<nav class="navbar">
    <a href="/" class="navbar-brand">
        geotiler <span class="version">v{{ version }}</span>
    </a>
    <button class="navbar-toggle" aria-label="Toggle navigation" onclick="this.parentElement.classList.toggle('open')">
        &#9776;
    </button>
    <div class="navbar-links">
        <a href="/" class="{{ 'active' if nav_active == '/' else '' }}">Home</a>
        <a href="/catalog" class="{{ 'active' if nav_active and nav_active.startswith('/catalog') else '' }}">Catalog</a>
        {% if stac_api_enabled %}
        <a href="/catalog/stac" class="{{ 'active' if nav_active == '/catalog/stac' else '' }}">STAC</a>
        {% endif %}
        {% if tipg_enabled %}
        <a href="/catalog/vector" class="{{ 'active' if nav_active == '/catalog/vector' else '' }}">Vector</a>
        {% endif %}
        <a href="/reference" class="{{ 'active' if nav_active and nav_active.startswith('/reference') else '' }}">Reference</a>
        <a href="/system" class="{{ 'active' if nav_active == '/system' else '' }}">System</a>
        <a href="/docs" class="{{ 'active' if nav_active == '/docs' else '' }}">API</a>
    </div>
</nav>
```

**Step 3: Write footer.html**

```html
<footer class="footer">
    <div class="container">
        <span>geotiler v{{ version }}</span>
        <span class="footer-separator">·</span>
        <a href="/docs">API Docs</a>
        <span class="footer-separator">·</span>
        <a href="/reference">Reference</a>
    </div>
</footer>
```

**Step 4: Commit**

```bash
git add geotiler/templates/base.html geotiler/templates/components/navbar.html geotiler/templates/components/footer.html
git commit -m "feat(ui): rebuild base template, navbar, and footer"
```

---

### Task 1.4: Phase 1 Validation

**Step 1: Create a smoke-test template**

Create a temporary `geotiler/templates/pages/_test_macros.html` that imports and exercises every macro:

```html
{% extends "base.html" %}
{% from "components/macros.html" import card, badge, map_container, form_group, data_table, status_indicator, empty_state %}

{% block title %}Macro Test{% endblock %}
{% block content %}
<h1>Component Test Page</h1>

<div class="card-grid">
    {{ card("Test Card", subtitle="Subtitle", body="<p>Body content</p>", footer="Footer") }}
    {{ card("Linked Card", href="/catalog", body="<p>Click me</p>") }}
</div>

<p>Badges: {{ badge("Raster", "raster") }} {{ badge("Vector", "vector") }} {{ badge("Zarr", "zarr") }}</p>

{{ status_indicator("healthy", "All systems operational") }}
{{ status_indicator("error", "Database unreachable") }}

{{ data_table(["Property", "Value"], [["CRS", "EPSG:4326"], ["Bands", "3"], ["Resolution", "10m"]]) }}

{{ empty_state("No collections found", "Try broadening your search") }}

{{ map_container("test-map", height="300px") }}

{% call sidebar_panel("Test Panel", collapsible=true) %}
{{ form_group("Band", '<select><option>1</option><option>2</option></select>') }}
{% endcall %}
{% endblock %}
```

**Step 2: Add a temporary test route**

Add to any existing router (or create a quick route in app.py) that renders this template. Verify in browser:
- All macros render valid HTML
- CSS classes produce correct styling
- Responsive breakpoints work (resize browser to 768px and 480px)
- Navbar links are correct and active state works
- Footer renders with version

**Step 3: Delete test template and route after validation**

**Step 4: Commit phase 1 complete**

```bash
git commit -m "feat(ui): complete Phase 1 — design system and base shell"
```

---

## Phase 2: Homepage & Shared JS Utilities

**Greenfield run 2 of 6. Depends on Phase 1.**

### Task 2.1: JavaScript Utility Module

**Files:**
- Create: `geotiler/static/js/utils.js`

**Step 1: Write utils.js**

```javascript
/**
 * Shared utilities for geotiler UI.
 * Loaded on every page via base.html.
 */

/**
 * Fetch JSON from an API endpoint with error handling and timeout.
 * @param {string} url - API URL (same-origin, no CORS needed)
 * @param {Object} options - fetch options (method, body, headers)
 * @param {number} timeoutMs - timeout in milliseconds (default 30000)
 * @returns {Promise<Object>} parsed JSON response
 * @throws {Error} on network error, timeout, or non-2xx status
 */
async function fetchJSON(url, options = {}, timeoutMs = 30000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal,
            headers: {
                'Accept': 'application/json',
                ...(options.headers || {}),
            },
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
        }
        return await response.json();
    } catch (err) {
        if (err.name === 'AbortError') {
            throw new Error(`Request timed out after ${timeoutMs}ms: ${url}`);
        }
        throw err;
    } finally {
        clearTimeout(timeoutId);
    }
}

/** Get a query parameter value from the current URL. */
function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}

/** Update a query parameter in the URL without reloading. */
function setQueryParam(name, value) {
    const url = new URL(window.location);
    if (value === null || value === undefined || value === '') {
        url.searchParams.delete(name);
    } else {
        url.searchParams.set(name, value);
    }
    window.history.replaceState({}, '', url);
}

/** Copy text to clipboard with fallback for older browsers. */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showNotification('Copied to clipboard', 'success');
    } catch {
        // Fallback: textarea trick
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showNotification('Copied to clipboard', 'success');
    }
}

/** Debounce a function call. */
function debounce(fn, ms) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), ms);
    };
}

/** Throttle a function call. */
function throttle(fn, ms) {
    let last = 0;
    return function (...args) {
        const now = Date.now();
        if (now - last >= ms) {
            last = now;
            fn.apply(this, args);
        }
    };
}

/** Format bytes to human-readable string. */
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

/** Format ISO date to locale string. */
function formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
    });
}

/** Format lat/lng to fixed decimal string. */
function formatLatLng(lat, lng) {
    return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
}

/**
 * Show a toast notification.
 * @param {string} message - notification text
 * @param {'success'|'error'|'info'} type - notification type
 * @param {number} durationMs - auto-dismiss after (default 3000)
 */
function showNotification(message, type = 'info', durationMs = 3000) {
    const toast = document.createElement('div');
    toast.className = `notification-toast notification-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Trigger slide-in animation
    requestAnimationFrame(() => toast.classList.add('visible'));

    setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 300);
    }, durationMs);
}
```

**Step 2: Add utils.js to base.html**

In `base.html`, add before the `{% block scripts %}` line:

```html
    <script src="{{ url_for('static', path='js/utils.js') }}"></script>
    {% block scripts %}{% endblock %}
```

**Step 3: Commit**

```bash
git add geotiler/static/js/utils.js geotiler/templates/base.html
git commit -m "feat(ui): add shared JS utility module"
```

---

### Task 2.2: Homepage Router & Template

**Files:**
- Create: `geotiler/routers/home.py`
- Create: `geotiler/templates/pages/home.html`
- Modify: `geotiler/app.py` (add import + include_router)

**Step 1: Write the router**

```python
"""
Homepage router.

Serves the Geospatial Data Catalog splash page at /.
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(tags=["Homepage"])


@router.get("/", include_in_schema=False)
async def homepage(request: Request):
    """Geospatial Data Catalog homepage."""
    return render_template(request, "pages/home.html", nav_active="/")
```

**Step 2: Write the template**

```html
{% extends "base.html" %}
{% from "components/macros.html" import card, badge %}

{% block title %}Geospatial Data Catalog{% endblock %}

{% block content %}
<section class="hero-section">
    <h1>Geospatial Data Catalog</h1>
    <p>Browse, search, and visualize raster imagery, vector features, and multidimensional datasets.</p>
</section>

<div class="card-grid">
    {{ card(
        "Catalog",
        subtitle="Browse Collections",
        body="<p>Explore STAC raster collections and OGC Feature vector collections in a unified catalog.</p>",
        href="/catalog",
        css_class="card-featured"
    ) }}

    {% if stac_api_enabled %}
    {{ card(
        "STAC Collections",
        subtitle="Raster & Multidimensional",
        body="<p>Search STAC collections and items. View COGs, Zarr, and NetCDF datasets.</p>" ~ badge("STAC", "raster"),
        href="/catalog/stac"
    ) }}
    {% endif %}

    {% if tipg_enabled %}
    {{ card(
        "Vector Collections",
        subtitle="OGC Features",
        body="<p>Browse PostGIS tables exposed as OGC Feature collections with vector tiles.</p>" ~ badge("OGC", "vector"),
        href="/catalog/vector"
    ) }}
    {% endif %}

    {{ card(
        "Reference",
        subtitle="API Documentation",
        body="<p>Guides, endpoint reference, and code examples for the geotiler API.</p>",
        href="/reference"
    ) }}

    {{ card(
        "System",
        subtitle="Admin Dashboard",
        body="<p>Health status, service dependencies, and configuration for this instance.</p>",
        href="/system"
    ) }}
</div>
{% endblock %}
```

**Step 3: Register the router in app.py**

In `geotiler/app.py`:

1. Add to the import block (line ~32): `from geotiler.routers import home`
2. In the Routers section, add BEFORE the admin router (which currently handles `/`):

```python
    # Homepage (new UI)
    app.include_router(home.router, tags=["Homepage"])
```

3. The admin router currently serves `GET /` — either remove that route from `admin.py` or comment it out, since the new homepage now owns `/`. The admin dashboard moves to `/system` in Phase 5.

**Important**: For now, the admin console HTML endpoint at `GET /` in `admin.py` should be changed to `GET /system` or simply left in place but registered after the home router (FastAPI uses first-match). The simplest approach: register `home.router` before `admin.router` so `/` resolves to the homepage.

**Step 4: Verify**

Run the app: `uvicorn geotiler.main:app --reload --port 8000`
- `GET /` → Homepage renders with cards
- Cards conditional on `stac_api_enabled` and `tipg_enabled` show/hide correctly
- Navbar highlights "Home"
- All card links work (404 expected for not-yet-built pages, but href is correct)

**Step 5: Commit**

```bash
git add geotiler/routers/home.py geotiler/templates/pages/home.html geotiler/app.py
git commit -m "feat(ui): add homepage with catalog entry points"
```

---

## Phase 3: Catalog Pages

**Greenfield run 3 of 6. Depends on Phases 1 and 2.**

### Task 3.1: Catalog Router

**Files:**
- Create: `geotiler/routers/catalog.py`
- Modify: `geotiler/app.py` (register router)

**Step 1: Write the router**

```python
"""
Catalog pages — unified, STAC, and OGC Features collection browsers.

Routes:
    GET /catalog       — Unified catalog (merges STAC + OGC)
    GET /catalog/stac  — STAC-specific collection/item browser
    GET /catalog/vector — OGC Features collection browser
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.get("/", include_in_schema=False)
async def unified_catalog(request: Request):
    """Unified catalog — browse all collections."""
    return render_template(request, "pages/catalog/unified.html", nav_active="/catalog")


@router.get("/stac", include_in_schema=False)
async def stac_catalog(request: Request):
    """STAC collection and item browser."""
    return render_template(request, "pages/catalog/stac.html", nav_active="/catalog/stac")


@router.get("/vector", include_in_schema=False)
async def vector_catalog(request: Request):
    """OGC Features collection browser."""
    return render_template(request, "pages/catalog/vector.html", nav_active="/catalog/vector")
```

**Step 2: Register in app.py**

Add import and `app.include_router(catalog.router, tags=["Catalog"])` in the Routers section.

**Step 3: Commit**

```bash
git add geotiler/routers/catalog.py geotiler/app.py
git commit -m "feat(ui): add catalog router with unified, STAC, and vector routes"
```

---

### Task 3.2: Catalog JavaScript Module

**Files:**
- Create: `geotiler/static/js/catalog.js`

**Step 1: Write catalog.js**

This module handles:
- Fetching collections from `/stac/collections` and `/vector/collections`
- Merging results into a unified list with type tagging
- Client-side search/filter by name and type
- Rendering collection cards into the page DOM

Key functions:

```javascript
/**
 * Catalog module — fetches, merges, filters, and renders collections.
 */

/** Fetch STAC collections and normalize to common shape. */
async function fetchStacCollections() {
    try {
        const data = await fetchJSON('/stac/collections');
        return (data.collections || []).map(c => ({
            id: c.id,
            title: c.title || c.id,
            description: c.description || '',
            type: detectStacType(c),  // 'raster' or 'zarr'
            source: 'stac',
            extent: c.extent,
            links: c.links || [],
            raw: c,
        }));
    } catch (err) {
        console.warn('STAC collections unavailable:', err.message);
        return [];
    }
}

/** Detect if a STAC collection is raster (COG) or multidimensional (Zarr/NetCDF). */
function detectStacType(collection) {
    // Check item_assets or assets for zarr/netcdf media types
    const assets = collection.item_assets || collection.assets || {};
    for (const [key, asset] of Object.entries(assets)) {
        const mediaType = (asset.type || '').toLowerCase();
        if (mediaType.includes('zarr') || mediaType.includes('netcdf') || mediaType.includes('x-hdf')) {
            return 'zarr';
        }
    }
    return 'raster';
}

/** Fetch OGC Features collections and normalize to common shape. */
async function fetchVectorCollections() {
    try {
        const data = await fetchJSON('/vector/collections');
        return (data.collections || []).map(c => ({
            id: c.id,
            title: c.title || c.id,
            description: c.description || '',
            type: 'vector',
            source: 'tipg',
            extent: c.extent,
            itemCount: c.numberMatched || null,
            geometryType: extractGeometryType(c),
            raw: c,
        }));
    } catch (err) {
        console.warn('Vector collections unavailable:', err.message);
        return [];
    }
}

/** Extract geometry type from OGC collection schema. */
function extractGeometryType(collection) {
    // TiPG includes geometry info in the collection properties
    const props = collection.properties || {};
    for (const [key, val] of Object.entries(props)) {
        if (val && val.type === 'geometry') return val.geometry_type || 'geometry';
    }
    return 'geometry';
}

/** Build viewer URL for a collection based on its type. */
function getViewerUrl(collection) {
    switch (collection.type) {
        case 'raster': return `/viewer/raster?collection=${encodeURIComponent(collection.id)}`;
        case 'zarr': return `/viewer/zarr?collection=${encodeURIComponent(collection.id)}`;
        case 'vector': return `/viewer/vector?collection=${encodeURIComponent(collection.id)}`;
        default: return '#';
    }
}

/** Filter collections by search text and type toggle. */
function filterCollections(collections, searchText, activeTypes) {
    return collections.filter(c => {
        const matchesSearch = !searchText ||
            c.title.toLowerCase().includes(searchText) ||
            c.description.toLowerCase().includes(searchText) ||
            c.id.toLowerCase().includes(searchText);
        const matchesType = activeTypes.size === 0 || activeTypes.has(c.type);
        return matchesSearch && matchesType;
    });
}

/** Render collection cards into a target container element. */
function renderCollectionCards(collections, container) {
    if (collections.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p class="empty-state-message">No collections found</p>
                <p class="empty-state-hint">Try adjusting your search or filters</p>
            </div>`;
        return;
    }

    container.innerHTML = collections.map(c => `
        <a href="${getViewerUrl(c)}" class="card card-link">
            <div class="card-header">
                <h3 class="card-title">${escapeHtml(c.title)}</h3>
                <span class="badge badge-${c.type}">${c.type}</span>
            </div>
            <div class="card-body">
                <p>${escapeHtml(c.description).substring(0, 200)}</p>
                ${c.extent?.spatial?.bbox ? `<small class="text-muted">Bbox: ${formatBbox(c.extent.spatial.bbox[0])}</small>` : ''}
            </div>
        </a>
    `).join('');
}

/** Escape HTML to prevent XSS in dynamic content. */
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/** Format a bounding box array to readable string. */
function formatBbox(bbox) {
    if (!bbox || bbox.length < 4) return '';
    return `[${bbox.map(v => v.toFixed(2)).join(', ')}]`;
}
```

**Step 2: Commit**

```bash
git add geotiler/static/js/catalog.js
git commit -m "feat(ui): add catalog JS module for collection fetching and rendering"
```

---

### Task 3.3: Unified Catalog Template

**Files:**
- Create: `geotiler/templates/pages/catalog/unified.html`

**Step 1: Write the template**

```html
{% extends "base.html" %}
{% from "components/macros.html" import badge, empty_state %}

{% block title %}Catalog{% endblock %}

{% block content %}
<h1>Geospatial Data Catalog</h1>
<p>Browse all available raster, vector, and multidimensional collections.</p>

<div class="catalog-filters">
    <input type="search" id="catalog-search" class="form-input" placeholder="Search collections..." autocomplete="off">
    <div class="catalog-type-toggles">
        <button class="btn btn-outline btn-small type-toggle active" data-type="all">All</button>
        <button class="btn btn-outline btn-small type-toggle" data-type="raster">{{ badge("Raster", "raster") }}</button>
        <button class="btn btn-outline btn-small type-toggle" data-type="vector">{{ badge("Vector", "vector") }}</button>
        <button class="btn btn-outline btn-small type-toggle" data-type="zarr">{{ badge("Zarr", "zarr") }}</button>
    </div>
</div>

<div id="catalog-loading" class="empty-state">
    <p class="empty-state-message">Loading collections...</p>
</div>

<div id="catalog-grid" class="card-grid" style="display: none;"></div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', path='js/catalog.js') }}"></script>
<script>
(async function() {
    const grid = document.getElementById('catalog-grid');
    const loading = document.getElementById('catalog-loading');
    const search = document.getElementById('catalog-search');

    // Fetch both sources in parallel
    const [stac, vector] = await Promise.all([
        fetchStacCollections(),
        fetchVectorCollections(),
    ]);
    const allCollections = [...stac, ...vector];

    loading.style.display = 'none';
    grid.style.display = '';

    let activeTypes = new Set();

    function render() {
        const searchText = search.value.toLowerCase().trim();
        const filtered = filterCollections(allCollections, searchText, activeTypes);
        renderCollectionCards(filtered, grid);
    }

    render();

    // Search handler
    search.addEventListener('input', debounce(render, 200));

    // Type toggle handlers
    document.querySelectorAll('.type-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const type = btn.dataset.type;
            if (type === 'all') {
                activeTypes.clear();
                document.querySelectorAll('.type-toggle').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            } else {
                document.querySelector('.type-toggle[data-type="all"]').classList.remove('active');
                btn.classList.toggle('active');
                if (btn.classList.contains('active')) {
                    activeTypes.add(type);
                } else {
                    activeTypes.delete(type);
                }
                if (activeTypes.size === 0) {
                    document.querySelector('.type-toggle[data-type="all"]').classList.add('active');
                }
            }
            render();
        });
    });
})();
</script>
{% endblock %}
```

**Step 2: Commit**

```bash
git add geotiler/templates/pages/catalog/unified.html
git commit -m "feat(ui): add unified catalog page with search and type filtering"
```

---

### Task 3.4: STAC Catalog Template

**Files:**
- Create: `geotiler/templates/pages/catalog/stac.html`

**Step 1: Write the template**

Similar structure to unified but STAC-specific:
- Only fetches from `/stac/collections`
- Collection cards expand on click to show items (fetched via POST `/stac/search` with collection filter)
- Item cards show: thumbnail (if asset `thumbnail` exists), datetime, bbox, asset list
- Items link to raster or zarr viewer based on asset media type
- Item pagination (limit/offset via STAC API)

The template includes inline `<script>` with STAC-specific logic:
- `fetchStacItems(collectionId, limit, offset)` — POST to `/stac/search`
- `renderItemCards(items, container)` — render item cards with thumbnails
- Expandable collection detail panel

**Step 2: Commit**

```bash
git add geotiler/templates/pages/catalog/stac.html
git commit -m "feat(ui): add STAC catalog page with collection/item browser"
```

---

### Task 3.5: Vector Catalog Template

**Files:**
- Create: `geotiler/templates/pages/catalog/vector.html`

**Step 1: Write the template**

Vector-specific catalog:
- Fetches from `/vector/collections`
- Shows: title, description, geometry type badge, feature count, CRS
- Collection cards link to `/viewer/vector?collection={id}`
- No item expansion (features are viewed on the map)

**Step 2: Commit**

```bash
git add geotiler/templates/pages/catalog/vector.html
git commit -m "feat(ui): add OGC Features vector catalog page"
```

---

### Task 3.6: Phase 3 Validation

**Step 1: Verify all catalog pages render**

- `GET /catalog` → shows collections from both sources, search works, type filter works
- `GET /catalog/stac` → shows STAC collections, click to expand items
- `GET /catalog/vector` → shows vector collections with geometry types
- Viewer links use correct URL contract (`/viewer/raster?url=...`, `/viewer/vector?collection=...`)
- Empty states display when APIs are unavailable
- Search is responsive and debounced

**Step 2: Commit**

```bash
git commit -m "feat(ui): complete Phase 3 — catalog pages"
```

---

## Phase 4a: Raster & Zarr Viewers (parallel with Phase 4b)

**Greenfield run 4 of 6. Depends on Phases 1, 2, 3.**

### Task 4a.1: Viewer Router

**Files:**
- Create: `geotiler/routers/viewer.py`
- Modify: `geotiler/app.py`

**Step 1: Write the router**

```python
"""
Map viewer pages — raster, zarr, vector, and H3 viewers.

Routes:
    GET /viewer/raster  — COG tile viewer
    GET /viewer/zarr    — Zarr/NetCDF variable viewer
    GET /viewer/vector  — OGC Features map viewer (Phase 4b)
    GET /viewer/h3      — H3 choropleth viewer (Phase 4b)
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(prefix="/viewer", tags=["Viewers"])


@router.get("/raster", include_in_schema=False)
async def raster_viewer(request: Request):
    """COG raster tile viewer with band and colormap controls."""
    return render_template(request, "pages/viewer/raster.html", nav_active="/viewer")


@router.get("/zarr", include_in_schema=False)
async def zarr_viewer(request: Request):
    """Zarr/NetCDF variable viewer with dimension controls."""
    return render_template(request, "pages/viewer/zarr.html", nav_active="/viewer")
```

**Step 2: Register in app.py, commit**

```bash
git add geotiler/routers/viewer.py geotiler/app.py
git commit -m "feat(ui): add viewer router for raster and zarr pages"
```

---

### Task 4a.2: Raster Viewer

**Files:**
- Create: `geotiler/templates/pages/viewer/raster.html`
- Create: `geotiler/static/js/viewer-raster.js`

**Step 1: Write viewer-raster.js**

Key functions:
- `initRasterViewer()` — reads `?url=` param, fetches `/cog/info`, initializes MapLibre map
- `loadCogInfo(url)` — fetches band info, statistics, bounds from `/cog/info?url={url}`
- `addRasterTileLayer(map, url, options)` — adds a raster tile source/layer to MapLibre using `/cog/tiles/{z}/{x}/{y}` URL template
- `updateTileLayer(map, options)` — updates tile URL when controls change (band selection, colormap, rescale)
- `buildTileUrl(baseUrl, bidx, colormap, rescale)` — constructs the tile URL with query parameters
- `populateBandSelector(bands)` — fills the band dropdown from info response
- `populateColormapSelector()` — fills colormap dropdown (hardcoded list: viridis, terrain, plasma, inferno, magma, cividis, gray, rdylgn, rdbu, spectral)
- `fitToBounds(map, bounds)` — fit map to COG spatial extent

**Step 2: Write the template**

Layout: `sidebar-layout` CSS grid with controls on left, MapLibre map on right.

```html
{% extends "base.html" %}
{% from "components/macros.html" import map_container, form_group, sidebar_panel, status_indicator, empty_state %}

{% block title %}Raster Viewer{% endblock %}

{% block head %}
<link href="https://unpkg.com/maplibre-gl@^4.0.0/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@^4.0.0/dist/maplibre-gl.js"></script>
{% endblock %}

{% block main_class %}viewer-layout{% endblock %}

{% block content %}
<aside class="map-sidebar" id="viewer-sidebar">
    <div class="sidebar-header">
        <h2>Raster Viewer</h2>
    </div>

    <div id="viewer-controls" style="display: none;">
        {# Controls populated by JS after info loads #}
        {% call sidebar_panel("Band Selection") %}
        <div id="band-controls"></div>
        {% endcall %}

        {% call sidebar_panel("Display") %}
        <div id="display-controls"></div>
        {% endcall %}

        {% call sidebar_panel("Metadata", collapsible=true) %}
        <div id="metadata-panel"></div>
        {% endcall %}
    </div>

    <div id="viewer-loading" class="empty-state">
        <p class="empty-state-message">Enter a COG URL or select from the catalog</p>
    </div>

    <div id="viewer-error" class="empty-state" style="display: none;"></div>
</aside>

<div class="map-area">
    {{ map_container("raster-map", height="100%") }}
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', path='js/viewer-raster.js') }}"></script>
<script>
document.addEventListener('DOMContentLoaded', initRasterViewer);
</script>
{% endblock %}
```

**Step 3: Commit**

```bash
git add geotiler/templates/pages/viewer/raster.html geotiler/static/js/viewer-raster.js
git commit -m "feat(ui): add raster viewer with MapLibre and band/colormap controls"
```

---

### Task 4a.3: Zarr Viewer

**Files:**
- Create: `geotiler/templates/pages/viewer/zarr.html`
- Create: `geotiler/static/js/viewer-zarr.js`

**Step 1: Write viewer-zarr.js**

Similar to raster viewer but with Zarr-specific controls:
- `initZarrViewer()` — reads `?url=` and `?variable=` params
- `loadXarrayInfo(url)` — fetches `/xarray/info?url={url}` to get variables, dimensions, bounds
- `populateVariableSelector(variables)` — fills variable dropdown
- `populateDimensionSliders(dimensions)` — creates range sliders for extra dimensions (e.g., time)
- `addZarrTileLayer(map, url, variable, options)` — tile layer from `/xarray/tiles/{z}/{x}/{y}`
- Tile URL uses different query params: `?url={url}&variable={var}&colormap_name={cmap}`

**Step 2: Write the template**

Same `viewer-layout` as raster but with variable selector instead of band selector, plus dimension sliders.

**Step 3: Commit**

```bash
git add geotiler/templates/pages/viewer/zarr.html geotiler/static/js/viewer-zarr.js
git commit -m "feat(ui): add Zarr viewer with variable and dimension controls"
```

---

### Task 4a.4: Phase 4a Validation

- `GET /viewer/raster?url={valid_cog_url}` → map shows tiles, band/colormap controls work
- `GET /viewer/zarr?url={valid_zarr_url}` → variable selector populates, tiles render
- Controls update URL state (shareable links work)
- Error states display for invalid/missing URLs
- Sidebar collapses on mobile (768px breakpoint)

```bash
git commit -m "feat(ui): complete Phase 4a — raster and zarr viewers"
```

---

## Phase 4b: Vector & H3 Viewers (parallel with Phase 4a)

**Greenfield run 5 of 6. Depends on Phases 1, 2, 3. Independent of Phase 4a.**

### Task 4b.1: Add Vector & H3 Routes to Viewer Router

**Files:**
- Modify: `geotiler/routers/viewer.py`

**Step 1: Add routes**

Add to the existing viewer router:

```python
@router.get("/vector", include_in_schema=False)
async def vector_viewer(request: Request):
    """OGC Features vector map viewer."""
    return render_template(request, "pages/viewer/vector.html", nav_active="/viewer")


@router.get("/h3", include_in_schema=False)
async def h3_viewer(request: Request):
    """H3 choropleth viewer."""
    # Pass H3 region config and DuckDB availability
    from geotiler.config import settings
    return render_template(
        request,
        "pages/viewer/h3.html",
        nav_active="/viewer",
        h3_duckdb_enabled=settings.enable_h3_duckdb,
        h3_parquet_url=settings.h3_parquet_url,
    )
```

**Step 2: Commit**

```bash
git add geotiler/routers/viewer.py
git commit -m "feat(ui): add vector and H3 viewer routes"
```

---

### Task 4b.2: Vector Viewer

**Files:**
- Create: `geotiler/templates/pages/viewer/vector.html`
- Create: `geotiler/static/js/viewer-vector.js`

**Step 1: Write viewer-vector.js**

Key functions:
- `initVectorViewer()` — reads `?collection=` param, fetches collection metadata
- `loadCollectionInfo(collectionId)` — fetches `/vector/collections/{id}`
- `addVectorTileLayer(map, collectionId, tms)` — adds MVT source to MapLibre from `/vector/collections/{id}/tiles/WebMercatorQuad/{z}/{x}/{y}`
- `addGeoJSONLayer(map, collectionId, limit)` — fetches GeoJSON from `/vector/collections/{id}/items?limit={limit}` and adds as source
- `toggleLoadingMode(map, mode)` — switches between 'tiles' and 'geojson' mode
- `setupFeaturePopup(map)` — click handler that shows feature properties in a MapLibre popup
- `updateStyleControls(map, options)` — updates fill-color, fill-opacity, line-color on the MapLibre layer
- `buildPropertyTable(properties)` — HTML table from GeoJSON feature properties for popup

MapLibre vector tile source configuration:
```javascript
map.addSource('vector-tiles', {
    type: 'vector',
    tiles: [`${window.location.origin}/vector/collections/${collectionId}/tiles/WebMercatorQuad/{z}/{x}/{y}`],
    minzoom: 0,
    maxzoom: 22,
});
```

**Step 2: Write the template**

Sidebar + map layout. Sidebar has:
- Loading mode toggle (tiles vs GeoJSON)
- Style controls (fill color, stroke color, opacity slider)
- Feature count display
- Metadata panel (geometry type, CRS, properties list)

**Step 3: Commit**

```bash
git add geotiler/templates/pages/viewer/vector.html geotiler/static/js/viewer-vector.js
git commit -m "feat(ui): add vector viewer with MVT tiles and GeoJSON modes"
```

---

### Task 4b.3: H3 Viewer

**Files:**
- Create: `geotiler/templates/pages/viewer/h3.html`
- Create: `geotiler/static/js/viewer-h3.js`

**Step 1: Study the existing H3 implementation**

Read `geotiler/templates/pages/h3/region.html` fully. The key patterns to retain:
- MapLibre base map with dark style
- deck.gl `PolygonLayer` created via `new deck.MapboxOverlay({ layers: [...] })`
- h3-js `cellToBoundary()` for hex geometry conversion
- TopoJSON country boundaries from CDN
- 7 color palettes (Emergency Red, Sahel Gold, etc.)
- Server-side query via `/h3/query?crop=...&tech=...&scenario=...`
- Region presets (global, menaap, sar, lac) with center/zoom/country filters

**Step 2: Write viewer-h3.js**

Refactor the existing inline JS from `region.html` into a module. The H3 viewer is unique — it uses a dark full-viewport layout with floating controls, not the standard sidebar layout.

Key functions:
- `initH3Viewer()` — reads `?region=` param, initializes map and deck.gl overlay
- `loadH3Data(crop, tech, scenario)` — fetches from `/h3/query`
- `renderHexLayer(data, palette)` — creates deck.gl PolygonLayer with h3-js geometry
- `renderCountryBoundaries(map, countryCodes)` — loads TopoJSON, filters to region
- `PALETTES` — the 7 palette definitions (color arrays)
- `REGIONS` — region presets (global, menaap, sar, lac) with center/zoom

**Step 3: Write the template**

The H3 viewer does NOT extend `base.html` — it is a standalone full-viewport page (matching current behavior). It has its own `<head>` with CDN scripts for MapLibre, deck.gl, h3-js, and TopoJSON.

Layout: full-viewport map with floating control panel (top-left), color legend (bottom-right).

**Step 4: Commit**

```bash
git add geotiler/templates/pages/viewer/h3.html geotiler/static/js/viewer-h3.js
git commit -m "feat(ui): add H3 choropleth viewer with deck.gl and palette controls"
```

---

### Task 4b.4: Phase 4b Validation

- `GET /viewer/vector?collection={collection_id}` → MVT tiles render on MapLibre
- Toggle to GeoJSON mode → features load with pagination
- Feature click → popup with property table
- Style controls change layer appearance
- `GET /viewer/h3` → deck.gl hexagons render
- Region selector works (global, menaap, sar, lac)
- Palette selector changes colors
- Crop/tech/scenario filters update data

```bash
git commit -m "feat(ui): complete Phase 4b — vector and H3 viewers"
```

---

## Phase 5: Reference & System Pages

**Greenfield run 6 of 6. Depends on Phases 1 and 2.**

### Task 5.1: Reference Page

**Files:**
- Create: `geotiler/routers/reference.py`
- Create: `geotiler/templates/pages/reference/index.html`
- Modify: `geotiler/app.py`

**Step 1: Write the router**

```python
"""
Reference page — consolidated API documentation and guides.

Routes:
    GET /reference — API reference landing page
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(tags=["Reference"])


@router.get("/reference", include_in_schema=False)
async def reference_page(request: Request):
    """API reference and guides."""
    return render_template(request, "pages/reference/index.html", nav_active="/reference")
```

**Step 2: Write the template**

Sidebar navigation + content area. Sections:
- Quick Start — basic curl examples for COG info, tiles, vector collections
- Authentication — how Azure OAuth works with this tile server
- COG API — endpoint table for `/cog/*`
- XArray API — endpoint table for `/xarray/*`
- pgSTAC Searches — endpoint table for `/searches/*`
- STAC API — endpoint table for `/stac/*` (conditional on `stac_api_enabled`)
- Vector API — endpoint table for `/vector/*` (conditional on `tipg_enabled`)
- Custom Endpoints — `/health`, `/admin/*`, `/h3/*`

Each section has:
- Brief description
- Endpoint table (method, path, description)
- Example curl with copy-to-clipboard button
- Link to Swagger UI for interactive testing

Use hash-based navigation (`#cog-api`, `#vector-api`, etc.) with sidebar links.

**Step 3: Register in app.py, commit**

```bash
git add geotiler/routers/reference.py geotiler/templates/pages/reference/index.html geotiler/app.py
git commit -m "feat(ui): add reference page with API docs and guides"
```

---

### Task 5.2: System Page

**Files:**
- Create: `geotiler/routers/system.py`
- Create: `geotiler/templates/pages/system/index.html`
- Create: `geotiler/templates/pages/system/_health_fragment.html`
- Modify: `geotiler/app.py`

**Step 1: Write the router**

```python
"""
System page — admin diagnostics and health monitoring.

Routes:
    GET /system            — System dashboard
    GET /system/_health    — HTMX health fragment (30-second polling)
"""

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from geotiler.routers.health import health as get_health_data
from geotiler.templates_utils import templates, get_template_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/", include_in_schema=False)
async def system_dashboard(request: Request):
    """System diagnostics dashboard with health visualization."""
    response = Response()
    health_data = await get_health_data(request, response)
    context = get_template_context(request, health=health_data, nav_active="/system")
    return templates.TemplateResponse("pages/system/index.html", context)


@router.get("/_health", response_class=HTMLResponse, include_in_schema=False)
async def health_fragment(request: Request):
    """HTMX partial for health auto-refresh."""
    response = Response()
    health_data = await get_health_data(request, response)
    context = get_template_context(request, health=health_data)
    return templates.TemplateResponse("pages/system/_health_fragment.html", context)
```

**Step 2: Write the system dashboard template**

Based on the current admin dashboard (`pages/admin/index.html`) but with cleaner structure using the new macro library:
- Health status overview (version, uptime, overall status indicator)
- Service dependency cards (PostgreSQL, Blob Storage, STAC, TiPG) using `status_indicator` macro
- Configuration flags display (using `data_table` macro)
- Resource info (CPU, memory from health endpoint)
- HTMX auto-refresh: `hx-get="/system/_health" hx-trigger="every 30s" hx-swap="innerHTML"` on the health content div
- "QA/UAT Environment" banner

```html
{% extends "base.html" %}
{% from "components/macros.html" import status_indicator, data_table, card %}

{% block title %}System{% endblock %}

{% block head %}
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
{% endblock %}

{% block content %}
<div class="callout callout-warning">
    <strong>System Dashboard</strong> — QA/UAT diagnostic tool. Not shown in production.
</div>

<h1>System Status</h1>

<div id="health-content" hx-get="/system/_health" hx-trigger="every 30s" hx-swap="innerHTML">
    {% include "pages/system/_health_fragment.html" %}
</div>
{% endblock %}
```

**Step 3: Write the health fragment**

The fragment renders the health status cards, service cards, and config table. It is a standalone partial (no extends, no navbar/footer) that gets swapped in by HTMX.

Reference the current `pages/admin/_health_fragment.html` for the health data structure — the `health` object contains `status`, `version`, `services`, `resources`, `config`, etc.

**Step 4: Register in app.py, commit**

```bash
git add geotiler/routers/system.py geotiler/templates/pages/system/index.html geotiler/templates/pages/system/_health_fragment.html geotiler/app.py
git commit -m "feat(ui): add system dashboard with HTMX health polling"
```

---

### Task 5.3: Phase 5 Validation

- `GET /reference` → renders with sidebar navigation and all API sections
- Code examples have working copy-to-clipboard
- Conditional sections hide when features disabled
- `GET /system` → renders health dashboard
- HTMX polling works (health fragment refreshes every 30 seconds)
- Status indicators show correct colors

```bash
git commit -m "feat(ui): complete Phase 5 — reference and system pages"
```

---

## Phase 6: Cleanup & Integration

**Not a Greenfield run — manual integration and old UI removal.**

### Task 6.1: Update Admin Router

**Files:**
- Modify: `geotiler/routers/admin.py`

Remove the `GET /` route from admin.py (homepage now owns `/`). Keep `/api` and `/admin/refresh-collections`. Optionally add redirect from old URL to new:

```python
from fastapi.responses import RedirectResponse

# Old admin dashboard → new system page
@router.get("/", include_in_schema=False)
async def admin_redirect():
    return RedirectResponse(url="/system", status_code=301)
```

Actually, since the home router is registered first, it catches `/` first. Just leave admin as-is or clean up.

**Step 1: Commit**

```bash
git add geotiler/routers/admin.py
git commit -m "refactor(ui): update admin router for new URL structure"
```

---

### Task 6.2: Remove Old UI Files

**Files to delete** (after verifying new UI works):
- `geotiler/templates/base_guide.html`
- `geotiler/templates/components/guide_sidebar.html`
- `geotiler/templates/pages/admin/` (replaced by `/system`)
- `geotiler/templates/pages/cog/` (replaced by `/catalog/stac` + `/viewer/raster`)
- `geotiler/templates/pages/xarray/` (replaced by `/catalog/stac` + `/viewer/zarr`)
- `geotiler/templates/pages/searches/` (replaced by `/catalog/stac`)
- `geotiler/templates/pages/stac/` (replaced by `/catalog/stac`)
- `geotiler/templates/pages/map/` (replaced by `/viewer/*`)
- `geotiler/templates/pages/h3/` (replaced by `/viewer/h3`)
- `geotiler/templates/pages/guide/` (replaced by `/reference`)
- `geotiler/static/js/common.js` (replaced by `utils.js`)
- Old routers: `cog_landing.py`, `xarray_landing.py`, `searches_landing.py`, `stac_explorer.py`, `docs_guide.py`, `map_viewer.py`

**Do NOT delete**:
- `geotiler/routers/h3_explorer.py` — still serves `/h3/query` API endpoint
- `geotiler/routers/admin.py` — still serves `/admin/refresh-collections` and `/api`
- `geotiler/templates_utils.py` — still used by new routers

**Step 1: Remove old imports from app.py**

Remove imports and `include_router` calls for deleted routers.

**Step 2: Delete old files**

```bash
git rm geotiler/templates/base_guide.html
git rm geotiler/templates/components/guide_sidebar.html
git rm -r geotiler/templates/pages/admin/
git rm -r geotiler/templates/pages/cog/
git rm -r geotiler/templates/pages/xarray/
git rm -r geotiler/templates/pages/searches/
git rm -r geotiler/templates/pages/stac/
git rm -r geotiler/templates/pages/map/
git rm -r geotiler/templates/pages/h3/
git rm -r geotiler/templates/pages/guide/
git rm geotiler/static/js/common.js
git rm geotiler/routers/cog_landing.py
git rm geotiler/routers/xarray_landing.py
git rm geotiler/routers/searches_landing.py
git rm geotiler/routers/stac_explorer.py
git rm geotiler/routers/docs_guide.py
git rm geotiler/routers/map_viewer.py
```

**Step 3: Commit**

```bash
git add -A
git commit -m "refactor(ui): remove old UI templates, routers, and static assets"
```

---

### Task 6.3: Final Validation

Run the full app and verify every new route:

| Route | Expected |
|-------|----------|
| `GET /` | Homepage with catalog cards |
| `GET /catalog` | Unified catalog with STAC + OGC collections |
| `GET /catalog/stac` | STAC collection browser |
| `GET /catalog/vector` | OGC Features collection browser |
| `GET /viewer/raster?url={cog_url}` | Raster viewer with MapLibre |
| `GET /viewer/zarr?url={zarr_url}` | Zarr viewer with variable selector |
| `GET /viewer/vector?collection={id}` | Vector viewer with MVT tiles |
| `GET /viewer/h3` | H3 choropleth with deck.gl |
| `GET /reference` | API reference with sidebar nav |
| `GET /system` | System dashboard with HTMX polling |
| `GET /docs` | Swagger UI (unchanged) |
| `GET /health` | Health JSON (unchanged) |

Verify no old routes 404 unexpectedly. Existing API endpoints (`/cog/info`, `/vector/collections`, etc.) must still work — they are NOT affected by UI changes.

```bash
git commit -m "feat(ui): complete UI rebuild — all phases validated"
```

---

## Post-Build: Adversarial Review

After all phases complete, run the **Adversarial Review** pipeline on the full new UI codebase:

**Scope**: All new files:
- `geotiler/static/css/styles.css`
- `geotiler/static/js/utils.js`, `catalog.js`, `viewer-raster.js`, `viewer-zarr.js`, `viewer-vector.js`, `viewer-h3.js`
- `geotiler/templates/` (all new templates)
- `geotiler/routers/home.py`, `catalog.py`, `viewer.py`, `reference.py`, `system.py`

**Split**: A (Design vs Runtime) — Alpha reviews architecture/components, Beta reviews runtime behavior/JS error handling.

**Focus areas**: XSS in dynamic HTML rendering, API error handling, responsive layout edge cases, accessibility basics.
