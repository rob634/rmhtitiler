"""
Azure Storage OAuth authentication.

Handles OAuth token acquisition for Azure Blob Storage using Managed Identity
or Azure CLI credentials. Configures GDAL and fsspec for authenticated access.
"""

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
    if not settings.use_azure_auth:
        logger.debug("Azure OAuth authentication disabled")
        return None

    # Check cache first
    cached = storage_token_cache.get_if_valid(min_ttl_seconds=TOKEN_REFRESH_BUFFER_SECS)
    if cached:
        ttl = storage_token_cache.ttl_seconds()
        logger.debug(f"Using cached storage token, TTL: {ttl:.0f}s")
        return cached

    # Acquire new token
    logger.info("=" * 60)
    logger.info("Acquiring Azure Storage OAuth token...")
    logger.info(f"Mode: {'Local (Azure CLI)' if settings.local_mode else 'Production (Managed Identity)'}")
    logger.info(f"Storage Account: {settings.azure_storage_account}")
    logger.info("=" * 60)

    try:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        token_response = credential.get_token(STORAGE_SCOPE)

        access_token = token_response.token
        expires_at = datetime.fromtimestamp(token_response.expires_on, tz=timezone.utc)

        # Cache the token
        storage_token_cache.set(access_token, expires_at)

        logger.info(f"Storage token acquired, expires: {expires_at.isoformat()}")
        logger.info(f"Token length: {len(access_token)} characters")

        return access_token

    except Exception as e:
        logger.error("=" * 60)
        logger.error("FAILED TO GET STORAGE OAUTH TOKEN")
        logger.error("=" * 60)
        logger.error(f"Error: {type(e).__name__}: {e}")
        logger.error("")
        logger.error("Troubleshooting:")
        if settings.local_mode:
            logger.error("  - Run: az login")
            logger.error("  - Verify: az account show")
        else:
            logger.error("  - Verify Managed Identity is enabled on App Service")
            logger.error("  - Verify RBAC role: Storage Blob Data Reader")
        logger.error("=" * 60)
        raise


def configure_gdal_auth(token: str) -> None:
    """
    Configure GDAL for Azure blob access using OAuth token.

    Sets both environment variables and GDAL config options to ensure
    /vsiaz/ paths work correctly with Azure Storage.

    Args:
        token: OAuth bearer token for Azure Storage.
    """
    if not settings.azure_storage_account:
        logger.warning("AZURE_STORAGE_ACCOUNT not set, skipping GDAL config")
        return

    # Set environment variables (used by GDAL)
    os.environ["AZURE_STORAGE_ACCOUNT"] = settings.azure_storage_account
    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token

    # Also set GDAL config options directly (more reliable)
    try:
        from rasterio import _env
        _env.set_gdal_config("AZURE_STORAGE_ACCOUNT", settings.azure_storage_account)
        _env.set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token)
        logger.debug(f"GDAL configured for storage account: {settings.azure_storage_account}")
    except Exception as e:
        logger.warning(f"Could not set GDAL config directly: {e}")


def configure_fsspec_auth() -> None:
    """
    Configure fsspec/adlfs for Azure Zarr access.

    adlfs uses DefaultAzureCredential automatically when
    AZURE_STORAGE_ACCOUNT_NAME is set.
    """
    if not settings.azure_storage_account:
        return

    os.environ["AZURE_STORAGE_ACCOUNT_NAME"] = settings.azure_storage_account
    logger.debug(f"fsspec/adlfs configured for account: {settings.azure_storage_account}")


def initialize_storage_auth() -> Optional[str]:
    """
    Initialize storage authentication on application startup.

    Acquires initial OAuth token and configures GDAL/fsspec.

    Returns:
        OAuth token if successful, None if auth is disabled.
    """
    if not settings.use_azure_auth:
        logger.info("Azure Storage authentication is disabled")
        return None

    if not settings.azure_storage_account:
        logger.error("AZURE_STORAGE_ACCOUNT not set - Azure auth will not work")
        return None

    try:
        token = get_storage_oauth_token()
        if token:
            configure_gdal_auth(token)
            configure_fsspec_auth()
            logger.info("Storage OAuth authentication initialized successfully")
            if settings.local_mode:
                logger.info("Using Azure CLI credentials (az login)")
            else:
                logger.info("Using Managed Identity")
        return token
    except Exception as e:
        logger.error(f"Failed to initialize storage OAuth: {e}")
        if settings.local_mode:
            logger.info("TIP: Run 'az login' to authenticate locally")
        return None


def refresh_storage_token() -> Optional[str]:
    """
    Force refresh of storage OAuth token.

    Used by background refresh task to proactively update tokens.

    Returns:
        New OAuth token if successful, None otherwise.
    """
    logger.info("Refreshing Storage OAuth token...")

    # Invalidate cache to force new token
    storage_token_cache.invalidate()

    try:
        token = get_storage_oauth_token()
        if token:
            configure_gdal_auth(token)
            logger.info("Storage token refresh complete")
        return token
    except Exception as e:
        logger.error(f"Storage token refresh failed: {e}")
        return None
