# Implementation Plans

## 1. TiPG Dynamic Table Registration ✅ IMPLEMENTED

**Problem**: TiPG's collection catalog is a static snapshot taken at startup. New tables created by ETL pipelines are invisible until application restart.

**Solution**: Hybrid approach - webhook endpoint + optional TTL-based auto-refresh.

### What Was Implemented

#### Webhook Endpoint (Always Available)
```
POST /admin/refresh-collections
```

Orchestrator calls this after ETL creates tables. Returns:
```json
{
  "status": "success",
  "collections_before": 5,
  "collections_after": 7,
  "new_collections": ["geo.new_layer_1", "geo.new_layer_2"],
  "removed_collections": [],
  "refresh_time": "2025-01-30T12:00:00Z"
}
```

#### Optional TTL Auto-Refresh (Env Var Controlled)
```bash
TIPG_CATALOG_TTL_ENABLED=true   # Enable auto-refresh (default: false)
TIPG_CATALOG_TTL=300            # Refresh interval in seconds (default: 300)
```

When enabled, TiPG's `CatalogUpdateMiddleware` automatically re-scans the database for new tables on incoming requests when TTL expires.

### Files Modified
- `geotiler/config.py` - Added `tipg_catalog_ttl_enabled` and `tipg_catalog_ttl` settings
- `geotiler/routers/admin.py` - Added `POST /admin/refresh-collections` webhook
- `geotiler/app.py` - Conditionally adds `CatalogUpdateMiddleware` when TTL enabled

### Orchestrator Integration

**With authentication enabled (production):**
```python
from azure.identity import DefaultAzureCredential
import requests

def refresh_geotiler_collections(geotiler_url: str):
    # Get token using Orchestrator's Managed Identity
    credential = DefaultAzureCredential()
    # Use any resource - we validate the caller's app ID, not the audience
    token = credential.get_token("https://management.azure.com/.default")

    response = requests.post(
        f"{geotiler_url}/admin/refresh-collections",
        headers={"Authorization": f"Bearer {token.token}"}
    )

    result = response.json()
    if result["status"] == "success":
        print(f"New tables registered: {result['new_collections']}")
    return result
```

**Without authentication (local dev):**
```python
import requests
response = requests.post("http://localhost:8000/admin/refresh-collections")
```

### Authentication Configuration

```bash
# Enable Azure AD auth for admin endpoints
ADMIN_AUTH_ENABLED=true

# Orchestrator's Managed Identity client ID
ADMIN_ALLOWED_APP_IDS=<orchestrator-mi-client-id>

# Your Azure tenant ID
AZURE_TENANT_ID=<tenant-id>
```

### Files Added/Modified
- `geotiler/auth/admin_auth.py` - **NEW** - Azure AD token validation
- `geotiler/config.py` - Added auth settings
- `geotiler/routers/admin.py` - Applied auth dependency
- `requirements.txt` - Added PyJWT, cryptography

---

## 2. STAC Collection Preview in STAC Explorer

**Problem**: Clicking a STAC collection in `/stac-explorer` loads its items, but there's no quick way to preview the collection's data on a map.

**Goal**: Add "Preview on Map" functionality to STAC collections that opens the Map Viewer with the collection's representative imagery.

### Current State Analysis

**STAC Explorer (`/stac-explorer`)**:
- Leaflet-based map
- Collection sidebar → click loads items in bottom panel
- Item selection shows assets with "View on Map" for COGs
- No collection-level preview

**Map Viewer (`/map`)**:
- MapLibre GL JS based
- STAC tab with breadcrumb: Collections → Items → Assets
- Full layer management with opacity/color controls
- Can accept URL parameters for direct layer loading

### Implementation Plan

#### Phase 1: Backend - Collection Preview URLs

**Task 1.1**: Add helper function to extract preview URLs from STAC collections

File: `geotiler/services/stac_utils.py` (new)

```python
def get_collection_preview_info(collection: dict) -> dict:
    """
    Extract preview/thumbnail information from a STAC collection.

    Sources (in priority order):
    1. Collection links with rel="preview" or rel="thumbnail"
    2. Collection's item_assets with roles containing "visual" or "thumbnail"
    3. First item's visual/thumbnail asset (requires extra API call)

    Returns:
        {
            "has_preview": bool,
            "preview_url": str | None,      # Direct image URL
            "tile_url": str | None,         # TileJSON or tile template URL
            "preview_type": str,            # "thumbnail", "cog", "mosaic"
            "map_viewer_url": str | None,   # Pre-built /map URL with params
        }
    """
```

**Task 1.2**: Add API endpoint for collection preview metadata

File: `geotiler/routers/stac_explorer.py`

