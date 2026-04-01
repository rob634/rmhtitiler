/**
 * Raster (COG) Viewer JavaScript for geotiler.
 *
 * Depends on: MapLibre GL JS 4.x, common.js (fetchJSON, getQueryParam, setQueryParam, showNotification, escapeHtml)
 */

let rasterMap = null;
let currentCogUrl = null;
let cogInfo = null;
let currentStretch = 'auto';
let pointQueryActive = false;
let allBandStats = null;
let rasterLoadGen = 0;

const SOURCE_ID = 'raster-tiles';
const LAYER_ID = 'raster-layer';

/**
 * Convert https://{account}.blob.core.windows.net/{container}/{path}
 * to /vsiaz/{container}/{path} for GDAL managed identity auth.
 */
function toVsiaz(url) {
    var m = url.match(/^https?:\/\/[^/]+\.blob\.core\.windows\.net\/(.+)$/);
    return m ? '/vsiaz/' + m[1] : url;
}


// ============================================================================
// Initialization
// ============================================================================

/**
 * Initialize the raster viewer. Creates MapLibre map and auto-loads URL from query params.
 */
function initRasterViewer() {
    rasterMap = new maplibregl.Map({
        container: 'map',
        style: { version: 8, sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '&copy; OpenStreetMap contributors' } }, layers: [{ id: 'osm', type: 'raster', source: 'osm' }] },
        center: [0, 20],
        zoom: 2,
    });

    rasterMap.addControl(new maplibregl.NavigationControl(), 'top-right');
    rasterMap.addControl(new maplibregl.ScaleControl(), 'bottom-right');

    // Track map position for status overlay
    rasterMap.on('moveend', updateMapStatus);
    rasterMap.on('zoomend', updateMapStatus);

    // Point query click handler
    rasterMap.on('click', handleMapClick);

    // Auto-load from query parameter
    const urlParam = getQueryParam('url');
    const collParam = getQueryParam('collection');
    if (urlParam) {
        document.getElementById('cog-url').value = urlParam;
        rasterMap.on('load', () => loadRaster());
    } else if (collParam) {
        rasterMap.on('load', () => loadFromStacCollection(collParam));
    }
}

function updateMapStatus() {
    const center = rasterMap.getCenter();
    const zoom = rasterMap.getZoom();
    document.getElementById('map-zoom').textContent = 'Zoom: ' + zoom.toFixed(1);
    document.getElementById('map-coords').textContent =
        center.lat.toFixed(4) + ', ' + center.lng.toFixed(4);
}


// ============================================================================
// Load from STAC Collection
// ============================================================================

/**
 * Resolve a STAC collection to a COG asset URL and load it.
 * Called when viewer is opened with ?collection=X from the catalog.
 * @param {string} collectionId - STAC collection identifier
 */
async function loadFromStacCollection(collectionId) {
    showLoading(true);

    // Fetch first item from STAC collection
    const result = await fetchJSON('/stac/collections/' + encodeURIComponent(collectionId) + '/items?limit=1');
    if (!result.ok) {
        showNotification('STAC collection "' + collectionId + '" not found or unavailable', 'error');
        showLoading(false);
        return;
    }

    const features = (result.data && result.data.features) || [];
    if (features.length === 0) {
        showNotification('STAC collection "' + collectionId + '" has no items to display', 'error');
        showLoading(false);
        return;
    }

    // Find a viewable raster asset from the first item
    const item = features[0];
    const cogUrl = extractCogUrl(item);
    if (!cogUrl) {
        showNotification('No viewable raster asset found in "' + collectionId + '"', 'error');
        showLoading(false);
        return;
    }

    // Set URL input and load normally
    document.getElementById('cog-url').value = cogUrl;
    showLoading(false);
    loadRaster();
}

/**
 * Extract a COG/GeoTIFF URL from a STAC item's assets.
 * Tries well-known asset keys first, then falls back to media type / extension matching.
 * @param {object} item - STAC item with assets
 * @returns {string|null} COG URL (converted to /vsiaz/ if applicable) or null
 */
function extractCogUrl(item) {
    if (!item || !item.assets) return null;

    // Try well-known asset keys in priority order
    var preferredKeys = ['visual', 'data', 'image', 'default', 'cog', 'analytic'];
    for (var i = 0; i < preferredKeys.length; i++) {
        var asset = item.assets[preferredKeys[i]];
        if (asset && asset.href) return toVsiaz(asset.href);
    }

    // Try matching by media type or file extension
    var entries = Object.entries(item.assets);
    for (var j = 0; j < entries.length; j++) {
        var a = entries[j][1];
        if (!a.href) continue;
        var isGeoTiff = (a.type && (a.type.indexOf('geotiff') !== -1 || a.type.indexOf('tiff') !== -1));
        var hasTifExt = (a.href.endsWith('.tif') || a.href.endsWith('.tiff'));
        if (isGeoTiff || hasTifExt) return toVsiaz(a.href);
    }

    // Last resort: first asset with any href
    for (var k = 0; k < entries.length; k++) {
        if (entries[k][1].href) return toVsiaz(entries[k][1].href);
    }

    return null;
}


