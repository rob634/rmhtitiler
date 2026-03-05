# Viewer Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 5 highest-priority bugs found by the COMPETE adversarial review of the map viewer subsystem.

**Architecture:** All fixes are client-side JavaScript changes (no backend modifications). Each task is independent and can be committed separately. The fixes address: vector event handler leak, duplicate API calls, raster statistics per-band, raster single-band mode, and the broken `/viewer/h3` route.

**Tech Stack:** Vanilla JavaScript, MapLibre GL JS 4.x, HTML templates (Jinja2), CSS

---

### Task 1: Fix vector click handler accumulation

**Files:**
- Modify: `geotiler/static/js/viewer-vector.js:4-5` (add state variable)
- Modify: `geotiler/static/js/viewer-vector.js:367-375` (cleanup in removeVectorLayer)
- Modify: `geotiler/static/js/viewer-vector.js:482-515` (store handler refs)

**Context:** `setupClickHandlers()` at line 482 registers 9 event listeners (click + mouseenter + mouseleave on 3 layers) every time a collection loads. These are never removed. After N loads, you get N duplicate popups per click.

**Step 1: Add handler tracking array**

At the top of the file (after line 5 `let popup = null;`), add:

```javascript
let activeClickHandlers = [];
```

**Step 2: Add cleanup to removeVectorLayer**

Replace the `removeVectorLayer` function (lines 367-375) with:

```javascript
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
```

**Step 3: Store handler references in setupClickHandlers**

Replace the `setupClickHandlers` function (lines 482-515) with:

```javascript
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
```

**Step 4: Manual test**

1. Open `/viewer/vector`
2. Select a collection, switch to another collection 5 times
3. Click a feature — should show exactly ONE popup, not multiple
4. Check browser console for errors

**Step 5: Commit**

```bash
git add geotiler/static/js/viewer-vector.js
git commit -m "fix: prevent vector click handler accumulation on collection reload"
```

---

### Task 2: Eliminate duplicate vector API call

**Files:**
- Modify: `geotiler/static/js/viewer-vector.js:90-121` (loadCollection)
- Modify: `geotiler/static/js/viewer-vector.js:126-147` (loadCollectionMetadata signature)
- Modify: `geotiler/static/js/viewer-vector.js:157-182` (loadSchema signature)

**Context:** `loadCollection()` calls `loadCollectionMetadata(id)` and `loadSchema(id)`, each of which independently fetches `/vector/collections/{id}/items?limit=1`. The same request is made twice.

**Step 1: Fetch once in loadCollection, pass to both**

Replace `loadCollection` (lines 90-121) with:

```javascript
async function loadCollection(collectionId) {
    if (!collectionId) return;

    currentCollectionId = collectionId;
    setQueryParam('collection', collectionId);
    showLoading(true);

    // Show collection info
    const infoPanel = document.getElementById('collection-info');
    infoPanel.classList.remove('hidden');

    // Fetch items once, share between metadata and schema
    const prefix = '/vector/collections/' + encodeURIComponent(collectionId);
    const itemsResult = await fetchJSON(prefix + '/items?limit=1');

    displayCollectionMetadata(itemsResult);
    displaySchema(itemsResult);

    // Set API links
    document.getElementById('link-tilejson').href = prefix + '/tiles/WebMercatorQuad/tilejson.json';
    document.getElementById('link-collection').href = prefix;
    document.getElementById('link-items').href = prefix + '/items?limit=10';

    // Add layer based on current render mode
    if (currentRenderMode === 'mvt') {
        addMvtLayer(collectionId);
    } else {
        addGeoJsonLayer(collectionId);
    }

    showLoading(false);
}
```

**Step 2: Refactor loadCollectionMetadata to accept data**

Replace `loadCollectionMetadata` (lines 126-147) with:

```javascript
function displayCollectionMetadata(result) {
    var metadataGrid = document.getElementById('metadata-grid');
    var featureCountEl = document.getElementById('feature-count');

    if (result.ok && result.data) {
        var features = result.data.features || [];
        var matched = result.data.numberMatched || result.data.numberReturned || features.length;
        featureCountEl.textContent = '(' + matched + ' features)';

        var extent = result.data.bbox;
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
```

