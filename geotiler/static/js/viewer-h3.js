/**
 * H3 Hexagonal Viewer JavaScript for geotiler.
 *
 * Depends on: MapLibre GL JS 4.x, deck.gl 9.x, h3-js 4.x,
 *             common.js (fetchJSON, showNotification, escapeHtml)
 */

let h3Map = null;
let deckOverlay = null;
let currentH3Data = [];
let currentPalette = 'emergency_red';
let h3LoadGen = 0;


// ============================================================================
// Color Palettes
// ============================================================================

const PALETTES = {
    emergency_red: [
        [255, 255, 204], [255, 237, 160], [254, 178, 76],
        [253, 141, 60], [240, 59, 32], [189, 0, 38],
    ],
    viridis: [
        [68, 1, 84], [72, 40, 120], [62, 74, 137],
        [49, 104, 142], [38, 130, 142], [53, 183, 121], [253, 231, 37],
    ],
    plasma: [
        [13, 8, 135], [84, 2, 163], [139, 10, 165],
        [185, 50, 137], [219, 92, 104], [244, 136, 73], [240, 249, 33],
    ],
    ylgnbu: [
        [255, 255, 217], [199, 233, 180], [127, 205, 187],
        [65, 182, 196], [29, 145, 192], [34, 94, 168], [12, 44, 132],
    ],
    rdylgn: [
        [215, 48, 39], [244, 109, 67], [253, 174, 97],
        [254, 224, 139], [166, 217, 106], [102, 189, 99], [26, 152, 80],
    ],
    spectral: [
        [213, 62, 79], [252, 141, 89], [254, 224, 139],
        [255, 255, 191], [230, 245, 152], [153, 213, 148], [50, 136, 189],
    ],
    hot: [
        [10, 0, 0], [128, 0, 0], [200, 30, 0],
        [255, 100, 0], [255, 200, 0], [255, 255, 100], [255, 255, 255],
    ],
};


// ============================================================================
// Initialization
// ============================================================================

/**
 * Initialize the H3 viewer with basemap and deck.gl overlay.
 */
function initH3Viewer() {
    h3Map = new maplibregl.Map({
        container: 'map',
        style: { version: 8, sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '&copy; OpenStreetMap contributors' } }, layers: [{ id: 'osm', type: 'raster', source: 'osm' }] },
        center: [0, 20],
        zoom: 2,
    });

    h3Map.addControl(new maplibregl.NavigationControl(), 'top-right');
    h3Map.addControl(new maplibregl.ScaleControl(), 'bottom-right');

    // Track map position
    h3Map.on('moveend', updateMapStatus);
    h3Map.on('zoomend', updateMapStatus);

    // Initialize deck.gl overlay
    deckOverlay = new deck.MapboxOverlay({ layers: [] });
    h3Map.addControl(deckOverlay);

    // Auto-query on load
    h3Map.on('load', () => queryH3());
}

function updateMapStatus() {
    const center = h3Map.getCenter();
    const zoom = h3Map.getZoom();
    document.getElementById('map-zoom').textContent = 'Zoom: ' + zoom.toFixed(1);
    document.getElementById('map-coords').textContent =
        center.lat.toFixed(4) + ', ' + center.lng.toFixed(4);
}


// ============================================================================
// Query H3 Data
// ============================================================================

/**
 * Query the H3 API with current selector values and render hexagons.
 */
async function queryH3() {
    const crop = document.getElementById('crop-select').value;
    const tech = document.getElementById('tech-select').value;
    const scenario = document.getElementById('scenario-select').value;

    showLoading(true);
    const myGen = ++h3LoadGen;

    const url = '/h3/query?crop=' + encodeURIComponent(crop)
        + '&tech=' + encodeURIComponent(tech)
        + '&scenario=' + encodeURIComponent(scenario);

    const result = await fetchJSON(url);
    if (myGen !== h3LoadGen) return;
    showLoading(false);

    if (!result.ok) {
        showNotification(result.error || 'H3 query failed', 'error');
        return;
    }

    const data = result.data.data || [];
    currentH3Data = data;

    renderHexagons(data);

    // Update stats
    const statsPanel = document.getElementById('h3-stats');
    const metaGrid = document.getElementById('h3-result-meta');
    const queryMs = (result.data.query_ms || 0).toFixed(0);

    if (data.length > 0) {
        const values = data.map(function(d) { return d.value; });
        const min = Math.min.apply(null, values);
        const max = Math.max.apply(null, values);
        const mean = values.reduce(function(a, b) { return a + b; }, 0) / values.length;

        metaGrid.innerHTML =
            '<div class="metadata-item"><div class="metadata-label">Hexagons</div><div class="metadata-value">' + data.length.toLocaleString() + '</div></div>' +
            '<div class="metadata-item"><div class="metadata-label">Query</div><div class="metadata-value">' + queryMs + ' ms</div></div>' +
            '<div class="metadata-item"><div class="metadata-label">Min</div><div class="metadata-value mono">' + min.toFixed(2) + '</div></div>' +
            '<div class="metadata-item"><div class="metadata-label">Max</div><div class="metadata-value mono">' + max.toFixed(2) + '</div></div>' +
            '<div class="metadata-item"><div class="metadata-label">Mean</div><div class="metadata-value mono">' + mean.toFixed(2) + '</div></div>' +
            '<div class="metadata-item"><div class="metadata-label">Selection</div><div class="metadata-value mono">' + escapeHtml(crop) + ' / ' + escapeHtml(tech) + '</div></div>';

        renderLegend(currentPalette, min, max);
    } else {
        metaGrid.innerHTML =
            '<div class="metadata-item full-width"><div class="metadata-label">Result</div><div class="metadata-value">No data</div></div>' +
            '<div class="metadata-item"><div class="metadata-label">Query</div><div class="metadata-value">' + queryMs + ' ms</div></div>';
    }
    statsPanel.classList.remove('hidden');
}


