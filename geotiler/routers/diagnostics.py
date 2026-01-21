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
from geotiler.services.database import get_app_state_from_request
from geotiler.routers.vector import get_tipg_startup_state_from_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vector", tags=["Diagnostics"])


async def _run_query(pool, query: str, *args) -> tuple[list[dict], Optional[str]]:
    """
    Run a query and return results as list of dicts with error info.

    Returns:
        Tuple of (results, error). On success: ([rows], None). On failure: ([], error_message).

    Note: Future enhancement could return a QueryResult dataclass with success, data,
    error, and metadata fields (Option C) for richer error context and query timing.
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows], None
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return [], str(e)


async def _run_query_single(pool, query: str, *args) -> tuple[Any, Optional[str]]:
    """
    Run a query and return single value with error info.

    Returns:
        Tuple of (value, error). On success: (value, None). On failure: (None, error_message).
    """
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args), None
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return None, str(e)


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
    app_state = get_app_state_from_request(request)
    pool = getattr(app_state, "pool", None) if app_state else None

    if not pool:
        return {
            "status": "error",
            "error": "TiPG pool not initialized",
            "hint": "Check application logs for TiPG initialization errors",
        }

    # Get startup state
    startup_state = get_tipg_startup_state_from_app(request.app)

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
    current_user, user_err = await _run_query_single(pool, "SELECT current_user")
    search_path, path_err = await _run_query_single(pool, "SHOW search_path")
    db_name, db_err = await _run_query_single(pool, "SELECT current_database()")

    conn_error = user_err or path_err or db_err
    if conn_error:
        diagnostics["connection"] = {"error": conn_error}
        issues.append(f"Connection query failed: {conn_error}")
    else:
        diagnostics["connection"] = {
            "pool_exists": True,
            "pool_size": pool.get_size(),
            "pool_free": pool.get_idle_size(),
            "current_user": current_user,
            "current_database": db_name,
            "search_path": search_path,
        }

    # ==========================================================================
    # POSTGIS STATUS
    # ==========================================================================
    postgis_info, postgis_err = await _run_query(
        pool,
        """
        SELECT extname, extversion
        FROM pg_extension
        WHERE extname IN ('postgis', 'postgis_topology', 'postgis_raster')
        """
    )

    if postgis_err:
        diagnostics["postgis"] = {"error": postgis_err}
        issues.append(f"PostGIS check failed: {postgis_err}")
    elif postgis_info:
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

    # ==========================================================================
    # SCHEMA DIAGNOSTICS (for each configured schema)
    # ==========================================================================
    for schema in settings.tipg_schema_list:
        schema_diag = await _diagnose_schema(pool, schema, issues)
        diagnostics["schemas"][schema] = schema_diag

    # ==========================================================================
    # GLOBAL GEOMETRY_COLUMNS VIEW (all schemas)
    # ==========================================================================
    all_geometry_columns, geom_cols_err = await _run_query(
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
    if geom_cols_err:
        diagnostics["all_geometry_columns"] = {"error": geom_cols_err}
        diagnostics["all_geometry_columns_count"] = 0
    else:
        diagnostics["all_geometry_columns"] = all_geometry_columns
        diagnostics["all_geometry_columns_count"] = len(all_geometry_columns)

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
    schema_exists, exists_err = await _run_query_single(
        pool,
        "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = $1)",
        schema
    )
    if exists_err:
        schema_diag["error"] = exists_err
        issues.append(f"Schema check failed for '{schema}': {exists_err}")
        return schema_diag

    schema_diag["exists"] = schema_exists

    if not schema_exists:
        issues.append(f"Schema '{schema}' does not exist")
        return schema_diag

    # Check USAGE permission on schema
    has_usage, usage_err = await _run_query_single(
        pool,
        "SELECT has_schema_privilege(current_user, $1, 'USAGE')",
        schema
    )
    if usage_err:
        schema_diag["error"] = usage_err
        issues.append(f"Permission check failed for '{schema}': {usage_err}")
        return schema_diag

    schema_diag["has_usage_permission"] = has_usage

    if not has_usage:
        issues.append(f"No USAGE permission on schema '{schema}' - run: GRANT USAGE ON SCHEMA {schema} TO <user>;")
        return schema_diag

    # Count total tables in schema
    table_count, tc_err = await _run_query_single(
        pool,
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = $1 AND table_type = 'BASE TABLE'
        """,
        schema
    )
    schema_diag["tables_total"] = table_count or 0
    if tc_err:
        schema_diag["tables_total_error"] = tc_err

    # Count views in schema
    view_count, vc_err = await _run_query_single(
        pool,
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = $1 AND table_type = 'VIEW'
        """,
        schema
    )
    schema_diag["views_total"] = view_count or 0
    if vc_err:
        schema_diag["views_total_error"] = vc_err

    # Raw query to geometry_columns - shows exactly what PostGIS sees
    raw_geom_cols, raw_err = await _run_query(
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
    schema_diag["raw_geometry_columns"] = raw_geom_cols if not raw_err else {"error": raw_err}

    # Get tables with geometry columns from geometry_columns view
    geometry_tables, geom_err = await _run_query(
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
    if geom_err:
        schema_diag["geometry_tables_error"] = geom_err

    # If geometry_columns is empty, try direct column check
    if not geometry_tables and not geom_err:
        geometry_tables, fallback_err = await _run_query(
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
        if fallback_err:
            schema_diag["geometry_fallback_error"] = fallback_err

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
        can_select, select_err = await _run_query_single(
            pool,
            "SELECT has_table_privilege(current_user, $1, 'SELECT')",
            f"{schema}.{table_name}"
        )

        table_info = {
            "name": table_name,
            "geometry_column": table["geometry_column"],
            "geometry_type": table["geometry_type"],
            "srid": table["srid"],
            "can_select": can_select if not select_err else None,
        }
        if select_err:
            table_info["permission_check_error"] = select_err
        tables_detail.append(table_info)

        if can_select and not select_err:
            accessible_count += 1
        elif not select_err:
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
    all_tables, all_tables_err = await _run_query(
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
    if all_tables_err:
        schema_diag["all_tables_error"] = all_tables_err

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
    app_state = get_app_state_from_request(request)
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
    current_user, u_err = await _run_query_single(pool, "SELECT current_user")
    current_db, db_err = await _run_query_single(pool, "SELECT current_database()")
    search_path, sp_err = await _run_query_single(pool, "SHOW search_path")
    server_version, sv_err = await _run_query_single(pool, "SHOW server_version")
    postgis_version, pv_err = await _run_query_single(pool, "SELECT PostGIS_Version()")

    result["connection"] = {
        "current_user": current_user if not u_err else {"error": u_err},
        "current_database": current_db if not db_err else {"error": db_err},
        "search_path": search_path if not sp_err else {"error": sp_err},
        "server_version": server_version if not sv_err else {"error": sv_err},
        "postgis_version": postgis_version if not pv_err else {"error": pv_err},
    }

    # ==========================================================================
    # SCHEMA EXISTS CHECK (rmhgeoapi style - pg_namespace)
    # ==========================================================================
    schema_exists, exists_err = await _run_query_single(
        pool,
        "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = $1)",
        schema
    )
    if exists_err:
        result["schema_info"]["exists"] = {"error": exists_err}
        result["status"] = "error"
        result["error"] = f"Schema check failed: {exists_err}"
        return result

    result["schema_info"]["exists"] = schema_exists

    if not schema_exists:
        result["status"] = "error"
        result["error"] = f"Schema '{schema}' does not exist"
        return result

    # ==========================================================================
    # ALL TABLES IN SCHEMA (rmhgeoapi: information_schema.tables)
    # ==========================================================================
    all_tables, tables_err = await _run_query(
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
    if tables_err:
        result["schema_info"]["tables_error"] = tables_err
    result["schema_info"]["tables"] = [t["table_name"] for t in all_tables]
    result["schema_info"]["table_count"] = len(all_tables)

    # ==========================================================================
    # ROW COUNTS (rmhgeoapi: pg_stat_user_tables)
    # ==========================================================================
    if include_row_counts:
        row_counts, rc_err = await _run_query(
            pool,
            """
            SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
            FROM pg_stat_user_tables
            WHERE schemaname = $1
            ORDER BY relname
            """,
            schema
        )
        if rc_err:
            result["schema_info"]["row_counts_error"] = rc_err
        else:
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
    geometry_columns, gc_err = await _run_query(
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
    if gc_err:
        result["geometry_columns_error"] = gc_err
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
        pk_info, pk_err = await _run_query(
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
        if pk_err:
            table_info["primary_key_error"] = pk_err
        table_info["primary_key"] = [p["column_name"] for p in pk_info] if pk_info else None
        table_info["has_primary_key"] = len(pk_info) > 0

        # Get columns (if requested)
        if include_columns:
            columns, col_err = await _run_query(
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
            if col_err:
                table_info["columns_error"] = col_err
            table_info["columns"] = columns

            # Check for geometry-like columns
            geom_cols = [c for c in columns if c["udt_name"] in ("geometry", "geography")]
            table_info["geometry_columns_found"] = [
                {"name": c["column_name"], "type": c["udt_name"]}
                for c in geom_cols
            ]

        # Check SELECT permission
        can_select, sel_err = await _run_query_single(
            pool,
            "SELECT has_table_privilege(current_user, $1, 'SELECT')",
            f"{schema}.{table_name}"
        )
        if sel_err:
            table_info["can_select_error"] = sel_err
        table_info["can_select"] = can_select if not sel_err else None

        result["tables"][table_name] = table_info

    # ==========================================================================
    # COMPARISON QUERIES - Run the EXACT queries for debugging
    # ==========================================================================

    # Query 1: Direct geometry_columns (no schema filter)
    all_geom, ag_err = await _run_query(
        pool,
        """
        SELECT f_table_schema, f_table_name, f_geometry_column, type, srid
        FROM geometry_columns
        ORDER BY f_table_schema, f_table_name
        LIMIT 50
        """
    )
    result["comparison_queries"]["geometry_columns_all_schemas"] = all_geom if not ag_err else {"error": ag_err}

    # Query 2: Check pg_type for geometry type
    geom_type, gt_err = await _run_query(
        pool,
        """
        SELECT typname, typnamespace::regnamespace as schema
        FROM pg_type
        WHERE typname IN ('geometry', 'geography')
        """
    )
    result["comparison_queries"]["geometry_types_registered"] = geom_type if not gt_err else {"error": gt_err}

    # Query 3: Check if geometry_columns is a view or table
    geom_view_check, gv_err = await _run_query(
        pool,
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_name = 'geometry_columns'
        """
    )
    result["comparison_queries"]["geometry_columns_object_type"] = geom_view_check if not gv_err else {"error": gv_err}

    # Query 4: Raw pg_attribute check for geometry columns
    raw_geom_attrs, rga_err = await _run_query(
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
    result["comparison_queries"]["pg_attribute_geometry_columns"] = raw_geom_attrs if not rga_err else {"error": rga_err}

    # Query 5: Check constraints on geometry columns
    geom_constraints, gc_err2 = await _run_query(
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
    result["comparison_queries"]["table_constraints"] = geom_constraints if not gc_err2 else {"error": gc_err2}

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
    # Tables visible via information_schema (requires SELECT privilege)
    visible_tables, vt_err = await _run_query(
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
    all_pg_tables, apt_err = await _run_query(
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

    if vt_err or apt_err:
        result["permissions"] = {"error": vt_err or apt_err}
    else:
        # Check SELECT privilege on each table
        permission_check = []
        for t in all_pg_tables:
            table_name = t["table_name"]
            has_select, hs_err = await _run_query_single(
                pool,
                "SELECT has_table_privilege(current_user, $1, 'SELECT')",
                f"{schema}.{table_name}"
            )
            permission_check.append({
                "table": table_name,
                "has_select": has_select if not hs_err else None,
                "has_select_error": hs_err if hs_err else None,
                "visible_in_info_schema": table_name in [v["table_name"] for v in visible_tables]
            })

        # Get role grants for the schema (not critical, ignore errors)
        schema_grants, sg_err = await _run_query(
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

        perm_user, pu_err = await _run_query_single(pool, "SELECT current_user")

        result["permissions"] = {
            "current_user": perm_user if not pu_err else {"error": pu_err},
            "tables_in_pg_class": len(all_pg_tables),
            "tables_visible_in_info_schema": len(visible_tables),
            "tables_with_select": sum(1 for p in permission_check if p["has_select"]),
            "permission_details": permission_check,
            "missing_select": [
                p["table"] for p in permission_check
                if not p["has_select"] and not p.get("has_select_error")
            ],
        }

        # Add summary of the permission issue
        if result["permissions"]["tables_in_pg_class"] != result["permissions"]["tables_visible_in_info_schema"]:
            result["permissions"]["issue"] = (
                f"User '{perm_user}' can see "
                f"{result['permissions']['tables_in_pg_class']} tables in pg_class but only "
                f"{result['permissions']['tables_visible_in_info_schema']} in information_schema. "
                f"Missing SELECT on: {result['permissions']['missing_select']}"
            )

    # ==========================================================================
    # GEOMETRY REGISTRATION DIAGNOSTICS
    # ==========================================================================
    # Compare pg_attribute (actual columns) vs geometry_columns (PostGIS registry)
    pg_attr_geom, pag_err = await _run_query(
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

    geom_cols_registered, gcr_err = await _run_query(
        pool,
        "SELECT f_table_name FROM geometry_columns WHERE f_table_schema = $1",
        schema
    )

    if pag_err or gcr_err:
        result["geometry_registration"] = {"error": pag_err or gcr_err}
    else:
        tables_with_geom_attr = [t["table_name"] for t in pg_attr_geom]
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

    # ==========================================================================
    # SELECT ATTEMPT DIAGNOSTICS - Actually try to SELECT from each table
    # This captures real permission errors for service requests
    # ==========================================================================
    # Get all tables from pg_class (includes ones we can't SELECT from)
    select_pg_tables, spt_err = await _run_query(
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

    if spt_err:
        result["select_attempts"] = {"error": spt_err}
    else:
        select_attempts = []
        for t in select_pg_tables:
            tbl_name = t["table_name"]
            full_table = f"{schema}.{tbl_name}"
            attempt = {
                "table": tbl_name,
                "full_name": full_table,
                "can_select": False,
                "error": None,
                "row_sample": None,
            }

            try:
                # Try to actually SELECT from the table
                async with pool.acquire() as conn:
                    # Use LIMIT 1 to minimize data transfer
                    row = await conn.fetchrow(f'SELECT 1 FROM "{schema}"."{tbl_name}" LIMIT 1')
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
            fix_user, fu_err = await _run_query_single(pool, "SELECT current_user")
            if not fu_err:
                fix_lines = [
                    f"-- Fix SELECT permissions for {fix_user} in {schema} schema",
                    f"-- Run this SQL as database administrator",
                    f"-- Service Request Evidence: {len(permission_denied)} tables returned 'permission denied'",
                    "",
                ]
                for a in permission_denied:
                    fix_lines.append(f"GRANT SELECT ON {a['full_name']} TO {fix_user};")

                fix_lines.extend([
                    "",
                    "-- To automatically grant SELECT on future tables:",
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {fix_user};",
                ])

                result["select_attempts"]["fix_sql"] = "\n".join(fix_lines)

                # Add a clear summary for service request
                result["select_attempts"]["service_request_summary"] = {
                    "issue": f"User '{fix_user}' lacks SELECT permission on {len(permission_denied)} tables in schema '{schema}'",
                    "affected_tables": [a["table"] for a in permission_denied],
                    "sample_error": permission_denied[0]["error"] if permission_denied else None,
                    "resolution": f"Grant SELECT on listed tables to {fix_user}",
                }

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
    app_state = get_app_state_from_request(request)
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
    exists, exists_err = await _run_query_single(
        pool,
        """
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = $1 AND table_name = $2
        )
        """,
        schema, table_name
    )
    if exists_err:
        result["status"] = "error"
        result["error"] = f"Table check failed: {exists_err}"
        return result

    result["exists"] = exists

    if not exists:
        result["status"] = "error"
        result["error"] = f"Table {full_name} does not exist"
        return result

    # Get all columns
    columns, col_err = await _run_query(
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
    if col_err:
        result["columns_error"] = col_err
    result["columns"] = columns
    result["column_count"] = len(columns)

    # Find geometry columns
    geom_cols = [c for c in columns if c["udt_name"] in ("geometry", "geography")]
    result["geometry_columns"] = geom_cols

    # Check geometry_columns view
    in_geom_view, igv_err = await _run_query(
        pool,
        """
        SELECT f_geometry_column, type, srid, coord_dimension
        FROM geometry_columns
        WHERE f_table_schema = $1 AND f_table_name = $2
        """,
        schema, table_name
    )
    if igv_err:
        result["geometry_columns_view_error"] = igv_err
    result["in_geometry_columns_view"] = in_geom_view
    result["registered_with_postgis"] = len(in_geom_view) > 0

    # Get primary key
    pk, pk_err = await _run_query(
        pool,
        """
        SELECT a.attname as column_name
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = $1::regclass AND i.indisprimary
        """,
        full_name
    )
    if pk_err:
        result["primary_key_error"] = pk_err
    result["primary_key"] = [p["column_name"] for p in pk] if pk else None

    # Get all indexes
    indexes, idx_err = await _run_query(
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
    if idx_err:
        result["indexes_error"] = idx_err
    result["indexes"] = indexes
    result["has_spatial_index"] = any("gist" in str(idx.get("index_type", "")).lower() for idx in indexes)

    # Get constraints
    constraints, con_err = await _run_query(
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
    if con_err:
        result["constraints_error"] = con_err
    result["constraints"] = constraints

    # Check permissions
    select_perm, sp_err = await _run_query_single(pool, "SELECT has_table_privilege(current_user, $1, 'SELECT')", full_name)
    insert_perm, ip_err = await _run_query_single(pool, "SELECT has_table_privilege(current_user, $1, 'INSERT')", full_name)
    update_perm, up_err = await _run_query_single(pool, "SELECT has_table_privilege(current_user, $1, 'UPDATE')", full_name)
    delete_perm, dp_err = await _run_query_single(pool, "SELECT has_table_privilege(current_user, $1, 'DELETE')", full_name)

    result["permissions"] = {
        "select": select_perm if not sp_err else {"error": sp_err},
        "insert": insert_perm if not ip_err else {"error": ip_err},
        "update": update_perm if not up_err else {"error": up_err},
        "delete": delete_perm if not dp_err else {"error": dp_err},
    }

    # Row count
    row_count, rc_err = await _run_query_single(
        pool,
        "SELECT n_live_tup FROM pg_stat_user_tables WHERE schemaname = $1 AND relname = $2",
        schema, table_name
    )
    if rc_err:
        result["row_count_error"] = rc_err
    result["approximate_row_count"] = row_count

    # Sample data (first row)
    sample, sample_err = await _run_query(
        pool,
        f'SELECT * FROM "{schema}"."{table_name}" LIMIT 1'
    )
    if sample_err:
        result["sample_row"] = {"error": sample_err}
    elif sample:
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
    if not result["permissions"].get("select") or isinstance(result["permissions"]["select"], dict):
        issues.append("Current user cannot SELECT from this table")

    result["issues"] = issues if issues else None
    result["status"] = "issues_found" if issues else "ok"

    return result
