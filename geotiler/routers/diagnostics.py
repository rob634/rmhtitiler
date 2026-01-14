"""
Diagnostic endpoints for debugging TiPG and database issues.

Provides detailed diagnostics for:
- PostGIS installation and version
- Schema existence and permissions
- Geometry columns detection
- Table accessibility
- Search path verification
"""

import logging
from typing import Any

from fastapi import APIRouter, Request

from geotiler.config import settings
from geotiler.services.database import get_app_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vector", tags=["Diagnostics"])


async def _run_query(pool, query: str, *args) -> list[dict]:
    """Run a query and return results as list of dicts."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return []


async def _run_query_single(pool, query: str, *args) -> Any:
    """Run a query and return single value."""
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return None


@router.get("/diagnostics")
async def tipg_diagnostics(request: Request):
    """
    Run comprehensive diagnostics for TiPG table discovery.

    Checks:
    - Database connection and current user
    - Search path configuration
    - PostGIS extension status
    - Schema existence and permissions
    - Tables with geometry columns
    - Table-level SELECT permissions

    Use this endpoint to debug why TiPG isn't discovering tables
    in the configured schemas.

    Returns:
        Detailed diagnostic report with issues identified.
    """
    app_state = get_app_state()
    pool = getattr(app_state, "pool", None) if app_state else None

    if not pool:
        return {
            "status": "error",
            "error": "TiPG pool not initialized",
            "hint": "Check application logs for TiPG initialization errors",
        }

    diagnostics = {
        "status": "ok",
        "configured_schemas": settings.tipg_schema_list,
        "expected_geometry_column": settings.ogc_geometry_column,
        "connection": {},
        "postgis": {},
        "schemas": {},
        "issues": [],
    }

    issues = []

    # ==========================================================================
    # CONNECTION INFO
    # ==========================================================================
    try:
        current_user = await _run_query_single(pool, "SELECT current_user")
        search_path = await _run_query_single(pool, "SHOW search_path")
        db_name = await _run_query_single(pool, "SELECT current_database()")

        diagnostics["connection"] = {
            "pool_exists": True,
            "pool_size": pool.get_size(),
            "pool_free": pool.get_idle_size(),
            "current_user": current_user,
            "current_database": db_name,
            "search_path": search_path,
        }
    except Exception as e:
        diagnostics["connection"] = {"error": str(e)}
        issues.append(f"Connection query failed: {e}")

    # ==========================================================================
    # POSTGIS STATUS
    # ==========================================================================
    try:
        postgis_info = await _run_query(
            pool,
            """
            SELECT extname, extversion
            FROM pg_extension
            WHERE extname IN ('postgis', 'postgis_topology', 'postgis_raster')
            """
        )

        if postgis_info:
            postgis_dict = {row["extname"]: row["extversion"] for row in postgis_info}
            diagnostics["postgis"] = {
                "installed": "postgis" in postgis_dict,
                "extensions": postgis_dict,
            }
            if "postgis" not in postgis_dict:
                issues.append("PostGIS extension not installed - geometry columns won't be recognized")
        else:
            diagnostics["postgis"] = {"installed": False, "extensions": {}}
            issues.append("PostGIS extension not installed - run: CREATE EXTENSION postgis;")

    except Exception as e:
        diagnostics["postgis"] = {"error": str(e)}
        issues.append(f"PostGIS check failed: {e}")

    # ==========================================================================
    # SCHEMA DIAGNOSTICS (for each configured schema)
    # ==========================================================================
    for schema in settings.tipg_schema_list:
        schema_diag = await _diagnose_schema(pool, schema, issues)
        diagnostics["schemas"][schema] = schema_diag

    # ==========================================================================
    # COLLECTION CATALOG INFO
    # ==========================================================================
    catalog = getattr(app_state, "collection_catalog", None) if app_state else None
    if catalog:
        diagnostics["tipg_catalog"] = {
            "collections_registered": len(catalog),
            "collection_ids": list(catalog.keys())[:20],  # First 20
        }
        if len(catalog) > 20:
            diagnostics["tipg_catalog"]["note"] = f"Showing first 20 of {len(catalog)} collections"
    else:
        diagnostics["tipg_catalog"] = {"collections_registered": 0}
        if not issues:
            issues.append("TiPG collection catalog is empty - no tables discovered")

    # ==========================================================================
    # FINAL STATUS
    # ==========================================================================
    diagnostics["issues"] = issues if issues else None
    if issues:
        diagnostics["status"] = "issues_found"

    return diagnostics


async def _diagnose_schema(pool, schema: str, issues: list) -> dict:
    """
    Run diagnostics for a specific schema.

    Args:
        pool: asyncpg connection pool
        schema: Schema name to diagnose
        issues: List to append issues to

    Returns:
        Schema diagnostic dict
    """
    schema_diag = {
        "exists": False,
        "has_usage_permission": False,
        "tables_total": 0,
        "tables_with_geometry": 0,
        "tables_accessible": 0,
        "tables": [],
        "all_tables_detail": [],  # Shows ALL tables with their geometry column status
    }

    # Check if schema exists
    schema_exists = await _run_query_single(
        pool,
        "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = $1)",
        schema
    )
    schema_diag["exists"] = schema_exists

    if not schema_exists:
        issues.append(f"Schema '{schema}' does not exist")
        return schema_diag

    # Check USAGE permission on schema
    has_usage = await _run_query_single(
        pool,
        "SELECT has_schema_privilege(current_user, $1, 'USAGE')",
        schema
    )
    schema_diag["has_usage_permission"] = has_usage

    if not has_usage:
        issues.append(f"No USAGE permission on schema '{schema}' - run: GRANT USAGE ON SCHEMA {schema} TO <user>;")
        return schema_diag

    # Count total tables in schema
    table_count = await _run_query_single(
        pool,
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = $1 AND table_type = 'BASE TABLE'
        """,
        schema
    )
    schema_diag["tables_total"] = table_count or 0

    # Get tables with geometry columns from geometry_columns view
    geometry_tables = await _run_query(
        pool,
        """
        SELECT
            f_table_name as table_name,
            f_geometry_column as geometry_column,
            type as geometry_type,
            srid
        FROM geometry_columns
        WHERE f_table_schema = $1
        ORDER BY f_table_name
        """,
        schema
    )

    # If geometry_columns is empty, try direct column check
    if not geometry_tables:
        geometry_tables = await _run_query(
            pool,
            """
            SELECT DISTINCT
                t.table_name,
                c.column_name as geometry_column,
                c.udt_name as geometry_type,
                NULL::integer as srid
            FROM information_schema.tables t
            JOIN information_schema.columns c
                ON c.table_schema = t.table_schema AND c.table_name = t.table_name
            WHERE t.table_schema = $1
              AND t.table_type = 'BASE TABLE'
              AND c.udt_name IN ('geometry', 'geography')
            ORDER BY t.table_name
            """,
            schema
        )

    schema_diag["tables_with_geometry"] = len(geometry_tables)

    if not geometry_tables and table_count and table_count > 0:
        issues.append(
            f"Schema '{schema}' has {table_count} tables but none have geometry columns. "
            "TiPG only discovers tables with geometry/geography columns."
        )

    # Check SELECT permission on each geometry table
    tables_detail = []
    accessible_count = 0

    for table in geometry_tables:
        table_name = table["table_name"]
        can_select = await _run_query_single(
            pool,
            "SELECT has_table_privilege(current_user, $1, 'SELECT')",
            f"{schema}.{table_name}"
        )

        table_info = {
            "name": table_name,
            "geometry_column": table["geometry_column"],
            "geometry_type": table["geometry_type"],
            "srid": table["srid"],
            "can_select": can_select,
        }
        tables_detail.append(table_info)

        if can_select:
            accessible_count += 1
        else:
            issues.append(
                f"No SELECT permission on {schema}.{table_name} - "
                f"run: GRANT SELECT ON {schema}.{table_name} TO <user>;"
            )

    schema_diag["tables_accessible"] = accessible_count
    schema_diag["tables"] = tables_detail

    # Summary issue if tables exist but none accessible
    if geometry_tables and accessible_count == 0:
        issues.append(
            f"Schema '{schema}' has {len(geometry_tables)} geometry tables but none are accessible. "
            "Check SELECT permissions."
        )

    # Get ALL tables with potential geometry column info (for debugging)
    # This shows every table and what columns might be geometry-like
    all_tables = await _run_query(
        pool,
        """
        SELECT
            t.table_name,
            (
                SELECT string_agg(
                    c.column_name || ':' || c.udt_name,
                    ', ' ORDER BY c.ordinal_position
                )
                FROM information_schema.columns c
                WHERE c.table_schema = t.table_schema
                  AND c.table_name = t.table_name
                  AND c.udt_name IN ('geometry', 'geography', 'USER-DEFINED', 'bytea')
            ) as potential_geom_columns,
            (
                SELECT gc.f_geometry_column || ':' || gc.type
                FROM geometry_columns gc
                WHERE gc.f_table_schema = t.table_schema
                  AND gc.f_table_name = t.table_name
                LIMIT 1
            ) as registered_in_geometry_columns
        FROM information_schema.tables t
        WHERE t.table_schema = $1
          AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name
        """,
        schema
    )

    # Build detailed table list with geometry column match status
    expected_col = settings.ogc_geometry_column
    all_tables_detail = []

    for row in all_tables:
        potential = row["potential_geom_columns"]
        registered = row["registered_in_geometry_columns"]

        # Check if expected geometry column is present
        has_expected_col = False
        if potential:
            # potential is like "geom:geometry" or "geometry:geometry, wkb:bytea"
            col_names = [c.split(":")[0] for c in potential.split(", ")]
            has_expected_col = expected_col in col_names

        detail = {
            "table": row["table_name"],
            "potential_geom_columns": potential,
            "in_geometry_columns": registered,
            "has_expected_column": has_expected_col,
        }

        # Flag tables that have geometry but wrong column name
        if potential and not has_expected_col:
            detail["warning"] = f"Has geometry column but not named '{expected_col}'"
            issues.append(
                f"Table '{row['table_name']}' has geometry column ({potential}) "
                f"but not named '{expected_col}' - TiPG may not discover it correctly"
            )

        all_tables_detail.append(detail)

    schema_diag["all_tables_detail"] = all_tables_detail

    return schema_diag
