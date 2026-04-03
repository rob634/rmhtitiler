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
 * Load a Zarr/NetCDF URL: fetch variable list, select variable, fetch info, add tile layer.
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

    // Step 1: Get variable list
    const keysResult = await fetchJSON('/xarray/dataset/keys?url=' + encodeURIComponent(url));
    if (myGen !== zarrLoadGen) return;
    if (!keysResult.ok || !keysResult.data || !keysResult.data.length) {
        showNotification(keysResult.error || 'No variables found in dataset', 'error');
        showLoading(false);
        return;
    }

    // Step 2: Select variable (from query param or first available)
    const varParam = getQueryParam('variable');
    const selectedVar = (varParam && keysResult.data.includes(varParam))
        ? varParam : keysResult.data[0];

    // Populate variable selector from keys
    populateVariablesFromKeys(keysResult.data, selectedVar);

    // Step 3: Fetch info WITH selected variable
    const result = await fetchJSON('/xarray/info?url=' + encodeURIComponent(url)
        + '&variable=' + encodeURIComponent(selectedVar));
    if (myGen !== zarrLoadGen) return;
    if (!result.ok) {
        showNotification(result.error || 'Failed to load dataset info', 'error');
        showLoading(false);
        return;
    }

    zarrInfo = result.data;
    displayZarrMetadata(zarrInfo);
    populateTimeSteps(zarrInfo);

    // Auto-populate rescale from statistics
    autoConfigureRescale(zarrInfo);

    // Auto-load tiles
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
 * Populate variable selector from a list of variable names.
 * @param {string[]} varList - Variable names from /xarray/dataset/keys
 * @param {string} selectedVar - Variable to select
 */
function populateVariablesFromKeys(varList, selectedVar) {
    const select = document.getElementById('variable-select');
    select.innerHTML = '';

    varList.forEach(function(v) {
        const option = document.createElement('option');
        option.value = v;
        option.textContent = v;
        if (v === selectedVar) option.selected = true;
        select.appendChild(option);
    });
}


/**
 * Auto-configure rescale min/max from dataset info.
 *
 * Uses band statistics if available, otherwise falls back to dtype-based heuristics.
 * @param {object} info - XArray info response (from /xarray/info?variable=...)
 */
function autoConfigureRescale(info) {
    const minInput = document.getElementById('zarr-min');
    const maxInput = document.getElementById('zarr-max');

    // Try to extract min/max from band statistics
    if (info.band_metadata && info.band_metadata.length > 0) {
        const bandMeta = info.band_metadata[0];
        // band_metadata is [["b1", {metadata}]] — check the metadata dict
        if (bandMeta.length >= 2 && typeof bandMeta[1] === 'object') {
            const meta = bandMeta[1];
            if (meta.min !== undefined && meta.max !== undefined) {
                minInput.value = meta.min;
                maxInput.value = meta.max;
                return;
            }
        }
    }

    // Try statistics object
    if (info.statistics) {
        const stats = Object.values(info.statistics)[0];
        if (stats && stats.min !== undefined && stats.max !== undefined) {
            minInput.value = stats.min;
            maxInput.value = stats.max;
            return;
        }
    }

    // Fallback: dtype-based heuristics
    const dtype = (info.dtype || '').toLowerCase();
    if (dtype.includes('float')) {
        // Float data — assume symmetric around 0 as starting point
        minInput.value = -10;
        maxInput.value = 10;
    } else if (dtype.includes('uint8') || dtype === 'u1') {
        minInput.value = 0;
        maxInput.value = 255;
    } else if (dtype.includes('uint16') || dtype === 'u2') {
        minInput.value = 0;
        maxInput.value = 65535;
    } else if (dtype.includes('int16') || dtype === 'i2') {
        minInput.value = -32768;
        maxInput.value = 32767;
    } else {
        // Generic fallback
        minInput.value = 0;
        maxInput.value = 1;
    }
}


/**
 * Handle variable selection change: re-fetch info for new variable,
 * update rescale, then refresh tiles.
 */
async function onVariableChange() {
    const variable = document.getElementById('variable-select').value;
    if (!variable || !currentZarrUrl) return;

    showLoading(true);

    // Fetch info for the newly selected variable
    const result = await fetchJSON('/xarray/info?url=' + encodeURIComponent(currentZarrUrl)
        + '&variable=' + encodeURIComponent(variable));

    if (result.ok) {
        zarrInfo = result.data;
        autoConfigureRescale(result.data);
    }

    updateZarrTiles();
    showLoading(false);
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
