# geotiler/services/validate/zarr.py
"""
Zarr/NetCDF dataset validation checks.

Uses xarray directly with the existing fsspec/obstore auth.
All xarray calls are synchronous and wrapped in asyncio.to_thread().
"""

import asyncio
import logging

import xarray as xr

from geotiler.services.validate import Depth, Status, check, report

logger = logging.getLogger(__name__)

# Known spatial dimension names across common conventions
_SPATIAL_X = {"x", "lon", "longitude"}
_SPATIAL_Y = {"y", "lat", "latitude"}


def _run_checks_sync(url: str, variable: str, depth: Depth) -> list[dict]:
    """Run all Zarr checks synchronously. Called via asyncio.to_thread()."""
    checks = []

    # --- accessible: can we open the store? ---
    try:
        ds = xr.open_zarr(url, consolidated=True)
    except Exception:
        try:
            ds = xr.open_zarr(url, consolidated=False)
        except Exception as e:
            checks.append(check("accessible", Status.FAIL, f"Cannot open Zarr store: {e}"))
            return checks

    try:
        checks.append(check(
            "accessible", Status.PASS,
            f"Opened successfully ({len(ds.data_vars)} variables, {len(ds.dims)} dimensions)",
            {"variables": list(ds.data_vars), "dimensions": dict(ds.dims)},
        ))

        # --- variable_exists ---
        if variable in ds.data_vars:
            var = ds[variable]
            checks.append(check(
                "variable_exists", Status.PASS,
                f"Variable '{variable}' found: shape {var.shape}, dtype {var.dtype}",
                {"shape": list(var.shape), "dtype": str(var.dtype), "dims": list(var.dims)},
            ))
        else:
            available = list(ds.data_vars)
            checks.append(check(
                "variable_exists", Status.FAIL,
                f"Variable '{variable}' not found. Available: {available}",
                {"available": available},
            ))
            return checks  # Can't run further checks without the variable

        if depth in (Depth.sample, Depth.full):
            # --- crs_defined ---
            crs_found = False
            grid_mapping = var.attrs.get("grid_mapping")
            if grid_mapping and grid_mapping in ds:
                crs_found = True
                gm_attrs = dict(ds[grid_mapping].attrs)
                checks.append(check("crs_defined", Status.PASS, f"CRS via grid_mapping '{grid_mapping}'", gm_attrs))
            elif "crs" in ds.attrs:
                crs_found = True
                checks.append(check("crs_defined", Status.PASS, f"CRS in dataset attrs: {ds.attrs['crs']}"))
            elif "crs" in var.attrs:
                crs_found = True
                checks.append(check("crs_defined", Status.PASS, f"CRS in variable attrs: {var.attrs['crs']}"))
            if not crs_found:
                checks.append(check("crs_defined", Status.WARN, "No CRS found in grid_mapping or attrs"))

            # --- dimensions ---
            dim_names = set(var.dims)
            has_x = bool(dim_names & _SPATIAL_X)
            has_y = bool(dim_names & _SPATIAL_Y)
            if has_x and has_y:
                x_name = (dim_names & _SPATIAL_X).pop()
                y_name = (dim_names & _SPATIAL_Y).pop()
                checks.append(check(
                    "dimensions", Status.PASS,
                    f"Spatial dims: {y_name}={ds.dims[y_name]}, {x_name}={ds.dims[x_name]}",
                ))
            else:
                missing = []
                if not has_x:
                    missing.append("x/lon/longitude")
                if not has_y:
                    missing.append("y/lat/latitude")
                checks.append(check(
                    "dimensions", Status.WARN,
                    f"Missing spatial dimensions: {', '.join(missing)}. Dims present: {list(var.dims)}",
                ))

            # --- chunk_structure ---
            encoding_chunks = var.encoding.get("chunks")
            if encoding_chunks:
                checks.append(check(
                    "chunk_structure", Status.PASS,
                    f"Chunks: {encoding_chunks}",
                    {"chunks": list(encoding_chunks)},
                ))
            else:
                checks.append(check(
                    "chunk_structure", Status.WARN,
                    "No chunk encoding found — data may not be chunked for efficient access",
                ))

            # --- time_dim_indexed ---
            time_dims = dim_names & {"time", "t"}
            if time_dims:
                time_name = time_dims.pop()
                time_len = ds.dims[time_name]
                if time_len > 0:
                    checks.append(check(
                        "time_dim_indexed", Status.PASS,
                        f"Time dimension '{time_name}' has {time_len} steps",
                        {"time_dim": time_name, "steps": time_len},
                    ))
                else:
                    checks.append(check("time_dim_indexed", Status.WARN, f"Time dimension '{time_name}' is empty"))
            # If no time dim, skip this check silently — not all datasets are temporal

        if depth == Depth.full:
            # --- readable_slice: read one spatial element ---
            try:
                # Build isel kwargs for the first element of each dim
                isel_kwargs = {}
                for dim in var.dims:
                    isel_kwargs[dim] = 0
                val = var.isel(**isel_kwargs).values
                checks.append(check(
                    "readable_slice", Status.PASS,
                    f"Read single value successfully: {val}",
                ))
            except Exception as e:
                checks.append(check("readable_slice", Status.FAIL, f"Failed to read data slice: {e}"))

    finally:
        ds.close()

    return checks


async def validate_zarr(url: str, variable: str, depth: Depth) -> dict:
    """
    Validate a Zarr/NetCDF dataset.

    Args:
        url: Zarr store URL (e.g. abfs://container/path.zarr)
        variable: Data variable name to validate
        depth: Validation depth (metadata, sample, full)

    Returns:
        ValidationReport dict.
    """
    checks = await asyncio.to_thread(_run_checks_sync, url, variable, depth)
    return report(url, "zarr", depth, checks)
