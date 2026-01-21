"""
Background services for token refresh and maintenance tasks.

All token refresh operations use async wrappers that run blocking Azure SDK
calls in a thread pool via asyncio.to_thread(), ensuring the event loop
remains responsive during token acquisition.

Note: No module-level mutable state - app is passed explicitly to all functions.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from geotiler.config import settings, BACKGROUND_REFRESH_INTERVAL_SECS
from geotiler.auth.storage import refresh_storage_token_async
from geotiler.auth.postgres import refresh_postgres_token_async, build_database_url
from geotiler.routers.vector import refresh_tipg_pool

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def token_refresh_background_task(app: "FastAPI"):
    """
    Background task that proactively refreshes OAuth tokens.

    Refreshes both Storage and PostgreSQL tokens to prevent expiration.
    Runs every 45 minutes by default.

    All token refresh calls use asyncio.to_thread() internally to avoid
    blocking the event loop during Azure SDK HTTP operations.

    Args:
        app: FastAPI application instance (passed explicitly, no globals).
    """
    while True:
        await asyncio.sleep(BACKGROUND_REFRESH_INTERVAL_SECS)

        logger.debug("Background token refresh triggered")

        # Refresh Storage Token (async - runs in thread pool)
        if settings.use_azure_auth and settings.azure_storage_account:
            await refresh_storage_token_async()

        # Refresh PostgreSQL Token (if using managed_identity)
        if settings.postgres_auth_mode == "managed_identity":
            await _refresh_postgres_with_pool_recreation(app)

        logger.debug(f"Background refresh complete, next in {BACKGROUND_REFRESH_INTERVAL_SECS // 60}m")


async def _refresh_postgres_with_pool_recreation(app: "FastAPI"):
    """
    Refresh PostgreSQL token and recreate ALL connection pools.

    When using managed identity for PostgreSQL, the OAuth token is embedded
    in the connection string. When the token is refreshed, we need to
    recreate both connection pools with the new token:
    - titiler-pgstac pool (psycopg, app.state.dbpool)
    - TiPG pool (asyncpg, app.state.pool)

    Token refresh runs in thread pool via asyncio.to_thread() to avoid
    blocking the event loop during Azure SDK operations.

    Args:
        app: FastAPI application instance (passed explicitly, no globals).
    """
    try:
        # Refresh token (runs in thread pool)
        new_token = await refresh_postgres_token_async()
        if not new_token:
            logger.warning("PostgreSQL token refresh returned no token")
            return

        # Rebuild DATABASE_URL with new token
        new_database_url = build_database_url(new_token)

        # 1. Refresh titiler-pgstac pool (psycopg, app.state.dbpool)
        from titiler.pgstac.db import close_db_connection, connect_to_db
        from titiler.pgstac.settings import PostgresSettings

        try:
            await close_db_connection(app)
            db_settings = PostgresSettings(database_url=new_database_url)
            await connect_to_db(app, settings=db_settings)
            logger.debug("titiler-pgstac pool recreated with fresh token")

        except Exception as pool_err:
            logger.error(f"Failed to recreate titiler-pgstac pool: {pool_err}")

        # 2. Refresh TiPG pool (asyncpg, app.state.pool)
        if settings.enable_tipg:
            try:
                await refresh_tipg_pool(app)
            except Exception as tipg_err:
                logger.error(f"Failed to refresh TiPG pool: {tipg_err}")

    except Exception as e:
        logger.error(f"PostgreSQL token refresh failed: {e}")


def start_token_refresh(app: "FastAPI") -> asyncio.Task:
    """
    Start the background token refresh task.

    Args:
        app: FastAPI application instance.

    Returns:
        The created asyncio Task.
    """
    task = asyncio.create_task(token_refresh_background_task(app))
    logger.info(f"Background token refresh task started ({BACKGROUND_REFRESH_INTERVAL_SECS // 60}-minute interval)")
    return task
