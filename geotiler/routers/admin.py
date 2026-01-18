"""
Admin console and API info endpoints.

Provides:
- GET / - HTML admin dashboard with health visualization
- GET /api - JSON API information
- GET /_health-fragment - HTMX partial for auto-refresh

Design system adapted from rmhgeoapi web interfaces.
"""

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

from geotiler import __version__
from geotiler.config import settings
from geotiler.routers.health import health as get_health_data, _get_hardware_info

router = APIRouter(tags=["Admin"])

# =============================================================================
# CSS DESIGN SYSTEM (adapted from rmhgeoapi)
# =============================================================================

CSS = """
:root {
  --ds-blue-primary: #0071BC;
  --ds-blue-dark: #245AAD;
  --ds-navy: #053657;
  --ds-cyan: #00A3DA;
  --ds-gold: #FFC14D;
  --ds-gray: #626F86;
  --ds-gray-light: #e9ecef;
  --ds-bg: #f8f9fa;

  /* Status colors */
  --ds-status-healthy: #059669;
  --ds-status-healthy-bg: #d1fae5;
  --ds-status-warning: #d97706;
  --ds-status-warning-bg: #fef3c7;
  --ds-status-error: #dc2626;
  --ds-status-error-bg: #fee2e2;
  --ds-status-disabled: #6b7280;
  --ds-status-disabled-bg: #f3f4f6;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: "Open Sans", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--ds-navy);
  background-color: var(--ds-bg);
}

a {
  color: var(--ds-blue-primary);
  text-decoration: none;
}

a:hover {
  color: var(--ds-cyan);
  text-decoration: underline;
}

/* Navbar */
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 30px;
  background: white;
  border-bottom: 3px solid var(--ds-blue-primary);
  position: sticky;
  top: 0;
  z-index: 100;
}

.navbar-brand {
  font-size: 18px;
  font-weight: 700;
  color: var(--ds-navy);
}

.navbar-brand span {
  color: var(--ds-gray);
  font-weight: 400;
  font-size: 14px;
}

.navbar-links {
  display: flex;
  gap: 20px;
}

.navbar-links a {
  color: var(--ds-blue-primary);
  font-weight: 500;
  padding: 5px 10px;
  border-radius: 4px;
  transition: background 0.2s;
}

.navbar-links a:hover {
  background: var(--ds-gray-light);
  text-decoration: none;
}

/* Container */
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 30px;
}

/* Section headers */
.section-header {
  font-size: 16px;
  font-weight: 700;
  color: var(--ds-navy);
  margin-bottom: 15px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--ds-gray-light);
}

/* Status Banner */
.status-banner {
  background: white;
  border-radius: 8px;
  padding: 20px 25px;
  margin-bottom: 25px;
  border-left: 4px solid var(--ds-blue-primary);
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.status-banner-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
}

.status-banner-title {
  font-size: 18px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 10px;
}

.auto-refresh-label {
  font-size: 12px;
  color: var(--ds-gray);
  display: flex;
  align-items: center;
  gap: 5px;
}

.auto-refresh-label input {
  cursor: pointer;
}

.stats-row {
  display: flex;
  gap: 40px;
  flex-wrap: wrap;
}

.stat-item {
  text-align: center;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--ds-navy);
}

.stat-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--ds-gray);
}

/* Status badges */
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.status-healthy {
  background: var(--ds-status-healthy-bg);
  color: var(--ds-status-healthy);
}

.status-degraded {
  background: var(--ds-status-warning-bg);
  color: var(--ds-status-warning);
}

.status-unavailable, .status-fail {
  background: var(--ds-status-error-bg);
  color: var(--ds-status-error);
}

.status-disabled {
  background: var(--ds-status-disabled-bg);
  color: var(--ds-status-disabled);
}

.status-ok {
  background: var(--ds-status-healthy-bg);
  color: var(--ds-status-healthy);
}

.status-warning {
  background: var(--ds-status-warning-bg);
  color: var(--ds-status-warning);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

/* Cards Grid */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 15px;
  margin-bottom: 25px;
}

.card {
  background: white;
  border-radius: 8px;
  padding: 18px;
  border-left: 4px solid var(--ds-blue-primary);
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  transition: transform 0.2s, border-color 0.2s;
}

.card:hover {
  transform: translateY(-2px);
  border-color: var(--ds-cyan);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}

.card-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--ds-navy);
}

.card-description {
  font-size: 12px;
  color: var(--ds-gray);
  margin-bottom: 10px;
  line-height: 1.4;
}

.card-endpoints {
  font-size: 11px;
  color: var(--ds-gray);
}

.card-endpoints code {
  background: var(--ds-gray-light);
  padding: 2px 5px;
  border-radius: 3px;
  font-family: monospace;
}

.card-link {
  display: block;
  text-decoration: none;
  color: inherit;
}

.card-link:hover {
  text-decoration: none;
}

/* Dependency cards */
.dep-card {
  background: white;
  border-radius: 8px;
  padding: 15px 18px;
  border-left: 4px solid var(--ds-gray-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.dep-card.dep-ok {
  border-left-color: var(--ds-status-healthy);
}

.dep-card.dep-warning {
  border-left-color: var(--ds-status-warning);
}

.dep-card.dep-fail {
  border-left-color: var(--ds-status-error);
}

.dep-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 5px;
}

.dep-name {
  font-weight: 600;
  font-size: 13px;
}

.dep-detail {
  font-size: 12px;
  color: var(--ds-gray);
}

/* Config section */
.config-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  background: white;
  border-radius: 8px;
  padding: 18px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.config-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.config-label {
  font-size: 12px;
  color: var(--ds-gray);
}

.config-value {
  font-size: 12px;
  font-weight: 600;
}

.config-on {
  color: var(--ds-status-healthy);
}

.config-off {
  color: var(--ds-status-disabled);
}

/* Issues section */
.issues-section {
  background: var(--ds-status-error-bg);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 25px;
  border-left: 4px solid var(--ds-status-error);
}

.issues-header {
  font-weight: 700;
  color: var(--ds-status-error);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.issues-list {
  list-style: none;
}

.issues-list li {
  font-size: 13px;
  color: var(--ds-status-error);
  padding: 4px 0;
}

.issues-list li::before {
  content: "\\26A0";
  margin-right: 8px;
}

/* HTMX loading */
.htmx-indicator {
  display: none;
}

.htmx-request .htmx-indicator {
  display: inline-block;
}

.htmx-request.htmx-indicator {
  display: inline-block;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--ds-gray-light);
  border-top-color: var(--ds-blue-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Footer */
.footer {
  text-align: center;
  padding: 20px;
  color: var(--ds-gray);
  font-size: 12px;
}

.footer a {
  color: var(--ds-blue-primary);
}
"""


