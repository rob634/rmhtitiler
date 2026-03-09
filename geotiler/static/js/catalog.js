/**
 * Catalog page JavaScript for geotiler.
 *
 * Depends on common.js: fetchJSON, debounce, escapeHtml, buildViewerUrl
 */

// ============================================================================
// Unified Catalog
// ============================================================================

/**
 * Load all collections (STAC + Vector) into the unified catalog list.
 * Called on DOMContentLoaded from the unified catalog template.
 * @param {boolean} stacEnabled - Whether STAC API is available
 * @param {boolean} tipgEnabled - Whether TiPG is available
 */
async function loadUnifiedCatalog(stacEnabled, tipgEnabled) {
    const grid = document.getElementById('catalog-grid');
    const emptyEl = document.getElementById('catalog-empty');
    let collections = [];

    // Fetch STAC collections
    if (stacEnabled) {
        const result = await fetchJSON('/stac/collections');
        if (result.ok && result.data.collections) {
            collections = collections.concat(
                result.data.collections.map(c => ({
                    id: c.id,
                    title: c.title || c.id,
                    description: c.description || '',
                    type: 'raster',
                    source: 'stac',
                    stac_version: c.stac_version || null,
                    license: c.license || null,
                    extent: c.extent,
                    href: buildViewerUrl('raster', { collection: c.id }),
                    itemsHref: '/stac/collections/' + encodeURIComponent(c.id) + '/items',
                    apiHref: '/stac/collections/' + encodeURIComponent(c.id),
                }))
            );
        }
    }

    // Fetch Vector collections
    if (tipgEnabled) {
        const result = await fetchJSON('/vector/collections?f=json');
        if (result.ok && result.data.collections) {
            collections = collections.concat(
                result.data.collections
                    .filter(c => c.id !== 'public.spatial_ref_sys')
                    .map(c => ({
                        id: c.id,
                        title: c.title || c.id,
                        description: c.description || '',
                        type: 'vector',
                        source: 'tipg',
                        itemType: c.itemType || 'feature',
                        crs: (c.crs && c.crs[0]) ? c.crs[0] : null,
                        extent: c.extent,
                        href: buildViewerUrl('vector', { collection: c.id }),
                        itemsHref: '/vector/collections/' + encodeURIComponent(c.id) + '/items?limit=10',
                        apiHref: '/vector/collections/' + encodeURIComponent(c.id),
                    }))
            );
        }
    }

    // Sort alphabetically by title
    collections.sort((a, b) => a.title.localeCompare(b.title));

    renderUnifiedList(collections, grid, emptyEl);

    // Wire up search
    const searchInput = document.getElementById('catalog-search');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(() => {
            const query = searchInput.value.toLowerCase();
            const filtered = collections.filter(c =>
                c.title.toLowerCase().includes(query) ||
                c.description.toLowerCase().includes(query) ||
                c.id.toLowerCase().includes(query)
            );
            renderUnifiedList(filtered, grid, emptyEl);
        }, 300));
    }

    // Store for filter buttons
    window._catalogCollections = collections;
}


/**
 * Filter the unified catalog by collection type.
 * Called from filter button onclick handlers.
 * @param {string} type - 'all', 'raster', or 'vector'
 */
function filterCatalog(type) {
    const collections = window._catalogCollections || [];
    const filtered = type === 'all' ? collections : collections.filter(c => c.type === type);
    const grid = document.getElementById('catalog-grid');
    const emptyEl = document.getElementById('catalog-empty');
    renderUnifiedList(filtered, grid, emptyEl);

    // Update active button styling
    document.querySelectorAll('[data-filter]').forEach(btn => {
        btn.classList.toggle('btn-primary', btn.dataset.filter === type);
        btn.classList.toggle('btn-secondary', btn.dataset.filter !== type);
    });
}


/**
 * Render unified collection rows.
 * @param {Array} collections - Array of collection objects
 * @param {HTMLElement} grid - Container element
 * @param {HTMLElement} emptyEl - Empty state element
 */
