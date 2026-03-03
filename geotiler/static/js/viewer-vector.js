/**
 * Vector Viewer JavaScript for geotiler.
 *
 * Depends on: MapLibre GL JS 4.x, common.js (fetchJSON, getQueryParam, setQueryParam, showNotification, escapeHtml)
 */

let vectorMap = null;
let currentCollectionId = null;
let currentRenderMode = 'mvt';
let popup = null;

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
        style: 'https://demotiles.maplibre.org/style.json',
        center: [0, 20],
        zoom: 2,
    });

    vectorMap.addControl(new maplibregl.NavigationControl(), 'top-right');

    // Create popup instance for feature info
    popup = new maplibregl.Popup({ closeButton: true, closeOnClick: false });

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

    // Show collection info
    const infoPanel = document.getElementById('collection-info');
    document.getElementById('collection-title').textContent = collectionId;
    document.getElementById('collection-description').textContent = '';
    document.getElementById('feature-count').textContent = 'Loading...';
    document.getElementById('feature-properties').innerHTML = '';
    infoPanel.classList.remove('hidden');

    // Fetch a sample of features for metadata
    const result = await fetchJSON('/vector/collections/' + encodeURIComponent(collectionId) + '/items?limit=1');
    if (result.ok && result.data) {
        const features = result.data.features || [];
        const matched = result.data.numberMatched || result.data.numberReturned || features.length;
        document.getElementById('feature-count').textContent = matched + ' features';

        // Show properties of first feature
        if (features.length > 0 && features[0].properties) {
            const props = features[0].properties;
            const propEntries = Object.entries(props).slice(0, 8);
            let html = '<table class="data-table"><thead><tr><th>Property</th><th>Value</th></tr></thead><tbody>';
            propEntries.forEach(([key, value]) => {
                html += `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(String(value))}</td></tr>`;
            });
            html += '</tbody></table>';
            document.getElementById('feature-properties').innerHTML = html;
        }
    }

    // Add layer based on current render mode
    if (currentRenderMode === 'mvt') {
        addMvtLayer(collectionId);
    } else {
        addGeoJsonLayer(collectionId);
    }
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

    const color = document.getElementById('fill-color').value;
    const opacity = parseFloat(document.getElementById('fill-opacity').value);

    // Add fill layer (for polygons)
    vectorMap.addLayer({
        id: VECTOR_FILL_LAYER,
        type: 'fill',
        source: VECTOR_SOURCE_ID,
        'source-layer': 'default',
        paint: {
            'fill-color': color,
            'fill-opacity': opacity,
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
            'line-color': color,
            'line-width': 2,
        },
    });

    // Add point layer (for points)
    vectorMap.addLayer({
        id: VECTOR_POINT_LAYER,
        type: 'circle',
        source: VECTOR_SOURCE_ID,
        'source-layer': 'default',
        paint: {
            'circle-color': color,
            'circle-radius': 5,
            'circle-opacity': opacity,
        },
        filter: ['==', '$type', 'Point'],
    });

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

    const result = await fetchJSON('/vector/collections/' + encodeURIComponent(collectionId) + '/items?limit=1000');
    if (!result.ok) {
        showNotification(result.error || 'Failed to load features', 'error');
        return;
    }

    const geojson = result.data;

    vectorMap.addSource(VECTOR_SOURCE_ID, {
        type: 'geojson',
        data: geojson,
    });

    const color = document.getElementById('fill-color').value;
    const opacity = parseFloat(document.getElementById('fill-opacity').value);

    // Add fill layer
    vectorMap.addLayer({
        id: VECTOR_FILL_LAYER,
        type: 'fill',
        source: VECTOR_SOURCE_ID,
        paint: {
            'fill-color': color,
            'fill-opacity': opacity,
        },
        filter: ['==', '$type', 'Polygon'],
    });

    // Add line layer
    vectorMap.addLayer({
        id: VECTOR_LINE_LAYER,
        type: 'line',
        source: VECTOR_SOURCE_ID,
        paint: {
            'line-color': color,
            'line-width': 2,
        },
    });

    // Add point layer
    vectorMap.addLayer({
        id: VECTOR_POINT_LAYER,
        type: 'circle',
        source: VECTOR_SOURCE_ID,
        paint: {
            'circle-color': color,
            'circle-radius': 5,
            'circle-opacity': opacity,
        },
        filter: ['==', '$type', 'Point'],
    });

    // Fit bounds to data
    if (geojson.features && geojson.features.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        geojson.features.forEach(f => {
            if (f.geometry && f.geometry.coordinates) {
                addCoordsToBounds(bounds, f.geometry.coordinates);
            }
        });
        if (bounds.getNorthEast()) {
            vectorMap.fitBounds(bounds, { padding: 50 });
        }
    }

    // Setup click popups
    setupPopups();

    showNotification('GeoJSON loaded: ' + (geojson.features || []).length + ' features', 'success');
}


