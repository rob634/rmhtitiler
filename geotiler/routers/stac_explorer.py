"""
STAC Explorer GUI.

Provides an interactive web interface for browsing STAC collections and items,
with integrated map visualization and JSON viewer.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from geotiler import __version__
from geotiler.config import settings

router = APIRouter(tags=["STAC Explorer"])


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
  --sidebar-width: 320px;
  --panel-height: 300px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: "Open Sans", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--ds-navy);
  background-color: var(--ds-bg);
  height: 100vh;
  overflow: hidden;
}

a { color: var(--ds-blue-primary); text-decoration: none; }
a:hover { color: var(--ds-cyan); }

/* Navbar */
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  background: white;
  border-bottom: 3px solid var(--ds-blue-primary);
  height: 50px;
}

.navbar-brand { font-size: 16px; font-weight: 700; color: var(--ds-navy); }
.navbar-brand span { color: var(--ds-gray); font-weight: 400; font-size: 13px; }
.navbar-links { display: flex; gap: 15px; }
.navbar-links a {
  color: var(--ds-blue-primary);
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 13px;
}
.navbar-links a:hover { background: var(--ds-gray-light); }
.navbar-links a.active { background: var(--ds-blue-primary); color: white; }

/* Main layout */
.main-container {
  display: flex;
  height: calc(100vh - 50px);
}

/* Sidebar */
.sidebar {
  width: var(--sidebar-width);
  background: white;
  border-right: 1px solid var(--ds-gray-light);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  padding: 15px;
  border-bottom: 1px solid var(--ds-gray-light);
  background: var(--ds-bg);
}

.sidebar-title { font-size: 14px; font-weight: 700; margin-bottom: 10px; }

.search-box {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--ds-gray-light);
  border-radius: 4px;
  font-size: 13px;
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.collection-item {
  padding: 12px;
  border: 1px solid var(--ds-gray-light);
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.collection-item:hover { border-color: var(--ds-blue-primary); background: #f8fafc; }
.collection-item.selected { border-color: var(--ds-blue-primary); background: #e8f4fc; }

.collection-title { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
.collection-desc { font-size: 11px; color: var(--ds-gray); line-height: 1.4; }
.collection-meta { font-size: 10px; color: var(--ds-gray); margin-top: 6px; }

/* Map and panel container */
.content-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Map */
#map {
  flex: 1;
  min-height: 200px;
}

/* Bottom panel */
.bottom-panel {
  height: var(--panel-height);
  background: white;
  border-top: 1px solid var(--ds-gray-light);
  display: flex;
  flex-direction: column;
}

.panel-tabs {
  display: flex;
  border-bottom: 1px solid var(--ds-gray-light);
  background: var(--ds-bg);
}

.panel-tab {
  padding: 10px 20px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.panel-tab:hover { background: white; }
.panel-tab.active { border-bottom-color: var(--ds-blue-primary); background: white; }

.panel-content {
  flex: 1;
  overflow: auto;
  padding: 15px;
}

.panel-section { display: none; }
.panel-section.active { display: block; }

/* Items list */
.items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 10px;
}

.item-card {
  padding: 12px;
  border: 1px solid var(--ds-gray-light);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.item-card:hover { border-color: var(--ds-blue-primary); }
.item-card.selected { border-color: var(--ds-blue-primary); background: #e8f4fc; }

.item-id { font-weight: 600; font-size: 12px; margin-bottom: 4px; font-family: monospace; }
.item-date { font-size: 11px; color: var(--ds-gray); }

/* JSON viewer */
.json-viewer {
  font-family: monospace;
  font-size: 12px;
  white-space: pre-wrap;
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 15px;
  border-radius: 4px;
  max-height: 100%;
  overflow: auto;
}

.json-key { color: #9cdcfe; }
.json-string { color: #ce9178; }
.json-number { color: #b5cea8; }
.json-boolean { color: #569cd6; }
.json-null { color: #569cd6; }

/* Assets panel */
.asset-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px;
  border: 1px solid var(--ds-gray-light);
  border-radius: 4px;
  margin-bottom: 8px;
}

.asset-name { font-weight: 600; font-size: 13px; }
.asset-type { font-size: 11px; color: var(--ds-gray); }

.btn {
  display: inline-block;
  padding: 6px 12px;
  background: var(--ds-blue-primary);
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  text-decoration: none;
}

.btn:hover { background: var(--ds-blue-dark); color: white; }
.btn-small { padding: 4px 8px; font-size: 11px; }
.btn-secondary { background: var(--ds-gray); }

/* Status */
.status-bar {
  padding: 8px 15px;
  background: var(--ds-bg);
  border-top: 1px solid var(--ds-gray-light);
  font-size: 12px;
  color: var(--ds-gray);
}

/* Empty states */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--ds-gray);
}

.empty-state h3 { color: var(--ds-navy); margin-bottom: 8px; }

/* Loading */
.loading {
  text-align: center;
  padding: 20px;
  color: var(--ds-gray);
}

.spinner {
  display: inline-block;
  width: 20px;
  height: 20px;
  border: 2px solid var(--ds-gray-light);
  border-top-color: var(--ds-blue-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* Error state */
.error-box {
  background: #fee2e2;
  border: 1px solid var(--ds-status-error);
  border-radius: 4px;
  padding: 15px;
  color: var(--ds-status-error);
}

/* Resize handle */
.resize-handle {
  height: 4px;
  background: var(--ds-gray-light);
  cursor: ns-resize;
}

.resize-handle:hover { background: var(--ds-blue-primary); }
"""

