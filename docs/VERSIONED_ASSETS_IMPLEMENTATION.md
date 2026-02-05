# Versioned Assets Implementation Plan

**Created**: 31 JAN 2026
**Status**: PLANNED
**Priority**: HIGH - Enables B2B `?version=latest` pattern
**Depends On**: rmhgeoapi V0.8 Release Control (lineage tracking)

---

## Executive Summary

Add a `/assets/{dataset}/{resource}` router that resolves `?version=latest` (or specific versions) to concrete TiTiler/TiPG endpoints. This enables B2B apps to use stable URLs that always point to the latest version of a dataset.

**Key Principle**: This is an **additive** feature. Native TiTiler (`/cog/*`), TiPG (`/vector/*`), and STAC (`/stac/*`) endpoints remain fully functional and unchanged.

---

## B2B Requirement

DDH (and other B2B platforms) need:

```bash
# Always get the latest version
/assets/floods/jakarta/tiles/{z}/{x}/{y}?version=latest

# Get a specific version
/assets/floods/jakarta/tiles/{z}/{x}/{y}?version=v2.0

# List available versions
/assets/floods/jakarta/versions
```

These URLs should be **stable** - the `?version=latest` URL automatically points to the newest version without B2B apps needing to update their references.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  B2B Request                                                                 │
│  GET /assets/floods/jakarta/tiles/10/512/384?version=latest                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Versioned Assets Router (NEW)                                               │
│  /assets/{dataset}/{resource}/...                                            │
│                                                                              │
│  1. Parse dataset_id + resource_id from path                                 │
│  2. Compute lineage_id (same algorithm as rmhgeoapi)                         │
│  3. Query rmhgeoapi database for asset                                       │
│     - version=latest → WHERE is_latest = TRUE                                │
│     - version=v2.0   → WHERE platform_refs->>'version_id' = 'v2.0'          │
│  4. Get blob_path (raster) or table_name (vector)                           │
│  5. Redirect to native endpoint                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ 307 Redirect
┌─────────────────────────────────────────────────────────────────────────────┐
│  Native TiTiler/TiPG Endpoint                                                │
│                                                                              │
│  Raster: /cog/tiles/10/512/384?url=https://storage.../floods-jakarta-v3.tif │
│  Vector: /vector/collections/geo.floods_jakarta_v3/tiles/10/512/384         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## rmhgeoapi Lineage Tracking Context

### How Lineage Works

In rmhgeoapi, assets are tracked in `app.geospatial_assets` with lineage support:

| Column | Purpose |
|--------|---------|
| `asset_id` | Primary key - hash of ALL platform refs including version |
| `lineage_id` | Groups assets with same nominal identity (excludes version) |
| `platform_id` | Platform identifier (e.g., "ddh") |
| `platform_refs` | JSONB with `dataset_id`, `resource_id`, `version_id` |
| `is_latest` | TRUE for the newest version in a lineage |
| `is_served` | TRUE if this version should be accessible via service URLs |
| `version_ordinal` | Integer ordering (1, 2, 3...) |
| `data_type` | "raster" or "vector" |
| `blob_path` | For raster: path to COG in blob storage |
| `table_name` | For vector: PostGIS table name |
| `schema_name` | For vector: PostGIS schema (usually "geo") |

### Lineage ID Generation

The `lineage_id` is computed from **nominal refs only** (excluding version):

```python
def compute_lineage_id(platform_id: str, dataset_id: str, resource_id: str) -> str:
    """
    Must match rmhgeoapi's generate_lineage_id() exactly.

    Example:
        platform_id = "ddh"
        dataset_id = "floods"
        resource_id = "jakarta"

        → lineage_id = sha256("ddh|{\"dataset_id\":\"floods\",\"resource_id\":\"jakarta\"}")[:32]
    """
    import hashlib
    import json

    nominal_values = {"dataset_id": dataset_id, "resource_id": resource_id}
    sorted_refs = json.dumps(nominal_values, sort_keys=True, separators=(',', ':'))
    composite = f"{platform_id}|{sorted_refs}"
    return hashlib.sha256(composite.encode()).hexdigest()[:32]
```

**Critical**: This algorithm must match rmhgeoapi exactly, or lookups will fail.

### Version Resolution Queries

