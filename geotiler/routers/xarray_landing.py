"""
XArray Landing Page.

Provides an interactive landing page for exploring Zarr and NetCDF datasets.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from geotiler import __version__
from geotiler.config import settings

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

.container { max-width: 900px; margin: 0 auto; padding: 30px; }

.page-header {
  background: white;
  border-radius: 8px;
  padding: 25px;
  margin-bottom: 25px;
  border-left: 4px solid var(--ds-cyan);
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.page-title { font-size: 24px; font-weight: 700; margin-bottom: 10px; }
.page-description { color: var(--ds-gray); }

.feature-badge {
  display: inline-block;
  background: var(--ds-status-healthy);
  color: white;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  margin-left: 10px;
  vertical-align: middle;
}

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

.form-row { display: flex; gap: 15px; }
.form-row .form-group { flex: 1; }

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
.sample-urls .sample-label { font-size: 12px; color: var(--ds-gray); margin-bottom: 3px; }

.info-box {
  background: #e8f4fc;
  border: 1px solid var(--ds-cyan);
  border-radius: 4px;
  padding: 12px 15px;
  margin-bottom: 20px;
  font-size: 13px;
}
.info-box strong { color: var(--ds-navy); }

.footer {
  text-align: center;
  padding: 20px;
  color: var(--ds-gray);
  font-size: 12px;
}
"""

JS = """
function setUrl(url, variable) {
    document.getElementById('zarr-url').value = url;
    if (variable) {
        document.getElementById('variable').value = variable;
    }
}

function getInfo() {
    const url = document.getElementById('zarr-url').value;
    if (!url) { alert('Please enter a Zarr/NetCDF URL'); return; }
    const variable = document.getElementById('variable').value;

    let endpoint = '/xarray/info?url=' + encodeURIComponent(url);
    if (variable) endpoint += '&variable=' + encodeURIComponent(variable);

    window.location.href = endpoint;
}

function getVariables() {
    const url = document.getElementById('zarr-url').value;
    if (!url) { alert('Please enter a Zarr/NetCDF URL'); return; }
    window.location.href = '/xarray/variables?url=' + encodeURIComponent(url);
}

function openViewer() {
    const url = document.getElementById('zarr-url').value;
    if (!url) { alert('Please enter a Zarr/NetCDF URL'); return; }

    const variable = document.getElementById('variable').value;
    const timeIdx = document.getElementById('time-idx').value;

    let endpoint = '/xarray/WebMercatorQuad/map?url=' + encodeURIComponent(url);
    if (variable) endpoint += '&variable=' + encodeURIComponent(variable);
    if (timeIdx) endpoint += '&datetime=' + encodeURIComponent(timeIdx);

    window.location.href = endpoint;
}

function getTileJSON() {
    const url = document.getElementById('zarr-url').value;
    if (!url) { alert('Please enter a Zarr/NetCDF URL'); return; }

    const variable = document.getElementById('variable').value;

    let endpoint = '/xarray/WebMercatorQuad/tilejson.json?url=' + encodeURIComponent(url);
    if (variable) endpoint += '&variable=' + encodeURIComponent(variable);

    window.location.href = endpoint;
}
"""


def _render_page() -> str:
    """Render the XArray landing page."""
    pc_badge = ""
    pc_section = ""

    if settings.enable_planetary_computer:
        pc_badge = '<span class="feature-badge">Planetary Computer</span>'
        pc_section = '''
        <div class="info-box">
            <strong>Planetary Computer Integration Enabled</strong><br>
            This instance supports automatic token signing for Microsoft Planetary Computer datasets.
            Use <code>/pc/*</code> endpoints for PC-hosted Zarr data.
        </div>
        '''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>XArray Explorer - geotiler</title>
    <style>{CSS}</style>
