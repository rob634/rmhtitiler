"""
TiTiler-pgSTAC with Azure OAuth Token authentication

STAC catalog tile server with multi-container Azure Storage access.
OAuth tokens grant access to ALL containers based on RBAC role assignments.

Based on: rmhtitiler v2.0.0 (OAuth Bearer Token Authentication)
"""
import os
import asyncio
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from fastapi import FastAPI, Request, Response
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

# Configuration - Storage Authentication
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"

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
            from azure.identity import DefaultAzureCredential

            # Step 1: Create credential
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

    Uses Azure Managed Identity (production) or Azure CLI (local dev) to obtain OAuth tokens.
    Sets environment variables that GDAL uses for /vsiaz/ authentication.
    """
    async def dispatch(self, request: Request, call_next):
        logger.info(f"🔵 Middleware called for: {request.url.path}")
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                # Get OAuth token (uses cache if valid)
                token = get_azure_storage_oauth_token()

                if token:
                    # Set environment variables that GDAL will use
                    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token

                    # Also set GDAL config options directly (in case rasterio doesn't inherit os.environ)
                    try:
                        import rasterio
                        from rasterio import _env
                        # Set in GDAL global config
                        _env.set_gdal_config("AZURE_STORAGE_ACCOUNT", AZURE_STORAGE_ACCOUNT)
                        _env.set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token)
                        logger.info(f"✓ Set OAuth token via GDAL config for storage account: {AZURE_STORAGE_ACCOUNT}")
                    except Exception as config_err:
                        logger.warning(f"⚠ Could not set GDAL config directly: {config_err}")

                    logger.info(f"✓ Token length: {len(token)} chars")
                else:
                    logger.warning("⚠ No OAuth token available")

            except Exception as e:
                logger.error(f"❌ Error in Azure OAuth authentication: {e}", exc_info=True)
        else:
            logger.warning(f"⚠ OAuth disabled or no storage account (USE_AZURE_AUTH={USE_AZURE_AUTH}, AZURE_STORAGE_ACCOUNT={AZURE_STORAGE_ACCOUNT})")

        response = await call_next(request)
        return response


# Create FastAPI application
app = FastAPI(
    title="TiTiler-pgSTAC with Azure OAuth Auth",
    description="STAC catalog tile server with Azure Managed Identity authentication",
    version="1.0.0"
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
        1. Database connection (required for pgSTAC searches)
        2. Storage OAuth token (required for Azure blob access)
    """
    checks = {}
    issues = []
    
    # Check 1: Database connection
    db_connected = hasattr(app.state, "pool") and app.state.pool is not None
    checks["database"] = {
        "status": "ok" if db_connected else "fail",
        "required_for": ["pgSTAC searches", "mosaic endpoints"]
    }
    if db_connected and DATABASE_URL:
        checks["database"]["host"] = DATABASE_URL.split("@")[1].split("/")[0] if "@" in DATABASE_URL else "unknown"
    if not db_connected:
        issues.append("Database not connected - pgSTAC search endpoints will fail")
    
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
        except Exception as e:
            logger.error(f"✗ Failed to connect to database: {e}")
            logger.error("")
            logger.error("Troubleshooting:")
            logger.error("  - Verify PostgreSQL server is running")
            logger.error("  - Verify user exists in database")
            logger.error("  - Verify MI token is valid (if using MI)")
            logger.error("  - Check firewall rules allow App Service")
            logger.error("")
            logger.warning("⚠️  App will start in degraded mode - database features unavailable")
            # Don't raise - let the app start for health checks
    else:
        logger.warning("DATABASE_URL not configured - running in degraded mode")

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
