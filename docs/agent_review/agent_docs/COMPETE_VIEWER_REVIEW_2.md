# COMPETE Agent Review: Raster & Vector Viewer Subsystem (Run 2)

**Date:** 2026-03-10
**Pipeline:** Adversarial Review (COMPETE_AGENT)
**Scope:** Raster viewer, Vector viewer, shared common.js, H3 viewer innerHTML
**Split:** A — Design/Architecture (Alpha) vs Runtime/Correctness (Beta)
**Prior Review:** COMPETE_VIEWER_REVIEW.md (2026-03-05) — top 5 fixes implemented

---

## EXECUTIVE SUMMARY

The raster and vector viewers are functional and well-structured. The previous COMPETE run's top 5 fixes (click handler leak, duplicate API call, per-band stats, single-band mode, H3 parameter mismatch) have been addressed. This second pass focuses on residual issues: XSS defense gaps where innerHTML is used without escapeHtml(), a race condition pattern shared across all viewers, null-safety gaps in metadata rendering, and ~130 lines of dead code in common.js. All findings are SMALL or MEDIUM effort. No P0-CRITICAL issues remain.

---

## TOP 5 FIXES

### 1. Race condition guard — load-generation counter in viewers

- **WHAT:** `loadRaster()` (viewer-raster.js:76) and `loadCollection()` (viewer-vector.js) have no cancellation mechanism. If a user triggers a second load while the first is still fetching, both async chains run concurrently — the first may overwrite the second's results depending on network timing.
- **WHY:** Stale data rendered over fresh data. User clicks "Load" twice quickly, slower first request completes after faster second request, viewer shows wrong COG or collection.
- **WHERE:** `geotiler/static/js/viewer-raster.js` line 76 (`loadRaster()`), `geotiler/static/js/viewer-vector.js` (`loadCollection()`), `geotiler/static/js/viewer-zarr.js` (same pattern)
- **HOW:** Add a module-level generation counter (e.g., `let loadGeneration = 0`). At function entry, increment and capture `const myGen = ++loadGeneration`. After each `await`, check `if (myGen !== loadGeneration) return;` to bail out if a newer load has started.
- **EFFORT:** Medium (touch 3 files, each needs the same pattern)
- **RISK OF FIX:** Low

### 2. Escape `info.width` / `info.height` in raster viewer innerHTML

- **WHAT:** `info.width` and `info.height` are injected directly into innerHTML without `escapeHtml()` at lines 135-136 of viewer-raster.js. All other metadata fields (bandCount, dtype, crs, bounds, nodata) correctly use `escapeHtml()`.
- **WHY:** If a malicious COG server returns a crafted `width` or `height` field containing HTML/JS, it would execute in the viewer context. Low probability but trivial to fix.
- **WHERE:** `geotiler/static/js/viewer-raster.js` lines 135-136
- **HOW:** Change `+ info.width + ' px'` to `+ escapeHtml(String(info.width)) + ' px'` (same for height).
- **EFFORT:** Small (2 lines)
- **RISK OF FIX:** None

### 3. Guard null bbox values in vector metadata `.toFixed()` call

- **WHAT:** `extent.map(function(v) { return v.toFixed(4); })` at line 141 of viewer-vector.js will throw `TypeError: Cannot read properties of null` if the bbox array from the API contains null values (e.g., `[-180, -90, 180, null]`).
- **WHY:** Some OGC collections may have partial or null bbox coordinates. The metadata panel would fail to render, breaking the UI.
- **WHERE:** `geotiler/static/js/viewer-vector.js` line 141
- **HOW:** Guard with: `extent.map(function(v) { return v != null ? v.toFixed(4) : '?'; }).join(', ')`
- **EFFORT:** Small (1 line)
- **RISK OF FIX:** None

### 4. Escape `crop` / `tech` in H3 viewer innerHTML

- **WHAT:** `crop + ' / ' + tech` at line 137 of viewer-h3.js is injected into innerHTML without `escapeHtml()`. These values come from HTML select dropdowns (user-controlled).
- **WHY:** While the backend validates against frozen sets, the frontend should not trust that validation has occurred. Defense-in-depth.
- **WHERE:** `geotiler/static/js/viewer-h3.js` line 137
- **HOW:** Change to `escapeHtml(crop) + ' / ' + escapeHtml(tech)`
- **EFFORT:** Small (1 line)
- **RISK OF FIX:** None

### 5. Remove 13 dead functions from common.js (~130 lines)

