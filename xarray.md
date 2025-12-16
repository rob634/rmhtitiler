# TiTiler-xarray Implementation Guide

**Version: 0.1.3** | **Status: Phase 1 Complete** ✅

## Overview

This guide describes how to add multidimensional data support (Zarr/NetCDF) to an existing TiTiler application that currently serves COGs. Two implementation approaches are provided:

1. **Parallel Routes** - Add `/xarray` endpoints alongside existing `/cog` endpoints ✅ **IMPLEMENTED**
2. **Unified pgSTAC Reader** - Extend pgSTAC to route COG vs Zarr based on STAC asset media type (Phase 2)

Both approaches share the same Azure authentication pattern and can coexist.

---

## Architecture Context

### Current State
- TiTiler serving COGs via `/cog` endpoints
- Azure Managed Identity authentication via OAuth tokens
- GDAL reads COGs using `AZURE_STORAGE_ACCESS_TOKEN` environment variable
- URLs use GDAL's `/vsiaz/` virtual filesystem

### Target State
- Same COG functionality preserved
- NEW: Zarr/NetCDF support via xarray
- fsspec/adlfs handles Azure Blob access for Zarr
- Same OAuth token works for both GDAL and fsspec

### Key Libraries
```
titiler.core          - Base TiTiler functionality (already installed)
titiler.xarray        - Xarray/Zarr support (NEW)
titiler.pgstac        - pgSTAC integration (for unified approach)
adlfs                 - Azure Data Lake filesystem for fsspec (NEW)
zarr                  - Zarr array library (NEW)
h5netcdf              - NetCDF reader (NEW, optional)
fsspec                - Filesystem abstraction (NEW)
```

---

## Approach 1: Parallel Routes (Simplest)

This approach adds a separate `/xarray` router alongside existing `/cog` endpoints. Minimal changes to existing code.

### Dependencies to Add

```txt
# requirements.txt additions
titiler.xarray[full]>=0.18.0
adlfs>=2024.4.1
```

The `[full]` extra includes: fsspec, zarr, h5netcdf, s3fs, aiohttp

### Implementation

