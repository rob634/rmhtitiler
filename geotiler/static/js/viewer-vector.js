/**
 * Vector Viewer JavaScript for geotiler.
 *
 * Depends on: MapLibre GL JS 4.x, common.js (fetchJSON, getQueryParam, setQueryParam, showNotification, escapeHtml)
 */

let vectorMap = null;
let currentCollectionId = null;
let currentRenderMode = 'mvt';
let popup = null;
let activeClickHandlers = [];

const VECTOR_SOURCE_ID = 'vector-data';
const VECTOR_FILL_LAYER = 'vector-fill';
const VECTOR_LINE_LAYER = 'vector-line';
const VECTOR_POINT_LAYER = 'vector-point';


// ============================================================================
// Initialization
// ============================================================================

/**
 * Initialize the vector viewer. Creates MapLibre map, populates collection dropdown.
 * @param {boolean} tipgEnabled - Whether TiPG is available
 */
async function initVectorViewer(tipgEnabled) {
    vectorMap = new maplibregl.Map({
        container: 'map',
        style: { version: 8, sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '&copy; OpenStreetMap contributors' } }, layers: [{ id: 'osm', type: 'raster', source: 'osm' }] },
        center: [0, 20],
        zoom: 2,
    });

    vectorMap.addControl(new maplibregl.NavigationControl(), 'top-right');
    vectorMap.addControl(new maplibregl.ScaleControl(), 'bottom-right');

    // Create popup instance for feature info
    popup = new maplibregl.Popup({ closeButton: true, closeOnClick: false });

    // Track map position
    vectorMap.on('moveend', updateMapStatus);
    vectorMap.on('zoomend', updateMapStatus);

    if (!tipgEnabled) {
        showNotification('Vector data (TiPG) is not enabled on this server', 'warning');
        return;
    }

    // Populate collection dropdown
    const result = await fetchJSON('/vector/collections');
    if (result.ok && result.data.collections) {
        const select = document.getElementById('collection-select');
        result.data.collections
            .filter(c => c.id !== 'public.spatial_ref_sys')
            .forEach(c => {
                const option = document.createElement('option');
                option.value = c.id;
                option.textContent = c.title || c.id;
                select.appendChild(option);
            });

        // Auto-select from query parameter
        const collParam = getQueryParam('collection');
        if (collParam) {
            select.value = collParam;
            vectorMap.on('load', () => loadCollection(collParam));
        }
    } else {
        showNotification('Failed to load vector collections', 'error');
    }
}

function updateMapStatus() {
    const center = vectorMap.getCenter();
    const zoom = vectorMap.getZoom();
    document.getElementById('map-zoom').textContent = 'Zoom: ' + zoom.toFixed(1);
    document.getElementById('map-coords').textContent =
        center.lat.toFixed(4) + ', ' + center.lng.toFixed(4);
}


// ============================================================================
// Load Collection
// ============================================================================

/**
 * Load a vector collection: display metadata and add layer to map.
 * @param {string} collectionId - Collection identifier
 */
async function loadCollection(collectionId) {
    if (!collectionId) return;

    currentCollectionId = collectionId;
    setQueryParam('collection', collectionId);
    showLoading(true);

    // Show collection info
    const infoPanel = document.getElementById('collection-info');
    infoPanel.classList.remove('hidden');

    // Fetch collection metadata
    await loadCollectionMetadata(collectionId);

    // Set API links
    const prefix = '/vector/collections/' + encodeURIComponent(collectionId);
    document.getElementById('link-tilejson').href = prefix + '/tiles/WebMercatorQuad/tilejson.json';
    document.getElementById('link-collection').href = prefix;
    document.getElementById('link-items').href = prefix + '/items?limit=10';

    // Load schema
    loadSchema(collectionId);

    // Add layer based on current render mode
    if (currentRenderMode === 'mvt') {
        addMvtLayer(collectionId);
    } else {
        addGeoJsonLayer(collectionId);
    }

    showLoading(false);
}

