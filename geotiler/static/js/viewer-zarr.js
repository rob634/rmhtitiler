/**
 * Zarr/NetCDF Viewer JavaScript for geotiler.
 *
 * Depends on: MapLibre GL JS 4.x, common.js (fetchJSON, getQueryParam, setQueryParam, showNotification, escapeHtml)
 */

let zarrMap = null;
let currentZarrUrl = null;
let zarrInfo = null;

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
        style: 'https://demotiles.maplibre.org/style.json',
        center: [0, 20],
        zoom: 2,
    });

    zarrMap.addControl(new maplibregl.NavigationControl(), 'top-right');

    // Auto-load from query parameter
    const urlParam = getQueryParam('url');
    if (urlParam) {
        document.getElementById('zarr-url').value = urlParam;
        zarrMap.on('load', () => loadZarr());
    }
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

    // Fetch XArray info
    const result = await fetchJSON('/xarray/info?url=' + encodeURIComponent(url));
    if (!result.ok) {
        showNotification(result.error || 'Failed to load dataset info', 'error');
        return;
    }

    zarrInfo = result.data;
    displayZarrMetadata(zarrInfo);
    populateVariables(zarrInfo);
    populateTimeSteps(zarrInfo);

    // Auto-load first variable
    updateZarrTiles();

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
        ? `${bounds[0].toFixed(4)}, ${bounds[1].toFixed(4)} to ${bounds[2].toFixed(4)}, ${bounds[3].toFixed(4)}`
        : 'Unknown';

    const dims = info.dims ? Object.entries(info.dims).map(([k, v]) => `${k}=${v}`).join(', ') : 'Unknown';

    metadata.innerHTML = `
        <table class="data-table">
            <tr><td><strong>Bounds</strong></td><td>${escapeHtml(boundsStr)}</td></tr>
            <tr><td><strong>Dimensions</strong></td><td>${escapeHtml(dims)}</td></tr>
            ${info.crs ? `<tr><td><strong>CRS</strong></td><td>${escapeHtml(info.crs)}</td></tr>` : ''}
        </table>
    `;

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

    varList.forEach(v => {
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
    const timeDim = timeKeys.find(k => k in dims);

    if (!timeDim || !info.coords || !info.coords[timeDim]) {
        container.classList.add('hidden');
        return;
    }

    select.innerHTML = '';
    const timeValues = info.coords[timeDim];
    (Array.isArray(timeValues) ? timeValues : []).forEach((t, i) => {
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

    let tileUrl = '/xarray/tiles/{z}/{x}/{y}?url=' + encodeURIComponent(currentZarrUrl)
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