```sql
-- Resolve ?version=latest
SELECT asset_id, data_type, blob_path, table_name, schema_name,
       stac_item_id, stac_collection_id,
       platform_refs->>'version_id' as version_id,
       is_latest
FROM app.geospatial_assets
WHERE lineage_id = $1
  AND is_latest = TRUE
  AND is_served = TRUE
  AND deleted_at IS NULL;

-- Resolve ?version=v2.0
SELECT asset_id, data_type, blob_path, table_name, schema_name,
       stac_item_id, stac_collection_id,
       platform_refs->>'version_id' as version_id,
       is_latest
FROM app.geospatial_assets
WHERE lineage_id = $1
  AND platform_refs->>'version_id' = $2
  AND is_served = TRUE
  AND deleted_at IS NULL;

-- List all versions
SELECT platform_refs->>'version_id' as version_id,
       version_ordinal,
       is_latest,
       created_at
FROM app.geospatial_assets
WHERE lineage_id = $1
  AND is_served = TRUE
  AND deleted_at IS NULL
ORDER BY version_ordinal DESC;
```

### Example Lineage Data

```
Lineage: floods/jakarta (lineage_id = "abc123...")

┌─────────────┬────────────┬─────────────────┬───────────┬───────────┐
│ asset_id    │ version_id │ version_ordinal │ is_latest │ is_served │
├─────────────┼────────────┼─────────────────┼───────────┼───────────┤
│ aaa...      │ v1.0       │ 1               │ FALSE     │ TRUE      │
│ bbb...      │ v2.0       │ 2               │ FALSE     │ TRUE      │
│ ccc...      │ v3.0       │ 3               │ TRUE      │ TRUE      │
└─────────────┴────────────┴─────────────────┴───────────┴───────────┘

Query: ?version=latest  → Returns ccc... (v3.0)
Query: ?version=v2.0    → Returns bbb... (v2.0)
Query: ?version=v1.0    → Returns aaa... (v1.0)
```

---

## Implementation Plan

### Phase 1: Configuration

**File**: `geotiler/config.py`

Add rmhgeoapi database connection settings:

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # rmhgeoapi database connection (for asset version resolution)
    rmhgeoapi_postgres_host: str = Field(default="", env="RMHGEOAPI_POSTGRES_HOST")
    rmhgeoapi_postgres_db: str = Field(default="", env="RMHGEOAPI_POSTGRES_DB")
    rmhgeoapi_postgres_user: str = Field(default="", env="RMHGEOAPI_POSTGRES_USER")
    rmhgeoapi_postgres_password: str = Field(default="", env="RMHGEOAPI_POSTGRES_PASSWORD")
    rmhgeoapi_postgres_schema: str = Field(default="app", env="RMHGEOAPI_POSTGRES_SCHEMA")

    # Feature flag
    enable_versioned_assets: bool = Field(default=False, env="ENABLE_VERSIONED_ASSETS")

    @property
    def rmhgeoapi_enabled(self) -> bool:
        """Check if rmhgeoapi connection is configured."""
        return self.enable_versioned_assets and bool(self.rmhgeoapi_postgres_host)
```

**Environment Variables**:
```bash
ENABLE_VERSIONED_ASSETS=true
RMHGEOAPI_POSTGRES_HOST=rmhpostgres.postgres.database.azure.com
RMHGEOAPI_POSTGRES_DB=rmhgeoapi
RMHGEOAPI_POSTGRES_USER=geotiler_reader
RMHGEOAPI_POSTGRES_PASSWORD=<secret>
RMHGEOAPI_POSTGRES_SCHEMA=app
```

**Note**: Consider using Managed Identity for the database connection (same pattern as existing postgres auth).

---

### Phase 2: Asset Resolver Service

**File**: `geotiler/services/asset_resolver.py`

```python
"""
Asset Resolver Service - Queries rmhgeoapi for versioned assets.

This service connects to the rmhgeoapi database to resolve version queries
(e.g., ?version=latest) to concrete assets with blob_path or table_name.

Architecture Decision (31 JAN 2026):
Lineage is implicit in rmhgeoapi - there is no app.lineages table.
Lineage is an emergent grouping of assets with the same lineage_id.
See rmhgeoapi/V0.8_RELEASE_CONTROL.md for details.
"""
import hashlib
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from geotiler.infrastructure.logging import LoggerFactory

logger = LoggerFactory.get_logger(__name__)