# =============================================================================
# HTML GENERATION FUNCTIONS
# =============================================================================

def _render_status_badge(status: str) -> str:
    """Render a status badge with appropriate styling."""
    status_lower = status.lower()
    return f'''<span class="status-badge status-{status_lower}">
        <span class="status-dot"></span>{status}
    </span>'''


def _render_service_card(name: str, data: dict) -> str:
    """Render a service card."""
    status = data.get("status", "unknown")
    description = data.get("description", "")
    endpoints = data.get("endpoints", [])
    available = data.get("available", False)
    disabled_reason = data.get("disabled_reason")

    # Determine if this service has a landing page link
    landing_pages = {
        "tipg": "/vector",
        "stac_api": "/stac",
    }
    link = landing_pages.get(name)

    # Build endpoints display
    endpoints_html = ""
    if endpoints:
        first_endpoint = endpoints[0] if endpoints else ""
        endpoints_html = f'<div class="card-endpoints"><code>{first_endpoint}</code></div>'
    elif disabled_reason:
        endpoints_html = f'<div class="card-endpoints" style="color: var(--ds-status-disabled);">{disabled_reason}</div>'

    badge = _render_status_badge(status)

    card_content = f'''
        <div class="card-header">
            <span class="card-title">{name.upper().replace("_", " ")}</span>
            {badge}
        </div>
        <div class="card-description">{description}</div>
        {endpoints_html}
    '''

    if link and available:
        return f'<a href="{link}" class="card card-link">{card_content}</a>'
    else:
        return f'<div class="card">{card_content}</div>'