// ============================================================================
// Layer Management
// ============================================================================

/**
 * Remove all vector layers and source.
 */
function removeVectorLayer() {
    [VECTOR_FILL_LAYER, VECTOR_LINE_LAYER, VECTOR_POINT_LAYER].forEach(id => {
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
    document.getElementById('mode-mvt').className = 'btn btn-sm ' + (mode === 'mvt' ? 'btn-primary' : 'btn-secondary');
    document.getElementById('mode-geojson').className = 'btn btn-sm ' + (mode === 'geojson' ? 'btn-primary' : 'btn-secondary');

    // Reload current collection if one is selected
    if (currentCollectionId) {
        loadCollection(currentCollectionId);
    }
}

/**
 * Update layer style (color and opacity) from controls.
 */
function updateStyle() {
    const color = document.getElementById('fill-color').value;
    const opacity = parseFloat(document.getElementById('fill-opacity').value);

    if (vectorMap.getLayer(VECTOR_FILL_LAYER)) {
        vectorMap.setPaintProperty(VECTOR_FILL_LAYER, 'fill-color', color);
        vectorMap.setPaintProperty(VECTOR_FILL_LAYER, 'fill-opacity', opacity);
    }
    if (vectorMap.getLayer(VECTOR_LINE_LAYER)) {
        vectorMap.setPaintProperty(VECTOR_LINE_LAYER, 'line-color', color);
    }
    if (vectorMap.getLayer(VECTOR_POINT_LAYER)) {
        vectorMap.setPaintProperty(VECTOR_POINT_LAYER, 'circle-color', color);
        vectorMap.setPaintProperty(VECTOR_POINT_LAYER, 'circle-opacity', opacity);
    }
}


// ============================================================================
// Popups (GeoJSON mode only)
// ============================================================================

/**
 * Setup click handlers for feature property popups.
 */
function setupPopups() {
    [VECTOR_FILL_LAYER, VECTOR_LINE_LAYER, VECTOR_POINT_LAYER].forEach(layerId => {
        vectorMap.on('click', layerId, (e) => {
            if (!e.features || e.features.length === 0) return;

            const feature = e.features[0];
            const props = feature.properties || {};
            let html = '<div style="max-height: 200px; overflow-y: auto;">';
            html += '<table style="font-size: 12px;">';
            Object.entries(props).slice(0, 10).forEach(([key, value]) => {
                html += `<tr><td><strong>${escapeHtml(key)}</strong></td><td>${escapeHtml(String(value))}</td></tr>`;
            });
            html += '</table></div>';

            popup.setLngLat(e.lngLat).setHTML(html).addTo(vectorMap);
        });

        vectorMap.on('mouseenter', layerId, () => {
            vectorMap.getCanvas().style.cursor = 'pointer';
        });
        vectorMap.on('mouseleave', layerId, () => {
            vectorMap.getCanvas().style.cursor = '';
        });
    });
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
        coords.forEach(c => addCoordsToBounds(bounds, c));
    }
}
