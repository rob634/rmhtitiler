"""
COG Landing Page.

Provides an interactive landing page for exploring Cloud Optimized GeoTIFFs.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from geotiler import __version__

router = APIRouter(tags=["Landing Pages"])


# Reuse CSS from admin module for consistent styling
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

.navbar-brand {
  font-size: 18px;
  font-weight: 700;
  color: var(--ds-navy);
}

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

.container { max-width: 900px; margin: 0 auto; padding: 30px; }

.page-header {
  background: white;
  border-radius: 8px;
  padding: 25px;
  margin-bottom: 25px;
  border-left: 4px solid var(--ds-blue-primary);
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

.form-group { margin-bottom: 15px; }
.form-label { display: block; font-weight: 600; margin-bottom: 5px; font-size: 13px; }
.form-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--ds-gray-light);
  border-radius: 4px;
  font-size: 14px;
}
.form-input:focus { outline: none; border-color: var(--ds-blue-primary); }
.form-hint { font-size: 12px; color: var(--ds-gray); margin-top: 5px; }

.btn {
  display: inline-block;
  padding: 10px 20px;
  background: var(--ds-blue-primary);
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  transition: background 0.2s;
}
.btn:hover { background: var(--ds-blue-dark); color: white; text-decoration: none; }
.btn-secondary { background: var(--ds-gray); }
.btn-secondary:hover { background: var(--ds-navy); }

.btn-group { display: flex; gap: 10px; flex-wrap: wrap; }

.endpoint-list { list-style: none; }
.endpoint-list li {
  padding: 10px 0;
  border-bottom: 1px solid var(--ds-gray-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.endpoint-list li:last-child { border-bottom: none; }
.endpoint-path { font-family: monospace; background: var(--ds-gray-light); padding: 3px 8px; border-radius: 3px; }
.endpoint-desc { color: var(--ds-gray); font-size: 13px; }

.sample-urls { list-style: none; }
.sample-urls li { padding: 8px 0; }
.sample-urls code {
  display: block;
  background: var(--ds-gray-light);
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
  cursor: pointer;
}
.sample-urls code:hover { background: #dde1e5; }

#result {
  margin-top: 20px;
  padding: 15px;
  background: var(--ds-gray-light);
  border-radius: 4px;
  display: none;
}
#result.show { display: block; }
#result pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 12px;
  max-height: 300px;
  overflow-y: auto;
}

.footer {
  text-align: center;
  padding: 20px;
  color: var(--ds-gray);
  font-size: 12px;
}
"""

JS = """
function setUrl(url) {
    document.getElementById('cog-url').value = url;
}

function getInfo() {
    const url = document.getElementById('cog-url').value;
    if (!url) { alert('Please enter a COG URL'); return; }
    window.location.href = '/cog/info?url=' + encodeURIComponent(url);
}

function openViewer() {
    const url = document.getElementById('cog-url').value;
    if (!url) { alert('Please enter a COG URL'); return; }
    window.location.href = '/cog/WebMercatorQuad/map?url=' + encodeURIComponent(url);
}

function getTileJSON() {
    const url = document.getElementById('cog-url').value;
    if (!url) { alert('Please enter a COG URL'); return; }
    window.location.href = '/cog/WebMercatorQuad/tilejson.json?url=' + encodeURIComponent(url);
}

function getStatistics() {
    const url = document.getElementById('cog-url').value;
    if (!url) { alert('Please enter a COG URL'); return; }
    window.location.href = '/cog/statistics?url=' + encodeURIComponent(url);
}
"""