// ============================================================================
// Load Raster
// ============================================================================

/**
 * Load a COG URL: fetch info, display metadata, add tile layer.
 */
async function loadRaster() {
    var url = document.getElementById('cog-url').value.trim();
    if (!url) {
        showNotification('Please enter a COG URL', 'warning');
        return;
    }

    // Auto-convert https blob URLs to /vsiaz/ for managed identity auth
    url = toVsiaz(url);
    document.getElementById('cog-url').value = url;

    currentCogUrl = url;
    setQueryParam('url', url);
    showLoading(true);
    const myGen = ++rasterLoadGen;

    // Fetch COG info
    const result = await fetchJSON('/cog/info?url=' + encodeURIComponent(url));
    if (myGen !== rasterLoadGen) return;
    if (!result.ok) {
        showNotification(result.error || 'Failed to load COG info', 'error');
        showLoading(false);
        return;
    }

    cogInfo = result.data;
    displayMetadata(cogInfo);
    buildBandControls(cogInfo);

    // Fetch statistics
    await fetchStatistics(url);
    if (myGen !== rasterLoadGen) return;

    addTileLayer(url, cogInfo.bounds);
    showLoading(false);

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
        ? bounds[0].toFixed(4) + ', ' + bounds[1].toFixed(4) + ' to ' + bounds[2].toFixed(4) + ', ' + bounds[3].toFixed(4)
        : 'Unknown';

    const bandCount = info.band_metadata ? info.band_metadata.length : (info.count || 'Unknown');

    metadata.innerHTML =
        '<div class="metadata-item"><div class="metadata-label">Bands</div><div class="metadata-value">' + escapeHtml(String(bandCount)) + '</div></div>' +
        '<div class="metadata-item"><div class="metadata-label">Data Type</div><div class="metadata-value mono">' + escapeHtml(info.dtype || 'Unknown') + '</div></div>' +
        (info.width ? '<div class="metadata-item"><div class="metadata-label">Width</div><div class="metadata-value">' + escapeHtml(String(info.width)) + ' px</div></div>' : '') +
        (info.height ? '<div class="metadata-item"><div class="metadata-label">Height</div><div class="metadata-value">' + escapeHtml(String(info.height)) + ' px</div></div>' : '') +
        '<div class="metadata-item"><div class="metadata-label">CRS</div><div class="metadata-value mono">' + escapeHtml(info.crs || 'Unknown') + '</div></div>' +
        '<div class="metadata-item full-width"><div class="metadata-label">Bounds</div><div class="metadata-value mono">' + escapeHtml(boundsStr) + '</div></div>' +
        (info.nodata !== null && info.nodata !== undefined ?
            '<div class="metadata-item"><div class="metadata-label">NoData</div><div class="metadata-value mono">' + escapeHtml(String(info.nodata)) + '</div></div>' : '');

    panel.classList.remove('hidden');
}


// ============================================================================
// Band Controls
// ============================================================================

/**
 * Build band selection controls: R/G/B dropdowns for multi-band, single selector for single-band.
 * @param {object} info - COG info response
 */
