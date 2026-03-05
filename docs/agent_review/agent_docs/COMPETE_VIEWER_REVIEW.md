# COMPETE Agent Review: Map Viewer Subsystem

**Date:** 2026-03-05
**Pipeline:** Adversarial Review (COMPETE_AGENT)
**Scope:** 4 map viewers (raster, vector, zarr, H3) — templates, JS, CSS
**Split:** B — Internal Logic (Alpha) vs External Interfaces (Beta)

---

## EXECUTIVE SUMMARY

The map viewer subsystem has four viewers served from two distinct codebases: the `/viewer/*` routes (raster, vector, zarr, H3) built on a shared design system, and the `/h3` route using a self-contained standalone template. The primary H3 explorer (`/h3`) is well-built with correct backend integration. The secondary H3 viewer at `/viewer/h3` is completely non-functional due to parameter and schema mismatches — but this is the less-used path. The vector viewer has a real event handler leak that degrades with use. The raster viewer has a single-band rendering limitation and applies first-band statistics globally. Overall: the raster and vector viewers are functional with moderate bugs; the zarr viewer works with a minor cosmetic issue; the `/viewer/h3` route is broken but the primary `/h3` route is solid.

---

## TOP 5 FIXES

### 1. Vector click handler accumulation (memory leak + duplicate popups)

- **WHAT:** `setupClickHandlers()` stacks 9 new MapLibre event listeners (click, mouseenter, mouseleave x 3 layers) on every `loadCollection()` / `setRenderMode()` call without removing prior listeners.
- **WHY:** After switching collections 5 times, there are 45 active click handlers. This causes duplicate popups, performance degradation, and memory leaks in long-running sessions.
- **WHERE:** `geotiler/static/js/viewer-vector.js`, function `setupClickHandlers()`, lines 482-514. Called from `addMvtLayer()` line 263 and `addGeoJsonLayer()` line 352.
- **HOW:** Add a cleanup step at the start of `setupClickHandlers()` that calls `vectorMap.off('click', layerId, handler)` for each layer. Store handler references in a module-level array (e.g., `let activeHandlers = []`), iterate and `.off()` before re-attaching. Alternatively, move cleanup into `removeVectorLayer()` at line 367.
- **EFFORT:** Small (< 1 hour)
- **RISK OF FIX:** Low

### 2. Duplicate vector API call per collection load

- **WHAT:** `loadCollectionMetadata()` and `loadSchema()` both independently fetch `/vector/collections/{id}/items?limit=1`, making two identical network requests on every collection load.
- **WHY:** Doubles API load on the TiPG backend for every collection selection. On slow connections, this also doubles perceived latency.
- **WHERE:** `geotiler/static/js/viewer-vector.js`, `loadCollectionMetadata()` line 130 and `loadSchema()` line 160. Both called from `loadCollection()` lines 102 and 111.
- **HOW:** Fetch once in `loadCollection()`, pass the result to both functions as a parameter.
- **EFFORT:** Small (< 1 hour)
- **RISK OF FIX:** Low

### 3. Raster statistics use only first band for all stretch modes

- **WHAT:** `fetchStatistics()` stores only the first band's stats in `bandStats`. Percentile-based stretches (p2-98, p5-95, minmax) apply these values uniformly to all displayed bands.
- **WHY:** For multi-band COGs where bands have different value ranges (e.g., Landsat surface reflectance vs thermal), the stretch will be incorrect for all bands except the first.
- **WHERE:** `geotiler/static/js/viewer-raster.js`, function `fetchStatistics()` lines 270-276 (stores `data[firstKey]` only). Consumed by `getRescaleValues()` lines 231-253.
- **HOW:** Store per-band stats as a dictionary keyed by band name. In `getRescaleValues()`, compute per-band rescale ranges and emit multiple `&rescale=` parameters (one per selected band index). TiTiler supports repeated `rescale` params.
- **EFFORT:** Medium (1-4 hours)
- **RISK OF FIX:** Medium — requires understanding TiTiler's multi-band rescale parameter format.

### 4. Missing single-band rendering mode in raster viewer

- **WHAT:** Band selectors always produce three `&bidx=` parameters. There is no option to select a single band for colormap visualization.
- **WHY:** Users cannot apply a colormap to a single band of a multi-band COG. Sending `colormap_name` with 3 bidx params will either error or produce unexpected results.
- **WHERE:** `geotiler/static/js/viewer-raster.js`, function `buildBandControls()` lines 150-184 (no "None" option for G/B), and `buildTileUrl()` lines 382-389 (always sends 3 bidx).
- **HOW:** Add a "None" option (value="") to the G and B selectors. In `buildTileUrl()`, filter out empty bidx values. Show/hide colormap selector based on whether single-band mode is active.
- **EFFORT:** Medium (1-4 hours)
- **RISK OF FIX:** Low

### 5. `/viewer/h3` route is non-functional (parameter + schema mismatch)

