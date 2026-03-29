# geotiler/services/validate/stac.py
"""
STAC (pgSTAC) dataset validation checks.

Uses raw asyncpg on the STAC read pool (app.state.readpool)
querying pgstac.collections and pgstac.items directly.
"""

import logging
from datetime import datetime

import httpx
from fastapi import FastAPI

from geotiler.services.validate import Depth, Status, check, report

logger = logging.getLogger(__name__)


async def _check_collection_exists(pool, collection_id: str) -> dict:
    """Check if collection exists in pgSTAC."""
    try:
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM pgstac.collections WHERE id = $1",
                collection_id,
            )
        if exists:
            return check("collection_exists", Status.PASS, f"Collection '{collection_id}' found in pgSTAC")
        return check("collection_exists", Status.FAIL, f"Collection '{collection_id}' not found in pgSTAC")
    except Exception as e:
        return check("collection_exists", Status.FAIL, f"Collection lookup failed: {e}")


async def _check_item_count(pool, collection_id: str) -> dict:
    """Check that the collection has items."""
    try:
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM pgstac.items WHERE collection = $1",
                collection_id,
            )
        if count and count > 0:
            return check("item_count", Status.PASS, f"{count:,} items", {"count": count})
        return check("item_count", Status.WARN, "Collection has no items", {"count": 0})
    except Exception as e:
        return check("item_count", Status.FAIL, f"Item count failed: {e}")


async def _check_assets_have_href(pool, collection_id: str, depth: Depth) -> dict:
    """Check that items have assets with href links."""
    try:
        async with pool.acquire() as conn:
            if depth == Depth.full:
                rows = await conn.fetch(
                    "SELECT id, content->'assets' as assets FROM pgstac.items "
                    "WHERE collection = $1",
                    collection_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, content->'assets' as assets FROM pgstac.items "
                    "WHERE collection = $1 LIMIT 10",
                    collection_id,
                )
        if not rows:
            return check("assets_have_href", Status.WARN, "No items to check")

        missing = []
        for row in rows:
            assets = row["assets"]
            if assets is None:
                missing.append(row["id"])
                continue
            # assets is a JSONB dict — check if any asset has an href
            has_href = False
            if isinstance(assets, dict):
                for asset in assets.values():
                    if isinstance(asset, dict) and asset.get("href"):
                        has_href = True
                        break
            elif isinstance(assets, str):
                # asyncpg may return JSON as string
                import json
                try:
                    parsed = json.loads(assets)
                    for asset in parsed.values():
                        if isinstance(asset, dict) and asset.get("href"):
                            has_href = True
                            break
                except (json.JSONDecodeError, AttributeError):
                    pass
            if not has_href:
                missing.append(row["id"])

        if not missing:
            return check(
                "assets_have_href", Status.PASS,
                f"All {len(rows)} checked items have asset hrefs",
            )
        return check(
            "assets_have_href", Status.WARN,
            f"{len(missing)} of {len(rows)} items missing asset hrefs",
            {"missing_ids": missing[:10]},
        )
    except Exception as e:
        return check("assets_have_href", Status.FAIL, f"Asset href check failed: {e}")


async def _check_bounds_valid(pool, collection_id: str, depth: Depth) -> dict:
    """Check that item bounding boxes are within WGS84 range."""
    try:
        async with pool.acquire() as conn:
            if depth == Depth.full:
                rows = await conn.fetch(
                    "SELECT id, content->'bbox' as bbox FROM pgstac.items "
                    "WHERE collection = $1",
                    collection_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, content->'bbox' as bbox FROM pgstac.items "
                    "WHERE collection = $1 LIMIT 10",
                    collection_id,
                )
        if not rows:
            return check("bounds_valid", Status.WARN, "No items to check")

        import json
        invalid = []
        for row in rows:
            bbox = row["bbox"]
            if bbox is None:
                invalid.append({"id": row["id"], "reason": "no bbox"})
                continue
            if isinstance(bbox, str):
                try:
                    bbox = json.loads(bbox)
                except json.JSONDecodeError:
                    invalid.append({"id": row["id"], "reason": "unparseable bbox"})
                    continue
            if not isinstance(bbox, list) or len(bbox) < 4:
                invalid.append({"id": row["id"], "reason": f"bbox has {len(bbox) if isinstance(bbox, list) else 0} elements"})
                continue
            minx, miny, maxx, maxy = bbox[0], bbox[1], bbox[2], bbox[3]
            if not (-180 <= minx <= 180 and -90 <= miny <= 90 and -180 <= maxx <= 180 and -90 <= maxy <= 90):
                invalid.append({"id": row["id"], "reason": f"out of WGS84 range: {bbox}"})

        if not invalid:
            return check("bounds_valid", Status.PASS, f"All {len(rows)} checked items have valid bounds")
        return check(
            "bounds_valid", Status.WARN,
            f"{len(invalid)} of {len(rows)} items have invalid bounds",
            {"invalid": invalid[:10]},
        )
    except Exception as e:
        return check("bounds_valid", Status.FAIL, f"Bounds check failed: {e}")