function buildBandControls(info) {
    const container = document.getElementById('band-controls');
    const presetsContainer = document.getElementById('band-presets');
    const bandCount = info.band_metadata ? info.band_metadata.length : (info.count || 0);

    if (bandCount <= 1) {
        container.innerHTML = '<span class="text-muted" style="font-size:0.8rem;">Single band dataset</span>';
        presetsContainer.classList.add('hidden');
        return;
    }

    // Build band options with descriptions when available
    var bandOptions = [];
    for (var i = 1; i <= Math.min(bandCount, 20); i++) {
        var label = 'Band ' + i;
        if (info.band_descriptions && info.band_descriptions[i - 1] && info.band_descriptions[i - 1][1]) {
            label = i + ': ' + info.band_descriptions[i - 1][1];
        } else if (info.band_metadata && info.band_metadata[i - 1]) {
            var meta = info.band_metadata[i - 1];
            var desc = (meta[1] && meta[1].DESCRIPTION) || (meta[1] && meta[1].description);
            if (desc) label = i + ': ' + desc;
        }
        bandOptions.push({ value: i, label: label });
    }

    // R/G/B selectors — G and B get a "None" option for single-band mode
    var colors = [
        { id: 'band-r', label: 'R', cls: 'red', defaultVal: 1, allowNone: false },
        { id: 'band-g', label: 'G', cls: 'green', defaultVal: Math.min(2, bandCount), allowNone: true },
        { id: 'band-b', label: 'B', cls: 'blue', defaultVal: Math.min(3, bandCount), allowNone: true },
    ];

    var html = '';
    colors.forEach(function(c) {
        html += '<div class="band-selector-row" style="margin-bottom:var(--space-xs);">' +
            '<span class="band-label ' + c.cls + '">' + c.label + '</span>' +
            '<select id="' + c.id + '" class="form-select" onchange="updateTiles()" style="padding:4px 8px;font-size:0.8rem;">';
        if (c.allowNone) {
            html += '<option value="">-- None --</option>';
        }
        bandOptions.forEach(function(opt) {
            var selected = (opt.value === c.defaultVal) ? ' selected' : '';
            html += '<option value="' + opt.value + '"' + selected + '>' + escapeHtml(opt.label) + '</option>';
        });
        html += '</select></div>';
    });
    container.innerHTML = html;

    // Presets
    var presets = '<button class="preset-btn" onclick="setBandPreset(1,\'\',\'\')">Gray</button>';
    if (bandCount >= 3) {
        presets += '<button class="preset-btn" onclick="setBandPreset(1,2,3)">RGB</button>';
    }
    if (bandCount >= 4) {
        presets += '<button class="preset-btn" onclick="setBandPreset(4,3,2)">NIR</button>';
    }
    presetsContainer.innerHTML = presets;
    presetsContainer.classList.remove('hidden');
}

/**
 * Set band preset by updating R/G/B selectors and reloading tiles.
 */
function setBandPreset(r, g, b) {
    const rSel = document.getElementById('band-r');
    const gSel = document.getElementById('band-g');
    const bSel = document.getElementById('band-b');
    if (rSel) rSel.value = r;
    if (gSel) gSel.value = g;
    if (bSel) bSel.value = b;
    updateTiles();
}


// ============================================================================
// Stretch Controls
// ============================================================================

/**
 * Set stretch mode and update tiles.
 * @param {string} mode - 'auto', 'p2-98', 'p5-95', 'minmax', 'custom'
 */
function setStretch(mode) {
    currentStretch = mode;

    // Update active button
    document.querySelectorAll('.stretch-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.stretch === mode);
    });

    // Show/hide custom inputs
    const customDiv = document.getElementById('custom-rescale');
    if (mode === 'custom') {
        customDiv.classList.remove('hidden');
    } else {
        customDiv.classList.add('hidden');
        updateTiles();
    }
}

/**
 * Get rescale values based on current stretch mode and statistics.
 * @returns {string|null} Rescale string like "0,255" or null
 */
function getRescaleValues() {
    if (currentStretch === 'custom') {
        const min = document.getElementById('rescale-min').value;
        const max = document.getElementById('rescale-max').value;
        return (min && max) ? min + ',' + max : null;
    }

    if (!allBandStats) return null;

    // Use the first selected band's statistics (R band, or band-r selector)
    var bandR = document.getElementById('band-r');
    var bandIdx = bandR ? bandR.value : '1';
    var bandKey = 'b' + bandIdx;
    var stats = allBandStats[bandKey];

    // Fallback: try first available key if bandKey not found
    if (!stats) {
        var firstKey = Object.keys(allBandStats)[0];
        stats = firstKey ? allBandStats[firstKey] : null;
    }
    if (!stats) return null;

    if (currentStretch === 'minmax' && stats.min !== undefined) {
        return stats.min + ',' + stats.max;
    }
    if (currentStretch === 'p2-98' && stats.percentile_2 !== undefined) {
        return stats.percentile_2 + ',' + stats.percentile_98;
    }
    if (currentStretch === 'p5-95' && stats.percentile_5 !== undefined) {
        return stats.percentile_5 + ',' + stats.percentile_95;
    }

    return null;
}


// ============================================================================
// Statistics
// ============================================================================

/**
 * Fetch band statistics for the dataset.
 */
async function fetchStatistics(url) {
    const result = await fetchJSON('/cog/statistics?url=' + encodeURIComponent(url));
    if (!result.ok || !result.data) {
        allBandStats = null;
        return;
    }

    allBandStats = result.data;
    displayStatistics(result.data);
}

/**
 * Render band statistics in the sidebar.
 */
