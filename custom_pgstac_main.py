"""
TiTiler-pgSTAC with Azure OAuth Token Authentication, Xarray, and Planetary Computer Support
==============================================================================================

STAC catalog tile server with multi-container Azure Storage access, multidimensional data
support (Zarr/NetCDF), and Planetary Computer integration for climate data.

AUTHENTICATION MECHANISMS
-------------------------
1. AZURE MANAGED IDENTITY (for your own Azure Blob Storage)
   - Uses OAuth bearer tokens via Azure Managed Identity
   - Production: Uses system-assigned or user-assigned Managed Identity
   - Development: Uses Azure CLI credentials (az login)
   - Endpoints: /cog/*, /xarray/*, /searches/*

2. POSTGRESQL MANAGED IDENTITY (for pgSTAC database)
   - Uses OAuth tokens for Azure Database for PostgreSQL
   - Supports user-assigned MI via POSTGRES_MI_CLIENT_ID
   - Also supports Key Vault or password-based auth
   - Endpoints: /searches/*, /mosaic/*

3. PLANETARY COMPUTER CREDENTIAL PROVIDER (for external climate data)
   - Gets temporary SAS tokens from Planetary Computer's API
   - Grants read access to their public storage accounts
   - Endpoints: /pc/*

VERSION: 0.4.0
"""
import os
import re
import asyncio
import logging
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Optional, Any, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from titiler.pgstac.factory import (
    MosaicTilerFactory,
    add_search_list_route,
    add_search_register_route,
)
from titiler.pgstac.db import close_db_connection, connect_to_db
from titiler.pgstac.dependencies import SearchIdParams
from titiler.pgstac.settings import PostgresSettings
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.core.factory import TilerFactory, MultiBaseTilerFactory, TMSFactory
from titiler.mosaic.factory import MosaicTilerFactory as BaseMosaicTilerFactory

# Xarray/Zarr support for multidimensional data
from titiler.xarray.factory import TilerFactory as XarrayTilerFactory
from titiler.xarray.extensions import VariablesExtension

# Planetary Computer credential provider for external climate data
try:
    from obstore.store import AzureStore
    from obstore.auth.planetary_computer import PlanetaryComputerCredentialProvider
    PLANETARY_COMPUTER_AVAILABLE = True
except ImportError:
    PLANETARY_COMPUTER_AVAILABLE = False
    AzureStore = None
    PlanetaryComputerCredentialProvider = None

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# OAuth token cache - shared across all workers
oauth_token_cache = {
    "token": None,
    "expires_at": None,
    "lock": Lock()
}

# PostgreSQL OAuth token cache (for managed_identity mode)
postgres_token_cache = {
    "token": None,
    "expires_at": None,
    "lock": Lock()
}

# Database connection error cache (for health check reporting)
db_error_cache = {
    "last_error": None,
    "last_error_time": None,
    "last_success_time": None,
    "lock": Lock()
}

# Configuration - Storage Authentication
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"
ENABLE_PLANETARY_COMPUTER = os.getenv("ENABLE_PLANETARY_COMPUTER", "true").lower() == "true"

# ============================================================================
# PLANETARY COMPUTER CONFIGURATION
# ============================================================================
# Known Planetary Computer storage accounts that require their SAS token service.
PLANETARY_COMPUTER_STORAGE_ACCOUNTS = {
    "rhgeuwest": "cil-gdpcir-cc0",  # Climate Impact Lab CMIP6 projections
    "ai4edataeuwest": "daymet-daily-na",  # gridMET, Daymet climate data
}

# Cache for Planetary Computer credential providers
_pc_credential_cache: Dict[str, Any] = {}
_pc_credential_lock = Lock()

# Configuration - PostgreSQL Authentication
# Three authentication modes:
# 1. "managed_identity" - Use Azure Managed Identity (production)
# 2. "key_vault" - Retrieve password from Azure Key Vault
# 3. "password" - Use password from environment variable (debugging)
POSTGRES_AUTH_MODE = os.getenv("POSTGRES_AUTH_MODE", "password").lower()

# Common PostgreSQL settings
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

# Mode-specific settings
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")  # For "password" mode
KEY_VAULT_NAME = os.getenv("KEY_VAULT_NAME")  # For "key_vault" mode
KEY_VAULT_SECRET_NAME = os.getenv("KEY_VAULT_SECRET_NAME", "postgres-password")  # For "key_vault" mode
POSTGRES_MI_CLIENT_ID = os.getenv("POSTGRES_MI_CLIENT_ID")  # For "managed_identity" mode - user-assigned MI client ID

# DATABASE_URL will be built at startup based on auth mode
DATABASE_URL = None


