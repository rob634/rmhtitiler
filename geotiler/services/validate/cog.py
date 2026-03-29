# geotiler/services/validate/cog.py
"""
COG (Cloud Optimized GeoTIFF) dataset validation checks.

Uses rasterio directly with the existing GDAL env/auth configuration.
All rasterio calls are synchronous and wrapped in asyncio.to_thread().
"""

import asyncio
import logging

import rasterio

from geotiler.services.validate import Depth, Status, check, report

logger = logging.getLogger(__name__)


def _run_checks_sync(url: str, depth: Depth) -> list[dict]:
    """Run all COG checks synchronously. Called via asyncio.to_thread()."""
    checks = []

    # --- accessible: can we open the file at all? ---
    try:
        src = rasterio.open(url)
    except Exception as e:
        checks.append(check("accessible", Status.FAIL, f"Cannot open: {e}"))
        return checks

    try:
        checks.append(check("accessible", Status.PASS, f"Opened successfully ({src.driver})"))

        if depth in (Depth.sample, Depth.full):
            # --- is_tiled ---
            if src.is_tiled:
                block = src.block_shapes[0] if src.block_shapes else "unknown"
                checks.append(check("is_tiled", Status.PASS, f"Tiled (block shape: {block})"))
            else:
                checks.append(check(
                    "is_tiled", Status.WARN,
                    "Not internally tiled — tile serving will be slow (full scanline reads)",
                ))

            # --- has_overviews ---
            overviews = src.overviews(1)
            if overviews:
                checks.append(check(
                    "has_overviews", Status.PASS,
                    f"{len(overviews)} overview levels: {overviews}",
                    {"levels": len(overviews), "factors": overviews},
                ))
            else:
                checks.append(check(
                    "has_overviews", Status.WARN,
                    "No overviews — zoom-out tiles will be slow (read full resolution + downsample)",
                ))

            # --- crs_defined ---
            if src.crs is not None:
                checks.append(check("crs_defined", Status.PASS, f"CRS: {src.crs}"))
            else:
                checks.append(check("crs_defined", Status.FAIL, "No CRS defined — tiles cannot be georeferenced"))

            # --- nodata_defined ---
            if src.nodata is not None:
                checks.append(check("nodata_defined", Status.PASS, f"Nodata: {src.nodata}"))
            else:
                checks.append(check(
                    "nodata_defined", Status.WARN,
                    "No nodata value — transparent areas may render as black",
                ))

            # --- band_count ---
            if src.count >= 1:
                dtypes = list(set(src.dtypes))
                checks.append(check(
                    "band_count", Status.PASS,
                    f"{src.count} band(s), dtype: {', '.join(dtypes)}",
                    {"bands": src.count, "dtypes": dtypes},
                ))
            else:
                checks.append(check("band_count", Status.FAIL, "Zero bands"))

        if depth == Depth.full:
            # --- readable_tile: read a small window of actual pixel data ---
            try:
                # Read a 256x256 window from top-left corner
                window = rasterio.windows.Window(0, 0, min(256, src.width), min(256, src.height))
                data = src.read(1, window=window)
                checks.append(check(
                    "readable_tile", Status.PASS,
                    f"Read {window.width}x{window.height} tile successfully",
                    {"shape": list(data.shape)},
                ))
            except Exception as e:
                checks.append(check("readable_tile", Status.FAIL, f"Failed to read tile data: {e}"))

    finally:
        src.close()

    return checks


async def validate_cog(url: str, depth: Depth) -> dict:
    """
    Validate a Cloud Optimized GeoTIFF.

    Args:
        url: COG URL (e.g. /vsiaz/container/path.tif or https://...)
        depth: Validation depth (metadata, sample, full)

    Returns:
        ValidationReport dict.
    """
    checks = await asyncio.to_thread(_run_checks_sync, url, depth)
    return report(url, "cog", depth, checks)
