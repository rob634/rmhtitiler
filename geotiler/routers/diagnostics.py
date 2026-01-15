"""
Diagnostic endpoints for debugging TiPG and database issues.

Provides detailed diagnostics for:
- PostGIS installation and version
- Schema existence and permissions
- Geometry columns detection
- Table accessibility
- Search path verification
- Primary key detection
- Column definitions
- Row counts

Verbose mode mirrors rmhgeoapi health.py queries for direct comparison.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request, Query

from geotiler.config import settings
from geotiler.services.database import get_app_state
from geotiler.routers.vector import get_tipg_startup_state

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

    # Get startup state
    startup_state = get_tipg_startup_state()

    diagnostics = {
        "status": "ok",
        "configured_schemas": settings.tipg_schema_list,
        "expected_geometry_column": settings.ogc_geometry_column,
        "startup": startup_state.to_dict(),
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
    # GLOBAL GEOMETRY_COLUMNS VIEW (all schemas)
    # ==========================================================================
    try:
        all_geometry_columns = await _run_query(
            pool,
            """
            SELECT
                f_table_schema as schema,
                f_table_name as table_name,
                f_geometry_column as geometry_column,
                type as geometry_type,
                srid
            FROM public.geometry_columns
            ORDER BY f_table_schema, f_table_name
            LIMIT 100
            """
        )
        diagnostics["all_geometry_columns"] = all_geometry_columns
        diagnostics["all_geometry_columns_count"] = len(all_geometry_columns)
    except Exception as e:
        diagnostics["all_geometry_columns"] = {"error": str(e)}

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
        "views_total": 0,
        "tables_with_geometry": 0,
        "tables_accessible": 0,
        "tables": [],
        "all_tables_detail": [],  # Shows ALL tables with their geometry column status
        "raw_geometry_columns": [],  # Direct query to geometry_columns view
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

    # Count views in schema
    view_count = await _run_query_single(
        pool,
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = $1 AND table_type = 'VIEW'
        """,
        schema
    )
    schema_diag["views_total"] = view_count or 0

    # Raw query to geometry_columns - shows exactly what PostGIS sees
    raw_geom_cols = await _run_query(
        pool,
        """
        SELECT
            f_table_schema as schema,
            f_table_name as table_name,
            f_geometry_column as geometry_column,
            type as geometry_type,
            srid
        FROM public.geometry_columns
        WHERE f_table_schema = $1
        ORDER BY f_table_name
        """,
        schema
    )
    schema_diag["raw_geometry_columns"] = raw_geom_cols

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

    # Get ALL tables AND views with potential geometry column info (for debugging)
    # This shows every table/view and what columns might be geometry-like
    all_tables = await _run_query(
        pool,
        """
        SELECT
            t.table_name,
            t.table_type,
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
                FROM public.geometry_columns gc
                WHERE gc.f_table_schema = t.table_schema
                  AND gc.f_table_name = t.table_name
                LIMIT 1
            ) as registered_in_geometry_columns
        FROM information_schema.tables t
        WHERE t.table_schema = $1
          AND t.table_type IN ('BASE TABLE', 'VIEW')
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
            "type": row["table_type"],  # BASE TABLE or VIEW
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


@router.get("/diagnostics/verbose")
async def verbose_diagnostics(
    request: Request,
    schema: str = Query(default="geo", description="Schema to diagnose"),
    include_columns: bool = Query(default=True, description="Include column definitions"),
    include_row_counts: bool = Query(default=True, description="Include row counts from pg_stat"),
):
    """
    Verbose database diagnostics - mirrors rmhgeoapi health.py queries.

    This endpoint provides maximum visibility into the database state,
    useful for debugging QA environments where direct DB access is limited.

    Queries performed (matching rmhgeoapi):
    - information_schema.tables (all tables in schema)
    - pg_stat_user_tables (row counts)
    - geometry_columns (PostGIS geometry registration)
    - pg_catalog queries for column definitions
    - Primary key detection
    - Constraint information

    Args:
        schema: Schema to diagnose (default: geo)
        include_columns: Include full column definitions for each table
        include_row_counts: Include approximate row counts from pg_stat

    Returns:
        Comprehensive database state for comparison with rmhgeoapi.
    """
    app_state = get_app_state()
    pool = getattr(app_state, "pool", None) if app_state else None

    if not pool:
        return {
            "status": "error",
            "error": "Database pool not initialized",
        }

    result = {
        "status": "ok",
        "schema": schema,
        "connection": {},
        "schema_info": {},
        "tables": {},
        "geometry_columns_raw": [],
        "geometry_columns_count": 0,
        "comparison_queries": {},
    }

    # ==========================================================================
    # CONNECTION INFO (same as rmhgeoapi)
    # ==========================================================================
    try:
        result["connection"] = {
            "current_user": await _run_query_single(pool, "SELECT current_user"),
            "current_database": await _run_query_single(pool, "SELECT current_database()"),
            "search_path": await _run_query_single(pool, "SHOW search_path"),
            "server_version": await _run_query_single(pool, "SHOW server_version"),
            "postgis_version": await _run_query_single(pool, "SELECT PostGIS_Version()"),
        }
    except Exception as e:
        result["connection"] = {"error": str(e)}

    # ==========================================================================
    # SCHEMA EXISTS CHECK (rmhgeoapi style - pg_namespace)
    # ==========================================================================
    schema_exists = await _run_query_single(
        pool,
        "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = $1)",
        schema
    )
    result["schema_info"]["exists"] = schema_exists

    if not schema_exists:
        result["status"] = "error"
        result["error"] = f"Schema '{schema}' does not exist"
        return result

    # ==========================================================================
    # ALL TABLES IN SCHEMA (rmhgeoapi: information_schema.tables)
    # ==========================================================================
    all_tables = await _run_query(
        pool,
        """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = $1
        AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        schema
    )
    result["schema_info"]["tables"] = [t["table_name"] for t in all_tables]
    result["schema_info"]["table_count"] = len(all_tables)

    # ==========================================================================
    # ROW COUNTS (rmhgeoapi: pg_stat_user_tables)
    # ==========================================================================
    if include_row_counts:
        row_counts = await _run_query(
            pool,
            """
            SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
            FROM pg_stat_user_tables
            WHERE schemaname = $1
            ORDER BY relname
            """,
            schema
        )
        result["schema_info"]["row_counts"] = {
            r["relname"]: {
                "live_rows": r["n_live_tup"],
                "dead_rows": r["n_dead_tup"],
                "last_vacuum": str(r["last_vacuum"]) if r["last_vacuum"] else None,
            }
            for r in row_counts
        }

    # ==========================================================================
    # GEOMETRY_COLUMNS - THE KEY QUERY (rmhgeoapi style)
    # This is the exact query rmhgeoapi uses to discover tables
    # ==========================================================================
    geometry_columns = await _run_query(
        pool,
        """
        SELECT
            f_table_name as id,
            f_geometry_column as geometry_column,
            type as geometry_type,
            srid,
            f_table_schema as schema
        FROM geometry_columns
        WHERE f_table_schema = $1
        ORDER BY f_table_name
        """,
        schema
    )
    result["geometry_columns_raw"] = geometry_columns
    result["geometry_columns_count"] = len(geometry_columns)

    # ==========================================================================
    # DETAILED TABLE INFO WITH PRIMARY KEYS AND COLUMNS
    # ==========================================================================
    for table_row in all_tables:
        table_name = table_row["table_name"]
        table_info = {
            "exists": True,
            "type": table_row["table_type"],
        }

        # Check if in geometry_columns
        geom_entry = next(
            (g for g in geometry_columns if g["id"] == table_name),
            None
        )
        table_info["in_geometry_columns"] = geom_entry is not None
        if geom_entry:
            table_info["geometry_column"] = geom_entry["geometry_column"]
            table_info["geometry_type"] = geom_entry["geometry_type"]
            table_info["srid"] = geom_entry["srid"]

        # Get primary key
        pk_info = await _run_query(
            pool,
            """
            SELECT a.attname as column_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = $1::regclass
            AND i.indisprimary
            """,
            f"{schema}.{table_name}"
        )
        table_info["primary_key"] = [p["column_name"] for p in pk_info] if pk_info else None
        table_info["has_primary_key"] = len(pk_info) > 0

        # Get columns (if requested)
        if include_columns:
            columns = await _run_query(
                pool,
                """
                SELECT
                    column_name,
                    data_type,
                    udt_name,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
                """,
                schema, table_name
            )
            table_info["columns"] = columns

            # Check for geometry-like columns
            geom_cols = [c for c in columns if c["udt_name"] in ("geometry", "geography")]
            table_info["geometry_columns_found"] = [
                {"name": c["column_name"], "type": c["udt_name"]}
                for c in geom_cols
            ]

        # Check SELECT permission
        can_select = await _run_query_single(
            pool,
            "SELECT has_table_privilege(current_user, $1, 'SELECT')",
            f"{schema}.{table_name}"
        )
        table_info["can_select"] = can_select

        result["tables"][table_name] = table_info

    # ==========================================================================
    # COMPARISON QUERIES - Run the EXACT queries for debugging
    # ==========================================================================

    # Query 1: Direct geometry_columns (no schema filter)
    all_geom = await _run_query(
        pool,
        """
        SELECT f_table_schema, f_table_name, f_geometry_column, type, srid
        FROM geometry_columns
        ORDER BY f_table_schema, f_table_name
        LIMIT 50
        """
    )
    result["comparison_queries"]["geometry_columns_all_schemas"] = all_geom

    # Query 2: Check pg_type for geometry type
    geom_type = await _run_query(
        pool,
        """
        SELECT typname, typnamespace::regnamespace as schema
        FROM pg_type
        WHERE typname IN ('geometry', 'geography')
        """
    )
    result["comparison_queries"]["geometry_types_registered"] = geom_type

    # Query 3: Check if geometry_columns is a view or table
    geom_view_check = await _run_query(
        pool,
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_name = 'geometry_columns'
        """
    )
    result["comparison_queries"]["geometry_columns_object_type"] = geom_view_check

    # Query 4: Raw pg_attribute check for geometry columns
    raw_geom_attrs = await _run_query(
        pool,
        """
        SELECT
            c.relname as table_name,
            a.attname as column_name,
            t.typname as type_name,
            n.nspname as type_schema
        FROM pg_class c
        JOIN pg_namespace ns ON c.relnamespace = ns.oid
        JOIN pg_attribute a ON a.attrelid = c.oid
        JOIN pg_type t ON a.atttypid = t.oid
        JOIN pg_namespace n ON t.typnamespace = n.oid
        WHERE ns.nspname = $1
        AND c.relkind = 'r'
        AND a.attnum > 0
        AND NOT a.attisdropped
        AND t.typname IN ('geometry', 'geography')
        ORDER BY c.relname, a.attname
        """,
        schema
    )
    result["comparison_queries"]["pg_attribute_geometry_columns"] = raw_geom_attrs

    # Query 5: Check constraints on geometry columns
    geom_constraints = await _run_query(
        pool,
        """
        SELECT
            tc.table_name,
            tc.constraint_name,
            tc.constraint_type,
            cc.check_clause
        FROM information_schema.table_constraints tc
        LEFT JOIN information_schema.check_constraints cc
            ON tc.constraint_name = cc.constraint_name
        WHERE tc.table_schema = $1
        AND (tc.constraint_type = 'CHECK' OR tc.constraint_type = 'PRIMARY KEY')
        ORDER BY tc.table_name, tc.constraint_type
        LIMIT 100
        """,
        schema
    )
    result["comparison_queries"]["table_constraints"] = geom_constraints

    # ==========================================================================
    # SUMMARY
    # ==========================================================================
    tables_with_geom_cols = sum(
        1 for t in result["tables"].values()
        if t.get("geometry_columns_found")
    )
    tables_in_geom_view = sum(
        1 for t in result["tables"].values()
        if t.get("in_geometry_columns")
    )
    tables_with_pk = sum(
        1 for t in result["tables"].values()
        if t.get("has_primary_key")
    )

    result["summary"] = {
        "total_tables": len(all_tables),
        "tables_with_geometry_column": tables_with_geom_cols,
        "tables_in_geometry_columns_view": tables_in_geom_view,
        "tables_with_primary_key": tables_with_pk,
        "geometry_columns_view_count": len(geometry_columns),
        "discrepancy": tables_with_geom_cols != tables_in_geom_view,
    }

    if result["summary"]["discrepancy"]:
        result["summary"]["discrepancy_note"] = (
            f"Found {tables_with_geom_cols} tables with geometry columns in pg_attribute, "
            f"but only {tables_in_geom_view} in geometry_columns view. "
            "Tables may not be properly registered with PostGIS."
        )

    # ==========================================================================
    # PERMISSION DIAGNOSTICS - Check what user can actually see
    # ==========================================================================
    try:
        # Tables visible via information_schema (requires SELECT privilege)
        visible_tables = await _run_query(
            pool,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = $1 AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            schema
        )

        # All tables in pg_class (system catalog, no privilege filter)
        all_pg_tables = await _run_query(
            pool,
            """
            SELECT c.relname as table_name
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = $1 AND c.relkind = 'r'
            ORDER BY c.relname
            """,
            schema
        )

        # Check SELECT privilege on each table
        permission_check = []
        for t in all_pg_tables:
            table_name = t["table_name"]
            has_select = await _run_query_single(
                pool,
                "SELECT has_table_privilege(current_user, $1, 'SELECT')",
                f"{schema}.{table_name}"
            )
            permission_check.append({
                "table": table_name,
                "has_select": has_select,
                "visible_in_info_schema": table_name in [v["table_name"] for v in visible_tables]
            })

        # Get role grants for the schema
        schema_grants = await _run_query(
            pool,
            """
            SELECT grantee, privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = $1
            ORDER BY grantee, table_name
            LIMIT 50
            """
            , schema
        )

        result["permissions"] = {
            "current_user": await _run_query_single(pool, "SELECT current_user"),
            "tables_in_pg_class": len(all_pg_tables),
            "tables_visible_in_info_schema": len(visible_tables),
            "tables_with_select": sum(1 for p in permission_check if p["has_select"]),
            "permission_details": permission_check,
            "missing_select": [
                p["table"] for p in permission_check
                if not p["has_select"]
            ],
        }

        # Add summary of the permission issue
        if result["permissions"]["tables_in_pg_class"] != result["permissions"]["tables_visible_in_info_schema"]:
            result["permissions"]["issue"] = (
                f"User '{result['permissions']['current_user']}' can see "
                f"{result['permissions']['tables_in_pg_class']} tables in pg_class but only "
                f"{result['permissions']['tables_visible_in_info_schema']} in information_schema. "
                f"Missing SELECT on: {result['permissions']['missing_select']}"
            )

    except Exception as e:
        result["permissions"] = {"error": str(e)}

    # ==========================================================================
    # GEOMETRY REGISTRATION DIAGNOSTICS
    # ==========================================================================
    try:
        # Compare pg_attribute (actual columns) vs geometry_columns (PostGIS registry)
        pg_attr_geom = await _run_query(
            pool,
            """
            SELECT c.relname as table_name
            FROM pg_class c
            JOIN pg_namespace ns ON c.relnamespace = ns.oid
            JOIN pg_attribute a ON a.attrelid = c.oid
            JOIN pg_type t ON a.atttypid = t.oid
            WHERE ns.nspname = $1
            AND c.relkind = 'r'
            AND a.attnum > 0
            AND NOT a.attisdropped
            AND t.typname IN ('geometry', 'geography')
            ORDER BY c.relname
            """,
            schema
        )
        tables_with_geom_attr = [t["table_name"] for t in pg_attr_geom]

        geom_cols_registered = await _run_query(
            pool,
            "SELECT f_table_name FROM geometry_columns WHERE f_table_schema = $1",
            schema
        )
        tables_registered = [t["f_table_name"] for t in geom_cols_registered]

        # Find tables with geometry column but NOT registered
        not_registered = [t for t in tables_with_geom_attr if t not in tables_registered]

        result["geometry_registration"] = {
            "tables_with_geometry_column": tables_with_geom_attr,
            "tables_in_geometry_columns": tables_registered,
            "not_registered_with_postgis": not_registered,
            "registration_issue": len(not_registered) > 0,
        }

        if not_registered:
            result["geometry_registration"]["fix_sql"] = [
                f"SELECT Populate_Geometry_Columns('{schema}.{t}'::regclass);"
                for t in not_registered
            ]

    except Exception as e:
        result["geometry_registration"] = {"error": str(e)}

    # ==========================================================================
    # SELECT ATTEMPT DIAGNOSTICS - Actually try to SELECT from each table
    # This captures real permission errors for service requests
    # ==========================================================================
    try:
        # Get all tables from pg_class (includes ones we can't SELECT from)
        all_pg_tables = await _run_query(
            pool,
            """
            SELECT c.relname as table_name
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = $1 AND c.relkind = 'r'
            ORDER BY c.relname
            """,
            schema
        )

        select_attempts = []
        for t in all_pg_tables:
            table_name = t["table_name"]
            full_table = f"{schema}.{table_name}"
            attempt = {
                "table": table_name,
                "full_name": full_table,
                "can_select": False,
                "error": None,
                "row_sample": None,
            }

            try:
                # Try to actually SELECT from the table
                async with pool.acquire() as conn:
                    # Use LIMIT 1 to minimize data transfer
                    row = await conn.fetchrow(f'SELECT 1 FROM "{schema}"."{table_name}" LIMIT 1')
                    attempt["can_select"] = True
                    attempt["row_sample"] = "OK - SELECT succeeded"
            except Exception as select_error:
                # Capture the actual error message - this is the evidence we need
                attempt["can_select"] = False
                attempt["error"] = str(select_error)
                # Extract just the key part of the error for readability
                error_str = str(select_error)
                if "permission denied" in error_str.lower():
                    attempt["error_type"] = "PERMISSION_DENIED"
                elif "does not exist" in error_str.lower():
                    attempt["error_type"] = "TABLE_NOT_FOUND"
                else:
                    attempt["error_type"] = "OTHER"

            select_attempts.append(attempt)

        # Summarize results
        succeeded = [a for a in select_attempts if a["can_select"]]
        failed = [a for a in select_attempts if not a["can_select"]]
        permission_denied = [a for a in failed if a.get("error_type") == "PERMISSION_DENIED"]

        result["select_attempts"] = {
            "total_tables": len(select_attempts),
            "select_succeeded": len(succeeded),
            "select_failed": len(failed),
            "permission_denied_count": len(permission_denied),
            "details": select_attempts,
        }

        # Generate fix SQL for permission issues
        if permission_denied:
            current_user = await _run_query_single(pool, "SELECT current_user")
            fix_lines = [
                f"-- Fix SELECT permissions for {current_user} in {schema} schema",
                f"-- Run this SQL as database administrator",
                f"-- Service Request Evidence: {len(permission_denied)} tables returned 'permission denied'",
                "",
            ]
            for a in permission_denied:
                fix_lines.append(f"GRANT SELECT ON {a['full_name']} TO {current_user};")

            fix_lines.extend([
                "",
                "-- To automatically grant SELECT on future tables:",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {current_user};",
            ])

            result["select_attempts"]["fix_sql"] = "\n".join(fix_lines)

            # Add a clear summary for service request
            result["select_attempts"]["service_request_summary"] = {
                "issue": f"User '{current_user}' lacks SELECT permission on {len(permission_denied)} tables in schema '{schema}'",
                "affected_tables": [a["table"] for a in permission_denied],
                "sample_error": permission_denied[0]["error"] if permission_denied else None,
                "resolution": f"Grant SELECT on listed tables to {current_user}",
            }

    except Exception as e:
        result["select_attempts"] = {"error": str(e)}

    return result


@router.get("/diagnostics/table/{table_name}")
async def table_diagnostics(
    request: Request,
    table_name: str,
    schema: str = Query(default="geo", description="Schema containing the table"),
):
    """
    Deep diagnostics for a specific table.

    Use this to understand why a specific table isn't appearing in TiPG.

    Returns:
        Comprehensive table metadata including all columns, constraints,
        geometry registration status, and permissions.
    """
    app_state = get_app_state()
    pool = getattr(app_state, "pool", None) if app_state else None

    if not pool:
        return {"status": "error", "error": "Database pool not initialized"}

    full_name = f"{schema}.{table_name}"

    result = {
        "table": table_name,
        "schema": schema,
        "full_name": full_name,
    }

    # Check if table exists
    exists = await _run_query_single(
        pool,
        """
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = $1 AND table_name = $2
        )
        """,
        schema, table_name
    )
    result["exists"] = exists

    if not exists:
        result["status"] = "error"
        result["error"] = f"Table {full_name} does not exist"
        return result

    # Get all columns
    columns = await _run_query(
        pool,
        """
        SELECT
            column_name,
            ordinal_position,
            data_type,
            udt_name,
            character_maximum_length,
            numeric_precision,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
        ORDER BY ordinal_position
        """,
        schema, table_name
    )
    result["columns"] = columns
    result["column_count"] = len(columns)

    # Find geometry columns
    geom_cols = [c for c in columns if c["udt_name"] in ("geometry", "geography")]
    result["geometry_columns"] = geom_cols

    # Check geometry_columns view
    in_geom_view = await _run_query(
        pool,
        """
        SELECT f_geometry_column, type, srid, coord_dimension
        FROM geometry_columns
        WHERE f_table_schema = $1 AND f_table_name = $2
        """,
        schema, table_name
    )
    result["in_geometry_columns_view"] = in_geom_view
    result["registered_with_postgis"] = len(in_geom_view) > 0

    # Get primary key
    pk = await _run_query(
        pool,
        """
        SELECT a.attname as column_name
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = $1::regclass AND i.indisprimary
        """,
        full_name
    )
    result["primary_key"] = [p["column_name"] for p in pk] if pk else None

    # Get all indexes
    indexes = await _run_query(
        pool,
        """
        SELECT
            i.relname as index_name,
            am.amname as index_type,
            pg_get_indexdef(i.oid) as definition
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_am am ON i.relam = am.oid
        WHERE ix.indrelid = $1::regclass
        """,
        full_name
    )
    result["indexes"] = indexes
    result["has_spatial_index"] = any("gist" in str(idx.get("index_type", "")).lower() for idx in indexes)

    # Get constraints
    constraints = await _run_query(
        pool,
        """
        SELECT
            conname as constraint_name,
            contype as constraint_type,
            pg_get_constraintdef(oid) as definition
        FROM pg_constraint
        WHERE conrelid = $1::regclass
        """,
        full_name
    )
    result["constraints"] = constraints

    # Check permissions
    result["permissions"] = {
        "select": await _run_query_single(pool, "SELECT has_table_privilege(current_user, $1, 'SELECT')", full_name),
        "insert": await _run_query_single(pool, "SELECT has_table_privilege(current_user, $1, 'INSERT')", full_name),
        "update": await _run_query_single(pool, "SELECT has_table_privilege(current_user, $1, 'UPDATE')", full_name),
        "delete": await _run_query_single(pool, "SELECT has_table_privilege(current_user, $1, 'DELETE')", full_name),
    }

    # Row count
    row_count = await _run_query_single(
        pool,
        "SELECT n_live_tup FROM pg_stat_user_tables WHERE schemaname = $1 AND relname = $2",
        schema, table_name
    )
    result["approximate_row_count"] = row_count

    # Sample data (first row)
    try:
        sample = await _run_query(
            pool,
            f'SELECT * FROM "{schema}"."{table_name}" LIMIT 1'
        )
        if sample:
            # Convert geometry to text for display
            sample_row = {}
            for key, value in sample[0].items():
                if hasattr(value, '__geo_interface__'):
                    sample_row[key] = "<geometry>"
                elif isinstance(value, bytes):
                    sample_row[key] = f"<binary {len(value)} bytes>"
                else:
                    sample_row[key] = str(value) if value is not None else None
            result["sample_row"] = sample_row
    except Exception as e:
        result["sample_row"] = {"error": str(e)}

    # Diagnosis
    issues = []
    if not result["geometry_columns"]:
        issues.append("No geometry/geography columns found in table")
    if not result["registered_with_postgis"]:
        issues.append("Table not registered in PostGIS geometry_columns view")
    if not result["primary_key"]:
        issues.append("No primary key - TiPG may require a primary key")
    if not result["has_spatial_index"]:
        issues.append("No spatial (GIST) index - queries may be slow")
    if not result["permissions"]["select"]:
        issues.append("Current user cannot SELECT from this table")

    result["issues"] = issues if issues else None
    result["status"] = "issues_found" if issues else "ok"

    return result