def get_azure_storage_oauth_token() -> Optional[str]:
    """
    Get OAuth token for Azure Storage using Managed Identity.

    This token grants access to ALL containers based on the Managed Identity's
    RBAC role assignments (e.g., Storage Blob Data Reader).

    The token is valid for ~1 hour and is automatically cached and refreshed.

    Returns:
        str: OAuth bearer token for Azure Storage
        None: If authentication is disabled or fails
    """
    if not USE_AZURE_AUTH:
        logger.debug("Azure OAuth authentication disabled")
        return None

    with oauth_token_cache["lock"]:
        now = datetime.now(timezone.utc)

        # Check cached token (refresh 5 minutes before expiry)
        if oauth_token_cache["token"] and oauth_token_cache["expires_at"]:
            time_until_expiry = (oauth_token_cache["expires_at"] - now).total_seconds()

            if time_until_expiry > 300:  # More than 5 minutes remaining
                logger.debug(f"✓ Using cached OAuth token, expires in {time_until_expiry:.0f}s")
                return oauth_token_cache["token"]
            else:
                logger.info(f"⚠ OAuth token expires in {time_until_expiry:.0f}s, refreshing...")

        # Generate new token
        logger.info("=" * 80)
        logger.info("🔑 Acquiring OAuth token for Azure Storage")
        logger.info("=" * 80)
        logger.info(f"Mode: {'DEVELOPMENT (Azure CLI)' if LOCAL_MODE else 'PRODUCTION (Managed Identity)'}")
        logger.info(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
        logger.info(f"Token Scope: https://storage.azure.com/.default")
        logger.info("=" * 80)

        try:
            from azure.identity import DefaultAzureCredential

            # Step 1: Get credential (Azure CLI in dev, Managed Identity in prod)
            logger.debug("Step 1/2: Creating DefaultAzureCredential...")
            try:
                credential = DefaultAzureCredential()
                logger.info("✓ DefaultAzureCredential created successfully")
            except Exception as cred_error:
                logger.error("=" * 80)
                logger.error("❌ FAILED TO CREATE AZURE CREDENTIAL")
                logger.error("=" * 80)
                logger.error(f"Error Type: {type(cred_error).__name__}")
                logger.error(f"Error Message: {str(cred_error)}")
                logger.error("")
                logger.error("Troubleshooting:")
                if LOCAL_MODE:
                    logger.error("  - Run: az login")
                    logger.error("  - Verify: az account show")
                else:
                    logger.error("  - Verify Managed Identity: az webapp identity show --name <app> --resource-group <rg>")
                    logger.error("  - Wait 2-3 minutes after enabling identity")
                logger.error("=" * 80)
                raise

            # Step 2: Get token for Azure Storage scope
            logger.debug("Step 2/2: Requesting token for scope 'https://storage.azure.com/.default'...")
            try:
                token = credential.get_token("https://storage.azure.com/.default")
                access_token = token.token
                expires_on = datetime.fromtimestamp(token.expires_on, tz=timezone.utc)

                logger.info(f"✓ OAuth token acquired, expires at {expires_on.isoformat()}")
                logger.debug(f"  Token length: {len(access_token)} characters")
                logger.debug(f"  Token starts with: {access_token[:20]}...")

            except Exception as token_error:
                logger.error("=" * 80)
                logger.error("❌ FAILED TO GET OAUTH TOKEN")
                logger.error("=" * 80)
                logger.error(f"Error Type: {type(token_error).__name__}")
                logger.error(f"Error Message: {str(token_error)}")
                logger.error(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
                logger.error("")
                logger.error("Troubleshooting:")
                logger.error("  - Verify RBAC Role: Storage Blob Data Reader or higher")
                logger.error("  - Check role assignment:")
                logger.error(f"    az role assignment list --assignee <principal-id>")
                logger.error("  - Grant role if missing:")
                logger.error(f"    az role assignment create --role 'Storage Blob Data Reader' \\")
                logger.error(f"      --assignee <principal-id> \\")
                logger.error(f"      --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/{AZURE_STORAGE_ACCOUNT}")
                logger.error("=" * 80)
                raise

            # Cache token
            oauth_token_cache["token"] = access_token
            oauth_token_cache["expires_at"] = expires_on

            logger.info("=" * 80)
            logger.info("✅ OAuth token successfully generated and cached")
            logger.info("=" * 80)
            logger.info(f"   Storage Account: {AZURE_STORAGE_ACCOUNT}")
            logger.info(f"   Valid until: {expires_on.isoformat()}")
            logger.info(f"   Grants access to: ALL containers per RBAC role")
            logger.info("=" * 80)

            return access_token

        except Exception as e:
            logger.error("=" * 80)
            logger.error("❌ CATASTROPHIC FAILURE IN OAUTH TOKEN GENERATION")
            logger.error("=" * 80)
            logger.error(f"Error Type: {type(e).__name__}")
            logger.error(f"Error Message: {str(e)}")
            logger.error(f"Mode: {'DEVELOPMENT' if LOCAL_MODE else 'PRODUCTION'}")
            logger.error(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
            logger.error("")
            logger.error("Full traceback:", exc_info=True)
            logger.error("=" * 80)
            raise


def is_planetary_computer_url(url: str) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Check if a URL points to a Planetary Computer storage account.

    Args:
        url: The URL to check (can be https:// or abfs:// format)

    Returns:
        Tuple of (is_pc_url, storage_account, collection_id)
    """
    if not url:
        return False, None, None

    # Parse HTTPS URLs: https://{account}.blob.core.windows.net/...
    https_match = re.match(r'https://([^.]+)\.blob\.core\.windows\.net/', url)
    if https_match:
        account = https_match.group(1)
        if account in PLANETARY_COMPUTER_STORAGE_ACCOUNTS:
            return True, account, PLANETARY_COMPUTER_STORAGE_ACCOUNTS[account]

    # Parse ABFS URLs: abfs://{container}@{account}.dfs.core.windows.net/...
    abfs_match = re.match(r'abfs://[^@]+@([^.]+)\.dfs\.core\.windows\.net/', url)
    if abfs_match:
        account = abfs_match.group(1)
        if account in PLANETARY_COMPUTER_STORAGE_ACCOUNTS:
            return True, account, PLANETARY_COMPUTER_STORAGE_ACCOUNTS[account]

    return False, None, None


def get_planetary_computer_credential_provider(url: str) -> Optional[Any]:
    """
    Get a PlanetaryComputerCredentialProvider for the given URL.

    The credential provider automatically fetches SAS tokens from Planetary Computer's
    API and caches them for reuse.

    Args:
        url: The full URL to the Planetary Computer Zarr data

    Returns:
        A PlanetaryComputerCredentialProvider instance, or None if not available
    """
    if not PLANETARY_COMPUTER_AVAILABLE or not ENABLE_PLANETARY_COMPUTER:
        logger.debug("Planetary Computer support not available or disabled")
        return None

    # Cache key is the base URL (storage account + container)
    parsed = urlparse(url)
    path_parts = parsed.path.strip('/').split('/', 1)
    container = path_parts[0] if path_parts else ""
    cache_key = f"{parsed.netloc}/{container}"

    with _pc_credential_lock:
        if cache_key not in _pc_credential_cache:
            try:
                logger.info(f"Creating PlanetaryComputerCredentialProvider for: {cache_key}")
                provider = PlanetaryComputerCredentialProvider(url=url)
                _pc_credential_cache[cache_key] = provider
                logger.info(f"✓ Credential provider created for {cache_key}")
            except Exception as e:
                logger.error(f"Failed to create PC credential provider for {cache_key}: {e}")
                _pc_credential_cache[cache_key] = None

        return _pc_credential_cache.get(cache_key)


def setup_fsspec_azure_credentials(account_name: str):
    """
    Configure fsspec/adlfs to use Azure OAuth token.

    adlfs uses DefaultAzureCredential automatically when no explicit
    credentials are provided.
    """
    os.environ["AZURE_STORAGE_ACCOUNT_NAME"] = account_name
    logger.debug(f"Configured fsspec/adlfs for account: {account_name}")


async def token_refresh_background_task():
    """
    Background task that proactively refreshes OAuth tokens every 45 minutes.
    Refreshes both Storage and PostgreSQL tokens to prevent expiration.
    """
    REFRESH_INTERVAL = 45 * 60  # 45 minutes in seconds

    while True:
        await asyncio.sleep(REFRESH_INTERVAL)

        logger.info("=" * 60)
        logger.info("🔄 Background token refresh triggered")
        logger.info("=" * 60)

        # ============================================
        # REFRESH STORAGE TOKEN
        # ============================================
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                logger.info("🔄 Refreshing Storage OAuth token...")

                # Force cache invalidation to get fresh token
                with oauth_token_cache["lock"]:
                    oauth_token_cache["expires_at"] = None

                # Get fresh token
                token = get_azure_storage_oauth_token()

                if token:
                    # Update environment and GDAL config
                    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token

                    from rasterio import _env
                    _env.set_gdal_config("AZURE_STORAGE_ACCOUNT", AZURE_STORAGE_ACCOUNT)
                    _env.set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token)

                    logger.info("✅ Storage token refresh complete")
                else:
                    logger.warning("⚠ Storage token refresh: No token returned")

            except Exception as e:
                logger.error(f"❌ Storage token refresh failed: {e}")

        # ============================================
        # REFRESH POSTGRESQL TOKEN (if using managed_identity)
        # ============================================
        if POSTGRES_AUTH_MODE == "managed_identity":
            try:
                logger.info("🔄 Refreshing PostgreSQL OAuth token...")

                # Force cache invalidation to get fresh token
                with postgres_token_cache["lock"]:
                    postgres_token_cache["expires_at"] = None

                # Get fresh token
                new_pg_token = get_postgres_oauth_token()

                if new_pg_token:
                    # Rebuild DATABASE_URL with new token
                    new_database_url = (
                        f"postgresql://{POSTGRES_USER}:{new_pg_token}"
                        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}?sslmode=require"
                    )

                    # Recreate the database connection pool with new token
                    try:
                        # Close existing pool
                        await close_db_connection(app)
                        logger.info("  Closed existing database connection pool")

                        # Create new pool with fresh token
                        db_settings = PostgresSettings(database_url=new_database_url)
                        await connect_to_db(app, settings=db_settings)
                        logger.info("✅ PostgreSQL token refresh complete - new connection pool created")

                    except Exception as pool_err:
                        logger.error(f"❌ Failed to recreate connection pool: {pool_err}")
                        raise
                else:
                    logger.warning("⚠ PostgreSQL token refresh: No token returned")

            except Exception as e:
                logger.error(f"❌ PostgreSQL token refresh failed: {e}")

        logger.info(f"   Next refresh in {REFRESH_INTERVAL // 60} minutes")
        logger.info("=" * 60)


def get_postgres_password_from_keyvault() -> str:
    """
    Retrieve PostgreSQL password from Azure Key Vault.

    Returns:
        str: Password from Key Vault

    Raises:
        RuntimeError: If Key Vault access fails
    """
    logger.info("=" * 80)
    logger.info("🔑 Retrieving PostgreSQL password from Key Vault")
    logger.info("=" * 80)
    logger.info(f"Key Vault: {KEY_VAULT_NAME}")
    logger.info(f"Secret Name: {KEY_VAULT_SECRET_NAME}")
    logger.info("=" * 80)

    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        vault_url = f"https://{KEY_VAULT_NAME}.vault.azure.net/"

        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)

        secret = client.get_secret(KEY_VAULT_SECRET_NAME)
        password = secret.value

        logger.info("✅ Password retrieved from Key Vault successfully")
        logger.info(f"  Password length: {len(password)} characters")
        logger.info("=" * 80)

        return password

    except Exception as e:
        logger.error("=" * 80)
        logger.error("❌ FAILED TO RETRIEVE PASSWORD FROM KEY VAULT")
        logger.error("=" * 80)
        logger.error(f"Error Type: {type(e).__name__}")
        logger.error(f"Error Message: {str(e)}")
        logger.error(f"Key Vault: {KEY_VAULT_NAME}")
        logger.error(f"Secret Name: {KEY_VAULT_SECRET_NAME}")
        logger.error("")
        logger.error("Troubleshooting:")
        logger.error("  - Verify Key Vault exists")
        logger.error("  - Verify secret exists in Key Vault")
        logger.error("  - Verify Managed Identity has 'Get' permission on secrets")
        logger.error("=" * 80)
        raise


def get_postgres_oauth_token() -> str:
    """
    Get OAuth token for Azure PostgreSQL using Managed Identity.

    Uses caching with automatic refresh when token is within 5 minutes of expiry.
    Token is valid for ~1 hour and is automatically refreshed.

    Returns:
        str: OAuth bearer token for Azure Database for PostgreSQL

    Raises:
        RuntimeError: If token acquisition fails
    """
    with postgres_token_cache["lock"]:
        now = datetime.now(timezone.utc)

        # Check cached token (refresh 5 minutes before expiry)
        if postgres_token_cache["token"] and postgres_token_cache["expires_at"]:
            time_until_expiry = (postgres_token_cache["expires_at"] - now).total_seconds()

            if time_until_expiry > 300:  # More than 5 minutes remaining
                logger.debug(f"✓ Using cached PostgreSQL OAuth token, expires in {time_until_expiry:.0f}s")
                return postgres_token_cache["token"]
            else:
                logger.info(f"⚠ PostgreSQL OAuth token expires in {time_until_expiry:.0f}s, refreshing...")

        # Generate new token
        logger.info("=" * 80)
        logger.info("🔑 Acquiring OAuth token for PostgreSQL")
        logger.info("=" * 80)
        logger.info(f"Mode: {'DEVELOPMENT (Azure CLI)' if LOCAL_MODE else 'PRODUCTION (Managed Identity)'}")
        logger.info(f"PostgreSQL Host: {POSTGRES_HOST}")
        logger.info(f"PostgreSQL User: {POSTGRES_USER}")
        logger.info(f"Token Scope: https://ossrdbms-aad.database.windows.net/.default")
        logger.info("=" * 80)

        try:
            from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

            # Step 1: Create credential
            # Use user-assigned managed identity if POSTGRES_MI_CLIENT_ID is set
            # Otherwise fall back to DefaultAzureCredential (for local dev with az login)
            if POSTGRES_MI_CLIENT_ID and not LOCAL_MODE:
                logger.debug(f"Step 1/2: Creating ManagedIdentityCredential with client_id={POSTGRES_MI_CLIENT_ID}...")
                try:
                    credential = ManagedIdentityCredential(client_id=POSTGRES_MI_CLIENT_ID)
                    logger.info(f"✓ ManagedIdentityCredential created for user-assigned MI: {POSTGRES_MI_CLIENT_ID}")
                except Exception as cred_error:
                    logger.error("=" * 80)
                    logger.error("❌ FAILED TO CREATE MANAGED IDENTITY CREDENTIAL")
                    logger.error("=" * 80)
                    logger.error(f"Error Type: {type(cred_error).__name__}")
                    logger.error(f"Error Message: {str(cred_error)}")
                    logger.error(f"Client ID: {POSTGRES_MI_CLIENT_ID}")
                    logger.error("")
                    logger.error("Troubleshooting:")
                    logger.error("  - Verify user-assigned MI is assigned to App Service")
                    logger.error("  - Verify client ID is correct")
                    logger.error("  - az webapp identity show --name <app> --resource-group <rg>")
                    logger.error("=" * 80)
                    raise
            else:
                logger.debug("Step 1/2: Creating DefaultAzureCredential (local dev mode)...")
                try:
                    credential = DefaultAzureCredential()
                    logger.info("✓ DefaultAzureCredential created successfully")
                except Exception as cred_error:
                    logger.error("=" * 80)
                    logger.error("❌ FAILED TO CREATE AZURE CREDENTIAL")
                    logger.error("=" * 80)
                    logger.error(f"Error Type: {type(cred_error).__name__}")
                    logger.error(f"Error Message: {str(cred_error)}")
                    logger.error("")
                    logger.error("Troubleshooting:")
                    if LOCAL_MODE:
                        logger.error("  - Run: az login")
                        logger.error("  - Verify: az account show")
                    else:
                        logger.error("  - Set POSTGRES_MI_CLIENT_ID for user-assigned MI")
                        logger.error("  - Or verify system-assigned MI is enabled")
                    logger.error("=" * 80)
                    raise

            # Step 2: Get token for PostgreSQL scope (DIFFERENT from storage!)
            logger.debug("Step 2/2: Requesting token for scope 'https://ossrdbms-aad.database.windows.net/.default'...")
            try:
                # IMPORTANT: PostgreSQL scope is different from Storage!
                token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
                access_token = token.token
                expires_on = datetime.fromtimestamp(token.expires_on, tz=timezone.utc)

                logger.info(f"✓ PostgreSQL OAuth token acquired")
                logger.info(f"  Token length: {len(access_token)} characters")
                logger.info(f"  Token expires at: {expires_on.isoformat()}")
                logger.debug(f"  Token starts with: {access_token[:20]}...")

            except Exception as token_error:
                logger.error("=" * 80)
                logger.error("❌ FAILED TO GET POSTGRESQL OAUTH TOKEN")
                logger.error("=" * 80)
                logger.error(f"Error Type: {type(token_error).__name__}")
                logger.error(f"Error Message: {str(token_error)}")
                logger.error(f"PostgreSQL Host: {POSTGRES_HOST}")
                logger.error(f"PostgreSQL User: {POSTGRES_USER}")
                logger.error("")
                logger.error("Troubleshooting:")
                logger.error("  - Verify database user exists:")
                logger.error(f"    psql -c \"SELECT rolname FROM pg_roles WHERE rolname='{POSTGRES_USER}';\"")
                logger.error("  - Verify user was created with correct name matching MI")
                logger.error("  - Check MI is assigned to App Service")
                logger.error("=" * 80)
                raise

            # Cache token
            postgres_token_cache["token"] = access_token
            postgres_token_cache["expires_at"] = expires_on

            logger.info("=" * 80)
            logger.info("✅ PostgreSQL OAuth token successfully acquired and cached")
            logger.info("=" * 80)
            logger.info(f"   PostgreSQL Host: {POSTGRES_HOST}")
            logger.info(f"   PostgreSQL User: {POSTGRES_USER}")
            logger.info(f"   Valid until: {expires_on.isoformat()}")
            logger.info("=" * 80)

            return access_token

        except Exception as e:
            logger.error("=" * 80)
            logger.error("❌ CATASTROPHIC FAILURE IN POSTGRESQL TOKEN GENERATION")
            logger.error("=" * 80)
            logger.error(f"Error Type: {type(e).__name__}")
            logger.error(f"Error Message: {str(e)}")
            logger.error(f"Mode: {'DEVELOPMENT' if LOCAL_MODE else 'PRODUCTION'}")
            logger.error(f"PostgreSQL Host: {POSTGRES_HOST}")
            logger.error(f"PostgreSQL User: {POSTGRES_USER}")
            logger.error("")
            logger.error("Full traceback:", exc_info=True)
            logger.error("=" * 80)
            raise


class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage OAuth authentication is set before each request.

    Configures authentication for:
    - GDAL: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN (for /vsiaz/ COG access)
    - fsspec/adlfs: AZURE_STORAGE_ACCOUNT_NAME (for abfs:// Zarr access)
    """
    async def dispatch(self, request: Request, call_next):
        logger.debug(f"🔵 Middleware called for: {request.url.path}")
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                # Get OAuth token (uses cache if valid)
                token = get_azure_storage_oauth_token()

                if token:
                    # Set environment variables for GDAL (COG access via /vsiaz/)
                    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token

                    # Also set GDAL config options directly
                    try:
                        from rasterio import _env
                        _env.set_gdal_config("AZURE_STORAGE_ACCOUNT", AZURE_STORAGE_ACCOUNT)
                        _env.set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token)
                        logger.debug(f"✓ Set OAuth token via GDAL config for storage account: {AZURE_STORAGE_ACCOUNT}")
                    except Exception as config_err:
                        logger.warning(f"⚠ Could not set GDAL config directly: {config_err}")

                    # Configure fsspec/adlfs for Zarr access
                    setup_fsspec_azure_credentials(AZURE_STORAGE_ACCOUNT)

                    logger.debug(f"✓ Token length: {len(token)} chars")
                else:
                    logger.warning("⚠ No OAuth token available")

            except Exception as e:
                logger.error(f"❌ Error in Azure OAuth authentication: {e}", exc_info=True)

        response = await call_next(request)
        return response


# Create FastAPI application
app = FastAPI(
    title="TiTiler-pgSTAC with Azure OAuth + Xarray + Planetary Computer",
    description="STAC catalog tile server with Managed Identity authentication, Zarr/NetCDF support, and Planetary Computer integration",
    version="0.4.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Azure authentication middleware
app.add_middleware(AzureAuthMiddleware)

# Add exception handlers
add_exception_handlers(app, DEFAULT_STATUS_CODES)

# ============================================================================
# TiTiler COG Endpoint - Direct file access (your primary use case)
# ============================================================================
cog = TilerFactory(
    router_prefix="/cog",
    add_viewer=True,
)
app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])

# ============================================================================
# TiTiler Xarray Endpoint - Zarr/NetCDF multidimensional data
# ============================================================================
xarray_tiler = XarrayTilerFactory(
    router_prefix="/xarray",
    extensions=[
        VariablesExtension(),  # Adds /variables endpoint to list dataset variables
    ],
)
app.include_router(xarray_tiler.router, prefix="/xarray", tags=["Multidimensional (Zarr/NetCDF)"])

# ============================================================================
# TiTiler MosaicJSON Endpoint - For MosaicJSON files
# ============================================================================
mosaic_json = BaseMosaicTilerFactory(
    router_prefix="/mosaicjson",
    add_viewer=True,
)
app.include_router(mosaic_json.router, prefix="/mosaicjson", tags=["MosaicJSON"])

# ============================================================================
# TiTiler-pgSTAC Search Endpoints - For STAC catalog searches (edge cases)
# ============================================================================
pgstac_mosaic = MosaicTilerFactory(
    path_dependency=SearchIdParams,
    router_prefix="/searches/{search_id}",
    add_statistics=True,
    add_viewer=True,
)
app.include_router(pgstac_mosaic.router, prefix="/searches/{search_id}", tags=["STAC Search"])

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


# ============================================================================
# PLANETARY COMPUTER ENDPOINTS
# ============================================================================

@app.get("/pc/collections", tags=["Planetary Computer"])
async def pc_collections():
    """List known Planetary Computer collections and their storage accounts."""
    return {
        "planetary_computer_enabled": ENABLE_PLANETARY_COMPUTER,
        "credential_provider_available": PLANETARY_COMPUTER_AVAILABLE,
        "storage_accounts": PLANETARY_COMPUTER_STORAGE_ACCOUNTS,
        "documentation": "https://planetarycomputer.microsoft.com/catalog",
        "example_collections": {
            "cil-gdpcir-cc0": {
                "description": "Climate Impact Lab CMIP6 downscaled projections (Public Domain)",
                "variables": ["tasmax", "tasmin", "pr"],
                "example_url": "https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmax/v1.1.zarr"
            },
            "gridmet": {
                "description": "gridMET daily meteorological data",
                "example_url": "https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr"
            }
        }
    }


@app.get("/pc/variables", tags=["Planetary Computer"])
async def pc_variables(
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    collection: Optional[str] = Query(None, description="Collection ID for SAS token")
):
    """List variables in a Planetary Computer Zarr dataset."""
    import xarray as xr
    from zarr.storage import ObjectStore

    if not PLANETARY_COMPUTER_AVAILABLE:
        return {"error": "Planetary Computer support not installed"}

    is_pc, storage_account, default_collection = is_planetary_computer_url(url)
    if not is_pc:
        return {"error": f"URL is not a Planetary Computer URL. Known: {list(PLANETARY_COMPUTER_STORAGE_ACCOUNTS.keys())}"}

    try:
        credential_provider = get_planetary_computer_credential_provider(url)
        if not credential_provider:
            return {"error": f"Failed to get credential provider for URL: {url}"}

        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/', 1)
        container = path_parts[0]
        zarr_path = path_parts[1] if len(path_parts) > 1 else ""

        store = AzureStore(credential_provider=credential_provider)
        zarr_store = ObjectStore(store, read_only=True)
        ds = xr.open_zarr(zarr_store, consolidated=True, decode_times=False)

        return {
            "variables": list(ds.data_vars.keys()),
            "url": url,
            "collection": default_collection,
            "storage_account": storage_account,
            "container": container,
            "path": zarr_path
        }

    except Exception as e:
        logger.error(f"Error accessing Planetary Computer data: {e}", exc_info=True)
        return {"error": str(e), "url": url, "collection": default_collection}


@app.get("/pc/info", tags=["Planetary Computer"])
async def pc_info(
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    variable: str = Query(..., description="Variable name to get info for"),
    collection: Optional[str] = Query(None, description="Collection ID for SAS token")
):
    """Get metadata for a variable in a Planetary Computer Zarr dataset."""
    import xarray as xr
    from zarr.storage import ObjectStore

    if not PLANETARY_COMPUTER_AVAILABLE:
        return {"error": "Planetary Computer support not installed"}

    is_pc, storage_account, default_collection = is_planetary_computer_url(url)
    if not is_pc:
        return {"error": "URL is not a Planetary Computer URL"}

    try:
        credential_provider = get_planetary_computer_credential_provider(url)
        if not credential_provider:
            return {"error": f"Failed to get credential provider for URL: {url}"}

        store = AzureStore(credential_provider=credential_provider)
        zarr_store = ObjectStore(store, read_only=True)
        ds = xr.open_zarr(zarr_store, consolidated=True, decode_times=False)

        if variable not in ds.data_vars:
            return {"error": f"Variable '{variable}' not found. Available: {list(ds.data_vars.keys())}"}

        var = ds[variable]

        return {
            "variable": variable,
            "dims": list(var.dims),
            "shape": list(var.shape),
            "dtype": str(var.dtype),
            "attrs": dict(var.attrs),
            "coords": {
                coord: {
                    "min": float(ds[coord].min().values) if ds[coord].dtype.kind in 'iuf' else str(ds[coord].values[0]),
                    "max": float(ds[coord].max().values) if ds[coord].dtype.kind in 'iuf' else str(ds[coord].values[-1]),
                    "size": len(ds[coord])
                }
                for coord in var.dims if coord in ds.coords
            }
        }

    except Exception as e:
        logger.error(f"Error getting PC variable info: {e}", exc_info=True)
        return {"error": str(e)}


# ============================================================================
# PLANETARY COMPUTER TILE SERVING ENDPOINTS
# ============================================================================

def tile_to_bbox(z: int, x: int, y: int) -> tuple:
    """Convert tile coordinates to WGS84 bounding box."""
    import math
    n = 2.0 ** z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


@app.get("/pc/tiles/{tileMatrixSetId}/{z}/{x}/{y}.png", tags=["Planetary Computer"])
async def pc_tile(
    tileMatrixSetId: str,
    z: int,
    x: int,
    y: int,
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    variable: str = Query(..., description="Variable name"),
    time_idx: int = Query(0, description="Time index (0-based)"),
    colormap: str = Query("viridis", description="Matplotlib colormap name"),
    vmin: Optional[float] = Query(None, description="Min value for colormap"),
    vmax: Optional[float] = Query(None, description="Max value for colormap"),
):
    """
    Serve map tiles from Planetary Computer Zarr data.

    Renders a 256x256 PNG tile for the specified z/x/y coordinates.
    """
    import io
    import numpy as np
    import xarray as xr
    from zarr.storage import ObjectStore
    from PIL import Image
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    if not PLANETARY_COMPUTER_AVAILABLE:
        return Response(content="PC support not installed", status_code=500)

    try:
        # Get tile bounds
        lon_min, lat_min, lon_max, lat_max = tile_to_bbox(z, x, y)

        # Open dataset with PC credentials
        credential_provider = get_planetary_computer_credential_provider(url)
        if not credential_provider:
            return Response(content="Failed to get credentials", status_code=500)

        store = AzureStore(credential_provider=credential_provider)
        zarr_store = ObjectStore(store, read_only=True)
        ds = xr.open_zarr(zarr_store, consolidated=True, decode_times=False)

        if variable not in ds.data_vars:
            return Response(content=f"Variable not found: {variable}", status_code=404)

        var = ds[variable]

        # Select time if present
        if 'time' in var.dims:
            var = var.isel(time=time_idx)

        # Determine lat/lon dimension names
        lat_dim = 'lat' if 'lat' in var.dims else 'latitude' if 'latitude' in var.dims else 'y'
        lon_dim = 'lon' if 'lon' in var.dims else 'longitude' if 'longitude' in var.dims else 'x'

        # Slice to tile bounds
        try:
            # Handle reversed lat coordinates (common in climate data)
            lat_coords = ds[lat_dim].values
            if lat_coords[0] > lat_coords[-1]:
                # Lat is descending
                data = var.sel(**{lat_dim: slice(lat_max, lat_min), lon_dim: slice(lon_min, lon_max)})
            else:
                data = var.sel(**{lat_dim: slice(lat_min, lat_max), lon_dim: slice(lon_min, lon_max)})
        except Exception as slice_err:
            logger.warning(f"Slice failed: {slice_err}, returning empty tile")
            # Return transparent tile if no data in bounds
            img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            return Response(content=buf.read(), media_type="image/png")

        # Load data
        values = data.values

        if values.size == 0:
            # No data in this tile
            img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            return Response(content=buf.read(), media_type="image/png")

        # Calculate colormap bounds
        if vmin is None:
            vmin = float(np.nanmin(values))
        if vmax is None:
            vmax = float(np.nanmax(values))

        # Normalize data
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

        # Apply colormap
        cmap = plt.get_cmap(colormap)
        colored = cmap(norm(values))

        # Handle NaN as transparent
        mask = np.isnan(values)
        colored[mask, 3] = 0  # Set alpha to 0 for NaN

        # Convert to uint8
        colored_uint8 = (colored * 255).astype(np.uint8)

        # Create image and resize to 256x256
        img = Image.fromarray(colored_uint8, mode='RGBA')
        img = img.resize((256, 256), Image.Resampling.BILINEAR)

        # Save to buffer
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        return Response(content=buf.read(), media_type="image/png")

    except Exception as e:
        logger.error(f"Error generating PC tile: {e}", exc_info=True)
        return Response(content=str(e), status_code=500)


@app.get("/pc/{tileMatrixSetId}/tilejson.json", tags=["Planetary Computer"])
async def pc_tilejson(
    request: Request,
    tileMatrixSetId: str,
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    variable: str = Query(..., description="Variable name"),
    time_idx: int = Query(0, description="Time index"),
    colormap: str = Query("viridis", description="Colormap name"),
    vmin: Optional[float] = Query(None, description="Min value"),
    vmax: Optional[float] = Query(None, description="Max value"),
):
    """
    Return TileJSON for Planetary Computer Zarr data.

    TileJSON is used by map viewers (Leaflet, MapLibre) to configure tile layers.
    """
    base_url = str(request.base_url).rstrip('/')

    # Build tile URL with query params
    tile_url = f"{base_url}/pc/tiles/{tileMatrixSetId}/{{z}}/{{x}}/{{y}}.png"
    tile_url += f"?url={url}&variable={variable}&time_idx={time_idx}&colormap={colormap}"
    if vmin is not None:
        tile_url += f"&vmin={vmin}"
    if vmax is not None:
        tile_url += f"&vmax={vmax}"

    return {
        "tilejson": "2.2.0",
        "name": f"{variable} from Planetary Computer",
        "description": f"Climate data variable: {variable}",
        "version": "1.0.0",
        "attribution": "Microsoft Planetary Computer / Climate Impact Lab",
        "scheme": "xyz",
        "tiles": [tile_url],
        "minzoom": 0,
        "maxzoom": 8,
        "bounds": [-180, -90, 180, 90],
        "center": [0, 0, 2]
    }


@app.get("/pc/{tileMatrixSetId}/map.html", tags=["Planetary Computer"], response_class=Response)
async def pc_map(
    request: Request,
    tileMatrixSetId: str,
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    variable: str = Query(..., description="Variable name"),
    time_idx: int = Query(0, description="Time index"),
    colormap: str = Query("viridis", description="Colormap name"),
    vmin: Optional[float] = Query(None, description="Min value"),
    vmax: Optional[float] = Query(None, description="Max value"),
):
    """
    Interactive map viewer for Planetary Computer Zarr data.

    Displays the data on a Leaflet map with the specified colormap.
    """
    base_url = str(request.base_url).rstrip('/')

    # Build tilejson URL
    tilejson_url = f"{base_url}/pc/{tileMatrixSetId}/tilejson.json"
    tilejson_url += f"?url={url}&variable={variable}&time_idx={time_idx}&colormap={colormap}"
    if vmin is not None:
        tilejson_url += f"&vmin={vmin}"
    if vmax is not None:
        tilejson_url += f"&vmax={vmax}"

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{variable} - Planetary Computer Viewer</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ position: absolute; top: 0; bottom: 0; width: 100%; }}
        .info-box {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: white;
            padding: 10px 15px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.3);
            z-index: 1000;
            font-family: Arial, sans-serif;
            font-size: 12px;
            max-width: 300px;
        }}
        .info-box h3 {{ margin: 0 0 5px 0; font-size: 14px; }}
        .info-box p {{ margin: 2px 0; color: #666; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="info-box">
        <h3>Planetary Computer Data</h3>
        <p><strong>Variable:</strong> {variable}</p>
        <p><strong>Time Index:</strong> {time_idx}</p>
        <p><strong>Colormap:</strong> {colormap}</p>
        <p><strong>Source:</strong> CMIP6 Climate Projections</p>
    </div>
    <script>
        var map = L.map('map').setView([20, 0], 2);

        // Base layer
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
            subdomains: 'abcd',
            maxZoom: 19
        }}).addTo(map);

        // Fetch TileJSON and add layer
        fetch('{tilejson_url}')
            .then(response => response.json())
            .then(tilejson => {{
                L.tileLayer(tilejson.tiles[0], {{
                    attribution: tilejson.attribution,
                    maxZoom: tilejson.maxzoom,
                    minZoom: tilejson.minzoom,
                    opacity: 0.7
                }}).addTo(map);
            }})
            .catch(err => console.error('Failed to load TileJSON:', err));
    </script>
