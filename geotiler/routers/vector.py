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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

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


# =============================================================================
# STARTUP STATE TRACKING
# =============================================================================

class TiPGStartupState:
    """Captures TiPG initialization state for diagnostics."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset state (called before each init/refresh)."""
        self.last_init_time: Optional[datetime] = None
        self.last_init_type: Optional[str] = None  # "startup" or "refresh"
        self.schemas_configured: list[str] = []
        self.collections_discovered: int = 0
        self.collection_ids: list[str] = []
        self.init_success: bool = False
        self.init_error: Optional[str] = None
        self.search_path_used: Optional[str] = None

    def record_success(
        self,
        init_type: str,
        schemas: list[str],
        collection_count: int,
        collection_ids: list[str],
        search_path: str,
    ):
        """Record successful initialization."""
        self.last_init_time = datetime.now(timezone.utc)
        self.last_init_type = init_type
        self.schemas_configured = schemas
        self.collections_discovered = collection_count
        self.collection_ids = collection_ids[:50]  # Cap at 50 for diagnostics
        self.init_success = True
        self.init_error = None
        self.search_path_used = search_path

    def record_failure(self, init_type: str, error: str):
        """Record failed initialization."""
        self.last_init_time = datetime.now(timezone.utc)
        self.last_init_type = init_type
        self.init_success = False
        self.init_error = error

    def to_dict(self) -> dict:
        """Convert to dict for diagnostics endpoint."""
        return {
            "last_init_time": self.last_init_time.isoformat() if self.last_init_time else None,
            "last_init_type": self.last_init_type,
            "init_success": self.init_success,
            "init_error": self.init_error,
            "schemas_configured": self.schemas_configured,
            "search_path_used": self.search_path_used,
            "collections_discovered": self.collections_discovered,
            "collection_ids": self.collection_ids,
        }


# Note: TiPG state is stored in app.state.tipg_state (no module-level globals)


def get_tipg_startup_state_from_app(app: "FastAPI") -> Optional[TiPGStartupState]:
    """
    Get TiPG startup state from app (for non-request contexts).

    Args:
        app: FastAPI application instance.

    Returns:
        TiPGStartupState if initialized, None otherwise.
    """
    return getattr(app.state, "tipg_state", None)


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
    logger.info(f"Initializing TiPG: schemas={settings.tipg_schema_list} prefix={settings.tipg_prefix}")

    # Initialize TiPG state tracking (stored in app.state, not module global)
    app.state.tipg_state = TiPGStartupState()

    try:
        # Build schemas list for search_path
        schemas = settings.tipg_schema_list.copy()

        # Add pgstac schema if STAC API is enabled (stac-fastapi-pgstac needs it in search_path)
        if settings.enable_stac_api and "pgstac" not in schemas:
            schemas.append("pgstac")
            logger.debug("Added pgstac schema for STAC API support")

        # Get settings using our auth system (pass schemas for connection-level search_path)
        postgres_settings = get_tipg_postgres_settings(schemas=schemas)
        db_settings = get_tipg_database_settings()

        # Create asyncpg connection pool (schemas is required keyword arg)
        await tipg_connect_to_db(app, settings=postgres_settings, schemas=schemas)
        logger.debug(f"TiPG asyncpg pool created: schemas={schemas}")

        # Set up STAC API database aliases to share the pool
        # stac-fastapi-pgstac expects readpool/writepool and get_connection
        if settings.enable_stac_api:
            app.state.readpool = app.state.pool
            app.state.writepool = app.state.pool
            app.state.get_connection = stac_get_connection
            logger.debug("STAC API database aliases configured")

        # Register collections from PostGIS schemas
        await register_collection_catalog(app, db_settings=db_settings)
        logger.debug("TiPG collection catalog registered")

        # Log discovered collections and record startup state
        collection_count = 0
        collection_ids = []
        if hasattr(app.state, "collection_catalog"):
            catalog = app.state.collection_catalog
            collection_count = len(catalog) if catalog else 0
            collection_ids = list(catalog.keys()) if catalog else []
            logger.info(f"TiPG discovered {collection_count} collections")
            if collection_ids:
                logger.info(f"Collection IDs: {collection_ids[:10]}{'...' if len(collection_ids) > 10 else ''}")

        # Build search_path string for recording
        search_path_schemas = schemas.copy()
        if "public" not in search_path_schemas:
            search_path_schemas.append("public")
        search_path = ",".join(search_path_schemas)

        # Record successful startup
        app.state.tipg_state.record_success(
            init_type="startup",
            schemas=schemas,
            collection_count=collection_count,
            collection_ids=collection_ids,
            search_path=search_path,
        )

        logger.info("TiPG initialization complete")

    except Exception as e:
        # Record failed startup
        app.state.tipg_state.record_failure(init_type="startup", error=str(e))

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

        # Record refresh state
        collection_count = 0
        collection_ids = []
        if hasattr(app.state, "collection_catalog"):
            catalog = app.state.collection_catalog
            collection_count = len(catalog) if catalog else 0
            collection_ids = list(catalog.keys()) if catalog else []

        search_path_schemas = schemas.copy()
        if "public" not in search_path_schemas:
            search_path_schemas.append("public")
        search_path = ",".join(search_path_schemas)

        app.state.tipg_state.record_success(
            init_type="refresh",
            schemas=schemas,
            collection_count=collection_count,
            collection_ids=collection_ids,
            search_path=search_path,
        )

        logger.info(f"TiPG pool refresh complete - {collection_count} collections")

    except Exception as e:
        if hasattr(app.state, "tipg_state"):
            app.state.tipg_state.record_failure(init_type="refresh", error=str(e))
        logger.error(f"TiPG pool refresh failed: {e}")


def create_tipg_endpoints() -> TiPGEndpoints:
    """
    Create TiPG endpoint factory with configured options.

    Returns:
        TiPGEndpoints instance ready to be mounted on FastAPI app.
    """
    return TiPGEndpoints(
        with_tiles_viewer=True,  # Include MapLibre map viewer
        router_prefix=settings.tipg_prefix,  # URL prefix for generated links
    )
