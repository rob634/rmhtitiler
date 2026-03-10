# COMPETE Viewer Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 5 issues from COMPETE_VIEWER_REVIEW_2.md — race condition guards, XSS escaping, null-safety, and dead code removal.

**Architecture:** All changes are frontend JavaScript. No Python, no API changes. Each fix is independent and can be committed separately. No JS test framework exists for these files — verification is manual browser smoke test after each task.

**Tech Stack:** Vanilla JavaScript, MapLibre GL JS 4.x, deck.gl 9.x

---

### Task 1: Escape `info.width` / `info.height` in raster viewer innerHTML

**Files:**
- Modify: `geotiler/static/js/viewer-raster.js:135-136`

**Step 1: Apply the fix**

At line 135-136 of `viewer-raster.js`, `info.width` and `info.height` are injected into innerHTML without `escapeHtml()`. Every other field in this block already uses `escapeHtml()`.

Change line 135 from:
```javascript
        (info.width ? '<div class="metadata-item"><div class="metadata-label">Width</div><div class="metadata-value">' + info.width + ' px</div></div>' : '') +
```
to:
```javascript
        (info.width ? '<div class="metadata-item"><div class="metadata-label">Width</div><div class="metadata-value">' + escapeHtml(String(info.width)) + ' px</div></div>' : '') +
```

Change line 136 from:
```javascript
        (info.height ? '<div class="metadata-item"><div class="metadata-label">Height</div><div class="metadata-value">' + info.height + ' px</div></div>' : '') +
```
to:
```javascript
        (info.height ? '<div class="metadata-item"><div class="metadata-label">Height</div><div class="metadata-value">' + escapeHtml(String(info.height)) + ' px</div></div>' : '') +
```

**Step 2: Verify**

Open `/viewer/raster` in browser, load a COG. Confirm Width and Height still display correctly in the metadata panel.

**Step 3: Commit**

```bash
git add geotiler/static/js/viewer-raster.js
git commit -m "fix: escape info.width/height in raster viewer innerHTML (XSS)"
```

---

### Task 2: Guard null bbox and escape `matched` in vector viewer

**Files:**
- Modify: `geotiler/static/js/viewer-vector.js:138,141`

**Step 1: Escape `matched` at line 138**

`matched` is from API response `numberMatched` — should be escaped for defense-in-depth.

Change line 138 from:
```javascript
            '<div class="metadata-item"><div class="metadata-label">Features</div><div class="metadata-value">' + matched + '</div></div>' +
```
to:
```javascript
            '<div class="metadata-item"><div class="metadata-label">Features</div><div class="metadata-value">' + escapeHtml(String(matched)) + '</div></div>' +
```

**Step 2: Guard null bbox values at line 141**

`extent.map(function(v) { return v.toFixed(4); })` throws if any bbox coordinate is null.

Change line 141 from:
```javascript
                extent.map(function(v) { return v.toFixed(4); }).join(', ') + '</div></div>' : '');
```
to:
```javascript
                escapeHtml(extent.map(function(v) { return v != null ? v.toFixed(4) : '?'; }).join(', ')) + '</div></div>' : '');
```

**Step 3: Verify**

Open `/viewer/vector`, select a collection. Confirm feature count and extent display correctly in the metadata panel. The extent values should show 4 decimal places.

**Step 4: Commit**

```bash
git add geotiler/static/js/viewer-vector.js
git commit -m "fix: escape matched + guard null bbox in vector viewer (XSS/null-safety)"
```

---

### Task 3: Escape `crop` / `tech` in H3 viewer innerHTML

**Files:**
- Modify: `geotiler/static/js/viewer-h3.js:137`

**Step 1: Apply the fix**

At line 137, `crop` and `tech` (from HTML select dropdowns) are inserted into innerHTML unescaped.