**Step 3: Refactor loadSchema to accept data**

Replace `loadSchema` (lines 157-182) with:

```javascript
function displaySchema(result) {
    var container = document.getElementById('attribute-list');

    if (!result.ok || !result.data || !result.data.features || result.data.features.length === 0) {
        container.innerHTML = '<div style="font-size:0.8rem;color:var(--color-gray);font-style:italic;">No features to analyze</div>';
        return;
    }

    var properties = result.data.features[0].properties || {};
    var entries = Object.entries(properties);

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
```

**Step 4: Manual test**

1. Open browser DevTools Network tab
2. Open `/viewer/vector`, select a collection
3. Verify only ONE `/items?limit=1` request appears (not two)
4. Verify metadata and attribute schema both render correctly

**Step 5: Commit**

```bash
git add geotiler/static/js/viewer-vector.js
git commit -m "fix: eliminate duplicate /items API call in vector viewer"
```

---

### Task 3: Per-band statistics for raster stretch

**Files:**
- Modify: `geotiler/static/js/viewer-raster.js:7` (change bandStats type)
- Modify: `geotiler/static/js/viewer-raster.js:263-277` (fetchStatistics)
- Modify: `geotiler/static/js/viewer-raster.js:231-253` (getRescaleValues)

**Context:** `fetchStatistics()` stores only the first band's stats. All stretch modes use that single band's percentiles regardless of which band the user selected. TiTiler returns stats keyed by band name like `{"b1": {...}, "b2": {...}}`.

**Step 1: Store all band stats**

Change line 7 from:
```javascript
let bandStats = null;
```
to:
```javascript
let allBandStats = null;
```

**Step 2: Rewrite fetchStatistics to store all bands**

Replace `fetchStatistics` (lines 263-277) with:

```javascript
async function fetchStatistics(url) {
    const result = await fetchJSON('/cog/statistics?url=' + encodeURIComponent(url));
    if (!result.ok || !result.data) {
        allBandStats = null;
        return;
    }

    allBandStats = result.data;
    displayStatistics(result.data);
}
```

**Step 3: Rewrite getRescaleValues to use selected band**

Replace `getRescaleValues` (lines 231-253) with:

```javascript
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
```

**Step 4: Manual test**

1. Load a multi-band COG (e.g., Sentinel-2 with bands that have different ranges)
2. Select P2-98 stretch, verify tiles render with proper contrast
3. Switch R band to band 4 (NIR) — stretch values should update to band 4's percentiles
4. Check that statistics still display correctly in the sidebar

**Step 5: Commit**

```bash
git add geotiler/static/js/viewer-raster.js
git commit -m "fix: use per-band statistics for raster stretch calculations"
```

---

### Task 4: Add single-band mode to raster viewer

**Files:**
- Modify: `geotiler/static/js/viewer-raster.js:139-185` (buildBandControls — add None option)
- Modify: `geotiler/static/js/viewer-raster.js:367-392` (buildTileUrl — filter empty bands)
- Modify: `geotiler/static/js/viewer-raster.js:173-184` (presets — add Gray)

**Context:** The G and B band selectors always have a band selected, forcing 3-band tile requests. Users need a "None" option to view a single band with a colormap (e.g., NDVI with viridis). The rmhgeoapi reference implementation has this.

**Step 1: Add "None" option to G and B selectors**

Replace `buildBandControls` (lines 139-185) with:

```javascript
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
```

**Step 2: Filter empty bands in buildTileUrl**

Replace lines 382-389 in `buildTileUrl` with:

```javascript
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
```

**Step 3: Update setBandPreset to handle empty values**

Replace `setBandPreset` (lines 190-198) with:

```javascript
function setBandPreset(r, g, b) {
    const rSel = document.getElementById('band-r');
    const gSel = document.getElementById('band-g');
    const bSel = document.getElementById('band-b');
    if (rSel) rSel.value = r;
    if (gSel) gSel.value = g;
    if (bSel) bSel.value = b;
    updateTiles();
}
```

**Step 4: Manual test**

