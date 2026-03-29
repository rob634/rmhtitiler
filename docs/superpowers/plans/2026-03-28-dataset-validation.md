# Dataset Validation Endpoints — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add feature-flagged `/validate/*` endpoints that report data quality for vector, COG, Zarr, and STAC datasets.

**Architecture:** New router at `geotiler/routers/validate.py` delegates to four service modules under `geotiler/services/validate/`. Each service module contains plain async check functions that return standardized `CheckResult` dicts. No classes, no registry. Checks use existing pools and libraries directly, bypassing the serving layer.

**Tech Stack:** asyncpg (vector, STAC), rasterio (COG), xarray (Zarr), httpx (asset HEAD requests). All already installed — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-28-dataset-validation-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `geotiler/services/validate/__init__.py` | Create | Shared types: `CheckResult`, `ValidationReport`, `Depth` enum, helper functions |
| `geotiler/services/validate/vector.py` | Create | Vector (PostGIS) check functions |
| `geotiler/services/validate/cog.py` | Create | COG (GeoTIFF) check functions |
| `geotiler/services/validate/zarr.py` | Create | Zarr/NetCDF check functions |
| `geotiler/services/validate/stac.py` | Create | STAC (pgSTAC) check functions |
| `geotiler/routers/validate.py` | Create | FastAPI router: endpoints, depth gating, response assembly |
| `geotiler/config.py` | Modify | Add `enable_validation` and `enable_validation_full_scan` flags |
| `geotiler/errors.py` | Modify | Add `VALIDATION_DISABLED` and `FULL_SCAN_DISABLED` error codes |
| `geotiler/app.py` | Modify | Conditionally mount validation router |

---

## Task 1: Shared Types & Helpers

**Files:**
- Create: `geotiler/services/validate/__init__.py`

This module defines the data structures every check function and endpoint uses. All other tasks depend on this.

- [ ] **Step 1: Create the validate service package with shared types**

```python
# geotiler/services/validate/__init__.py
"""
Dataset validation service.

Shared types and helpers for validation check functions.
Each submodule (vector, cog, zarr, stac) exports a single async entry point
that returns a ValidationReport.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Depth(str, Enum):
    """Validation depth level."""
    metadata = "metadata"
    sample = "sample"
    full = "full"


class Status(str, Enum):
    """Check result status. Ordered by severity: pass < warn < fail."""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


def check(
    name: str,
    status: Status,
    message: str,
    details: Optional[dict[str, Any]] = None,
) -> dict:
    """Build a single check result dict."""
    result = {"name": name, "status": status.value, "message": message}
    if details is not None:
        result["details"] = details
    return result


def report(
    target: str,
    target_type: str,
    depth: Depth,
    checks: list[dict],
) -> dict:
    """Build a validation report from a list of check results."""
    # Overall status is the worst of all checks
    severity = {Status.PASS.value: 0, Status.WARN.value: 1, Status.FAIL.value: 2}
    worst = max(checks, key=lambda c: severity.get(c["status"], 0)) if checks else None
    overall = worst["status"] if worst else Status.PASS.value

    # Summary counts
    counts = {Status.PASS.value: 0, Status.WARN.value: 0, Status.FAIL.value: 0}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1

    total = len(checks)
    parts = []
    if counts["fail"]:
        parts.append(f"{counts['fail']} fail")
    if counts["warn"]:
        parts.append(f"{counts['warn']} warn")
    if counts["pass"]:
        parts.append(f"{counts['pass']} pass")
    summary = f"{total} checks: {', '.join(parts)}"

    return {
        "target": target,
        "target_type": target_type,
        "depth": depth.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "summary": summary,
        "checks": checks,
    }
```

- [ ] **Step 2: Verify the file is importable**

Run: `cd /Users/robertharrison/python_builds/rmhtitiler && python -c "from geotiler.services.validate import Depth, Status, check, report; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add geotiler/services/validate/__init__.py
git commit -m "feat(validate): add shared types for validation service"
```

---

## Task 2: Vector Validator

**Files:**
- Create: `geotiler/services/validate/vector.py`

**Dependencies:** Task 1 (shared types)

**Key patterns:**
- Access TiPG catalog via `app.state.collection_catalog`
- Access TiPG pool via `app.state.pool`
- Use `_validate_identifier()` regex from `geotiler/services/vector_query.py` for SQL safety
- Parameterized queries with `$1` for values, double-quoted identifiers for schema/table