</body>
</html>
"""
    return Response(content=html, media_type="text/html")


@app.get("/livez", tags=["Health"])
async def liveness():
    """
    Liveness probe - responds immediately to indicate container is running.
    
    This endpoint is for Azure App Service startup probes. It responds
    before database connection is established, preventing the container
    from being killed during slow database connections or MI token acquisition.
    
    Use /healthz for full readiness checks.
    """
    return {
        "status": "alive",
        "message": "Container is running"
    }


@app.get("/healthz", tags=["Health"])
async def health(response: Response):
    """
    Readiness probe - full health check with diagnostic details.

    Returns HTTP 200 for healthy, HTTP 503 for degraded/unhealthy.
    Response body always includes detailed status for debugging.

    Status levels:
        - healthy: All systems operational (HTTP 200)
        - degraded: App running but some features unavailable (HTTP 503)
        - unhealthy: Critical failure (HTTP 503)

    Checks performed:
        1. Database connection with active ping (required for pgSTAC searches)
        2. Storage OAuth token (required for Azure blob access)
    """
    checks = {}
    issues = []

    # Check 1: Database connection with ACTIVE PING
    # titiler-pgstac uses "dbpool" attribute, not "pool"
    db_pool_exists = hasattr(app.state, "dbpool") and app.state.dbpool is not None
    db_connected = False
    db_ping_error = None
    db_ping_time_ms = None

    if db_pool_exists:
        # Perform actual database ping to verify connection works
        ping_start = time.monotonic()
        try:
            async with app.state.dbpool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_connected = True
            db_ping_time_ms = round((time.monotonic() - ping_start) * 1000, 2)
            # Record successful ping
            with db_error_cache["lock"]:
                db_error_cache["last_error"] = None
                db_error_cache["last_success_time"] = datetime.now(timezone.utc)
        except Exception as e:
            db_ping_error = f"{type(e).__name__}: {str(e)}"
            db_ping_time_ms = round((time.monotonic() - ping_start) * 1000, 2)
            # Record ping failure
            with db_error_cache["lock"]:
                db_error_cache["last_error"] = db_ping_error
                db_error_cache["last_error_time"] = datetime.now(timezone.utc)

    # Build database check response
    checks["database"] = {
        "status": "ok" if db_connected else "fail",
        "pool_exists": db_pool_exists,
        "ping_success": db_connected,
        "required_for": ["pgSTAC searches", "mosaic endpoints"]
    }

    if db_ping_time_ms is not None:
        checks["database"]["ping_time_ms"] = db_ping_time_ms

    if DATABASE_URL:
        try:
            checks["database"]["host"] = DATABASE_URL.split("@")[1].split("/")[0] if "@" in DATABASE_URL else "unknown"
        except (IndexError, AttributeError):
            checks["database"]["host"] = "parse_error"

    # Include error details
    if db_ping_error:
        checks["database"]["error"] = db_ping_error
        issues.append(f"Database ping failed: {db_ping_error}")
    elif not db_pool_exists:
        # Check cached error from startup
        with db_error_cache["lock"]:
            cached_error = db_error_cache["last_error"]
            cached_error_time = db_error_cache["last_error_time"]
        if cached_error:
            checks["database"]["error"] = cached_error
            if cached_error_time:
                checks["database"]["error_time"] = cached_error_time.isoformat()
            issues.append(f"Database connection failed: {cached_error}")
        else:
            issues.append("Database pool not initialized - pgSTAC search endpoints will fail")

    # Include last success time if available
    with db_error_cache["lock"]:
        if db_error_cache["last_success_time"]:
            checks["database"]["last_success"] = db_error_cache["last_success_time"].isoformat()
    
    # Check 2: Storage OAuth token
    if USE_AZURE_AUTH:
        token_valid = oauth_token_cache["token"] and oauth_token_cache["expires_at"]
        if token_valid:
            now = datetime.now(timezone.utc)
            time_until_expiry = (oauth_token_cache["expires_at"] - now).total_seconds()
            checks["storage_oauth"] = {
                "status": "ok" if time_until_expiry > 300 else "warning",
                "expires_in_seconds": max(0, int(time_until_expiry)),
                "storage_account": AZURE_STORAGE_ACCOUNT,
                "required_for": ["Azure blob storage access"]
            }
            if time_until_expiry <= 300:
                issues.append(f"OAuth token expires soon ({int(time_until_expiry)}s) - may cause access issues")
        else:
            checks["storage_oauth"] = {
                "status": "fail",
                "storage_account": AZURE_STORAGE_ACCOUNT,
                "required_for": ["Azure blob storage access"]
            }
            issues.append("Storage OAuth token not initialized - cannot access Azure blobs")
    else:
        checks["storage_oauth"] = {
            "status": "disabled",
            "note": "Azure auth disabled - using anonymous/SAS access"
        }

    # Check 3: PostgreSQL OAuth token (only for managed_identity mode)
    if POSTGRES_AUTH_MODE == "managed_identity":
        pg_token_valid = postgres_token_cache["token"] and postgres_token_cache["expires_at"]
        if pg_token_valid:
            now = datetime.now(timezone.utc)
            time_until_expiry = (postgres_token_cache["expires_at"] - now).total_seconds()
            checks["postgres_oauth"] = {
                "status": "ok" if time_until_expiry > 300 else "warning",
                "expires_in_seconds": max(0, int(time_until_expiry)),
                "required_for": ["PostgreSQL database connection"]
            }
            if time_until_expiry <= 300:
                issues.append(f"PostgreSQL OAuth token expires soon ({int(time_until_expiry)}s) - may cause DB reconnect")
        else:
            checks["postgres_oauth"] = {
                "status": "fail",
                "required_for": ["PostgreSQL database connection"]
            }
            issues.append("PostgreSQL OAuth token not initialized - database may fail on token expiry")

    # Determine overall status
    has_critical_failure = not db_connected or (USE_AZURE_AUTH and not oauth_token_cache["token"])
    
    if not issues:
        overall_status = "healthy"
        response.status_code = 200
    elif has_critical_failure:
        overall_status = "degraded"
        response.status_code = 503  # Service Unavailable - don't send traffic
    else:
        overall_status = "healthy"  # Warnings but functional
        response.status_code = 200
    
    return {
        "status": overall_status,
        "checks": checks,
        "issues": issues if issues else None,
        "config": {
            "postgres_auth_mode": POSTGRES_AUTH_MODE,
            "azure_auth_enabled": USE_AZURE_AUTH,
            "local_mode": LOCAL_MODE
        },
        "available_features": {
            "cog_tiles": USE_AZURE_AUTH and bool(oauth_token_cache["token"]),
            "pgstac_searches": db_connected,
            "mosaic_json": db_connected
        }
    }


@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information."""
    return {
        "title": "TiTiler-pgSTAC with Azure OAuth Auth",
        "description": "STAC catalog tile server with OAuth token support",
        "version": "1.0.0",
        "auth_type": "OAuth Bearer Token (Managed Identity)",
        "endpoints": {
            "liveness": "/livez",
            "readiness": "/healthz",
            "docs": "/docs",
            "redoc": "/redoc",
            "search_list": "/searches",
            "search_register": "/searches/register",
            "search_tiles": "/searches/{search_id}/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "search_info": "/searches/{search_id}/info",
            "search_tilejson": "/searches/{search_id}/{tileMatrixSetId}/tilejson.json"
        },
        "local_mode": LOCAL_MODE,
        "azure_auth": USE_AZURE_AUTH,
        "multi_container_support": True,
        "note": "OAuth token grants access to ALL containers based on RBAC role assignments"
    }