@dataclass
class ResolvedAsset:
    """
    Result of asset resolution.

    Contains all information needed to route to TiTiler or TiPG.
    """
    asset_id: str
    data_type: str  # "raster" or "vector"
    blob_path: Optional[str]  # For raster: path in blob storage
    table_name: Optional[str]  # For vector: PostGIS table name
    schema_name: Optional[str]  # For vector: PostGIS schema (usually "geo")
    stac_item_id: str
    stac_collection_id: str
    version_id: str
    is_latest: bool


@dataclass
class VersionInfo:
    """Version metadata for listing."""
    version_id: str
    version_ordinal: int
    is_latest: bool
    created_at: datetime


def compute_lineage_id(platform_id: str, dataset_id: str, resource_id: str) -> str:
    """
    Compute lineage_id from nominal refs.

    CRITICAL: This algorithm must match rmhgeoapi's generate_lineage_id() exactly.
    See: rmhgeoapi/core/models/asset.py::GeospatialAsset.generate_lineage_id()

    The lineage_id groups all versions of the same dataset/resource together.
    It excludes version_id from the hash.

    Args:
        platform_id: Platform identifier (e.g., "ddh")
        dataset_id: Dataset identifier from B2B platform
        resource_id: Resource identifier from B2B platform

    Returns:
        32-character hex string (truncated SHA256)

    Example:
        compute_lineage_id("ddh", "floods", "jakarta")
        → "a1b2c3d4..."  (32 chars)
    """
    # Build nominal refs dict (sorted keys for determinism)
    nominal_values = {"dataset_id": dataset_id, "resource_id": resource_id}

    # JSON serialize with specific formatting (must match rmhgeoapi)
    sorted_refs = json.dumps(nominal_values, sort_keys=True, separators=(',', ':'))

    # Composite string format: "platform_id|json_refs"
    composite = f"{platform_id}|{sorted_refs}"

    # SHA256 hash, truncated to 32 chars
    return hashlib.sha256(composite.encode()).hexdigest()[:32]


class AssetResolver:
    """
    Resolves versioned asset requests to concrete assets.

    This service queries the rmhgeoapi database's app.geospatial_assets table
    to find assets by lineage and version.

    Usage:
        resolver = AssetResolver(pool, schema="app")

        # Get latest version
        asset = await resolver.resolve("floods", "jakarta", version="latest")

        # Get specific version
        asset = await resolver.resolve("floods", "jakarta", version="v2.0")

        # List all versions
        versions = await resolver.list_versions("floods", "jakarta")
    """

    def __init__(self, pool: asyncpg.Pool, schema: str = "app"):
        """
        Initialize resolver with database pool.

        Args:
            pool: asyncpg connection pool to rmhgeoapi database
            schema: Database schema containing geospatial_assets table
        """
        self._pool = pool
        self._schema = schema

    async def resolve(
        self,
        dataset_id: str,
        resource_id: str,
        version: str = "latest",
        platform_id: str = "ddh"
    ) -> Optional[ResolvedAsset]:
        """
        Resolve a versioned asset request.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            version: "latest" or specific version like "v2.0"
            platform_id: Platform identifier (default: "ddh")

        Returns:
            ResolvedAsset if found, None if no matching asset

        Example:
            # Resolve latest
            asset = await resolver.resolve("floods", "jakarta", "latest")
            if asset:
                if asset.data_type == "raster":
                    # Use asset.blob_path for TiTiler
                else:
                    # Use asset.schema_name + asset.table_name for TiPG
        """
        lineage_id = compute_lineage_id(platform_id, dataset_id, resource_id)

        logger.debug(
            f"Resolving asset: {dataset_id}/{resource_id}?version={version} "
            f"(lineage_id={lineage_id[:8]}...)"
        )

        if version == "latest":
            query = f"""
                SELECT
                    asset_id,
                    data_type,
                    blob_path,
                    table_name,
                    schema_name,
                    stac_item_id,
                    stac_collection_id,
                    platform_refs->>'version_id' as version_id,
                    is_latest
                FROM {self._schema}.geospatial_assets
                WHERE lineage_id = $1
                  AND is_latest = TRUE
                  AND is_served = TRUE
                  AND deleted_at IS NULL
            """
            row = await self._pool.fetchrow(query, lineage_id)
        else:
            query = f"""
                SELECT
                    asset_id,
                    data_type,
                    blob_path,
                    table_name,
                    schema_name,
                    stac_item_id,
                    stac_collection_id,
                    platform_refs->>'version_id' as version_id,
                    is_latest
                FROM {self._schema}.geospatial_assets
                WHERE lineage_id = $1
                  AND platform_refs->>'version_id' = $2
                  AND is_served = TRUE
                  AND deleted_at IS NULL
            """
            row = await self._pool.fetchrow(query, lineage_id, version)

        if not row:
            logger.warning(
                f"Asset not found: {dataset_id}/{resource_id}?version={version} "
                f"(lineage_id={lineage_id[:8]}...)"
            )
            return None

        asset = ResolvedAsset(
            asset_id=row['asset_id'],
            data_type=row['data_type'],
            blob_path=row['blob_path'],
            table_name=row['table_name'],
            schema_name=row['schema_name'],
            stac_item_id=row['stac_item_id'],
            stac_collection_id=row['stac_collection_id'],
            version_id=row['version_id'],
            is_latest=row['is_latest']
        )

        logger.debug(
            f"Resolved asset: {asset.asset_id[:8]}... "
            f"({asset.data_type}, version={asset.version_id})"
        )

        return asset

    async def list_versions(
        self,
        dataset_id: str,
        resource_id: str,
        platform_id: str = "ddh"
    ) -> List[VersionInfo]:
        """
        List all served versions for a lineage.

        Args:
            dataset_id: DDH dataset identifier
            resource_id: DDH resource identifier
            platform_id: Platform identifier (default: "ddh")

        Returns:
            List of VersionInfo ordered by version_ordinal descending (newest first)
        """
        lineage_id = compute_lineage_id(platform_id, dataset_id, resource_id)

        query = f"""
            SELECT
                platform_refs->>'version_id' as version_id,
                version_ordinal,
                is_latest,
                created_at
            FROM {self._schema}.geospatial_assets
            WHERE lineage_id = $1
              AND is_served = TRUE
              AND deleted_at IS NULL
            ORDER BY version_ordinal DESC
        """

        rows = await self._pool.fetch(query, lineage_id)

        return [
            VersionInfo(
                version_id=row['version_id'],
                version_ordinal=row['version_ordinal'],
                is_latest=row['is_latest'],
                created_at=row['created_at']
            )
            for row in rows
        ]

    async def health_check(self) -> bool:
        """Check if database connection is healthy."""
        try:
            await self._pool.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Asset resolver health check failed: {e}")
            return False