- [ ] **Step 1: Create vector.py with all check functions**

```python
# geotiler/services/validate/vector.py
"""
Vector (PostGIS) dataset validation checks.

Uses TiPG catalog for existence checks and raw asyncpg queries
on the TiPG pool (app.state.pool) for data quality checks.
"""

import logging
import re

from fastapi import FastAPI

from geotiler.services.validate import Depth, Status, check, report

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str, label: str) -> None:
    """Validate a SQL identifier to prevent injection."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid {label}: '{name}' — must match [a-zA-Z_][a-zA-Z0-9_]*")


def _parse_collection_id(collection_id: str) -> tuple[str, str]:
    """Parse 'schema.table' into (schema, table). Validates both identifiers."""
    if "." in collection_id:
        schema, table = collection_id.split(".", 1)
    else:
        schema, table = "public", collection_id
    _validate_identifier(schema, "schema")
    _validate_identifier(table, "table")
    return schema, table


def _check_table_exists(catalog, collection_id: str) -> dict:
    """Check if collection exists in TiPG catalog."""
    if catalog is None:
        return check("table_exists", Status.FAIL, "TiPG catalog not initialized")
    # TiPG catalog keys may be "schema.table" or just "table"
    found = collection_id in catalog
    if not found:
        return check("table_exists", Status.FAIL, f"Collection '{collection_id}' not found in TiPG catalog")
    return check("table_exists", Status.PASS, f"Collection '{collection_id}' found in catalog")


def _check_geometry_column(catalog, collection_id: str) -> dict:
    """Check if the catalog entry has geometry type and SRID."""
    entry = catalog.get(collection_id)
    if entry is None:
        return check("geometry_column", Status.FAIL, "Collection not in catalog")
    # TiPG Collection objects have a 'geometry_columns' or geometry info
    # Access the geometry type from the collection's properties
    geom_type = getattr(entry, "geometry_type", None)
    if geom_type is None:
        # Try alternate attribute paths used by different TiPG versions
        columns = getattr(entry, "properties", [])
        has_geom = any(
            getattr(col, "type", "").startswith("geometry") or getattr(col, "name", "") == "geom"
            for col in columns
        ) if columns else False
        if not has_geom:
            return check("geometry_column", Status.WARN, "Could not confirm geometry column from catalog metadata")
        return check("geometry_column", Status.PASS, "Geometry column found in catalog properties")
    return check("geometry_column", Status.PASS, f"Geometry type: {geom_type}")


def _check_primary_key(catalog, collection_id: str) -> dict:
    """Check if TiPG catalog entry has a primary key (required for TiPG)."""
    entry = catalog.get(collection_id)
    if entry is None:
        return check("primary_key", Status.FAIL, "Collection not in catalog")
    pk = getattr(entry, "id_column", None) or getattr(entry, "pk", None)
    if pk:
        return check("primary_key", Status.PASS, f"Primary key: {pk}")
    return check("primary_key", Status.WARN, "No primary key detected in catalog — TiPG may fail on item queries")


async def _check_permissions(pool, schema: str, table: str) -> dict:
    """Check if the current database role has SELECT on the table."""
    try:
        async with pool.acquire() as conn:
            has_priv = await conn.fetchval(
                "SELECT has_table_privilege(current_user, $1, 'SELECT')",
                f"{schema}.{table}",
            )
        if has_priv:
            return check("permissions", Status.PASS, f"SELECT granted on {schema}.{table}")
        return check("permissions", Status.FAIL, f"No SELECT privilege on {schema}.{table}")
    except Exception as e:
        return check("permissions", Status.FAIL, f"Permission check failed: {e}")


async def _check_row_count(pool, schema: str, table: str, depth: Depth) -> dict:
    """Check row count. Sample uses pg_class estimate, full uses exact count."""
    try:
        async with pool.acquire() as conn:
            if depth == Depth.full:
                count = await conn.fetchval(
                    f'SELECT count(*) FROM "{schema}"."{table}"'
                )
            else:
                # Fast estimate from pg_class
                count = await conn.fetchval(
                    "SELECT reltuples::bigint FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = $1 AND c.relname = $2",
                    schema, table,
                )
        if count is None or count == 0:
            return check("row_count", Status.WARN, "Table appears empty", {"count": 0, "exact": depth == Depth.full})
        return check("row_count", Status.PASS, f"{count:,} rows", {"count": count, "exact": depth == Depth.full})
    except Exception as e:
        return check("row_count", Status.FAIL, f"Row count failed: {e}")


async def _check_srid_consistent(pool, schema: str, table: str, geom_col: str, depth: Depth) -> dict:
    """Check that all geometries use a consistent SRID."""
    try:
        async with pool.acquire() as conn:
            if depth == Depth.full:
                rows = await conn.fetch(
                    f'SELECT DISTINCT ST_SRID("{geom_col}") as srid FROM "{schema}"."{table}" '
                    f'WHERE "{geom_col}" IS NOT NULL'
                )
            else:
                rows = await conn.fetch(
                    f'SELECT DISTINCT ST_SRID("{geom_col}") as srid FROM "{schema}"."{table}" '
                    f'WHERE "{geom_col}" IS NOT NULL LIMIT 10'
                )
        srids = [r["srid"] for r in rows]
        if len(srids) == 0:
            return check("srid_consistent", Status.WARN, "No non-null geometries to check SRID")
        if len(srids) == 1:
            return check("srid_consistent", Status.PASS, f"Consistent SRID: {srids[0]}", {"srid": srids[0]})
        return check("srid_consistent", Status.FAIL, f"Mixed SRIDs: {srids}", {"srids": srids})
    except Exception as e:
        return check("srid_consistent", Status.FAIL, f"SRID check failed: {e}")


async def _check_geometry_not_null(pool, schema: str, table: str, geom_col: str, depth: Depth) -> dict:
    """Check for NULL geometries."""
    try:
        async with pool.acquire() as conn:
            if depth == Depth.full:
                row = await conn.fetchrow(
                    f'SELECT count(*) as total, '
                    f'count(*) FILTER (WHERE "{geom_col}" IS NULL) as null_count '
                    f'FROM "{schema}"."{table}"'
                )
            else:
                row = await conn.fetchrow(
                    f'SELECT count(*) as total, '
                    f'count(*) FILTER (WHERE "{geom_col}" IS NULL) as null_count '
                    f'FROM (SELECT "{geom_col}" FROM "{schema}"."{table}" LIMIT 100) sub'
                )
        total = row["total"]
        nulls = row["null_count"]
        if nulls == 0:
            scope = f"all {total:,} rows" if depth == Depth.full else f"{total} sampled rows"
            return check("geometry_not_null", Status.PASS, f"No NULL geometries in {scope}")
        pct = (nulls / total * 100) if total > 0 else 0
        return check(
            "geometry_not_null", Status.WARN,
            f"{nulls:,} of {total:,} geometries are NULL ({pct:.1f}%)",
            {"total": total, "null_count": nulls, "pct": round(pct, 1)},
        )
    except Exception as e:
        return check("geometry_not_null", Status.FAIL, f"NULL geometry check failed: {e}")


async def _check_geometry_valid(pool, schema: str, table: str, geom_col: str, depth: Depth) -> dict:
    """Check geometry validity with ST_IsValid()."""
    try:
        async with pool.acquire() as conn:
            if depth == Depth.full:
                row = await conn.fetchrow(
                    f'SELECT count(*) as total, '
                    f'count(*) FILTER (WHERE NOT ST_IsValid("{geom_col}")) as invalid_count '
                    f'FROM "{schema}"."{table}" WHERE "{geom_col}" IS NOT NULL'
                )
            else:
                row = await conn.fetchrow(
                    f'SELECT count(*) as total, '
                    f'count(*) FILTER (WHERE NOT ST_IsValid("{geom_col}")) as invalid_count '
                    f'FROM (SELECT "{geom_col}" FROM "{schema}"."{table}" WHERE "{geom_col}" IS NOT NULL LIMIT 100) sub'
                )
        total = row["total"]
        invalid = row["invalid_count"]
        if invalid == 0:
            scope = f"all {total:,} rows" if depth == Depth.full else f"{total} sampled rows"
            return check("geometry_valid", Status.PASS, f"All geometries valid in {scope}")
        pct = (invalid / total * 100) if total > 0 else 0
        return check(
            "geometry_valid", Status.WARN,
            f"{invalid:,} of {total:,} geometries invalid ({pct:.1f}%)",
            {"total": total, "invalid_count": invalid, "pct": round(pct, 1)},
        )
    except Exception as e:
        return check("geometry_valid", Status.FAIL, f"Geometry validity check failed: {e}")


async def validate_vector(collection_id: str, depth: Depth, app: FastAPI) -> dict:
    """
    Validate a vector (PostGIS) collection.

    Args:
        collection_id: Collection identifier, e.g. "geo.floods_jakarta_2024"
        depth: Validation depth (metadata, sample, full)
        app: FastAPI application instance (for app.state access)

    Returns:
        ValidationReport dict with check results.
    """
    catalog = getattr(app.state, "collection_catalog", None)
    pool = getattr(app.state, "pool", None)

    checks = []

    # --- Metadata checks (always run) ---
    checks.append(_check_table_exists(catalog, collection_id))
    checks.append(_check_geometry_column(catalog, collection_id))
    checks.append(_check_primary_key(catalog, collection_id))

    # Parse schema.table for SQL queries
    try:
        schema, table = _parse_collection_id(collection_id)
    except ValueError as e:
        checks.append(check("identifier", Status.FAIL, str(e)))
        return report(collection_id, "vector", depth, checks)

    if pool is None:
        checks.append(check("permissions", Status.FAIL, "TiPG database pool not initialized"))
        return report(collection_id, "vector", depth, checks)

    checks.append(await _check_permissions(pool, schema, table))

    # --- Sample/Full checks (require database queries) ---
    if depth in (Depth.sample, Depth.full):
        geom_col = getattr(
            catalog.get(collection_id), "geometry_column",
            None,
        ) or "geom"
        # Validate geom column name too
        if not _IDENTIFIER_RE.match(geom_col):
            geom_col = "geom"

        checks.append(await _check_row_count(pool, schema, table, depth))
        checks.append(await _check_srid_consistent(pool, schema, table, geom_col, depth))
        checks.append(await _check_geometry_not_null(pool, schema, table, geom_col, depth))
        checks.append(await _check_geometry_valid(pool, schema, table, geom_col, depth))

    return report(collection_id, "vector", depth, checks)
```