- **WHAT:** The `/viewer/h3` page sends human-readable values ("wheat", "irrigated", "baseline") to `/h3/query`, but the backend expects coded values ("whea", "i", "spei12_*"). Additionally, `viewer-h3.js` reads `d.value` from response objects that have `{h3_index, production, harv_area_ha, spei}` — no `value` property exists.
- **WHY:** Every query from `/viewer/h3` returns HTTP 400. Even if parameters were fixed, all statistics and hex coloring produce NaN.
- **WHERE:** Parameter mismatch: `geotiler/templates/pages/viewer/h3.html` lines 26-49. Schema mismatch: `geotiler/static/js/viewer-h3.js` lines 126, 163, 172, 186, 239. Backend contract: `geotiler/services/duckdb.py` lines 88-107 and 281-284.
- **HOW:** Either (a) delete `/viewer/h3` route and redirect to `/h3` (recommended), or (b) rewrite dropdown values and JS to match backend contract.
- **EFFORT:** Small (option a) / Large (option b)
- **RISK OF FIX:** Low

---

## ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|--------------|
| fetchJSON sets Content-Type: application/json on GETs (common.js:374) | All fetches are same-origin, no CORS preflight | Viewers need cross-origin API calls |
| Custom rescale no min < max validation (viewer-raster.js:232, viewer-zarr.js:206) | TiTiler handles inverted ranges gracefully | Users report confusion |
| DuckDB SQL path interpolation (duckdb.py:183) | Path from server config, never user input | Path config exposed to user input |
| Zarr colormap conflicting defaults (zarr.html:67-69) | Both produce valid tile requests | Users report inconsistent behavior |
| No concurrent load guard | Last call wins due to layer cleanup | Operations become expensive |
| Mobile layout overflow (styles.css:1285-1288) | Desktop-oriented analysis tools | Mobile becomes a requirement |

---

## ARCHITECTURE WINS

1. **H3 region.html is production-quality.** The standalone `pages/h3/region.html` correctly maps crop codes, tech codes, and SPEI scenarios. Handles bivariate coloring, country filtering, TopoJSON boundaries. This is the model implementation.

2. **DuckDB frozen-set input validation** (`duckdb.py` lines 88-107). Using `frozenset` for allowed parameter values prevents injection without parameterized queries. Clear error messages from `validate_h3_params()`.

3. **Non-fatal service initialization** (`duckdb.py` lines 209-244). DuckDB failure is captured in `DuckDBStartupState` and reported via `/health` without crashing the app. The `_is_duckdb_ready()` pattern should be applied to future optional services.

4. **Consistent viewer page structure.** All four templates share `viewer-layout`, `sidebar-section`, `metadata-grid`, `map-overlay` patterns. The `common.js` `fetchJSON()` wrapper with timeout, abort controller, and unified error shape eliminates boilerplate.

5. **Vector removeVectorLayer() cleanup** (`viewer-vector.js` lines 367-375). Correctly removes all three layer types and source before re-adding, preventing "source already exists" errors. Just needs extending to also clean up event handlers (Fix #1).

---

## FULL SEVERITY RANKING

| # | Severity | Finding | Confidence |
|---|----------|---------|------------|
| 1 | P0-CRITICAL | H3 viewer/h3 parameter mismatch — every query fails | CONFIRMED |
| 2 | P0-CRITICAL | H3 viewer/h3 d.value property doesn't exist in response | CONFIRMED |
| 3 | P1-HIGH | Vector click handler accumulation / memory leak | CONFIRMED |
| 4 | P1-HIGH | Missing single-band mode (no None for G/B) | CONFIRMED |
| 5 | P1-HIGH | Statistics use only first band for all stretches | CONFIRMED |
| 6 | P1-HIGH | Missing mosaic/search mode | SPECULATIVE |
| 7 | P2-MEDIUM | Duplicate vector API call | CONFIRMED |
| 8 | P2-MEDIUM | fetchJSON Content-Type on GETs | CONFIRMED |
| 9 | P2-MEDIUM | Custom rescale no min<max validation | CONFIRMED |
| 10 | P2-MEDIUM | Zarr colormap conflicting defaults | CONFIRMED |
| 11 | P2-MEDIUM | Duplicate "Query" label in H3 stats | CONFIRMED |
| 12 | P2-MEDIUM | Missing toast-warning CSS class | CONFIRMED |
| 13 | P2-MEDIUM | No concurrent load guard | PROBABLE |
| 14 | P3-LOW | Missing NoData in raster metadata | CONFIRMED |
| 15 | P3-LOW | Missing Zoom to Extent button | SPECULATIVE |
| 16 | P3-LOW | Band descriptions not in selectors | CONFIRMED |
| 17 | P3-LOW | Band presets hidden for 2-band datasets | CONFIRMED |
| 18 | P3-LOW | Mobile layout overflow | CONFIRMED |
| 19 | P3-LOW | DuckDB SQL path interpolation | CONFIRMED |
