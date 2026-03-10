/**
 * Zarr/NetCDF Viewer JavaScript for geotiler.
 *
 * Depends on: MapLibre GL JS 4.x, common.js (fetchJSON, getQueryParam, setQueryParam, showNotification, escapeHtml)
 */

let zarrMap = null;
let currentZarrUrl = null;
let zarrInfo = null;
let zarrLoadGen = 0;

const ZARR_SOURCE_ID = 'zarr-tiles';
const ZARR_LAYER_ID = 'zarr-layer';


// ============================================================================
// Initialization
// ============================================================================

/**
 * Initialize the Zarr viewer. Creates MapLibre map and auto-loads URL from query params.
 */
function initZarrViewer() {
    zarrMap = new maplibregl.Map({
        container: 'map',
        style: { version: 8, sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '&copy; OpenStreetMap contributors' } }, layers: [{ id: 'osm', type: 'raster', source: 'osm' }] },
        center: [0, 20],
        zoom: 2,
    });

    zarrMap.addControl(new maplibregl.NavigationControl(), 'top-right');
    zarrMap.addControl(new maplibregl.ScaleControl(), 'bottom-right');

    // Track map position
    zarrMap.on('moveend', updateMapStatus);
    zarrMap.on('zoomend', updateMapStatus);

    // Auto-load from query parameter
    const urlParam = getQueryParam('url');
    if (urlParam) {
        document.getElementById('zarr-url').value = urlParam;
        zarrMap.on('load', () => loadZarr());
    }
}

function updateMapStatus() {
    const center = zarrMap.getCenter();
    const zoom = zarrMap.getZoom();
    document.getElementById('map-zoom').textContent = 'Zoom: ' + zoom.toFixed(1);
    document.getElementById('map-coords').textContent =
        center.lat.toFixed(4) + ', ' + center.lng.toFixed(4);
}


// ============================================================================
// Load Zarr
// ============================================================================

/**
 * Load a Zarr/NetCDF URL: fetch info, populate variable selector, add tile layer.
 */
async function loadZarr() {
    const url = document.getElementById('zarr-url').value.trim();
    if (!url) {
        showNotification('Please enter a dataset URL', 'warning');
        return;
    }

    currentZarrUrl = url;
    setQueryParam('url', url);
    showLoading(true);
    const myGen = ++zarrLoadGen;

    // Fetch XArray info
    const result = await fetchJSON('/xarray/info?url=' + encodeURIComponent(url));
    if (myGen !== zarrLoadGen) return;
    if (!result.ok) {
        showNotification(result.error || 'Failed to load dataset info', 'error');
        showLoading(false);
        return;
    }

    zarrInfo = result.data;
    displayZarrMetadata(zarrInfo);
    populateVariables(zarrInfo);
    populateTimeSteps(zarrInfo);

    // Auto-load first variable
    updateZarrTiles();
    showLoading(false);

    showNotification('Dataset loaded successfully', 'success');
}


// ============================================================================
// Metadata Display
// ============================================================================

/**
 * Render dataset metadata in the sidebar.
 * @param {object} info - XArray info response
 */
function displayZarrMetadata(info) {
    const panel = document.getElementById('zarr-info');
    const metadata = document.getElementById('zarr-metadata');

    const bounds = info.bounds || [];
    const boundsStr = bounds.length === 4
        ? bounds[0].toFixed(4) + ', ' + bounds[1].toFixed(4) + ' to ' + bounds[2].toFixed(4) + ', ' + bounds[3].toFixed(4)
        : 'Unknown';

    const dims = info.dims ? Object.entries(info.dims).map(function(e) { return e[0] + '=' + e[1]; }).join(', ') : 'Unknown';

    const variables = info.variables || info.data_vars || [];
    const varCount = Array.isArray(variables) ? variables.length : Object.keys(variables).length;

    metadata.innerHTML =
        '<div class="metadata-item"><div class="metadata-label">Variables</div><div class="metadata-value">' + varCount + '</div></div>' +
        (info.crs ? '<div class="metadata-item"><div class="metadata-label">CRS</div><div class="metadata-value mono">' + escapeHtml(info.crs) + '</div></div>' : '') +
        '<div class="metadata-item full-width"><div class="metadata-label">Dimensions</div><div class="metadata-value mono">' + escapeHtml(dims) + '</div></div>' +
        '<div class="metadata-item full-width"><div class="metadata-label">Bounds</div><div class="metadata-value mono">' + escapeHtml(boundsStr) + '</div></div>';

    panel.classList.remove('hidden');
}


