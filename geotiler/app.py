"""
FastAPI application factory for geotiler.

Creates and configures the TiTiler application with:
- Azure Managed Identity authentication for blob storage
- TiTiler-core (COG tiles via rio-tiler 8.x)
- TiTiler-pgstac (STAC catalog searches - dynamic mosaics)
- TiTiler-xarray (Zarr/NetCDF multidimensional data)
- TiPG (OGC Features API + Vector Tiles for PostGIS)
- Health probe endpoints (/livez, /readyz, /health)
- Request timing and observability (when OBSERVABILITY_MODE=true)

Entry Point:
    Always use geotiler.main:app which configures Azure Monitor telemetry
    and structured logging before FastAPI is imported.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from geotiler import __version__
from geotiler.config import settings
from geotiler.middleware.azure_auth import AzureAuthMiddleware
from geotiler.infrastructure.middleware import RequestTimingMiddleware
from geotiler.routers import health, admin, vector, stac, diagnostics
from geotiler.routers import cog_landing, xarray_landing, searches_landing, stac_explorer, docs_guide, map_viewer, h3_explorer
from geotiler.services.background import start_token_refresh
from geotiler.services.duckdb import initialize_duckdb, close_duckdb
from geotiler.auth.storage import initialize_storage_auth
from geotiler.auth.postgres import get_postgres_credential, build_database_url
from geotiler.auth.cache import db_error_cache

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
    logger.info(f"Starting geotiler v{__version__} (auth_use_cli={settings.auth_use_cli}, storage_auth={settings.enable_storage_auth}, pg_auth={settings.pg_auth_mode})")

    # Initialize database connection (titiler-pgstac)
    await _initialize_database(app)

    # Initialize TiPG (OGC Features + Vector Tiles)
    if settings.enable_tipg and settings.has_postgres_config:
        await vector.initialize_tipg(app)

    # Initialize storage OAuth
    initialize_storage_auth()

    # Start background token refresh
    if settings.enable_storage_auth:
        app.state.refresh_task = start_token_refresh(app)

    # Initialize H3 DuckDB (server-side parquet queries)
    if settings.enable_h3_duckdb and settings.h3_parquet_url:
        await initialize_duckdb(app)

    logger.info(f"Startup complete: geotiler v{__version__}")

    yield  # Application runs here

    # =========================================================================
    # SHUTDOWN
    # =========================================================================
    logger.info("Shutting down geotiler...")

    # Close H3 DuckDB
    if settings.enable_h3_duckdb:
        await close_duckdb(app)

    # Close TiPG pool
    if settings.enable_tipg:
        await vector.close_tipg(app)

    # Close titiler-pgstac pool
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
        logger.warning(f"  GEOTILER_PG_HOST: {settings.pg_host or '(not set)'}")
        logger.warning(f"  GEOTILER_PG_DB: {settings.pg_db or '(not set)'}")
        logger.warning(f"  GEOTILER_PG_USER: {settings.pg_user or '(not set)'}")
        logger.warning("")
        logger.warning("App will start but database features will not work.")
        logger.warning("=" * 60)
        db_error_cache.record_error("Missing PostgreSQL configuration")
        return

    # Get credential based on auth mode
    try:
        logger.info(f"PostgreSQL Authentication Mode: {settings.pg_auth_mode}")
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
    logger.info(f"  Host: {settings.pg_host}")
    logger.info(f"  Database: {settings.pg_db}")
    logger.info(f"  User: {settings.pg_user}")

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
    """
    Mount all TiTiler routers.

    Endpoint Overview:
    - /cog/* - Cloud Optimized GeoTIFF tiles (rio-tiler 8.x)
    - /xarray/* - Zarr/NetCDF multidimensional data (titiler.xarray)
    - /searches/* - pgSTAC dynamic mosaics (STAC catalog searches)
    """

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


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="geotiler",
        description=(
            "Geospatial tile server with Azure Managed Identity authentication.\n\n"
            "| Prefix | Service |\n"
            "|--------|---------|\n"
            "| `/cog/*` | Cloud Optimized GeoTIFF tiles |\n"
            "| `/xarray/*` | Zarr / NetCDF multidimensional data |\n"
            "| `/searches/*` | pgSTAC dynamic mosaic searches |\n"
            "| `/stac/*` | STAC catalog browsing and search |\n"
            "| `/vector/*` | OGC Features API + Vector Tiles (TiPG) |\n"
            "| `/h3/*` | H3 Crop Production & Drought Risk Explorer |\n"
        ),
        version=__version__,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "Health", "description": "Liveness, readiness, and detailed health probes."},
            {"name": "Cloud Optimized GeoTIFF", "description": "COG tile serving via GDAL `/vsiaz/`."},
            {"name": "Multidimensional (Zarr/NetCDF)", "description": "Zarr and NetCDF tile serving via xarray."},
            {"name": "STAC Search", "description": "pgSTAC dynamic mosaic search and tile rendering."},
            {"name": "STAC Catalog", "description": "STAC API for catalog browsing, search, and filtering."},
            {"name": "OGC Vector -- Features", "description": "OGC Features API endpoints (TiPG)."},
            {"name": "OGC Vector -- Tiles", "description": "OGC Vector Tiles endpoints (TiPG)."},
            {"name": "OGC Vector -- Common", "description": "OGC API common endpoints (TiPG)."},
            {"name": "Diagnostics", "description": "Database and TiPG table-discovery diagnostics."},
            {"name": "H3 Explorer", "description": "H3 Crop Production & Drought Risk Explorer."},
            {"name": "API Info", "description": "API metadata and endpoint listing."},
            {"name": "Admin", "description": "Admin dashboard and operational webhooks."},
        ],
    )

    # =========================================================================
    # Static Files & Templates
    # =========================================================================
    static_dir = Path(__file__).parent / "static"
    templates_dir = Path(__file__).parent / "templates"

    # Mount static files (CSS, JS)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Configure Jinja2 templates (store in app.state for router access)
    app.state.templates = Jinja2Templates(directory=templates_dir)

    # =========================================================================
    # Middleware (order matters - first added = outermost = runs first)
    # =========================================================================
    # Note: CORS is handled by infrastructure (Azure APIM / Cloudflare CDN),
    # not by the application. This app runs behind reverse proxies that manage
    # cross-origin access, caching, and security policies.

    # Request timing - Captures latency, status, response size for all requests
    # Only logs when OBSERVABILITY_MODE=true (zero overhead otherwise)
    app.add_middleware(RequestTimingMiddleware)

    # Azure auth - Configures OAuth tokens for Azure Blob Storage access
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

    # TiPG OGC Features + Vector Tiles
    if settings.enable_tipg:
        tipg_endpoints = vector.create_tipg_endpoints()
        app.include_router(
            tipg_endpoints.router,
            prefix=settings.tipg_prefix,
            tags=["OGC Vector (TiPG)"],
        )
        logger.info(f"TiPG router mounted at {settings.tipg_prefix}")

        # Optional: CatalogUpdateMiddleware for automatic catalog refresh
        if settings.enable_tipg_catalog_ttl:
            from tipg.middleware import CatalogUpdateMiddleware
            from tipg.collections import register_collection_catalog
            from tipg.settings import DatabaseSettings as TiPGDatabaseSettings

            db_settings = TiPGDatabaseSettings(schemas=settings.tipg_schema_list)
            app.add_middleware(
                CatalogUpdateMiddleware,
                func=register_collection_catalog,
                ttl=settings.tipg_catalog_ttl_sec,
                db_settings=db_settings,
            )
            logger.info(
                f"TiPG CatalogUpdateMiddleware enabled: TTL={settings.tipg_catalog_ttl_sec}s"
            )

        # TiPG diagnostics endpoint (for debugging table discovery)
        app.include_router(diagnostics.router, tags=["Diagnostics"])

    # STAC API (stac-fastapi-pgstac)
    # Note: Requires TiPG to be enabled (shares asyncpg pool)
    if settings.enable_stac_api and settings.enable_tipg:
        try:
            # StacApi adds routes directly to app with router_prefix
            stac.create_stac_api(app)
            logger.info(f"STAC API routes added at {settings.stac_prefix}")
        except Exception as e:
            logger.error(f"Failed to create STAC API: {e}")
            logger.warning("STAC API will not be available")
    elif settings.enable_stac_api and not settings.enable_tipg:
        logger.warning("STAC API requires TiPG to be enabled (shared pool)")
        logger.warning("Set GEOTILER_ENABLE_TIPG=true to enable STAC API")

    # Landing pages for TiTiler components
    app.include_router(cog_landing.router, tags=["Landing Pages"])
    app.include_router(xarray_landing.router, tags=["Landing Pages"])
    app.include_router(searches_landing.router, tags=["Landing Pages"])

    # STAC Explorer GUI
    if settings.enable_stac_api and settings.enable_tipg:
        app.include_router(stac_explorer.router, tags=["STAC Explorer"])

    # Documentation guides
    app.include_router(docs_guide.router, tags=["Documentation"])

    # Map Viewer
    app.include_router(map_viewer.router, tags=["Map Viewer"])

    # H3 Crop Production & Drought Risk Explorer
    app.include_router(h3_explorer.router, tags=["H3 Explorer"])

    # Admin console (HTML at /, JSON at /api)
    app.include_router(admin.router)

    # Post-process OpenAPI spec (fix upstream tags/descriptions)
    from geotiler.openapi import customize_openapi
    app.openapi = lambda: customize_openapi(app)

    return app