1. Load a multi-band COG
2. Click "Gray" preset — G and B should show "-- None --", only 1 bidx sent
3. Select a colormap (e.g., Viridis) — should render the single band with that colormap
4. Click "RGB" preset — all three bands selected, colormap should be ignored by TiTiler
5. Click "NIR" preset — bands 4,3,2 selected

**Step 5: Commit**

```bash
git add geotiler/static/js/viewer-raster.js
git commit -m "feat: add single-band mode with None option for G/B band selectors"
```

---

### Task 5: Fix /viewer/h3 route (redirect to working /h3)

**Files:**
- Modify: `geotiler/routers/viewer.py:33-36` (redirect /viewer/h3 to /h3)

**Context:** The `/viewer/h3` route serves `pages/viewer/h3.html` which has wrong parameter values AND reads `d.value` from a response that doesn't have that property. The working H3 explorer at `/h3` uses `pages/h3/region.html` with correct codes. Rather than rewriting the broken viewer, redirect to the working one.

**Step 1: Change route to redirect**

Replace lines 33-36 in `viewer.py`:

```python
@router.get("/h3", include_in_schema=False)
async def h3_viewer(request: Request):
    """Redirect to the canonical H3 explorer at /h3."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/h3", status_code=302)
```

**Step 2: Manual test**

1. Navigate to `/viewer/h3` — should redirect to `/h3`
2. Verify the H3 explorer at `/h3` loads and queries work
3. Verify other viewer routes still work: `/viewer/raster`, `/viewer/vector`, `/viewer/zarr`

**Step 3: Commit**

```bash
git add geotiler/routers/viewer.py
git commit -m "fix: redirect /viewer/h3 to canonical /h3 explorer (broken params)"
```

---

### Task 6: Quick wins (cosmetic fixes from review)

**Files:**
- Modify: `geotiler/static/css/styles.css:1921` (add toast-warning)
- Modify: `geotiler/static/js/viewer-h3.js:137` (rename duplicate Query label)
- Modify: `geotiler/templates/pages/viewer/zarr.html:69` (fix colormap default)
- Modify: `geotiler/static/js/viewer-raster.js:119-125` (add NoData to metadata)

**Step 1: Add toast-warning CSS**

After line 1921 in styles.css (after `.toast-info`), add:

```css
.toast-warning { border-left-color: var(--color-warning); }
```

**Step 2: Fix duplicate Query label in H3**

In `viewer-h3.js` line 137, change:

```javascript
'<div class="metadata-item"><div class="metadata-label">Query</div><div class="metadata-value mono">' + crop + ' / ' + tech + '</div></div>';
```

to:

```javascript
'<div class="metadata-item"><div class="metadata-label">Selection</div><div class="metadata-value mono">' + crop + ' / ' + tech + '</div></div>';
```

**Step 3: Fix zarr colormap default**

In `zarr.html` line 69, remove the `selected` attribute from viridis:

Change: `<option value="viridis" selected>Viridis</option>`
To: `<option value="viridis">Viridis</option>`

**Step 4: Add NoData to raster metadata**

In `viewer-raster.js`, in the `displayMetadata` function, before the closing of the metadata innerHTML (around line 125), add a conditional NoData row:

After the Bounds row and before the closing `';`, add:

```javascript
        (info.nodata !== null && info.nodata !== undefined ?
            '<div class="metadata-item"><div class="metadata-label">NoData</div><div class="metadata-value mono">' + escapeHtml(String(info.nodata)) + '</div></div>' : '')
```

**Step 5: Manual test**

1. Trigger a warning notification — should have orange/amber left border
2. Open `/viewer/zarr` — colormap should default to "Default" (empty), not Viridis
3. Load a COG with nodata — metadata should show the NoData value
4. H3 stats should show "Selection" label, not duplicate "Query"

**Step 6: Commit**

```bash
git add geotiler/static/css/styles.css geotiler/static/js/viewer-h3.js geotiler/templates/pages/viewer/zarr.html geotiler/static/js/viewer-raster.js
git commit -m "fix: cosmetic viewer fixes (toast-warning, h3 label, zarr default, nodata)"
```