```python
"""
TiTiler with Azure OAuth Token authentication + Xarray Support

Extends base TiTiler to support both:
- COGs via /cog endpoints (existing)
- Zarr/NetCDF via /xarray endpoints (new)

Both use the same Azure Managed Identity OAuth token.
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

# NEW: Import xarray components
from titiler.xarray.factory import TilerFactory as XarrayTilerFactory
from titiler.xarray.extensions import VariablesExtension

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
    [... existing implementation unchanged ...]
    """
    # Keep existing implementation exactly as-is
    pass  # Placeholder - use existing code


def setup_fsspec_azure_credentials(token: str, account_name: str):
    """
    Configure fsspec/adlfs to use Azure OAuth token.
    
    This enables xarray to read Zarr stores from Azure Blob Storage
    using the same Managed Identity token that GDAL uses for COGs.
    
    Args:
        token: OAuth bearer token for Azure Storage
        account_name: Azure Storage account name
    """
    # Method 1: Environment variables (adlfs respects these)
    os.environ["AZURE_STORAGE_ACCOUNT_NAME"] = account_name
    
    # Note: adlfs can use DefaultAzureCredential directly, but we already
    # have the token, so we can pass it via storage_options in open_zarr calls.
    # The XarrayReader will need custom storage_options injection.
    
    # For now, we rely on DefaultAzureCredential which adlfs uses automatically
    # when no explicit credentials are provided. This works because:
    # - In dev: Azure CLI credentials (az login)
    # - In prod: Managed Identity
    
    logger.debug(f"Configured fsspec/adlfs for account: {account_name}")


class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage OAuth token is set before each request.
    
    Sets environment variables for:
    - GDAL: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN (for /vsiaz/)
    - fsspec/adlfs: AZURE_STORAGE_ACCOUNT_NAME (uses DefaultAzureCredential)
    """
    async def dispatch(self, request: Request, call_next):
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                # Get OAuth token (uses cache if valid)
                token = get_azure_storage_oauth_token()

                if token:
                    # GDAL environment variables (existing)
                    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
                    
                    # fsspec/adlfs environment variables (NEW)
                    setup_fsspec_azure_credentials(token, AZURE_STORAGE_ACCOUNT)
                    
                    logger.debug(f"Set OAuth credentials for both GDAL and fsspec")

            except Exception as e:
                logger.error(f"Error in Azure auth middleware: {e}", exc_info=True)

        response = await call_next(request)
        return response


# Create FastAPI application
app = FastAPI(
    title="TiTiler with Azure OAuth Auth + Multidimensional Support",
    description="""
    Cloud Optimized GeoTIFF and Zarr/NetCDF tile server.
    
    Endpoints:
    - /cog/* - Cloud Optimized GeoTIFFs
    - /xarray/* - Zarr and NetCDF multidimensional arrays
    
    Both use Azure Managed Identity for authentication.
    """,
    version="3.0.0"
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
# EXISTING: COG endpoints
# ============================================================================
cog = TilerFactory(router_prefix="/cog")
app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])

# ============================================================================
# NEW: Xarray/Zarr endpoints
# ============================================================================
xarray_tiler = XarrayTilerFactory(
    router_prefix="/xarray",
    extensions=[
        VariablesExtension(),  # Adds /variables endpoint to list dataset variables
    ],
)
app.include_router(xarray_tiler.router, prefix="/xarray", tags=["Multidimensional (Zarr/NetCDF)"])


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
            status["token_status"] = "active"
        else:
            status["token_status"] = "not_initialized"

    return status


@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information"""
    return {
        "title": "TiTiler with Multidimensional Support",
        "version": "3.0.0",
        "endpoints": {
            "health": "/healthz",
            "docs": "/docs",
            # COG endpoints
            "cog_info": "/cog/info?url=<path>",
            "cog_tiles": "/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}?url=<path>",
            # Xarray endpoints (NEW)
            "xarray_info": "/xarray/info?url=<zarr_url>&variable=<var>",
            "xarray_variables": "/xarray/variables?url=<zarr_url>",
            "xarray_tiles": "/xarray/tiles/{tileMatrixSetId}/{z}/{x}/{y}?url=<zarr_url>&variable=<var>",
        },
        "url_formats": {
            "cog_local": "/vsiaz/container/path/to/file.tif",
            "zarr_azure": "abfs://container/path/to/store.zarr",
            "zarr_https": "https://account.blob.core.windows.net/container/store.zarr",
            "zarr_planetary_computer": "https://planetarycomputer.microsoft.com/api/stac/v1/..."
        }
    }


# Startup and shutdown events remain the same
@app.on_event("startup")
async def startup_event():
    """Initialize Azure OAuth authentication on startup"""
    logger.info("=" * 60)
    logger.info("TiTiler with Multidimensional Support - Starting up")
    logger.info("=" * 60)
    logger.info(f"Version: 3.0.0")
    logger.info(f"Supported formats: COG, Zarr, NetCDF")
    logger.info(f"Local mode: {LOCAL_MODE}")
    logger.info(f"Azure auth enabled: {USE_AZURE_AUTH}")

    if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
        try:
            token = get_azure_storage_oauth_token()
            if token:
                logger.info("✓ OAuth authentication initialized")
                logger.info("✓ GDAL (/vsiaz/) ready")
                logger.info("✓ fsspec (abfs://) ready")
        except Exception as e:
            logger.error(f"Failed to initialize OAuth: {e}")

    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("TiTiler - Shutting down")
```

### URL Patterns for Approach 1