function displayStatistics(data) {
    const section = document.getElementById('stats-section');
    const container = document.getElementById('band-stats');

    const entries = Object.entries(data);
    if (entries.length === 0) return;

    let html = '';
    entries.forEach(([bandName, stats]) => {
        html += '<div style="margin-bottom:var(--space-sm);">' +
            '<div style="font-size:0.7rem;font-weight:600;color:var(--color-navy);margin-bottom:2px;">' + escapeHtml(bandName) + '</div>' +
            '<div class="stats-bands">' +
            '<div class="stat-band"><span class="stat-key">min</span> <span class="stat-val">' + formatStatVal(stats.min) + '</span></div>' +
            '<div class="stat-band"><span class="stat-key">max</span> <span class="stat-val">' + formatStatVal(stats.max) + '</span></div>' +
            '<div class="stat-band"><span class="stat-key">mean</span> <span class="stat-val">' + formatStatVal(stats.mean) + '</span></div>' +
            '<div class="stat-band"><span class="stat-key">std</span> <span class="stat-val">' + formatStatVal(stats.std) + '</span></div>' +
            '</div></div>';
    });

    container.innerHTML = html;
    section.style.display = '';
}

function formatStatVal(val) {
    if (val === null || val === undefined) return '--';
    return typeof val === 'number' ? val.toFixed(2) : String(val);
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

    // Update layer info overlay
    updateLayerInfo();
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
    let tileUrl = '/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=' + encodeURIComponent(url);

    // Colormap
    const colormap = document.getElementById('colormap-select').value;
    if (colormap) {
        tileUrl += '&colormap_name=' + colormap;
    }

    // Rescale
    const rescale = getRescaleValues();
    if (rescale) {
        tileUrl += '&rescale=' + rescale;
    }

    // Bands (R/G/B selectors — filter out empty "None" values)
    const bandR = document.getElementById('band-r');
    if (bandR) {
        var bands = [bandR.value,
            document.getElementById('band-g').value,
            document.getElementById('band-b').value
        ].filter(function(b) { return b !== ''; });
        bands.forEach(function(b) {
            tileUrl += '&bidx=' + b;
        });
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

/**
 * Update the layer info overlay.
 */
function updateLayerInfo() {
    const info = document.getElementById('layer-info');
    const bandR = document.getElementById('band-r');

    let bandsText = 'Single band';
    if (bandR) {
        bandsText = 'R:' + bandR.value + ' G:' + document.getElementById('band-g').value + ' B:' + document.getElementById('band-b').value;
    }

    document.getElementById('layer-name').textContent = currentCogUrl ? currentCogUrl.split('/').pop() : '';
    document.getElementById('layer-bands').textContent = bandsText;
    document.getElementById('layer-stretch').textContent = currentStretch;
    info.classList.remove('hidden');
}


// ============================================================================
// Point Query
// ============================================================================

/**
 * Toggle point query mode on/off.
 */
function togglePointQuery() {
    pointQueryActive = !pointQueryActive;
    const btn = document.getElementById('btn-point-query');

    if (pointQueryActive) {
        btn.textContent = 'Disable Point Query';
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-primary');
        rasterMap.getCanvas().style.cursor = 'crosshair';
    } else {
        btn.textContent = 'Enable Point Query';
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-secondary');
        rasterMap.getCanvas().style.cursor = '';
        document.getElementById('point-result').classList.add('hidden');
    }
}

/**
 * Handle map click for point query.
 */
async function handleMapClick(e) {
    if (!pointQueryActive || !currentCogUrl) return;

    const lng = e.lngLat.lng;
    const lat = e.lngLat.lat;

    const resultDiv = document.getElementById('point-result');
    resultDiv.innerHTML = '<div class="text-muted" style="font-size:0.8rem;">Querying...</div>';
    resultDiv.classList.remove('hidden');

    const result = await fetchJSON('/cog/point/' + lng + ',' + lat + '?url=' + encodeURIComponent(currentCogUrl));
    if (!result.ok) {
        resultDiv.innerHTML = '<div class="text-error" style="font-size:0.8rem;">No data at this location</div>';
        return;
    }

    const values = result.data.values || [];
    let html = '<div class="metadata-grid">' +
        '<div class="metadata-item full-width"><div class="metadata-label">Location</div><div class="metadata-value mono">' +
        lat.toFixed(6) + ', ' + lng.toFixed(6) + '</div></div>';
    values.forEach((v, i) => {
        html += '<div class="metadata-item"><div class="metadata-label">Band ' + (i + 1) + '</div><div class="metadata-value mono">' +
            (v !== null ? (typeof v === 'number' ? v.toFixed(4) : v) : 'nodata') + '</div></div>';
    });
    html += '</div>';
    resultDiv.innerHTML = html;
}


// ============================================================================
// UI Helpers
// ============================================================================

function showLoading(show) {
    const overlay = document.getElementById('map-loading');
    if (show) {
        overlay.classList.remove('hidden');
    } else {
        overlay.classList.add('hidden');
    }
}
