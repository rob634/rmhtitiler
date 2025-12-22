"""
TiTiler with Azure OAuth Token Authentication and Planetary Computer Support
=============================================================================

This module provides a production-ready TiTiler deployment with two authentication mechanisms:

1. AZURE MANAGED IDENTITY (for your own Azure Blob Storage)
   ---------------------------------------------------------
   Uses OAuth bearer tokens via Azure Managed Identity to access COGs and Zarr stores
   in your Azure Blob Storage accounts. This is the primary authentication method for
   data you own and control.

   - Production: Uses Managed Identity assigned to Azure App Service
   - Development: Uses Azure CLI credentials (az login)
   - Scope: All containers your identity has RBAC access to
   - Endpoints: /cog/* and /xarray/* for your Azure storage

2. PLANETARY COMPUTER CREDENTIAL PROVIDER (for external climate data)
   -------------------------------------------------------------------
   Microsoft's Planetary Computer hosts petabytes of environmental data including
   CMIP6 climate projections in Zarr format. This data requires authentication via
   their SAS token service.

   The `PlanetaryComputerCredentialProvider` is a specialized authentication mechanism
   from the `obstore` library that:

   - Automatically fetches SAS tokens from Planetary Computer's token API
   - Caches tokens and refreshes them before expiry
   - Works transparently with titiler-xarray's Zarr reader
   - Only activates for URLs matching Planetary Computer storage accounts

   Planetary Computer Storage Accounts (auto-detected):
   - rhgeuwest.blob.core.windows.net (Climate Impact Lab data)
   - ai4edataeuwest.blob.core.windows.net (gridMET, Daymet)
   - Other PC storage accounts

   Available CMIP6 Zarr Collections:
   - cil-gdpcir-cc0: Climate Impact Lab downscaled projections (Public Domain)
   - cil-gdpcir-cc-by: Climate Impact Lab projections (CC-BY license)

   Example Zarr paths:
   - ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmax/v1.1.zarr (max temperature)
   - ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmin/v1.1.zarr (min temperature)
   - ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/pr/v1.1.zarr (precipitation)

ARCHITECTURE
------------
The xarray endpoints (/xarray/*) use a custom opener function that:
1. Parses the incoming URL to determine the storage provider
2. For Planetary Computer URLs: Uses PlanetaryComputerCredentialProvider
3. For your Azure URLs: Uses the OAuth token from Managed Identity
4. For other URLs: Uses default (anonymous) access

This allows seamless access to both your private data AND public climate datasets
through the same API endpoints.

ENVIRONMENT VARIABLES
---------------------
- USE_AZURE_AUTH: Enable Azure authentication (true/false)
- AZURE_STORAGE_ACCOUNT: Your Azure storage account name
- LOCAL_MODE: Use Azure CLI credentials instead of Managed Identity (true/false)
- ENABLE_PLANETARY_COMPUTER: Enable Planetary Computer support (true/false, default: true)

VERSION: 0.4.0
"""
import os
import re
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Optional, Any, Dict, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from titiler.core.factory import TilerFactory
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers

# Xarray/Zarr support for multidimensional data
from titiler.xarray.factory import TilerFactory as XarrayTilerFactory
from titiler.xarray.extensions import VariablesExtension

# Planetary Computer credential provider for external climate data
# This is imported conditionally to allow graceful degradation if not installed
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
ENABLE_PLANETARY_COMPUTER = os.getenv("ENABLE_PLANETARY_COMPUTER", "true").lower() == "true"

# ============================================================================
# PLANETARY COMPUTER CONFIGURATION
# ============================================================================
# Known Planetary Computer storage accounts that require their SAS token service.
# When a URL matches one of these accounts, we use PlanetaryComputerCredentialProvider
# instead of our Azure Managed Identity.
#
# These storage accounts host public environmental datasets that are free to access
# but require authentication via Planetary Computer's token service.

PLANETARY_COMPUTER_STORAGE_ACCOUNTS = {
    # Climate Impact Lab downscaled CMIP6 projections (Zarr format)
    # Collections: cil-gdpcir-cc0, cil-gdpcir-cc-by
    "rhgeuwest": "cil-gdpcir-cc0",

    # gridMET meteorological data, Daymet climate data
    # Collections: gridmet, daymet-daily-hi, daymet-daily-na, etc.
    "ai4edataeuwest": "daymet-daily-na",

    # Additional Planetary Computer storage accounts can be added here
    # Format: "storage_account_name": "default_collection_id"
}