```

---

### Phase 3: Versioned Assets Router

**File**: `geotiler/routers/versioned_assets.py`

```python
"""
Versioned Assets Router - Routes ?version=latest to TiTiler/TiPG.

This router provides B2B-friendly URLs that abstract away the underlying
storage paths and table names. It resolves version queries and redirects
to native TiTiler or TiPG endpoints.

URL Patterns:
    Raster:
        /assets/{dataset}/{resource}/tiles/{z}/{x}/{y}?version=latest
        /assets/{dataset}/{resource}/tilejson.json?version=latest
        /assets/{dataset}/{resource}/preview?version=latest

    Vector:
        /assets/{dataset}/{resource}/vector/tiles/{z}/{x}/{y}?version=latest
        /assets/{dataset}/{resource}/vector/items?version=latest

    Metadata:
        /assets/{dataset}/{resource}/info?version=latest
        /assets/{dataset}/{resource}/versions

Architecture:
    All endpoints use 307 Temporary Redirect to preserve request method.
    Native TiTiler/TiPG endpoints remain fully functional alongside this router.
"""
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Optional
from urllib.parse import urlencode

from geotiler.config import settings
from geotiler.services.asset_resolver import AssetResolver
from geotiler.infrastructure.logging import LoggerFactory

logger = LoggerFactory.get_logger(__name__)

router = APIRouter(prefix="/assets", tags=["Versioned Assets"])


def get_resolver(request: Request) -> AssetResolver:
    """
    Get asset resolver from app state.

    The resolver is initialized during app startup if ENABLE_VERSIONED_ASSETS=true.
    """
    if not hasattr(request.app.state, 'rmhgeoapi_pool'):
        raise HTTPException(
            status_code=503,
            detail="Versioned assets not configured. Set ENABLE_VERSIONED_ASSETS=true."
        )
    return AssetResolver(
        request.app.state.rmhgeoapi_pool,
        schema=settings.rmhgeoapi_postgres_schema
    )


def build_blob_url(blob_path: str) -> str:
    """
    Build full blob URL from path.

    Args:
        blob_path: Path like "silver-raster/floods/jakarta/v3.tif"

    Returns:
        Full URL like "https://account.blob.core.windows.net/silver-raster/..."
    """
    # blob_path format: "container/path/to/file.tif"
    return f"https://{settings.azure_storage_account}.blob.core.windows.net/{blob_path}"


