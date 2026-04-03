# Zarr Viewer Fixes — Implementation Guide

**Date**: 02 APR 2026
**Priority**: HIGH — tiles render blank without these fixes
**Context**: The ETL pipeline (rmhgeoapi) now produces flat Zarr v3 stores with optimized chunking. The titiler-xarray backend serves tiles correctly, but the zarr viewer UI doesn't auto-configure rescale and colormap, resulting in blank tiles on initial load.

**Confirmed working tile URL** (manual):
```
/xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=abfs://silver-zarr/zarr/spei12-test/ssp370-2040-2059.zarr&variable=climatology-spei12-annual-mean&decode_times=false&rescale=-3,3&colormap_name=rdylbu
```

**Test dataset**: `abfs://silver-zarr/zarr/spei12-test/ssp370-2040-2059.zarr`
- Variable: `climatology-spei12-annual-mean` (SPEI drought index, range approx -3 to +3)
- CRS: EPSG:4326, global extent, Zarr v3 format

---

## Bug 1: Initial load shows blank tiles (CRITICAL)

**File**: `geotiler/static/js/viewer-zarr.js`

**Problem**: When a dataset loads, `loadZarr()` calls `/xarray/info` and then `updateZarrTiles()`. The tile URL is built without `rescale` because `zarr-min` and `zarr-max` inputs are empty. Float32 data (e.g. -3 to +3) maps to near-invisible grayscale values.

**Root cause**: The `loadZarr()` function never auto-populates the rescale fields from the `/xarray/info` response. The info response contains band statistics with min/max values that should drive the rescale.

**Fix**: After `populateVariables(zarrInfo)`, call a new function that:

1. Reads the selected variable's statistics from the info response
2. The `/xarray/info?url=...&variable=X` response includes `band_metadata` like:
   ```json
   "band_metadata": [["b1", {"standard_name": "...", "long_name": "..."}]]
   ```
   However, this may not include min/max stats. If not, you have two options:

   **(A)** Call the `/xarray/bbox/{minx},{miny},{maxx},{maxy}.npy` or `/xarray/statistics` endpoint to compute stats on the fly

   **(B)** Use a heuristic: read the `dtype` from info response. For float32 data, default to a symmetric range around 0 (e.g. `-10,10`) as a starting point, then let the user refine via the existing min/max inputs. For uint8/uint16, use `0,255` / `0,65535`.

3. Set `zarr-min` and `zarr-max` input values
4. Set a sensible default colormap (e.g. `viridis` for generic data)
5. Then call `updateZarrTiles()` which already reads from these inputs

**Suggested flow in `loadZarr()`** (after line 88):
```javascript
// Auto-populate rescale from statistics
autoConfigureRescale(zarrInfo);

// Auto-load first variable
updateZarrTiles();
```

**Note**: The rescale should update when the user switches variables (each variable has a different range). Hook into the variable `<select>` `onchange` to re-fetch info for the new variable and update rescale.

---

## Bug 2: Colormap dropdown — add a sensible default selection

**File**: `geotiler/templates/pages/viewer/zarr.html`

**Problem**: The colormap dropdown defaults to "Default" (empty value), which means no `colormap_name` param is sent. Without a colormap, tiles render in grayscale.

**Fix**: Either:
- **(A)** Change the default `<option>` to a colormap like `viridis` (good general-purpose diverging colormap)
- **(B)** Add logic to auto-select a colormap based on the variable name or data characteristics. For example:
  - Temperature data → `magma` or `inferno`
  - Precipitation/drought → `rdylbu` (red-yellow-blue diverging)
  - Generic → `viridis`

**Suggestion**: Add a colormap palette picker/preview so the user can see what each colormap looks like before selecting. This is a nice-to-have UX enhancement — implementation left to your judgment. Consider a visual swatch grid or thumbnails next to each option in the dropdown.

---

## Bug 3: `/xarray/info` called without `variable` param

**File**: `geotiler/static/js/viewer-zarr.js`, line 75

