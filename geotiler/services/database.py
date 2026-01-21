"""
Database connection helpers and health check utilities.

Provides database ping functionality for health probes and
manages database pool access via explicit dependency injection.

All ping functions have async versions that use asyncio.to_thread()
to avoid blocking the event loop during database operations.

Note: No module-level mutable state - all state accessed via Request or app parameter.
"""

import asyncio
import time
import logging
from typing import Tuple, Optional, TYPE_CHECKING

from psycopg_pool import ConnectionPool
from starlette.datastructures import State

from geotiler.auth.cache import db_error_cache

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request

logger = logging.getLogger(__name__)


# =============================================================================
# State Access Functions (no globals - use Request or app parameter)
# =============================================================================


def get_app_state_from_request(request: "Request") -> State:
    """
    Get app state from request (for FastAPI dependency injection).

    Args:
        request: FastAPI/Starlette Request object.

    Returns:
        FastAPI app.state object.
    """
    return request.app.state


def get_app_state_from_app(app: "FastAPI") -> State:
    """
    Get app state from app instance (for non-request contexts).

    Args:
        app: FastAPI application instance.

    Returns:
        FastAPI app.state object.
    """
    return app.state


def get_db_pool_from_request(request: "Request") -> Optional[ConnectionPool]:
    """
    Get database pool from request (for FastAPI dependency injection).

    Args:
        request: FastAPI/Starlette Request object.

    Returns:
        Database pool if available, None otherwise.
    """
    return getattr(request.app.state, "dbpool", None)


def get_db_pool_from_app(app: "FastAPI") -> Optional[ConnectionPool]:
    """
    Get database pool from app instance (for non-request contexts).

    Args:
        app: FastAPI application instance.

    Returns:
        Database pool if available, None otherwise.
    """
    return getattr(app.state, "dbpool", None)


# =============================================================================
# Core Ping Implementation (takes pool directly - no global state)
# =============================================================================


def _ping_database_impl(pool: Optional[ConnectionPool]) -> Tuple[bool, Optional[str]]:
    """
    Ping database using provided pool.

    Internal implementation - use ping_database_async() for request handlers.

    Args:
        pool: Database connection pool.

    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    if not pool:
        return False, "pool not initialized"

    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        db_error_cache.record_success()
        return True, None
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)}"
        db_error_cache.record_error(error)
        return False, type(e).__name__


def _ping_database_with_timing_impl(
    pool: Optional[ConnectionPool],
) -> Tuple[bool, Optional[str], Optional[float]]:
    """
    Ping database with timing using provided pool.

    Internal implementation - use ping_database_with_timing_async() for request handlers.

    Args:
        pool: Database connection pool.

    Returns:
        Tuple of (success: bool, error_message: Optional[str], ping_time_ms: Optional[float])
    """
    if not pool:
        return False, "pool not initialized", None

    start = time.monotonic()
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        ping_ms = round((time.monotonic() - start) * 1000, 2)
        db_error_cache.record_success()
        return True, None, ping_ms
    except Exception as e:
        ping_ms = round((time.monotonic() - start) * 1000, 2)
        error = f"{type(e).__name__}: {str(e)}"
        db_error_cache.record_error(error)
        return False, type(e).__name__, ping_ms


# =============================================================================
# Async Versions for Request Handlers (use asyncio.to_thread)
# =============================================================================


async def ping_database_async(request: "Request") -> Tuple[bool, Optional[str]]:
    """
    Ping database and return status (async version for request handlers).

    Extracts pool from request and runs the blocking ping in a thread pool.

    Args:
        request: FastAPI/Starlette Request object.

    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    pool = get_db_pool_from_request(request)
    return await asyncio.to_thread(_ping_database_impl, pool)


async def ping_database_with_timing_async(
    request: "Request",
) -> Tuple[bool, Optional[str], Optional[float]]:
    """
    Ping database with timing (async version for request handlers).

    Extracts pool from request and runs the blocking ping in a thread pool.

    Args:
        request: FastAPI/Starlette Request object.

    Returns:
        Tuple of (success: bool, error_message: Optional[str], ping_time_ms: Optional[float])
    """
    pool = get_db_pool_from_request(request)
    return await asyncio.to_thread(_ping_database_with_timing_impl, pool)


async def is_database_ready_async(request: "Request") -> bool:
    """
    Check if database is ready for queries (async version).

    Args:
        request: FastAPI/Starlette Request object.

    Returns:
        True if database is accessible, False otherwise.
    """
    success, _ = await ping_database_async(request)
    return success