function renderUnifiedList(collections, grid, emptyEl) {
    if (collections.length === 0) {
        grid.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    const countHtml = `<div class="catalog-count">${collections.length} collection${collections.length !== 1 ? 's' : ''}</div>`;

    grid.innerHTML = countHtml + '<div class="catalog-list">' + collections.map(c => {
        const typeBadge = c.type === 'raster'
            ? '<span class="badge badge-raster">Raster</span>'
            : '<span class="badge badge-vector">Vector</span>';

        const sourceBadge = c.source === 'stac'
            ? '<span class="badge badge-stac">STAC</span>'
            : '<span class="badge badge-ogc">OGC</span>';

        // Build metadata items
        const metaItems = [];
        metaItems.push(metaItem('Platform', c.source === 'stac' ? 'STAC API' : 'TiPG / PostGIS'));
        if (c.stac_version) metaItems.push(metaItem('STAC Version', c.stac_version));
        if (c.license) metaItems.push(metaItem('License', c.license));
        if (c.itemType) metaItems.push(metaItem('Item Type', c.itemType));

        const spatial = formatBbox(c.extent);
        if (spatial) metaItems.push(metaItem('Bbox', spatial));

        const temporal = formatExtent(c.extent);
        if (temporal) metaItems.push(metaItem('Temporal', temporal));

        if (c.crs) metaItems.push(metaItem('CRS', formatCrs(c.crs)));

        return `
            <div class="catalog-row">
                <div class="catalog-row-header">
                    <h3 class="catalog-row-title">${escapeHtml(c.title)}</h3>
                    ${typeBadge}
                    ${sourceBadge}
                    <span class="catalog-row-id">${escapeHtml(c.id)}</span>
                </div>
                ${c.description ? `<div class="catalog-row-description">${escapeHtml(c.description)}</div>` : ''}
                <div class="catalog-row-meta">
                    ${metaItems.join('')}
                </div>
                <div class="catalog-row-actions">
                    <a href="${escapeHtml(c.href)}" class="btn btn-primary btn-sm">View on Map</a>
                    <a href="${escapeHtml(c.itemsHref)}" class="btn btn-secondary btn-sm" target="_blank">Browse ${c.type === 'raster' ? 'Items' : 'Features'}</a>
                    <a href="${escapeHtml(c.apiHref)}" class="btn btn-secondary btn-sm" target="_blank">API JSON</a>
                </div>
            </div>
        `;
    }).join('') + '</div>';
}


// ============================================================================
// STAC Catalog
// ============================================================================

/**
 * Load STAC collections into the STAC catalog page.
 * Called on DOMContentLoaded from the STAC catalog template.
 */
async function loadStacCatalog() {
    const grid = document.getElementById('stac-grid');
    const emptyEl = document.getElementById('stac-empty');

    const result = await fetchJSON('/stac/collections');
    if (!result.ok) {
        grid.innerHTML = '';
        if (emptyEl) {
            emptyEl.classList.remove('hidden');
            emptyEl.querySelector('p').textContent = result.error || 'Failed to load STAC collections.';
        }
        return;
    }

    const collections = (result.data.collections || []).map(c => ({
        id: c.id,
        title: c.title || c.id,
        description: c.description || '',
        stac_version: c.stac_version || null,
        license: c.license || null,
        extent: c.extent,
        links: c.links || [],
    }));

    // Sort alphabetically
    collections.sort((a, b) => a.title.localeCompare(b.title));

    renderStacList(collections, grid, emptyEl);

    // Wire up search
    const searchInput = document.getElementById('stac-search');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(() => {
            const query = searchInput.value.toLowerCase();
            const filtered = collections.filter(c =>
                c.title.toLowerCase().includes(query) ||
                c.description.toLowerCase().includes(query) ||
                c.id.toLowerCase().includes(query)
            );
            renderStacList(filtered, grid, emptyEl);
        }, 300));
    }
}

/**
 * Render STAC collection rows with detailed metadata.
 * @param {Array} collections - STAC collection objects
 * @param {HTMLElement} grid - Container element
 * @param {HTMLElement} emptyEl - Empty state element
 */