| Format | URL Pattern | Example |
|--------|-------------|---------|
| COG (Azure) | `/cog/info?url=/vsiaz/container/path.tif` | `/cog/info?url=/vsiaz/cogs/dem.tif` |
| Zarr (Azure abfs) | `/xarray/info?url=abfs://container/path.zarr&variable=temp` | `/xarray/info?url=abfs://climate/cmip6.zarr&variable=tas` |
| Zarr (HTTPS) | `/xarray/info?url=https://account.blob.../path.zarr&variable=temp` | Direct HTTPS to blob |
| NetCDF | `/xarray/info?url=abfs://container/file.nc&variable=temp` | Same pattern as Zarr |

---

## Approach 2: Unified pgSTAC Reader (Production Pattern)

This approach extends pgSTAC so that Zarr assets are served through the same `/mosaic` endpoints as COGs. The reader routes to xarray or rasterio based on the asset's media type in STAC.

### Additional Dependencies

```txt
# requirements.txt additions (on top of Approach 1)
titiler.pgstac[psycopg-binary]>=1.0.0
```

### Custom Reader Implementation

Create a new file `readers.py`:

```python
"""
Custom PgSTAC Reader with Zarr/NetCDF Support

This reader extends the standard PgSTACReader to support multidimensional
data formats (Zarr, NetCDF, HDF5) alongside traditional COGs.

Routing is based on the asset's media_type in the STAC item:
- image/tiff, image/tiff; application=geotiff → RasterioReader (COG)
- application/vnd+zarr, application/x-netcdf → XarrayReader (Zarr/NetCDF)
"""
from typing import Set, Type, Tuple, Dict, Optional
import attr
from rio_tiler.io import Reader as RasterioReader
from rio_tiler.io.base import BaseReader
from rio_tiler.types import AssetInfo

# Import will fail if titiler.xarray not installed - handle gracefully
try:
    from titiler.xarray.io import Reader as XarrayReader
    XARRAY_AVAILABLE = True
except ImportError:
    XARRAY_AVAILABLE = False
    XarrayReader = None

# Import will fail if titiler.pgstac not installed
try:
    from titiler.pgstac.reader import PgSTACReader
    PGSTAC_AVAILABLE = True
except ImportError:
    PGSTAC_AVAILABLE = False
    PgSTACReader = None


# Media types for COGs (rasterio/GDAL)
COG_MEDIA_TYPES = {
    'image/tiff',
    'image/tiff; application=geotiff',
    'image/tiff; application=geotiff; profile=cloud-optimized',
    'image/tiff; profile=cloud-optimized; application=geotiff',
    'image/vnd.stac.geotiff; cloud-optimized=true',
    'image/x.geotiff',
    'image/jp2',
    'application/x-hdf',
    'application/x-hdf5',
}

# Media types for multidimensional data (xarray)
MULTIDIM_MEDIA_TYPES = {
    'application/vnd+zarr',
    'application/x-zarr',
    'application/zarr',
    'application/x-netcdf',
    'application/netcdf',
    'application/x-hdf5',  # Can be either - xarray handles HDF5 too
    'application/x-hdf',
}

# Combined valid types
ALL_VALID_TYPES = COG_MEDIA_TYPES | MULTIDIM_MEDIA_TYPES


if PGSTAC_AVAILABLE:
    @attr.s
    class MultiDimPgSTACReader(PgSTACReader):
        """
        PgSTAC Reader that supports both COG and Zarr/NetCDF assets.
        
        This reader inspects the asset's media_type and routes to the appropriate
        underlying reader:
        - COG/GeoTIFF → RasterioReader (via GDAL)
        - Zarr/NetCDF → XarrayReader (via xarray)
        
        Usage in TiTiler factory:
            mosaic = MosaicTilerFactory(reader=MultiDimPgSTACReader)
        
        STAC Item Example (Zarr asset):
            {
                "assets": {
                    "zarr": {
                        "href": "abfs://container/climate.zarr",
                        "type": "application/vnd+zarr",
                        "roles": ["data"]
                    }
                }
            }
        """
        
        # Override to include multidimensional types
        include_asset_types: Set[str] = attr.ib(default=ALL_VALID_TYPES)
        
        def _get_reader(self, asset_info: AssetInfo) -> Tuple[Type[BaseReader], Dict]:
            """
            Route to appropriate reader based on asset media type.
            
            Args:
                asset_info: Asset information including media_type and URL
                
            Returns:
                Tuple of (ReaderClass, reader_options)
            """
            media_type = asset_info.get("media_type", "")
            reader_options = asset_info.get("reader_options", {})
            
            # Check if this is a multidimensional format
            if media_type in MULTIDIM_MEDIA_TYPES:
                if not XARRAY_AVAILABLE:
                    raise ImportError(
                        f"Asset has media_type '{media_type}' but titiler.xarray "
                        "is not installed. Install with: pip install titiler.xarray[full]"
                    )
                
                # Extract xarray-specific options from asset extras if present
                # These can be set in STAC item's asset properties
                xarray_options = {}
                
                # Common xarray open options
                if "xarray:variable" in asset_info.get("metadata", {}):
                    xarray_options["variable"] = asset_info["metadata"]["xarray:variable"]
                if "xarray:group" in asset_info.get("metadata", {}):
                    xarray_options["group"] = asset_info["metadata"]["xarray:group"]
                if "xarray:decode_times" in asset_info.get("metadata", {}):
                    xarray_options["decode_times"] = asset_info["metadata"]["xarray:decode_times"]
                
                # Merge with any existing reader_options
                reader_options.update(xarray_options)
                
                return XarrayReader, reader_options
            
            # Default to rasterio reader for COGs
            return RasterioReader, reader_options
        
        def _get_asset_info(self, asset: str) -> AssetInfo:
            """
            Override to support md:// prefix for multidimensional assets.
            
            The md:// prefix allows specifying variable and other options:
                assets=md://zarr_asset?variable=temperature&time=2050-01-01
            
            Args:
                asset: Asset name, optionally with md:// prefix
                
            Returns:
                AssetInfo dict with url, media_type, and reader_options
            """
            # Handle md:// prefix for multidimensional assets
            if asset.startswith("md://"):
                from urllib.parse import urlparse, parse_qsl
                
                parsed = urlparse(asset)
                asset_name = parsed.netloc
                
                if asset_name not in self.assets:
                    raise ValueError(
                        f"Asset '{asset_name}' not found. Available: {self.assets}"
                    )
                
                # Get base asset info
                info = super()._get_asset_info(asset_name)
                
                # Parse query parameters as reader options
                query_options = dict(parse_qsl(parsed.query))
                info["reader_options"] = {
                    **info.get("reader_options", {}),
                    **query_options
                }
                
                return info
            
            # Standard asset handling
            return super()._get_asset_info(asset)


# Convenience function to check availability
def get_multidim_reader():
    """
    Get the MultiDimPgSTACReader if dependencies are available.
    
    Returns:
        MultiDimPgSTACReader class or None
        
    Raises:
        ImportError: With helpful message if dependencies missing
    """
    if not PGSTAC_AVAILABLE:
        raise ImportError(
            "titiler.pgstac is required for unified pgSTAC reader. "
            "Install with: pip install titiler.pgstac[psycopg-binary]"
        )
    
    if not XARRAY_AVAILABLE:
        raise ImportError(
            "titiler.xarray is required for Zarr/NetCDF support. "
            "Install with: pip install titiler.xarray[full]"
        )
    
    return MultiDimPgSTACReader
```

