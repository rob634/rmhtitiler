"""
TiTiler with Azure User Delegation SAS Token authentication

Development: Uses storage account key to generate User Delegation SAS tokens
Production: Uses Managed Identity to generate User Delegation SAS tokens

This approach:
1. Tests the SAS token workflow in development
2. Never exposes storage keys in environment variables (more secure)
3. Easy transition to production (just swap credential type)
"""
import os
import logging
from datetime import datetime, timezone, timedelta
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

# SAS Token cache - shared across all workers
sas_cache = {
    "sas_token": None,
    "expires_at": None,
    "lock": Lock()
}

# Configuration
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
AZURE_STORAGE_KEY = os.getenv("AZURE_STORAGE_KEY")  # For development only
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"
USE_SAS_TOKEN = os.getenv("USE_SAS_TOKEN", "true").lower() == "true"


def get_credential():
    """
    Get Azure credential based on environment.
    Development: Uses storage account key
    Production: Uses Managed Identity
    """
    if LOCAL_MODE and AZURE_STORAGE_KEY:
        logger.info("Using storage account key credential (development mode)")
        from azure.storage.blob import BlobServiceClient
        # Create credential from account key
        from azure.core.credentials import AzureNamedKeyCredential
        return AzureNamedKeyCredential(AZURE_STORAGE_ACCOUNT, AZURE_STORAGE_KEY)
    else:
        logger.info("Using DefaultAzureCredential (managed identity/Azure CLI)")
        from azure.identity import DefaultAzureCredential
        return DefaultAzureCredential()