def _render_page() -> str:
    """Render the COG landing page."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>COG Explorer - geotiler</title>
    <style>{CSS}</style>
</head>
<body>
    <nav class="navbar">
        <a href="/" class="navbar-brand">geotiler <span>v{__version__}</span></a>
        <div class="navbar-links">
            <a href="/cog/" class="active">COG</a>
            <a href="/xarray/">XArray</a>
            <a href="/searches/">Searches</a>
            <a href="/vector">Vector</a>
            <a href="/stac/">STAC</a>
            <a href="/guide/">Guide</a>
            <a href="/docs">API Docs</a>
        </div>
    </nav>

    <div class="container">
        <div class="page-header">
            <h1 class="page-title">Cloud Optimized GeoTIFF Explorer</h1>
            <p class="page-description">
                Explore and visualize Cloud Optimized GeoTIFFs (COGs) from any accessible URL.
                Supports Azure Blob Storage with OAuth, HTTP URLs, and /vsiaz/ paths.
            </p>
        </div>

        <div class="card">
            <h2 class="card-title">Explore a COG</h2>
            <div class="form-group">
                <label class="form-label" for="cog-url">COG URL</label>
                <input type="text" id="cog-url" class="form-input"
                       placeholder="https://example.com/path/to/file.tif"
                       value="">
                <p class="form-hint">
                    Enter a URL to a Cloud Optimized GeoTIFF. Supports HTTPS, Azure Blob (/vsiaz/), and S3 (/vsis3/) paths.
                </p>
            </div>
            <div class="btn-group">
                <button class="btn" onclick="getInfo()">Get Info</button>
                <button class="btn" onclick="openViewer()">Open Viewer</button>
                <button class="btn btn-secondary" onclick="getTileJSON()">TileJSON</button>
                <button class="btn btn-secondary" onclick="getStatistics()">Statistics</button>
            </div>
        </div>

        <div class="card">
            <h2 class="card-title">Sample COG URLs</h2>
            <p style="color: var(--ds-gray); margin-bottom: 15px; font-size: 13px;">
                Click any URL to use it in the explorer above:
            </p>
            <ul class="sample-urls">
                <li>
                    <code onclick="setUrl('https://data.geo.admin.ch/ch.swisstopo.swissalti3d/swissalti3d_2019_2573-1085/swissalti3d_2019_2573-1085_0.5_2056_5728.tif')">
                        Swiss Terrain (SRTM) - data.geo.admin.ch
                    </code>
                </li>
                <li>
                    <code onclick="setUrl('https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/36/Q/WD/2020/7/S2A_36QWD_20200701_0_L2A/TCI.tif')">
                        Sentinel-2 True Color - AWS Open Data
                    </code>
                </li>
            </ul>
        </div>

        <div class="card">
            <h2 class="card-title">Available Endpoints</h2>
            <ul class="endpoint-list">
                <li>
                    <span class="endpoint-path">GET /cog/info</span>
                    <span class="endpoint-desc">Get COG metadata (bounds, CRS, bands)</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /cog/statistics</span>
                    <span class="endpoint-desc">Band statistics (min, max, mean, std)</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /cog/tiles/{{tms}}/{{z}}/{{x}}/{{y}}</span>
                    <span class="endpoint-desc">XYZ map tiles</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /cog/{{tms}}/tilejson.json</span>
                    <span class="endpoint-desc">TileJSON for web maps</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /cog/{{tms}}/map</span>
                    <span class="endpoint-desc">Interactive map viewer</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /cog/point/{{lon}},{{lat}}</span>
                    <span class="endpoint-desc">Value at point</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /cog/preview</span>
                    <span class="endpoint-desc">Static preview image</span>
                </li>
            </ul>
            <p style="margin-top: 15px;">
                <a href="/docs#/Cloud%20Optimized%20GeoTIFF">View full API documentation</a>
            </p>
        </div>
    </div>

    <footer class="footer">
        <a href="https://github.com/developmentseed/titiler">TiTiler</a> |
        <a href="/">Home</a> |
        <a href="/docs">API Docs</a>
    </footer>

    <script>{JS}</script>
</body>
</html>'''


@router.get("/cog/", response_class=HTMLResponse, include_in_schema=False)
async def cog_landing():
    """
    COG Explorer landing page.

    Provides an interface to explore Cloud Optimized GeoTIFFs with:
    - URL input form
    - Quick action buttons (info, viewer, tilejson, statistics)
    - Sample COG URLs
    - Endpoint reference
    """
    return _render_page()