# ============================================================================
# RASTER ENDPOINTS (redirect to /cog)
# ============================================================================

@router.get(
    "/{dataset}/{resource}/tiles/{z}/{x}/{y}.{format}",
    summary="Get raster tile for versioned asset",
    description="Resolves version and redirects to /cog/tiles endpoint"
)
@router.get(
    "/{dataset}/{resource}/tiles/{z}/{x}/{y}",
    include_in_schema=False  # Avoid duplicate in OpenAPI
)
async def versioned_raster_tile(
    request: Request,
    dataset: str,
    resource: str,
    z: int,
    x: int,
    y: int,
    format: str = "png",
    version: str = Query("latest", description="Version ID or 'latest'"),
    # Pass through TiTiler parameters
    scale: Optional[int] = Query(None, description="Tile scale factor"),
    tilesize: Optional[int] = Query(None, alias="tileSize", description="Tile size"),
    colormap_name: Optional[str] = Query(None, description="Colormap name"),
    rescale: Optional[str] = Query(None, description="Rescale range (min,max)"),
    return_mask: Optional[bool] = Query(None, description="Return mask band"),
):
    """
    Get raster tile for versioned asset.

    Resolves the version query and redirects (307) to /cog/tiles.
    All TiTiler query parameters are passed through.
    """
    resolver = get_resolver(request)
    asset = await resolver.resolve(dataset, resource, version)

    if not asset:
        raise HTTPException(
            status_code=404,
            detail=f"Asset not found: {dataset}/{resource}?version={version}"
        )

    if asset.data_type != "raster":
        raise HTTPException(
            status_code=400,
            detail=f"Asset is {asset.data_type}, not raster. Use /assets/{dataset}/{resource}/vector/tiles/..."
        )

    # Build redirect URL
    blob_url = build_blob_url(asset.blob_path)

    # Collect pass-through params
    params = {"url": blob_url}
    if scale:
        params["scale"] = scale
    if tilesize:
        params["tileSize"] = tilesize
    if colormap_name:
        params["colormap_name"] = colormap_name
    if rescale:
        params["rescale"] = rescale
    if return_mask is not None:
        params["return_mask"] = str(return_mask).lower()

    redirect_url = f"/cog/tiles/{z}/{x}/{y}.{format}?{urlencode(params)}"

    logger.info(
        f"Resolved {dataset}/{resource}?version={version} → {asset.version_id} "
        f"(asset_id={asset.asset_id[:8]}...)"
    )

    return RedirectResponse(url=redirect_url, status_code=307)


@router.get(
    "/{dataset}/{resource}/tilejson.json",
    summary="Get TileJSON for versioned raster asset"
)
async def versioned_raster_tilejson(
    request: Request,
    dataset: str,
    resource: str,
    version: str = Query("latest"),
    tile_format: str = Query("png", description="Tile format"),
    tilesize: Optional[int] = Query(None, alias="tileSize"),
    minzoom: Optional[int] = Query(None),
    maxzoom: Optional[int] = Query(None),
):
    """Get TileJSON for versioned raster asset."""
    resolver = get_resolver(request)
    asset = await resolver.resolve(dataset, resource, version)

    if not asset:
        raise HTTPException(404, f"Asset not found: {dataset}/{resource}?version={version}")

    if asset.data_type != "raster":
        raise HTTPException(400, f"Asset is {asset.data_type}, not raster")

    blob_url = build_blob_url(asset.blob_path)

    params = {"url": blob_url, "tile_format": tile_format}
    if tilesize:
        params["tileSize"] = tilesize
    if minzoom is not None:
        params["minzoom"] = minzoom
    if maxzoom is not None:
        params["maxzoom"] = maxzoom

    return RedirectResponse(
        url=f"/cog/tilejson.json?{urlencode(params)}",
        status_code=307
    )


@router.get(
    "/{dataset}/{resource}/preview",
    summary="Get preview image for versioned raster asset"
)
async def versioned_raster_preview(
    request: Request,
    dataset: str,
    resource: str,
    version: str = Query("latest"),
    max_size: int = Query(1024, description="Maximum dimension"),
    format: str = Query("png", description="Output format"),
):
    """Get preview image for versioned raster asset."""
    resolver = get_resolver(request)
    asset = await resolver.resolve(dataset, resource, version)

    if not asset:
        raise HTTPException(404, f"Asset not found: {dataset}/{resource}?version={version}")

    if asset.data_type != "raster":
        raise HTTPException(400, f"Asset is {asset.data_type}, not raster")

    blob_url = build_blob_url(asset.blob_path)

    return RedirectResponse(
        url=f"/cog/preview.{format}?url={blob_url}&max_size={max_size}",
        status_code=307
    )