function renderStacList(collections, grid, emptyEl) {
    if (collections.length === 0) {
        grid.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    const countHtml = `<div class="catalog-count">${collections.length} STAC collection${collections.length !== 1 ? 's' : ''}</div>`;

    grid.innerHTML = countHtml + '<div class="catalog-list">' + collections.map(c => {
        const viewerUrl = buildViewerUrl('raster', { collection: c.id });
        const temporal = formatExtent(c.extent);
        const spatial = formatBbox(c.extent);

        const metaItems = [];
        metaItems.push(metaItem('Platform', 'STAC API'));
        if (c.stac_version) metaItems.push(metaItem('STAC Version', c.stac_version));
        if (c.license) metaItems.push(metaItem('License', c.license));
        if (spatial) metaItems.push(metaItem('Bbox', spatial));
        if (temporal) metaItems.push(metaItem('Temporal', temporal));

        return `
            <div class="catalog-row">
                <div class="catalog-row-header">
                    <h3 class="catalog-row-title">${escapeHtml(c.title)}</h3>
                    <span class="badge badge-raster">Raster</span>
                    <span class="badge badge-stac">STAC</span>
                    <span class="catalog-row-id">${escapeHtml(c.id)}</span>
                </div>
                ${c.description ? `<div class="catalog-row-description">${escapeHtml(c.description)}</div>` : ''}
                <div class="catalog-row-meta">
                    ${metaItems.join('')}
                </div>
                <div class="catalog-row-actions">
                    <a href="${escapeHtml(viewerUrl)}" class="btn btn-primary btn-sm">View on Map</a>
                    <a href="/stac/collections/${escapeHtml(c.id)}/items" class="btn btn-secondary btn-sm" target="_blank">Browse Items</a>
                    <a href="/stac/collections/${escapeHtml(c.id)}" class="btn btn-secondary btn-sm" target="_blank">API JSON</a>
                </div>
            </div>
        `;
    }).join('') + '</div>';
}


// ============================================================================
// Vector Catalog
// ============================================================================

/**
 * Load Vector collections into the Vector catalog page.
 * Called on DOMContentLoaded from the Vector catalog template.
 */
async function loadVectorCatalog() {
    const grid = document.getElementById('vector-grid');
    const emptyEl = document.getElementById('vector-empty');

    const result = await fetchJSON('/vector/collections?f=json');
    if (!result.ok) {
        grid.innerHTML = '';
        if (emptyEl) {
            emptyEl.classList.remove('hidden');
            emptyEl.querySelector('p').textContent = result.error || 'Failed to load vector collections.';
        }
        return;
    }

    const collections = (result.data.collections || [])
        .filter(c => c.id !== 'public.spatial_ref_sys')
        .map(c => ({
            id: c.id,
            title: c.title || c.id,
            description: c.description || '',
            itemType: c.itemType || 'feature',
            crs: (c.crs && c.crs[0]) ? c.crs[0] : null,
            extent: c.extent,
            links: c.links || [],
        }));

    // Sort alphabetically
    collections.sort((a, b) => a.title.localeCompare(b.title));

    renderVectorList(collections, grid, emptyEl);

    // Wire up search
    const searchInput = document.getElementById('vector-search');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(() => {
            const query = searchInput.value.toLowerCase();
            const filtered = collections.filter(c =>
                c.title.toLowerCase().includes(query) ||
                c.description.toLowerCase().includes(query) ||
                c.id.toLowerCase().includes(query)
            );
            renderVectorList(filtered, grid, emptyEl);
        }, 300));
    }
}

/**
 * Render Vector collection rows.
 * @param {Array} collections - Vector collection objects
 * @param {HTMLElement} grid - Container element
 * @param {HTMLElement} emptyEl - Empty state element
 */