// ============================================================================
// Render Hexagons
// ============================================================================

/**
 * Render H3 hexagons using deck.gl H3HexagonLayer.
 * @param {Array} data - Array of {h3_index, value} objects
 */
function renderHexagons(data) {
    if (data.length === 0) {
        deckOverlay.setProps({ layers: [] });
        return;
    }

    const values = data.map(function(d) { return d.value; });
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const palette = PALETTES[currentPalette] || PALETTES.emergency_red;

    const layer = new deck.H3HexagonLayer({
        id: 'h3-layer',
        data: data,
        getHexagon: function(d) { return d.h3_index; },
        getFillColor: function(d) { return interpolateColor(palette, d.value, min, max); },
        extruded: false,
        pickable: true,
        opacity: 0.8,
        onHover: function(info) {
            if (info.object) {
                h3Map.getCanvas().style.cursor = 'pointer';
            } else {
                h3Map.getCanvas().style.cursor = '';
            }
        },
        onClick: function(info) {
            if (info.object) {
                showNotification(
                    'H3: ' + info.object.h3_index + ' | Value: ' + info.object.value.toFixed(2),
                    'info'
                );
            }
        },
    });

    deckOverlay.setProps({ layers: [layer] });
}


// ============================================================================
// Color Interpolation
// ============================================================================

/**
 * Interpolate a color from a palette based on a value.
 * @param {Array} palette - Array of [R, G, B] stops
 * @param {number} value - Data value
 * @param {number} min - Minimum value in dataset
 * @param {number} max - Maximum value in dataset
 * @returns {Array} [R, G, B, A]
 */
function interpolateColor(palette, value, min, max) {
    if (max === min) return [palette[0][0], palette[0][1], palette[0][2], 200];

    const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
    const idx = t * (palette.length - 1);
    const lower = Math.floor(idx);
    const upper = Math.min(lower + 1, palette.length - 1);
    const frac = idx - lower;

    return [
        Math.round(palette[lower][0] + (palette[upper][0] - palette[lower][0]) * frac),
        Math.round(palette[lower][1] + (palette[upper][1] - palette[lower][1]) * frac),
        Math.round(palette[lower][2] + (palette[upper][2] - palette[lower][2]) * frac),
        200,
    ];
}


// ============================================================================
// Palette Management
// ============================================================================

/**
 * Update the color palette and re-render hexagons.
 */
function updatePalette() {
    currentPalette = document.getElementById('palette-select').value;
    if (currentH3Data.length > 0) {
        renderHexagons(currentH3Data);

        const values = currentH3Data.map(function(d) { return d.value; });
        renderLegend(currentPalette, Math.min.apply(null, values), Math.max.apply(null, values));
    }
}


// ============================================================================
// Legend
// ============================================================================

/**
 * Render a gradient legend in the sidebar.
 * @param {string} paletteName - Name of the palette
 * @param {number} min - Minimum data value
 * @param {number} max - Maximum data value
 */
function renderLegend(paletteName, min, max) {
    const container = document.getElementById('h3-legend');
    const palette = PALETTES[paletteName] || PALETTES.emergency_red;

    // Build CSS gradient
    const stops = palette.map(function(c, i) {
        const pct = (i / (palette.length - 1) * 100).toFixed(0);
        return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ') ' + pct + '%';
    }).join(', ');

    container.innerHTML =
        '<div style="height:16px;border-radius:4px;background:linear-gradient(to right, ' + stops + ');"></div>' +
        '<div style="display:flex;justify-content:space-between;font-size:0.7rem;color:var(--color-gray);margin-top:2px;">' +
        '<span>' + min.toFixed(1) + '</span>' +
        '<span>' + max.toFixed(1) + '</span>' +
        '</div>';
}


// ============================================================================
// UI Helpers
// ============================================================================

function showLoading(show) {
    var overlay = document.getElementById('map-loading');
    if (show) {
        overlay.classList.remove('hidden');
    } else {
        overlay.classList.add('hidden');
    }
}
