"""
Searches Landing Page.

Provides an interactive landing page for pgSTAC dynamic mosaic searches.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from geotiler import __version__

router = APIRouter(tags=["Landing Pages"])


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
  --ds-status-healthy: #059669;
  --ds-status-warning: #d97706;
  --ds-status-error: #dc2626;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: "Open Sans", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--ds-navy);
  background-color: var(--ds-bg);
}

a { color: var(--ds-blue-primary); text-decoration: none; }
a:hover { color: var(--ds-cyan); text-decoration: underline; }

.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 30px;
  background: white;
  border-bottom: 3px solid var(--ds-blue-primary);
}

.navbar-brand { font-size: 18px; font-weight: 700; color: var(--ds-navy); }
.navbar-brand span { color: var(--ds-gray); font-weight: 400; font-size: 14px; }
.navbar-links { display: flex; gap: 20px; }
.navbar-links a {
  color: var(--ds-blue-primary);
  font-weight: 500;
  padding: 5px 10px;
  border-radius: 4px;
  transition: background 0.2s;
}
.navbar-links a:hover { background: var(--ds-gray-light); text-decoration: none; }
.navbar-links a.active { background: var(--ds-blue-primary); color: white; }

.container { max-width: 1000px; margin: 0 auto; padding: 30px; }

.page-header {
  background: white;
  border-radius: 8px;
  padding: 25px;
  margin-bottom: 25px;
  border-left: 4px solid var(--ds-gold);
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.page-title { font-size: 24px; font-weight: 700; margin-bottom: 10px; }
.page-description { color: var(--ds-gray); }

.card {
  background: white;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.card-title { font-size: 16px; font-weight: 700; margin-bottom: 15px; color: var(--ds-navy); }

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-ok { background: #d1fae5; color: var(--ds-status-healthy); }
.status-warning { background: #fef3c7; color: var(--ds-status-warning); }
.status-error { background: #fee2e2; color: var(--ds-status-error); }

.search-list { list-style: none; }
.search-item {
  padding: 15px;
  border: 1px solid var(--ds-gray-light);
  border-radius: 6px;
  margin-bottom: 10px;
  transition: border-color 0.2s;
}
.search-item:hover { border-color: var(--ds-blue-primary); }

.search-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.search-id {
  font-family: monospace;
  font-weight: 600;
  color: var(--ds-navy);
}

.search-meta {
  font-size: 12px;
  color: var(--ds-gray);
  margin-bottom: 10px;
}

.search-actions { display: flex; gap: 10px; }

.btn {
  display: inline-block;
  padding: 6px 12px;
  background: var(--ds-blue-primary);
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  transition: background 0.2s;
}
.btn:hover { background: var(--ds-blue-dark); color: white; text-decoration: none; }
.btn-secondary { background: var(--ds-gray); }
.btn-secondary:hover { background: var(--ds-navy); }
.btn-large { padding: 10px 20px; font-size: 14px; }

.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--ds-gray);
}

.empty-state h3 { margin-bottom: 10px; color: var(--ds-navy); }

.endpoint-list { list-style: none; }
.endpoint-list li {
  padding: 10px 0;
  border-bottom: 1px solid var(--ds-gray-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.endpoint-list li:last-child { border-bottom: none; }
.endpoint-path { font-family: monospace; background: var(--ds-gray-light); padding: 3px 8px; border-radius: 3px; font-size: 12px; }
.endpoint-desc { color: var(--ds-gray); font-size: 13px; }

.loading {
  text-align: center;
  padding: 40px;
  color: var(--ds-gray);
}

.footer {
  text-align: center;
  padding: 20px;
  color: var(--ds-gray);
  font-size: 12px;
}

.info-box {
  background: #fef3c7;
  border: 1px solid var(--ds-gold);
  border-radius: 4px;
  padding: 12px 15px;
  margin-bottom: 20px;
  font-size: 13px;
}

#db-status { margin-bottom: 20px; }
"""

JS = """
let searchesData = [];

async function loadSearches() {
    const container = document.getElementById('searches-container');
    const dbStatus = document.getElementById('db-status');

    try {
        const response = await fetch('/searches/list');

        if (!response.ok) {
            if (response.status === 503) {
                dbStatus.innerHTML = '<div class="info-box"><strong>Database Unavailable</strong><br>The pgSTAC database is not connected. Searches functionality requires a PostgreSQL database with pgSTAC extension.</div>';
                container.innerHTML = '<div class="empty-state"><h3>Database Required</h3><p>Connect to a pgSTAC database to use search functionality.</p></div>';
                return;
            }
            throw new Error('Failed to load searches');
        }

        searchesData = await response.json();
        renderSearches(searchesData);

    } catch (error) {
        console.error('Error loading searches:', error);
        container.innerHTML = '<div class="empty-state"><h3>Error Loading Searches</h3><p>' + error.message + '</p></div>';
    }
}

function renderSearches(searches) {
    const container = document.getElementById('searches-container');

    if (!searches || searches.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <h3>No Searches Registered</h3>
                <p>Create a search by POSTing to <code>/searches/register</code> with a STAC search query.</p>
                <p style="margin-top: 15px;">
                    <a href="/docs#/STAC%20Search/register_search_searches_register_post">View API documentation</a>
                </p>
            </div>
        `;
        return;
    }

    let html = '<ul class="search-list">';

    for (const search of searches) {
        const searchId = search.id || search.search_id || 'unknown';
        const metadata = search.metadata || {};
        const created = metadata.created || search.created || 'Unknown';

        html += `
            <li class="search-item">
                <div class="search-header">
                    <span class="search-id">${searchId}</span>
                </div>
                <div class="search-meta">
                    Created: ${created}
                </div>
                <div class="search-actions">
                    <a href="/searches/${searchId}/WebMercatorQuad/map" class="btn">Open Viewer</a>
                    <a href="/searches/${searchId}/info" class="btn btn-secondary">Info</a>
                    <a href="/searches/${searchId}/WebMercatorQuad/tilejson.json" class="btn btn-secondary">TileJSON</a>
                </div>
            </li>
        `;
    }

    html += '</ul>';
    container.innerHTML = html;
}

// Load searches on page load
document.addEventListener('DOMContentLoaded', loadSearches);
"""