- **WHAT:** 13 functions in common.js are never referenced outside the file: `getInputValue`, `getCogInfo`, `getXarrayInfo`, `viewTiles`, `displayJson`, `showSuccess`, `copyToClipboard`, `copyElementContent`, `throttle`, `formatDate`, `serializeForm`, `populateForm`, `formatLatLng`. Related internal-only helpers `showError`, `formatJson`, `formatBytes` are also only called by dead functions.
- **WHY:** Dead code increases maintenance burden, confuses contributors, and inflates page weight. These appear to be legacy functions from before the viewer rewrite.
- **WHERE:** `geotiler/static/js/common.js` — functions at lines 14, 27, 42, 72, 102, 120, 132, 144, 156, 182, 215, 233, 246, 268, 283, 301, 315, 450
- **HOW:** Delete all 13 dead functions plus their internal-only dependencies (`showError`, `formatJson`, `formatBytes`). Keep: `setUrl`, `escapeHtml`, `debounce`, `initTabs`, `fetchJSON`, `getQueryParam`, `setQueryParam`, `buildViewerUrl`, `showNotification`.
- **EFFORT:** Small (delete ~160 lines, run manual smoke test)
- **RISK OF FIX:** Low — verify no HTML templates call these functions inline

---

## ADDITIONAL FINDINGS

### P2-MEDIUM: `matched` unescaped in vector innerHTML

- **WHERE:** `geotiler/static/js/viewer-vector.js` line 138
- **WHAT:** `matched` (from `numberMatched` API field) inserted into innerHTML without escapeHtml(). It's always a number in practice, but defense-in-depth says escape it.
- **HOW:** `escapeHtml(String(matched))`
- **EFFORT:** Trivial

### P2-MEDIUM: fetchJSON sets Content-Type on GET requests

- **WHERE:** `geotiler/static/js/common.js` line 374
- **WHAT:** `Content-Type: application/json` header is set on all requests including GETs. GETs should not have a Content-Type header. While harmless for same-origin requests, this would trigger CORS preflight for cross-origin requests.
- **HOW:** Only set Content-Type when body is present: move header into the `if (body)` block.
- **EFFORT:** Small

---

## ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|--------------|
| No concurrent load guard (loadRaster, loadCollection) | Last layer cleanup prevents visual bugs; race only affects metadata | Users report wrong metadata after rapid switching |
| fetchJSON Content-Type on GETs | All requests are same-origin | Cross-origin API calls needed |
| No CSP headers on viewer pages | Server-side concern, not JS | Security audit |

---

## ARCHITECTURE WINS

1. **TileJSON-based MVT loading** (viewer-vector.js). The rewritten `addMvtLayer()` correctly fetches TileJSON for source-layer names, bounds, and zoom ranges. No more hardcoded `'default'` source-layer. Auto-zoom via `fitBounds()` ensures data is visible on load.

2. **escapeHtml() via DOM textContent** (common.js:166). Using `document.createElement('div').appendChild(document.createTextNode(text))` is XSS-proof by construction. Used consistently across raster, vector, zarr, and catalog JS.

3. **fetchJSON never-throws contract** (common.js:365). `{ok, data, error}` shape with AbortController timeout eliminates try/catch boilerplate in all callers. Clean error propagation.

4. **Click handler cleanup array** (viewer-vector.js:11). `activeClickHandlers` array tracks all registered handlers for proper cleanup — addresses the memory leak from the previous COMPETE review.

---

## FULL SEVERITY RANKING

| # | Severity | Finding | Confidence |
|---|----------|---------|------------|
| 1 | P1-HIGH | Race condition in loadRaster/loadCollection (stale data) | CONFIRMED |
| 2 | P2-MEDIUM | Unescaped info.width/info.height in raster innerHTML | CONFIRMED |
| 3 | P2-MEDIUM | Null bbox crash in vector .toFixed() | PROBABLE |
| 4 | P2-MEDIUM | Unescaped crop/tech in H3 innerHTML | CONFIRMED |
| 5 | P2-MEDIUM | 13 dead functions in common.js (~160 lines) | CONFIRMED |
| 6 | P2-MEDIUM | Unescaped matched in vector innerHTML | CONFIRMED |
| 7 | P2-MEDIUM | fetchJSON Content-Type on GETs | CONFIRMED |
| 8 | P3-LOW | No CSP headers | OUT OF SCOPE |

---

## DIFF FROM PREVIOUS REVIEW

Issues from COMPETE_VIEWER_REVIEW.md (2026-03-05) that are now resolved:
- **#1 Vector click handler accumulation** — FIXED (activeClickHandlers array + cleanup)
- **#2 Duplicate vector API call** — FIXED (single fetch, shared result)
- **#5 /viewer/h3 parameter mismatch** — still present but deprioritized (primary /h3 route works)

Issues carried forward:
- fetchJSON Content-Type on GETs (P2, accepted risk)
- No concurrent load guard (P1, now Top Fix #1)
