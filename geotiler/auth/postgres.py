"""
PostgreSQL authentication with multiple modes.

Supports three authentication modes:
1. password - Direct password from environment variable
2. key_vault - Password retrieved from Azure Key Vault
3. managed_identity - OAuth token via Managed Identity
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

from geotiler.config import settings, POSTGRES_SCOPE, TOKEN_REFRESH_BUFFER_SECS
from geotiler.auth.cache import postgres_token_cache

logger = logging.getLogger(__name__)


def get_postgres_credential() -> Optional[str]:
    """
    Get PostgreSQL credential based on configured auth mode.

    Returns:
        Password or OAuth token for PostgreSQL connection.

    Raises:
        ValueError: If auth mode is invalid.
        Exception: If credential acquisition fails.
    """
    mode = settings.postgres_auth_mode.lower()

    if mode == "password":
        return _get_password_from_env()

    elif mode == "key_vault":
        return _get_password_from_keyvault()

    elif mode == "managed_identity":
        return _get_postgres_oauth_token()

    else:
        raise ValueError(
            f"Invalid POSTGRES_AUTH_MODE: {mode}. "
            "Valid modes: password, key_vault, managed_identity"
        )


def _get_password_from_env() -> Optional[str]:
    """Get password from POSTGRES_PASSWORD environment variable."""
    if not settings.postgres_password:
        logger.error("POSTGRES_PASSWORD environment variable not set")
        return None

    logger.info("Using PostgreSQL password from environment variable")
    logger.debug(f"Password length: {len(settings.postgres_password)} characters")
    return settings.postgres_password


def _get_password_from_keyvault() -> str:
    """
    Retrieve PostgreSQL password from Azure Key Vault.

    Returns:
        Password from Key Vault.

    Raises:
        Exception: If Key Vault access fails.
    """
    if not settings.key_vault_name:
        raise ValueError("KEY_VAULT_NAME environment variable not set")

    logger.info("=" * 60)
    logger.info("Retrieving PostgreSQL password from Key Vault")
    logger.info(f"Key Vault: {settings.key_vault_name}")
    logger.info(f"Secret Name: {settings.key_vault_secret_name}")
    logger.info("=" * 60)

    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        vault_url = f"https://{settings.key_vault_name}.vault.azure.net/"

        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)

        secret = client.get_secret(settings.key_vault_secret_name)
        password = secret.value

        logger.info("Password retrieved from Key Vault successfully")
        logger.debug(f"Password length: {len(password)} characters")

        return password

    except Exception as e:
        logger.error("=" * 60)
        logger.error("FAILED TO RETRIEVE PASSWORD FROM KEY VAULT")
        logger.error("=" * 60)
        logger.error(f"Error: {type(e).__name__}: {e}")
        logger.error("")
        logger.error("Troubleshooting:")
        logger.error("  - Verify Key Vault exists")
        logger.error("  - Verify secret exists in Key Vault")
        logger.error("  - Verify Managed Identity has 'Get' permission on secrets")
        logger.error("=" * 60)
        raise


def _get_postgres_oauth_token() -> str:
    """
    Get OAuth token for Azure PostgreSQL using Managed Identity.

    Uses caching with automatic refresh when token is within 5 minutes of expiry.

    Returns:
        OAuth bearer token for Azure Database for PostgreSQL.

    Raises:
        Exception: If token acquisition fails.
    """
    # Check cache first
    cached = postgres_token_cache.get_if_valid(min_ttl_seconds=TOKEN_REFRESH_BUFFER_SECS)
    if cached:
        ttl = postgres_token_cache.ttl_seconds()
        logger.debug(f"Using cached PostgreSQL token, TTL: {ttl:.0f}s")
        return cached

    # Acquire new token
    logger.info("=" * 60)
    logger.info("Acquiring PostgreSQL OAuth token...")
    logger.info(f"Mode: {'Local (Azure CLI)' if settings.local_mode else 'Production (Managed Identity)'}")
    logger.info(f"PostgreSQL Host: {settings.postgres_host}")
    logger.info(f"PostgreSQL User: {settings.postgres_user}")
    logger.info("=" * 60)

    try:
        # Use user-assigned MI if client ID is set (production)
        # Otherwise use DefaultAzureCredential (local dev with az login)
        if settings.postgres_mi_client_id and not settings.local_mode:
            from azure.identity import ManagedIdentityCredential
            credential = ManagedIdentityCredential(client_id=settings.postgres_mi_client_id)
            logger.info(f"Using user-assigned Managed Identity: {settings.postgres_mi_client_id}")
        else:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            logger.info("Using DefaultAzureCredential")

        token_response = credential.get_token(POSTGRES_SCOPE)

        access_token = token_response.token
        expires_at = datetime.fromtimestamp(token_response.expires_on, tz=timezone.utc)

        # Cache the token
        postgres_token_cache.set(access_token, expires_at)

        logger.info(f"PostgreSQL token acquired, expires: {expires_at.isoformat()}")
        logger.debug(f"Token length: {len(access_token)} characters")

        return access_token

    except Exception as e:
        logger.error("=" * 60)
        logger.error("FAILED TO GET POSTGRESQL OAUTH TOKEN")
        logger.error("=" * 60)
        logger.error(f"Error: {type(e).__name__}: {e}")
        logger.error("")
        logger.error("Troubleshooting:")
        if settings.local_mode:
            logger.error("  - Run: az login")
            logger.error("  - Verify: az account show")
        else:
            logger.error("  - Verify Managed Identity is assigned to App Service")
            logger.error("  - Verify database user exists and matches MI name")
            logger.error(f"  - Check: az webapp identity show --name <app> --resource-group <rg>")
        logger.error("=" * 60)
        raise


def build_database_url(password: str, search_path: Optional[str] = None) -> str:
    """
    Build PostgreSQL connection URL.

    Args:
        password: Password or OAuth token for authentication.
        search_path: Optional comma-separated list of schemas for search_path.
                     e.g., "pgstac,geo,public"

    Returns:
        PostgreSQL connection URL with SSL mode required.
    """
    # URL-encode the password in case it contains special characters
    encoded_password = quote_plus(password)

    url = (
        f"postgresql://{settings.postgres_user}:{encoded_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}"
        f"/{settings.postgres_db}?sslmode=require"
    )

    # Add search_path as connection option if specified
    if search_path:
        # URL-encode the options value
        options = quote_plus(f"-c search_path={search_path}")
        url += f"&options={options}"

    return url


def refresh_postgres_token() -> Optional[str]:
    """
    Force refresh of PostgreSQL OAuth token.

    Only applicable when using managed_identity auth mode.

    Returns:
        New OAuth token if successful, None if not using MI or refresh fails.
    """
    if settings.postgres_auth_mode != "managed_identity":
        logger.debug("PostgreSQL token refresh skipped (not using managed_identity)")
        return None

    logger.info("Refreshing PostgreSQL OAuth token...")

    # Invalidate cache to force new token
    postgres_token_cache.invalidate()

    try:
        token = _get_postgres_oauth_token()
        logger.info("PostgreSQL token refresh complete")
        return token
    except Exception as e:
        logger.error(f"PostgreSQL token refresh failed: {e}")
        return None