def _render_page() -> str:
    """Render the Searches landing page."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STAC Searches - geotiler</title>
    <style>{CSS}</style>
</head>
<body>
    <nav class="navbar">
        <a href="/" class="navbar-brand">geotiler <span>v{__version__}</span></a>
        <div class="navbar-links">
            <a href="/cog/">COG</a>
            <a href="/xarray/">XArray</a>
            <a href="/searches/" class="active">Searches</a>
            <a href="/vector">Vector</a>
            <a href="/stac/">STAC</a>
            <a href="/guide/">Guide</a>
            <a href="/docs">API Docs</a>
        </div>
    </nav>

    <div class="container">
        <div class="page-header">
            <h1 class="page-title">pgSTAC Mosaic Searches</h1>
            <p class="page-description">
                Dynamic tile mosaics generated from STAC catalog searches.
                Register a search query to create a mosaic of matching items.
            </p>
        </div>

        <div id="db-status"></div>

        <div class="card">
            <h2 class="card-title">Registered Searches</h2>
            <div id="searches-container">
                <div class="loading">Loading searches...</div>
            </div>
        </div>

        <div class="card">
            <h2 class="card-title">How It Works</h2>
            <ol style="margin-left: 20px; color: var(--ds-gray);">
                <li style="margin-bottom: 8px;"><strong>Register a Search:</strong> POST a STAC search query to <code>/searches/register</code></li>
                <li style="margin-bottom: 8px;"><strong>Get a Search ID:</strong> The response contains a unique search ID</li>
                <li style="margin-bottom: 8px;"><strong>Render Tiles:</strong> Use <code>/searches/{{id}}/tiles/...</code> to render mosaic tiles</li>
                <li><strong>View on Map:</strong> Open the interactive viewer at <code>/searches/{{id}}/{{tms}}/map</code></li>
            </ol>
        </div>

        <div class="card">
            <h2 class="card-title">Available Endpoints</h2>
            <ul class="endpoint-list">
                <li>
                    <span class="endpoint-path">GET /searches/list</span>
                    <span class="endpoint-desc">List all registered searches</span>
                </li>
                <li>
                    <span class="endpoint-path">POST /searches/register</span>
                    <span class="endpoint-desc">Register a new search (returns search ID)</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /searches/{{id}}/info</span>
                    <span class="endpoint-desc">Get search metadata and bounds</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /searches/{{id}}/tiles/{{tms}}/{{z}}/{{x}}/{{y}}</span>
                    <span class="endpoint-desc">XYZ mosaic tiles</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /searches/{{id}}/{{tms}}/tilejson.json</span>
                    <span class="endpoint-desc">TileJSON for web maps</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /searches/{{id}}/{{tms}}/map</span>
                    <span class="endpoint-desc">Interactive map viewer</span>
                </li>
                <li>
                    <span class="endpoint-path">POST /searches/{{id}}/statistics</span>
                    <span class="endpoint-desc">Regional statistics</span>
                </li>
            </ul>
            <p style="margin-top: 15px;">
                <a href="/docs#/STAC%20Search">View full API documentation</a>
            </p>
        </div>

        <div class="card">
            <h2 class="card-title">Example: Register a Search</h2>
            <pre style="background: var(--ds-gray-light); padding: 15px; border-radius: 4px; overflow-x: auto; font-size: 12px;">
POST /searches/register
Content-Type: application/json

{{
  "collections": ["my-collection"],
  "filter-lang": "cql2-json",
  "filter": {{
    "op": "and",
    "args": [
      {{"op": "<=", "args": [{{"property": "eo:cloud_cover"}}, 20]}},
      {{"op": "s_intersects", "args": [
        {{"property": "geometry"}},
        {{"type": "Polygon", "coordinates": [[[-105, 40], [-104, 40], [-104, 41], [-105, 41], [-105, 40]]]}}
      ]}}
    ]
  }}
}}</pre>
        </div>
    </div>

    <footer class="footer">
        <a href="https://github.com/developmentseed/titiler-pgstac">titiler-pgstac</a> |
        <a href="https://github.com/stac-utils/pgstac">pgSTAC</a> |
        <a href="/">Home</a>
    </footer>

    <script>{JS}</script>
</body>
</html>'''


@router.get("/searches/", response_class=HTMLResponse, include_in_schema=False)
async def searches_landing(request: Request):
    """
    pgSTAC Searches landing page.

    Provides an interface to browse and visualize registered mosaic searches:
    - Lists all registered searches
    - Quick links to viewer, info, and tilejson for each search
    - Documentation on how to register new searches
    - Example search registration payload
    """
    return _render_page()