Change line 137 from:
```javascript
            '<div class="metadata-item"><div class="metadata-label">Selection</div><div class="metadata-value mono">' + crop + ' / ' + tech + '</div></div>';
```
to:
```javascript
            '<div class="metadata-item"><div class="metadata-label">Selection</div><div class="metadata-value mono">' + escapeHtml(crop) + ' / ' + escapeHtml(tech) + '</div></div>';
```

**Step 2: Verify**

Open `/viewer/h3`, run a query. Confirm the "Selection" metadata row shows the crop/tech values correctly.

**Step 3: Commit**

```bash
git add geotiler/static/js/viewer-h3.js
git commit -m "fix: escape crop/tech in H3 viewer innerHTML (XSS)"
```

---

### Task 4: Add race condition guard to all viewers

**Files:**
- Modify: `geotiler/static/js/viewer-raster.js:8,76-110`
- Modify: `geotiler/static/js/viewer-vector.js:8,91-122`
- Modify: `geotiler/static/js/viewer-zarr.js:8,61-90`
- Modify: `geotiler/static/js/viewer-h3.js:8,96-146`

The pattern is the same for all 4 files: add a module-level generation counter, increment at function entry, bail after each `await` if a newer invocation has started.

**Step 1: Add generation counter to viewer-raster.js**

After line 12 (`let allBandStats = null;`), add:
```javascript
let rasterLoadGen = 0;
```

Then modify `loadRaster()` (line 76) — add generation check after each `await`:
```javascript
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
```

**Step 2: Add generation counter to viewer-vector.js**

After line 11 (`let activeClickHandlers = [];`), add:
```javascript
let vectorLoadGen = 0;
```

Then modify `loadCollection()` (line 91):
```javascript
async function loadCollection(collectionId) {
    if (!collectionId) return;

    currentCollectionId = collectionId;
    setQueryParam('collection', collectionId);
    showLoading(true);

    const myGen = ++vectorLoadGen;

    // Show collection info
    const infoPanel = document.getElementById('collection-info');
    infoPanel.classList.remove('hidden');

    // Fetch items once, share between metadata and schema
    const prefix = '/vector/collections/' + encodeURIComponent(collectionId);
    const itemsResult = await fetchJSON(prefix + '/items?limit=1');
    if (myGen !== vectorLoadGen) return;

    displayCollectionMetadata(itemsResult);
    displaySchema(itemsResult);

    // Set API links
    document.getElementById('link-tilejson').href = prefix + '/tiles/WebMercatorQuad/tilejson.json';
    document.getElementById('link-collection').href = prefix;
    document.getElementById('link-items').href = prefix + '/items?limit=10';

    // Add layer based on current render mode
    if (currentRenderMode === 'mvt') {
        await addMvtLayer(collectionId);
    } else {
        await addGeoJsonLayer(collectionId);
    }
    if (myGen !== vectorLoadGen) return;

    showLoading(false);
}
```

**Step 3: Add generation counter to viewer-zarr.js**

After line 9 (`let zarrInfo = null;`), add:
```javascript
let zarrLoadGen = 0;
```

Then modify `loadZarr()` (line 61):
```javascript
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
```

**Step 4: Add generation counter to viewer-h3.js**

After line 11 (`let currentPalette = 'emergency_red';`), add:
```javascript
let h3LoadGen = 0;
```

Then modify `queryH3()` (line 96):
```javascript
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

    // ... rest of function unchanged ...
}
```

**Step 5: Verify**

Open each viewer (`/viewer/raster`, `/viewer/vector`, `/viewer/zarr`, `/viewer/h3`). Load a dataset. Rapidly click "Load" twice — only the second result should render. No duplicate layers.

**Step 6: Commit**

```bash
git add geotiler/static/js/viewer-raster.js geotiler/static/js/viewer-vector.js geotiler/static/js/viewer-zarr.js geotiler/static/js/viewer-h3.js
git commit -m "fix: add load-generation guards to prevent race conditions in all viewers"
```

---

### Task 5: Remove dead functions from common.js

