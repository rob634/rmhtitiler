"""
Azure Storage OAuth authentication.

Handles OAuth token acquisition for Azure Blob Storage using Managed Identity
or Azure CLI credentials. Configures GDAL (COG /vsiaz/) and obstore (Zarr abfs://).
"""

import asyncio
import os
import logging
from datetime import datetime, timezone
from typing import Optional

from geotiler.config import settings, STORAGE_SCOPE, TOKEN_REFRESH_BUFFER_SECS
from geotiler.auth.cache import storage_token_cache

logger = logging.getLogger(__name__)


def get_storage_oauth_token() -> Optional[str]:
    """
    Get OAuth token for Azure Storage using Managed Identity.

    Token grants access to ALL containers based on the Managed Identity's
    RBAC role assignments (e.g., Storage Blob Data Reader).

    The token is automatically cached and refreshed 5 minutes before expiry.

    Returns:
        OAuth bearer token for Azure Storage, or None if auth is disabled.

    Raises:
        Exception: If token acquisition fails.
    """
    if not settings.enable_storage_auth:
        logger.debug("Azure OAuth authentication disabled")
        return None

    # Check cache first
    cached = storage_token_cache.get_if_valid(min_ttl_seconds=TOKEN_REFRESH_BUFFER_SECS)
    if cached:
        ttl = storage_token_cache.ttl_seconds()
        logger.debug(f"Using cached storage token, TTL: {ttl:.0f}s")
        return cached

    # Acquire new token
    mode = "local" if settings.auth_use_cli else "managed_identity"
    logger.debug(f"Acquiring storage token: account={settings.storage_account} mode={mode}")

    try:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        token_response = credential.get_token(STORAGE_SCOPE)

        access_token = token_response.token
        expires_at = datetime.fromtimestamp(token_response.expires_on, tz=timezone.utc)

        # Cache the token
        storage_token_cache.set(access_token, expires_at)

        logger.info(f"Storage token acquired, expires={expires_at.isoformat()}")

        return access_token

    except Exception as e:
        logger.error(f"Storage token acquisition failed: {type(e).__name__}: {e}")
        if settings.auth_use_cli:
            logger.error("Troubleshooting: Run 'az login' and verify with 'az account show'")
        else:
            logger.error("Troubleshooting: Verify Managed Identity is enabled and has Storage Blob Data Reader role")
        raise


async def get_storage_oauth_token_async() -> Optional[str]:
    """
    Get OAuth token for Azure Storage (async version).

    Uses asyncio.Lock to coordinate concurrent callers and prevent
    thundering herd on token refresh. Only one coroutine acquires
    a new token; others wait and use the cached result.

    Returns:
        OAuth bearer token for Azure Storage, or None if auth is disabled.
    """
    if not settings.enable_storage_auth:
        return None

    async with storage_token_cache.async_lock:
        # Check cache while holding async lock
        cached = storage_token_cache.get_if_valid_unlocked(
            min_ttl_seconds=TOKEN_REFRESH_BUFFER_SECS
        )
        if cached:
            ttl = storage_token_cache.ttl_seconds_unlocked()
            logger.debug(f"Using cached storage token, TTL: {ttl:.0f}s")
            return cached

        # Cache miss - acquire new token in thread pool
        token, expires_at = await asyncio.to_thread(_acquire_storage_token)

        if token and expires_at:
            storage_token_cache.set_unlocked(token, expires_at)

        return token


def _acquire_storage_token() -> tuple[Optional[str], Optional[datetime]]:
    """
    Acquire token from Azure SDK (internal, runs in thread pool).

    Returns:
        Tuple of (token, expires_at) or (None, None) on failure.
    """
    mode = "local" if settings.auth_use_cli else "managed_identity"
    logger.debug(f"Acquiring storage token: account={settings.storage_account} mode={mode}")

    try:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        token_response = credential.get_token(STORAGE_SCOPE)

        access_token = token_response.token
        expires_at = datetime.fromtimestamp(token_response.expires_on, tz=timezone.utc)

        logger.info(f"Storage token acquired, expires={expires_at.isoformat()}")

        return access_token, expires_at

    except Exception as e:
        logger.error(f"Storage token acquisition failed: {type(e).__name__}: {e}")
        if settings.auth_use_cli:
            logger.error("Troubleshooting: Run 'az login'")
        else:
            logger.error("Troubleshooting: Verify Managed Identity is enabled")
        raise


