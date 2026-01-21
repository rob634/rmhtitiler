# Application Review - rmhtitiler

**Review Date:** 2026-01-18 (Updated 2026-01-21)
**Reviewer:** Claude Code Analysis
**Version Reviewed:** 0.7.16.0

---

## Executive Summary

**rmhtitiler** is a production-grade geospatial tile server built on TiTiler, deployed on Azure App Service. It's a well-architected system with comprehensive documentation, but has some technical debt from rapid feature development.

### Key Strengths
- **Enterprise Azure Integration**: Passwordless auth via Managed Identity for storage and PostgreSQL
- **Multi-format Support**: COGs, Zarr/NetCDF, pgSTAC mosaics, and PostGIS vector tiles
- **Comprehensive Diagnostics**: Health endpoints, verbose diagnostics for debugging
- **Good Documentation**: Detailed deployment guides, API reference, implementation docs

### Areas for Improvement
- **12 issues identified, 9 resolved, 1 not applicable** (2 remaining: 0 High, 1 Medium, 1 Low severity)
- **UI technical debt**: ✅ Resolved via Jinja2 migration (CSS consolidated, URLs configurable)
- **Async patterns**: ✅ Fixed - Token acquisition now uses `asyncio.to_thread()`
- **Error handling**: ✅ Fixed - Diagnostics now surface query errors instead of swallowing

