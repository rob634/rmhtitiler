"""
TiTiler with Azure OAuth Token authentication

Uses Azure Managed Identity to get OAuth bearer tokens for Azure Storage.
This approach is simpler than SAS tokens and works for ALL containers the identity has access to.

Why OAuth instead of SAS:
- SAS tokens are for *restricting* access (delegation to untrusted clients)
- OAuth tokens are for *granting* identity-based access (service-to-service)
- OAuth works for multiple containers automatically (no container-specific tokens needed)
- Simpler code, fewer dependencies, direct RBAC permission model

Development: Uses Azure CLI credentials
Production: Uses Managed Identity
"""
import os
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from titiler.core.factory import TilerFactory
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# OAuth token cache - shared across all workers
oauth_token_cache = {
    "token": None,
    "expires_at": None,
    "lock": Lock()
}

# Configuration
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"


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


class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage OAuth token is set before each request.
    Sets AZURE_STORAGE_ACCESS_TOKEN which GDAL uses for /vsiaz/ authentication.
    """
    async def dispatch(self, request: Request, call_next):
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                # Get OAuth token (uses cache if valid)
                token = get_azure_storage_oauth_token()

                if token:
                    # Set environment variables that GDAL will use
                    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
                    logger.debug(f"Set OAuth token for storage account: {AZURE_STORAGE_ACCOUNT}")
                    logger.debug("GDAL will use: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN")

            except Exception as e:
                logger.error(f"Error in Azure auth middleware: {e}", exc_info=True)
                # Continue with request even if auth fails (may result in 403 errors)

        response = await call_next(request)
        return response


# Create FastAPI application
app = FastAPI(
    title="TiTiler with Azure OAuth Auth",
    description="Cloud Optimized GeoTIFF tile server with Azure Managed Identity (OAuth) authentication",
    version="2.0.0"
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

# Register TiTiler COG endpoints
cog = TilerFactory(router_prefix="/cog")
app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])


@app.get("/healthz", tags=["Health"])
async def health():
    """Health check endpoint with OAuth token status"""
    status = {
        "status": "healthy",
        "azure_auth_enabled": USE_AZURE_AUTH,
        "local_mode": LOCAL_MODE,
        "auth_type": "OAuth Bearer Token"
    }

    if USE_AZURE_AUTH:
        status["storage_account"] = AZURE_STORAGE_ACCOUNT

        if oauth_token_cache["token"] and oauth_token_cache["expires_at"]:
            now = datetime.now(timezone.utc)
            time_until_expiry = (oauth_token_cache["expires_at"] - now).total_seconds()
            status["token_expires_in_seconds"] = max(0, int(time_until_expiry))
            status["token_scope"] = "ALL containers (RBAC-based)"
            status["token_status"] = "active"
        else:
            status["token_status"] = "not_initialized"

    return status


@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information"""
    return {
        "title": "TiTiler with Azure OAuth Auth",
        "description": "Cloud Optimized GeoTIFF tile server with OAuth token support",
        "version": "2.0.0",
        "auth_type": "OAuth Bearer Token (Managed Identity)",
        "endpoints": {
            "health": "/healthz",
            "docs": "/docs",
            "redoc": "/redoc",
            "cog_info": "/cog/info?url=<path>",
            "cog_tiles": "/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}?url=<path>",
            "cog_viewer": "/cog/{tileMatrixSetId}/map.html?url=<path>"
        },
        "local_mode": LOCAL_MODE,
        "azure_auth": USE_AZURE_AUTH,
        "examples": {
            "local_file": "/cog/info?url=/data/example.tif" if LOCAL_MODE else None,
            "azure_blob": f"/cog/info?url=/vsiaz/container/path/to/file.tif" if USE_AZURE_AUTH else None
        },
        "multi_container_support": True,
        "note": "OAuth token grants access to ALL containers based on RBAC role assignments"
    }


@app.on_event("startup")
async def startup_event():
    """Initialize Azure OAuth authentication on startup"""
    logger.info("=" * 60)
    logger.info("TiTiler with Azure OAuth Auth - Starting up")
    logger.info("=" * 60)
    logger.info(f"Version: 2.0.0")
    logger.info(f"Local mode: {LOCAL_MODE}")
    logger.info(f"Azure auth enabled: {USE_AZURE_AUTH}")
    logger.info(f"Auth type: OAuth Bearer Token")

    if USE_AZURE_AUTH:
        if not AZURE_STORAGE_ACCOUNT:
            logger.error("AZURE_STORAGE_ACCOUNT environment variable not set!")
            logger.error("Set this to your storage account name for Azure auth to work")
        else:
            logger.info(f"Storage account: {AZURE_STORAGE_ACCOUNT}")

            try:
                # Get initial OAuth token
                token = get_azure_storage_oauth_token()
                if token:
                    logger.info("✓ OAuth authentication initialized successfully")
                    logger.info(f"✓ Token expires at: {oauth_token_cache['expires_at']}")
                    logger.info(f"✓ Access scope: ALL containers per RBAC role")
                    if LOCAL_MODE:
                        logger.info("✓ Using Azure CLI credentials (az login)")
                    else:
                        logger.info("✓ Using Managed Identity")
                else:
                    logger.warning("Failed to get initial OAuth token")
            except Exception as e:
                logger.error(f"Failed to initialize OAuth authentication: {e}")
                logger.error("The app will continue but may not be able to access Azure Storage")
                if LOCAL_MODE:
                    logger.info("TIP: Run 'az login' to authenticate locally")
    else:
        logger.info("Azure authentication is disabled")
        logger.info("Enable with: USE_AZURE_AUTH=true")

    logger.info("=" * 60)
    logger.info("Startup complete - Ready to serve tiles!")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("TiTiler with Azure OAuth Auth - Shutting down")