### Main Application with pgSTAC Integration

```python
"""
TiTiler with pgSTAC + Multidimensional Support

This version integrates with pgSTAC for STAC-driven tile serving.
Assets route to COG or Zarr readers based on their media type.
"""
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.pgstac.db import close_db_connection, connect_to_db
from titiler.pgstac.factory import MosaicTilerFactory

# Import custom reader
from readers import MultiDimPgSTACReader, XARRAY_AVAILABLE

# Also keep standalone xarray endpoints for direct Zarr access
if XARRAY_AVAILABLE:
    from titiler.xarray.factory import TilerFactory as XarrayTilerFactory
    from titiler.xarray.extensions import VariablesExtension

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"

# pgSTAC database configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASS = os.getenv("POSTGRES_PASS", "postgres")
POSTGRES_DBNAME = os.getenv("POSTGRES_DBNAME", "postgis")

# OAuth token cache
oauth_token_cache = {"token": None, "expires_at": None, "lock": Lock()}


def get_azure_storage_oauth_token() -> Optional[str]:
    """Get OAuth token - implementation same as before"""
    # [Keep existing implementation]
    pass


def setup_fsspec_azure_credentials(token: str, account_name: str):
    """Configure fsspec for Azure access"""
    os.environ["AZURE_STORAGE_ACCOUNT_NAME"] = account_name


class AzureAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for Azure OAuth - same as before but adds fsspec config"""
    async def dispatch(self, request: Request, call_next):
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                token = get_azure_storage_oauth_token()
                if token:
                    # GDAL (COGs)
                    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
                    # fsspec (Zarr)
                    setup_fsspec_azure_credentials(token, AZURE_STORAGE_ACCOUNT)
            except Exception as e:
                logger.error(f"Azure auth error: {e}")
        
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles:
    - pgSTAC database connection pool
    - Azure OAuth initialization
    """
    logger.info("Starting TiTiler with pgSTAC + Multidimensional Support")
    
    # Initialize Azure auth
    if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
        try:
            token = get_azure_storage_oauth_token()
            if token:
                os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
                setup_fsspec_azure_credentials(token, AZURE_STORAGE_ACCOUNT)
                logger.info("✓ Azure OAuth initialized for GDAL and fsspec")
        except Exception as e:
            logger.error(f"Azure auth init failed: {e}")
    
    # Connect to pgSTAC database
    await connect_to_db(app)
    logger.info("✓ Connected to pgSTAC database")
    
    yield
    
    # Cleanup
    await close_db_connection(app)
    logger.info("Database connection closed")


# Create application
app = FastAPI(
    title="TiTiler pgSTAC + Multidimensional",
    description="""
    STAC-driven tile server with COG and Zarr/NetCDF support.
    
    Endpoints:
    - /mosaic/* - STAC search-based mosaics (COG or Zarr based on asset type)
    - /xarray/* - Direct Zarr/NetCDF access (standalone)
    """,
    version="3.0.0",
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AzureAuthMiddleware)
add_exception_handlers(app, DEFAULT_STATUS_CODES)


# ============================================================================
# pgSTAC Mosaic endpoints (unified COG + Zarr)
# ============================================================================
mosaic = MosaicTilerFactory(
    reader=MultiDimPgSTACReader,  # Custom reader routes based on media type
    router_prefix="/mosaic"
)
app.include_router(mosaic.router, prefix="/mosaic", tags=["STAC Mosaic (COG + Zarr)"])


# ============================================================================
# Standalone xarray endpoints (direct Zarr access without STAC)
# ============================================================================
if XARRAY_AVAILABLE:
    xarray_tiler = XarrayTilerFactory(
        router_prefix="/xarray",
        extensions=[VariablesExtension()]
    )
    app.include_router(xarray_tiler.router, prefix="/xarray", tags=["Direct Zarr/NetCDF"])


# ============================================================================
# Health and info endpoints
# ============================================================================
@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "pgstac": "connected",
        "xarray_available": XARRAY_AVAILABLE,
        "azure_auth": USE_AZURE_AUTH
    }


@app.get("/")
async def root():
    return {
        "title": "TiTiler pgSTAC + Multidimensional",
        "version": "3.0.0",
        "endpoints": {
            # pgSTAC endpoints (COG or Zarr via STAC)
            "mosaic_register": "POST /mosaic/register",
            "mosaic_tiles": "/mosaic/{mosaic_id}/tiles/{z}/{x}/{y}",
            "mosaic_info": "/mosaic/{mosaic_id}/info",
            # Direct xarray endpoints
            "xarray_info": "/xarray/info?url=<zarr_url>&variable=<var>",
            "xarray_tiles": "/xarray/tiles/{z}/{x}/{y}?url=<zarr_url>&variable=<var>",
        },
        "stac_asset_routing": {
            "cog_types": ["image/tiff", "image/tiff; application=geotiff", "..."],
            "zarr_types": ["application/vnd+zarr", "application/x-netcdf", "..."],
        }
    }
```