- [ ] **Step 2: Verify the file is importable**

Run: `cd /Users/robertharrison/python_builds/rmhtitiler && python -c "from geotiler.services.validate.vector import validate_vector; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add geotiler/services/validate/vector.py
git commit -m "feat(validate): add vector PostGIS validation checks"
```

---

## Task 3: COG Validator

**Files:**
- Create: `geotiler/services/validate/cog.py`

**Dependencies:** Task 1 (shared types)

**Key patterns:**
- `rasterio.open()` is synchronous — wrap in `asyncio.to_thread()`
- GDAL env/auth is already configured globally by `initialize_storage_auth()` at startup
- Header reads happen via HTTP range requests — cheap, no full download

- [ ] **Step 1: Create cog.py with all check functions**

```python
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
```

- [ ] **Step 2: Verify the file is importable**

Run: `cd /Users/robertharrison/python_builds/rmhtitiler && python -c "from geotiler.services.validate.cog import validate_cog; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add geotiler/services/validate/cog.py
git commit -m "feat(validate): add COG GeoTIFF validation checks"
```

---

## Task 4: Zarr Validator

**Files:**
- Create: `geotiler/services/validate/zarr.py`

**Dependencies:** Task 1 (shared types)

**Key patterns:**
- `xarray.open_zarr()` is synchronous — wrap in `asyncio.to_thread()`
- Auth for `abfs://` is handled by environment variables set by `initialize_storage_auth()`
- Metadata reads are lazy — no data loaded until `.values` is called