JS = """
// State
let collections = [];
let selectedCollection = null;
let items = [];
let selectedItem = null;
let map = null;
let itemsLayer = null;
let tileLayer = null;

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    initMap();
    await loadCollections();
    initTabs();
});

// Map initialization
function initMap() {
    map = L.map('map').setView([0, 0], 2);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    itemsLayer = L.featureGroup().addTo(map);
}

// Load collections
async function loadCollections() {
    const container = document.getElementById('collections-list');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Loading...</div>';

    try {
        const response = await fetch('/stac/collections');

        if (!response.ok) {
            throw new Error('STAC API not available');
        }

        const data = await response.json();
        collections = data.collections || [];

        renderCollections(collections);

    } catch (error) {
        container.innerHTML = '<div class="error-box">' + error.message + '</div>';
    }
}

// Render collections
function renderCollections(cols) {
    const container = document.getElementById('collections-list');

    if (!cols.length) {
        container.innerHTML = '<div class="empty-state"><h3>No Collections</h3><p>No STAC collections found.</p></div>';
        return;
    }

    let html = '';
    for (const col of cols) {
        const desc = col.description ? col.description.substring(0, 100) + '...' : '';
        const extent = col.extent?.spatial?.bbox?.[0];
        const extentStr = extent ? `Bounds: [${extent.map(n => n.toFixed(1)).join(', ')}]` : '';

        html += `
            <div class="collection-item" data-id="${col.id}" onclick="selectCollection('${col.id}')">
                <div class="collection-title">${col.id}</div>
                <div class="collection-desc">${desc}</div>
                <div class="collection-meta">${extentStr}</div>
            </div>
        `;
    }

    container.innerHTML = html;
}

// Select collection
async function selectCollection(id) {
    // Update UI
    document.querySelectorAll('.collection-item').forEach(el => {
        el.classList.toggle('selected', el.dataset.id === id);
    });

    selectedCollection = collections.find(c => c.id === id);
    selectedItem = null;

    // Zoom to collection extent
    if (selectedCollection?.extent?.spatial?.bbox?.[0]) {
        const [minX, minY, maxX, maxY] = selectedCollection.extent.spatial.bbox[0];
        map.fitBounds([[minY, minX], [maxY, maxX]]);
    }

    // Load items
    await loadItems(id);

    // Switch to items tab
    switchTab('items');
}

// Load items
async function loadItems(collectionId) {
    const container = document.getElementById('items-content');
    container.innerHTML = '<div class="loading"><span class="spinner"></span> Loading items...</div>';

    updateStatus('Loading items from ' + collectionId + '...');

    try {
        const response = await fetch(`/stac/collections/${collectionId}/items?limit=50`);

        if (!response.ok) throw new Error('Failed to load items');

        const data = await response.json();
        items = data.features || [];

        renderItems(items);
        renderItemsOnMap(items);

        updateStatus(`Loaded ${items.length} items from ${collectionId}`);

    } catch (error) {
        container.innerHTML = '<div class="error-box">' + error.message + '</div>';
        updateStatus('Error: ' + error.message);
    }
}

// Render items list
function renderItems(itemsList) {
    const container = document.getElementById('items-content');

    if (!itemsList.length) {
        container.innerHTML = '<div class="empty-state"><h3>No Items</h3><p>This collection has no items.</p></div>';
        return;
    }

    let html = '<div class="items-grid">';
    for (const item of itemsList) {
        const datetime = item.properties?.datetime || 'No date';
        html += `
            <div class="item-card" data-id="${item.id}" onclick="selectItem('${item.id}')">
                <div class="item-id">${item.id}</div>
                <div class="item-date">${datetime}</div>
            </div>
        `;
    }
    html += '</div>';

    container.innerHTML = html;
}

// Render items on map
function renderItemsOnMap(itemsList) {
    itemsLayer.clearLayers();

    for (const item of itemsList) {
        if (item.geometry) {
            const layer = L.geoJSON(item.geometry, {
                style: {
                    color: '#0071BC',
                    weight: 2,
                    fillOpacity: 0.1
                }
            });

            layer.on('click', () => selectItem(item.id));
            layer.bindTooltip(item.id);
            itemsLayer.addLayer(layer);
        }
    }

    if (itemsLayer.getLayers().length > 0) {
        map.fitBounds(itemsLayer.getBounds(), { padding: [20, 20] });
    }
}

// Select item
function selectItem(id) {
    selectedItem = items.find(i => i.id === id);

    // Update UI
    document.querySelectorAll('.item-card').forEach(el => {
        el.classList.toggle('selected', el.dataset.id === id);
    });

    // Highlight on map
    itemsLayer.eachLayer(layer => {
        const itemId = layer.getTooltip()?.getContent();
        if (itemId === id) {
            layer.setStyle({ color: '#00A3DA', weight: 3, fillOpacity: 0.3 });
            map.fitBounds(layer.getBounds(), { padding: [50, 50] });
        } else {
            layer.setStyle({ color: '#0071BC', weight: 2, fillOpacity: 0.1 });
        }
    });

    // Update panels
    renderJSON(selectedItem);
    renderAssets(selectedItem);

    updateStatus('Selected: ' + id);
}

// Render JSON
function renderJSON(obj) {
    const container = document.getElementById('json-content');

    if (!obj) {
        container.innerHTML = '<div class="empty-state">Select an item to view its JSON</div>';
        return;
    }

    const html = syntaxHighlight(JSON.stringify(obj, null, 2));
    container.innerHTML = '<pre class="json-viewer">' + html + '</pre>';
}

// Syntax highlighting for JSON
function syntaxHighlight(json) {
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return json.replace(
        /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
        function (match) {
            let cls = 'json-number';
            if (/^"/.test(match)) {
                if (/:$/.test(match)) {
                    cls = 'json-key';
                } else {
                    cls = 'json-string';
                }
            } else if (/true|false/.test(match)) {
                cls = 'json-boolean';
            } else if (/null/.test(match)) {
                cls = 'json-null';
            }
            return '<span class="' + cls + '">' + match + '</span>';
        }
    );
}

// Render assets
function renderAssets(item) {
    const container = document.getElementById('assets-content');

    if (!item || !item.assets) {
        container.innerHTML = '<div class="empty-state">Select an item to view its assets</div>';
        return;
    }

    let html = '';
    for (const [key, asset] of Object.entries(item.assets)) {
        const type = asset.type || 'unknown';
        const isCog = type.includes('tiff') || type.includes('geotiff') || key.includes('cog');

        html += `
            <div class="asset-item">
                <div>
                    <div class="asset-name">${key}</div>
                    <div class="asset-type">${type}</div>
                </div>
                <div>
                    ${isCog ? `<button class="btn btn-small" onclick="viewAssetOnMap('${encodeURIComponent(asset.href)}')">View on Map</button>` : ''}
                    <a href="${asset.href}" target="_blank" class="btn btn-small btn-secondary">Open</a>
                </div>
            </div>
        `;
    }

    container.innerHTML = html || '<div class="empty-state">No assets</div>';
}

// View asset on map
function viewAssetOnMap(encodedHref) {
    const href = decodeURIComponent(encodedHref);

    // Remove existing tile layer
    if (tileLayer) {
        map.removeLayer(tileLayer);
    }

    // Add COG tile layer
    const tileUrl = '/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=' + encodeURIComponent(href);

    tileLayer = L.tileLayer(tileUrl, {
        maxZoom: 22,
        attribution: 'COG Tiles'
    }).addTo(map);

    updateStatus('Viewing: ' + href.split('/').pop());
}

// Tab switching
function initTabs() {
    document.querySelectorAll('.panel-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });
}

function switchTab(tabName) {
    document.querySelectorAll('.panel-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tabName);
    });
    document.querySelectorAll('.panel-section').forEach(s => {
        s.classList.toggle('active', s.id === tabName + '-content');
    });
}

// Status bar
function updateStatus(message) {
    document.getElementById('status-text').textContent = message;
}

// Search filter
document.getElementById('collection-search')?.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    const filtered = collections.filter(c =>
        c.id.toLowerCase().includes(query) ||
        (c.description && c.description.toLowerCase().includes(query))
    );
    renderCollections(filtered);
});
"""