---

## STAC Item Examples

### COG Asset (existing pattern)

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "dem-tile-001",
  "properties": {
    "datetime": "2024-01-01T00:00:00Z"
  },
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "assets": {
    "visual": {
      "href": "abfs://cogs/dem/tile001.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    }
  }
}
```

### Zarr Asset (new pattern)

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/datacube/v2.2.0/schema.json"
  ],
  "id": "cmip6-temperature-ssp245",
  "properties": {
    "datetime": null,
    "start_datetime": "2015-01-01T00:00:00Z",
    "end_datetime": "2100-12-31T00:00:00Z",
    "cube:dimensions": {
      "time": {
        "type": "temporal",
        "extent": ["2015-01-01T00:00:00Z", "2100-12-31T00:00:00Z"]
      },
      "x": {
        "type": "spatial",
        "axis": "x",
        "extent": [-180, 180],
        "reference_system": 4326
      },
      "y": {
        "type": "spatial",
        "axis": "y", 
        "extent": [-90, 90],
        "reference_system": 4326
      }
    },
    "cube:variables": {
      "tas": {
        "dimensions": ["time", "y", "x"],
        "type": "data",
        "unit": "K",
        "description": "Near-Surface Air Temperature"
      }
    }
  },
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "assets": {
    "zarr": {
      "href": "abfs://climate/cmip6/tas_ssp245.zarr",
      "type": "application/vnd+zarr",
      "roles": ["data"],
      "xarray:storage_options": {
        "account_name": "yourstorageaccount"
      }
    }
  }
}
```