/**
 * Populate variable selector from dataset info.
 * @param {object} info - XArray info response
 */
function populateVariables(info) {
    const select = document.getElementById('variable-select');
    select.innerHTML = '';

    const variables = info.variables || info.data_vars || [];
    const varList = Array.isArray(variables) ? variables : Object.keys(variables);

    // Check for variable from query param
    const varParam = getQueryParam('variable');

    varList.forEach(function(v) {
        const option = document.createElement('option');
        option.value = v;
        option.textContent = v;
        if (v === varParam) option.selected = true;
        select.appendChild(option);
    });
}


/**
 * Populate time step selector if temporal dimension exists.
 * @param {object} info - XArray info response
 */
function populateTimeSteps(info) {
    const container = document.getElementById('time-controls');
    const select = document.getElementById('time-select');

    const dims = info.dims || {};
    const timeKeys = ['time', 'datetime', 'date', 't'];
    const timeDim = timeKeys.find(function(k) { return k in dims; });

    if (!timeDim || !info.coords || !info.coords[timeDim]) {
        container.classList.add('hidden');
        return;
    }

    select.innerHTML = '';
    const timeValues = info.coords[timeDim];
    (Array.isArray(timeValues) ? timeValues : []).forEach(function(t, i) {
        const option = document.createElement('option');
        option.value = i;
        option.textContent = String(t).substring(0, 19);
        select.appendChild(option);
    });

    container.classList.remove('hidden');
}


// ============================================================================
// Tile Layer Management
// ============================================================================

/**
 * Update Zarr tiles when visualization parameters change.
 */
function updateZarrTiles() {
    if (!currentZarrUrl) return;

    removeZarrLayer();

    const variable = document.getElementById('variable-select').value;
    if (!variable) return;

    setQueryParam('variable', variable);

    let tileUrl = '/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}?url=' + encodeURIComponent(currentZarrUrl)
        + '&variable=' + encodeURIComponent(variable);

    // Colormap
    const colormap = document.getElementById('zarr-colormap').value;
    if (colormap) {
        tileUrl += '&colormap_name=' + colormap;
    }

    // Rescale
    const min = document.getElementById('zarr-min').value;
    const max = document.getElementById('zarr-max').value;
    if (min && max) {
        tileUrl += '&rescale=' + min + ',' + max;
    }

    // Time step
    const timeSelect = document.getElementById('time-select');
    if (timeSelect.value && !document.getElementById('time-controls').classList.contains('hidden')) {
        tileUrl += '&time=' + timeSelect.value;
    }

    const bounds = zarrInfo ? zarrInfo.bounds : undefined;

    zarrMap.addSource(ZARR_SOURCE_ID, {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
        bounds: bounds || undefined,
    });

    zarrMap.addLayer({
        id: ZARR_LAYER_ID,
        type: 'raster',
        source: ZARR_SOURCE_ID,
    });

    // Fit to bounds if available
    if (bounds && bounds.length === 4) {
        zarrMap.fitBounds(
            [[bounds[0], bounds[1]], [bounds[2], bounds[3]]],
            { padding: 50, maxZoom: 16 }
        );
    }

    // Update layer info
    updateLayerInfo(variable);
}

/**
 * Remove existing Zarr tile layer and source.
 */
function removeZarrLayer() {
    if (zarrMap.getLayer(ZARR_LAYER_ID)) {
        zarrMap.removeLayer(ZARR_LAYER_ID);
    }
    if (zarrMap.getSource(ZARR_SOURCE_ID)) {
        zarrMap.removeSource(ZARR_SOURCE_ID);
    }
}

function updateLayerInfo(variable) {
    var info = document.getElementById('layer-info');
    document.getElementById('layer-name').textContent = currentZarrUrl ? currentZarrUrl.split('/').pop() : '';
    document.getElementById('layer-variable').textContent = variable || '';
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