</head>
<body>
    <nav class="navbar">
        <a href="/" class="navbar-brand">geotiler <span>v{__version__}</span></a>
        <div class="navbar-links">
            <a href="/cog/">COG</a>
            <a href="/xarray/" class="active">XArray</a>
            <a href="/searches/">Searches</a>
            <a href="/vector">Vector</a>
            <a href="/stac/">STAC</a>
            <a href="/guide/">Guide</a>
            <a href="/docs">API Docs</a>
        </div>
    </nav>

    <div class="container">
        <div class="page-header">
            <h1 class="page-title">XArray / Zarr Explorer {pc_badge}</h1>
            <p class="page-description">
                Explore and visualize multidimensional datasets in Zarr or NetCDF format.
                Powered by <a href="https://github.com/developmentseed/titiler-xarray">titiler-xarray</a>.
            </p>
        </div>

        {pc_section}

        <div class="card">
            <h2 class="card-title">Explore a Dataset</h2>
            <div class="form-group">
                <label class="form-label" for="zarr-url">Dataset URL</label>
                <input type="text" id="zarr-url" class="form-input"
                       placeholder="https://example.com/path/to/data.zarr"
                       value="">
                <p class="form-hint">
                    Enter a URL to a Zarr store or NetCDF file. Supports HTTPS, Azure Blob, and S3 paths.
                </p>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label" for="variable">Variable Name</label>
                    <input type="text" id="variable" class="form-input"
                           placeholder="e.g., temperature, precipitation">
                    <p class="form-hint">
                        Leave empty to auto-select first variable, or use "List Variables" to discover.
                    </p>
                </div>
                <div class="form-group">
                    <label class="form-label" for="time-idx">Time Index (optional)</label>
                    <input type="text" id="time-idx" class="form-input"
                           placeholder="e.g., 0 or 2024-01-15">
                    <p class="form-hint">
                        Index or datetime string for temporal dimension.
                    </p>
                </div>
            </div>
            <div class="btn-group">
                <button class="btn" onclick="openViewer()">Open Viewer</button>
                <button class="btn btn-secondary" onclick="getVariables()">List Variables</button>
                <button class="btn btn-secondary" onclick="getInfo()">Get Info</button>
                <button class="btn btn-secondary" onclick="getTileJSON()">TileJSON</button>
            </div>
        </div>

        <div class="card">
            <h2 class="card-title">Sample Datasets</h2>
            <p style="color: var(--ds-gray); margin-bottom: 15px; font-size: 13px;">
                Click any dataset to load it in the explorer above:
            </p>
            <ul class="sample-urls">
                <li>
                    <div class="sample-label">ERA5 Temperature - Planetary Computer</div>
                    <code onclick="setUrl('https://cpdataeuwest.blob.core.windows.net/cpdata/raw/era5/pds/2020/01/era5-pds-2020-01-fc.zarr', 't2m')">
                        ERA5 2m Temperature (t2m) - January 2020
                    </code>
                </li>
                <li>
                    <div class="sample-label">NOAA Global Forecast System</div>
                    <code onclick="setUrl('https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20240115/00/atmos/gfs.t00z.pgrb2.0p25.f000.zarr', 'TMP_2maboveground')">
                        GFS 2m Temperature - AWS Open Data
                    </code>
                </li>
            </ul>
        </div>

        <div class="card">
            <h2 class="card-title">Available Endpoints</h2>
            <ul class="endpoint-list">
                <li>
                    <span class="endpoint-path">GET /xarray/variables</span>
                    <span class="endpoint-desc">List all variables in the dataset</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /xarray/info</span>
                    <span class="endpoint-desc">Get variable metadata (dims, shape, dtype)</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /xarray/tiles/{{tms}}/{{z}}/{{x}}/{{y}}</span>
                    <span class="endpoint-desc">XYZ map tiles</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /xarray/{{tms}}/tilejson.json</span>
                    <span class="endpoint-desc">TileJSON for web maps</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /xarray/{{tms}}/map</span>
                    <span class="endpoint-desc">Interactive map viewer</span>
                </li>
                <li>
                    <span class="endpoint-path">GET /xarray/point/{{lon}},{{lat}}</span>
                    <span class="endpoint-desc">Value at point</span>
                </li>
            </ul>
            <p style="margin-top: 15px;">
                <a href="/docs#/Multidimensional%20(Zarr/NetCDF)">View full API documentation</a>
            </p>
        </div>

        <div class="card">
            <h2 class="card-title">Common Query Parameters</h2>
            <ul class="endpoint-list">
                <li>
                    <span class="endpoint-path">url</span>
                    <span class="endpoint-desc">Zarr store or NetCDF URL (required)</span>
                </li>
                <li>
                    <span class="endpoint-path">variable</span>
                    <span class="endpoint-desc">Variable name to visualize</span>
                </li>
                <li>
                    <span class="endpoint-path">datetime</span>
                    <span class="endpoint-desc">Time index or datetime string</span>
                </li>
                <li>
                    <span class="endpoint-path">colormap_name</span>
                    <span class="endpoint-desc">Colormap (viridis, plasma, inferno, magma, etc.)</span>
                </li>
                <li>
                    <span class="endpoint-path">rescale</span>
                    <span class="endpoint-desc">Min,max value scaling (e.g., 0,100)</span>
                </li>
                <li>
                    <span class="endpoint-path">decode_times</span>
                    <span class="endpoint-desc">Set to false to disable time decoding</span>
                </li>
            </ul>
        </div>
    </div>

    <footer class="footer">
        <a href="https://github.com/developmentseed/titiler-xarray">titiler-xarray</a> |
        <a href="/">Home</a> |
        <a href="/docs">API Docs</a>
    </footer>

    <script>{JS}</script>
</body>
</html>'''


@router.get("/xarray/", response_class=HTMLResponse, include_in_schema=False)
async def xarray_landing():
    """
    XArray Explorer landing page.

    Provides an interface to explore Zarr and NetCDF datasets with:
    - URL input form with variable and time parameters
    - Quick action buttons (variables, info, viewer, tilejson)
    - Sample dataset URLs
    - Endpoint and parameter reference
    """
    return _render_page()
