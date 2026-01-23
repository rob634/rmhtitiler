# Map Viewer Implementation Plan

**Status:** TODO
**Priority:** Feature enhancement
**Estimated Effort:** 1-2 hours

---

## Overview

A unified map viewer at `/map` that combines all geotiler services into a single interactive interface using MapLibre GL JS. Users can discover available layers, add them to the map, and remove them as needed.

### Goals

1. **See available services** - Auto-discover TiPG vector collections and STAC searches
2. **Add layers to map** - Click to add any discovered layer or enter custom URLs
3. **Remove from map** - Simple layer management with toggle/remove controls
4. **No persistent state** - Configure and forget; refresh resets the map

---

## Architecture

### Layout (Three-Panel)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Navbar                                                    [Map]    │
├─────────────────┬───────────────────────────┬───────────────────────┤
│                 │                           │                       │
│  LAYER CATALOG  │                           │  ACTIVE LAYERS        │
│  (280px)        │      MapLibre GL Map      │  (260px)              │
│                 │                           │                       │
│  ▼ Vector       │                           │  ┌─────────────────┐  │
│    parcels  [+] │                           │  │ ☑ parcels    [×]│  │
│    roads    [+] │                           │  │ ☑ dem-cog   [×]│  │
│    rivers   [+] │                           │  │ ☐ flood     [×]│  │
│                 │                           │  └─────────────────┘  │
│  ▼ STAC Searches│                           │                       │
│    flood-risk[+]│                           │  Layer opacity:       │
│                 │                           │  [────●────] 80%      │
│  ▼ Raster (URL) │                           │                       │
│  ┌────────────┐ │                           │                       │
│  │ COG URL... │ │                           │                       │
│  └────────────┘ │                           │                       │
│  [Add COG]      │                           │                       │
│                 │                           │                       │
│  ┌────────────┐ │                           │                       │
│  │ Zarr URL.. │ │                           │                       │
│  └────────────┘ │                           │                       │
│  [Add Zarr]     │                           │                       │
│                 │                           │                       │
├─────────────────┴───────────────────────────┴───────────────────────┤
│  Status: 3 layers | Zoom: 12 | Center: -1.234, 36.567               │
└─────────────────────────────────────────────────────────────────────┘
```

### Layer Types

| Type | Source | Tile URL Pattern | Format |
|------|--------|------------------|--------|
| **TiPG Vector** | `/vector/collections` | `/vector/collections/{id}/tiles/WebMercatorQuad/{z}/{x}/{y}.pbf` | MVT |
| **STAC Search** | `/searches` | `/searches/{search_id}/tiles/WebMercatorQuad/{z}/{x}/{y}.png` | Raster |
| **COG** | User URL | `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={url}` | Raster |
| **XArray** | User URL | `/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={url}` | Raster |

---

## File Structure

```
geotiler/
├── routers/
│   └── map_viewer.py              # NEW: Router for /map endpoint
├── templates/
│   └── pages/
│       └── map/
│           └── viewer.html        # NEW: Map viewer template
├── static/
│   └── js/
│       └── map-viewer.js          # NEW: MapLibre integration
└── components/
    └── navbar.html                # MODIFY: Add Map link