# ============================================================================
# VECTOR ENDPOINTS (redirect to /vector TiPG)
# ============================================================================

@router.get(
    "/{dataset}/{resource}/vector/tiles/{z}/{x}/{y}",
    summary="Get vector tile for versioned asset"
)
async def versioned_vector_tile(
    request: Request,
    dataset: str,
    resource: str,
    z: int,
    x: int,
    y: int,
    version: str = Query("latest"),
):
    """
    Get vector tile (MVT) for versioned asset.

    Resolves version and redirects to TiPG endpoint.
    """
    resolver = get_resolver(request)
    asset = await resolver.resolve(dataset, resource, version)

    if not asset:
        raise HTTPException(404, f"Asset not found: {dataset}/{resource}?version={version}")

    if asset.data_type != "vector":
        raise HTTPException(
            400,
            f"Asset is {asset.data_type}, not vector. Use /assets/{dataset}/{resource}/tiles/..."
        )

    # TiPG collection ID format: schema.table
    collection_id = f"{asset.schema_name}.{asset.table_name}"

    logger.info(
        f"Resolved vector {dataset}/{resource}?version={version} → {collection_id}"
    )

    return RedirectResponse(
        url=f"/vector/collections/{collection_id}/tiles/{z}/{x}/{y}",
        status_code=307
    )


@router.get(
    "/{dataset}/{resource}/vector/items",
    summary="Get vector features for versioned asset"
)
async def versioned_vector_items(
    request: Request,
    dataset: str,
    resource: str,
    version: str = Query("latest"),
    limit: int = Query(10, ge=1, le=10000, description="Maximum features to return"),
    offset: int = Query(0, ge=0, description="Number of features to skip"),
    bbox: Optional[str] = Query(None, description="Bounding box filter (minx,miny,maxx,maxy)"),
):
    """
    Get vector features (GeoJSON) for versioned asset.

    Redirects to TiPG OGC Features endpoint.
    """
    resolver = get_resolver(request)
    asset = await resolver.resolve(dataset, resource, version)

    if not asset:
        raise HTTPException(404, f"Asset not found: {dataset}/{resource}?version={version}")

    if asset.data_type != "vector":
        raise HTTPException(400, f"Asset is {asset.data_type}, not vector")

    collection_id = f"{asset.schema_name}.{asset.table_name}"

    params = {"limit": limit, "offset": offset}
    if bbox:
        params["bbox"] = bbox

    return RedirectResponse(
        url=f"/vector/collections/{collection_id}/items?{urlencode(params)}",
        status_code=307
    )


@router.get(
    "/{dataset}/{resource}/vector/tilejson.json",
    summary="Get TileJSON for versioned vector asset"
)
async def versioned_vector_tilejson(
    request: Request,
    dataset: str,
    resource: str,
    version: str = Query("latest"),
):
    """Get TileJSON for versioned vector asset."""
    resolver = get_resolver(request)
    asset = await resolver.resolve(dataset, resource, version)

    if not asset:
        raise HTTPException(404, f"Asset not found: {dataset}/{resource}?version={version}")

    if asset.data_type != "vector":
        raise HTTPException(400, f"Asset is {asset.data_type}, not vector")

    collection_id = f"{asset.schema_name}.{asset.table_name}"

    return RedirectResponse(
        url=f"/vector/collections/{collection_id}/tilejson.json",
        status_code=307
    )


# ============================================================================
# METADATA ENDPOINTS
# ============================================================================