```python
@router.get("/api/stac/collection/{collection_id}/preview")
async def get_collection_preview(collection_id: str, request: Request):
    """
    Get preview URLs for a STAC collection.

    Returns:
        - thumbnail_url: Static preview image
        - tilejson_url: For mosaic rendering
        - map_url: Direct link to /map with collection pre-loaded
    """
```

#### Phase 2: Frontend - Collection Card Enhancement

**Task 2.1**: Update collection card HTML in `explorer.html`

Add preview button/icon to each collection card:
```html
<div class="collection-item" data-id="${col.id}">
    <div class="collection-title">${col.id}</div>
    <div class="collection-desc">${desc}</div>
    <div class="collection-actions">
        <button onclick="previewCollection('${col.id}')" title="Preview on Map">
            🗺️ Preview
        </button>
        <button onclick="selectCollection('${col.id}')" title="Browse Items">
            📂 Browse
        </button>
    </div>
</div>
```

**Task 2.2**: Add `previewCollection()` JavaScript function

```javascript
async function previewCollection(collectionId) {
    // Option A: Open in new tab with Map Viewer
    const mapUrl = `/map?stac_collection=${collectionId}`;
    window.open(mapUrl, '_blank');

    // Option B: Fetch preview info and open appropriate viewer
    const preview = await fetch(`/api/stac/collection/${collectionId}/preview`);
    if (preview.tilejson_url) {
        window.open(preview.map_url, '_blank');
    }
}
```

#### Phase 3: Map Viewer - STAC Collection Direct Loading

**Task 3.1**: Update Map Viewer to accept URL parameters

File: `geotiler/templates/pages/map/viewer.html`

Add URL parameter parsing on load:
```javascript
// Parse URL params
const urlParams = new URLSearchParams(window.location.search);
const stacCollection = urlParams.get('stac_collection');

if (stacCollection) {
    // Auto-switch to STAC tab
    // Auto-load collection and first item's visual asset
    await autoLoadStacCollection(stacCollection);
}
```

**Task 3.2**: Implement `autoLoadStacCollection()` function

```javascript
async function autoLoadStacCollection(collectionId) {
    // 1. Fetch collection to get extent
    // 2. Fetch first N items
    // 3. Add first item's visual asset as layer
    // 4. Fit map to collection extent
}
```

#### Phase 4: pgSTAC Mosaic Integration (Optional Enhancement)

If the collection has many items, use pgSTAC mosaic search instead of individual items:

**Task 4.1**: Create mosaic search for collection

```javascript
async function createCollectionMosaic(collectionId) {
    // POST /searches/register with collection filter
    const search = await fetch('/searches/register', {
        method: 'POST',
        body: JSON.stringify({
            collections: [collectionId],
            limit: 100
        })
    });

    // Get search_id and load mosaic tiles
    const searchId = search.id;
    const tileUrl = `/searches/${searchId}/tiles/WebMercatorQuad/{z}/{x}/{y}.png`;
}
```

### File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `geotiler/services/stac_utils.py` | New | Helper functions for STAC preview extraction |
| `geotiler/routers/stac_explorer.py` | Modify | Add `/api/stac/collection/{id}/preview` endpoint |
| `geotiler/templates/pages/stac/explorer.html` | Modify | Add preview buttons, `previewCollection()` function |
| `geotiler/templates/pages/map/viewer.html` | Modify | URL param handling, `autoLoadStacCollection()` |
| `geotiler/routers/map_viewer.py` | Modify | Pass URL params to template context |

### UI/UX Considerations

1. **Collection Card Actions**:
   - "Preview" button → Opens Map Viewer in new tab
   - "Browse" button → Current behavior (loads items in bottom panel)

2. **Map Viewer URL Params**:
   - `?stac_collection={id}` → Load collection's first visual asset
   - `?stac_item={collection}/{item}` → Load specific item
   - `?stac_search={search_id}` → Load pgSTAC mosaic

3. **Preview Fallback Chain**:
   - Try collection thumbnail link first
   - Then try first item's "visual" asset
   - Then try first item's first COG asset
   - Show "No preview available" if none found

### Testing Checklist

- [ ] Collection with thumbnail link shows preview
- [ ] Collection without thumbnail falls back to first item
- [ ] "Preview" button opens Map Viewer in new tab
- [ ] Map Viewer URL params work correctly
- [ ] Map fits to collection extent
- [ ] Empty collections show appropriate message

---

## Questions to Resolve

### For STAC Preview Feature:

1. **Preview button placement**: On the collection card itself, or only visible on hover?
2. **New tab vs same page**: Should preview open in new tab or replace current view?
3. **Mosaic vs single item**: For collections with many items, should we use pgSTAC mosaic search?
4. **Asset selection**: If multiple visual assets exist, which one to use? First? User choice?