```

---

## Implementation Details

### Phase 1: Router (`geotiler/routers/map_viewer.py`)

```python
"""
Map Viewer - Unified layer viewer for all geotiler services.

Provides a MapLibre GL JS interface for:
- TiPG vector collections (MVT tiles)
- STAC searches (raster tiles)
- COG/XArray URLs (raster tiles)
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from geotiler.config import settings
from geotiler.templates_utils import templates, get_template_context

router = APIRouter(tags=["Map Viewer"])


@router.get("/map", response_class=HTMLResponse, include_in_schema=False)
async def map_viewer(request: Request):
    """
    Unified map viewer page.

    Auto-discovers:
    - TiPG vector collections (if ENABLE_TIPG=true)
    - STAC searches (if ENABLE_STAC_API=true)
    """
    context = get_template_context(
        request,
        nav_active="/map",
        tipg_enabled=settings.enable_tipg,
        stac_enabled=settings.enable_stac_api,
    )
    return templates.TemplateResponse("pages/map/viewer.html", context)
```

### Phase 2: Template (`geotiler/templates/pages/map/viewer.html`)

```html
{% extends "base.html" %}

{% block title %}Map Viewer{% endblock %}

{% block main_class %}map-viewer-page{% endblock %}

{% block head %}
<!-- MapLibre GL JS -->
<link href="https://unpkg.com/maplibre-gl@4.1.2/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl@4.1.2/dist/maplibre-gl.js"></script>
<style>
/* Map Viewer Layout */
.map-viewer-page {
    display: flex;
    height: calc(100vh - 50px);
    padding: 0;
    max-width: none;
}

/* Left Sidebar - Layer Catalog */
.layer-catalog {
    width: 280px;
    background: var(--ds-white);
    border-right: 1px solid var(--ds-gray-light);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.catalog-header {
    padding: 15px;
    border-bottom: 1px solid var(--ds-gray-light);
    background: var(--ds-bg);
}

.catalog-header h2 {
    font-size: 14px;
    font-weight: 700;
    margin: 0;
}

.catalog-content {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
}

.catalog-section {
    margin-bottom: 15px;
}

.section-header {
    display: flex;
    align-items: center;
    padding: 8px 10px;
    background: var(--ds-bg);
    border-radius: 4px;
    cursor: pointer;
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--ds-gray);
}

.section-header:hover {
    background: var(--ds-gray-light);
}

.section-header .arrow {
    margin-right: 8px;
    transition: transform 0.2s;
}

.section-header.collapsed .arrow {
    transform: rotate(-90deg);
}

.section-content {
    padding: 8px 0;
}

.section-content.collapsed {
    display: none;
}

.layer-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 10px;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.2s;
}

.layer-item:hover {
    background: var(--ds-bg);
}

.layer-name {
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.layer-add-btn {
    background: var(--ds-blue-primary);
    color: white;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.2s;
}

.layer-item:hover .layer-add-btn {
    opacity: 1;
}

.layer-add-btn:hover {
    background: var(--ds-blue-dark);
}

/* URL Input Section */
.url-input-group {
    padding: 10px;
    background: var(--ds-bg);
    border-radius: 4px;
    margin-top: 8px;
}

.url-input {
    width: 100%;
    padding: 8px;
    border: 1px solid var(--ds-gray-light);
    border-radius: 4px;
    font-size: 12px;
    font-family: var(--font-mono);
    margin-bottom: 8px;
}

.url-input:focus {
    outline: none;
    border-color: var(--ds-blue-primary);
}

.url-add-btn {
    width: 100%;
    padding: 8px;
    background: var(--ds-blue-primary);
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 12px;
    cursor: pointer;
}

.url-add-btn:hover {
    background: var(--ds-blue-dark);
}

/* Map Container */
.map-container {
    flex: 1;
    position: relative;
}

#map {
    width: 100%;
    height: 100%;
}

/* Right Sidebar - Active Layers */
.active-layers {
    width: 260px;
    background: var(--ds-white);
    border-left: 1px solid var(--ds-gray-light);
    display: flex;
    flex-direction: column;
}

.layers-header {
    padding: 15px;
    border-bottom: 1px solid var(--ds-gray-light);
    background: var(--ds-bg);
}

.layers-header h2 {
    font-size: 14px;
    font-weight: 700;
    margin: 0;
}

.layers-list {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
}

.active-layer {
    display: flex;
    align-items: center;
    padding: 10px;
    border: 1px solid var(--ds-gray-light);
    border-radius: 6px;
    margin-bottom: 8px;
    background: var(--ds-white);
}

.active-layer.vector {
    border-left: 3px solid var(--ds-cyan);
}

.active-layer.raster {
    border-left: 3px solid var(--ds-gold);
}

.layer-visibility {
    margin-right: 10px;
}

.layer-info {
    flex: 1;
    overflow: hidden;
}

.layer-title {
    font-size: 13px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.layer-type {
    font-size: 11px;
    color: var(--ds-gray);
}

.layer-remove {
    background: none;
    border: none;
    color: var(--ds-gray);
    cursor: pointer;
    padding: 4px;
    font-size: 16px;
}

.layer-remove:hover {
    color: var(--ds-error);
}

/* Layer Controls */
.layer-controls {
    padding: 15px;
    border-top: 1px solid var(--ds-gray-light);
}

.opacity-control label {
    font-size: 12px;
    color: var(--ds-gray);
    display: block;
    margin-bottom: 5px;
}

.opacity-slider {
    width: 100%;
}

/* Empty State */
.empty-layers {
    text-align: center;
    padding: 30px 15px;
    color: var(--ds-gray);
}

.empty-layers p {
    font-size: 13px;
    margin: 0;
}

/* Status Bar */
.status-bar {
    padding: 8px 15px;
    background: var(--ds-bg);
    border-top: 1px solid var(--ds-gray-light);
    font-size: 12px;
    color: var(--ds-gray);
    display: flex;
    justify-content: space-between;
}

/* Loading State */
.loading-spinner {
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid var(--ds-gray-light);
    border-top-color: var(--ds-blue-primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* Badge for layer type */
.type-badge {
    font-size: 9px;
    padding: 2px 5px;
    border-radius: 3px;
    text-transform: uppercase;
    font-weight: 600;
}

.type-badge.mvt {
    background: #e0f7fa;
    color: #00838f;
}

.type-badge.raster {
    background: #fff8e1;
    color: #f57c00;
}
</style>
{% endblock %}

{% block content %}
<!-- Left Sidebar: Layer Catalog -->
<aside class="layer-catalog">
    <div class="catalog-header">
        <h2>Layer Catalog</h2>
    </div>
    <div class="catalog-content">
        <!-- Vector Collections (TiPG) -->
        {% if tipg_enabled %}
        <div class="catalog-section">
            <div class="section-header" onclick="toggleSection(this)">
                <span class="arrow">▼</span> Vector Collections
            </div>
            <div class="section-content" id="vector-collections">
                <div class="loading"><span class="loading-spinner"></span> Loading...</div>
            </div>
        </div>
        {% endif %}

        <!-- STAC Searches -->
        {% if stac_enabled %}
        <div class="catalog-section">
            <div class="section-header" onclick="toggleSection(this)">
                <span class="arrow">▼</span> STAC Searches
            </div>
            <div class="section-content" id="stac-searches">
                <div class="loading"><span class="loading-spinner"></span> Loading...</div>
            </div>
        </div>
        {% endif %}

        <!-- COG URL Input -->
        <div class="catalog-section">
            <div class="section-header" onclick="toggleSection(this)">
                <span class="arrow">▼</span> COG (URL)
            </div>
            <div class="section-content">
                <div class="url-input-group">
                    <input type="text" id="cog-url" class="url-input" placeholder="https://example.com/file.tif">
                    <button class="url-add-btn" onclick="addCogLayer()">Add COG Layer</button>
                </div>
            </div>
        </div>

        <!-- XArray URL Input -->
        <div class="catalog-section">
            <div class="section-header" onclick="toggleSection(this)">
                <span class="arrow">▼</span> Zarr/NetCDF (URL)
            </div>
            <div class="section-content">
                <div class="url-input-group">
                    <input type="text" id="zarr-url" class="url-input" placeholder="https://example.com/data.zarr">
                    <input type="text" id="zarr-variable" class="url-input" placeholder="variable (e.g., temperature)" style="margin-top: 4px;">
                    <button class="url-add-btn" onclick="addZarrLayer()">Add Zarr Layer</button>
                </div>
            </div>
        </div>
    </div>
</aside>

<!-- Map -->
<div class="map-container">
    <div id="map"></div>
</div>

<!-- Right Sidebar: Active Layers -->
<aside class="active-layers">
    <div class="layers-header">
        <h2>Active Layers</h2>
    </div>
    <div class="layers-list" id="active-layers-list">
        <div class="empty-layers">
            <p>No layers added yet.</p>
            <p>Select layers from the catalog.</p>
        </div>
    </div>
    <div class="layer-controls" id="layer-controls" style="display: none;">
        <div class="opacity-control">
            <label>Selected Layer Opacity</label>
            <input type="range" class="opacity-slider" id="opacity-slider" min="0" max="100" value="100" onchange="updateOpacity(this.value)">
        </div>
    </div>
</aside>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', path='js/map-viewer.js') }}"></script>
<script>
// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    initMapViewer({
        tipgEnabled: {{ tipg_enabled | tojson }},
        stacEnabled: {{ stac_enabled | tojson }}
    });
});
</script>
{% endblock %}
```

### Phase 3: JavaScript (`geotiler/static/js/map-viewer.js`)

```javascript
/**
 * Map Viewer - MapLibre GL JS integration for geotiler
 *
 * Handles:
 * - Map initialization with basemap
 * - Vector tile layers (TiPG MVT)
 * - Raster tile layers (TiTiler COG/XArray/STAC)
 * - Layer management (add/remove/toggle)
 */

// Global state
let map = null;
let activeLayers = [];
let layerCounter = 0;
let selectedLayerId = null;

// Vector style colors (cycle through for different layers)
const VECTOR_COLORS = [
    '#0071BC', '#00A3DA', '#059669', '#d97706',
    '#dc2626', '#7c3aed', '#db2777', '#0891b2'
];

/**
 * Initialize the map viewer
 */
function initMapViewer(config) {
    // Initialize MapLibre map
    map = new maplibregl.Map({
        container: 'map',
        style: {
            version: 8,
            sources: {
                'osm': {
                    type: 'raster',
                    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                    tileSize: 256,
                    attribution: '&copy; OpenStreetMap contributors'
                }
            },
            layers: [{
                id: 'osm-basemap',
                type: 'raster',
                source: 'osm',
                minzoom: 0,
                maxzoom: 19
            }]
        },
        center: [0, 20],
        zoom: 2
    });

    // Add navigation controls
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.addControl(new maplibregl.ScaleControl(), 'bottom-left');

    // Update status on move
    map.on('moveend', updateStatus);

    // Load available layers after map loads
    map.on('load', () => {
        if (config.tipgEnabled) {
            loadVectorCollections();
        }
        if (config.stacEnabled) {
            loadStacSearches();
        }
        updateStatus();
    });
}

/**
 * Load TiPG vector collections
 */
async function loadVectorCollections() {
    const container = document.getElementById('vector-collections');

    try {
        const response = await fetch('/vector/collections');
        if (!response.ok) throw new Error('Failed to load collections');

        const data = await response.json();
        const collections = data.collections || [];

        if (collections.length === 0) {
            container.innerHTML = '<div class="empty-layers"><p>No vector collections found</p></div>';
            return;
        }

        let html = '';
        for (const col of collections) {
            const id = col.id;
            const title = col.title || id;
            html += `
                <div class="layer-item" onclick="addVectorLayer('${id}', '${title}')">
                    <span class="layer-name" title="${title}">${title}</span>
                    <button class="layer-add-btn">+ Add</button>
                </div>
            `;
        }

        container.innerHTML = html;

    } catch (error) {
        container.innerHTML = `<div class="empty-layers"><p>Error: ${error.message}</p></div>`;
    }
}

/**
 * Load STAC searches
 */
async function loadStacSearches() {
    const container = document.getElementById('stac-searches');

    try {
        const response = await fetch('/searches');
        if (!response.ok) throw new Error('Failed to load searches');

        const data = await response.json();
        const searches = data.searches || [];

        if (searches.length === 0) {
            container.innerHTML = '<div class="empty-layers"><p>No STAC searches registered</p></div>';
            return;
        }

        let html = '';
        for (const search of searches) {
            const id = search.id;
            html += `
                <div class="layer-item" onclick="addStacLayer('${id}')">
                    <span class="layer-name" title="${id}">${id}</span>
                    <button class="layer-add-btn">+ Add</button>
                </div>
            `;
        }

        container.innerHTML = html;

    } catch (error) {
        container.innerHTML = `<div class="empty-layers"><p>Error: ${error.message}</p></div>`;
    }
}

/**
 * Add a TiPG vector layer (MVT)
 */
function addVectorLayer(collectionId, title) {
    const layerId = `vector-${collectionId}-${++layerCounter}`;
    const colorIndex = activeLayers.length % VECTOR_COLORS.length;
    const color = VECTOR_COLORS[colorIndex];

    const sourceId = `${layerId}-source`;
    const tileUrl = `/vector/collections/${collectionId}/tiles/WebMercatorQuad/{z}/{x}/{y}.pbf`;

    // Add source
    map.addSource(sourceId, {
        type: 'vector',
        tiles: [window.location.origin + tileUrl],
        minzoom: 0,
        maxzoom: 22
    });

    // Add fill layer
    map.addLayer({
        id: `${layerId}-fill`,
        type: 'fill',
        source: sourceId,
        'source-layer': collectionId,
        paint: {
            'fill-color': color,
            'fill-opacity': 0.3
        }
    });

    // Add line layer
    map.addLayer({
        id: `${layerId}-line`,
        type: 'line',
        source: sourceId,
        'source-layer': collectionId,
        paint: {
            'line-color': color,
            'line-width': 2
        }
    });

    // Track layer
    const layer = {
        id: layerId,
        sourceId: sourceId,
        name: title || collectionId,
        type: 'vector',
        visible: true,
        sublayers: [`${layerId}-fill`, `${layerId}-line`]
    };

    activeLayers.push(layer);
    renderActiveLayers();
    updateStatus();

    // Try to fit bounds
    fitToCollection(collectionId);
}

/**
 * Add a STAC search layer (raster)
 */
function addStacLayer(searchId) {
    const layerId = `stac-${searchId}-${++layerCounter}`;
    const sourceId = `${layerId}-source`;
    const tileUrl = `/searches/${searchId}/tiles/WebMercatorQuad/{z}/{x}/{y}.png`;

    map.addSource(sourceId, {
        type: 'raster',
        tiles: [window.location.origin + tileUrl],
        tileSize: 256
    });

    map.addLayer({
        id: layerId,
        type: 'raster',
        source: sourceId,
        paint: {
            'raster-opacity': 1
        }
    });

    const layer = {
        id: layerId,
        sourceId: sourceId,
        name: searchId,
        type: 'raster',
        visible: true,
        sublayers: [layerId]
    };

    activeLayers.push(layer);
    renderActiveLayers();
    updateStatus();
}

/**
 * Add a COG layer from URL
 */
function addCogLayer() {
    const urlInput = document.getElementById('cog-url');
    const url = urlInput.value.trim();

    if (!url) {
        alert('Please enter a COG URL');
        return;
    }

    const layerId = `cog-${++layerCounter}`;
    const sourceId = `${layerId}-source`;
    const tileUrl = `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=${encodeURIComponent(url)}`;

    map.addSource(sourceId, {
        type: 'raster',
        tiles: [window.location.origin + tileUrl],
        tileSize: 256
    });

    map.addLayer({
        id: layerId,
        type: 'raster',
        source: sourceId,
        paint: {
            'raster-opacity': 1
        }
    });

    // Extract filename for display
    const filename = url.split('/').pop().split('?')[0] || 'COG';

    const layer = {
        id: layerId,
        sourceId: sourceId,
        name: filename,
        type: 'raster',
        visible: true,
        sublayers: [layerId],
        url: url
    };

    activeLayers.push(layer);
    renderActiveLayers();
    updateStatus();

    // Clear input
    urlInput.value = '';

    // Try to get bounds and zoom
    fetchCogBounds(url);
}

/**
 * Add a Zarr/NetCDF layer from URL
 */
function addZarrLayer() {
    const urlInput = document.getElementById('zarr-url');
    const varInput = document.getElementById('zarr-variable');
    const url = urlInput.value.trim();
    const variable = varInput.value.trim();

    if (!url) {
        alert('Please enter a Zarr URL');
        return;
    }

    const layerId = `zarr-${++layerCounter}`;
    const sourceId = `${layerId}-source`;

    let tileUrl = `/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=${encodeURIComponent(url)}`;
    if (variable) {
        tileUrl += `&variable=${encodeURIComponent(variable)}`;
    }

    map.addSource(sourceId, {
        type: 'raster',
        tiles: [window.location.origin + tileUrl],
        tileSize: 256
    });

    map.addLayer({
        id: layerId,
        type: 'raster',
        source: sourceId,
        paint: {
            'raster-opacity': 1
        }
    });

    const filename = url.split('/').pop().split('?')[0] || 'Zarr';
    const displayName = variable ? `${filename} (${variable})` : filename;

    const layer = {
        id: layerId,
        sourceId: sourceId,
        name: displayName,
        type: 'raster',
        visible: true,
        sublayers: [layerId],
        url: url
    };

    activeLayers.push(layer);
    renderActiveLayers();
    updateStatus();

    // Clear inputs
    urlInput.value = '';
    varInput.value = '';
}

/**
 * Remove a layer from the map
 */
function removeLayer(layerId) {
    const layer = activeLayers.find(l => l.id === layerId);
    if (!layer) return;

    // Remove sublayers from map
    for (const sublayer of layer.sublayers) {
        if (map.getLayer(sublayer)) {
            map.removeLayer(sublayer);
        }
    }

    // Remove source
    if (map.getSource(layer.sourceId)) {
        map.removeSource(layer.sourceId);
    }

    // Remove from tracking
    activeLayers = activeLayers.filter(l => l.id !== layerId);

    if (selectedLayerId === layerId) {
        selectedLayerId = null;
    }

    renderActiveLayers();
    updateStatus();
}

/**
 * Toggle layer visibility
 */
function toggleLayerVisibility(layerId) {
    const layer = activeLayers.find(l => l.id === layerId);
    if (!layer) return;

    layer.visible = !layer.visible;

    for (const sublayer of layer.sublayers) {
        map.setLayoutProperty(sublayer, 'visibility', layer.visible ? 'visible' : 'none');
    }

    renderActiveLayers();
}

/**
 * Select a layer for opacity control
 */
function selectLayer(layerId) {
    selectedLayerId = layerId;
    renderActiveLayers();

    const controlsEl = document.getElementById('layer-controls');
    if (selectedLayerId) {
        controlsEl.style.display = 'block';
        const layer = activeLayers.find(l => l.id === layerId);
        if (layer) {
            // Get current opacity
            const opacity = layer.type === 'vector'
                ? map.getPaintProperty(layer.sublayers[0], 'fill-opacity')
                : map.getPaintProperty(layer.sublayers[0], 'raster-opacity');
            document.getElementById('opacity-slider').value = (opacity || 1) * 100;
        }
    } else {
        controlsEl.style.display = 'none';
    }
}

/**
 * Update opacity for selected layer
 */
function updateOpacity(value) {
    if (!selectedLayerId) return;

    const layer = activeLayers.find(l => l.id === selectedLayerId);
    if (!layer) return;

    const opacity = value / 100;

    if (layer.type === 'vector') {
        map.setPaintProperty(`${layer.id}-fill`, 'fill-opacity', opacity * 0.3);
        map.setPaintProperty(`${layer.id}-line`, 'line-opacity', opacity);
    } else {
        map.setPaintProperty(layer.id, 'raster-opacity', opacity);
    }
}

/**
 * Render the active layers list
 */
function renderActiveLayers() {
    const container = document.getElementById('active-layers-list');

    if (activeLayers.length === 0) {
        container.innerHTML = `
            <div class="empty-layers">
                <p>No layers added yet.</p>
                <p>Select layers from the catalog.</p>
            </div>
        `;
        return;
    }

    let html = '';
    for (const layer of activeLayers) {
        const typeClass = layer.type === 'vector' ? 'vector' : 'raster';
        const typeBadge = layer.type === 'vector' ? 'MVT' : 'Raster';
        const selected = layer.id === selectedLayerId ? 'selected' : '';

        html += `
            <div class="active-layer ${typeClass} ${selected}" onclick="selectLayer('${layer.id}')">
                <input type="checkbox" class="layer-visibility"
                    ${layer.visible ? 'checked' : ''}
                    onclick="event.stopPropagation(); toggleLayerVisibility('${layer.id}')">
                <div class="layer-info">
                    <div class="layer-title" title="${layer.name}">${layer.name}</div>
                    <div class="layer-type">
                        <span class="type-badge ${layer.type === 'vector' ? 'mvt' : 'raster'}">${typeBadge}</span>
                    </div>
                </div>
                <button class="layer-remove" onclick="event.stopPropagation(); removeLayer('${layer.id}')" title="Remove layer">×</button>
            </div>
        `;
    }

    container.innerHTML = html;
}

/**
 * Update status bar
 */
function updateStatus() {
    const center = map.getCenter();
    const zoom = map.getZoom().toFixed(1);
    const layerCount = activeLayers.length;

    const statusEl = document.querySelector('.status-bar');
    if (statusEl) {
        statusEl.innerHTML = `
            <span>${layerCount} layer${layerCount !== 1 ? 's' : ''}</span>
            <span>Zoom: ${zoom} | Center: ${center.lat.toFixed(4)}, ${center.lng.toFixed(4)}</span>
        `;
    }
}

/**
 * Toggle catalog section collapse
 */
function toggleSection(header) {
    header.classList.toggle('collapsed');
    const content = header.nextElementSibling;
    content.classList.toggle('collapsed');
}

/**
 * Fetch COG bounds and zoom to it
 */
async function fetchCogBounds(url) {
    try {
        const response = await fetch(`/cog/info?url=${encodeURIComponent(url)}`);
        if (response.ok) {
            const info = await response.json();
            if (info.bounds) {
                const [minX, minY, maxX, maxY] = info.bounds;
                map.fitBounds([[minX, minY], [maxX, maxY]], { padding: 50 });
            }
        }
    } catch (e) {
        // Ignore - user can pan manually
    }
}

/**
 * Fit map to vector collection bounds
 */
async function fitToCollection(collectionId) {
    try {
        const response = await fetch(`/vector/collections/${collectionId}`);
        if (response.ok) {
            const col = await response.json();
            if (col.extent?.spatial?.bbox) {
                const [minX, minY, maxX, maxY] = col.extent.spatial.bbox;
                map.fitBounds([[minX, minY], [maxX, maxY]], { padding: 50 });
            }
        }
    } catch (e) {
        // Ignore
    }
}
```

### Phase 4: Update App (`geotiler/app.py`)

Add import and router mount:

```python
from geotiler.routers import map_viewer

# In create_app():
app.include_router(map_viewer.router, tags=["Map Viewer"])
```

### Phase 5: Update Navbar (`geotiler/templates/components/navbar.html`)

Add Map link to navbar:

```html
<a href="/map" class="{{ 'active' if nav_active == '/map' else '' }}">Map</a>
```

---

## API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `GET /vector/collections` | List TiPG vector collections |
| `GET /vector/collections/{id}` | Get collection metadata (for bounds) |
| `GET /vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}.pbf` | Vector tiles |
| `GET /searches` | List registered STAC searches |
| `GET /searches/{id}/tiles/{tms}/{z}/{x}/{y}.png` | STAC mosaic tiles |
| `GET /cog/info?url=` | COG metadata (for bounds) |
| `GET /cog/tiles/{tms}/{z}/{x}/{y}.png?url=` | COG tiles |
| `GET /xarray/tiles/{tms}/{z}/{x}/{y}.png?url=` | Zarr/NetCDF tiles |

---

## Future Enhancements (Out of Scope)

- [ ] Persistent layer state (localStorage)
- [ ] Layer reordering (drag and drop)
- [ ] Custom vector styling UI
- [ ] Legend generation
- [ ] Basemap switcher
- [ ] Feature info popup on click
- [ ] Export map as image
- [ ] Share map state via URL

---

## Testing Checklist

- [ ] Map loads with basemap
- [ ] Vector collections auto-discovered
- [ ] STAC searches auto-discovered
- [ ] Add vector layer works
- [ ] Add STAC layer works
- [ ] Add COG by URL works
- [ ] Add Zarr by URL works
- [ ] Layer visibility toggle works
- [ ] Layer remove works
- [ ] Opacity slider works
- [ ] Status bar updates
- [ ] Map navigation (zoom/pan) works
- [ ] Responsive on smaller screens

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `geotiler/routers/map_viewer.py` | CREATE |
| `geotiler/templates/pages/map/viewer.html` | CREATE |
| `geotiler/static/js/map-viewer.js` | CREATE |
| `geotiler/app.py` | MODIFY (add router) |
| `geotiler/templates/components/navbar.html` | MODIFY (add link) |

---

**Created:** 2026-01-21
**Author:** Claude Code