/**
 * Load collection metadata and render in sidebar.
 */
async function loadCollectionMetadata(collectionId) {
    const metadataGrid = document.getElementById('metadata-grid');
    const featureCountEl = document.getElementById('feature-count');

    const result = await fetchJSON('/vector/collections/' + encodeURIComponent(collectionId) + '/items?limit=1');
    if (result.ok && result.data) {
        const features = result.data.features || [];
        const matched = result.data.numberMatched || result.data.numberReturned || features.length;
        featureCountEl.textContent = '(' + matched + ' features)';

        // Build metadata grid
        const extent = result.data.bbox;
        metadataGrid.innerHTML =
            '<div class="metadata-item"><div class="metadata-label">Features</div><div class="metadata-value">' + matched + '</div></div>' +
            '<div class="metadata-item"><div class="metadata-label">Format</div><div class="metadata-value mono">OGC</div></div>' +
            (extent ? '<div class="metadata-item full-width"><div class="metadata-label">Extent</div><div class="metadata-value mono">' +
                extent.map(function(v) { return v.toFixed(4); }).join(', ') + '</div></div>' : '');
    } else {
        featureCountEl.textContent = '';
        metadataGrid.innerHTML = '<div style="font-size:0.8rem;color:var(--color-gray);">Error loading metadata</div>';
    }
}


// ============================================================================
// Schema / Attributes
// ============================================================================

/**
 * Load attribute schema from a sample feature.
 */
async function loadSchema(collectionId) {
    const container = document.getElementById('attribute-list');

    const result = await fetchJSON('/vector/collections/' + encodeURIComponent(collectionId) + '/items?limit=1');
    if (!result.ok || !result.data || !result.data.features || result.data.features.length === 0) {
        container.innerHTML = '<div style="font-size:0.8rem;color:var(--color-gray);font-style:italic;">No features to analyze</div>';
        return;
    }

    const properties = result.data.features[0].properties || {};
    const entries = Object.entries(properties);

    if (entries.length === 0) {
        container.innerHTML = '<div style="font-size:0.8rem;color:var(--color-gray);font-style:italic;">No attributes found</div>';
        return;
    }

    container.innerHTML = entries.map(function(entry) {
        var key = entry[0], value = entry[1];
        var type = getAttributeType(value);
        return '<div class="attribute-item">' +
            '<span class="attribute-name">' + escapeHtml(key) + '</span>' +
            '<span class="attribute-type ' + type + '">' + type + '</span>' +
            '</div>';
    }).join('');
}

function getAttributeType(value) {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'boolean') return 'boolean';
    if (typeof value === 'string') return 'string';
    if (Array.isArray(value)) return 'array';
    return 'object';
}

function toggleSection(id) {
    document.getElementById(id).classList.toggle('hidden');
}


// ============================================================================
// MVT (Vector Tiles) Layer
// ============================================================================

/**
 * Add MVT vector tile layer for a collection.
 * @param {string} collectionId - Collection identifier
 */