---

## Azure URL Formats Reference

| Reader | Protocol | Example |
|--------|----------|---------|
| GDAL (COG) | `/vsiaz/` | `/vsiaz/container/path/file.tif` |
| fsspec (Zarr) | `abfs://` | `abfs://container/path/store.zarr` |
| fsspec (Zarr) | `az://` | `az://container/path/store.zarr` |
| fsspec (Zarr) | `https://` | `https://account.blob.core.windows.net/container/store.zarr` |

Note: GDAL uses `/vsiaz/` virtual filesystem. fsspec uses `abfs://` or `az://` protocols via the `adlfs` package.

---

## Testing

### Test COG endpoint (existing)
```bash
curl "http://localhost:8000/cog/info?url=/vsiaz/cogs/test.tif"
```

### Test Zarr endpoint (new - Approach 1)
```bash
# List variables in a Zarr store
curl "http://localhost:8000/xarray/variables?url=abfs://climate/test.zarr"

# Get info for a specific variable
curl "http://localhost:8000/xarray/info?url=abfs://climate/test.zarr&variable=temperature"

# Get a tile
curl "http://localhost:8000/xarray/tiles/WebMercatorQuad/0/0/0.png?url=abfs://climate/test.zarr&variable=temperature"
```

---

## Planetary Computer Public Datasets (Production Test Data)

Microsoft Planetary Computer provides free, public Zarr datasets that are ideal for testing. These require **no authentication** and can be accessed via HTTPS URLs.

### Available Zarr Datasets