def generate_user_delegation_sas() -> Optional[str]:
    """
    Generate a User Delegation SAS token for the storage account.

    User Delegation SAS is more secure than Account Key SAS because:
    - Uses Azure AD credentials (not account keys)
    - Can be scoped to specific permissions
    - Can be revoked by revoking the Azure AD identity

    Development: Uses storage account key to get user delegation key
    Production: Uses Managed Identity to get user delegation key
    """
    if not USE_AZURE_AUTH or not USE_SAS_TOKEN:
        logger.debug("SAS token generation skipped (USE_AZURE_AUTH or USE_SAS_TOKEN disabled)")
        return None

    with sas_cache["lock"]:
        now = datetime.now(timezone.utc)

        # Check if we have a valid cached SAS token (refresh 5 minutes before expiry)
        if sas_cache["sas_token"] and sas_cache["expires_at"]:
            time_until_expiry = (sas_cache["expires_at"] - now).total_seconds()
            if time_until_expiry > 300:  # More than 5 minutes left
                logger.debug(f"✓ Using cached SAS token, expires in {time_until_expiry:.0f}s")
                return sas_cache["sas_token"]
            else:
                logger.info(f"⚠ SAS token expires in {time_until_expiry:.0f}s, generating new token...")

        # Need to generate a new SAS token
        try:
            from azure.storage.blob import generate_account_sas, ResourceTypes, AccountSasPermissions

            if LOCAL_MODE and AZURE_STORAGE_KEY:
                # Development: Generate account SAS using storage key
                logger.info("=" * 80)
                logger.info("🔧 DEVELOPMENT MODE: Generating Account SAS token using storage key")
                logger.info("=" * 80)

                try:
                    # Generate account SAS token (valid for 1 hour)
                    sas_token_expiry = now + timedelta(hours=1)

                    logger.debug(f"  Storage Account: {AZURE_STORAGE_ACCOUNT}")
                    logger.debug(f"  Token Expiry: {sas_token_expiry}")
                    logger.debug(f"  Permissions: Read, List")
                    logger.debug(f"  Resource Types: Container, Object")

                    sas_token = generate_account_sas(
                        account_name=AZURE_STORAGE_ACCOUNT,
                        account_key=AZURE_STORAGE_KEY,
                        resource_types=ResourceTypes(service=False, container=True, object=True),
                        permission=AccountSasPermissions(read=True, list=True),
                        expiry=sas_token_expiry
                    )

                    logger.info(f"✓ Account SAS token generated successfully (expires in 1 hour)")

                except Exception as dev_error:
                    logger.error("=" * 80)
                    logger.error("❌ FAILED TO GENERATE ACCOUNT SAS TOKEN (DEVELOPMENT MODE)")
                    logger.error("=" * 80)
                    logger.error(f"Error Type: {type(dev_error).__name__}")
                    logger.error(f"Error Message: {str(dev_error)}")
                    logger.error(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
                    logger.error(f"Has Storage Key: {bool(AZURE_STORAGE_KEY)}")
                    logger.error("=" * 80)
                    raise

            else:
                # Production: Generate User Delegation SAS using Managed Identity
                logger.info("=" * 80)
                logger.info("🚀 PRODUCTION MODE: Generating User Delegation SAS token via Managed Identity")
                logger.info("=" * 80)

                from azure.storage.blob import BlobServiceClient, generate_container_sas, ContainerSasPermissions
                from azure.identity import DefaultAzureCredential

                # Step 1: Get credential (managed identity in production)
                logger.debug("Step 1/4: Acquiring Azure credential via DefaultAzureCredential...")
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
                    logger.error("Possible causes:")
                    logger.error("  1. Managed Identity not enabled on App Service")
                    logger.error("  2. Azure environment variables not set")
                    logger.error("  3. Running in unsupported environment")
                    logger.error("")
                    logger.error("Troubleshooting:")
                    logger.error("  - Verify Managed Identity: az webapp identity show --name <app-name> --resource-group <rg>")
                    logger.error("  - Check environment variables for Azure credentials")
                    logger.error("=" * 80)
                    raise

                # Step 2: Create BlobServiceClient
                account_url = f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net"
                logger.debug(f"Step 2/4: Creating BlobServiceClient for {account_url}...")
                try:
                    blob_service_client = BlobServiceClient(
                        account_url=account_url,
                        credential=credential
                    )
                    logger.info(f"✓ BlobServiceClient created for {AZURE_STORAGE_ACCOUNT}")
                except Exception as client_error:
                    logger.error("=" * 80)
                    logger.error("❌ FAILED TO CREATE BLOB SERVICE CLIENT")
                    logger.error("=" * 80)
                    logger.error(f"Error Type: {type(client_error).__name__}")
                    logger.error(f"Error Message: {str(client_error)}")
                    logger.error(f"Storage Account URL: {account_url}")
                    logger.error("")
                    logger.error("Possible causes:")
                    logger.error("  1. Invalid storage account name")
                    logger.error("  2. Network connectivity issues")
                    logger.error("  3. Storage account doesn't exist")
                    logger.error("=" * 80)
                    raise

                # Step 3: Get user delegation key (requires managed identity with permissions)
                key_start_time = now
                key_expiry_time = now + timedelta(hours=1)
                logger.debug(f"Step 3/4: Requesting user delegation key (valid {key_start_time} to {key_expiry_time})...")
                try:
                    user_delegation_key = blob_service_client.get_user_delegation_key(
                        key_start_time=key_start_time,
                        key_expiry_time=key_expiry_time
                    )
                    logger.info("✓ User delegation key acquired successfully")
                    logger.debug(f"  Key Start: {user_delegation_key.signed_start}")
                    logger.debug(f"  Key Expiry: {user_delegation_key.signed_expiry}")
                except Exception as key_error:
                    logger.error("=" * 80)
                    logger.error("❌ FAILED TO GET USER DELEGATION KEY")
                    logger.error("=" * 80)
                    logger.error(f"Error Type: {type(key_error).__name__}")
                    logger.error(f"Error Message: {str(key_error)}")
                    logger.error(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
                    logger.error("")
                    logger.error("Possible causes:")
                    logger.error("  1. Managed Identity lacks 'Storage Blob Data Reader' role")
                    logger.error("  2. Role assignment not propagated yet (wait 5-10 minutes)")
                    logger.error("  3. Managed Identity disabled or misconfigured")
                    logger.error("")
                    logger.error("Troubleshooting:")
                    logger.error("  - Check role assignment:")
                    logger.error(f"    az role assignment list --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/{AZURE_STORAGE_ACCOUNT}")
                    logger.error("  - Grant role if missing:")
                    logger.error(f"    az role assignment create --role 'Storage Blob Data Reader' --assignee <principal-id> --scope <storage-account-id>")
                    logger.error("=" * 80)
                    raise

                # Step 4: Generate container SAS token using user delegation key
                container_name = "silver-cogs"
                logger.debug(f"Step 4/4: Generating container SAS token for '{container_name}'...")
                try:
                    sas_token = generate_container_sas(
                        account_name=AZURE_STORAGE_ACCOUNT,
                        container_name=container_name,
                        user_delegation_key=user_delegation_key,
                        permission=ContainerSasPermissions(read=True, list=True),
                        expiry=key_expiry_time
                    )
                    logger.info(f"✓ Container SAS token generated successfully for '{container_name}'")
                    logger.debug(f"  Permissions: Read, List")
                    logger.debug(f"  Expires: {key_expiry_time}")
                except Exception as sas_error:
                    logger.error("=" * 80)
                    logger.error("❌ FAILED TO GENERATE CONTAINER SAS TOKEN")
                    logger.error("=" * 80)
                    logger.error(f"Error Type: {type(sas_error).__name__}")
                    logger.error(f"Error Message: {str(sas_error)}")
                    logger.error(f"Container: {container_name}")
                    logger.error(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
                    logger.error("")
                    logger.error("Possible causes:")
                    logger.error("  1. Invalid container name")
                    logger.error("  2. Container doesn't exist")
                    logger.error("  3. Permission mismatch (using wrong permission type)")
                    logger.error("=" * 80)
                    raise

                sas_token_expiry = key_expiry_time
                logger.info("=" * 80)
                logger.info("✓ USER DELEGATION SAS TOKEN GENERATION COMPLETE")
                logger.info("=" * 80)

            # Cache the SAS token
            sas_cache["sas_token"] = sas_token
            sas_cache["expires_at"] = sas_token_expiry

            expires_in = (sas_cache["expires_at"] - now).total_seconds()
            logger.info(f"✓ SAS token cached, expires at {sas_cache['expires_at']} (in {expires_in:.0f}s)")

            return sas_token

        except Exception as e:
            logger.error("=" * 80)
            logger.error("❌ CATASTROPHIC FAILURE IN SAS TOKEN GENERATION")
            logger.error("=" * 80)
            logger.error(f"Error Type: {type(e).__name__}")
            logger.error(f"Error Message: {str(e)}")
            logger.error(f"Mode: {'DEVELOPMENT' if LOCAL_MODE else 'PRODUCTION'}")
            logger.error(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
            logger.error(f"USE_AZURE_AUTH: {USE_AZURE_AUTH}")
            logger.error(f"USE_SAS_TOKEN: {USE_SAS_TOKEN}")
            logger.error("")

            # If we have a cached token (even if expired), use it
            if sas_cache["sas_token"]:
                logger.warning("⚠ ATTEMPTING FALLBACK: Using expired cached SAS token")
                logger.warning(f"   Cached token expired at: {sas_cache['expires_at']}")
                logger.warning("   This may result in 403 Forbidden errors!")
                logger.error("=" * 80)
                return sas_cache["sas_token"]

            logger.error("❌ NO FALLBACK AVAILABLE: No cached token exists")
            logger.error("   Application will NOT be able to access Azure Storage!")
            logger.error("=" * 80)
            logger.error("Full traceback:", exc_info=True)
            logger.error("=" * 80)
            raise


class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage credentials are set before each request.
    Uses SAS tokens for secure, delegated access to Azure Storage.
    """
    async def dispatch(self, request: Request, call_next):
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                if USE_SAS_TOKEN:
                    # Get fresh SAS token (uses cache if valid)
                    sas_token = generate_user_delegation_sas()

                    if sas_token:
                        # CRITICAL: Ensure storage key is NOT in environment variables
                        # Remove it if it exists (safety measure)
                        if "AZURE_STORAGE_ACCESS_KEY" in os.environ:
                            del os.environ["AZURE_STORAGE_ACCESS_KEY"]
                            logger.warning("Removed AZURE_STORAGE_ACCESS_KEY from environment (SAS mode)")

                        # Set environment variables that GDAL will use
                        os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                        os.environ["AZURE_STORAGE_SAS_TOKEN"] = sas_token
                        logger.debug(f"Set Azure SAS token for storage account: {AZURE_STORAGE_ACCOUNT}")
                        logger.debug("GDAL will use: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_SAS_TOKEN")
                else:
                    # Fallback: use account key directly (not recommended for production)
                    if AZURE_STORAGE_KEY:
                        os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                        os.environ["AZURE_STORAGE_ACCESS_KEY"] = AZURE_STORAGE_KEY
                        logger.debug(f"Set Azure account key for storage account: {AZURE_STORAGE_ACCOUNT}")

            except Exception as e:
                logger.error(f"Error in Azure auth middleware: {e}", exc_info=True)
                # Continue with request even if auth fails

        response = await call_next(request)
        return response


# Create FastAPI application
app = FastAPI(
    title="TiTiler with Azure Auth",
    description="Cloud Optimized GeoTIFF tile server with Azure Managed Identity authentication",
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

# Register TiTiler COG endpoints
cog = TilerFactory(router_prefix="/cog")
app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])


@app.get("/healthz", tags=["Health"])
async def health():
    """Health check endpoint"""
    status = {
        "status": "healthy",
        "azure_auth_enabled": USE_AZURE_AUTH,
        "use_sas_token": USE_SAS_TOKEN,
        "local_mode": LOCAL_MODE
    }

    if USE_AZURE_AUTH:
        status["storage_account"] = AZURE_STORAGE_ACCOUNT
        if USE_SAS_TOKEN and sas_cache["expires_at"]:
            now = datetime.now(timezone.utc)
            time_until_expiry = (sas_cache["expires_at"] - now).total_seconds()
            status["sas_token_expires_in_seconds"] = max(0, int(time_until_expiry))

    return status


@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information"""
    return {
        "title": "TiTiler with Azure Auth",
        "description": "Cloud Optimized GeoTIFF tile server with SAS token support",
        "endpoints": {
            "health": "/healthz",
            "env_check": "/debug/env",
            "docs": "/docs",
            "cog_info": "/cog/info?url=<path>",
            "cog_tiles": "/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}?url=<path>"
        },
        "local_mode": LOCAL_MODE,
        "azure_auth": USE_AZURE_AUTH,
        "use_sas_token": USE_SAS_TOKEN,
        "examples": {
            "local_file": "/cog/info?url=/data/example.tif" if LOCAL_MODE else None,
            "azure_blob": f"/cog/info?url=/vsiaz/container/path/to/file.tif" if USE_AZURE_AUTH else None
        }
    }


@app.get("/debug/env", tags=["Debug"])
async def debug_environment():
    """
    Debug endpoint to verify what GDAL sees in the environment.
    CRITICAL: Ensures storage key is NOT visible to GDAL.
    """
    azure_vars = {}

    # Check what Azure-related vars are in environment
    for key in os.environ:
        if key.startswith("AZURE_"):
            if key == "AZURE_STORAGE_ACCESS_KEY" or key == "AZURE_STORAGE_KEY":
                # NEVER expose the actual key value
                azure_vars[key] = "***REDACTED***" if os.environ.get(key) else "NOT_SET"
            elif key == "AZURE_STORAGE_SAS_TOKEN":
                # Show that SAS token exists but not the value
                token = os.environ.get(key, "")
                if token:
                    azure_vars[key] = f"SET (length: {len(token)}, starts with: {token[:15]}...)"
                else:
                    azure_vars[key] = "NOT_SET"
            else:
                azure_vars[key] = os.environ.get(key, "NOT_SET")

    # Key safety check
    has_storage_key_in_env = "AZURE_STORAGE_ACCESS_KEY" in os.environ or "AZURE_STORAGE_KEY" in os.environ
    has_sas_token_in_env = "AZURE_STORAGE_SAS_TOKEN" in os.environ

    return {
        "warning": "This endpoint is for debugging only. Disable in production!",
        "mode": {
            "local_mode": LOCAL_MODE,
            "azure_auth_enabled": USE_AZURE_AUTH,
            "use_sas_token": USE_SAS_TOKEN
        },
        "environment_variables": azure_vars,
        "security_check": {
            "storage_key_in_environment": has_storage_key_in_env,
            "sas_token_in_environment": has_sas_token_in_env,
            "status": "✅ SECURE" if (not has_storage_key_in_env and has_sas_token_in_env) else "⚠️ CHECK CONFIG"
        },
        "what_gdal_sees": {
            "AZURE_STORAGE_ACCOUNT": os.environ.get("AZURE_STORAGE_ACCOUNT", "NOT_SET"),
            "AZURE_STORAGE_ACCESS_KEY": "PRESENT" if os.environ.get("AZURE_STORAGE_ACCESS_KEY") else "NOT PRESENT",
            "AZURE_STORAGE_SAS_TOKEN": "PRESENT" if os.environ.get("AZURE_STORAGE_SAS_TOKEN") else "NOT PRESENT"
        },
        "expected_for_sas_mode": {
            "AZURE_STORAGE_ACCOUNT": "SET",
            "AZURE_STORAGE_ACCESS_KEY": "NOT PRESENT ← Key Point!",
            "AZURE_STORAGE_SAS_TOKEN": "PRESENT"
        }
    }


@app.on_event("startup")
async def startup_event():
    """Initialize Azure authentication on startup"""
    logger.info("=" * 60)
    logger.info("TiTiler with Azure SAS Token Auth - Starting up")
    logger.info("=" * 60)
    logger.info(f"Local mode: {LOCAL_MODE}")
    logger.info(f"Azure auth enabled: {USE_AZURE_AUTH}")
    logger.info(f"Use SAS tokens: {USE_SAS_TOKEN}")

    if USE_AZURE_AUTH:
        if not AZURE_STORAGE_ACCOUNT:
            logger.error("AZURE_STORAGE_ACCOUNT environment variable not set!")
            logger.error("Set this to your storage account name for Azure auth to work")
        else:
            logger.info(f"Initializing Azure auth for account: {AZURE_STORAGE_ACCOUNT}")

            if LOCAL_MODE and not AZURE_STORAGE_KEY:
                logger.warning("AZURE_STORAGE_KEY not set for local development")
                logger.warning("Set this to test SAS token generation locally")

            if USE_SAS_TOKEN:
                try:
                    # Get initial SAS token
                    sas_token = generate_user_delegation_sas()
                    if sas_token:
                        logger.info("SAS token authentication initialized successfully")
                        logger.info(f"SAS token expires at: {sas_cache['expires_at']}")
                        logger.info("SAS token workflow: Storage Key -> SAS Token -> GDAL")
                    else:
                        logger.warning("Failed to get initial SAS token")
                except Exception as e:
                    logger.error(f"Failed to initialize SAS token authentication: {e}")
                    logger.error("The app will continue but may not be able to access Azure Storage")
                    if LOCAL_MODE:
                        logger.info("TIP: Set AZURE_STORAGE_KEY environment variable to test SAS tokens locally")
            else:
                logger.info("Using direct account key authentication (not recommended for production)")
    else:
        logger.info("Azure authentication is disabled")
        logger.info("Enable with: USE_AZURE_AUTH=true")

    logger.info("=" * 60)
    logger.info("Startup complete - Ready to serve tiles!")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("TiTiler with Azure Auth - Shutting down")