- [ ] **Step 1: Create zarr.py with all check functions**

```python
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
```

- [ ] **Step 2: Verify the file is importable**

Run: `cd /Users/robertharrison/python_builds/rmhtitiler && python -c "from geotiler.services.validate.zarr import validate_zarr; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add geotiler/services/validate/zarr.py
git commit -m "feat(validate): add Zarr/NetCDF validation checks"
```

---

## Task 5: STAC Validator

**Files:**
- Create: `geotiler/services/validate/stac.py`

**Dependencies:** Task 1 (shared types)

**Key patterns:**
- Use STAC read pool (`app.state.readpool`) with raw asyncpg
- pgSTAC stores items as JSONB in `pgstac.items` with `content` column
- For `asset_accessible` full-depth check, use `httpx` for HEAD requests

- [ ] **Step 1: Create stac.py with all check functions**

```python
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
```

- [ ] **Step 2: Verify the file is importable**

Run: `cd /Users/robertharrison/python_builds/rmhtitiler && python -c "from geotiler.services.validate.stac import validate_stac; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add geotiler/services/validate/stac.py
git commit -m "feat(validate): add STAC pgSTAC validation checks"
```

---

## Task 6: Config + Error Codes + Router + App Wiring

**Files:**
- Modify: `geotiler/config.py` (add 2 fields)
- Modify: `geotiler/errors.py` (add 2 constants)
- Create: `geotiler/routers/validate.py`
- Modify: `geotiler/app.py` (mount router)