# Cache for Planetary Computer credential providers (one per storage account)
_pc_credential_cache: Dict[str, Any] = {}
_pc_credential_lock = Lock()


def is_planetary_computer_url(url: str) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Check if a URL points to a Planetary Computer storage account.

    Planetary Computer hosts environmental datasets on Azure Blob Storage accounts
    that require authentication via their SAS token service. This function detects
    URLs that need Planetary Computer credentials.

    Args:
        url: The URL to check (can be https:// or abfs:// format)

    Returns:
        Tuple of (is_pc_url, storage_account, collection_id):
        - is_pc_url: True if this is a Planetary Computer URL
        - storage_account: The Azure storage account name (e.g., "rhgeuwest")
        - collection_id: The default collection ID for token requests

    Examples:
        >>> is_planetary_computer_url("https://rhgeuwest.blob.core.windows.net/cil-gdpcir/...")
        (True, "rhgeuwest", "cil-gdpcir-cc0")

        >>> is_planetary_computer_url("https://myaccount.blob.core.windows.net/container/...")
        (False, None, None)

        >>> is_planetary_computer_url("abfs://cil-gdpcir@rhgeuwest.dfs.core.windows.net/...")
        (True, "rhgeuwest", "cil-gdpcir-cc0")
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

    The PlanetaryComputerCredentialProvider is a specialized authentication mechanism
    from the obstore library. It works by:

    1. Making a request to Planetary Computer's SAS token API based on the URL
    2. Receiving a time-limited SAS token that grants read access to the storage
    3. Automatically refreshing the token before it expires
    4. Injecting the token into all requests made by the obstore AzureStore

    This is different from Azure Managed Identity because:
    - Managed Identity: Your app's identity has RBAC permissions on YOUR storage
    - PC Credential Provider: Gets temporary tokens for THEIR public storage

    The credential provider is cached per URL to avoid creating multiple
    instances and to ensure token caching works correctly.

    Args:
        url: The full URL to the Planetary Computer Zarr data

    Returns:
        A PlanetaryComputerCredentialProvider instance, or None if not available

    Note:
        Requires the obstore package:
        pip install obstore
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
                # Pass the URL directly - obstore extracts account/container from it
                provider = PlanetaryComputerCredentialProvider(url=url)
                _pc_credential_cache[cache_key] = provider
                logger.info(f"✓ Credential provider created for {cache_key}")
            except Exception as e:
                logger.error(f"Failed to create PC credential provider for {cache_key}: {e}")
                logger.error(f"Error details: {type(e).__name__}: {str(e)}")
                _pc_credential_cache[cache_key] = None

        return _pc_credential_cache.get(cache_key)


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


def setup_fsspec_azure_credentials(account_name: str):
    """
    Configure fsspec/adlfs to use Azure OAuth token.

    adlfs uses DefaultAzureCredential automatically when no explicit
    credentials are provided. This works because:
    - In dev: Azure CLI credentials (az login)
    - In prod: Managed Identity

    We just need to set the account name for fsspec to know which
    storage account to connect to.
    """
    os.environ["AZURE_STORAGE_ACCOUNT_NAME"] = account_name
    logger.debug(f"Configured fsspec/adlfs for account: {account_name}")


class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage OAuth token is set before each request.

    Configures authentication for:
    - GDAL: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN (for /vsiaz/ COG access)
    - fsspec/adlfs: AZURE_STORAGE_ACCOUNT_NAME (for abfs:// Zarr access)
    """
    async def dispatch(self, request: Request, call_next):
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                # Get OAuth token (uses cache if valid)
                token = get_azure_storage_oauth_token()

                if token:
                    # Set environment variables for GDAL (COG access via /vsiaz/)
                    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
                    logger.debug(f"Set OAuth token for storage account: {AZURE_STORAGE_ACCOUNT}")
                    logger.debug("GDAL will use: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN")

                    # Configure fsspec/adlfs for Zarr access (uses DefaultAzureCredential)
                    setup_fsspec_azure_credentials(AZURE_STORAGE_ACCOUNT)
                    logger.debug("fsspec/adlfs will use: DefaultAzureCredential")

            except Exception as e:
                logger.error(f"Error in Azure auth middleware: {e}", exc_info=True)
                # Continue with request even if auth fails (may result in 403 errors)

        response = await call_next(request)
        return response


# Create FastAPI application
app = FastAPI(
    title="TiTiler with Azure OAuth Auth + Multidimensional Support",
    description="""
    Cloud Optimized GeoTIFF and Zarr/NetCDF tile server with Azure Managed Identity authentication.

    Endpoints:
    - /cog/* - Cloud Optimized GeoTIFFs
    - /xarray/* - Zarr and NetCDF multidimensional arrays

    Both use Azure Managed Identity for authentication.
    """,
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

# Register TiTiler COG endpoints
cog = TilerFactory(router_prefix="/cog")
app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])

# Register TiTiler xarray endpoints for Zarr/NetCDF support
xarray_tiler = XarrayTilerFactory(
    router_prefix="/xarray",
    extensions=[
        VariablesExtension(),  # Adds /variables endpoint to list dataset variables
    ],
)
app.include_router(xarray_tiler.router, prefix="/xarray", tags=["Multidimensional (Zarr/NetCDF)"])


# ============================================================================
# PLANETARY COMPUTER ENDPOINTS
# ============================================================================
# These endpoints provide access to Microsoft Planetary Computer's environmental
# datasets using their SAS token authentication. They are separate from the main
# /xarray/* endpoints because they require a different authentication mechanism.


@app.get("/pc/variables", tags=["Planetary Computer"])
async def pc_variables(
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    collection: Optional[str] = Query(None, description="Collection ID for SAS token (auto-detected if not provided)")
):
    """
    List variables in a Planetary Computer Zarr dataset.

    This endpoint provides access to Zarr datasets hosted on Microsoft's Planetary
    Computer platform. It automatically handles authentication via their SAS token
    service using the PlanetaryComputerCredentialProvider.

    **How Authentication Works:**

    1. The URL is parsed to identify the Planetary Computer storage account
    2. A SAS token is fetched from: https://planetarycomputer.microsoft.com/api/sas/v1/token/{collection}
    3. The token is cached and automatically refreshed before expiry
    4. All requests to the Zarr store include the SAS token

    **Available Collections:**

    - `cil-gdpcir-cc0`: Climate Impact Lab CMIP6 projections (Public Domain)
    - `cil-gdpcir-cc-by`: Climate Impact Lab CMIP6 projections (CC-BY)
    - `daymet-daily-na`: Daymet daily climate data (North America)
    - `gridmet`: gridMET meteorological data

    **Example URLs:**

    - `https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmax/v1.1.zarr`
    - `https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr`

    Args:
        url: The Planetary Computer Zarr URL
        collection: Optional collection ID (auto-detected from URL if not provided)

    Returns:
        List of variable names in the Zarr dataset
    """
    import xarray as xr
    from zarr.storage import ObjectStore

    if not PLANETARY_COMPUTER_AVAILABLE:
        return {"error": "Planetary Computer support not installed. Install with: pip install obstore[planetary-computer]"}

    # Detect if this is a PC URL and get the collection
    is_pc, storage_account, default_collection = is_planetary_computer_url(url)

    if not is_pc:
        return {"error": f"URL does not appear to be a Planetary Computer URL. Known PC storage accounts: {list(PLANETARY_COMPUTER_STORAGE_ACCOUNTS.keys())}"}

    try:
        # Get the credential provider using the full URL
        credential_provider = get_planetary_computer_credential_provider(url)
        if not credential_provider:
            return {"error": f"Failed to get credential provider for URL: {url}"}

        # Parse the URL to extract container and path for info
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/', 1)
        container = path_parts[0]
        zarr_path = path_parts[1] if len(path_parts) > 1 else ""

        logger.info(f"Opening Planetary Computer Zarr: {url}")

        # Create Azure store with PC credentials
        # The credential provider is created from the full URL and includes account/container/prefix info
        store = AzureStore(credential_provider=credential_provider)

        # Create Zarr-compatible store wrapper
        zarr_store = ObjectStore(store, read_only=True)

        # Open with xarray (decode_times=False handles non-standard calendars like 'noleap')
        ds = xr.open_zarr(zarr_store, consolidated=True, decode_times=False)

        # Get variable names (data variables, not coordinates)
        variables = list(ds.data_vars.keys())

        return {
            "variables": variables,
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
    """
    Get metadata for a variable in a Planetary Computer Zarr dataset.

    Returns dimension information, coordinate ranges, and attributes for the
    specified variable.

    Args:
        url: The Planetary Computer Zarr URL
        variable: The variable name (e.g., "tasmax", "pr")
        collection: Optional collection ID

    Returns:
        Variable metadata including dimensions, shape, dtype, and attributes
    """
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

        # Create Azure store with PC credentials
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


@app.get("/pc/collections", tags=["Planetary Computer"])
async def pc_collections():
    """
    List known Planetary Computer collections and their storage accounts.

    This endpoint returns the pre-configured Planetary Computer storage accounts
    and their default collection IDs. These are used for automatic SAS token
    acquisition when accessing data.

    To add support for additional collections, update the
    PLANETARY_COMPUTER_STORAGE_ACCOUNTS dictionary in the configuration.

    Returns:
        Dictionary of storage accounts and their default collections
    """
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


@app.get("/healthz", tags=["Health"])
async def health():
    """Health check endpoint with OAuth token status"""
    status = {
        "status": "healthy",
        "azure_auth_enabled": USE_AZURE_AUTH,
        "local_mode": LOCAL_MODE,
        "auth_type": "OAuth Bearer Token",
        "supported_formats": {
            "cog": "/cog/* endpoints",
            "zarr": "/xarray/* endpoints",
            "netcdf": "/xarray/* endpoints"
        }
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


@app.get("/livez", tags=["Health"])
async def liveness():
    """Liveness probe - simple check that the app is running"""
    return {"status": "alive"}


@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information"""
    return {
        "title": "TiTiler with Multidimensional Support",
        "description": "Cloud Optimized GeoTIFF and Zarr/NetCDF tile server with OAuth token support",
        "version": "0.4.0",
        "auth_type": "OAuth Bearer Token (Managed Identity)",
        "endpoints": {
            "health": "/healthz",
            "docs": "/docs",
            "redoc": "/redoc",
            # COG endpoints
            "cog_info": "/cog/info?url=<path>",
            "cog_tiles": "/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}?url=<path>",
            "cog_viewer": "/cog/{tileMatrixSetId}/map.html?url=<path>",
            # Xarray/Zarr endpoints
            "xarray_info": "/xarray/info?url=<zarr_url>&variable=<var>",
            "xarray_variables": "/xarray/variables?url=<zarr_url>",
            "xarray_tiles": "/xarray/tiles/{tileMatrixSetId}/{z}/{x}/{y}?url=<zarr_url>&variable=<var>",
        },
        "url_formats": {
            "cog_local": "/vsiaz/container/path/to/file.tif",
            "zarr_azure": "abfs://container/path/to/store.zarr",
            "zarr_https": "https://account.blob.core.windows.net/container/store.zarr",
        },
        "local_mode": LOCAL_MODE,
        "azure_auth": USE_AZURE_AUTH,
        "examples": {
            "local_cog": "/cog/info?url=/data/example.tif" if LOCAL_MODE else None,
            "azure_cog": "/cog/info?url=/vsiaz/container/path/to/file.tif" if USE_AZURE_AUTH else None,
            "azure_zarr": "/xarray/variables?url=abfs://container/store.zarr" if USE_AZURE_AUTH else None,
        },
        "multi_container_support": True,
        "note": "OAuth token grants access to ALL containers based on RBAC role assignments"
    }


@app.on_event("startup")
async def startup_event():
    """Initialize Azure OAuth authentication on startup"""
    logger.info("=" * 60)
    logger.info("TiTiler with Multidimensional Support - Starting up")
    logger.info("=" * 60)
    logger.info(f"Version: 0.4.0")
    logger.info(f"Supported formats: COG, Zarr, NetCDF")
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
                    logger.info("✓ GDAL (/vsiaz/) ready for COG access")
                    logger.info("✓ fsspec (abfs://) ready for Zarr access")
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
    logger.info("TiTiler with Multidimensional Support - Shutting down")