**Problem**: `loadZarr()` calls `/xarray/info?url=...` without a `&variable=` parameter. The titiler-xarray `/xarray/info` endpoint requires a variable to return band-level metadata. Without it, the response may be incomplete or error.

**Fix**: Change the load sequence to:
1. First call `/xarray/dataset/keys?url=...` to get the variable list
2. Select the first variable (or from query param)
3. Then call `/xarray/info?url=...&variable=SELECTED` to get full metadata including band stats

**Current code** (line 75):
```javascript
const result = await fetchJSON('/xarray/info?url=' + encodeURIComponent(url));
```

**Proposed**:
```javascript
// Step 1: Get variable list
const keysResult = await fetchJSON('/xarray/dataset/keys?url=' + encodeURIComponent(url));
if (!keysResult.ok || !keysResult.data.length) {
    showNotification('No variables found in dataset', 'error');
    showLoading(false);
    return;
}

// Step 2: Select variable (from query param or first available)
const varParam = getQueryParam('variable');
const selectedVar = (varParam && keysResult.data.includes(varParam))
    ? varParam : keysResult.data[0];

// Step 3: Get info WITH variable
const result = await fetchJSON('/xarray/info?url=' + encodeURIComponent(url)
    + '&variable=' + encodeURIComponent(selectedVar));
```

Then update `populateVariables()` to use `keysResult.data` instead of `info.variables`.

---

## Bug 4: Variable switch doesn't update rescale

**File**: `geotiler/static/js/viewer-zarr.js`

**Problem**: When the user selects a different variable from the dropdown, `updateZarrTiles()` is called (line 194), but the rescale min/max fields still contain the previous variable's values. Different variables have different data ranges.

**Fix**: On variable change, re-fetch `/xarray/info?variable=NEW_VAR` and update the rescale fields before calling `updateZarrTiles()`. Add an async handler:

```javascript
async function onVariableChange() {
    const variable = document.getElementById('variable-select').value;
    if (!variable || !currentZarrUrl) return;

    // Fetch info for this variable to get statistics
    const result = await fetchJSON('/xarray/info?url=' + encodeURIComponent(currentZarrUrl)
        + '&variable=' + encodeURIComponent(variable));

    if (result.ok) {
        autoConfigureRescale(result.data);
    }

    updateZarrTiles();
}
```

Update the variable `<select>` in `zarr.html` to call `onVariableChange()` instead of `updateZarrTiles()`.

---

## Summary of Changes

| # | File | What | Priority |
|---|------|------|----------|
| 1 | `viewer-zarr.js` | Auto-populate rescale from statistics on load | CRITICAL |
| 2 | `zarr.html` | Default colormap selection (or auto-select) | HIGH |
| 3 | `viewer-zarr.js` | Load sequence: dataset/keys first, then info with variable | HIGH |
| 4 | `viewer-zarr.js` | Re-fetch info on variable switch, update rescale | MEDIUM |

**Testing**: Load `https://rmhtitiler-{host}/preview/zarr?url=abfs://silver-zarr/zarr/spei12-test/ssp370-2040-2059.zarr` — tiles should render with color on first load without manual input.

---

## Endpoint Reference (titiler-xarray)

| Endpoint | Purpose | Notes |
|----------|---------|-------|
| `GET /xarray/dataset/keys?url=` | List variable names | Returns `["var1", "var2"]` |
| `GET /xarray/info?url=&variable=` | Variable metadata (bounds, CRS, dtype, bands) | Requires `variable` param |
| `GET /xarray/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url=&variable=&rescale=&colormap_name=` | Tile rendering | `rescale` and `colormap_name` required for visible output |
| `GET /xarray/WebMercatorQuad/tilejson.json?url=&variable=` | TileJSON spec | Used by MapLibre for auto-bounds |
| `GET /xarray/WebMercatorQuad/map.html?url=&variable=&rescale=&colormap_name=` | Native titiler map viewer | Works with all params in URL |
| `POST /xarray/statistics?url=&variable=` | Compute statistics | Can be used for auto-rescale if info lacks stats |
