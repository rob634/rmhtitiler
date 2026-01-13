"""
Database connection helpers and health check utilities.

Provides database ping functionality for health probes and
manages the app state reference for database access.
"""

import time
import logging
from typing import Tuple, Optional, Any

from geotiler.auth.cache import db_error_cache

logger = logging.getLogger(__name__)

# Reference to FastAPI app.state, set during startup
_app_state: Optional[Any] = None


def set_app_state(state: Any) -> None:
    """
    Set the app state reference for database access.

    Called during application startup to provide access to app.state.dbpool.

    Args:
        state: FastAPI app.state object.
    """
    global _app_state
    _app_state = state
    logger.debug("Database service app state configured")


def get_app_state() -> Optional[Any]:
    """
    Get the FastAPI app state.

    Returns:
        FastAPI app.state if available, None otherwise.
    """
    return _app_state


def get_db_pool() -> Optional[Any]:
    """
    Get the database connection pool.

    Returns:
        Database pool if available, None otherwise.
    """
    if not _app_state:
        return None
    return getattr(_app_state, "dbpool", None)


def ping_database() -> Tuple[bool, Optional[str]]:
    """
    Ping database and return status.

    Performs a simple SELECT 1 query to verify database connectivity.
    Updates error cache for health reporting.

    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    pool = get_db_pool()

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


def ping_database_with_timing() -> Tuple[bool, Optional[str], Optional[float]]:
    """
    Ping database and return status with timing.

    Like ping_database() but also returns the ping duration in milliseconds.

    Returns:
        Tuple of (success: bool, error_message: Optional[str], ping_time_ms: Optional[float])
    """
    pool = get_db_pool()

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


def is_database_ready() -> bool:
    """
    Check if database is ready for queries.

    Simple boolean check for readiness probes.

    Returns:
        True if database is accessible, False otherwise.
    """
    success, _ = ping_database()
    return success
