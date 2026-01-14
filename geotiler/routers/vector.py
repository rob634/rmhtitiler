"""
TiPG integration for OGC Features + Vector Tiles.

Provides OGC API - Features and OGC API - Tiles endpoints for PostGIS tables,
complementing TiTiler's raster tile capabilities.

Key integration points:
- Uses same PostgreSQL credentials as titiler-pgstac (Managed Identity)
- Separate asyncpg connection pool (app.state.pool)
- Pool refreshes synchronized with token refresh cycle
"""

import logging
from typing import TYPE_CHECKING

from tipg.settings import PostgresSettings as TiPGPostgresSettings
from tipg.settings import DatabaseSettings as TiPGDatabaseSettings
from tipg.database import connect_to_db as tipg_connect_to_db
from tipg.database import close_db_connection as tipg_close_db_connection
from tipg.collections import register_collection_catalog
from tipg.factory import Endpoints as TiPGEndpoints

# Import STAC API database function for pool sharing
from stac_fastapi.pgstac.db import get_connection as stac_get_connection

from geotiler.config import settings
from geotiler.auth.postgres import get_postgres_credential, build_database_url

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def get_tipg_postgres_settings(schemas: list[str] | None = None) -> TiPGPostgresSettings:
    """
    Build TiPG PostgresSettings using geotiler's Azure auth.

    Reuses the existing credential acquisition (Managed Identity or password)
    to create a database URL for TiPG's asyncpg connection pool.

    Args:
        schemas: Optional list of schemas to include in search_path.
                 If provided, these are set at the connection level.

    Returns:
        TiPGPostgresSettings configured with authenticated database URL.

    Raises:
        Exception: If credential acquisition fails.
    """
    credential = get_postgres_credential()
    if not credential:
        raise RuntimeError("Failed to get PostgreSQL credential for TiPG")

    # Build search_path string from schemas list
    # Always include 'public' for PostGIS types (geometry, geography, etc.)
    search_path = None
    if schemas:
        search_path_schemas = schemas.copy()
        if "public" not in search_path_schemas:
            search_path_schemas.append("public")
        search_path = ",".join(search_path_schemas)

    database_url = build_database_url(credential, search_path=search_path)

    return TiPGPostgresSettings(database_url=database_url)


def get_tipg_database_settings() -> TiPGDatabaseSettings:
    """
    Build TiPG DatabaseSettings from geotiler config.

    Returns:
        TiPGDatabaseSettings with schemas to expose.
    """
    return TiPGDatabaseSettings(schemas=settings.tipg_schema_list)


async def initialize_tipg(app: "FastAPI") -> None:
    """
    Initialize TiPG connection pool and collection catalog.

    Creates an asyncpg connection pool stored in app.state.pool
    and registers available PostGIS collections.

    Args:
        app: FastAPI application instance.
    """
    logger.info("=" * 60)
    logger.info("Initializing TiPG (OGC Features + Vector Tiles)")
    logger.info("=" * 60)
    logger.info(f"Schemas to expose: {settings.tipg_schema_list}")
    logger.info(f"Router prefix: {settings.tipg_router_prefix}")

    try:
        # Build schemas list for search_path
        schemas = settings.tipg_schema_list.copy()

        # Add pgstac schema if STAC API is enabled (stac-fastapi-pgstac needs it in search_path)
        if settings.enable_stac_api and "pgstac" not in schemas:
            schemas.append("pgstac")
            logger.info("Added pgstac schema for STAC API support")

        # Get settings using our auth system (pass schemas for connection-level search_path)
        postgres_settings = get_tipg_postgres_settings(schemas=schemas)
        db_settings = get_tipg_database_settings()

        # Create asyncpg connection pool (schemas is required keyword arg)
        await tipg_connect_to_db(app, settings=postgres_settings, schemas=schemas)
        logger.info(f"TiPG asyncpg connection pool created with schemas: {schemas}")

        # Set up STAC API database aliases to share the pool
        # stac-fastapi-pgstac expects readpool/writepool and get_connection
        if settings.enable_stac_api:
            app.state.readpool = app.state.pool
            app.state.writepool = app.state.pool
            app.state.get_connection = stac_get_connection
            logger.info("STAC API database aliases configured (shared pool)")

        # Register collections from PostGIS schemas
        await register_collection_catalog(app, db_settings=db_settings)
        logger.info("TiPG collection catalog registered")

        # Log discovered collections
        if hasattr(app.state, "collection_catalog"):
            catalog = app.state.collection_catalog
            collection_count = len(catalog) if catalog else 0
            logger.info(f"TiPG discovered {collection_count} collections")

        logger.info("TiPG initialization complete")

    except Exception as e:
        logger.error("=" * 60)
        logger.error("TIPG INITIALIZATION FAILED")
        logger.error("=" * 60)
        logger.error(f"Error: {type(e).__name__}: {e}")
        logger.error("")
        logger.error("TiPG endpoints will not be available.")
        logger.error("App will continue without vector tile support.")
        logger.error("=" * 60)
        # Don't raise - allow app to start in degraded mode


async def close_tipg(app: "FastAPI") -> None:
    """
    Close TiPG connection pool.

    Args:
        app: FastAPI application instance.
    """
    if hasattr(app.state, "pool") and app.state.pool:
        try:
            await tipg_close_db_connection(app)
            logger.info("TiPG connection pool closed")
        except Exception as e:
            logger.warning(f"Error closing TiPG pool: {e}")


async def refresh_tipg_pool(app: "FastAPI") -> None:
    """
    Refresh TiPG connection pool with new credentials.

    Called during token refresh cycle to recreate pool with fresh
    Managed Identity token.

    Args:
        app: FastAPI application instance.
    """
    if not hasattr(app.state, "pool"):
        logger.debug("TiPG pool not initialized, skipping refresh")
        return

    logger.info("Refreshing TiPG connection pool...")

    try:
        # Close existing pool
        await tipg_close_db_connection(app)

        # Build schemas list for search_path
        schemas = settings.tipg_schema_list.copy()

        # Add pgstac schema if STAC API is enabled
        if settings.enable_stac_api and "pgstac" not in schemas:
            schemas.append("pgstac")

        # Get fresh credentials and settings (pass schemas for connection-level search_path)
        postgres_settings = get_tipg_postgres_settings(schemas=schemas)
        db_settings = get_tipg_database_settings()

        # Create new pool
        await tipg_connect_to_db(app, settings=postgres_settings, schemas=schemas)

        # Re-register collection catalog
        await register_collection_catalog(app, db_settings=db_settings)

        # Re-establish STAC API database aliases
        if settings.enable_stac_api:
            app.state.readpool = app.state.pool
            app.state.writepool = app.state.pool
            app.state.get_connection = stac_get_connection

        logger.info("TiPG pool refresh complete")

    except Exception as e:
        logger.error(f"TiPG pool refresh failed: {e}")


def create_tipg_endpoints() -> TiPGEndpoints:
    """
    Create TiPG endpoint factory with configured options.

    Returns:
        TiPGEndpoints instance ready to be mounted on FastAPI app.
    """
    return TiPGEndpoints(
        with_tiles_viewer=True,  # Include MapLibre map viewer
        router_prefix=settings.tipg_router_prefix,  # URL prefix for generated links
    )
