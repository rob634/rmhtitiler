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

from rmhtitiler.config import settings
from rmhtitiler.auth.postgres import get_postgres_credential, build_database_url

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def get_tipg_postgres_settings() -> TiPGPostgresSettings:
    """
    Build TiPG PostgresSettings using rmhtitiler's Azure auth.

    Reuses the existing credential acquisition (Managed Identity or password)
    to create a database URL for TiPG's asyncpg connection pool.

    Returns:
        TiPGPostgresSettings configured with authenticated database URL.

    Raises:
        Exception: If credential acquisition fails.
    """
    credential = get_postgres_credential()
    if not credential:
        raise RuntimeError("Failed to get PostgreSQL credential for TiPG")

    database_url = build_database_url(credential)

    return TiPGPostgresSettings(database_url=database_url)


def get_tipg_database_settings() -> TiPGDatabaseSettings:
    """
    Build TiPG DatabaseSettings from rmhtitiler config.

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
        # Get settings using our auth system
        postgres_settings = get_tipg_postgres_settings()
        db_settings = get_tipg_database_settings()

        # Create asyncpg connection pool
        await tipg_connect_to_db(app, settings=postgres_settings)
        logger.info("TiPG asyncpg connection pool created (app.state.pool)")

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

        # Get fresh credentials and settings
        postgres_settings = get_tipg_postgres_settings()
        db_settings = get_tipg_database_settings()

        # Create new pool
        await tipg_connect_to_db(app, settings=postgres_settings)

        # Re-register collection catalog
        await register_collection_catalog(app, db_settings=db_settings)

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
    )