function addMvtLayer(collectionId) {
    removeVectorLayer();

    const tileUrl = '/vector/collections/' + encodeURIComponent(collectionId) + '/tiles/WebMercatorQuad/{z}/{x}/{y}';

    vectorMap.addSource(VECTOR_SOURCE_ID, {
        type: 'vector',
        tiles: [tileUrl],
    });

    const fillColor = document.getElementById('fill-color').value;
    const fillOpacity = parseFloat(document.getElementById('fill-opacity').value);
    const strokeColor = document.getElementById('stroke-color').value;
    const strokeWidth = parseFloat(document.getElementById('stroke-width').value);
    const pointRadius = parseFloat(document.getElementById('point-radius').value);

    // Add fill layer (for polygons)
    vectorMap.addLayer({
        id: VECTOR_FILL_LAYER,
        type: 'fill',
        source: VECTOR_SOURCE_ID,
        'source-layer': 'default',
        paint: {
            'fill-color': fillColor,
            'fill-opacity': fillOpacity,
        },
        filter: ['==', '$type', 'Polygon'],
    });

    // Add line layer (for lines and polygon outlines)
    vectorMap.addLayer({
        id: VECTOR_LINE_LAYER,
        type: 'line',
        source: VECTOR_SOURCE_ID,
        'source-layer': 'default',
        paint: {
            'line-color': strokeColor,
            'line-width': strokeWidth,
        },
    });

    // Add point layer (for points)
    vectorMap.addLayer({
        id: VECTOR_POINT_LAYER,
        type: 'circle',
        source: VECTOR_SOURCE_ID,
        'source-layer': 'default',
        paint: {
            'circle-color': fillColor,
            'circle-radius': pointRadius,
            'circle-stroke-color': strokeColor,
            'circle-stroke-width': strokeWidth,
        },
        filter: ['==', '$type', 'Point'],
    });

    // Click handlers for feature inspection
    setupClickHandlers();

    updateLayerInfo('MVT', 'All');
    showNotification('MVT layer loaded for ' + collectionId, 'success');
}


// ============================================================================
// GeoJSON Layer
// ============================================================================

/**
 * Add GeoJSON layer for a collection (supports popups).
 * @param {string} collectionId - Collection identifier
 */
async function addGeoJsonLayer(collectionId) {
    removeVectorLayer();

    const limit = document.getElementById('geojson-limit').value;
    const result = await fetchJSON('/vector/collections/' + encodeURIComponent(collectionId) + '/items?limit=' + limit);
    if (!result.ok) {
        showNotification(result.error || 'Failed to load features', 'error');
        return;
    }

    const geojson = result.data;

    vectorMap.addSource(VECTOR_SOURCE_ID, {
        type: 'geojson',
        data: geojson,
    });

    const fillColor = document.getElementById('fill-color').value;
    const fillOpacity = parseFloat(document.getElementById('fill-opacity').value);
    const strokeColor = document.getElementById('stroke-color').value;
    const strokeWidth = parseFloat(document.getElementById('stroke-width').value);
    const pointRadius = parseFloat(document.getElementById('point-radius').value);

    // Add fill layer
    vectorMap.addLayer({
        id: VECTOR_FILL_LAYER,
        type: 'fill',
        source: VECTOR_SOURCE_ID,
        paint: {
            'fill-color': fillColor,
            'fill-opacity': fillOpacity,
        },
        filter: ['==', '$type', 'Polygon'],
    });

    // Add line layer
    vectorMap.addLayer({
        id: VECTOR_LINE_LAYER,
        type: 'line',
        source: VECTOR_SOURCE_ID,
        paint: {
            'line-color': strokeColor,
            'line-width': strokeWidth,
        },
    });

    // Add point layer
    vectorMap.addLayer({
        id: VECTOR_POINT_LAYER,
        type: 'circle',
        source: VECTOR_SOURCE_ID,
        paint: {
            'circle-color': fillColor,
            'circle-radius': pointRadius,
            'circle-stroke-color': strokeColor,
            'circle-stroke-width': strokeWidth,
        },
        filter: ['==', '$type', 'Point'],
    });

    // Fit bounds to data
    if (geojson.features && geojson.features.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        geojson.features.forEach(function(f) {
            if (f.geometry && f.geometry.coordinates) {
                addCoordsToBounds(bounds, f.geometry.coordinates);
            }
        });
        if (bounds.getNorthEast()) {
            vectorMap.fitBounds(bounds, { padding: 50 });
        }
    }

    // Setup click handlers
    setupClickHandlers();

    const featureCount = (geojson.features || []).length;
    updateLayerInfo('GeoJSON', featureCount.toLocaleString());
    showNotification('GeoJSON loaded: ' + featureCount + ' features', 'success');
}


// ============================================================================
// Layer Management
// ============================================================================

/**
 * Remove all vector layers and source.
 */