| Dataset | Storage Account | Container | Description |
|---------|----------------|-----------|-------------|
| **gridMET** | `ai4edataeuwest` | `gridmet` | US meteorological data (1979-2020), ~4km resolution |
| **Daymet Daily Hawaii** | `daymeteuwest` | `daymet-zarr` | Hawaii climate data (1980-2020), 1km resolution |
| **Daymet Daily Puerto Rico** | `daymeteuwest` | `daymet-zarr` | Puerto Rico climate (1980-2020), 1km resolution |
| **Daymet Annual North America** | `daymeteuwest` | `daymet-zarr` | NA climate aggregates (1980-2020) |
| **Daymet Monthly North America** | `daymeteuwest` | `daymet-zarr` | NA monthly climate (1980-2020) |

### gridMET Variables (14 meteorological variables)

| Variable | Description | Units |
|----------|-------------|-------|
| `air_temperature` | Near-surface air temperature | K |
| `precipitation_amount` | Daily precipitation | mm |
| `relative_humidity` | Relative humidity | % |
| `specific_humidity` | Specific humidity | kg/kg |
| `wind_speed` | Wind speed | m/s |
| `wind_from_direction` | Wind direction | degrees |
| `potential_evapotranspiration` | PET | mm |
| `mean_vapor_pressure_deficit` | VPD | kPa |
| `surface_downwelling_shortwave_flux_in_air` | Solar radiation | W/m² |
| `burning_index_g` | Fire danger index | Unitless |
| `dead_fuel_moisture_100hr` | 100-hour fuel moisture | % |
| `dead_fuel_moisture_1000hr` | 1000-hour fuel moisture | % |

### Test Commands for Planetary Computer

```bash
# Start local server
docker-compose up --build

# ============================================================================
# gridMET (US Meteorological Data)
# ============================================================================

# List all variables
curl "http://localhost:8001/xarray/variables?url=https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr"

# Get info for air temperature
curl "http://localhost:8001/xarray/info?url=https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr&variable=air_temperature"

# Get info for precipitation
curl "http://localhost:8001/xarray/info?url=https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr&variable=precipitation_amount"

# Get a tile (example coordinates for continental US)
curl "http://localhost:8001/xarray/tiles/WebMercatorQuad/4/3/5.png?url=https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr&variable=air_temperature" -o tile.png

# ============================================================================
# Daymet Daily Hawaii
# ============================================================================

# List variables
curl "http://localhost:8001/xarray/variables?url=https://daymeteuwest.blob.core.windows.net/daymet-zarr/daily/hi.zarr"

# Get temperature info
curl "http://localhost:8001/xarray/info?url=https://daymeteuwest.blob.core.windows.net/daymet-zarr/daily/hi.zarr&variable=tmax"

# ============================================================================
# Daymet Monthly North America
# ============================================================================

# List variables
curl "http://localhost:8001/xarray/variables?url=https://daymeteuwest.blob.core.windows.net/daymet-zarr/monthly/na.zarr"
```

### URL Formats for Planetary Computer

| Protocol | URL Pattern | Use Case |
|----------|-------------|----------|
| **HTTPS** (recommended for public) | `https://{account}.blob.core.windows.net/{container}/{path}.zarr` | No auth needed, works anywhere |
| **ABFS** (for authenticated Azure) | `abfs://{container}@{account}.dfs.core.windows.net/{path}.zarr` | Requires Azure credentials |

### Example HTTPS URLs (Copy-Paste Ready)

```
# gridMET
https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr

# Daymet Daily
https://daymeteuwest.blob.core.windows.net/daymet-zarr/daily/hi.zarr
https://daymeteuwest.blob.core.windows.net/daymet-zarr/daily/pr.zarr

# Daymet Monthly
https://daymeteuwest.blob.core.windows.net/daymet-zarr/monthly/na.zarr
https://daymeteuwest.blob.core.windows.net/daymet-zarr/monthly/hi.zarr
https://daymeteuwest.blob.core.windows.net/daymet-zarr/monthly/pr.zarr

# Daymet Annual
https://daymeteuwest.blob.core.windows.net/daymet-zarr/annual/na.zarr
https://daymeteuwest.blob.core.windows.net/daymet-zarr/annual/hi.zarr
https://daymeteuwest.blob.core.windows.net/daymet-zarr/annual/pr.zarr
```