async def _check_datetime_valid(pool, collection_id: str, depth: Depth) -> dict:
    """Check that items have valid datetime or start/end datetime."""
    try:
        async with pool.acquire() as conn:
            if depth == Depth.full:
                rows = await conn.fetch(
                    "SELECT id, "
                    "content->'properties'->>'datetime' as dt, "
                    "content->'properties'->>'start_datetime' as start_dt, "
                    "content->'properties'->>'end_datetime' as end_dt "
                    "FROM pgstac.items WHERE collection = $1",
                    collection_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, "
                    "content->'properties'->>'datetime' as dt, "
                    "content->'properties'->>'start_datetime' as start_dt, "
                    "content->'properties'->>'end_datetime' as end_dt "
                    "FROM pgstac.items WHERE collection = $1 LIMIT 10",
                    collection_id,
                )
        if not rows:
            return check("datetime_valid", Status.WARN, "No items to check")

        invalid = []
        for row in rows:
            dt = row["dt"]
            start_dt = row["start_dt"]
            end_dt = row["end_dt"]

            has_valid = False
            if dt and dt != "null":
                try:
                    datetime.fromisoformat(dt.replace("Z", "+00:00"))
                    has_valid = True
                except ValueError:
                    invalid.append({"id": row["id"], "reason": f"unparseable datetime: {dt}"})
                    continue
            if start_dt and end_dt:
                try:
                    datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
                    datetime.fromisoformat(end_dt.replace("Z", "+00:00"))
                    has_valid = True
                except ValueError:
                    invalid.append({"id": row["id"], "reason": "unparseable start/end datetime"})
                    continue
            if not has_valid:
                invalid.append({"id": row["id"], "reason": "no datetime or start/end_datetime"})

        if not invalid:
            return check("datetime_valid", Status.PASS, f"All {len(rows)} checked items have valid datetime")
        return check(
            "datetime_valid", Status.WARN,
            f"{len(invalid)} of {len(rows)} items have datetime issues",
            {"invalid": invalid[:10]},
        )
    except Exception as e:
        return check("datetime_valid", Status.FAIL, f"Datetime check failed: {e}")


async def _check_asset_accessible(pool, collection_id: str) -> dict:
    """HEAD request sampled asset URLs to verify they resolve. Full depth only."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, content->'assets' as assets FROM pgstac.items "
                "WHERE collection = $1 LIMIT 10",
                collection_id,
            )
        if not rows:
            return check("asset_accessible", Status.WARN, "No items to check")

        import json
        urls_to_check = []
        for row in rows:
            assets = row["assets"]
            if isinstance(assets, str):
                try:
                    assets = json.loads(assets)
                except json.JSONDecodeError:
                    continue
            if isinstance(assets, dict):
                for asset in assets.values():
                    if isinstance(asset, dict) and asset.get("href"):
                        urls_to_check.append((row["id"], asset["href"]))
                        break  # One URL per item is enough

        if not urls_to_check:
            return check("asset_accessible", Status.WARN, "No asset URLs found to check")

        accessible = 0
        failed = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for item_id, url in urls_to_check[:10]:
                try:
                    resp = await client.head(url)
                    if resp.status_code < 400:
                        accessible += 1
                    else:
                        failed.append({"id": item_id, "url": url, "status": resp.status_code})
                except Exception as e:
                    failed.append({"id": item_id, "url": url, "error": str(e)})

        total = len(urls_to_check[:10])
        if not failed:
            return check("asset_accessible", Status.PASS, f"All {total} sampled asset URLs accessible")
        return check(
            "asset_accessible", Status.WARN,
            f"{len(failed)} of {total} sampled asset URLs failed",
            {"failed": failed},
        )
    except Exception as e:
        return check("asset_accessible", Status.FAIL, f"Asset accessibility check failed: {e}")


async def validate_stac(collection_id: str, depth: Depth, app: FastAPI) -> dict:
    """
    Validate a STAC collection in pgSTAC.

    Args:
        collection_id: STAC collection identifier
        depth: Validation depth (metadata, sample, full)
        app: FastAPI application instance

    Returns:
        ValidationReport dict.
    """
    pool = getattr(app.state, "readpool", None)
    if pool is None:
        checks = [check("pool", Status.FAIL, "STAC read pool not initialized")]
        return report(collection_id, "stac", depth, checks)

    checks = []

    # --- Metadata checks ---
    checks.append(await _check_collection_exists(pool, collection_id))
    checks.append(await _check_item_count(pool, collection_id))

    # If collection doesn't exist, stop here
    if checks[0]["status"] == "fail":
        return report(collection_id, "stac", depth, checks)

    # --- Sample/Full checks ---
    if depth in (Depth.sample, Depth.full):
        checks.append(await _check_assets_have_href(pool, collection_id, depth))
        checks.append(await _check_bounds_valid(pool, collection_id, depth))
        checks.append(await _check_datetime_valid(pool, collection_id, depth))

    # --- Full-only checks ---
    if depth == Depth.full:
        checks.append(await _check_asset_accessible(pool, collection_id))

    return report(collection_id, "stac", depth, checks)