@app.on_event("startup")
async def startup_event():
    """Initialize database connection and Azure OAuth authentication on startup."""
    global DATABASE_URL  # Need to modify the global variable

    logger.info("=" * 60)
    logger.info("TiTiler-pgSTAC with Azure OAuth Auth - Starting up")
    logger.info("=" * 60)
    logger.info(f"Version: 1.0.0")
    logger.info(f"Local mode: {LOCAL_MODE}")
    logger.info(f"Azure Storage auth enabled: {USE_AZURE_AUTH}")
    logger.info(f"PostgreSQL auth mode: {POSTGRES_AUTH_MODE}")

    # ============================================
    # STEP 1: BUILD DATABASE_URL BASED ON AUTH MODE
    # ============================================

    # Validate common required variables - warn but don't crash
    if not all([POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER]):
        logger.warning("=" * 60)
        logger.warning("⚠️  Missing PostgreSQL environment variables!")
        logger.warning(f"  POSTGRES_HOST: {POSTGRES_HOST or '(not set)'}")
        logger.warning(f"  POSTGRES_DB: {POSTGRES_DB or '(not set)'}")
        logger.warning(f"  POSTGRES_USER: {POSTGRES_USER or '(not set)'}")
        logger.warning("")
        logger.warning("The app will start but database features will not work.")
        logger.warning("Set these environment variables and restart the app.")
        logger.warning("=" * 60)
        # Don't raise - let the app start for health checks
        logger.info("✅ TiTiler-pgSTAC startup complete (degraded mode - no database)")
        return

    postgres_password = None
    db_auth_failed = False

    if POSTGRES_AUTH_MODE == "managed_identity":
        logger.info("🔐 PostgreSQL Authentication Mode: Managed Identity")
        try:
            postgres_password = get_postgres_oauth_token()
        except Exception as e:
            logger.error(f"✗ Failed to acquire PostgreSQL OAuth token: {e}")
            logger.warning("⚠️  MI authentication failed - app will start in degraded mode")
            db_auth_failed = True

    elif POSTGRES_AUTH_MODE == "key_vault":
        logger.info("🔐 PostgreSQL Authentication Mode: Key Vault")
        if not KEY_VAULT_NAME:
            logger.error("KEY_VAULT_NAME environment variable not set!")
            logger.warning("⚠️  App will start in degraded mode")
            db_auth_failed = True
        else:
            try:
                postgres_password = get_postgres_password_from_keyvault()
            except Exception as e:
                logger.error(f"✗ Failed to retrieve password from Key Vault: {e}")
                logger.warning("⚠️  Key Vault authentication failed - app will start in degraded mode")
                db_auth_failed = True

    elif POSTGRES_AUTH_MODE == "password":
        logger.info("🔐 PostgreSQL Authentication Mode: Environment Variable Password")
        if not POSTGRES_PASSWORD:
            logger.error("POSTGRES_PASSWORD environment variable not set!")
            logger.warning("⚠️  App will start in degraded mode")
            db_auth_failed = True
        else:
            postgres_password = POSTGRES_PASSWORD
            logger.info(f"✓ Using password from environment variable")
            logger.info(f"  Password length: {len(postgres_password)} characters")

    else:
        logger.error(f"Invalid POSTGRES_AUTH_MODE: {POSTGRES_AUTH_MODE}")
        logger.error("Valid modes: managed_identity, key_vault, password")
        logger.warning("⚠️  App will start in degraded mode")
        db_auth_failed = True

    # Build DATABASE_URL only if authentication succeeded
    if db_auth_failed or not postgres_password:
        logger.warning("=" * 60)
        logger.warning("⚠️  Database authentication failed")
        logger.warning("App will start but database features will not work.")
        logger.warning("=" * 60)
        DATABASE_URL = None
    else:
        DATABASE_URL = (
            f"postgresql://{POSTGRES_USER}:{postgres_password}"
            f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}?sslmode=require"
        )

        logger.info(f"✓ Built DATABASE_URL with {POSTGRES_AUTH_MODE} authentication")
        logger.info(f"  Host: {POSTGRES_HOST}")
        logger.info(f"  Database: {POSTGRES_DB}")
        logger.info(f"  User: {POSTGRES_USER}")

    # ============================================
    # STEP 2: CONNECT TO DATABASE (non-fatal if fails)
    # ============================================

    if DATABASE_URL:
        logger.info(f"Connecting to PostgreSQL database...")
        try:
            db_settings = PostgresSettings(database_url=DATABASE_URL)
            await connect_to_db(app, settings=db_settings)
            logger.info("✓ Database connection established")
            logger.info("  Connection pool created and ready")
            # Record successful connection
            with db_error_cache["lock"]:
                db_error_cache["last_error"] = None
                db_error_cache["last_success_time"] = datetime.now(timezone.utc)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"✗ Failed to connect to database: {error_msg}")
            logger.error("")
            logger.error("Troubleshooting:")
            logger.error("  - Verify PostgreSQL server is running")
            logger.error("  - Verify user exists in database")
            logger.error("  - Verify MI token is valid (if using MI)")
            logger.error("  - Check firewall rules allow App Service")
            logger.error("")
            logger.warning("⚠️  App will start in degraded mode - database features unavailable")
            # Store error for health check reporting
            with db_error_cache["lock"]:
                db_error_cache["last_error"] = error_msg
                db_error_cache["last_error_time"] = datetime.now(timezone.utc)
            # Don't raise - let the app start for health checks
    else:
        logger.warning("DATABASE_URL not configured - running in degraded mode")
        with db_error_cache["lock"]:
            db_error_cache["last_error"] = "DATABASE_URL not configured"
            db_error_cache["last_error_time"] = datetime.now(timezone.utc)

    # ============================================
    # STEP 3: INITIALIZE STORAGE OAUTH
    # ============================================

    if USE_AZURE_AUTH:
        if not AZURE_STORAGE_ACCOUNT:
            logger.error("AZURE_STORAGE_ACCOUNT environment variable not set!")
            logger.error("Set this to your storage account name for Azure auth to work")
        else:
            logger.info(f"Storage account: {AZURE_STORAGE_ACCOUNT}")

            try:
                # Get initial OAuth token for storage
                token = get_azure_storage_oauth_token()
                if token:
                    logger.info("✓ Storage OAuth authentication initialized successfully")
                    logger.info(f"✓ Token expires at: {oauth_token_cache['expires_at']}")
                    logger.info(f"✓ Access scope: ALL containers per RBAC role")
                    if LOCAL_MODE:
                        logger.info("✓ Using Azure CLI credentials (az login)")
                    else:
                        logger.info("✓ Using Managed Identity")
                else:
                    logger.warning("Failed to get initial storage OAuth token")
            except Exception as e:
                logger.error(f"Failed to initialize storage OAuth authentication: {e}")
                logger.error("The app will continue but may not access Azure Storage")
                if LOCAL_MODE:
                    logger.info("TIP: Run 'az login' to authenticate locally")
    else:
        logger.info("Azure Storage authentication is disabled")

    # ============================================
    # STEP 4: START BACKGROUND TOKEN REFRESH
    # ============================================

    if USE_AZURE_AUTH:
        asyncio.create_task(token_refresh_background_task())
        logger.info("🔄 Background token refresh task started (45-minute interval)")

    logger.info("=" * 60)
    logger.info("✅ TiTiler-pgSTAC startup complete")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("TiTiler-pgSTAC with Azure OAuth Auth - Shutting down")

    # Close database connection
    await close_db_connection(app)

    logger.info("Shutdown complete")
