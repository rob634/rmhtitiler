/**
 * Raster (COG) Viewer JavaScript for geotiler.
 *
 * Depends on: MapLibre GL JS 4.x, common.js (fetchJSON, getQueryParam, setQueryParam, showNotification, escapeHtml)
 */

let rasterMap = null;
let currentCogUrl = null;
let cogInfo = null;

const SOURCE_ID = 'raster-tiles';
const LAYER_ID = 'raster-layer';


// ============================================================================
// Initialization
// ============================================================================

/**
 * Initialize the raster viewer. Creates MapLibre map and auto-loads URL from query params.
 */
function initRasterViewer() {
    rasterMap = new maplibregl.Map({
        container: 'map',
        style: 'https://demotiles.maplibre.org/style.json',
        center: [0, 20],
        zoom: 2,
    });

    rasterMap.addControl(new maplibregl.NavigationControl(), 'top-right');

    // Auto-load from query parameter
    const urlParam = getQueryParam('url');
    if (urlParam) {
        document.getElementById('cog-url').value = urlParam;
        rasterMap.on('load', () => loadRaster());
    }
}


// ============================================================================
// Load Raster
// ============================================================================

/**
 * Load a COG URL: fetch info, display metadata, add tile layer.
 */
async function loadRaster() {
    const url = document.getElementById('cog-url').value.trim();
    if (!url) {
        showNotification('Please enter a COG URL', 'warning');
        return;
    }

    currentCogUrl = url;
    setQueryParam('url', url);

    // Fetch COG info
    const result = await fetchJSON('/cog/info?url=' + encodeURIComponent(url));
    if (!result.ok) {
        showNotification(result.error || 'Failed to load COG info', 'error');
        return;
    }

    cogInfo = result.data;
    displayMetadata(cogInfo);
    addTileLayer(url, cogInfo.bounds);

    showNotification('Raster loaded successfully', 'success');
}


// ============================================================================
// Metadata Display
// ============================================================================

/**
 * Render dataset metadata in the sidebar.
 * @param {object} info - COG info response
 */
function displayMetadata(info) {
    const panel = document.getElementById('raster-info');
    const metadata = document.getElementById('raster-metadata');

    const bounds = info.bounds || [];
    const boundsStr = bounds.length === 4
        ? `${bounds[0].toFixed(4)}, ${bounds[1].toFixed(4)} to ${bounds[2].toFixed(4)}, ${bounds[3].toFixed(4)}`
        : 'Unknown';

    const bandCount = info.band_metadata ? info.band_metadata.length : (info.count || 'Unknown');

    metadata.innerHTML = `
        <table class="data-table">
            <tr><td><strong>Bounds</strong></td><td>${escapeHtml(boundsStr)}</td></tr>
            <tr><td><strong>Bands</strong></td><td>${escapeHtml(String(bandCount))}</td></tr>
            <tr><td><strong>Data Type</strong></td><td>${escapeHtml(info.dtype || 'Unknown')}</td></tr>
            <tr><td><strong>CRS</strong></td><td>${escapeHtml(info.crs || 'Unknown')}</td></tr>
            ${info.width ? `<tr><td><strong>Size</strong></td><td>${info.width} x ${info.height}</td></tr>` : ''}
        </table>
    `;

    // Build band controls
    buildBandControls(info);

    panel.classList.remove('hidden');
}

/**
 * Build band selection checkboxes from COG info.
 * @param {object} info - COG info response
 */
function buildBandControls(info) {
    const container = document.getElementById('band-controls');
    const bandCount = info.band_metadata ? info.band_metadata.length : (info.count || 0);

    if (bandCount <= 1) {
        container.innerHTML = '<span class="text-muted">Single band</span>';
        return;
    }

    let html = '';
    for (let i = 1; i <= Math.min(bandCount, 10); i++) {
        const checked = i <= 3 ? 'checked' : '';
        html += `<label style="margin-right: var(--space-sm);">
            <input type="checkbox" value="${i}" class="band-checkbox" ${checked}
                   onchange="updateTiles()"> B${i}
        </label>`;
    }
    container.innerHTML = html;
}


// ============================================================================
// Tile Layer Management
// ============================================================================

/**
 * Add a raster tile layer to the map.
 * @param {string} url - COG URL
 * @param {Array} bounds - [west, south, east, north]
 */
function addTileLayer(url, bounds) {
    removeTileLayer();

    const tileUrl = buildTileUrl(url);

    rasterMap.addSource(SOURCE_ID, {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
        bounds: bounds || undefined,
    });

    rasterMap.addLayer({
        id: LAYER_ID,
        type: 'raster',
        source: SOURCE_ID,
    });

    // Fit to bounds if available
    if (bounds && bounds.length === 4) {
        rasterMap.fitBounds(
            [[bounds[0], bounds[1]], [bounds[2], bounds[3]]],
            { padding: 50, maxZoom: 16 }
        );
    }
}

/**
 * Remove existing tile layer and source.
 */
function removeTileLayer() {
    if (rasterMap.getLayer(LAYER_ID)) {
        rasterMap.removeLayer(LAYER_ID);
    }
    if (rasterMap.getSource(SOURCE_ID)) {
        rasterMap.removeSource(SOURCE_ID);
    }
}

/**
 * Build the tile URL with current parameters.
 * @param {string} url - COG URL
 * @returns {string} Full tile URL template
 */
function buildTileUrl(url) {
    let tileUrl = '/cog/tiles/{z}/{x}/{y}?url=' + encodeURIComponent(url);

    // Colormap
    const colormap = document.getElementById('colormap-select').value;
    if (colormap) {
        tileUrl += '&colormap_name=' + colormap;
    }

    // Rescale
    const min = document.getElementById('rescale-min').value;
    const max = document.getElementById('rescale-max').value;
    if (min && max) {
        tileUrl += '&rescale=' + min + ',' + max;
    }

    // Bands
    const bandCheckboxes = document.querySelectorAll('.band-checkbox:checked');
    if (bandCheckboxes.length > 0) {
        const bands = Array.from(bandCheckboxes).map(cb => cb.value);
        tileUrl += '&bidx=' + bands.join(',');
    }

    return tileUrl;
}

/**
 * Update tiles when visualization parameters change.
 */
function updateTiles() {
    if (!currentCogUrl) return;
    addTileLayer(currentCogUrl, cogInfo ? cogInfo.bounds : null);
}