def _render_dependency_card(name: str, data: dict) -> str:
    """Render a dependency card."""
    status = data.get("status", "unknown")
    status_class = "dep-ok" if status == "ok" else ("dep-warning" if status == "warning" else "dep-fail")

    # Build detail string based on dependency type
    detail = ""
    if name == "database":
        ping_ms = data.get("ping_time_ms")
        if ping_ms is not None:
            detail = f"{ping_ms:.0f}ms ping"
        elif data.get("error"):
            detail = data["error"][:40] + "..." if len(data.get("error", "")) > 40 else data.get("error", "")
    elif "expires_in_seconds" in data:
        ttl = data["expires_in_seconds"]
        if ttl > 3600:
            detail = f"{ttl // 3600}h {(ttl % 3600) // 60}m TTL"
        elif ttl > 60:
            detail = f"{ttl // 60}m TTL"
        else:
            detail = f"{ttl}s TTL"
    elif data.get("note"):
        detail = data["note"]

    badge = _render_status_badge(status)

    # Pretty name
    pretty_names = {
        "database": "Database",
        "storage_oauth": "Storage OAuth",
        "postgres_oauth": "PostgreSQL OAuth",
    }
    pretty_name = pretty_names.get(name, name)

    return f'''<div class="dep-card {status_class}">
        <div class="dep-header">
            <span class="dep-name">{pretty_name}</span>
            {badge}
        </div>
        <div class="dep-detail">{detail}</div>
    </div>'''


def _render_config_item(label: str, value: bool) -> str:
    """Render a config item."""
    value_class = "config-on" if value else "config-off"
    value_text = "ON" if value else "OFF"
    return f'''<div class="config-item">
        <span class="config-label">{label}:</span>
        <span class="config-value {value_class}">{value_text}</span>
    </div>'''


def _render_health_fragment(health_data: dict) -> str:
    """Render the health fragment (status banner + services + deps + issues)."""
    status = health_data.get("status", "unknown")
    services = health_data.get("services", {})
    dependencies = health_data.get("dependencies", {})
    hardware = health_data.get("hardware", {})
    issues = health_data.get("issues") or []
    config = health_data.get("config", {})

    # Stats
    memory_pct = hardware.get("ram_utilization_percent", 0)
    cpu_pct = hardware.get("cpu_utilization_percent", 0)

    # Status banner
    status_banner = f'''
    <div class="status-banner">
        <div class="status-banner-header">
            <div class="status-banner-title">
                System Status: {_render_status_badge(status)}
            </div>
            <label class="auto-refresh-label">
                <input type="checkbox" id="auto-refresh" checked onchange="toggleAutoRefresh()">
                Auto-refresh (30s)
                <span class="htmx-indicator spinner"></span>
            </label>
        </div>
        <div class="stats-row">
            <div class="stat-item">
                <div class="stat-value">{__version__}</div>
                <div class="stat-label">Version</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{memory_pct:.0f}%</div>
                <div class="stat-label">Memory</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{cpu_pct:.0f}%</div>
                <div class="stat-label">CPU</div>
            </div>
        </div>
    </div>
    '''

    # Issues section (only if there are issues)
    issues_html = ""
    if issues:
        issues_items = "".join(f"<li>{issue}</li>" for issue in issues)
        issues_html = f'''
        <div class="issues-section">
            <div class="issues-header">Issues Detected</div>
            <ul class="issues-list">{issues_items}</ul>
        </div>
        '''

    # Services grid
    services_cards = "".join(
        _render_service_card(name, data)
        for name, data in services.items()
    )
    services_html = f'''
    <div class="section-header">Services</div>
    <div class="cards-grid">{services_cards}</div>
    '''

    # Dependencies grid
    deps_cards = "".join(
        _render_dependency_card(name, data)
        for name, data in dependencies.items()
    )
    deps_html = f'''
    <div class="section-header">Dependencies</div>
    <div class="cards-grid">{deps_cards}</div>
    '''

    # Config section
    config_items = "".join([
        _render_config_item("Azure Auth", config.get("azure_auth_enabled", False)),
        _render_config_item("Local Mode", config.get("local_mode", False)),
        _render_config_item("TiPG", config.get("tipg_enabled", False)),
        _render_config_item("STAC API", config.get("stac_api_enabled", False)),
        _render_config_item("Planetary Computer", config.get("planetary_computer_enabled", False)),
    ])
    config_html = f'''
    <div class="section-header">Configuration</div>
    <div class="config-grid">{config_items}</div>
    '''

    return status_banner + issues_html + services_html + deps_html + config_html