function renderVectorList(collections, grid, emptyEl) {
    if (collections.length === 0) {
        grid.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    const countHtml = `<div class="catalog-count">${collections.length} vector collection${collections.length !== 1 ? 's' : ''}</div>`;

    grid.innerHTML = countHtml + '<div class="catalog-list">' + collections.map(c => {
        const viewerUrl = buildViewerUrl('vector', { collection: c.id });
        const spatial = formatBbox(c.extent);

        const metaItems = [];
        metaItems.push(metaItem('Platform', 'TiPG / PostGIS'));
        if (c.itemType) metaItems.push(metaItem('Item Type', c.itemType));
        if (spatial) metaItems.push(metaItem('Bbox', spatial));
        if (c.crs) metaItems.push(metaItem('CRS', formatCrs(c.crs)));

        return `
            <div class="catalog-row">
                <div class="catalog-row-header">
                    <h3 class="catalog-row-title">${escapeHtml(c.title)}</h3>
                    <span class="badge badge-vector">Vector</span>
                    <span class="badge badge-ogc">OGC</span>
                    <span class="catalog-row-id">${escapeHtml(c.id)}</span>
                </div>
                ${c.description ? `<div class="catalog-row-description">${escapeHtml(c.description)}</div>` : ''}
                <div class="catalog-row-meta">
                    ${metaItems.join('')}
                </div>
                <div class="catalog-row-actions">
                    <a href="${escapeHtml(viewerUrl)}" class="btn btn-primary btn-sm">View on Map</a>
                    <a href="/vector/collections/${escapeHtml(c.id)}/items?limit=10" class="btn btn-secondary btn-sm" target="_blank">Browse Features</a>
                    <a href="/vector/collections/${escapeHtml(c.id)}" class="btn btn-secondary btn-sm" target="_blank">API JSON</a>
                </div>
            </div>
        `;
    }).join('') + '</div>';
}


// ============================================================================
// Collection Detail (STAC detail panel)
// ============================================================================

/**
 * Show detailed information for a selected collection.
 * @param {string} collectionJson - JSON string of the collection object
 */
function showCollectionDetail(collectionJson) {
    const c = JSON.parse(collectionJson);
    const detail = document.getElementById('collection-detail');
    if (!detail) return;

    document.getElementById('detail-title').textContent = c.title || c.id;
    document.getElementById('detail-description').textContent = c.description || '';

    const metadata = document.getElementById('detail-metadata');
    const temporal = formatExtent(c.extent);
    const spatial = formatBbox(c.extent);
    metadata.innerHTML = `
        <table class="data-table">
            <tr><td><strong>ID</strong></td><td><code>${escapeHtml(c.id)}</code></td></tr>
            ${c.stac_version ? `<tr><td><strong>STAC Version</strong></td><td>${escapeHtml(c.stac_version)}</td></tr>` : ''}
            ${c.license ? `<tr><td><strong>License</strong></td><td>${escapeHtml(c.license)}</td></tr>` : ''}
            ${spatial ? `<tr><td><strong>Bbox</strong></td><td><code>${escapeHtml(spatial)}</code></td></tr>` : ''}
            ${temporal ? `<tr><td><strong>Temporal</strong></td><td>${escapeHtml(temporal)}</td></tr>` : ''}
        </table>
    `;

    const viewerLink = document.getElementById('detail-viewer-link');
    viewerLink.href = buildViewerUrl('raster', { collection: c.id });

    const apiLink = document.getElementById('detail-api-link');
    apiLink.href = '/stac/collections/' + encodeURIComponent(c.id);

    detail.classList.remove('hidden');
    detail.scrollIntoView({ behavior: 'smooth' });
}


// ============================================================================
// Helpers
// ============================================================================

/**
 * Build a metadata item HTML snippet.
 * @param {string} label - Label text
 * @param {string} value - Value text
 * @returns {string} HTML string
 */
function metaItem(label, value) {
    return `<div class="catalog-meta-item">
        <span class="catalog-meta-label">${escapeHtml(label)}</span>
        <span class="catalog-meta-value">${escapeHtml(value)}</span>
    </div>`;
}

/**
 * Format a STAC extent object into a human-readable temporal string.
 * @param {object} extent - STAC extent object with temporal/spatial
 * @returns {string} Formatted extent description or empty string
 */
function formatExtent(extent) {
    if (!extent || !extent.temporal || !extent.temporal.interval) return '';

    const interval = extent.temporal.interval[0];
    if (!interval) return '';

    const start = interval[0] ? interval[0].substring(0, 10) : 'open';
    const end = interval[1] ? interval[1].substring(0, 10) : 'present';
    return start + ' to ' + end;
}

/**
 * Format spatial bbox from extent object.
 * @param {object} extent - Extent object with spatial.bbox
 * @returns {string} Formatted bbox string or empty string
 */
function formatBbox(extent) {
    if (!extent || !extent.spatial || !extent.spatial.bbox) return '';
    const bbox = extent.spatial.bbox[0];
    if (!bbox || bbox.length < 4) return '';
    return bbox.map(v => Number(v).toFixed(2)).join(', ');
}

/**
 * Format a CRS URI to a short readable name.
 * @param {string} crs - CRS URI string
 * @returns {string} Short CRS name
 */
function formatCrs(crs) {
    if (!crs) return '';
    if (crs.includes('CRS84')) return 'WGS 84 (CRS84)';
    if (crs.includes('4326')) return 'EPSG:4326';
    // Return last segment of URI
    const parts = crs.split('/');
    return parts[parts.length - 1] || crs;
}