### Current Focus
Jinja2 UI refactoring is **COMPLETE** (all 8 phases done). This addresses CSS duplication (#8) and hardcoded URLs (#11).

### Documentation Coverage
| Document | Status | Notes |
|----------|--------|-------|
| `WIKI.md` | Excellent | Complete API reference with examples |
| `QA_DEPLOYMENT.md` | Excellent | Enterprise deployment with RBAC |
| `xarray.md` | Good | Zarr/NetCDF implementation guide |
| `CLAUDE.md` | Good | Project overview and resume context |

---

## Overview

**rmhtitiler** is a production-ready geospatial tile server built on TiTiler, designed for Azure App Service deployment. It integrates multiple data access patterns:

| Component | Purpose |
|-----------|---------|
| **COG Tiles** | Cloud Optimized GeoTIFF serving via GDAL |
| **Zarr/NetCDF** | Multidimensional array tiles via xarray |
| **pgSTAC Mosaics** | Dynamic tiling from STAC catalog searches |
| **TiPG** | OGC Features API + Vector Tiles from PostGIS |
| **STAC API** | STAC catalog browsing and search |
| **Planetary Computer** | Climate data integration |

The architecture is solid overall, with proper lifespan management, health endpoints, and background token refresh for Azure Managed Identity.

---

## Issues Identified

### 1. ~~Synchronous Blocking in Async Context~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-19

**Resolution:** Added async wrappers using `asyncio.to_thread()` to run Azure SDK token acquisition in the thread pool. The middleware now calls `await get_storage_oauth_token_async()` which doesn't block the event loop during token refresh.

**Files Modified:**
- `geotiler/auth/storage.py` - Added `get_storage_oauth_token_async()`, `refresh_storage_token_async()`
- `geotiler/auth/postgres.py` - Added `get_postgres_credential_async()`, `refresh_postgres_token_async()`
- `geotiler/middleware/azure_auth.py` - Now uses async token function
- `geotiler/services/background.py` - Now uses async refresh functions

---

### 2. Global Mutable State Singletons

**Severity:** Medium
**Locations:**
- `geotiler/services/background.py:20` - `_app: "FastAPI" = None`
- `geotiler/services/database.py:17` - `_app_state: Optional[Any] = None`
- `geotiler/routers/vector.py:97` - `tipg_startup_state = TiPGStartupState()`

**Explanation:**
Multiple modules use module-level global variables that are mutated at runtime. This pattern creates several problems:

1. **Testing difficulty** - Unit tests can't run in isolation because global state persists between tests
2. **Hidden dependencies** - Functions depend on global state being set correctly by other code
3. **Race conditions** - In multi-worker deployments, each worker has its own copy, but within a worker, concurrent requests could see inconsistent state
4. **Initialization order** - Code must be called in a specific order or it fails silently

A better approach would be dependency injection via FastAPI's dependency system or storing state exclusively in `app.state`.

---

### 3. ~~Environment Variable Mutation~~ ⊘ WON'T FIX

**Status:** Not applicable for single-tenant deployment

**Location:** `geotiler/auth/storage.py:115-116`

**Original Concern:** Mutating `os.environ` could cause race conditions if multiple requests wrote different values simultaneously.

**Why It's Safe:**
This application is single-tenant - all requests use the same Azure Storage account and the same cached MI token. The "race condition" would only be two requests writing identical values, which is harmless.

Additionally:
- Token refresh is coordinated via `asyncio.Lock` (no thundering herd)
- Python string assignment is atomic (GIL)
- GDAL reads happen after token is set

**If Multi-Tenant Were Needed:** Would use `rasterio.Env()` context managers for thread-local GDAL configuration. Not required for current architecture.

---

### 4. ~~Threading Lock in Async Code~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-21

**Resolution:** Added `asyncio.Lock` to `TokenCache` for async callers. The cache now supports both:
- **Async access** (preferred): Uses `async_lock` property with unlocked methods
- **Sync access** (startup): Uses `threading.Lock` for initialization before event loop

**Files Modified:**
- `geotiler/auth/cache.py` - Added `_async_lock` field and `*_unlocked()` methods
- `geotiler/auth/storage.py` - Async functions now use `async with cache.async_lock:`
- `geotiler/auth/postgres.py` - Async functions now use `async with cache.async_lock:`

**Pattern:**
```python
async with storage_token_cache.async_lock:
    cached = storage_token_cache.get_if_valid_unlocked(min_ttl_seconds=300)
    if cached:
        return cached
    token, expires_at = await asyncio.to_thread(_acquire_token)
    storage_token_cache.set_unlocked(token, expires_at)
```

This prevents thundering herd on token refresh - only one coroutine acquires a new token; others wait and use the cached result.

---

### 5. ~~Overly Permissive CORS Configuration~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-18

**Resolution:** CORS middleware removed from FastAPI. CORS is now handled by infrastructure:
- **External traffic**: Cloudflare WAF + CDN
- **Internal traffic**: Azure APIM

The application no longer needs to manage cross-origin access since it runs behind reverse proxies that handle security policies at the infrastructure level.

---

### 6. ~~Error Swallowing in Query Helpers~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-21

**Resolution:** Changed `_run_query()` and `_run_query_single()` helpers to return `(result, error)` tuples instead of silently returning empty results. All ~50 call sites updated to handle errors and surface them in API responses.

**Files Modified:**
- `geotiler/routers/diagnostics.py` - Helper functions now return tuples, all call sites updated

**Before:**
```python
async def _run_query(...) -> list[dict]:
    ...
    return []  # Error swallowed - can't distinguish from "no rows"
```

**After:**
```python
async def _run_query(...) -> tuple[list[dict], Optional[str]]:
    ...
    return [], str(e)  # Error surfaced in API response
```

Now users see actual errors (e.g., "permission denied") instead of misleading results (e.g., "PostGIS not installed").

---

### 7. God Function - Verbose Diagnostics

**Severity:** Low
**Location:** `geotiler/routers/diagnostics.py:445-1000`

**Explanation:**
The `verbose_diagnostics` endpoint is approximately 550 lines long and executes 15+ sequential database queries. This violates the Single Responsibility Principle and creates several problems:

1. **Timeout risk** - Sequential queries on a slow database could exceed HTTP timeouts
2. **Untestable** - Can't unit test individual diagnostic checks
3. **Hard to maintain** - Changes to one query risk breaking others
4. **All-or-nothing** - Can't get partial results if one query fails

Consider breaking this into smaller functions, each responsible for one diagnostic category (permissions, geometry registration, schema info, etc.). The endpoint could then orchestrate these and potentially run them in parallel.

---

### 8. ~~Duplicated CSS Across Landing Pages~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-18

**Resolution:** CSS consolidated into `geotiler/static/css/styles.css` (~900 lines). All landing pages now use Jinja2 templates that extend `base.html` and reference the shared stylesheet. Changes to styling only need to be made in one place.

---

### 9. ~~Mixed Sync/Async Database Access~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-21

**Resolution:** Added async wrappers for database ping functions that use `asyncio.to_thread()` to run blocking psycopg calls in a thread pool:

```python
async def ping_database_async() -> Tuple[bool, Optional[str]]:
    """Runs blocking ping in thread pool."""
    return await asyncio.to_thread(ping_database)

async def ping_database_with_timing_async() -> Tuple[bool, Optional[str], Optional[float]]:
    """Runs blocking ping with timing in thread pool."""
    return await asyncio.to_thread(ping_database_with_timing)
```

**Files Modified:**
- `geotiler/services/database.py` - Added `ping_database_async()`, `ping_database_with_timing_async()`, `is_database_ready_async()`
- `geotiler/routers/health.py` - Updated `/readyz` and `/health` to use async versions

Health checks no longer block the event loop during database pings.

**Note:** Two connection pools remain (psycopg for titiler-pgstac, asyncpg for TiPG) because the upstream libraries require different drivers. This is documented and intentional.

---

### 10. ~~Excessive Logging Noise~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-21

**Resolution:** Cleaned up logging throughout the codebase:

- Removed all banner-style logging (`"=" * 60`)
- Moved verbose token acquisition details to DEBUG level
- Converted multi-line log entries to single concise lines
- Kept one INFO log per significant event (startup, token acquired)

**Files Modified:**
- `geotiler/auth/storage.py` - Token acquisition logs
- `geotiler/auth/postgres.py` - Token acquisition logs
- `geotiler/app.py` - Startup logs
- `geotiler/services/background.py` - Background refresh logs
- `geotiler/routers/stac.py` - STAC API initialization
- `geotiler/routers/vector.py` - TiPG initialization

**Before:**
```python
logger.info("=" * 60)
logger.info("Acquiring Azure Storage OAuth token...")
logger.info(f"Mode: {mode}")
logger.info(f"Storage Account: {account}")
logger.info("=" * 60)
```

**After:**
```python
logger.debug(f"Acquiring storage token: account={account} mode={mode}")
logger.info(f"Storage token acquired, expires={expires_at.isoformat()}")
```

---

### 11. ~~Hardcoded Sample URLs~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-18

**Resolution:** Sample URLs are now loaded from environment configuration via `settings.sample_cog_urls`, `settings.sample_zarr_urls`, and `settings.sample_stac_collections`. Templates receive these via `get_template_context()`. URLs can be configured per-environment using JSON environment variables without redeployment.

---

### 12. ~~Missing Type Annotations~~ ✅ RESOLVED

**Status:** Fixed on 2026-01-21

**Resolution:** Added proper type annotations to `geotiler/services/database.py`:

```python
from psycopg_pool import ConnectionPool
from starlette.datastructures import State

_app_state: Optional[State] = None

def get_db_pool() -> Optional[ConnectionPool]:
```

This provides:
- IDE autocomplete for `State` and `ConnectionPool` methods
- Type checker catches errors at development time
- Self-documenting code for future maintainers

**Note:** `planetary_computer.py` still uses `Any` for `PlanetaryComputerCredentialProvider` - this is intentional because the type is conditionally imported and may not exist at runtime.

---

## Positive Patterns

The codebase demonstrates several good practices worth preserving:

| Pattern | Location | Notes |
|---------|----------|-------|
| **Pydantic Settings** | `config.py` | Clean configuration with validation and defaults |
| **Health Endpoint Stratification** | `routers/health.py` | Proper `/livez`, `/readyz`, `/health` Kubernetes pattern |
| **Degraded Mode** | `app.py:165-176` | App starts even if database connection fails |
| **Token Caching** | `auth/cache.py` | Proactive refresh prevents mid-request expiration |
| **Lifespan Context Manager** | `app.py:60-111` | Modern FastAPI pattern for startup/shutdown |
| **Comprehensive Diagnostics** | `routers/diagnostics.py` | Excellent for debugging without direct DB access |
| **Feature Flags** | `config.py:90-116` | Clean enable/disable for optional components |

---

## Summary Table

| # | Issue | Severity | Effort to Fix | Impact |
|---|-------|----------|---------------|--------|
| 1 | ~~Sync blocking in async~~ | ~~**High**~~ | ✅ Fixed | ~~Event loop blocking~~ |
| 2 | Global mutable state | Medium | High | Testing, race conditions |
| 3 | ~~Environment mutation~~ | ~~Medium~~ | ⊘ N/A | ~~Race conditions~~ |
| 4 | ~~Threading lock in async~~ | ~~Medium~~ | ✅ Fixed | ~~Potential deadlocks~~ |
| 5 | ~~CORS misconfiguration~~ | ~~Medium~~ | ✅ Fixed | ~~Security~~ |
| 6 | ~~Error swallowing~~ | ~~Medium~~ | ✅ Fixed | ~~Debugging difficulty~~ |
| 7 | God function | Low | Medium | Maintainability |
| 8 | ~~CSS duplication~~ | ~~Low~~ | ✅ Fixed | ~~Maintainability~~ |
| 9 | ~~Mixed sync/async DB~~ | ~~Low~~ | ✅ Fixed | ~~Consistency~~ |
| 10 | ~~Excessive logging~~ | ~~Low~~ | ✅ Fixed | ~~Log noise~~ |
| 11 | ~~Hardcoded URLs~~ | ~~Low~~ | ✅ Fixed | ~~Brittleness~~ |
| 12 | ~~Missing types~~ | ~~Low~~ | ✅ Fixed | ~~Type safety~~ |

---

## Recommended Priority

Based on severity and effort, suggested order of fixes:

1. ~~**CORS misconfiguration** (#5)~~ ✅ Fixed - Removed, handled by infrastructure
2. ~~**Sync blocking in async** (#1)~~ ✅ Fixed - Uses `asyncio.to_thread()` for Azure SDK calls
3. ~~**Error swallowing** (#6)~~ ✅ Fixed - Returns `(result, error)` tuples, surfaces errors in API
4. ~~**Threading lock** (#4)~~ ✅ Fixed - Added `asyncio.Lock` for async callers
5. ~~**Environment mutation** (#3)~~ ⊘ N/A - Single-tenant, no race condition possible
6. **Global mutable state** (#2) - Recommended for handoff readiness
7. ~~**CSS duplication** (#8)~~ ✅ Fixed - Jinja2 templates with shared CSS
8. ~~**Hardcoded URLs** (#11)~~ ✅ Fixed - Configurable via environment

Items 7, 9, 10, 12 can be addressed opportunistically during other work.

---

## Implementation Plan: Jinja2 UI Refactoring

**Status:** ✅ COMPLETE
**Target Issues:** #8 (CSS duplication), #11 (Hardcoded URLs), Front-end consolidation
**Approach:** Treat the UI as a proper website with Jinja2 templating, static assets, and environment-driven configuration

### Implementation Progress

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Directory Structure | ✅ Complete | Created `static/`, `templates/`, all subdirectories |
| 2. Config Updates | ✅ Complete | Added JSON-based sample URL settings to `config.py` |
| 3. Base Templates | ✅ Complete | Created `base.html`, `base_guide.html`, navbar, footer, macros |
| 4. Consolidated CSS | ✅ Complete | Created `styles.css` (~900 lines) with design tokens |
| 5. JavaScript Utilities | ✅ Complete | Created `common.js` with helper functions |
| 6. FastAPI Setup | ✅ Complete | Static files mounted, Jinja2 configured in `app.py` |
| 7. Page Migration | ✅ Complete | All pages migrated (admin, COG, XArray, Searches, STAC Explorer, Guide) |
| 8. Testing & Cleanup | ✅ Complete | Routers using `templates_utils.py`, all templates populated |

### Files Created/Modified

**New Files:**
- `geotiler/static/css/styles.css` - Consolidated CSS (~900 lines)
- `geotiler/static/js/common.js` - JavaScript utilities
- `geotiler/templates/base.html` - Master template
- `geotiler/templates/base_guide.html` - Guide pages template
- `geotiler/templates/components/navbar.html`
- `geotiler/templates/components/footer.html`
- `geotiler/templates/components/macros.html`
- `geotiler/templates/components/guide_sidebar.html`
- `geotiler/templates/pages/cog/landing.html`
- `geotiler/templates/pages/xarray/landing.html`
- `geotiler/templates/pages/searches/landing.html`
- `geotiler/templates_utils.py` - Template helper functions

**Modified Files:**
- `geotiler/app.py` - Added static file mounting, Jinja2 configuration
- `geotiler/config.py` - Added sample URL JSON settings
- `geotiler/routers/cog_landing.py` - Converted to use templates
- `geotiler/routers/xarray_landing.py` - Converted to use templates
- `geotiler/routers/searches_landing.py` - Converted to use templates

### Completed Work

**Phase 7 (Page Migration) - All Done:**
- [x] `admin.py` → `templates/pages/admin/index.html` (HTMX auto-refresh working)
- [x] `stac_explorer.py` → `templates/pages/stac/explorer.html` (Leaflet map with collection/item browser)
- [x] `docs_guide.py` → `templates/pages/guide/*.html` (9 guide pages)
- [x] `cog_landing.py` → `templates/pages/cog/landing.html`
- [x] `xarray_landing.py` → `templates/pages/xarray/landing.html`
- [x] `searches_landing.py` → `templates/pages/searches/landing.html`

**Phase 8 (Testing) - Verification:**
- [x] All routers use `templates_utils.py` for consistent context
- [x] Static files served via `/static/` mount point
- [x] Sample URLs configurable via `settings.sample_*_urls` properties
- [ ] Production deployment verification (recommended next step)

---

### Goals

1. **Single source of truth for CSS** - One stylesheet, cached by browser/CDN
2. **Reusable components** - Navbar, footer, cards via Jinja2 macros/includes
3. **Template inheritance** - Base template with `{% block %}` for page content
4. **Environment-driven samples** - No hardcoded URLs, configurable per deployment
5. **Maintainable structure** - Clear separation of templates, static files, and routes

---

### Phase 1: Project Structure

#### 1.1 New Directory Structure

```
geotiler/
├── static/                          # NEW: Static assets
│   ├── css/
│   │   └── styles.css               # Consolidated CSS (~400 lines)
│   └── js/
│       └── common.js                # Shared JavaScript utilities
│
├── templates/                       # NEW: Jinja2 templates
│   ├── base.html                    # Master template (DOCTYPE, head, nav, footer)
│   ├── components/
│   │   ├── navbar.html              # Navigation bar macro
│   │   ├── footer.html              # Footer macro
│   │   ├── cards.html               # Card components (service, sample URL, etc.)
│   │   ├── status_badge.html        # Status indicator macro
│   │   ├── code_block.html          # Syntax-highlighted code macro
│   │   └── callout.html             # Info/warning/success callout macro
│   │
│   └── pages/
│       ├── admin/
│       │   └── index.html           # Admin dashboard
│       ├── cog/
│       │   └── index.html           # COG landing page
│       ├── xarray/
│       │   └── index.html           # Zarr/NetCDF landing page
│       ├── searches/
│       │   └── index.html           # pgSTAC searches landing page
│       ├── stac/
│       │   └── explorer.html        # STAC explorer with map
│       └── guide/
│           ├── index.html           # Documentation home
│           ├── authentication.html
│           ├── quick-start.html
│           ├── data-scientists/
│           │   ├── index.html
│           │   ├── point-queries.html
│           │   ├── batch-queries.html
│           │   └── stac-search.html
│           └── web-developers/
│               ├── index.html
│               ├── maplibre-tiles.html
│               └── vector-features.html
│
├── config.py                        # MODIFY: Add sample URL settings
│
└── routers/
    ├── pages.py                     # NEW: Consolidated UI routes
    └── api.py                       # Keep API routes separate (health, etc.)
```

#### 1.2 Files to Delete (after migration)

```
geotiler/routers/
├── admin.py                 # → templates/pages/admin/index.html
├── cog_landing.py           # → templates/pages/cog/index.html
├── xarray_landing.py        # → templates/pages/xarray/index.html
├── searches_landing.py      # → templates/pages/searches/index.html
├── stac_explorer.py         # → templates/pages/stac/explorer.html
└── docs_guide.py            # → templates/pages/guide/*.html
```

---

### Phase 2: Configuration Updates

#### 2.1 Sample URLs Configuration (`config.py`)

```python
from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional
import json

class SampleUrl(BaseSettings):
    """Single sample URL configuration."""
    label: str
    url: str
    description: Optional[str] = None
    # For xarray samples
    variable: Optional[str] = None
    datetime: Optional[str] = None

class Settings(BaseSettings):
    # ... existing settings ...

    # ==========================================================================
    # Sample URLs for Landing Pages (JSON arrays in env vars)
    # ==========================================================================
    sample_cog_urls_json: str = Field(
        default='[]',
        alias='SAMPLE_COG_URLS',
        description='JSON array of COG sample URLs'
    )

    sample_zarr_urls_json: str = Field(
        default='[]',
        alias='SAMPLE_ZARR_URLS',
        description='JSON array of Zarr/NetCDF sample URLs'
    )

    sample_stac_collections_json: str = Field(
        default='[]',
        alias='SAMPLE_STAC_COLLECTIONS',
        description='JSON array of STAC collection IDs to highlight'
    )

    @property
    def sample_cog_urls(self) -> list[dict]:
        """Parse COG sample URLs from JSON."""
        try:
            return json.loads(self.sample_cog_urls_json)
        except json.JSONDecodeError:
            return []

    @property
    def sample_zarr_urls(self) -> list[dict]:
        """Parse Zarr sample URLs from JSON."""
        try:
            return json.loads(self.sample_zarr_urls_json)
        except json.JSONDecodeError:
            return []

    @property
    def sample_stac_collections(self) -> list[dict]:
        """Parse STAC collection samples from JSON."""
        try:
            return json.loads(self.sample_stac_collections_json)
        except json.JSONDecodeError:
            return []
```

#### 2.2 Example Environment Variables

```bash
# Sample COG URLs (JSON array)
SAMPLE_COG_URLS='[
  {"label": "Swiss Terrain (SRTM)", "url": "https://data.geo.admin.ch/ch.swisstopo.swissalti3d/swissalti3d_2019_2573-1085/swissalti3d_2019_2573-1085_0.5_2056_5728.tif", "description": "High-resolution Swiss elevation data"},
  {"label": "Sentinel-2 TCI", "url": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/36/Q/WD/2020/7/S2A_36QWD_20200701_0_L2A/TCI.tif", "description": "True color imagery"}
]'

# Sample Zarr URLs (JSON array)
SAMPLE_ZARR_URLS='[
  {"label": "ERA5 Temperature", "url": "https://example.com/era5.zarr", "variable": "t2m", "description": "Global temperature reanalysis"}
]'

# Sample STAC collections
SAMPLE_STAC_COLLECTIONS='[
  {"id": "flood-risk", "label": "Flood Risk Maps", "description": "Flood depth and extent models"}
]'
```

---

### Phase 3: Base Template & Components

#### 3.1 Base Template (`templates/base.html`)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}geotiler{% endblock %} - geotiler v{{ version }}</title>
    <link rel="stylesheet" href="{{ url_for('static', path='css/styles.css') }}">
    {% block head %}{% endblock %}
</head>
<body>
    {% include "components/navbar.html" %}

    <main class="{% block main_class %}container{% endblock %}">
        {% block content %}{% endblock %}
    </main>

    {% include "components/footer.html" %}

    <script src="{{ url_for('static', path='js/common.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

#### 3.2 Navbar Component (`templates/components/navbar.html`)

```html
{# Navbar macro - pass active page name #}
{% macro navbar(active='') %}
<nav class="navbar">
    <a href="/" class="navbar-brand">
        geotiler <span class="version">v{{ version }}</span>
    </a>
    <div class="navbar-links">
        <a href="/cog/" class="{{ 'active' if active == 'cog' else '' }}">COG</a>
        <a href="/xarray/" class="{{ 'active' if active == 'xarray' else '' }}">XArray</a>
        <a href="/searches/" class="{{ 'active' if active == 'searches' else '' }}">Searches</a>
        <a href="/vector" class="{{ 'active' if active == 'vector' else '' }}">Vector</a>
        {% if stac_api_enabled %}
        <a href="/stac/" class="{{ 'active' if active == 'stac' else '' }}">STAC</a>
        {% endif %}
        <a href="/guide/" class="{{ 'active' if active == 'guide' else '' }}">Guide</a>
        <a href="/docs" class="{{ 'active' if active == 'docs' else '' }}">API Docs</a>
    </div>
</nav>
{% endmacro %}

{# Auto-render if included directly #}
{{ navbar(active|default('')) }}
```

#### 3.3 Sample URL Card (`templates/components/cards.html`)

```html
{# Sample URL card - clickable to populate form #}
{% macro sample_url_card(sample, input_id) %}
<div class="sample-card" onclick="setUrl('{{ sample.url }}', '{{ input_id }}')">
    <div class="sample-label">{{ sample.label }}</div>
    {% if sample.description %}
    <div class="sample-description">{{ sample.description }}</div>
    {% endif %}
</div>
{% endmacro %}

{# Service status card for admin #}
{% macro service_card(name, service) %}
<div class="service-card {{ 'healthy' if service.status == 'healthy' else 'degraded' }}">
    <div class="service-header">
        <span class="service-name">{{ name }}</span>
        {% include "components/status_badge.html" %}
    </div>
    <div class="service-description">{{ service.description }}</div>
    {% if service.endpoints %}
    <ul class="service-endpoints">
        {% for endpoint in service.endpoints[:3] %}
        <li><code>{{ endpoint }}</code></li>
        {% endfor %}
    </ul>
    {% endif %}
</div>
{% endmacro %}

{# Guide navigation card #}
{% macro guide_card(href, title, description) %}
<a href="{{ href }}" class="card-link">
    <div class="card">
        <h3>{{ title }}</h3>
        <p>{{ description }}</p>
    </div>
</a>
{% endmacro %}
```

#### 3.4 Status Badge (`templates/components/status_badge.html`)

```html
{% macro status_badge(status) %}
<span class="badge badge-{{ status }}">
    {% if status == 'healthy' or status == 'ok' %}✓{% endif %}
    {% if status == 'degraded' %}⚠{% endif %}
    {% if status == 'error' %}✗{% endif %}
    {{ status }}
</span>
{% endmacro %}
```

---

### Phase 4: Static CSS (`static/css/styles.css`)

#### 4.1 CSS Structure

```css
/* ==========================================================================
   CSS Variables (Design System)
   ========================================================================== */
:root {
    /* Brand Colors */
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

    /* Spacing */
    --spacing-xs: 4px;
    --spacing-sm: 8px;
    --spacing-md: 16px;
    --spacing-lg: 24px;
    --spacing-xl: 40px;

    /* Typography */
    --font-sans: "Open Sans", Arial, sans-serif;
    --font-mono: "SF Mono", Monaco, "Cascadia Code", monospace;
}

/* ==========================================================================
   Reset & Base
   ========================================================================== */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: var(--font-sans);
    font-size: 15px;
    line-height: 1.7;
    color: var(--ds-navy);
    background-color: var(--ds-bg);
}

a { color: var(--ds-blue-primary); text-decoration: none; }
a:hover { color: var(--ds-cyan); text-decoration: underline; }

/* ==========================================================================
   Layout
   ========================================================================== */
.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: var(--spacing-lg);
}

.layout-sidebar {
    display: flex;
    min-height: calc(100vh - 60px);
}

.sidebar { /* Documentation sidebar */ }
.content { /* Main content area */ }

/* ==========================================================================
   Navbar
   ========================================================================== */
.navbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 30px;
    background: var(--ds-white);
    border-bottom: 3px solid var(--ds-blue-primary);
    position: sticky;
    top: 0;
    z-index: 100;
}

.navbar-brand {
    font-size: 16px;
    font-weight: 700;
    color: var(--ds-navy);
}

.navbar-brand .version {
    color: var(--ds-gray);
    font-weight: 400;
    font-size: 13px;
}

.navbar-links { display: flex; gap: 15px; }
.navbar-links a {
    color: var(--ds-blue-primary);
    font-weight: 500;
    padding: 5px 10px;
    border-radius: 4px;
    font-size: 13px;
}
.navbar-links a:hover { background: var(--ds-gray-light); text-decoration: none; }
.navbar-links a.active { background: var(--ds-blue-primary); color: white; }

/* ==========================================================================
   Cards
   ========================================================================== */
.card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: var(--spacing-lg);
    margin: var(--spacing-lg) 0;
}

.card {
    background: var(--ds-white);
    border-radius: 8px;
    padding: var(--spacing-lg);
    border: 1px solid var(--ds-gray-light);
    transition: all 0.2s;
}

.card:hover {
    border-color: var(--ds-blue-primary);
    transform: translateY(-2px);
}

.card h3 { margin-top: 0; margin-bottom: var(--spacing-sm); }
.card p { margin-bottom: 0; color: var(--ds-gray); font-size: 14px; }

.card-link { text-decoration: none; color: inherit; display: block; }
.card-link:hover { text-decoration: none; }

/* Sample URL cards */
.sample-card {
    padding: var(--spacing-md);
    background: var(--ds-white);
    border: 1px solid var(--ds-gray-light);
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
}

.sample-card:hover {
    border-color: var(--ds-blue-primary);
    background: #f0f7ff;
}

.sample-label { font-weight: 600; font-size: 14px; }
.sample-description { font-size: 12px; color: var(--ds-gray); margin-top: 4px; }

/* ==========================================================================
   Status Badges
   ========================================================================== */
.badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
}

.badge-healthy, .badge-ok { background: #d1fae5; color: var(--ds-success); }
.badge-degraded, .badge-warning { background: #fef3c7; color: var(--ds-warning); }
.badge-error { background: #fee2e2; color: var(--ds-error); }

/* HTTP method badges */
.badge-get { background: #d1fae5; color: var(--ds-success); }
.badge-post { background: #fef3c7; color: var(--ds-warning); }

/* ==========================================================================
   Forms
   ========================================================================== */
.form-group { margin-bottom: var(--spacing-md); }

.form-label {
    display: block;
    font-weight: 600;
    margin-bottom: var(--spacing-xs);
}

.form-input {
    width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--ds-gray-light);
    border-radius: 6px;
    font-size: 14px;
    font-family: var(--font-mono);
}

.form-input:focus {
    outline: none;
    border-color: var(--ds-blue-primary);
    box-shadow: 0 0 0 3px rgba(0, 113, 188, 0.1);
}

.btn {
    display: inline-block;
    padding: 10px 20px;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-primary {
    background: var(--ds-blue-primary);
    color: white;
}

.btn-primary:hover {
    background: var(--ds-blue-dark);
}

.btn-secondary {
    background: var(--ds-gray-light);
    color: var(--ds-navy);
}

/* ==========================================================================
   Code Blocks
   ========================================================================== */
pre {
    background: var(--ds-code-bg);
    color: var(--ds-code-text);
    padding: var(--spacing-lg);
    border-radius: 6px;
    overflow-x: auto;
    margin-bottom: var(--spacing-lg);
    font-size: 13px;
    line-height: 1.5;
}

code {
    font-family: var(--font-mono);
}

p code, li code {
    background: var(--ds-gray-light);
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 13px;
    color: var(--ds-navy);
}

/* Syntax highlighting */
.kw { color: #569cd6; }   /* keywords */
.str { color: #ce9178; }  /* strings */
.num { color: #b5cea8; }  /* numbers */
.cmt { color: #6a9955; }  /* comments */
.fn { color: #dcdcaa; }   /* functions */
.var { color: #9cdcfe; }  /* variables */

/* ==========================================================================
   Callouts
   ========================================================================== */
.callout {
    padding: 15px 20px;
    border-radius: 6px;
    margin: var(--spacing-lg) 0;
    border-left: 4px solid;
}

.callout-info { background: #e8f4fc; border-color: var(--ds-cyan); }
.callout-warning { background: #fef3c7; border-color: var(--ds-gold); }
.callout-success { background: #d1fae5; border-color: var(--ds-success); }
.callout-error { background: #fee2e2; border-color: var(--ds-error); }

.callout strong { display: block; margin-bottom: 5px; }

/* ==========================================================================
   Tables
   ========================================================================== */
table {
    width: 100%;
    border-collapse: collapse;
    margin: var(--spacing-lg) 0;
    font-size: 14px;
}

th, td {
    padding: 12px 15px;
    text-align: left;
    border-bottom: 1px solid var(--ds-gray-light);
}

th {
    background: var(--ds-bg);
    font-weight: 600;
}

/* ==========================================================================
   Documentation Sidebar
   ========================================================================== */
.sidebar {
    width: 260px;
    background: var(--ds-white);
    border-right: 1px solid var(--ds-gray-light);
    padding: var(--spacing-lg) 0;
    position: sticky;
    top: 60px;
    height: calc(100vh - 60px);
    overflow-y: auto;
}

.sidebar-section { margin-bottom: var(--spacing-lg); }

.sidebar-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--ds-gray);
    padding: 0 var(--spacing-lg);
    margin-bottom: var(--spacing-sm);
}

.sidebar-nav { list-style: none; }
.sidebar-nav a {
    display: block;
    padding: var(--spacing-sm) var(--spacing-lg);
    font-size: 14px;
    color: var(--ds-navy);
    border-left: 3px solid transparent;
}
.sidebar-nav a:hover { background: var(--ds-bg); text-decoration: none; }
.sidebar-nav a.active {
    border-left-color: var(--ds-blue-primary);
    background: var(--ds-bg);
    font-weight: 600;
}

/* ==========================================================================
   Footer
   ========================================================================== */
.footer {
    text-align: center;
    padding: var(--spacing-xl);
    color: var(--ds-gray);
    font-size: 12px;
    border-top: 1px solid var(--ds-gray-light);
    margin-top: var(--spacing-xl);
}

/* ==========================================================================
   Admin Dashboard Specific
   ========================================================================== */
.service-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: var(--spacing-lg);
}

.service-card {
    background: var(--ds-white);
    border-radius: 8px;
    padding: var(--spacing-lg);
    border-left: 4px solid var(--ds-gray);
}

.service-card.healthy { border-left-color: var(--ds-success); }
.service-card.degraded { border-left-color: var(--ds-warning); }
.service-card.error { border-left-color: var(--ds-error); }

/* ==========================================================================
   STAC Explorer Specific
   ========================================================================== */
.split-layout {
    display: grid;
    grid-template-columns: 400px 1fr;
    height: calc(100vh - 60px);
}

.explorer-panel {
    overflow-y: auto;
    padding: var(--spacing-lg);
    background: var(--ds-white);
    border-right: 1px solid var(--ds-gray-light);
}

.map-container {
    height: 100%;
}

#map { height: 100%; width: 100%; }

/* JSON viewer */
.json-viewer {
    background: var(--ds-code-bg);
    color: var(--ds-code-text);
    padding: var(--spacing-md);
    border-radius: 6px;
    font-family: var(--font-mono);
    font-size: 12px;
    max-height: 400px;
    overflow: auto;
}

/* ==========================================================================
   Responsive
   ========================================================================== */
@media (max-width: 768px) {
    .navbar { flex-direction: column; gap: var(--spacing-sm); }
    .navbar-links { flex-wrap: wrap; justify-content: center; }

    .layout-sidebar { flex-direction: column; }
    .sidebar { width: 100%; height: auto; position: static; }

    .split-layout { grid-template-columns: 1fr; }
    .explorer-panel { max-height: 50vh; }
}
```

---

### Phase 5: JavaScript Utilities (`static/js/common.js`)

```javascript
/**
 * Common JavaScript utilities for geotiler UI
 */

/**
 * Set URL in a form input field
 * @param {string} url - The URL to set
 * @param {string} inputId - The input element ID
 */
function setUrl(url, inputId) {
    const input = document.getElementById(inputId);
    if (input) {
        input.value = url;
        input.focus();
    }
}

/**
 * Navigate to info endpoint with URL parameter
 * @param {string} baseEndpoint - e.g., '/cog/info', '/xarray/info'
 * @param {string} inputId - The input element ID containing the URL
 * @param {object} extraParams - Additional query parameters
 */
function getInfo(baseEndpoint, inputId, extraParams = {}) {
    const input = document.getElementById(inputId);
    const url = input?.value?.trim();

    if (!url) {
        alert('Please enter a URL');
        return;
    }

    const params = new URLSearchParams({ url, ...extraParams });
    window.location.href = `${baseEndpoint}?${params}`;
}

/**
 * Navigate to tile viewer
 * @param {string} baseEndpoint - e.g., '/cog', '/xarray'
 * @param {string} inputId - The input element ID containing the URL
 */
function viewTiles(baseEndpoint, inputId) {
    const input = document.getElementById(inputId);
    const url = input?.value?.trim();

    if (!url) {
        alert('Please enter a URL');
        return;
    }

    const encodedUrl = encodeURIComponent(url);
    window.location.href = `${baseEndpoint}/WebMercatorQuad/map?url=${encodedUrl}`;
}

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 * @param {HTMLElement} button - Button element for feedback
 */
async function copyToClipboard(text, button) {
    try {
        await navigator.clipboard.writeText(text);
        const originalText = button.textContent;
        button.textContent = 'Copied!';
        setTimeout(() => { button.textContent = originalText; }, 2000);
    } catch (err) {
        console.error('Copy failed:', err);
    }
}

/**
 * Format JSON for display
 * @param {object} obj - Object to format
 * @returns {string} - Formatted JSON string
 */
function formatJson(obj) {
    return JSON.stringify(obj, null, 2);
}

/**
 * Debounce function for search inputs
 * @param {function} func - Function to debounce
 * @param {number} wait - Wait time in ms
 */
function debounce(func, wait = 300) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
```

---

### Phase 6: FastAPI Integration

#### 6.1 Static Files & Templates Setup (`app.py`)

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Get base directory
BASE_DIR = Path(__file__).resolve().parent

def create_app() -> FastAPI:
    app = FastAPI(...)

    # Mount static files
    app.mount(
        "/static",
        StaticFiles(directory=BASE_DIR / "static"),
        name="static"
    )

    # ... rest of app setup

    return app

# Create templates instance (shared across routers)
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Add global template context
templates.env.globals.update({
    "version": __version__,
    "settings": settings,
})
```

#### 6.2 Consolidated Pages Router (`routers/pages.py`)

```python
"""
UI Pages Router

Serves all HTML pages using Jinja2 templates.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from geotiler import __version__
from geotiler.config import settings
from geotiler.app import templates

router = APIRouter(tags=["Pages"], include_in_schema=False)


def _context(request: Request, **kwargs) -> dict:
    """Build template context with common variables."""
    return {
        "request": request,
        "version": __version__,
        "stac_api_enabled": settings.enable_stac_api,
        "tipg_enabled": settings.enable_tipg,
        **kwargs
    }


# =============================================================================
# Landing Pages
# =============================================================================

@router.get("/", response_class=HTMLResponse)
async def admin_page(request: Request):
    """Admin dashboard."""
    # Fetch health data for display
    # ...
    return templates.TemplateResponse(
        "pages/admin/index.html",
        _context(request, active="admin", health=health_data)
    )


@router.get("/cog/", response_class=HTMLResponse)
async def cog_landing(request: Request):
    """COG landing page."""
    return templates.TemplateResponse(
        "pages/cog/index.html",
        _context(
            request,
            active="cog",
            sample_urls=settings.sample_cog_urls
        )
    )


@router.get("/xarray/", response_class=HTMLResponse)
async def xarray_landing(request: Request):
    """Zarr/NetCDF landing page."""
    return templates.TemplateResponse(
        "pages/xarray/index.html",
        _context(
            request,
            active="xarray",
            sample_urls=settings.sample_zarr_urls
        )
    )


@router.get("/searches/", response_class=HTMLResponse)
async def searches_landing(request: Request):
    """pgSTAC searches landing page."""
    return templates.TemplateResponse(
        "pages/searches/index.html",
        _context(request, active="searches")
    )


@router.get("/stac/", response_class=HTMLResponse)
async def stac_explorer(request: Request):
    """STAC explorer with map."""
    return templates.TemplateResponse(
        "pages/stac/explorer.html",
        _context(
            request,
            active="stac",
            sample_collections=settings.sample_stac_collections
        )
    )


# =============================================================================
# Documentation Guide
# =============================================================================

@router.get("/guide/", response_class=HTMLResponse)
async def guide_index(request: Request):
    """Documentation home."""
    return templates.TemplateResponse(
        "pages/guide/index.html",
        _context(request, active="guide", guide_active="/guide/")
    )


@router.get("/guide/authentication", response_class=HTMLResponse)
async def guide_authentication(request: Request):
    """Authentication guide."""
    return templates.TemplateResponse(
        "pages/guide/authentication.html",
        _context(request, active="guide", guide_active="/guide/authentication")
    )


@router.get("/guide/quick-start", response_class=HTMLResponse)
async def guide_quick_start(request: Request):
    """Quick start guide."""
    return templates.TemplateResponse(
        "pages/guide/quick-start.html",
        _context(request, active="guide", guide_active="/guide/quick-start")
    )


# ... additional guide routes ...
```

---

### Phase 7: Example Page Template

#### 7.1 COG Landing Page (`templates/pages/cog/index.html`)

```html
{% extends "base.html" %}

{% block title %}COG Tiles{% endblock %}

{% block content %}
<div class="page-header">
    <h1>Cloud Optimized GeoTIFF</h1>
    <p class="subtitle">Access raster tiles from any COG via HTTP range requests</p>
</div>

<div class="form-section">
    <div class="form-group">
        <label class="form-label" for="cog-url">COG URL</label>
        <input
            type="text"
            id="cog-url"
            class="form-input"
            placeholder="https://example.com/file.tif or /vsiaz/container/file.tif"
        >
    </div>

    <div class="btn-group">
        <button class="btn btn-primary" onclick="getInfo('/cog/info', 'cog-url')">
            Get Info
        </button>
        <button class="btn btn-secondary" onclick="viewTiles('/cog', 'cog-url')">
            View Tiles
        </button>
    </div>
</div>

{% if sample_urls %}
<div class="samples-section">
    <h2>Sample Datasets</h2>
    <p>Click a sample to populate the URL field:</p>

    <div class="card-grid">
        {% for sample in sample_urls %}
        {% include "components/cards.html" %}
        {{ sample_url_card(sample, 'cog-url') }}
        {% endfor %}
    </div>
</div>
{% endif %}

<div class="endpoints-section">
    <h2>Available Endpoints</h2>

    <table>
        <thead>
            <tr>
                <th>Endpoint</th>
                <th>Description</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><code>GET /cog/info</code></td>
                <td>Get COG metadata (bounds, CRS, bands)</td>
            </tr>
            <tr>
                <td><code>GET /cog/tiles/{tms}/{z}/{x}/{y}</code></td>
                <td>Get raster tile (PNG/WebP)</td>
            </tr>
            <tr>
                <td><code>GET /cog/statistics</code></td>
                <td>Get band statistics</td>
            </tr>
            <tr>
                <td><code>GET /cog/point/{lon},{lat}</code></td>
                <td>Query pixel value at coordinate</td>
            </tr>
        </tbody>
    </table>
</div>
{% endblock %}
```

---

### Phase 8: Migration Checklist

#### 8.1 Pre-Migration

- [ ] Create `geotiler/static/` directory
- [ ] Create `geotiler/templates/` directory structure
- [ ] Add `jinja2` and `aiofiles` to dependencies (if not present)
- [ ] Update `config.py` with sample URL settings
- [ ] Create consolidated `styles.css`
- [ ] Create `common.js`
- [ ] Create `base.html` template
- [ ] Create component templates (navbar, footer, cards, etc.)

#### 8.2 Page Migration (one at a time)

For each page:
1. [ ] Create template in `templates/pages/`
2. [ ] Add route in `routers/pages.py`
3. [ ] Test new template renders correctly
4. [ ] Remove old router file
5. [ ] Update `app.py` imports

Migration order:
1. [ ] `cog_landing.py` → `templates/pages/cog/index.html`
2. [ ] `xarray_landing.py` → `templates/pages/xarray/index.html`
3. [ ] `searches_landing.py` → `templates/pages/searches/index.html`
4. [ ] `admin.py` → `templates/pages/admin/index.html`
5. [ ] `stac_explorer.py` → `templates/pages/stac/explorer.html`
6. [ ] `docs_guide.py` → `templates/pages/guide/*.html`

#### 8.3 Post-Migration

- [ ] Delete old router files
- [ ] Update `app.py` to use new `pages.py` router
- [ ] Add sample URL environment variables to deployment docs
- [ ] Update `APP_REVIEW.md` to mark issue #8 and #11 as resolved
- [ ] Test all pages work correctly
- [ ] Verify static file caching headers
- [ ] Deploy and verify in production

---

### Phase 9: Environment Variable Documentation

Add to `docs/WIKI.md` or create `docs/UI_CONFIGURATION.md`:

```markdown
## UI Configuration

### Sample URLs

The landing pages display sample datasets that users can click to populate the URL field.
Configure these via environment variables using JSON arrays.

#### COG Samples

```bash
SAMPLE_COG_URLS='[
  {
    "label": "Swiss Terrain (SRTM)",
    "url": "https://data.geo.admin.ch/.../swissalti3d.tif",
    "description": "High-resolution Swiss elevation data"
  },
  {
    "label": "Sentinel-2 RGB",
    "url": "https://sentinel-cogs.s3.amazonaws.com/.../TCI.tif",
    "description": "True color satellite imagery"
  }
]'
```

#### Zarr/NetCDF Samples

```bash
SAMPLE_ZARR_URLS='[
  {
    "label": "ERA5 Temperature",
    "url": "https://storage.../era5.zarr",
    "variable": "t2m",
    "description": "Global 2m temperature reanalysis"
  }
]'
```

#### STAC Collection Highlights

```bash
SAMPLE_STAC_COLLECTIONS='[
  {
    "id": "flood-risk",
    "label": "Flood Risk Maps",
    "description": "Flood depth and extent models for East Africa"
  }
]'
```

### Disabling Sample URLs

To hide the samples section, set the variable to an empty array:

```bash
SAMPLE_COG_URLS='[]'
```
```

---

### Estimated Effort

| Phase | Tasks | Effort |
|-------|-------|--------|
| 1. Structure | Create directories, move files | 30 min |
| 2. Config | Add sample URL settings | 30 min |
| 3. Base Template | Create base.html, components | 1 hour |
| 4. CSS | Consolidate into styles.css | 1.5 hours |
| 5. JavaScript | Create common.js | 30 min |
| 6. FastAPI Setup | Static files, templates | 30 min |
| 7. Page Migration | 6 pages × 30 min each | 3 hours |
| 8. Testing | Verify all pages, responsive | 1 hour |
| 9. Documentation | Update docs, env vars | 30 min |

**Total Estimated: ~9 hours**

---

### Success Criteria

1. **All existing pages render identically** (visual regression check)
2. **CSS file is cached** (check browser network tab)
3. **No hardcoded URLs** in templates (grep verification)
4. **Sample URLs configurable** via environment variables
5. **Lighthouse score maintained** (performance, accessibility)
6. **All tests pass** (if any exist for UI)
7. **Mobile responsive** (test on narrow viewport)

---

## Documentation Review Findings

### docs/WIKI.md
Comprehensive API reference covering all endpoints. Version noted as 0.3.1 (outdated - actual is 0.7.14.0). Excellent coverage of:
- URL formats for COG, Zarr, and STAC data
- Query parameters and colormaps
- Error reference with solutions
- Test data locations

**Recommendation:** Update version number in WIKI.md to match current release.

### docs/QA_DEPLOYMENT.md
Enterprise-grade deployment guide with:
- Three PostgreSQL auth modes (Managed Identity, Key Vault, password)
- RBAC permission setup for storage and database
- Detailed troubleshooting for common issues
- Important note about `ALTER DEFAULT PRIVILEGES` per-grantor gotcha

**Recommendation:** None - excellent documentation.

### docs/xarray.md
Thorough guide for Zarr/NetCDF support including:
- Planetary Computer integration
- Required parameters (`bidx`, `decode_times`)
- Verified URL patterns from production testing
- Two implementation approaches (parallel routes vs unified pgSTAC)

**Recommendation:** Consider consolidating common errors into WIKI.md error reference.

### Architecture Summary

```
rmhtitiler (v0.7.14.0)
├── Tile Endpoints
│   ├── /cog/*        - COG tiles via rio-tiler/GDAL
│   ├── /xarray/*     - Zarr/NetCDF via xarray
│   ├── /pc/*         - Planetary Computer climate data
│   └── /searches/*   - pgSTAC dynamic mosaics
├── Vector Endpoints
│   └── /vector/*     - TiPG OGC Features + MVT tiles
├── UI Pages
│   ├── /             - Admin dashboard
│   ├── /cog/         - COG landing page
│   ├── /xarray/      - Zarr landing page
│   ├── /searches/    - pgSTAC landing page
│   ├── /stac/        - STAC explorer (Leaflet map)
│   └── /guide/*      - Documentation guides
├── Health Endpoints
│   ├── /health       - Full diagnostics
│   ├── /livez        - Liveness probe
│   └── /readyz       - Readiness probe
└── Authentication
    ├── Azure Managed Identity (storage)
    ├── PostgreSQL OAuth (database)
    └── Planetary Computer SAS tokens
```

---

## Next Steps / Recommended Plan

### Completed (6 of 12)
1. ~~**Complete Jinja2 migration**~~ ✅ DONE - All pages migrated
2. ~~**Fix sync blocking (#1)**~~ ✅ DONE - Uses `asyncio.to_thread()` for Azure SDK calls
3. ~~**Fix error swallowing (#6)**~~ ✅ DONE - Returns `(result, error)` tuples
4. ~~**Externalize sample URLs (#11)**~~ ✅ DONE - Completed via Jinja2 migration
5. ~~**Fix threading lock (#4)**~~ ✅ DONE - Added `asyncio.Lock` for async callers
6. ~~**Fix CORS (#5)**~~ ✅ DONE - Removed, handled by infrastructure

### Short-term (Next Sprint)
7. **Update WIKI.md version** - Change 0.3.1 to 0.7.16.0

### Medium-term (Backlog)
8. **Refactor global state (#2)** - Use FastAPI dependency injection (recommended for handoff)
9. **Break up verbose_diagnostics (#7)** - Split into smaller testable functions

### Low Priority (Tech Debt Cleanup)
10. **Add proper type annotations (#12)**
11. **Reduce logging noise (#10)** - Move verbose logs to DEBUG level
12. **Mixed sync/async DB (#9)** - Consider unifying on async pool

---

## File Inventory (Key Files)

| File | Lines | Purpose |
|------|-------|---------|
| `geotiler/app.py` | ~300 | Main FastAPI app, lifespan, router mounting |
| `geotiler/config.py` | ~150 | Pydantic settings, feature flags |
| `geotiler/routers/health.py` | ~100 | Health probe endpoints |
| `geotiler/routers/vector.py` | ~250 | TiPG integration |
| `geotiler/routers/diagnostics.py` | ~1000 | Verbose diagnostics (needs refactor) |
| `geotiler/auth/storage.py` | ~150 | Azure storage OAuth |
| `geotiler/middleware/azure_auth.py` | ~50 | Per-request OAuth injection |

---

**Last Updated:** 2026-01-21
**Next Review:** After global state refactor (#2)

---

## Implementation Plan: Global Mutable State Refactor (#2)

**Status:** TODO
**Priority:** Medium (recommended for handoff readiness)
**Effort:** ~2-3 hours
**Goal:** Eliminate module-level mutable globals, use explicit dependency injection

### Why This Matters

This refactor makes the codebase:
1. **Self-documenting** - Function signatures show all dependencies
2. **Testable** - No global state leaking between tests
3. **Handoff-ready** - New developers understand code without tribal knowledge
4. **Maintainable** - No hidden initialization order requirements

### Current State (Problems)

Three files use module-level mutable globals:

```python
# geotiler/services/background.py:20
_app: "FastAPI" = None  # Set via set_app_reference()

# geotiler/services/database.py:17
_app_state: Optional[Any] = None  # Set via set_app_state()

# geotiler/routers/vector.py:97
tipg_startup_state = TiPGStartupState()  # Mutable singleton
```

### Target State (Solution)

- No module-level mutable globals
- All dependencies passed explicitly or via FastAPI's `Depends()`
- State stored in `app.state` (FastAPI's blessed location)

---

### Phase 1: Refactor `background.py`

**File:** `geotiler/services/background.py`

**Current:**
```python
_app: "FastAPI" = None

def set_app_reference(app: "FastAPI") -> None:
    global _app
    _app = app

async def token_refresh_background_task():
    while True:
        await asyncio.sleep(BACKGROUND_REFRESH_INTERVAL_SECS)
        if settings.use_azure_auth:
            await refresh_storage_token_async()
        if settings.postgres_auth_mode == "managed_identity":
            await _refresh_postgres_with_pool_recreation()

async def _refresh_postgres_with_pool_recreation():
    if not _app:
        logger.warning("App reference not set")
        return
    # ... uses _app
```

**Target:**
```python
# No globals!

async def token_refresh_background_task(app: "FastAPI"):
    """Background task - receives app explicitly."""
    while True:
        await asyncio.sleep(BACKGROUND_REFRESH_INTERVAL_SECS)
        if settings.use_azure_auth:
            await refresh_storage_token_async()
        if settings.postgres_auth_mode == "managed_identity":
            await _refresh_postgres_with_pool_recreation(app)

async def _refresh_postgres_with_pool_recreation(app: "FastAPI"):
    """Refresh pools - app is explicit parameter."""
    # ... uses app parameter

def start_token_refresh(app: "FastAPI") -> asyncio.Task:
    """Start background task, passing app explicitly."""
    task = asyncio.create_task(token_refresh_background_task(app))
    return task
```

**Changes:**
- [ ] Remove `_app` global variable
- [ ] Remove `set_app_reference()` function
- [ ] Add `app` parameter to `token_refresh_background_task()`
- [ ] Add `app` parameter to `_refresh_postgres_with_pool_recreation()`
- [ ] Update `start_token_refresh()` to pass app to task

---

### Phase 2: Refactor `database.py`

**File:** `geotiler/services/database.py`

**Current:**
```python
_app_state: Optional[Any] = None

def set_app_state(state) -> None:
    global _app_state
    _app_state = state

def get_app_state():
    return _app_state

def get_db_pool():
    if not _app_state:
        return None
    return getattr(_app_state, "dbpool", None)
```

**Target:**
```python
# No globals!

def get_app_state(request: Request):
    """FastAPI dependency - get app state from request."""
    return request.app.state

def get_db_pool(request: Request):
    """FastAPI dependency - get database pool."""
    return getattr(request.app.state, "dbpool", None)

# For non-request contexts (health checks, diagnostics):
def get_db_pool_from_app(app: FastAPI):
    """Get database pool from app instance."""
    return getattr(app.state, "dbpool", None)
```

**Changes:**
- [ ] Remove `_app_state` global variable
- [ ] Remove `set_app_state()` function
- [ ] Convert `get_app_state()` to FastAPI dependency (takes `Request`)
- [ ] Convert `get_db_pool()` to FastAPI dependency
- [ ] Add `get_db_pool_from_app()` for non-request contexts
- [ ] Update all callers to use new signatures

**Callers to Update:**
- `geotiler/routers/health.py` - uses `get_db_pool()`
- `geotiler/routers/diagnostics.py` - uses `get_app_state()`
- Any other files importing from `database.py`

---

### Phase 3: Refactor `vector.py`

**File:** `geotiler/routers/vector.py`

**Current:**
```python
tipg_startup_state = TiPGStartupState()  # Module-level mutable

async def startup_tipg(app: FastAPI):
    tipg_startup_state.started = True
    # ...
```

**Target:**
```python
# No module-level mutable state!

async def startup_tipg(app: FastAPI):
    """Initialize TiPG, store state in app.state."""
    app.state.tipg = TiPGStartupState()
    app.state.tipg.started = True
    # ...

def get_tipg_state(request: Request) -> TiPGStartupState:
    """FastAPI dependency - get TiPG state."""
    return getattr(request.app.state, "tipg", None)
```

**Changes:**
- [ ] Remove `tipg_startup_state` module-level variable
- [ ] Store TiPG state in `app.state.tipg` during startup
- [ ] Add `get_tipg_state()` dependency for handlers that need it
- [ ] Update `refresh_tipg_pool()` to take app parameter

---

### Phase 4: Update `app.py` Lifespan

**File:** `geotiler/app.py`

**Current:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... setup ...
    set_app_reference(app)  # Sets global
    set_app_state(app.state)  # Sets global
    background_task = start_token_refresh(app)
    yield
    # ... cleanup ...
```

**Target:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... setup ...
    # No more set_app_reference() or set_app_state() calls!
    background_task = start_token_refresh(app)  # Pass app directly
    yield
    # ... cleanup ...
```

**Changes:**
- [ ] Remove `set_app_reference(app)` call
- [ ] Remove `set_app_state(app.state)` call
- [ ] Verify all state is stored in `app.state`

---

### Phase 5: Update Imports and Callers

Search for all usages of removed functions:

```bash
# Find all usages
grep -r "set_app_reference" geotiler/
grep -r "set_app_state" geotiler/
grep -r "get_app_state" geotiler/
grep -r "get_db_pool" geotiler/
grep -r "tipg_startup_state" geotiler/
```

For each caller:
- [ ] Update to use new dependency injection pattern
- [ ] For request handlers: use `Depends(get_db_pool)`
- [ ] For non-request code: pass `app` explicitly

**Example handler update:**

```python
# Before
@router.get("/health")
async def health():
    pool = get_db_pool()  # Uses global
    # ...

# After
@router.get("/health")
async def health(request: Request):
    pool = get_db_pool(request)  # Explicit dependency
    # ...

# Or with Depends:
@router.get("/health")
async def health(pool = Depends(get_db_pool)):
    # pool injected automatically
    # ...
```

---

### Phase 6: Testing & Verification

- [ ] Run syntax check: `python -m py_compile geotiler/**/*.py`
- [ ] Search for remaining globals: `grep -r "global " geotiler/`
- [ ] Verify no `_app` or `_app_state` references remain
- [ ] Test locally: `uvicorn geotiler.app:app --reload`
- [ ] Test health endpoint: `curl localhost:8000/health`
- [ ] Test background refresh logs (wait for refresh interval or reduce it temporarily)
- [ ] Deploy to staging and verify

---

### Files Modified Summary

| File | Changes |
|------|---------|
| `geotiler/services/background.py` | Remove `_app` global, add `app` params |
| `geotiler/services/database.py` | Remove `_app_state` global, convert to deps |
| `geotiler/routers/vector.py` | Move `tipg_startup_state` to `app.state` |
| `geotiler/app.py` | Remove `set_*` calls |
| `geotiler/routers/health.py` | Update to use dependencies |
| `geotiler/routers/diagnostics.py` | Update to use dependencies |

---

### Success Criteria

1. **No module-level mutable globals** - `grep -r "^_" geotiler/` shows no mutable state
2. **No `global` keyword** - `grep -r "global " geotiler/` returns nothing
3. **All tests pass** (if any exist)
4. **Health endpoint works** - Returns valid JSON with database status
5. **Background refresh works** - Logs show token refresh at interval
6. **TiPG works** - `/vector/collections` returns data

---

### Rollback Plan

If issues arise:
1. `git stash` or `git checkout .` to revert changes
2. Redeploy previous working version

Keep changes atomic - commit after each phase works.