def _render_page() -> str:
    """Render the STAC Explorer page."""
    stac_enabled = settings.enable_stac_api and settings.enable_tipg

    if not stac_enabled:
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STAC Explorer - geotiler</title>
    <style>{CSS}</style>
</head>
<body>
    <nav class="navbar">
        <a href="/" class="navbar-brand">geotiler <span>v{__version__}</span></a>
        <div class="navbar-links">
            <a href="/cog/">COG</a>
            <a href="/xarray/">XArray</a>
            <a href="/searches/">Searches</a>
            <a href="/vector">Vector</a>
            <a href="/stac/" class="active">STAC</a>
            <a href="/guide/">Guide</a>
            <a href="/docs">API Docs</a>
        </div>
    </nav>
    <div style="padding: 50px; text-align: center;">
        <h2>STAC API Not Enabled</h2>
        <p style="color: var(--ds-gray); margin-top: 10px;">
            The STAC API is not enabled on this instance. Set <code>ENABLE_STAC_API=true</code>
            and <code>ENABLE_TIPG=true</code> to enable it.
        </p>
        <p style="margin-top: 20px;">
            <a href="/">Return to Home</a>
        </p>
    </div>
</body>
</html>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>STAC Explorer - geotiler</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>{CSS}</style>
</head>
<body>
    <nav class="navbar">
        <a href="/" class="navbar-brand">geotiler <span>v{__version__}</span></a>
        <div class="navbar-links">
            <a href="/cog/">COG</a>
            <a href="/xarray/">XArray</a>
            <a href="/searches/">Searches</a>
            <a href="/vector">Vector</a>
            <a href="/stac/" class="active">STAC</a>
            <a href="/guide/">Guide</a>
            <a href="/docs">API Docs</a>
        </div>
    </nav>

    <div class="main-container">
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="sidebar-header">
                <div class="sidebar-title">Collections</div>
                <input type="text" id="collection-search" class="search-box" placeholder="Filter collections...">
            </div>
            <div class="sidebar-content" id="collections-list">
                <div class="loading"><span class="spinner"></span> Loading...</div>
            </div>
        </div>

        <!-- Content area -->
        <div class="content-area">
            <!-- Map -->
            <div id="map"></div>

            <!-- Resize handle -->
            <div class="resize-handle"></div>

            <!-- Bottom panel -->
            <div class="bottom-panel">
                <div class="panel-tabs">
                    <div class="panel-tab active" data-tab="items">Items</div>
                    <div class="panel-tab" data-tab="json">JSON</div>
                    <div class="panel-tab" data-tab="assets">Assets</div>
                </div>
                <div class="panel-content">
                    <div id="items-content" class="panel-section active">
                        <div class="empty-state">
                            <h3>Select a Collection</h3>
                            <p>Choose a collection from the sidebar to view its items.</p>
                        </div>
                    </div>
                    <div id="json-content" class="panel-section">
                        <div class="empty-state">Select an item to view its JSON</div>
                    </div>
                    <div id="assets-content" class="panel-section">
                        <div class="empty-state">Select an item to view its assets</div>
                    </div>
                </div>
            </div>

            <!-- Status bar -->
            <div class="status-bar">
                <span id="status-text">Ready</span>
            </div>
        </div>
    </div>

    <script>{JS}</script>
</body>
</html>'''


@router.get("/stac/", response_class=HTMLResponse, include_in_schema=False)
async def stac_explorer():
    """
    STAC Explorer GUI.

    Interactive web interface for browsing STAC collections and items:
    - Collection sidebar with search/filter
    - Map view with item footprints (Leaflet)
    - Item details with JSON viewer
    - Asset list with "View on Map" for COG assets
    """
    return _render_page()