**Files:**
- Modify: `geotiler/static/js/common.js`

**Context:** 16 functions in common.js have zero external callers. `setUrl` is used in HTML templates. `escapeHtml`, `debounce`, `initTabs`, `fetchJSON`, `getQueryParam`, `setQueryParam`, `buildViewerUrl`, `showNotification` are all used by viewer JS files. Everything else is dead.

**Dead functions to remove (with line ranges):**

| Function | Lines | Why dead |
|----------|-------|----------|
| `getInputValue` | 27-30 | No external callers |
| `getCogInfo` | 42-65 | No external callers |
| `getXarrayInfo` | 72-95 | No external callers |
| `viewTiles` | 102-108 | No external callers |
| `displayJson` | 120-125 | Only called by dead functions |
| `showError` | 132-137 | Only called by dead functions |
| `showSuccess` | 144-149 | No external callers |
| `formatJson` | 156-159 | Only called by dead functions |
| `copyToClipboard` | 182-208 | No external callers |
| `copyElementContent` | 215-220 | No external callers |
| `throttle` | 251-260 | No external callers |
| `formatBytes` | 268-276 | No external callers |
| `formatDate` | 283-289 | No external callers |
| `serializeForm` | 301-308 | No external callers |
| `populateForm` | 315-322 | No external callers |
| `formatLatLng` | 450-452 | No external callers |

**Step 1: Delete dead functions**

Remove all 16 functions listed above plus their JSDoc comments and section headers that become empty. Also remove section headers that become orphaned:
- "URL Input Helpers" section header (lines 5-7) — `setUrl` remains but rename section
- "API Helpers" section header (lines 33-35) — all functions deleted, remove header
- "Display Helpers" section header (lines 111-113) — all functions deleted, remove header
- "Clipboard Helpers" section header (lines 173-175) — all functions deleted, remove header
- "Form Helpers" section header (lines 292-294) — all functions deleted, remove header
- "Formatters" section header (lines 440-442) — `formatLatLng` deleted, remove header

**Step 2: Verify the kept functions are still present**

After editing, the file should contain exactly these functions:
1. `setUrl` (line ~14)
2. `escapeHtml` (line ~166)
3. `debounce` (line ~233)
4. `initTabs` (line ~333)
5. `fetchJSON` (line ~365)
6. `getQueryParam` (line ~403)
7. `setQueryParam` (line ~412)
8. `buildViewerUrl` (line ~433)
9. `showNotification` (line ~465)
10. DOMContentLoaded handler (line ~486)

**Step 3: Verify in browser**

Open each page that uses common.js:
- `/viewer/raster` — load a COG, check notifications work
- `/viewer/vector` — select a collection
- `/catalog` — search, filter
- `/cog` and `/xarray` landing pages — click sample cards (tests `setUrl`)

Check browser console for "X is not defined" errors.

**Step 4: Commit**

```bash
git add geotiler/static/js/common.js
git commit -m "refactor: remove 16 dead functions (~190 lines) from common.js"
```

---

### Task 6: Fix fetchJSON Content-Type on GETs (bonus)

**Files:**
- Modify: `geotiler/static/js/common.js:371-376`

**Step 1: Move Content-Type into body block**

Change lines 371-376 from:
```javascript
        const fetchOptions = {
            method,
            signal: controller.signal,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) fetchOptions.body = JSON.stringify(body);
```
to:
```javascript
        const fetchOptions = {
            method,
            signal: controller.signal,
        };
        if (body) {
            fetchOptions.headers = { 'Content-Type': 'application/json' };
            fetchOptions.body = JSON.stringify(body);
        }
```

**Step 2: Verify**

Open any viewer page, load data. Check browser Network tab — GET requests should no longer have `Content-Type` header.

**Step 3: Commit**

```bash
git add geotiler/static/js/common.js
git commit -m "fix: only set Content-Type header on fetchJSON when body is present"
```
