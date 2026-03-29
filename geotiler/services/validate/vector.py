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
