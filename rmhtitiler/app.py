"""
FastAPI application factory for rmhtitiler.

Creates and configures the TiTiler application with:
- Azure Managed Identity authentication for blob storage
- TiTiler-core (COG tiles)
- TiTiler-pgstac (STAC catalog searches)
- TiTiler-xarray (Zarr/NetCDF multidimensional data)
- Health probe endpoints
- Planetary Computer integration
- NiceGUI dashboard (optional)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rmhtitiler import __version__
from rmhtitiler.config import settings
from rmhtitiler.middleware.azure_auth import AzureAuthMiddleware
from rmhtitiler.routers import health, planetary_computer, root
from rmhtitiler.services.database import set_app_state
from rmhtitiler.services.background import start_token_refresh
from rmhtitiler.auth.storage import initialize_storage_auth
from rmhtitiler.auth.postgres import get_postgres_credential, build_database_url
from rmhtitiler.auth.cache import db_error_cache

# TiTiler imports
from titiler.core.factory import TilerFactory
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.pgstac.factory import (
    MosaicTilerFactory,
    add_search_list_route,
    add_search_register_route,
)
from titiler.pgstac.db import close_db_connection, connect_to_db
from titiler.pgstac.dependencies import SearchIdParams
from titiler.pgstac.settings import PostgresSettings
from titiler.xarray.factory import TilerFactory as XarrayTilerFactory
from titiler.xarray.extensions import VariablesExtension
from titiler.mosaic.factory import MosaicTilerFactory as BaseMosaicTilerFactory

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler - manages startup and shutdown.

    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown").
    """
    # =========================================================================
    # STARTUP
    # =========================================================================
    logger.info("=" * 60)
    logger.info(f"Starting rmhtitiler v{__version__}")
    logger.info("=" * 60)
    logger.info(f"Local mode: {settings.local_mode}")
    logger.info(f"Azure Storage auth: {settings.use_azure_auth}")
    logger.info(f"PostgreSQL auth mode: {settings.postgres_auth_mode}")

    # Initialize database connection
    await _initialize_database(app)

    # Initialize storage OAuth
    initialize_storage_auth()

    # Start background token refresh
    if settings.use_azure_auth:
        start_token_refresh(app)

    # Set app state reference for health checks
    set_app_state(app.state)

    logger.info("=" * 60)
    logger.info("Startup complete")
    logger.info("=" * 60)

    yield  # Application runs here

    # =========================================================================
    # SHUTDOWN
    # =========================================================================
    logger.info("Shutting down rmhtitiler...")
    await close_db_connection(app)
    logger.info("Shutdown complete")


async def _initialize_database(app: FastAPI) -> None:
    """
    Initialize database connection based on auth mode.

    Non-fatal if fails - app will start in degraded mode.
    """
    # Check required config
    if not settings.has_postgres_config:
        logger.warning("=" * 60)
        logger.warning("Missing PostgreSQL environment variables!")
        logger.warning(f"  POSTGRES_HOST: {settings.postgres_host or '(not set)'}")
        logger.warning(f"  POSTGRES_DB: {settings.postgres_db or '(not set)'}")
        logger.warning(f"  POSTGRES_USER: {settings.postgres_user or '(not set)'}")
        logger.warning("")
        logger.warning("App will start but database features will not work.")
        logger.warning("=" * 60)
        db_error_cache.record_error("Missing PostgreSQL configuration")
        return

    # Get credential based on auth mode
    try:
        logger.info(f"PostgreSQL Authentication Mode: {settings.postgres_auth_mode}")
        credential = get_postgres_credential()

        if not credential:
            logger.error("Failed to get PostgreSQL credential")
            db_error_cache.record_error("Failed to get PostgreSQL credential")
            return

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Failed to acquire PostgreSQL credential: {error_msg}")
        logger.warning("App will start in degraded mode")
        db_error_cache.record_error(error_msg)
        return

    # Build connection URL
    database_url = build_database_url(credential)

    logger.info(f"Connecting to PostgreSQL...")
    logger.info(f"  Host: {settings.postgres_host}")
    logger.info(f"  Database: {settings.postgres_db}")
    logger.info(f"  User: {settings.postgres_user}")

    # Connect to database
    try:
        db_settings = PostgresSettings(database_url=database_url)
        await connect_to_db(app, settings=db_settings)
        logger.info("Database connection established")
        db_error_cache.record_success()

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Failed to connect to database: {error_msg}")
        logger.error("")
        logger.error("Troubleshooting:")
        logger.error("  - Verify PostgreSQL server is running")
        logger.error("  - Verify user exists in database")
        logger.error("  - Verify MI token is valid (if using MI)")
        logger.error("  - Check firewall rules allow App Service")
        logger.warning("")
        logger.warning("App will start in degraded mode - database features unavailable")
        db_error_cache.record_error(error_msg)


