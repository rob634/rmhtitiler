/**
 * Catalog page JavaScript for geotiler.
 *
 * Depends on common.js: fetchJSON, debounce, escapeHtml, buildViewerUrl
 */

// ============================================================================
// Unified Catalog
// ============================================================================

/**
 * Load all collections (STAC + Vector) into the unified catalog grid.
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
                    extent: c.extent,
                    href: buildViewerUrl('raster', { collection: c.id }),
                    source: 'stac',
                }))
            );
        }
    }

    // Fetch Vector collections
    if (tipgEnabled) {
        const result = await fetchJSON('/vector/collections');
        if (result.ok && result.data.collections) {
            collections = collections.concat(
                result.data.collections
                    .filter(c => c.id !== 'public.spatial_ref_sys')
                    .map(c => ({
                        id: c.id,
                        title: c.title || c.id,
                        description: c.description || '',
                        type: 'vector',
                        extent: c.extent,
                        href: buildViewerUrl('vector', { collection: c.id }),
                        source: 'tipg',
                    }))
            );
        }
    }

    // Render collection cards
    renderCollections(collections);

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
            renderCollections(filtered);
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
    renderCollections(filtered);

    // Update active button styling
    document.querySelectorAll('[data-filter]').forEach(btn => {
        btn.classList.toggle('btn-primary', btn.dataset.filter === type);
        btn.classList.toggle('btn-secondary', btn.dataset.filter !== type);
    });
}


/**
 * Render collection cards into the catalog grid.
 * @param {Array} collections - Array of collection objects
 */
function renderCollections(collections) {
    const grid = document.getElementById('catalog-grid');
    const emptyEl = document.getElementById('catalog-empty');

    if (collections.length === 0) {
        grid.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    grid.innerHTML = collections.map(c => `
        <a href="${escapeHtml(c.href)}" class="card-link">
            <div class="card collection-card">
                <div class="card-header">
                    <h3>${escapeHtml(c.title)}</h3>
                    <span class="badge badge-${c.type === 'raster' ? 'info' : 'healthy'}">${escapeHtml(c.type)}</span>
                </div>
                <p>${escapeHtml(c.description).substring(0, 150)}</p>
            </div>
        </a>
    `).join('');
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
        extent: c.extent,
        links: c.links || [],
    }));

    renderStacCollections(collections, grid, emptyEl);

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
            renderStacCollections(filtered, grid, emptyEl);
        }, 300));
    }
}

/**
 * Render STAC collection cards with detailed metadata.
 * @param {Array} collections - STAC collection objects
 * @param {HTMLElement} grid - Grid container element
 * @param {HTMLElement} emptyEl - Empty state element
 */
function renderStacCollections(collections, grid, emptyEl) {
    if (collections.length === 0) {
        grid.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    grid.innerHTML = collections.map(c => {
        const viewerUrl = buildViewerUrl('raster', { collection: c.id });
        const temporal = formatExtent(c.extent);
        return `
            <div class="card collection-card" onclick="showCollectionDetail(${escapeHtml(JSON.stringify(JSON.stringify(c)))})">
                <div class="card-header">
                    <h3>${escapeHtml(c.title)}</h3>
                    <span class="badge badge-info">STAC</span>
                </div>
                <p>${escapeHtml(c.description).substring(0, 200)}</p>
                ${temporal ? `<p class="text-muted">${escapeHtml(temporal)}</p>` : ''}
                <div class="btn-group" style="margin-top: var(--space-sm);">
                    <a href="${escapeHtml(viewerUrl)}" class="btn btn-primary btn-sm" onclick="event.stopPropagation()">View on Map</a>
                    <a href="/stac/collections/${escapeHtml(c.id)}/items" class="btn btn-secondary btn-sm" target="_blank" onclick="event.stopPropagation()">Browse Items</a>
                </div>
            </div>
        `;
    }).join('');
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

    const result = await fetchJSON('/vector/collections');
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
            links: c.links || [],
        }));

    renderVectorCollections(collections, grid, emptyEl);

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
            renderVectorCollections(filtered, grid, emptyEl);
        }, 300));
    }
}

/**
 * Render Vector collection cards.
 * @param {Array} collections - Vector collection objects
 * @param {HTMLElement} grid - Grid container element
 * @param {HTMLElement} emptyEl - Empty state element
 */
function renderVectorCollections(collections, grid, emptyEl) {
    if (collections.length === 0) {
        grid.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    grid.innerHTML = collections.map(c => {
        const viewerUrl = buildViewerUrl('vector', { collection: c.id });
        return `
            <a href="${escapeHtml(viewerUrl)}" class="card-link">
                <div class="card collection-card">
                    <div class="card-header">
                        <h3>${escapeHtml(c.title)}</h3>
                        <span class="badge badge-healthy">vector</span>
                    </div>
                    <p>${escapeHtml(c.description).substring(0, 200)}</p>
                    <div class="btn-group" style="margin-top: var(--space-sm);">
                        <span class="btn btn-primary btn-sm">View on Map</span>
                        <a href="/vector/collections/${escapeHtml(c.id)}/items?limit=10" class="btn btn-secondary btn-sm" target="_blank" onclick="event.stopPropagation()">Browse Features</a>
                    </div>
                </div>
            </a>
        `;
    }).join('');
}


// ============================================================================
// Collection Detail
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
    metadata.innerHTML = `
        <table class="data-table">
            <tr><td><strong>ID</strong></td><td><code>${escapeHtml(c.id)}</code></td></tr>
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
// Extent Formatter
// ============================================================================

/**
 * Format a STAC extent object into a human-readable string.
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
