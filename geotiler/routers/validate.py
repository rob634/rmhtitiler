# geotiler/routers/validate.py
"""
Dataset validation endpoints.

Provides per-data-type validation and a batch /validate/all endpoint.
Feature-flagged via GEOTILER_ENABLE_VALIDATION.

See docs/superpowers/specs/2026-03-28-dataset-validation-design.md for spec.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request

from geotiler.config import settings
from geotiler.errors import error_response, FULL_SCAN_DISABLED, NOT_FOUND
from geotiler.services.validate import Depth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validate", tags=["Validation"])


def _gate_full_scan(depth: Depth):
    """Return an error response if full scan is requested but disabled."""
    if depth == Depth.full and not settings.enable_validation_full_scan:
        return error_response(
            "Full scan not enabled on this instance",
            403,
            FULL_SCAN_DISABLED,
            hint="Set GEOTILER_ENABLE_VALIDATION_FULL_SCAN=true to allow depth=full",
        )
    return None


@router.get("/vector/{collection_id}")
async def validate_vector_endpoint(
    request: Request,
    collection_id: str,
    depth: Depth = Query(Depth.metadata, description="Validation depth: metadata, sample, or full"),
):
    """Validate a vector (PostGIS) collection."""
    gate = _gate_full_scan(depth)
    if gate:
        return gate

    catalog = getattr(request.app.state, "collection_catalog", None)
    if catalog is not None and collection_id not in catalog:
        return error_response(f"Collection '{collection_id}' not found", 404, NOT_FOUND)

    from geotiler.services.validate.vector import validate_vector
    return await validate_vector(collection_id, depth, request.app)


@router.get("/cog")
async def validate_cog_endpoint(
    request: Request,
    url: str = Query(..., description="COG URL (e.g. /vsiaz/container/path.tif)"),
    depth: Depth = Query(Depth.metadata, description="Validation depth: metadata, sample, or full"),
):
    """Validate a Cloud Optimized GeoTIFF."""
    gate = _gate_full_scan(depth)
    if gate:
        return gate

    from geotiler.services.validate.cog import validate_cog
    return await validate_cog(url, depth)


@router.get("/zarr")
async def validate_zarr_endpoint(
    request: Request,
    url: str = Query(..., description="Zarr store URL (e.g. abfs://container/path.zarr)"),
    variable: str = Query(..., description="Data variable name to validate"),
    depth: Depth = Query(Depth.metadata, description="Validation depth: metadata, sample, or full"),
):
    """Validate a Zarr/NetCDF dataset."""
    gate = _gate_full_scan(depth)
    if gate:
        return gate

    from geotiler.services.validate.zarr import validate_zarr
    return await validate_zarr(url, variable, depth)


@router.get("/stac/{collection_id}")
async def validate_stac_endpoint(
    request: Request,
    collection_id: str,
    depth: Depth = Query(Depth.metadata, description="Validation depth: metadata, sample, or full"),
):
    """Validate a STAC collection in pgSTAC."""
    gate = _gate_full_scan(depth)
    if gate:
        return gate

    from geotiler.services.validate.stac import validate_stac
    return await validate_stac(collection_id, depth, request.app)


@router.get("/all")
async def validate_all_endpoint(
    request: Request,
    depth: Depth = Query(Depth.metadata, description="Validation depth: metadata, sample, or full"),
):
    """
    Validate all registered datasets.

    Discovers vector collections from TiPG catalog and STAC collections
    from pgstac. COG/Zarr URLs are discovered from STAC item assets.
    """
    gate = _gate_full_scan(depth)
    if gate:
        return gate

    datasets = []

    # --- Vector collections from TiPG catalog ---
    catalog = getattr(request.app.state, "collection_catalog", None)
    if catalog and settings.enable_tipg:
        from geotiler.services.validate.vector import validate_vector
        for cid in list(catalog.keys()):
            try:
                result = await validate_vector(cid, depth, request.app)
                datasets.append(result)
            except Exception as e:
                logger.error(f"Vector validation failed for {cid}: {e}")

    # --- STAC collections from pgSTAC ---
    stac_pool = getattr(request.app.state, "readpool", None)
    if stac_pool and settings.enable_stac_api:
        from geotiler.services.validate.stac import validate_stac
        try:
            async with stac_pool.acquire() as conn:
                rows = await conn.fetch("SELECT id FROM pgstac.collections")
            for row in rows:
                try:
                    result = await validate_stac(row["id"], depth, request.app)
                    datasets.append(result)
                except Exception as e:
                    logger.error(f"STAC validation failed for {row['id']}: {e}")
        except Exception as e:
            logger.error(f"Failed to list STAC collections: {e}")

    # --- Cross-reference: COG URLs from STAC assets (sample/full only) ---
    if stac_pool and depth in (Depth.sample, Depth.full):
        from geotiler.services.validate.cog import validate_cog
        cog_urls_checked = set()
        try:
            async with stac_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT DISTINCT content->'assets' as assets FROM pgstac.items LIMIT 50"
                )
            for row in rows:
                assets = row["assets"]
                if isinstance(assets, str):
                    try:
                        assets = json.loads(assets)
                    except json.JSONDecodeError:
                        continue
                if isinstance(assets, dict):
                    for asset in assets.values():
                        if isinstance(asset, dict):
                            href = asset.get("href", "")
                            if (href.endswith(".tif") or href.endswith(".tiff")) and href not in cog_urls_checked:
                                cog_urls_checked.add(href)
                                try:
                                    result = await validate_cog(href, depth)
                                    datasets.append(result)
                                except Exception as e:
                                    logger.error(f"COG validation failed for {href}: {e}")
        except Exception as e:
            logger.error(f"Failed to discover COG URLs from STAC: {e}")

    # --- Build aggregate report ---
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for ds in datasets:
        counts[ds.get("status", "fail")] = counts.get(ds.get("status", "fail"), 0) + 1
    total = len(datasets)
    parts = []
    if counts["fail"]:
        parts.append(f"{counts['fail']} fail")
    if counts["warn"]:
        parts.append(f"{counts['warn']} warn")
    if counts["pass"]:
        parts.append(f"{counts['pass']} pass")
    summary = f"{total} datasets validated: {', '.join(parts)}" if parts else "No datasets found"

    worst = "pass"
    if counts["warn"]:
        worst = "warn"
    if counts["fail"]:
        worst = "fail"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "depth": depth.value,
        "status": worst,
        "summary": summary,
        "datasets": datasets,
    }
