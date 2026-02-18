"""
OpenAPI schema post-processor for geotiler.

Fixes upstream tag, description, and operationId issues from TiTiler,
TiPG, and stac-fastapi libraries. These libraries auto-generate routes
with their own metadata that doesn't match our desired grouping.

This is the standard FastAPI pattern: we can't modify library source,
but we can transform the generated OpenAPI spec after the fact.
"""

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# ---------------------------------------------------------------------------
# STAC endpoint descriptions (replace the generic "Endpoint." text)
# ---------------------------------------------------------------------------
_STAC_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "/stac": {
        "get": "STAC API landing page with conformance and link metadata.",
    },
    "/stac/collections": {
        "get": "List all STAC collections in the catalog.",
    },
    "/stac/collections/{collection_id}": {
        "get": "Get metadata for a single STAC collection.",
    },
    "/stac/collections/{collection_id}/items": {
        "get": "List items (features) in a STAC collection with pagination.",
    },
    "/stac/collections/{collection_id}/items/{item_id}": {
        "get": "Get a single STAC item by ID.",
    },
    "/stac/search": {
        "get": "Search STAC items by spatial/temporal/property filters (GET).",
        "post": "Search STAC items by spatial/temporal/property filters (POST).",
    },
    "/stac/conformance": {
        "get": "List OGC API conformance classes supported by this server.",
    },
    "/stac/queryables": {
        "get": "List queryable properties for cross-collection filtering.",
    },
    "/stac/collections/{collection_id}/queryables": {
        "get": "List queryable properties for a specific collection.",
    },
}

# TiPG umbrella tag to strip (endpoints already have specific sub-tags)
_TIPG_UMBRELLA_TAG = "OGC Vector (TiPG)"

# TiPG sub-tag renames: original -> display name
_TIPG_TAG_RENAMES: dict[str, str] = {
    "OGC Features API": "OGC Vector -- Features",
    "OGC Tiles API": "OGC Vector -- Tiles",
    "OGC Common": "OGC Vector -- Common",
}


def _fix_operation(path: str, method: str, operation: dict) -> None:
    """Apply all fixes to a single operation."""
    tags = operation.get("tags", [])

    # --- A. Deduplicate tags ------------------------------------------------
    if len(tags) != len(set(tags)):
        tags = list(dict.fromkeys(tags))
        operation["tags"] = tags

    # --- B. Tag untagged STAC endpoints ------------------------------------
    if path.startswith("/stac") and (not tags or tags == ["default"]):
        operation["tags"] = ["STAC Catalog"]
        tags = operation["tags"]

    # --- C. Fix "Liveliness" typo (stac-fastapi _mgmt endpoints) -----------
    if "Liveliness/Readiness" in tags:
        operation["tags"] = ["STAC Catalog"]
        tags = operation["tags"]

    # --- D. Fix vector double-listing (strip umbrella, rename sub-tags) ----
    if _TIPG_UMBRELLA_TAG in tags:
        # Check if there's also a specific sub-tag
        has_sub = any(t in _TIPG_TAG_RENAMES for t in tags)
        if has_sub:
            tags = [t for t in tags if t != _TIPG_UMBRELLA_TAG]
        else:
            # No sub-tag — keep umbrella but rename to generic
            tags = [
                "OGC Vector -- Common" if t == _TIPG_UMBRELLA_TAG else t
                for t in tags
            ]
        operation["tags"] = tags

    # Rename TiPG sub-tags
    if any(t in _TIPG_TAG_RENAMES for t in tags):
        operation["tags"] = [_TIPG_TAG_RENAMES.get(t, t) for t in tags]
        tags = operation["tags"]

    # --- E. Fix STAC generic descriptions ----------------------------------
    desc = operation.get("summary", "") or operation.get("description", "")
    if path in _STAC_DESCRIPTIONS and method in _STAC_DESCRIPTIONS[path]:
        if not desc or desc.strip().rstrip(".") in ("Endpoint", ""):
            operation["summary"] = _STAC_DESCRIPTIONS[path][method]

    # --- F. Fix map viewer descriptions ------------------------------------
    if path.endswith("/map.html") or path.endswith("/map"):
        summary = operation.get("summary", "")
        if "TileJSON" in summary or "tilejson" in summary.lower():
            operation["summary"] = "Return an interactive map viewer (HTML page)."

    # --- G. Move GET /api from Admin to API Info ---------------------------
    if path == "/api" and method == "get":
        operation["tags"] = ["API Info"]

    # --- H. Tag Filter Extension queryables --------------------------------
    if path in ("/stac/queryables", "/stac/collections/{collection_id}/queryables"):
        if "STAC Catalog" not in tags:
            operation["tags"] = ["STAC Catalog"]


def customize_openapi(app: FastAPI) -> dict:
    """
    Generate and post-process the OpenAPI schema.

    Called via ``app.openapi = lambda: customize_openapi(app)``
    so FastAPI uses our fixed schema instead of the default.
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )

    # Post-process every operation
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method in ("get", "post", "put", "patch", "delete"):
                _fix_operation(path, method, operation)

    # Remove the umbrella tag definition if it exists
    if "tags" in schema:
        schema["tags"] = [
            t for t in schema["tags"] if t.get("name") != _TIPG_UMBRELLA_TAG
        ]

    app.openapi_schema = schema
    return schema