def _render_full_page(health_data: dict) -> str:
    """Render the full admin console page."""
    health_fragment = _render_health_fragment(health_data)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>geotiler Admin Console</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <style>{CSS}</style>
</head>
<body>
    <nav class="navbar">
        <div class="navbar-brand">
            geotiler <span>v{__version__}</span>
        </div>
        <div class="navbar-links">
            <a href="/cog/">COG</a>
            <a href="/xarray/">XArray</a>
            <a href="/searches/">Searches</a>
            <a href="/vector">Vector</a>
            <a href="/stac/">STAC</a>
            <a href="/guide/">Guide</a>
            <a href="/docs">API Docs</a>
        </div>
    </nav>

    <div class="container">
        <div id="health-content"
             hx-get="/_health-fragment"
             hx-trigger="load, every 30s [document.getElementById('auto-refresh').checked]"
             hx-swap="innerHTML"
             hx-indicator=".htmx-indicator">
            {health_fragment}
        </div>
    </div>

    <footer class="footer">
        <a href="https://github.com/developmentseed/titiler">TiTiler</a> |
        <a href="https://github.com/developmentseed/titiler-pgstac">titiler-pgstac</a> |
        <a href="https://github.com/developmentseed/tipg">TiPG</a>
    </footer>

    <script>
        function toggleAutoRefresh() {{
            // HTMX will automatically respect the checkbox state in the trigger condition
            console.log('Auto-refresh:', document.getElementById('auto-refresh').checked);
        }}
    </script>
</body>
</html>'''


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_console():
    """
    Admin console dashboard with health visualization.

    Displays:
    - System status with memory/CPU stats
    - Service status cards (COG, XArray, pgSTAC, TiPG, STAC API)
    - Dependency status (database, OAuth tokens)
    - Configuration flags
    - Issues list (if any)

    Auto-refreshes every 30 seconds via HTMX.
    """
    # Get health data
    response = Response()
    health_data = await get_health_data(response)

    return _render_full_page(health_data)


@router.get("/_health-fragment", response_class=HTMLResponse, include_in_schema=False)
async def health_fragment():
    """
    HTMX partial for health status auto-refresh.

    Returns only the health content section (no navbar/footer).
    Called every 30 seconds when auto-refresh is enabled.
    """
    response = Response()
    health_data = await get_health_data(response)

    return _render_health_fragment(health_data)


@router.get("/api")
async def api_info():
    """
    JSON API information endpoint.

    Returns API metadata and available endpoints.
    """
    return {
        "title": "geotiler - TiTiler with Azure OAuth",
        "description": "Geospatial tile server with Azure Managed Identity authentication",
        "version": __version__,
        "auth_type": "OAuth Bearer Token (Managed Identity)",
        "endpoints": {
            "admin": "/",
            "liveness": "/livez",
            "readiness": "/readyz",
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc",
            "cog_info": "/cog/info",
            "cog_tiles": "/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "xarray_info": "/xarray/info",
            "xarray_tiles": "/xarray/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "search_list": "/searches",
            "search_register": "/searches/register",
            "search_tiles": "/searches/{search_id}/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "search_info": "/searches/{search_id}/info",
            "vector_collections": "/vector/collections",
            "vector_items": "/vector/collections/{collection_id}/items",
            "vector_tiles": "/vector/collections/{collection_id}/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "stac_root": "/stac",
            "stac_collections": "/stac/collections",
            "stac_search": "/stac/search",
        },
        "config": {
            "local_mode": settings.local_mode,
            "azure_auth": settings.use_azure_auth,
            "tipg_enabled": settings.enable_tipg,
            "stac_api_enabled": settings.enable_stac_api,
            "planetary_computer_enabled": settings.enable_planetary_computer,
        },
    }
