"""
STAC API integration using stac-fastapi-pgstac.

Provides STAC API endpoints for catalog browsing and search,
complementing titiler-pgstac's tile rendering capabilities.

Key integration points:
- Own asyncpg connection pool (app.state.readpool) with server_settings
  that natively survive asyncpg's RESET ALL
- Uses same PostgreSQL credentials (Managed Identity)
- Pool refresh synchronized with token refresh cycle

Architecture:
    The STAC API router is created at app startup (create_app) but the
    database pool is initialized during lifespan (initialize_stac_pool).
    CoreCrudClient accesses app.state.readpool at request time, so this works.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter
from stac_fastapi.api.app import StacApi
from stac_fastapi.api.models import create_get_request_model, create_post_request_model
from stac_fastapi.extensions.core import (
    CollectionSearchExtension,
    FieldsExtension,
    FilterExtension,
    SortExtension,
    TokenPaginationExtension,
)
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.pgstac.types.search import PgstacSearch
from stac_fastapi.pgstac.config import Settings as PgstacSettings
from stac_fastapi.pgstac.config import PostgresSettings as StacPostgresSettings
from stac_fastapi.pgstac.config import ServerSettings as StacServerSettings
from stac_fastapi.pgstac.db import connect_to_db as stac_connect_to_db
from stac_fastapi.pgstac.db import close_db_connection as stac_close_db_connection

from geotiler.config import settings
from geotiler.auth.postgres import get_postgres_credential, build_database_url

logger = logging.getLogger(__name__)

# Module-level reference to StacApi instance
_stac_api: Optional[StacApi] = None


def create_stac_api(app) -> StacApi:
    """
    Create STAC API instance and add routes to the app.

    The StacApi is created at app startup. The database pool
    (app.state.readpool) is initialized later during lifespan
    (initialize_stac_pool). CoreCrudClient accesses the pool at
    request time, so this works.

    Args:
        app: FastAPI application to add routes to.

    Returns:
        StacApi instance.
    """
    global _stac_api

    logger.info(f"Creating STAC API: prefix={settings.stac_prefix}")

    # Create request models with extensions
    extensions_for_models = [FilterExtension(), FieldsExtension(), SortExtension()]

    get_request_model = create_get_request_model(extensions=extensions_for_models)
    post_request_model = create_post_request_model(
        extensions=extensions_for_models,
        base_model=PgstacSearch,
    )

    # Create extensions list
    extensions = [
        FilterExtension(),
        SortExtension(),
        FieldsExtension(),
        TokenPaginationExtension(),
    ]

    # CollectionSearchExtension: uses collection_search() instead of the
    # deprecated all_collections() SQL function (removed in pgstac ≥0.9).
    # Without this, GET /stac/collections fails with:
    #   UndefinedFunctionError: function all_collections() does not exist
    collection_search_ext = CollectionSearchExtension.from_extensions(
        extensions=[
            FieldsExtension(),
            SortExtension(),
        ]
    )
    collections_get_request_model = collection_search_ext.GET
    extensions.append(collection_search_ext)

    # Create router with prefix so routes are mounted at /stac/*
    # StacApi derives router_prefix from router.prefix during __attrs_post_init__
    stac_router = APIRouter(prefix=settings.stac_prefix)

    # Create STAC API settings with geotiler branding
    stac_settings = PgstacSettings(
        stac_fastapi_title="geotiler STAC API",
        stac_fastapi_description="STAC API for pgSTAC catalog browsing and search",
    )

    # Create STAC API with main app and prefixed router
    # CoreCrudClient will access request.app.state.readpool at request time
    _stac_api = StacApi(
        app=app,
        router=stac_router,
        settings=stac_settings,
        extensions=extensions,
        client=CoreCrudClient(
            pgstac_search_model=PgstacSearch,
        ),
        search_get_request_model=get_request_model,
        search_post_request_model=post_request_model,
        collections_get_request_model=collections_get_request_model,
    )

    logger.info("STAC API created successfully")
    return _stac_api


def get_stac_api() -> Optional[StacApi]:
    """Get the initialized StacApi instance."""
    return _stac_api


def is_stac_api_available() -> bool:
    """Check if STAC API is available and initialized."""
    return _stac_api is not None


# =============================================================================
# STAC POOL LIFECYCLE
# =============================================================================
# STAC gets its own asyncpg pool, independent of TiPG. Using stac-fastapi-
# pgstac's native connect_to_db() which passes server_settings to
# asyncpg.create_pool(). server_settings are protocol-level parameters set
# during connection establishment — they survive asyncpg's RESET ALL by design.
# This eliminates the search_path problem that plagued the shared-pool approach.
# =============================================================================

def _build_stac_postgres_settings() -> StacPostgresSettings:
    """Build PostgresSettings for stac-fastapi-pgstac's own pool.

    Uses geotiler's auth system (MI token or password) to construct
    connection parameters, with server_settings={"search_path": "pgstac,public"}
    that persist through asyncpg's RESET ALL.

    Returns:
        StacPostgresSettings ready for stac_connect_to_db().
    """
    credential = get_postgres_credential()
    if not credential:
        raise RuntimeError("Failed to get PostgreSQL credential for STAC pool")

    return StacPostgresSettings(
        pguser=settings.pg_user,
        pgpassword=credential,
        pghost=settings.pg_host,
        pgport=settings.pg_port,
        pgdatabase=settings.pg_db,
        db_min_conn_size=settings.pool_stac_min,
        db_max_conn_size=settings.pool_stac_max,
        server_settings=StacServerSettings(
            search_path="pgstac,public",
            application_name="geotiler-stac",
            statement_timeout=str(settings.db_statement_timeout_ms),
        ),
    )


async def initialize_stac_pool(app) -> None:
    """Create STAC API's own asyncpg connection pool.

    Uses stac-fastapi-pgstac's native connect_to_db() which passes
    server_settings to asyncpg.create_pool(). The search_path is set
    at the protocol level during connection establishment, so it
    survives asyncpg's RESET ALL on connection return.

    Sets app.state.readpool, app.state.writepool, app.state.get_connection.

    Args:
        app: FastAPI application instance.
    """
    logger.info("Initializing STAC API connection pool...")

    try:
        pg_settings = _build_stac_postgres_settings()
        await stac_connect_to_db(app, postgres_settings=pg_settings)

        # Log pool details for diagnostics
        pool = getattr(app.state, "readpool", None)
        pool_size = pool.get_size() if pool else "N/A"
        pool_min = pool.get_min_size() if pool else "N/A"
        pool_max = pool.get_max_size() if pool else "N/A"
        logger.info(
            f"STAC pool created: host={settings.pg_host} "
            f"db={settings.pg_db} pool_size={pool_size} "
            f"min={pool_min} max={pool_max} "
            f"server_settings.search_path=pgstac,public"
        )

        # Verify search_path and collection_search() work
        await _verify_stac_pool(app)

    except Exception as e:
        logger.error(f"Failed to create STAC pool: {type(e).__name__}: {e}")
        logger.warning("STAC API will not be available (no database pool)")
        raise


async def _verify_stac_pool(app) -> None:
    """Verify STAC pool has correct search_path and pgstac functions are callable.

    Runs immediately after pool creation. Acquires a connection, checks
    search_path, and calls collection_search() to confirm pgstac schema is
    accessible. Logs results for post-deployment verification.
    """
    pool = getattr(app.state, "readpool", None)
    if not pool:
        logger.warning("STAC pool verification skipped: no readpool")
        return

    try:
        async with pool.acquire() as conn:
            # Check search_path
            search_path = await conn.fetchval("SHOW search_path;")
            logger.info(f"STAC pool verification: search_path = '{search_path}'")

            # Check pgstac schema exists
            schema_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'pgstac');"
            )
            logger.info(f"STAC pool verification: pgstac schema exists = {schema_exists}")

            if not schema_exists:
                logger.error("CRITICAL: pgstac schema does not exist in database!")
                return

            # Test collection_search() — the function used by pgstac ≥0.8.2
            # (replaces the deprecated all_collections())
            try:
                # Inline JSON literal to avoid stac-fastapi-pgstac's custom
                # jsonb codec (bytes vs str DataError on parameterized queries)
                result = await conn.fetchval(
                    "SELECT * FROM collection_search('{}'::jsonb);",
                )
                # Result may be dict, JSON string, or bytes depending on codec
                if isinstance(result, (str, bytes)):
                    result = json.loads(result)
                if isinstance(result, dict):
                    cols = result.get("collections", [])
                    count = len(cols) if cols else 0
                else:
                    count = len(result) if result else 0
                logger.info(f"STAC pool verification: collection_search() OK — {count} collections")
            except Exception as fn_err:
                logger.error(f"STAC pool verification: collection_search() FAILED — {fn_err}")
                logger.error("This means pgstac functions are missing or search_path is wrong")

            # Also verify search() is callable (used by /stac/search)
            try:
                # Inline JSON literal (same codec issue as collection_search above)
                await conn.fetchval(
                    "SELECT * FROM search('{\"limit\": 0}'::jsonb);",
                )
                logger.info("STAC pool verification: search() OK")
            except Exception as search_err:
                # search with limit=0 might fail for business reasons but
                # UndefinedFunctionError is the critical one
                err_type = type(search_err).__name__
                if "UndefinedFunction" in err_type:
                    logger.error(f"STAC pool verification: search() FAILED — {search_err}")
                else:
                    logger.debug(f"STAC pool verification: search() returned error (expected): {err_type}")

    except Exception as e:
        logger.error(f"STAC pool verification failed: {type(e).__name__}: {e}")


async def close_stac_pool(app) -> None:
    """Close the STAC API connection pool.

    Args:
        app: FastAPI application instance.
    """
    try:
        await stac_close_db_connection(app)
        logger.info("STAC connection pool closed")
    except Exception as e:
        logger.warning(f"Error closing STAC pool: {e}")


async def refresh_stac_pool(app) -> None:
    """Refresh STAC pool with fresh credentials (MI token rotation).

    Called during the background token refresh cycle. Creates a new pool
    with fresh credentials, then closes the old one.

    Args:
        app: FastAPI application instance.
    """
    # Guard: only refresh if pool was initialized
    if not hasattr(app.state, "readpool") or app.state.readpool is None:
        logger.debug("STAC pool not initialized, skipping refresh")
        return

    # Prevent concurrent refresh
    # Lock is eagerly initialized in app.py lifespan startup
    if app.state._stac_refresh_lock.locked():
        logger.info("STAC pool refresh already in progress, skipping")
        return

    async with app.state._stac_refresh_lock:
        logger.info("Refreshing STAC connection pool...")
        try:
            old_readpool = getattr(app.state, "readpool", None)
            old_writepool = getattr(app.state, "writepool", None)

            # Create new pool (overwrites app.state.readpool/writepool/get_connection)
            pg_settings = _build_stac_postgres_settings()
            await stac_connect_to_db(app, postgres_settings=pg_settings)

            # Close old pools (if they differ from the new ones)
            for old_pool in (old_readpool, old_writepool):
                if old_pool and old_pool is not app.state.readpool and old_pool is not app.state.writepool:
                    try:
                        await old_pool.close()
                    except Exception as close_err:
                        logger.warning(f"Error closing old STAC pool: {close_err}")

            logger.info("STAC pool refresh complete")
        except Exception as e:
            logger.error(f"STAC pool refresh failed: {e}")
            logger.warning("Keeping existing STAC pool (old token may still be valid)")
