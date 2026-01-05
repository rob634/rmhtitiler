"""
Background services for token refresh and maintenance tasks.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from rmhtitiler.config import settings, BACKGROUND_REFRESH_INTERVAL_SECS
from rmhtitiler.auth.storage import refresh_storage_token
from rmhtitiler.auth.postgres import refresh_postgres_token, build_database_url

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Reference to the FastAPI app for database pool recreation
_app: "FastAPI" = None


def set_app_reference(app: "FastAPI") -> None:
    """Set the app reference for background tasks that need it."""
    global _app
    _app = app


async def token_refresh_background_task():
    """
    Background task that proactively refreshes OAuth tokens.

    Refreshes both Storage and PostgreSQL tokens to prevent expiration.
    Runs every 45 minutes by default.
    """
    while True:
        await asyncio.sleep(BACKGROUND_REFRESH_INTERVAL_SECS)

        logger.info("=" * 60)
        logger.info("Background token refresh triggered")
        logger.info("=" * 60)

        # ====================================================================
        # Refresh Storage Token
        # ====================================================================
        if settings.use_azure_auth and settings.azure_storage_account:
            refresh_storage_token()

        # ====================================================================
        # Refresh PostgreSQL Token (if using managed_identity)
        # ====================================================================
        if settings.postgres_auth_mode == "managed_identity":
            await _refresh_postgres_with_pool_recreation()

        logger.info(f"Next refresh in {BACKGROUND_REFRESH_INTERVAL_SECS // 60} minutes")
        logger.info("=" * 60)


async def _refresh_postgres_with_pool_recreation():
    """
    Refresh PostgreSQL token and recreate connection pool.

    When using managed identity for PostgreSQL, the OAuth token is embedded
    in the connection string. When the token is refreshed, we need to
    recreate the connection pool with the new token.
    """
    try:
        new_token = refresh_postgres_token()
        if not new_token:
            logger.warning("PostgreSQL token refresh returned no token")
            return

        if not _app:
            logger.warning("App reference not set, cannot recreate connection pool")
            return

        # Rebuild DATABASE_URL with new token
        new_database_url = build_database_url(new_token)

        # Import here to avoid circular imports
        from titiler.pgstac.db import close_db_connection, connect_to_db
        from titiler.pgstac.settings import PostgresSettings

        try:
            # Close existing pool
            await close_db_connection(_app)
            logger.info("Closed existing database connection pool")

            # Create new pool with fresh token
            db_settings = PostgresSettings(database_url=new_database_url)
            await connect_to_db(_app, settings=db_settings)
            logger.info("PostgreSQL token refresh complete - new connection pool created")

        except Exception as pool_err:
            logger.error(f"Failed to recreate connection pool: {pool_err}")

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
    set_app_reference(app)
    task = asyncio.create_task(token_refresh_background_task())
    logger.info(f"Background token refresh task started ({BACKGROUND_REFRESH_INTERVAL_SECS // 60}-minute interval)")
    return task