**Dependencies:** Tasks 1-5 (all validators must exist)

- [ ] **Step 1: Add feature flags to config.py**

Add after the `enable_diagnostics` field (around line 141):

```python
    enable_validation: bool = False
    """Enable dataset validation endpoints at /validate/*.
    Provides data quality checks for vector, COG, Zarr, and STAC datasets."""

    enable_validation_full_scan: bool = False
    """Allow depth=full on validation endpoints (expensive full-table scans).
    Only enable on internal instances — external instances should leave this false."""
```

- [ ] **Step 2: Add error codes to errors.py**

Add after the `POOL_NOT_INITIALIZED` constant (line 35):

```python
VALIDATION_DISABLED = "VALIDATION_DISABLED"
FULL_SCAN_DISABLED = "FULL_SCAN_DISABLED"
```

- [ ] **Step 3: Create the validation router**

```python
# geotiler/routers/validate.py
"""
Dataset validation endpoints.

Provides per-data-type validation and a batch /validate/all endpoint.
Feature-flagged via GEOTILER_ENABLE_VALIDATION.

See docs/superpowers/specs/2026-03-28-dataset-validation-design.md for spec.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request

from geotiler.config import settings
from geotiler.errors import error_response, FULL_SCAN_DISABLED, NOT_FOUND, SERVICE_UNAVAILABLE
from geotiler.services.validate import Depth, report

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
            import json
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
```

- [ ] **Step 4: Mount the router in app.py**

Add after the downloads block (around line 436) and before the admin block:

```python
    # Validation endpoints (data quality checks)
    if settings.enable_validation:
        from geotiler.routers import validate
        app.include_router(validate.router, tags=["Validation"])
        logger.info("Validation router mounted at /validate")
```

- [ ] **Step 5: Verify the app still starts (import check)**

Run: `cd /Users/robertharrison/python_builds/rmhtitiler && python -c "from geotiler.routers.validate import router; print(f'{len(router.routes)} routes'); from geotiler.config import settings; print(f'enable_validation={settings.enable_validation}')"`
Expected: `5 routes` and `enable_validation=False`

- [ ] **Step 6: Commit**

```bash
git add geotiler/config.py geotiler/errors.py geotiler/routers/validate.py geotiler/app.py
git commit -m "feat(validate): add validation router with feature-flag gating

Mounts /validate/* endpoints behind GEOTILER_ENABLE_VALIDATION flag.
Full scan depth gated separately by GEOTILER_ENABLE_VALIDATION_FULL_SCAN."
```

---

## Task 7: Update CLAUDE.md and Docs

**Files:**
- Modify: `CLAUDE.md` (add validation endpoints to Key Endpoints and env vars tables)

- [ ] **Step 1: Add validation endpoints to CLAUDE.md Key Endpoints section**

In the Key endpoints list, add:

```
- `GET /validate/vector/{collection}` - Vector dataset quality check
- `GET /validate/cog?url=...` - COG dataset quality check
- `GET /validate/zarr?url=...&variable=...` - Zarr dataset quality check
- `GET /validate/stac/{collection}` - STAC collection quality check
- `GET /validate/all` - Validate all registered datasets
```

- [ ] **Step 2: Add env vars to CLAUDE.md env var table**

Add to the Environment Variables table:

```
| `GEOTILER_ENABLE_VALIDATION` | Enable dataset validation endpoints at /validate/* (default: false) |
| `GEOTILER_ENABLE_VALIDATION_FULL_SCAN` | Allow expensive full-scan validation depth (default: false) |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add validation endpoints and config to CLAUDE.md"
```