@router.get(
    "/{dataset}/{resource}/info",
    summary="Get asset metadata"
)
async def versioned_asset_info(
    request: Request,
    dataset: str,
    resource: str,
    version: str = Query("latest"),
):
    """
    Get metadata for versioned asset.

    For raster: redirects to /cog/info
    For vector: returns asset metadata directly
    """
    resolver = get_resolver(request)
    asset = await resolver.resolve(dataset, resource, version)

    if not asset:
        raise HTTPException(404, f"Asset not found: {dataset}/{resource}?version={version}")

    if asset.data_type == "raster":
        blob_url = build_blob_url(asset.blob_path)
        return RedirectResponse(
            url=f"/cog/info?url={blob_url}",
            status_code=307
        )
    else:
        # Vector - return metadata directly
        collection_id = f"{asset.schema_name}.{asset.table_name}"
        return JSONResponse({
            "asset_id": asset.asset_id,
            "data_type": asset.data_type,
            "dataset_id": dataset,
            "resource_id": resource,
            "version_id": asset.version_id,
            "is_latest": asset.is_latest,
            "schema": asset.schema_name,
            "table": asset.table_name,
            "stac_item_id": asset.stac_item_id,
            "stac_collection_id": asset.stac_collection_id,
            "links": {
                "tipg_collection": f"/vector/collections/{collection_id}",
                "tipg_items": f"/vector/collections/{collection_id}/items",
                "tipg_tiles": f"/vector/collections/{collection_id}/tiles/{{z}}/{{x}}/{{y}}",
                "stac_item": f"/stac/collections/{asset.stac_collection_id}/items/{asset.stac_item_id}"
            }
        })


@router.get(
    "/{dataset}/{resource}/versions",
    summary="List available versions"
)
async def list_versions(
    request: Request,
    dataset: str,
    resource: str,
):
    """
    List all available versions for a dataset/resource.

    Returns versions ordered by ordinal (newest first).
    """
    resolver = get_resolver(request)
    versions = await resolver.list_versions(dataset, resource)

    if not versions:
        raise HTTPException(404, f"No versions found for {dataset}/{resource}")

    latest = next((v for v in versions if v.is_latest), None)

    return JSONResponse({
        "dataset_id": dataset,
        "resource_id": resource,
        "version_count": len(versions),
        "latest": {
            "version_id": latest.version_id,
            "version_ordinal": latest.version_ordinal
        } if latest else None,
        "versions": [
            {
                "version_id": v.version_id,
                "version_ordinal": v.version_ordinal,
                "is_latest": v.is_latest,
                "created_at": v.created_at.isoformat()
            }
            for v in versions
        ]
    })
```

---

### Phase 4: App Integration

**File**: `geotiler/app.py`

Add to the lifespan context manager and router mounting:

```python
# Add import at top
from geotiler.routers import versioned_assets
import asyncpg

# In lifespan() function, add after existing pool initialization:

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup code ...

    # Initialize rmhgeoapi connection pool (for versioned asset resolution)
    if settings.rmhgeoapi_enabled:
        logger.info("Initializing rmhgeoapi connection pool for versioned assets")
        try:
            app.state.rmhgeoapi_pool = await asyncpg.create_pool(
                host=settings.rmhgeoapi_postgres_host,
                database=settings.rmhgeoapi_postgres_db,
                user=settings.rmhgeoapi_postgres_user,
                password=settings.rmhgeoapi_postgres_password,
                min_size=2,
                max_size=10,
                command_timeout=30
            )
            logger.info("rmhgeoapi connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize rmhgeoapi pool: {e}")
            # Don't fail startup - versioned assets will return 503

    yield

    # Cleanup
    if hasattr(app.state, 'rmhgeoapi_pool'):
        logger.info("Closing rmhgeoapi connection pool")
        await app.state.rmhgeoapi_pool.close()

# In create_app(), add router mounting:

def create_app() -> FastAPI:
    # ... existing code ...

    # Mount versioned assets router (if configured)
    if settings.rmhgeoapi_enabled:
        app.include_router(versioned_assets.router)
        logger.info("Versioned assets router mounted at /assets")

    return app
```

---

### Phase 5: Health Check Integration

**File**: `geotiler/routers/health.py`

Add rmhgeoapi pool check to health endpoint:

```python
# In health() endpoint, add:

# Check rmhgeoapi pool (if configured)
rmhgeoapi_status = "not_configured"
if hasattr(app.state, 'rmhgeoapi_pool'):
    try:
        await app.state.rmhgeoapi_pool.fetchval("SELECT 1")
        rmhgeoapi_status = "healthy"
    except Exception as e:
        rmhgeoapi_status = f"error: {str(e)}"
        issues.append(f"rmhgeoapi database: {e}")