def _mount_titiler_routers(app: FastAPI) -> None:
    """Mount all TiTiler routers."""

    # =========================================================================
    # TiTiler COG Endpoint - Direct file access
    # =========================================================================
    cog = TilerFactory(
        router_prefix="/cog",
        add_viewer=True,
    )
    app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])

    # =========================================================================
    # TiTiler Xarray Endpoint - Zarr/NetCDF multidimensional data
    # =========================================================================
    xarray_tiler = XarrayTilerFactory(
        router_prefix="/xarray",
        extensions=[
            VariablesExtension(),  # Adds /variables endpoint
        ],
    )
    app.include_router(
        xarray_tiler.router, prefix="/xarray", tags=["Multidimensional (Zarr/NetCDF)"]
    )

    # =========================================================================
    # TiTiler MosaicJSON Endpoint - For MosaicJSON files
    # =========================================================================
    mosaic_json = BaseMosaicTilerFactory(
        router_prefix="/mosaicjson",
        add_viewer=True,
    )
    app.include_router(mosaic_json.router, prefix="/mosaicjson", tags=["MosaicJSON"])

    # =========================================================================
    # TiTiler-pgSTAC Search Endpoints - For STAC catalog searches
    # =========================================================================
    pgstac_mosaic = MosaicTilerFactory(
        path_dependency=SearchIdParams,
        router_prefix="/searches/{search_id}",
        add_statistics=True,
        add_viewer=True,
    )
    app.include_router(
        pgstac_mosaic.router, prefix="/searches/{search_id}", tags=["STAC Search"]
    )

    # Add search management routes
    add_search_list_route(app, prefix="/searches", tags=["STAC Search"])
    add_search_register_route(
        app,
        prefix="/searches",
        tile_dependencies=[
            pgstac_mosaic.layer_dependency,
            pgstac_mosaic.dataset_dependency,
            pgstac_mosaic.pixel_selection_dependency,
            pgstac_mosaic.process_dependency,
            pgstac_mosaic.render_dependency,
            pgstac_mosaic.assets_accessor_dependency,
            pgstac_mosaic.reader_dependency,
            pgstac_mosaic.backend_dependency,
        ],
        tags=["STAC Search"],
    )


def _mount_dashboard(app: FastAPI) -> None:
    """Mount NiceGUI dashboard if available."""
    try:
        from dashboard.main import mount_dashboard

        mount_dashboard(app)
        logger.info("NiceGUI Dashboard mounted at /dashboard")
    except ImportError as e:
        logger.warning(f"Dashboard not available: {e}")
        logger.info("Install nicegui>=2.0.0 and httpx>=0.27.0 to enable the dashboard")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="TiTiler-pgSTAC with Azure OAuth + Xarray + Planetary Computer",
        description="STAC catalog tile server with Managed Identity authentication, "
        "Zarr/NetCDF support, and Planetary Computer integration",
        version=__version__,
        lifespan=lifespan,
    )

    # =========================================================================
    # Middleware
    # =========================================================================
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AzureAuthMiddleware)

    # =========================================================================
    # Exception handlers
    # =========================================================================
    add_exception_handlers(app, DEFAULT_STATUS_CODES)

    # =========================================================================
    # Routers
    # =========================================================================

    # Health probes
    app.include_router(health.router)

    # TiTiler endpoints
    _mount_titiler_routers(app)

    # Planetary Computer endpoints
    if settings.enable_planetary_computer:
        app.include_router(planetary_computer.router)

    # Root info endpoint
    app.include_router(root.router)

    # Dashboard
    if settings.enable_dashboard:
        _mount_dashboard(app)

    return app


# Create app instance for uvicorn
app = create_app()