function removeVectorLayer() {
    // Remove stacked event handlers first
    activeClickHandlers.forEach(function(h) {
        vectorMap.off(h.event, h.layer, h.fn);
    });
    activeClickHandlers = [];

    [VECTOR_FILL_LAYER, VECTOR_LINE_LAYER, VECTOR_POINT_LAYER].forEach(function(id) {
        if (vectorMap.getLayer(id)) vectorMap.removeLayer(id);
    });
    if (vectorMap.getSource(VECTOR_SOURCE_ID)) {
        vectorMap.removeSource(VECTOR_SOURCE_ID);
    }
    popup.remove();
}

/**
 * Toggle between MVT and GeoJSON render modes.
 * @param {string} mode - 'mvt' or 'geojson'
 */
function setRenderMode(mode) {
    currentRenderMode = mode;

    // Update button styling
    document.querySelectorAll('.mode-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Show/hide GeoJSON options
    var geojsonOpts = document.getElementById('geojson-options');
    if (mode === 'geojson') {
        geojsonOpts.classList.remove('hidden');
    } else {
        geojsonOpts.classList.add('hidden');
    }

    // Reload current collection if one is selected
    if (currentCollectionId) {
        loadCollection(currentCollectionId);
    }
}

/**
 * Reload if currently in GeoJSON mode (for limit changes).
 */
function reloadIfGeoJson() {
    if (currentRenderMode === 'geojson' && currentCollectionId) {
        addGeoJsonLayer(currentCollectionId);
    }
}


// ============================================================================
// Styling
// ============================================================================

/**
 * Sync color picker → hex input.
 */
function syncHex(type) {
    var colorInput = document.getElementById(type + '-color');
    document.getElementById(type + '-color-hex').value = colorInput.value;
}

/**
 * Sync hex input → color picker and apply style.
 */
function syncColor(type) {
    var hexInput = document.getElementById(type + '-color-hex');
    var colorInput = document.getElementById(type + '-color');
    var hex = hexInput.value;
    if (!hex.startsWith('#')) hex = '#' + hex;
    if (/^#[0-9A-Fa-f]{6}$/.test(hex)) {
        colorInput.value = hex;
        hexInput.value = hex;
        applyStyle();
    }
}

/**
 * Update slider display value.
 */
function updateSliderDisplay(id) {
    var slider = document.getElementById(id);
    document.getElementById(id + '-value').textContent = slider.value;
}

/**
 * Apply current style settings to all layers.
 */
function applyStyle() {
    var fillColor = document.getElementById('fill-color').value;
    var fillOpacity = parseFloat(document.getElementById('fill-opacity').value);
    var strokeColor = document.getElementById('stroke-color').value;
    var strokeWidth = parseFloat(document.getElementById('stroke-width').value);
    var pointRadius = parseFloat(document.getElementById('point-radius').value);

    if (vectorMap.getLayer(VECTOR_FILL_LAYER)) {
        vectorMap.setPaintProperty(VECTOR_FILL_LAYER, 'fill-color', fillColor);
        vectorMap.setPaintProperty(VECTOR_FILL_LAYER, 'fill-opacity', fillOpacity);
    }
    if (vectorMap.getLayer(VECTOR_LINE_LAYER)) {
        vectorMap.setPaintProperty(VECTOR_LINE_LAYER, 'line-color', strokeColor);
        vectorMap.setPaintProperty(VECTOR_LINE_LAYER, 'line-width', strokeWidth);
    }
    if (vectorMap.getLayer(VECTOR_POINT_LAYER)) {
        vectorMap.setPaintProperty(VECTOR_POINT_LAYER, 'circle-color', fillColor);
        vectorMap.setPaintProperty(VECTOR_POINT_LAYER, 'circle-radius', pointRadius);
        vectorMap.setPaintProperty(VECTOR_POINT_LAYER, 'circle-stroke-color', strokeColor);
        vectorMap.setPaintProperty(VECTOR_POINT_LAYER, 'circle-stroke-width', strokeWidth);
    }
}


// ============================================================================
// Feature Inspection
// ============================================================================

/**
 * Setup click handlers for feature property popups and sidebar display.
 */
function setupClickHandlers() {
    [VECTOR_FILL_LAYER, VECTOR_LINE_LAYER, VECTOR_POINT_LAYER].forEach(function(layerId) {
        var clickFn = function(e) {
            if (!e.features || e.features.length === 0) return;

            var feature = e.features[0];
            var props = feature.properties || {};

            displayFeatureProperties(props);

            var entries = Object.entries(props).slice(0, 8);
            var html = '<div style="max-height:200px;overflow-y:auto;">' +
                '<table style="font-size:12px;">';
            entries.forEach(function(entry) {
                html += '<tr><td><strong>' + escapeHtml(entry[0]) + '</strong></td><td>' + escapeHtml(formatPropertyValue(entry[1])) + '</td></tr>';
            });
            if (Object.keys(props).length > 8) {
                html += '<tr><td colspan="2" style="color:var(--color-gray);font-style:italic;">+' + (Object.keys(props).length - 8) + ' more</td></tr>';
            }
            html += '</table></div>';

            popup.setLngLat(e.lngLat).setHTML(html).addTo(vectorMap);
        };

        var enterFn = function() {
            vectorMap.getCanvas().style.cursor = 'pointer';
        };
        var leaveFn = function() {
            vectorMap.getCanvas().style.cursor = '';
        };

        vectorMap.on('click', layerId, clickFn);
        vectorMap.on('mouseenter', layerId, enterFn);
        vectorMap.on('mouseleave', layerId, leaveFn);

        activeClickHandlers.push(
            { event: 'click', layer: layerId, fn: clickFn },
            { event: 'mouseenter', layer: layerId, fn: enterFn },
            { event: 'mouseleave', layer: layerId, fn: leaveFn }
        );
    });
}

/**
 * Display feature properties in the sidebar panel.
 */
function displayFeatureProperties(properties) {
    var container = document.getElementById('feature-properties');
    var entries = Object.entries(properties);

    if (entries.length === 0) {
        container.innerHTML = '<div style="font-size:0.8rem;color:var(--color-gray);font-style:italic;text-align:center;padding:var(--space-md);">No properties</div>';
        return;
    }

    container.innerHTML = entries.map(function(entry) {
        return '<div class="property-item">' +
            '<span class="property-key">' + escapeHtml(entry[0]) + '</span>' +
            '<span class="property-value">' + escapeHtml(formatPropertyValue(entry[1])) + '</span>' +
            '</div>';
    }).join('');
}

function formatPropertyValue(value) {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'object') return JSON.stringify(value);
    if (typeof value === 'number') {
        if (Number.isInteger(value)) return value.toLocaleString();
        return value.toFixed(4);
    }
    return String(value);
}


// ============================================================================
// UI Helpers
// ============================================================================

function updateLayerInfo(mode, featureCount) {
    var info = document.getElementById('layer-info');
    document.getElementById('layer-name').textContent = currentCollectionId || '';
    document.getElementById('layer-mode-display').textContent = mode;
    document.getElementById('visible-features').textContent = featureCount + ' features';
    info.classList.remove('hidden');
}

function showLoading(show) {
    var overlay = document.getElementById('map-loading');
    if (show) {
        overlay.classList.remove('hidden');
    } else {
        overlay.classList.add('hidden');
    }
}


// ============================================================================
// Utility
// ============================================================================

/**
 * Recursively add coordinates to a LngLatBounds.
 * @param {maplibregl.LngLatBounds} bounds - Bounds to extend
 * @param {Array} coords - GeoJSON coordinates (nested arrays)
 */
function addCoordsToBounds(bounds, coords) {
    if (typeof coords[0] === 'number') {
        bounds.extend(coords);
    } else {
        coords.forEach(function(c) { addCoordsToBounds(bounds, c); });
    }
}
