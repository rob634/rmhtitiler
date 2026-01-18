"""
Documentation Guide Pages.

Serves narrative documentation for TiTiler/TiPG APIs.
Complements the auto-generated /docs (Swagger) and /redoc endpoints.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from geotiler import __version__
from geotiler.config import settings

router = APIRouter(tags=["Documentation"])


# =============================================================================
# SHARED CSS
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
  --ds-code-bg: #1e1e1e;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: "Open Sans", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.7;
  color: var(--ds-navy);
  background-color: var(--ds-bg);
}

a { color: var(--ds-blue-primary); text-decoration: none; }
a:hover { color: var(--ds-cyan); text-decoration: underline; }

/* Navbar */
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 30px;
  background: white;
  border-bottom: 3px solid var(--ds-blue-primary);
  position: sticky;
  top: 0;
  z-index: 100;
}

.navbar-brand { font-size: 16px; font-weight: 700; color: var(--ds-navy); }
.navbar-brand span { color: var(--ds-gray); font-weight: 400; font-size: 13px; }
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

/* Layout */
.layout {
  display: flex;
  min-height: calc(100vh - 50px);
}

/* Sidebar */
.sidebar {
  width: 260px;
  background: white;
  border-right: 1px solid var(--ds-gray-light);
  padding: 20px 0;
  position: sticky;
  top: 50px;
  height: calc(100vh - 50px);
  overflow-y: auto;
}

.sidebar-section { margin-bottom: 20px; }
.sidebar-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--ds-gray);
  padding: 0 20px;
  margin-bottom: 8px;
}

.sidebar-nav { list-style: none; }
.sidebar-nav a {
  display: block;
  padding: 8px 20px;
  font-size: 14px;
  color: var(--ds-navy);
  border-left: 3px solid transparent;
}
.sidebar-nav a:hover { background: var(--ds-bg); text-decoration: none; }
.sidebar-nav a.active { border-left-color: var(--ds-blue-primary); background: var(--ds-bg); font-weight: 600; }

/* Content */
.content {
  flex: 1;
  padding: 40px 60px;
  max-width: 900px;
}

.content h1 {
  font-size: 32px;
  font-weight: 700;
  margin-bottom: 10px;
  color: var(--ds-navy);
}

.content h2 {
  font-size: 22px;
  font-weight: 700;
  margin-top: 40px;
  margin-bottom: 15px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--ds-gray-light);
}

.content h3 {
  font-size: 18px;
  font-weight: 600;
  margin-top: 30px;
  margin-bottom: 12px;
}

.content p { margin-bottom: 15px; }

.content ul, .content ol {
  margin-bottom: 15px;
  padding-left: 25px;
}

.content li { margin-bottom: 8px; }

.subtitle {
  font-size: 18px;
  color: var(--ds-gray);
  margin-bottom: 30px;
}

/* Code blocks */
pre {
  background: var(--ds-code-bg);
  color: #d4d4d4;
  padding: 20px;
  border-radius: 6px;
  overflow-x: auto;
  margin-bottom: 20px;
  font-size: 13px;
  line-height: 1.5;
}

code {
  font-family: "SF Mono", Monaco, "Cascadia Code", monospace;
}

p code, li code {
  background: var(--ds-gray-light);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 13px;
  color: var(--ds-navy);
}

/* Syntax highlighting */
.kw { color: #569cd6; }
.str { color: #ce9178; }
.num { color: #b5cea8; }
.cmt { color: #6a9955; }
.fn { color: #dcdcaa; }
.var { color: #9cdcfe; }

/* Cards */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  margin: 25px 0;
}

.card {
  background: white;
  border-radius: 8px;
  padding: 25px;
  border: 1px solid var(--ds-gray-light);
  transition: all 0.2s;
}

.card:hover { border-color: var(--ds-blue-primary); transform: translateY(-2px); }

.card h3 { margin-top: 0; margin-bottom: 10px; }
.card p { margin-bottom: 0; color: var(--ds-gray); font-size: 14px; }

.card-link { text-decoration: none; color: inherit; display: block; }
.card-link:hover { text-decoration: none; }

/* Tables */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 20px 0;
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

/* Callouts */
.callout {
  padding: 15px 20px;
  border-radius: 6px;
  margin: 20px 0;
  border-left: 4px solid;
}

.callout-info {
  background: #e8f4fc;
  border-color: var(--ds-cyan);
}

.callout-warning {
  background: #fef3c7;
  border-color: var(--ds-gold);
}

.callout-success {
  background: #d1fae5;
  border-color: #059669;
}

.callout strong { display: block; margin-bottom: 5px; }

/* Badges */
.badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.badge-get { background: #d1fae5; color: #059669; }
.badge-post { background: #fef3c7; color: #d97706; }

/* Steps */
.steps { counter-reset: step; list-style: none; padding-left: 0; }
.steps li {
  position: relative;
  padding-left: 50px;
  margin-bottom: 25px;
}
.steps li::before {
  counter-increment: step;
  content: counter(step);
  position: absolute;
  left: 0;
  top: 0;
  width: 32px;
  height: 32px;
  background: var(--ds-blue-primary);
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
}

/* Footer */
.footer {
  text-align: center;
  padding: 30px;
  color: var(--ds-gray);
  font-size: 12px;
  border-top: 1px solid var(--ds-gray-light);
  margin-top: 60px;
}
"""


# =============================================================================
# SIDEBAR COMPONENT
# =============================================================================

def _render_sidebar(active: str = "") -> str:
    """Render the documentation sidebar."""
    def link(href: str, text: str) -> str:
        cls = "active" if href == active else ""
        return f'<a href="{href}" class="{cls}">{text}</a>'

    return f'''
    <aside class="sidebar">
        <div class="sidebar-section">
            <div class="sidebar-title">Getting Started</div>
            <ul class="sidebar-nav">
                {link("/guide/", "Overview")}
                {link("/guide/authentication", "Authentication")}
                {link("/guide/quick-start", "Quick Start")}
            </ul>
        </div>
        <div class="sidebar-section">
            <div class="sidebar-title">Data Scientists</div>
            <ul class="sidebar-nav">
                {link("/guide/data-scientists/", "Overview")}
                {link("/guide/data-scientists/point-queries", "Point Queries")}
                {link("/guide/data-scientists/batch-queries", "Batch Queries")}
                {link("/guide/data-scientists/stac-search", "STAC Search")}
            </ul>
        </div>
        <div class="sidebar-section">
            <div class="sidebar-title">Web Developers</div>
            <ul class="sidebar-nav">
                {link("/guide/web-developers/", "Overview")}
                {link("/guide/web-developers/maplibre-tiles", "MapLibre Tiles")}
                {link("/guide/web-developers/vector-features", "Vector Features")}
            </ul>
        </div>
        <div class="sidebar-section">
            <div class="sidebar-title">API Reference</div>
            <ul class="sidebar-nav">
                {link("/docs", "Swagger UI")}
                {link("/redoc", "ReDoc")}
                {link("/api", "API Info")}
            </ul>
        </div>
        <div class="sidebar-section">
            <div class="sidebar-title">Endpoints</div>
            <ul class="sidebar-nav">
                {link("/cog/", "COG Tiles")}
                {link("/xarray/", "XArray / Zarr")}
                {link("/searches/", "STAC Searches")}
                {link("/vector", "Vector (TiPG)")}
                {link("/stac/", "STAC Explorer")}
            </ul>
        </div>
    </aside>
    '''