# Add to response:
return JSONResponse({
    # ... existing fields ...
    "services": {
        # ... existing services ...
        "versioned_assets": {
            "enabled": settings.rmhgeoapi_enabled,
            "rmhgeoapi_database": rmhgeoapi_status
        }
    }
})
```

---

## URL Patterns Summary

### Raster Assets

| Endpoint | Description |
|----------|-------------|
| `GET /assets/{dataset}/{resource}/tiles/{z}/{x}/{y}?version=latest` | Tile (PNG/WebP) |
| `GET /assets/{dataset}/{resource}/tilejson.json?version=latest` | TileJSON metadata |
| `GET /assets/{dataset}/{resource}/preview?version=latest` | Preview image |
| `GET /assets/{dataset}/{resource}/info?version=latest` | COG metadata |

### Vector Assets

| Endpoint | Description |
|----------|-------------|
| `GET /assets/{dataset}/{resource}/vector/tiles/{z}/{x}/{y}?version=latest` | MVT tile |
| `GET /assets/{dataset}/{resource}/vector/tilejson.json?version=latest` | TileJSON |
| `GET /assets/{dataset}/{resource}/vector/items?version=latest` | GeoJSON features |
| `GET /assets/{dataset}/{resource}/info?version=latest` | Table metadata |

### Metadata

| Endpoint | Description |
|----------|-------------|
| `GET /assets/{dataset}/{resource}/versions` | List all versions |

---

## Testing Plan

### Unit Tests

```python
# tests/test_asset_resolver.py

def test_compute_lineage_id():
    """Verify lineage_id matches rmhgeoapi algorithm."""
    lineage_id = compute_lineage_id("ddh", "floods", "jakarta")
    # Compare with known value from rmhgeoapi
    assert len(lineage_id) == 32
    assert lineage_id.isalnum()

async def test_resolve_latest(mock_pool):
    """Test resolving ?version=latest."""
    resolver = AssetResolver(mock_pool)
    asset = await resolver.resolve("floods", "jakarta", "latest")
    assert asset.is_latest == True

async def test_resolve_specific_version(mock_pool):
    """Test resolving specific version."""
    resolver = AssetResolver(mock_pool)
    asset = await resolver.resolve("floods", "jakarta", "v2.0")
    assert asset.version_id == "v2.0"
```

### Integration Tests

```bash
# Test raster tile resolution
curl "http://localhost:8000/assets/floods/jakarta/tiles/10/512/384?version=latest"
# Should redirect to /cog/tiles/...

# Test vector tile resolution
curl "http://localhost:8000/assets/floods/jakarta/vector/tiles/10/512/384?version=latest"
# Should redirect to /vector/collections/...

# Test version listing
curl "http://localhost:8000/assets/floods/jakarta/versions"
# Should return JSON with version list
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ENABLE_VERSIONED_ASSETS` | No | `false` | Enable versioned assets router |
| `RMHGEOAPI_POSTGRES_HOST` | If enabled | - | rmhgeoapi database host |
| `RMHGEOAPI_POSTGRES_DB` | If enabled | - | rmhgeoapi database name |
| `RMHGEOAPI_POSTGRES_USER` | If enabled | - | Database user |
| `RMHGEOAPI_POSTGRES_PASSWORD` | If enabled | - | Database password |
| `RMHGEOAPI_POSTGRES_SCHEMA` | No | `app` | Schema containing geospatial_assets |

---

## Deployment Considerations

### Database Access

The geotiler app needs **read-only** access to rmhgeoapi's `app.geospatial_assets` table:

```sql
-- Run in rmhgeoapi database
CREATE ROLE geotiler_reader WITH LOGIN PASSWORD '<secret>';
GRANT USAGE ON SCHEMA app TO geotiler_reader;
GRANT SELECT ON app.geospatial_assets TO geotiler_reader;
```

Consider using Managed Identity for production (same pattern as existing postgres auth).

### Connection Pooling

- Min pool size: 2 (handles health checks + occasional requests)
- Max pool size: 10 (tune based on load)
- Command timeout: 30s

### Caching (Future Enhancement)

Consider adding Redis caching for resolved assets:
- Cache key: `asset:{lineage_id}:{version}`
- TTL: 60 seconds for `latest`, longer for specific versions
- Invalidation: Not needed (ETL layer updates is_latest flag)

---

## References

- [rmhgeoapi V0.8_RELEASE_CONTROL.md](../rmhgeoapi/V0.8_RELEASE_CONTROL.md) - Lineage architecture
- [rmhgeoapi DRY_RUN_IMPLEMENTATION.md](../rmhgeoapi/docs_claude/DRY_RUN_IMPLEMENTATION.md) - Version validation
- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [TiPG Documentation](https://developmentseed.org/tipg/)