def configure_storage_auth(token: str) -> None:
    """
    Configure GDAL and obstore for Azure blob access using OAuth token.

    Sets environment variables for both consumers:
    - GDAL (COG tiles via /vsiaz/): AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN
    - obstore (Zarr tiles via abfs://): AZURE_STORAGE_ACCOUNT_NAME + AZURE_STORAGE_TOKEN

    Args:
        token: OAuth bearer token for Azure Storage.
    """
    if not settings.storage_account:
        logger.warning("GEOTILER_STORAGE_ACCOUNT not set, skipping storage auth config")
        return

    # GDAL env vars — used by rasterio for /vsiaz/ COG access
    os.environ["AZURE_STORAGE_ACCOUNT"] = settings.storage_account
    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token

    # obstore env vars — used by titiler-xarray for abfs:// Zarr access
    os.environ["AZURE_STORAGE_ACCOUNT_NAME"] = settings.storage_account
    os.environ["AZURE_STORAGE_TOKEN"] = token

    # Also set GDAL config options directly (more reliable than env vars)
    try:
        from rasterio import _env
        _env.set_gdal_config("AZURE_STORAGE_ACCOUNT", settings.storage_account)
        _env.set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token)
        logger.debug(f"Storage auth configured for account: {settings.storage_account}")
    except Exception as e:
        logger.warning(f"Could not set GDAL config directly: {e}")


def initialize_storage_auth() -> Optional[str]:
    """
    Initialize storage authentication on application startup.

    Acquires initial OAuth token and configures GDAL + obstore.

    Returns:
        OAuth token if successful, None if auth is disabled.
    """
    if not settings.enable_storage_auth:
        logger.info("Azure Storage authentication is disabled")
        return None

    if not settings.storage_account:
        logger.error("GEOTILER_STORAGE_ACCOUNT not set - Azure auth will not work")
        return None

    try:
        token = get_storage_oauth_token()
        if token:
            configure_storage_auth(token)
            mode = "Azure CLI" if settings.auth_use_cli else "Managed Identity"
            logger.info(f"Storage auth initialized: account={settings.storage_account} mode={mode}")
        return token
    except Exception as e:
        logger.error(f"Failed to initialize storage OAuth: {e}")
        if settings.auth_use_cli:
            logger.info("TIP: Run 'az login' to authenticate locally")
        return None


def refresh_storage_token() -> Optional[str]:
    """
    Force refresh of storage OAuth token (sync version).

    Used by background refresh task to proactively update tokens.
    Acquires new token BEFORE touching cache — no window where
    concurrent readers see an empty cache.

    Returns:
        New OAuth token if successful, None otherwise.
    """
    logger.debug("Refreshing storage token (sync)")

    try:
        # Acquire new token directly (bypass cache check)
        token, expires_at = _acquire_storage_token()
        if token and expires_at:
            storage_token_cache.set(token, expires_at)
            configure_storage_auth(token)
        return token
    except Exception as e:
        logger.error(f"Storage token refresh failed: {e}")
        logger.warning("Keeping existing cached token (may still be valid)")
        return None


async def refresh_storage_token_async() -> Optional[str]:
    """
    Force refresh of storage OAuth token (async version).

    Uses asyncio.Lock to coordinate with other async callers.

    Returns:
        New OAuth token if successful, None otherwise.
    """
    logger.debug("Refreshing storage token (async)")

    async with storage_token_cache.async_lock:
        # Acquire new token BEFORE invalidating old one.
        # If acquisition fails, the old (still-valid) token remains usable.
        try:
            token, expires_at = await asyncio.to_thread(_acquire_storage_token)
            if token and expires_at:
                storage_token_cache.set_unlocked(token, expires_at)
                configure_storage_auth(token)
            return token
        except Exception as e:
            logger.error(f"Storage token refresh failed: {e}")
            logger.warning("Keeping existing cached token (may still be valid)")
            return None