def _render_navbar() -> str:
    """Render the navigation bar."""
    return f'''
    <nav class="navbar">
        <a href="/" class="navbar-brand">geotiler <span>v{__version__}</span></a>
        <div class="navbar-links">
            <a href="/cog/">COG</a>
            <a href="/xarray/">XArray</a>
            <a href="/searches/">Searches</a>
            <a href="/vector">Vector</a>
            <a href="/stac/">STAC</a>
            <a href="/guide/" class="active">Guide</a>
            <a href="/docs">API Docs</a>
        </div>
    </nav>
    '''


def _render_page(title: str, content: str, active: str = "") -> str:
    """Render a full documentation page."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - geotiler Documentation</title>
    <style>{CSS}</style>
</head>
<body>
    {_render_navbar()}
    <div class="layout">
        {_render_sidebar(active)}
        <main class="content">
            {content}
        </main>
    </div>
</body>
</html>'''


# =============================================================================
# GUIDE INDEX
# =============================================================================

@router.get("/guide/", response_class=HTMLResponse, include_in_schema=False)
async def guide_index():
    """Documentation landing page."""
    content = '''
    <h1>Documentation</h1>
    <p class="subtitle">Guides and tutorials for the geotiler API</p>

    <div class="card-grid">
        <a href="/guide/authentication" class="card-link">
            <div class="card">
                <h3>Authentication</h3>
                <p>How to authenticate API requests using your browser token</p>
            </div>
        </a>
        <a href="/guide/quick-start" class="card-link">
            <div class="card">
                <h3>Quick Start</h3>
                <p>Make your first API call in under 5 minutes</p>
            </div>
        </a>
    </div>

    <h2>Choose Your Path</h2>

    <div class="card-grid">
        <a href="/guide/data-scientists/" class="card-link">
            <div class="card">
                <h3>Data Scientists</h3>
                <p>Query geospatial data from Jupyter notebooks. Extract point values, run batch queries, search STAC catalogs.</p>
            </div>
        </a>
        <a href="/guide/web-developers/" class="card-link">
            <div class="card">
                <h3>Web Developers</h3>
                <p>Build maps with MapLibre GL JS. Display raster tiles, query vector features, integrate with web apps.</p>
            </div>
        </a>
    </div>

    <h2>API Reference</h2>

    <div class="card-grid">
        <a href="/docs" class="card-link">
            <div class="card">
                <h3>Swagger UI</h3>
                <p>Interactive API documentation with try-it-out functionality</p>
            </div>
        </a>
        <a href="/redoc" class="card-link">
            <div class="card">
                <h3>ReDoc</h3>
                <p>Clean, readable API reference documentation</p>
            </div>
        </a>
    </div>

    <h2>Endpoint Explorers</h2>

    <p>Interactive landing pages for each API component:</p>

    <table>
        <tr>
            <th>Endpoint</th>
            <th>Description</th>
        </tr>
        <tr>
            <td><a href="/cog/">/cog/</a></td>
            <td>Cloud Optimized GeoTIFF tiles, info, and statistics</td>
        </tr>
        <tr>
            <td><a href="/xarray/">/xarray/</a></td>
            <td>Zarr and NetCDF multidimensional data</td>
        </tr>
        <tr>
            <td><a href="/searches/">/searches/</a></td>
            <td>pgSTAC dynamic mosaic searches</td>
        </tr>
        <tr>
            <td><a href="/vector">/vector</a></td>
            <td>TiPG OGC Features + Vector Tiles</td>
        </tr>
        <tr>
            <td><a href="/stac/">/stac/</a></td>
            <td>STAC catalog explorer with map interface</td>
        </tr>
    </table>
    '''
    return _render_page("Documentation", content, "/guide/")


# =============================================================================
# AUTHENTICATION
# =============================================================================

@router.get("/guide/authentication", response_class=HTMLResponse, include_in_schema=False)
async def guide_authentication():
    """Authentication guide."""
    content = '''
    <h1>Authentication</h1>
    <p class="subtitle">How to authenticate API requests</p>

    <div class="callout callout-info">
        <strong>Simple Rule</strong>
        If you're in our tenant, you have access. No groups, no roles &mdash; tenant membership = data access.
    </div>

    <h2>Browser to Notebook Workflow</h2>

    <p>The most common pattern for data scientists: log in via browser, copy your token, use it in Python.</p>

    <ol class="steps">
        <li>
            <strong>Log in via browser</strong><br>
            Navigate to the application and sign in with your organizational account (Entra ID).
        </li>
        <li>
            <strong>Open Developer Tools</strong><br>
            Press <code>F12</code> or right-click and select "Inspect" to open browser dev tools.
        </li>
        <li>
            <strong>Find your token</strong><br>
            Go to the <strong>Application</strong> tab, then look in <strong>Cookies</strong> or <strong>Local Storage</strong> for a token (usually named <code>access_token</code> or <code>id_token</code>).
        </li>
        <li>
            <strong>Copy the token value</strong><br>
            Copy the entire token string (it starts with <code>eyJ...</code>).
        </li>
    </ol>

    <h2>Using Your Token in Python</h2>

<pre><span class="kw">import</span> requests

<span class="cmt"># Your token from browser dev tools</span>
token = <span class="str">"eyJ0eXAiOiJKV1QiLCJhbGciOi..."</span>

<span class="cmt"># Make authenticated request</span>
response = requests.<span class="fn">get</span>(
    <span class="str">"https://your-titiler-instance/cog/info"</span>,
    params={<span class="str">"url"</span>: <span class="str">"https://storage.../file.tif"</span>},
    headers={<span class="str">"Authorization"</span>: <span class="str">f"Bearer </span>{token}<span class="str">"</span>}
)

data = response.<span class="fn">json</span>()
<span class="fn">print</span>(data)</pre>

    <h3>Using Environment Variables (Recommended)</h3>

    <p>For security, store your token in an environment variable instead of hardcoding it:</p>

<pre><span class="kw">import</span> os
<span class="kw">import</span> requests

<span class="cmt"># Set in terminal: export GEOTILER_TOKEN="eyJ..."</span>
token = os.environ.<span class="fn">get</span>(<span class="str">"GEOTILER_TOKEN"</span>)

<span class="kw">if not</span> token:
    <span class="kw">raise</span> <span class="fn">ValueError</span>(<span class="str">"Set GEOTILER_TOKEN environment variable"</span>)

response = requests.<span class="fn">get</span>(
    <span class="str">"https://your-titiler-instance/cog/info"</span>,
    params={<span class="str">"url"</span>: <span class="str">"https://storage.../file.tif"</span>},
    headers={<span class="str">"Authorization"</span>: <span class="str">f"Bearer </span>{token}<span class="str">"</span>}
)</pre>

    <h2>Token Expiration</h2>

    <p>Tokens typically expire after 1-8 hours. When you receive a <code>401 Unauthorized</code> error:</p>

    <ol>
        <li>Return to your browser</li>
        <li>Refresh the page (this may auto-renew your token)</li>
        <li>Copy the new token from dev tools</li>
    </ol>

    <h2>Troubleshooting</h2>

    <table>
        <tr>
            <th>Error</th>
            <th>Cause</th>
            <th>Solution</th>
        </tr>
        <tr>
            <td><code>401 Unauthorized</code></td>
            <td>Token expired or invalid</td>
            <td>Get a fresh token from browser</td>
        </tr>
        <tr>
            <td><code>403 Forbidden</code></td>
            <td>Token valid but no access</td>
            <td>Check with admin about permissions</td>
        </tr>
        <tr>
            <td>Invalid token format</td>
            <td>Copy/paste error</td>
            <td>Re-copy token, check for whitespace</td>
        </tr>
    </table>

    <h2>For Web Applications</h2>

    <p>Internal web applications authenticate via Entra ID app registration. The same simple rule applies: if the app is in our tenant, it has access. Configuration is handled by the platform team.</p>

    <div class="footer">
        <a href="/guide/">Back to Documentation</a> |
        <a href="/guide/quick-start">Next: Quick Start</a>
    </div>
    '''
    return _render_page("Authentication", content, "/guide/authentication")


# =============================================================================
# QUICK START
# =============================================================================

@router.get("/guide/quick-start", response_class=HTMLResponse, include_in_schema=False)
async def guide_quick_start():
    """Quick start guide."""
    content = '''
    <h1>Quick Start</h1>
    <p class="subtitle">Make your first API call in 5 minutes</p>

    <h2>Prerequisites</h2>

    <ul>
        <li>Python 3.8+ with <code>requests</code> library</li>
        <li>An authentication token (<a href="/guide/authentication">see Authentication guide</a>)</li>
    </ul>

    <h2>Step 1: Get COG Information</h2>

    <p>The simplest API call &mdash; get metadata about a Cloud Optimized GeoTIFF:</p>

<pre><span class="kw">import</span> requests

<span class="cmt"># Public COG - no auth needed for this example</span>
url = <span class="str">"https://your-titiler-instance/cog/info"</span>
params = {
    <span class="str">"url"</span>: <span class="str">"https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/36/Q/WD/2020/7/S2A_36QWD_20200701_0_L2A/TCI.tif"</span>
}

response = requests.<span class="fn">get</span>(url, params=params)
info = response.<span class="fn">json</span>()

<span class="fn">print</span>(<span class="str">f"Bounds: </span>{info[<span class="str">'bounds'</span>]}<span class="str">"</span>)
<span class="fn">print</span>(<span class="str">f"CRS: </span>{info[<span class="str">'crs'</span>]}<span class="str">"</span>)
<span class="fn">print</span>(<span class="str">f"Width x Height: </span>{info[<span class="str">'width'</span>]}<span class="str"> x </span>{info[<span class="str">'height'</span>]}<span class="str">"</span>)</pre>

    <h2>Step 2: Query a Point Value</h2>

    <p>Extract the pixel value at a specific coordinate:</p>

<pre><span class="cmt"># Query point value</span>
url = <span class="str">"https://your-titiler-instance/cog/point/36.8,-1.3"</span>
params = {
    <span class="str">"url"</span>: <span class="str">"https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/36/Q/WD/2020/7/S2A_36QWD_20200701_0_L2A/TCI.tif"</span>
}

response = requests.<span class="fn">get</span>(url, params=params)
data = response.<span class="fn">json</span>()

<span class="fn">print</span>(<span class="str">f"Values at point: </span>{data[<span class="str">'values'</span>]}<span class="str">"</span>)</pre>

    <h2>Step 3: Get a Tile URL</h2>

    <p>Generate a TileJSON for use in web maps:</p>

<pre><span class="cmt"># Get TileJSON</span>
url = <span class="str">"https://your-titiler-instance/cog/WebMercatorQuad/tilejson.json"</span>
params = {
    <span class="str">"url"</span>: <span class="str">"https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/36/Q/WD/2020/7/S2A_36QWD_20200701_0_L2A/TCI.tif"</span>
}

response = requests.<span class="fn">get</span>(url, params=params)
tilejson = response.<span class="fn">json</span>()

<span class="fn">print</span>(<span class="str">f"Tile URL template: </span>{tilejson[<span class="str">'tiles'</span>][<span class="num">0</span>]}<span class="str">"</span>)
<span class="fn">print</span>(<span class="str">f"Bounds: </span>{tilejson[<span class="str">'bounds'</span>]}<span class="str">"</span>)</pre>

    <h2>Interactive Explorers</h2>

    <p>Try the built-in interactive pages to explore the API:</p>

    <div class="card-grid">
        <a href="/cog/" class="card-link">
            <div class="card">
                <h3>COG Explorer</h3>
                <p>Enter a COG URL and get info, view tiles, or query statistics</p>
            </div>
        </a>
        <a href="/stac/" class="card-link">
            <div class="card">
                <h3>STAC Explorer</h3>
                <p>Browse collections, search items, view on map</p>
            </div>
        </a>
    </div>

    <h2>Next Steps</h2>

    <ul>
        <li><a href="/guide/data-scientists/">Data Scientists Guide</a> &mdash; Point queries, batch operations, STAC search</li>
        <li><a href="/guide/web-developers/">Web Developers Guide</a> &mdash; MapLibre integration, vector features</li>
        <li><a href="/docs">API Reference (Swagger)</a> &mdash; Full endpoint documentation</li>
    </ul>

    <div class="footer">
        <a href="/guide/authentication">Previous: Authentication</a> |
        <a href="/guide/">Back to Documentation</a>
    </div>
    '''
    return _render_page("Quick Start", content, "/guide/quick-start")


# =============================================================================
# DATA SCIENTISTS
# =============================================================================

@router.get("/guide/data-scientists/", response_class=HTMLResponse, include_in_schema=False)
async def guide_data_scientists():
    """Data scientists overview."""
    content = '''
    <h1>Data Scientists Guide</h1>
    <p class="subtitle">Query geospatial data from Jupyter notebooks</p>

    <div class="callout callout-success">
        <strong>Key Concept</strong>
        Compute goes to data. No more downloading 50GB files &mdash; use HTTP range requests to read only what you need.
    </div>

    <h2>What You Can Do</h2>

    <div class="card-grid">
        <a href="/guide/data-scientists/point-queries" class="card-link">
            <div class="card">
                <h3>Point Queries</h3>
                <p>Extract values at specific coordinates from any COG or Zarr dataset</p>
            </div>
        </a>
        <a href="/guide/data-scientists/batch-queries" class="card-link">
            <div class="card">
                <h3>Batch Queries</h3>
                <p>Query multiple points efficiently with async requests</p>
            </div>
        </a>
        <a href="/guide/data-scientists/stac-search" class="card-link">
            <div class="card">
                <h3>STAC Search</h3>
                <p>Search the catalog by location, time, and properties</p>
            </div>
        </a>
    </div>

    <h2>Available Endpoints</h2>

    <table>
        <tr>
            <th>Task</th>
            <th>Endpoint</th>
            <th>Description</th>
        </tr>
        <tr>
            <td>Get metadata</td>
            <td><code>GET /cog/info</code></td>
            <td>Bounds, CRS, bands, dtype</td>
        </tr>
        <tr>
            <td>Point value</td>
            <td><code>GET /cog/point/{lon},{lat}</code></td>
            <td>Pixel value at coordinate</td>
        </tr>
        <tr>
            <td>Statistics</td>
            <td><code>GET /cog/statistics</code></td>
            <td>Min, max, mean, std for bands</td>
        </tr>
        <tr>
            <td>List variables</td>
            <td><code>GET /xarray/variables</code></td>
            <td>Variables in Zarr/NetCDF</td>
        </tr>
        <tr>
            <td>Search catalog</td>
            <td><code>GET /stac/search</code></td>
            <td>Find items by bbox, time, properties</td>
        </tr>
    </table>

    <h2>Example Workflow</h2>

<pre><span class="kw">import</span> requests

<span class="cmt"># 1. Search for data</span>
search = requests.<span class="fn">get</span>(<span class="str">"https://titiler/stac/search"</span>, params={
    <span class="str">"collections"</span>: <span class="str">"flood-risk"</span>,
    <span class="str">"bbox"</span>: <span class="str">"29,-3,31,-1"</span>,
    <span class="str">"limit"</span>: <span class="num">10</span>
}).<span class="fn">json</span>()

<span class="cmt"># 2. Get COG URL from first result</span>
item = search[<span class="str">"features"</span>][<span class="num">0</span>]
cog_url = item[<span class="str">"assets"</span>][<span class="str">"data"</span>][<span class="str">"href"</span>]

<span class="cmt"># 3. Query point value</span>
point = requests.<span class="fn">get</span>(
    <span class="str">"https://titiler/cog/point/29.87,-1.94"</span>,
    params={<span class="str">"url"</span>: cog_url}
).<span class="fn">json</span>()

<span class="fn">print</span>(<span class="str">f"Flood depth: </span>{point[<span class="str">'values'</span>][<span class="num">0</span>]}<span class="str">m"</span>)</pre>

    <div class="footer">
        <a href="/guide/">Back to Documentation</a> |
        <a href="/guide/data-scientists/point-queries">Next: Point Queries</a>
    </div>
    '''
    return _render_page("Data Scientists Guide", content, "/guide/data-scientists/")


@router.get("/guide/data-scientists/point-queries", response_class=HTMLResponse, include_in_schema=False)
async def guide_point_queries():
    """Point queries guide."""
    content = '''
    <h1>Point Queries</h1>
    <p class="subtitle">Extract values at specific coordinates</p>

    <p>The most common analysis pattern: "What's the value at this location?"</p>

    <h2>Basic Point Query</h2>

<pre><span class="kw">import</span> requests

<span class="cmt"># COG URL (can be Azure Blob, S3, or HTTP)</span>
cog_url = <span class="str">"https://storage.../flood_depth.tif"</span>

<span class="cmt"># Query point at longitude, latitude</span>
response = requests.<span class="fn">get</span>(
    <span class="str">"https://titiler/cog/point/29.8739,-1.9403"</span>,
    params={<span class="str">"url"</span>: cog_url},
    headers={<span class="str">"Authorization"</span>: <span class="str">f"Bearer </span>{token}<span class="str">"</span>}
)

data = response.<span class="fn">json</span>()
<span class="fn">print</span>(<span class="str">f"Flood depth: </span>{data[<span class="str">'values'</span>][<span class="num">0</span>]}<span class="str"> meters"</span>)</pre>

    <h3>Response Format</h3>

<pre>{
  <span class="str">"coordinates"</span>: [<span class="num">29.8739</span>, <span class="num">-1.9403</span>],
  <span class="str">"values"</span>: [<span class="num">2.5</span>],
  <span class="str">"band_names"</span>: [<span class="str">"flood_depth"</span>]
}</pre>

    <h2>Query Multiple Bands</h2>

    <p>For multi-band rasters (e.g., RGB or multi-spectral):</p>

<pre>response = requests.<span class="fn">get</span>(
    <span class="str">"https://titiler/cog/point/29.8739,-1.9403"</span>,
    params={
        <span class="str">"url"</span>: <span class="str">"https://storage.../sentinel2.tif"</span>,
        <span class="str">"bidx"</span>: <span class="str">"1,2,3,4"</span>  <span class="cmt"># Request specific bands</span>
    }
)

data = response.<span class="fn">json</span>()
<span class="cmt"># values = [R, G, B, NIR]</span></pre>

    <h2>XArray Point Queries</h2>

    <p>For Zarr/NetCDF multidimensional data:</p>

<pre>response = requests.<span class="fn">get</span>(
    <span class="str">"https://titiler/xarray/point/29.8739,-1.9403"</span>,
    params={
        <span class="str">"url"</span>: <span class="str">"https://storage.../climate.zarr"</span>,
        <span class="str">"variable"</span>: <span class="str">"temperature"</span>,
        <span class="str">"datetime"</span>: <span class="str">"2024-01-15"</span>
    }
)

data = response.<span class="fn">json</span>()
<span class="fn">print</span>(<span class="str">f"Temperature: </span>{data[<span class="str">'values'</span>][<span class="num">0</span>]}<span class="str">K"</span>)</pre>

    <h2>Error Handling</h2>

<pre><span class="kw">import</span> requests

<span class="kw">def</span> <span class="fn">query_point</span>(lon, lat, cog_url, token):
    <span class="str">"""Query point with error handling."""</span>
    <span class="kw">try</span>:
        response = requests.<span class="fn">get</span>(
            <span class="str">f"https://titiler/cog/point/</span>{lon}<span class="str">,</span>{lat}<span class="str">"</span>,
            params={<span class="str">"url"</span>: cog_url},
            headers={<span class="str">"Authorization"</span>: <span class="str">f"Bearer </span>{token}<span class="str">"</span>},
            timeout=<span class="num">30</span>
        )
        response.<span class="fn">raise_for_status</span>()
        <span class="kw">return</span> response.<span class="fn">json</span>()

    <span class="kw">except</span> requests.exceptions.HTTPError <span class="kw">as</span> e:
        <span class="kw">if</span> e.response.status_code == <span class="num">401</span>:
            <span class="fn">print</span>(<span class="str">"Token expired - refresh from browser"</span>)
        <span class="kw">elif</span> e.response.status_code == <span class="num">404</span>:
            <span class="fn">print</span>(<span class="str">"Point outside raster bounds"</span>)
        <span class="kw">raise</span></pre>

    <div class="callout callout-info">
        <strong>Tip</strong>
        For querying many points, see <a href="/guide/data-scientists/batch-queries">Batch Queries</a> for efficient async patterns.
    </div>

    <div class="footer">
        <a href="/guide/data-scientists/">Previous: Overview</a> |
        <a href="/guide/data-scientists/batch-queries">Next: Batch Queries</a>
    </div>
    '''
    return _render_page("Point Queries", content, "/guide/data-scientists/point-queries")


@router.get("/guide/data-scientists/batch-queries", response_class=HTMLResponse, include_in_schema=False)
async def guide_batch_queries():
    """Batch queries guide."""
    content = '''
    <h1>Batch Queries</h1>
    <p class="subtitle">Query multiple points efficiently</p>

    <p>When you need to query hundreds or thousands of points, use async requests for better performance.</p>

    <h2>Async Batch Query</h2>

<pre><span class="kw">import</span> asyncio
<span class="kw">import</span> aiohttp

<span class="kw">async def</span> <span class="fn">query_point</span>(session, lon, lat, cog_url, token):
    <span class="str">"""Query a single point asynchronously."""</span>
    url = <span class="str">f"https://titiler/cog/point/</span>{lon}<span class="str">,</span>{lat}<span class="str">"</span>
    headers = {<span class="str">"Authorization"</span>: <span class="str">f"Bearer </span>{token}<span class="str">"</span>}

    <span class="kw">async with</span> session.<span class="fn">get</span>(url, params={<span class="str">"url"</span>: cog_url}, headers=headers) <span class="kw">as</span> resp:
        data = <span class="kw">await</span> resp.<span class="fn">json</span>()
        <span class="kw">return</span> {
            <span class="str">"lon"</span>: lon,
            <span class="str">"lat"</span>: lat,
            <span class="str">"value"</span>: data[<span class="str">"values"</span>][<span class="num">0</span>]
        }

<span class="kw">async def</span> <span class="fn">query_many_points</span>(points, cog_url, token):
    <span class="str">"""Query multiple points concurrently."""</span>
    <span class="kw">async with</span> aiohttp.<span class="fn">ClientSession</span>() <span class="kw">as</span> session:
        tasks = [
            <span class="fn">query_point</span>(session, p[<span class="num">0</span>], p[<span class="num">1</span>], cog_url, token)
            <span class="kw">for</span> p <span class="kw">in</span> points
        ]
        <span class="kw">return await</span> asyncio.<span class="fn">gather</span>(*tasks)

<span class="cmt"># Example: Query 100 points</span>
points = [(29.8 + i*<span class="num">0.01</span>, -<span class="num">2.0</span> + i*<span class="num">0.01</span>) <span class="kw">for</span> i <span class="kw">in</span> <span class="fn">range</span>(<span class="num">100</span>)]

results = asyncio.<span class="fn">run</span>(
    <span class="fn">query_many_points</span>(points, cog_url, token)
)

<span class="kw">for</span> r <span class="kw">in</span> results[:<span class="num">5</span>]:
    <span class="fn">print</span>(<span class="str">f"</span>{r[<span class="str">'lon'</span>]}<span class="str">, </span>{r[<span class="str">'lat'</span>]}<span class="str">: </span>{r[<span class="str">'value'</span>]}<span class="str">"</span>)</pre>

    <h2>With Rate Limiting</h2>

    <p>For very large batch queries, add rate limiting to avoid overwhelming the server:</p>

<pre><span class="kw">import</span> asyncio
<span class="kw">from</span> asyncio <span class="kw">import</span> Semaphore

<span class="kw">async def</span> <span class="fn">query_with_limit</span>(semaphore, session, lon, lat, cog_url, token):
    <span class="str">"""Rate-limited point query."""</span>
    <span class="kw">async with</span> semaphore:  <span class="cmt"># Limit concurrent requests</span>
        <span class="kw">return await</span> <span class="fn">query_point</span>(session, lon, lat, cog_url, token)

<span class="kw">async def</span> <span class="fn">query_many_points_limited</span>(points, cog_url, token, max_concurrent=<span class="num">20</span>):
    <span class="str">"""Query points with concurrency limit."""</span>
    semaphore = <span class="fn">Semaphore</span>(max_concurrent)

    <span class="kw">async with</span> aiohttp.<span class="fn">ClientSession</span>() <span class="kw">as</span> session:
        tasks = [
            <span class="fn">query_with_limit</span>(semaphore, session, p[<span class="num">0</span>], p[<span class="num">1</span>], cog_url, token)
            <span class="kw">for</span> p <span class="kw">in</span> points
        ]
        <span class="kw">return await</span> asyncio.<span class="fn">gather</span>(*tasks)

<span class="cmt"># Query 1000 points, max 20 concurrent</span>
results = asyncio.<span class="fn">run</span>(
    <span class="fn">query_many_points_limited</span>(points, cog_url, token, max_concurrent=<span class="num">20</span>)
)</pre>

    <h2>Converting to DataFrame</h2>

<pre><span class="kw">import</span> pandas <span class="kw">as</span> pd

<span class="cmt"># Convert results to DataFrame</span>
df = pd.<span class="fn">DataFrame</span>(results)
<span class="fn">print</span>(df.<span class="fn">head</span>())

<span class="cmt"># Save to CSV</span>
df.<span class="fn">to_csv</span>(<span class="str">"flood_depths.csv"</span>, index=<span class="kw">False</span>)</pre>

    <div class="callout callout-warning">
        <strong>Performance Tip</strong>
        For very large datasets (10,000+ points), consider using the custom batch API endpoint (coming soon) which processes points server-side.
    </div>

    <div class="footer">
        <a href="/guide/data-scientists/point-queries">Previous: Point Queries</a> |
        <a href="/guide/data-scientists/stac-search">Next: STAC Search</a>
    </div>
    '''
    return _render_page("Batch Queries", content, "/guide/data-scientists/batch-queries")


@router.get("/guide/data-scientists/stac-search", response_class=HTMLResponse, include_in_schema=False)
async def guide_stac_search():
    """STAC search guide."""
    content = '''
    <h1>STAC Search</h1>
    <p class="subtitle">Find data by location, time, and properties</p>

    <p>STAC (SpatioTemporal Asset Catalog) provides a standard way to search for geospatial data.</p>

    <h2>Basic Search</h2>

<pre><span class="kw">import</span> requests

<span class="cmt"># Search for items in a bounding box</span>
response = requests.<span class="fn">get</span>(
    <span class="str">"https://titiler/stac/search"</span>,
    params={
        <span class="str">"collections"</span>: <span class="str">"flood-risk"</span>,
        <span class="str">"bbox"</span>: <span class="str">"29,-3,31,-1"</span>,  <span class="cmt"># minx,miny,maxx,maxy</span>
        <span class="str">"limit"</span>: <span class="num">10</span>
    }
)

results = response.<span class="fn">json</span>()
<span class="fn">print</span>(<span class="str">f"Found </span>{len(results[<span class="str">'features'</span>])}<span class="str"> items"</span>)</pre>

    <h2>Search with Time Filter</h2>

<pre><span class="cmt"># Search by date range</span>
response = requests.<span class="fn">get</span>(
    <span class="str">"https://titiler/stac/search"</span>,
    params={
        <span class="str">"collections"</span>: <span class="str">"sentinel-2"</span>,
        <span class="str">"bbox"</span>: <span class="str">"29,-3,31,-1"</span>,
        <span class="str">"datetime"</span>: <span class="str">"2024-01-01/2024-06-30"</span>,
        <span class="str">"limit"</span>: <span class="num">20</span>
    }
)</pre>

    <h2>Using pystac-client</h2>

    <p>For advanced searches, use the <code>pystac-client</code> library:</p>

<pre><span class="kw">from</span> pystac_client <span class="kw">import</span> Client

<span class="cmt"># Connect to STAC API</span>
client = Client.<span class="fn">open</span>(<span class="str">"https://titiler/stac"</span>)

<span class="cmt"># Search with filters</span>
search = client.<span class="fn">search</span>(
    collections=[<span class="str">"flood-risk"</span>],
    bbox=[<span class="num">29</span>, -<span class="num">3</span>, <span class="num">31</span>, -<span class="num">1</span>],
    datetime=<span class="str">"2024-01-01/2024-12-31"</span>,
    max_items=<span class="num">100</span>
)

<span class="cmt"># Iterate through results</span>
<span class="kw">for</span> item <span class="kw">in</span> search.<span class="fn">items</span>():
    <span class="fn">print</span>(<span class="str">f"</span>{item.id}<span class="str">: </span>{item.datetime}<span class="str">"</span>)

    <span class="cmt"># Get COG asset URL</span>
    cog_url = item.assets[<span class="str">"data"</span>].href
    <span class="fn">print</span>(<span class="str">f"  Asset: </span>{cog_url}<span class="str">"</span>)</pre>

    <h2>List Collections</h2>

<pre><span class="cmt"># Get all available collections</span>
response = requests.<span class="fn">get</span>(<span class="str">"https://titiler/stac/collections"</span>)
collections = response.<span class="fn">json</span>()[<span class="str">"collections"</span>]

<span class="kw">for</span> col <span class="kw">in</span> collections:
    <span class="fn">print</span>(<span class="str">f"</span>{col[<span class="str">'id'</span>]}<span class="str">: </span>{col.get(<span class="str">'description'</span>, <span class="str">''</span>)[:50]}<span class="str">"</span>)</pre>

    <h2>From Search to Tiles</h2>

    <p>Once you find data, you can visualize it directly:</p>

<pre><span class="cmt"># Search for an item</span>
results = requests.<span class="fn">get</span>(<span class="str">"https://titiler/stac/search"</span>, params={
    <span class="str">"collections"</span>: <span class="str">"flood-risk"</span>,
    <span class="str">"limit"</span>: <span class="num">1</span>
}).<span class="fn">json</span>()

item = results[<span class="str">"features"</span>][<span class="num">0</span>]
cog_url = item[<span class="str">"assets"</span>][<span class="str">"data"</span>][<span class="str">"href"</span>]

<span class="cmt"># Get TileJSON for visualization</span>
tilejson = requests.<span class="fn">get</span>(
    <span class="str">"https://titiler/cog/WebMercatorQuad/tilejson.json"</span>,
    params={<span class="str">"url"</span>: cog_url}
).<span class="fn">json</span>()

<span class="fn">print</span>(<span class="str">f"Tile URL: </span>{tilejson[<span class="str">'tiles'</span>][<span class="num">0</span>]}<span class="str">"</span>)</pre>

    <div class="callout callout-info">
        <strong>Interactive Explorer</strong>
        Use the <a href="/stac/">STAC Explorer</a> to browse collections and items visually with a map interface.
    </div>

    <div class="footer">
        <a href="/guide/data-scientists/batch-queries">Previous: Batch Queries</a> |
        <a href="/guide/data-scientists/">Back to Overview</a>
    </div>
    '''
    return _render_page("STAC Search", content, "/guide/data-scientists/stac-search")


# =============================================================================
# WEB DEVELOPERS
# =============================================================================

@router.get("/guide/web-developers/", response_class=HTMLResponse, include_in_schema=False)
async def guide_web_developers():
    """Web developers overview."""
    content = '''
    <h1>Web Developers Guide</h1>
    <p class="subtitle">Build maps with MapLibre GL JS</p>

    <div class="callout callout-success">
        <strong>Key Benefit</strong>
        MapLibre GL JS is 30kb vs 800kb for proprietary SDKs. Standards-based skills are portable.
    </div>

    <h2>What You Can Build</h2>

    <div class="card-grid">
        <a href="/guide/web-developers/maplibre-tiles" class="card-link">
            <div class="card">
                <h3>Raster Tile Maps</h3>
                <p>Display COG imagery as XYZ tiles with dynamic styling</p>
            </div>
        </a>
        <a href="/guide/web-developers/vector-features" class="card-link">
            <div class="card">
                <h3>Vector Features</h3>
                <p>Query and display PostGIS data as GeoJSON or vector tiles</p>
            </div>
        </a>
    </div>

    <h2>Quick Example</h2>

<pre><span class="cmt">// MapLibre GL JS - Display COG tiles</span>
<span class="kw">const</span> map = <span class="kw">new</span> maplibregl.<span class="fn">Map</span>({
  container: <span class="str">'map'</span>,
  style: {
    version: <span class="num">8</span>,
    sources: {
      <span class="str">'flood'</span>: {
        type: <span class="str">'raster'</span>,
        tiles: [
          <span class="str">'https://titiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=...'</span>
        ],
        tileSize: <span class="num">256</span>
      }
    },
    layers: [{
      id: <span class="str">'flood-layer'</span>,
      type: <span class="str">'raster'</span>,
      source: <span class="str">'flood'</span>
    }]
  },
  center: [<span class="num">29.8</span>, -<span class="num">2.0</span>],
  zoom: <span class="num">8</span>
});</pre>

    <h2>Available Tile Endpoints</h2>

    <table>
        <tr>
            <th>Endpoint</th>
            <th>Format</th>
            <th>Use Case</th>
        </tr>
        <tr>
            <td><code>/cog/tiles/{tms}/{z}/{x}/{y}</code></td>
            <td>PNG/WebP</td>
            <td>Raster imagery (COGs)</td>
        </tr>
        <tr>
            <td><code>/xarray/tiles/{tms}/{z}/{x}/{y}</code></td>
            <td>PNG/WebP</td>
            <td>Zarr/NetCDF data</td>
        </tr>
        <tr>
            <td><code>/searches/{id}/tiles/{tms}/{z}/{x}/{y}</code></td>
            <td>PNG/WebP</td>
            <td>STAC search mosaics</td>
        </tr>
        <tr>
            <td><code>/vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}</code></td>
            <td>MVT</td>
            <td>Vector tiles from PostGIS</td>
        </tr>
    </table>

    <div class="footer">
        <a href="/guide/">Back to Documentation</a> |
        <a href="/guide/web-developers/maplibre-tiles">Next: MapLibre Tiles</a>
    </div>
    '''
    return _render_page("Web Developers Guide", content, "/guide/web-developers/")


@router.get("/guide/web-developers/maplibre-tiles", response_class=HTMLResponse, include_in_schema=False)
async def guide_maplibre_tiles():
    """MapLibre tiles guide."""
    content = '''
    <h1>MapLibre Tiles</h1>
    <p class="subtitle">Display raster imagery in MapLibre GL JS</p>

    <h2>Setup</h2>

    <p>Include MapLibre GL JS in your HTML:</p>

<pre><span class="cmt">&lt;!-- CSS --&gt;</span>
&lt;link href=<span class="str">"https://unpkg.com/maplibre-gl/dist/maplibre-gl.css"</span> rel=<span class="str">"stylesheet"</span> /&gt;

<span class="cmt">&lt;!-- JavaScript --&gt;</span>
&lt;script src=<span class="str">"https://unpkg.com/maplibre-gl/dist/maplibre-gl.js"</span>&gt;&lt;/script&gt;

<span class="cmt">&lt;!-- Map container --&gt;</span>
&lt;div id=<span class="str">"map"</span> style=<span class="str">"width: 100%; height: 100vh;"</span>&gt;&lt;/div&gt;</pre>

    <h2>Display a COG</h2>

<pre><span class="kw">const</span> cogUrl = <span class="str">'https://storage.../flood_depth.tif'</span>;

<span class="kw">const</span> map = <span class="kw">new</span> maplibregl.<span class="fn">Map</span>({
  container: <span class="str">'map'</span>,
  style: {
    version: <span class="num">8</span>,
    sources: {
      <span class="str">'basemap'</span>: {
        type: <span class="str">'raster'</span>,
        tiles: [<span class="str">'https://tile.openstreetmap.org/{z}/{x}/{y}.png'</span>],
        tileSize: <span class="num">256</span>,
        attribution: <span class="str">'&copy; OpenStreetMap'</span>
      },
      <span class="str">'flood'</span>: {
        type: <span class="str">'raster'</span>,
        tiles: [
          <span class="str">`https://titiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=</span>${<span class="fn">encodeURIComponent</span>(cogUrl)}<span class="str">`</span>
        ],
        tileSize: <span class="num">256</span>
      }
    },
    layers: [
      { id: <span class="str">'basemap'</span>, type: <span class="str">'raster'</span>, source: <span class="str">'basemap'</span> },
      { id: <span class="str">'flood'</span>, type: <span class="str">'raster'</span>, source: <span class="str">'flood'</span>, paint: { <span class="str">'raster-opacity'</span>: <span class="num">0.7</span> } }
    ]
  },
  center: [<span class="num">29.8</span>, -<span class="num">2.0</span>],
  zoom: <span class="num">8</span>
});</pre>

    <h2>Using TileJSON</h2>

    <p>Let the server provide bounds and attribution:</p>

<pre><span class="cmt">// Fetch TileJSON first</span>
<span class="kw">const</span> cogUrl = <span class="str">'https://storage.../flood_depth.tif'</span>;
<span class="kw">const</span> tilejsonUrl = <span class="str">`https://titiler/cog/WebMercatorQuad/tilejson.json?url=</span>${<span class="fn">encodeURIComponent</span>(cogUrl)}<span class="str">`</span>;

<span class="fn">fetch</span>(tilejsonUrl)
  .<span class="fn">then</span>(r => r.<span class="fn">json</span>())
  .<span class="fn">then</span>(tilejson => {
    <span class="cmt">// Add source using TileJSON</span>
    map.<span class="fn">addSource</span>(<span class="str">'flood'</span>, {
      type: <span class="str">'raster'</span>,
      tiles: tilejson.tiles,
      bounds: tilejson.bounds,
      minzoom: tilejson.minzoom,
      maxzoom: tilejson.maxzoom
    });

    map.<span class="fn">addLayer</span>({
      id: <span class="str">'flood-layer'</span>,
      type: <span class="str">'raster'</span>,
      source: <span class="str">'flood'</span>
    });

    <span class="cmt">// Zoom to data bounds</span>
    map.<span class="fn">fitBounds</span>(tilejson.bounds);
  });</pre>

    <h2>Styling with Colormap</h2>

    <p>Apply a colormap to single-band data:</p>

<pre><span class="kw">const</span> tileUrl = <span class="str">`https://titiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png`</span> +
  <span class="str">`?url=</span>${<span class="fn">encodeURIComponent</span>(cogUrl)}<span class="str">`</span> +
  <span class="str">`&colormap_name=viridis`</span> +
  <span class="str">`&rescale=0,10`</span>;  <span class="cmt">// Min/max values</span>

map.<span class="fn">addSource</span>(<span class="str">'flood'</span>, {
  type: <span class="str">'raster'</span>,
  tiles: [tileUrl],
  tileSize: <span class="num">256</span>
});</pre>

    <h2>Click to Query</h2>

    <p>Get pixel values on click:</p>

<pre>map.<span class="fn">on</span>(<span class="str">'click'</span>, <span class="kw">async</span> (e) => {
  <span class="kw">const</span> { lng, lat } = e.lngLat;

  <span class="kw">const</span> response = <span class="kw">await</span> <span class="fn">fetch</span>(
    <span class="str">`https://titiler/cog/point/</span>${lng}<span class="str">,</span>${lat}<span class="str">?url=</span>${<span class="fn">encodeURIComponent</span>(cogUrl)}<span class="str">`</span>
  );
  <span class="kw">const</span> data = <span class="kw">await</span> response.<span class="fn">json</span>();

  <span class="kw">new</span> maplibregl.<span class="fn">Popup</span>()
    .<span class="fn">setLngLat</span>([lng, lat])
    .<span class="fn">setHTML</span>(<span class="str">`&lt;strong&gt;Value:&lt;/strong&gt; </span>${data.values[<span class="num">0</span>].<span class="fn">toFixed</span>(<span class="num">2</span>)}<span class="str">`</span>)
    .<span class="fn">addTo</span>(map);
});</pre>

    <div class="footer">
        <a href="/guide/web-developers/">Previous: Overview</a> |
        <a href="/guide/web-developers/vector-features">Next: Vector Features</a>
    </div>
    '''
    return _render_page("MapLibre Tiles", content, "/guide/web-developers/maplibre-tiles")


@router.get("/guide/web-developers/vector-features", response_class=HTMLResponse, include_in_schema=False)
async def guide_vector_features():
    """Vector features guide."""
    content = '''
    <h1>Vector Features</h1>
    <p class="subtitle">Query and display PostGIS data with TiPG</p>

    <p>TiPG provides OGC API Features and Vector Tiles for PostGIS tables.</p>

    <h2>List Collections</h2>

<pre><span class="cmt">// Get available collections (tables)</span>
<span class="fn">fetch</span>(<span class="str">'https://titiler/vector/collections'</span>)
  .<span class="fn">then</span>(r => r.<span class="fn">json</span>())
  .<span class="fn">then</span>(data => {
    data.collections.<span class="fn">forEach</span>(col => {
      console.<span class="fn">log</span>(col.id, col.title);
    });
  });</pre>

    <h2>Query Features (GeoJSON)</h2>

<pre><span class="cmt">// Get features from a collection</span>
<span class="kw">const</span> params = <span class="kw">new</span> <span class="fn">URLSearchParams</span>({
  limit: <span class="num">100</span>,
  bbox: <span class="str">'29,-3,31,-1'</span>
});

<span class="fn">fetch</span>(<span class="str">`https://titiler/vector/collections/admin_boundaries/items?</span>${params}<span class="str">`</span>)
  .<span class="fn">then</span>(r => r.<span class="fn">json</span>())
  .<span class="fn">then</span>(geojson => {
    console.<span class="fn">log</span>(<span class="str">`Found </span>${geojson.features.length}<span class="str"> features`</span>);
  });</pre>

    <h2>Display as GeoJSON Layer</h2>

<pre><span class="cmt">// Add GeoJSON source</span>
map.<span class="fn">addSource</span>(<span class="str">'boundaries'</span>, {
  type: <span class="str">'geojson'</span>,
  data: <span class="str">'https://titiler/vector/collections/admin_boundaries/items?limit=1000'</span>
});

<span class="cmt">// Add fill layer</span>
map.<span class="fn">addLayer</span>({
  id: <span class="str">'boundaries-fill'</span>,
  type: <span class="str">'fill'</span>,
  source: <span class="str">'boundaries'</span>,
  paint: {
    <span class="str">'fill-color'</span>: <span class="str">'#088'</span>,
    <span class="str">'fill-opacity'</span>: <span class="num">0.3</span>
  }
});

<span class="cmt">// Add outline layer</span>
map.<span class="fn">addLayer</span>({
  id: <span class="str">'boundaries-line'</span>,
  type: <span class="str">'line'</span>,
  source: <span class="str">'boundaries'</span>,
  paint: {
    <span class="str">'line-color'</span>: <span class="str">'#088'</span>,
    <span class="str">'line-width'</span>: <span class="num">2</span>
  }
});</pre>

    <h2>Display as Vector Tiles</h2>

    <p>For large datasets, use vector tiles for better performance:</p>

<pre><span class="cmt">// Add vector tile source</span>
map.<span class="fn">addSource</span>(<span class="str">'boundaries'</span>, {
  type: <span class="str">'vector'</span>,
  tiles: [
    <span class="str">'https://titiler/vector/collections/admin_boundaries/tiles/WebMercatorQuad/{z}/{x}/{y}'</span>
  ]
});

<span class="cmt">// Add layer (note source-layer)</span>
map.<span class="fn">addLayer</span>({
  id: <span class="str">'boundaries-fill'</span>,
  type: <span class="str">'fill'</span>,
  source: <span class="str">'boundaries'</span>,
  <span class="str">'source-layer'</span>: <span class="str">'default'</span>,  <span class="cmt">// TiPG default layer name</span>
  paint: {
    <span class="str">'fill-color'</span>: <span class="str">'#088'</span>,
    <span class="str">'fill-opacity'</span>: <span class="num">0.3</span>
  }
});</pre>

    <h2>Filter Features</h2>

    <p>Use CQL2 filters for server-side filtering:</p>

<pre><span class="cmt">// Filter by property</span>
<span class="kw">const</span> filter = <span class="fn">encodeURIComponent</span>(<span class="str">'population > 100000'</span>);

<span class="fn">fetch</span>(<span class="str">`https://titiler/vector/collections/cities/items?filter=</span>${filter}<span class="str">&filter-lang=cql2-text`</span>)
  .<span class="fn">then</span>(r => r.<span class="fn">json</span>())
  .<span class="fn">then</span>(geojson => {
    console.<span class="fn">log</span>(<span class="str">`Found </span>${geojson.features.length}<span class="str"> cities with pop > 100k`</span>);
  });</pre>

    <h2>Click to Query</h2>

<pre>map.<span class="fn">on</span>(<span class="str">'click'</span>, <span class="str">'boundaries-fill'</span>, (e) => {
  <span class="kw">const</span> feature = e.features[<span class="num">0</span>];

  <span class="kw">new</span> maplibregl.<span class="fn">Popup</span>()
    .<span class="fn">setLngLat</span>(e.lngLat)
    .<span class="fn">setHTML</span>(<span class="str">`
      &lt;strong&gt;</span>${feature.properties.name}<span class="str">&lt;/strong&gt;&lt;br&gt;
      Population: </span>${feature.properties.population.<span class="fn">toLocaleString</span>()}<span class="str">
    `</span>)
    .<span class="fn">addTo</span>(map);
});

<span class="cmt">// Change cursor on hover</span>
map.<span class="fn">on</span>(<span class="str">'mouseenter'</span>, <span class="str">'boundaries-fill'</span>, () => {
  map.<span class="fn">getCanvas</span>().style.cursor = <span class="str">'pointer'</span>;
});

map.<span class="fn">on</span>(<span class="str">'mouseleave'</span>, <span class="str">'boundaries-fill'</span>, () => {
  map.<span class="fn">getCanvas</span>().style.cursor = <span class="str">''</span>;
});</pre>

    <div class="callout callout-info">
        <strong>Explore Interactively</strong>
        Visit the <a href="/vector">TiPG landing page</a> to browse available collections and their schemas.
    </div>

    <div class="footer">
        <a href="/guide/web-developers/maplibre-tiles">Previous: MapLibre Tiles</a> |
        <a href="/guide/web-developers/">Back to Overview</a>
    </div>
    '''
    return _render_page("Vector Features", content, "/guide/web-developers/vector-features")
