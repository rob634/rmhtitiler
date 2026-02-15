"""
STAC API integration using stac-fastapi-pgstac.

Provides STAC API endpoints for catalog browsing and search,
complementing titiler-pgstac's tile rendering capabilities.

Key integration points:
- Shares asyncpg connection pool with TiPG (app.state.pool)
- Uses same PostgreSQL credentials (Managed Identity)
- Pool refresh synchronized with token refresh cycle

Architecture:
    The STAC API router is created at app startup (create_app) but the
    database pool is initialized during lifespan (after TiPG creates it).
    CoreCrudClient accesses app.state.pool at request time, so this works.
"""

import logging
from typing import Optional

from fastapi import APIRouter
from stac_fastapi.api.app import StacApi
from stac_fastapi.api.models import create_get_request_model, create_post_request_model
from stac_fastapi.extensions.core import (
    FieldsExtension,
    FilterExtension,
    SortExtension,
    TokenPaginationExtension,
)
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.pgstac.types.search import PgstacSearch
from stac_fastapi.pgstac.config import Settings as PgstacSettings

from geotiler.config import settings

logger = logging.getLogger(__name__)

# Module-level reference to StacApi instance
_stac_api: Optional[StacApi] = None


def create_stac_api(app) -> StacApi:
    """
    Create STAC API instance and add routes to the app.

    The StacApi is created at app startup. The database pool (app.state.pool)
    is initialized later during lifespan by TiPG. CoreCrudClient accesses
    the pool at request time via request.app.state.pool.

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

    # Create router with prefix so routes are mounted at /stac/*
    # StacApi derives router_prefix from router.prefix during __attrs_post_init__
    stac_router = APIRouter(prefix=settings.stac_prefix)

    # Create STAC API settings with geotiler branding
    stac_settings = PgstacSettings(
        stac_fastapi_title="geotiler STAC API",
        stac_fastapi_description="STAC API for pgSTAC catalog browsing and search",
    )

    # Create STAC API with main app and prefixed router
    # CoreCrudClient will access request.app.state.pool at request time
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
    )

    logger.info("STAC API created successfully")
    return _stac_api


def get_stac_api() -> Optional[StacApi]:
    """Get the initialized StacApi instance."""
    return _stac_api


def is_stac_api_available() -> bool:
    """Check if STAC API is available and initialized."""
    return _stac_api is not None