---

### Test pgSTAC mosaic (Approach 2 - Future)
```bash
# Register a mosaic from STAC search
curl -X POST "http://localhost:8000/mosaic/register" \
  -H "Content-Type: application/json" \
  -d '{"collections": ["cmip6-projections"], "filter": {"op": "=", "args": [{"property": "scenario"}, "ssp245"]}}'

# Get tiles using mosaic ID
curl "http://localhost:8000/mosaic/{mosaic_id}/tiles/WebMercatorQuad/0/0/0.png?assets=zarr&variable=tas"

# Using md:// prefix for variable specification
curl "http://localhost:8000/mosaic/{mosaic_id}/tiles/0/0/0.png?assets=md://zarr?variable=tas&time=2050-01-01"
```

---

## Environment Variables

```bash
# Azure Authentication
USE_AZURE_AUTH=true
AZURE_STORAGE_ACCOUNT=yourstorageaccount
LOCAL_MODE=false  # true for dev (uses az login), false for prod (uses Managed Identity)

# pgSTAC Database (for Approach 2)
POSTGRES_HOST=your-postgres-host.database.azure.com
POSTGRES_PORT=5432
POSTGRES_USER=pgstac_user
POSTGRES_PASS=your_password
POSTGRES_DBNAME=pgstac

# Optional: fsspec caching
FSSPEC_CACHE_DIR=/tmp/fsspec_cache
```

---

## Dockerfile Updates

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY custom_main.py .
COPY readers.py .

# Run with uvicorn
CMD ["uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### requirements.txt

```txt
# Core TiTiler
titiler.core>=0.18.0

# Xarray support (Zarr, NetCDF)
titiler.xarray[full]>=0.18.0

# pgSTAC support (for unified approach)
titiler.pgstac[psycopg-binary]>=1.0.0

# Azure authentication
azure-identity>=1.15.0

# Azure blob storage for fsspec
adlfs>=2024.4.1

# Server
uvicorn[standard]>=0.27.0
```

---

## Implementation Checklist

### Phase 1: Parallel Routes (Quick Win) ✅ COMPLETE
- [x] Add `titiler.xarray[full]` and `adlfs` to requirements
- [x] Add `XarrayTilerFactory` router to existing app
- [x] Add `setup_fsspec_azure_credentials()` to middleware
- [ ] Test with public Planetary Computer Zarr ⏳ **READY TO TEST**
- [ ] Test with Azure Blob Zarr store
- [x] Update Dockerfile

### Phase 2: Unified pgSTAC (Production)
- [ ] Add `titiler.pgstac` dependency
- [ ] Create `readers.py` with `MultiDimPgSTACReader`
- [ ] Add pgSTAC database connection lifespan
- [ ] Update app to use custom reader
- [ ] Create test STAC items with Zarr assets
- [ ] Ingest test items to pgSTAC
- [ ] Test mosaic tile serving with Zarr assets
- [ ] Add datacube extension metadata to STAC items

---

## Notes for Implementation

1. **Start with Approach 1** - it's additive and low risk
2. **fsspec auth**: adlfs uses `DefaultAzureCredential` automatically - same credential chain as azure-identity
3. **Zarr chunking**: For best tile performance, Zarr stores should have spatial chunks ~256x256 or 512x512
4. **Consolidated metadata**: Ensure Zarr stores have consolidated metadata (`zarr.consolidate_metadata()`) for faster opens
5. **Variable parameter**: Unlike COGs, Zarr requires specifying which variable to render via `?variable=` query param
6. **Time slicing**: For temporal data, use `?time=2050-01-01` or similar to select time slice