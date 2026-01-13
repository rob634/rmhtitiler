# TiTiler-pgSTAC Project Onboarding Guide

**Welcome to the TiTiler-pgSTAC project!** This guide will help you understand how we've customized the base TiTiler-pgSTAC application and how it integrates with our broader ETL data pipeline.

**Last Updated**: November 18, 2025
**Audience**: New developers joining the project
**Prerequisites**: Basic understanding of Python, FastAPI, Docker, and cloud storage

---

## Table of Contents

1. [What is This Project?](#what-is-this-project)
2. [How We Modified TiTiler-pgSTAC](#how-we-modified-titiler-pgstac)
3. [Integration with the ETL Pipeline](#integration-with-the-etl-pipeline)
4. [Key Architecture Concepts](#key-architecture-concepts)
5. [Local Development Setup](#local-development-setup)
6. [Common Development Tasks](#common-development-tasks)
7. [Troubleshooting](#troubleshooting)
8. [Additional Resources](#additional-resources)

---

## What is This Project?

### The Big Picture

This project is a **custom geospatial tile server** that delivers map tiles from Cloud Optimized GeoTIFF (COG) files stored in Azure Blob Storage. It's built on top of [TiTiler-pgSTAC](https://stac-utils.github.io/titiler-pgstac/), an open-source tile server for STAC catalogs.

```
User's Web Map
    ↓ (requests tiles at zoom 14, position 11454, 6143)
TiTiler-pgSTAC (this project)
    ↓ (queries database for STAC items)
PostgreSQL with pgSTAC
    ↓ (returns asset locations: /vsiaz/container/file.tif)
TiTiler-pgSTAC
    ↓ (reads COG using OAuth token)
Azure Blob Storage
    ↓ (returns imagery data)
TiTiler-pgSTAC
    ↓ (renders PNG tile)
User's Web Map (displays tile)
```

### What Makes Our Implementation Special

We've enhanced the base TiTiler-pgSTAC with:

1. **Azure Managed Identity OAuth** - Passwordless authentication to Azure Blob Storage
2. **Multi-container support** - Single token accesses all containers via RBAC
3. **Production-grade logging** - Comprehensive operational visibility
4. **Multiple access patterns** - Direct COG access, pgSTAC searches, and MosaicJSON
5. **Flexible database authentication** - Supports Managed Identity, Key Vault, or password-based auth

---

## How We Modified TiTiler-pgSTAC

### What is TiTiler-pgSTAC?

[TiTiler-pgSTAC](https://stac-utils.github.io/titiler-pgstac/) is an open-source project that combines:
- **TiTiler**: Dynamic tile server for COG files
- **pgSTAC**: PostgreSQL extension for STAC catalog storage
- **STAC**: SpatioTemporal Asset Catalog standard for geospatial metadata

### Base TiTiler-pgSTAC vs. Our Custom Implementation

| Feature | Base TiTiler-pgSTAC | Our Custom Implementation |
|---------|---------------------|---------------------------|
| **Core tile serving** | ✅ `/searches/{id}/tiles/{z}/{x}/{y}` | ✅ Same |
| **Search registration** | ✅ `/searches/register` | ✅ Same |
| **Storage authentication** | Static credentials (SAS, keys) | ✅ **Azure Managed Identity OAuth** |
| **Database authentication** | Username/password only | ✅ **3 modes: MI, Key Vault, password** |
| **CORS support** | ❌ Requires reverse proxy | ✅ **Built-in CORS middleware** |
| **Direct COG access** | ❌ Not included | ✅ **`/cog/*` endpoints** |
| **Health monitoring** | ❌ No health endpoint | ✅ **`/healthz` with status** |
| **Logging** | Basic | ✅ **Production-grade with troubleshooting** |
| **Token management** | Manual | ✅ **Automatic refresh & caching** |

### Our Key Modifications

#### 1. Azure OAuth Authentication System

**Location**: [custom_pgstac_main.py:72-191](custom_pgstac_main.py#L72-L191)

We added OAuth token management for Azure Storage:

```python
def get_azure_storage_oauth_token() -> Optional[str]:
    """
    Get OAuth token for Azure Storage using Managed Identity.

    - Tokens grant access to ALL containers based on RBAC
    - Valid for ~1 hour, automatically cached and refreshed
    - Uses DefaultAzureCredential (Managed Identity in prod, Azure CLI locally)
    """
```

**Key features**:
- In-memory token caching with automatic refresh (5 min before expiry)
- Comprehensive error logging with troubleshooting steps
- Dual-mode support: Azure CLI for local dev, Managed Identity for production

#### 2. Per-Request OAuth Middleware

**Location**: [custom_pgstac_main.py:348-388](custom_pgstac_main.py#L348-L388)

```python
class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage OAuth authentication
    is set before each request.
    """
```

**What it does**:
- Runs before every HTTP request
- Acquires/refreshes OAuth token (from cache if valid)
- Sets environment variables that GDAL uses: `AZURE_STORAGE_ACCESS_TOKEN`
- Negligible performance impact (~1-5ms) due to caching

#### 3. Flexible PostgreSQL Authentication

**Location**: [custom_pgstac_main.py:50-66](custom_pgstac_main.py#L50-L66)

We support three authentication modes:

```python
# Mode 1: Managed Identity (production - most secure)
POSTGRES_AUTH_MODE=managed_identity
POSTGRES_USER=titiler-db-access  # Must match MI name

# Mode 2: Key Vault (fallback)
POSTGRES_AUTH_MODE=key_vault
KEY_VAULT_NAME=your-vault

# Mode 3: Password (development/debugging)
POSTGRES_AUTH_MODE=password
POSTGRES_PASSWORD=your_password
```

#### 4. Additional Endpoints

**Direct COG Access** (no database required):
```
GET /cog/info?url=/vsiaz/silver-cogs/file.tif
GET /cog/tiles/WebMercatorQuad/14/11454/6143.png?url=/vsiaz/silver-cogs/file.tif
GET /cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/file.tif
```

**Health Monitoring**:
```
GET /healthz
```

Returns:
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "token_expires_in_seconds": 3456,
  "database_status": "connected"
}
```

#### 5. Production-Grade Logging

Throughout the code, we've added comprehensive logging:

```python
logger.info("=" * 80)
logger.info("🔑 Acquiring OAuth token for Azure Storage")
logger.info("=" * 80)
logger.info(f"Mode: {'DEVELOPMENT (Azure CLI)' if LOCAL_MODE else 'PRODUCTION (Managed Identity)'}")
logger.info(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
```

**Benefits**:
- Easy troubleshooting in production
- Clear visibility into OAuth token lifecycle
- Detailed error messages with resolution steps

---

## Integration with the ETL Pipeline

### The Broader System

This TiTiler-pgSTAC service is **one component** in a larger geospatial data pipeline:

```
┌─────────────────────────────────────────────────────────────┐
│ ETL Application (rmhgeoapi)                                 │
│ - Processes raster files                                    │
│ - Extracts geospatial metadata                              │
│ - Creates STAC items                                        │
└──────────────────────┬──────────────────────────────────────┘
                       ↓ (inserts STAC items)
┌─────────────────────────────────────────────────────────────┐
│ PostgreSQL Database with pgSTAC Extension                   │
│ - Stores STAC collections and items                         │
│ - Items reference COG files in Azure Blob Storage           │
└──────────────────────┬──────────────────────────────────────┘
                       ↓ (queries STAC items)
┌─────────────────────────────────────────────────────────────┐
│ TiTiler-pgSTAC (this project)                               │
│ - Serves map tiles                                          │
│ - Reads COG files using OAuth                               │
└──────────────────────┬──────────────────────────────────────┘
                       ↓ (delivers tiles)
┌─────────────────────────────────────────────────────────────┐
│ Web Applications / Map Viewers                              │
│ - Leaflet, Mapbox, OpenLayers, etc.                         │
└─────────────────────────────────────────────────────────────┘
```

### The ETL Application (rmhgeoapi)

**Location**: `/Users/robertharrison/python_builds/rmhgeoapi/`

**Key files**:
- `jobs/stac_catalog_container.py` - ETL job that catalogs COG files
- `services/service_stac_metadata.py` - Extracts metadata from COGs
- `services/stac_catalog.py` - Task handler for STAC operations

**What the ETL does**:

1. **Scans Azure Blob Storage containers** for COG files
2. **Extracts metadata** using rasterio (bounds, CRS, resolution, etc.)
3. **Creates STAC items** with proper geospatial metadata
4. **Inserts items into PostgreSQL** pgSTAC database

**Critical requirement for TiTiler integration**:

The ETL **must** create STAC items with `/vsiaz/` paths in the asset `href`:

```json
{
  "type": "Feature",
  "id": "namangan14aug2019_R2C2cog",
  "collection": "system-rasters",
  "assets": {
    "data": {
      "href": "/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"]
    }
  }
}
```

**Why `/vsiaz/` paths are critical**:
- They trigger GDAL's Azure handler, which uses OAuth tokens
- HTTPS URLs bypass OAuth and cause 403/404 errors
- See [docs/historical/STAC-ETL-FIX.md](docs/historical/STAC-ETL-FIX.md) for details

### How TiTiler Consumes ETL Data

When a user requests a tile:

1. **User requests tile**: `GET /searches/{search_id}/tiles/14/11454/6143.png?assets=data`

2. **TiTiler queries PostgreSQL**:
   ```sql
   SELECT * FROM pgstac.items
   WHERE search_id = '31046149e1e628bfb40f400d77183742'
   AND ST_Intersects(geometry, tile_bounds);
   ```

3. **Extracts asset hrefs** from STAC items:
   ```python
   asset_hrefs = ["/vsiaz/silver-cogs/file1.tif", "/vsiaz/silver-cogs/file2.tif"]
   ```

4. **GDAL opens COG files** using OAuth token:
   ```python
   # Middleware has already set:
   os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = oauth_token

   # GDAL automatically uses token for /vsiaz/ paths:
   with rasterio.open("/vsiaz/silver-cogs/file1.tif") as src:
       data = src.read()
   ```

5. **Renders and returns tile** as PNG

### Data Flow Summary

```
ETL reads COG → Extracts metadata → Creates STAC item with /vsiaz/ href
    ↓
PostgreSQL stores STAC item
    ↓
TiTiler queries for items → Gets /vsiaz/ hrefs
    ↓
TiTiler's OAuth middleware → Sets token in environment
    ↓
GDAL reads COG using token → Returns data
    ↓
TiTiler renders tile → Returns PNG
```

---

## Key Architecture Concepts

### 1. OAuth vs. SAS Tokens

**OAuth Bearer Tokens (Our Approach)**:
- Identity-based authentication (who you are)
- Single token accesses ALL containers via RBAC
- Automatic rotation (~1 hour lifetime)
- No secrets in code or configuration

**SAS Tokens (Alternative)**:
- Capability-based authentication (what you have)
- Per-container or per-blob tokens needed
- Manual expiration management
- Requires storage account keys to generate

**Why we chose OAuth**: Simpler, more secure, and scalable for multi-container access.

### 2. GDAL Virtual File Systems

GDAL supports various cloud storage protocols through "virtual file systems":

| Path Format | Cloud Provider | Authentication |
|-------------|----------------|----------------|
| `/vsiaz/container/blob` | Azure Blob Storage | OAuth, SAS, or account key |
| `/vsis3/bucket/key` | AWS S3 | AWS credentials |
| `/vsigs/bucket/object` | Google Cloud Storage | GCS credentials |
| `/vsicurl/https://...` | Generic HTTPS | Custom headers |

**Our usage**:
```python
# ✅ Correct - triggers OAuth authentication
"/vsiaz/silver-cogs/file.tif"

# ❌ Wrong - bypasses OAuth, causes 403 errors
"https://rmhazuregeo.blob.core.windows.net/silver-cogs/file.tif"
```

### 3. Managed Identity

Azure Managed Identity is a service principal automatically managed by Azure:

**System-Assigned Managed Identity**:
- Created when you enable it on an Azure resource (App Service, VM, etc.)
- Lifecycle tied to the resource (deleted when resource is deleted)
- Used for **storage access** in our implementation

**User-Assigned Managed Identity**:
- Independent Azure resource with its own lifecycle
- Can be shared across multiple resources
- Used for **PostgreSQL access** in our implementation (optional)

**Benefits**:
- No passwords or keys to manage
- Automatic credential rotation
- Azure AD audit trails
- RBAC-based authorization

### 4. Local Development vs. Production

| Aspect | Local Development | Azure Production |
|--------|------------------|------------------|
| **OAuth credential** | Azure CLI (`az login`) | Managed Identity |
| **How provided** | Copied into Docker image | Platform-provided (IMDS) |
| **Configuration** | `LOCAL_MODE=true` | `LOCAL_MODE=false` |
| **Token refresh** | Manual re-login | Automatic |

**Local development flow**:
```bash
az login  # Authenticate with your Azure account
docker-compose build  # Copies ~/.azure into image
docker-compose up  # App uses AzureCliCredential
```

**Production flow**:
```bash
# No credentials needed!
# App uses ManagedIdentityCredential automatically
```

### 5. Three Access Patterns

Our implementation supports three ways to access tiles:

#### Pattern 1: Direct COG Access (Primary Use Case)

**When to use**: You know the exact COG file path

```bash
# Get COG metadata
GET /cog/info?url=/vsiaz/silver-cogs/file.tif

# Get a specific tile
GET /cog/tiles/WebMercatorQuad/14/11454/6143.png?url=/vsiaz/silver-cogs/file.tif

# Interactive map viewer
GET /cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/file.tif
```

**Pros**: Simple, no database query overhead
**Cons**: Must know exact file path

#### Pattern 2: pgSTAC Search (Recommended for Dynamic Queries)

**When to use**: Query items by collection, time, location, or properties

```bash
# Register a search query
POST /searches/register
{
  "collections": ["system-rasters"],
  "bbox": [69.0, 40.0, 70.0, 41.0],
  "datetime": "2019-08-14T00:00:00Z/.."
}

# Returns search_id: "31046149e1e628bfb40f400d77183742"

# Get tiles from search results
GET /searches/31046149e1e628bfb40f400d77183742/tiles/WebMercatorQuad/14/11454/6143.png?assets=data
```

**Pros**: Dynamic queries, supports complex filters
**Cons**: Requires database with STAC items

#### Pattern 3: MosaicJSON (Advanced)

**When to use**: Pre-generated static mosaics

```bash
POST /mosaicjson/
{
  "minzoom": 0,
  "maxzoom": 18,
  "tiles": {...}
}
```

**Pros**: Static, cacheable
**Cons**: Not recommended per our architecture (see docs)

---

## Local Development Setup

### Prerequisites

1. **Docker Desktop** installed and running
2. **Azure CLI** installed: `brew install azure-cli` (macOS) or [download](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
3. **Azure account** with access to:
   - Azure Blob Storage (with COG files)
   - Azure PostgreSQL with pgSTAC extension

### Step-by-Step Setup

#### 1. Clone the Repository

```bash
cd ~/python_builds
git clone <repository-url> titilerpgstac
cd titilerpgstac
```

#### 2. Authenticate with Azure

```bash
az login
az account show  # Verify correct subscription
```

This creates credentials in `~/.azure/` which will be used for local development.

#### 3. Configure Environment

Review [docker-compose.yml](docker-compose.yml):

```yaml
environment:
  LOCAL_MODE: "true"  # Use Azure CLI credentials
  USE_AZURE_AUTH: "true"  # Enable OAuth
  AZURE_STORAGE_ACCOUNT: "rmhazuregeo"
  DATABASE_URL: "postgresql://user:password@host:5432/database"
```

**Important**: The `DATABASE_URL` contains a password. Never commit this file if you modify it!

#### 4. Build and Run

```bash
# Build the Docker image (copies Azure credentials)
docker-compose build

# Start the application
docker-compose up

# Application will be available at http://localhost:8000
```

#### 5. Verify Setup

```bash
# Health check
curl http://localhost:8000/healthz | jq

# Expected response:
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "local_mode": true,
  "token_status": "active",
  "database_status": "connected"
}

# Test COG access
curl "http://localhost:8000/cog/info?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif" | jq

# Open interactive viewer
open "http://localhost:8000/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif"
```

### Project Structure

```
titilerpgstac/
├── custom_pgstac_main.py      # ⭐ Main application (our custom implementation)
├── Dockerfile                  # Production image (Managed Identity)
├── Dockerfile.local            # Local dev image (Azure CLI)
├── docker-compose.yml          # Local development setup
├── QA_DEPLOYMENT.md            # Complete QA/Production deployment guide
├── README.md                   # Quick start and feature overview
├── ONBOARDING.md              # This file
├── docs/
│   ├── implementation/         # Implementation guides
│   │   ├── OAUTH-ARCHITECTURE.md       # How OAuth works
│   │   ├── POSTGRES-MI-SETUP.md        # PostgreSQL MI setup
│   │   └── IMPLEMENTATION-COMPLETE.md  # Implementation summary
│   ├── analysis/              # Technical analysis
│   │   └── CUSTOM_VS_DEFAULT_COMPARISON.md  # Our mods vs base TiTiler
│   └── historical/            # Historical planning docs
│       └── STAC-ETL-FIX.md           # Critical ETL integration fix
└── scripts/
    ├── load_sample_data.py    # Load test STAC items
    └── test_oauth.py          # Test OAuth token acquisition
```

### Key Files to Know

1. **[custom_pgstac_main.py](custom_pgstac_main.py)** - The heart of the application
   - OAuth token management
   - Middleware implementation
   - All API endpoints
   - Database connection logic

2. **[QA_DEPLOYMENT.md](QA_DEPLOYMENT.md)** - Complete deployment guide
   - Environment variables reference
   - RBAC setup instructions
   - PostgreSQL Managed Identity configuration
   - Troubleshooting steps

3. **[docs/historical/STAC-ETL-FIX.md](docs/historical/STAC-ETL-FIX.md)** - Critical for ETL integration
   - Why `/vsiaz/` paths are required
   - How to fix ETL to generate correct hrefs
   - SQL scripts to update existing items

4. **[docs/analysis/CUSTOM_VS_DEFAULT_COMPARISON.md](docs/analysis/CUSTOM_VS_DEFAULT_COMPARISON.md)**
   - Detailed comparison with base TiTiler-pgSTAC
   - What we added and why

---

## Common Development Tasks

### Task 1: Test OAuth Token Acquisition

```bash
# Run the test script
docker-compose exec titiler-pgstac python /app/scripts/test_oauth.py

# Expected output:
# ✅ OAuth token acquired successfully
# Token expires at: 2025-11-18T14:23:45.123456+00:00
```

### Task 2: Load Sample STAC Data

```bash
# Load sample items into database
docker-compose exec titiler-pgstac python /app/scripts/load_sample_data.py

# Verify items were inserted
docker-compose exec titiler-pgstac psql $DATABASE_URL -c \
  "SELECT id, collection FROM pgstac.items LIMIT 5;"
```

### Task 3: Register and Query a Search

```bash
# Register a search
SEARCH_ID=$(curl -s -X POST "http://localhost:8000/searches/register" \
  -H "Content-Type: application/json" \
  -d '{"collections":["system-rasters"],"limit":10}' | jq -r '.id')

echo "Search ID: $SEARCH_ID"

# Get tile from search
curl "http://localhost:8000/searches/$SEARCH_ID/tiles/WebMercatorQuad/14/11454/6143.png?assets=data" \
  -o test_tile.png

# Open the tile
open test_tile.png
```

### Task 4: View Logs

```bash
# Stream logs
docker-compose logs -f titiler-pgstac

# Look for these key messages:
# ✅ OAuth token successfully generated and cached
# ✓ Database connection established
# ✅ TiTiler-pgSTAC startup complete
```

### Task 5: Hot Reload Development

The `docker-compose.yml` mounts your local `custom_pgstac_main.py` file:

```bash
# Edit custom_pgstac_main.py in your IDE
vim custom_pgstac_main.py

# Uvicorn will automatically reload (no need to restart Docker)
# Watch logs for: "Application startup complete"
```

### Task 6: Test Direct COG Access

```bash
# Get COG info
curl "http://localhost:8000/cog/info?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif" | jq

# Expected fields:
# - bounds
# - minzoom / maxzoom
# - band_metadata
# - overviews

# Get a specific tile
curl "http://localhost:8000/cog/tiles/WebMercatorQuad/14/11454/6143.png?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif" \
  -o tile.png
```

### Task 7: Explore the API

```bash
# Open interactive API documentation
open http://localhost:8000/docs

# Or visit
# http://localhost:8000/redoc  (alternative documentation UI)
```

---

## Troubleshooting

### Issue: "No credentials found" or "AzureCliCredential authentication unavailable"

**Cause**: Haven't run `az login` or credentials expired

**Solution**:
```bash
az login
az account show  # Verify login

# Rebuild Docker image to copy fresh credentials
docker-compose build --no-cache
docker-compose up
```

---

### Issue: "HTTP 403 Forbidden" when accessing COG files

**Cause 1**: STAC items have HTTPS URLs instead of `/vsiaz/` paths

**Check**:
```bash
# Connect to database
docker-compose exec titiler-pgstac psql $DATABASE_URL

# Check asset hrefs
SELECT id, content->'assets'->'data'->>'href'
FROM pgstac.items
LIMIT 5;

# Should see: /vsiaz/container/blob.tif
# NOT: https://account.blob.core.windows.net/...
```

**Solution**: See [docs/historical/STAC-ETL-FIX.md](docs/historical/STAC-ETL-FIX.md)

**Cause 2**: OAuth token not being acquired

**Check logs**:
```bash
docker-compose logs titiler-pgstac | grep "OAuth"

# Look for:
# ✅ OAuth token successfully generated and cached
# OR
# ❌ FAILED TO GET OAUTH TOKEN
```

**Cause 3**: Azure RBAC not configured

**Check**:
```bash
# Your user should have Storage Blob Data Reader role
az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) | grep "Storage Blob Data Reader"
```

---

### Issue: "Database connection failed"

**Cause**: Wrong DATABASE_URL or database not accessible

**Check**:
```bash
# Test database connection directly
docker-compose exec titiler-pgstac psql $DATABASE_URL -c "SELECT version();"

# Should return PostgreSQL version
```

**Common fixes**:
1. Verify `DATABASE_URL` in `docker-compose.yml` is correct
2. Check PostgreSQL firewall allows your IP
3. Verify database credentials are valid

---

### Issue: "Read-only file system" when building Docker image

**Cause**: macOS Docker volume mount issue (older versions)

**Solution**: Use `Dockerfile.local` which copies credentials at build time (already configured)

---

### Issue: Token expires during development

**Symptom**: Works initially, then 403 errors after ~1 hour

**Cause**: Azure CLI tokens expire

**Solution**:
```bash
# Re-authenticate
az login

# Rebuild and restart
docker-compose build --no-cache
docker-compose up
```

---

### Issue: "Module not found" or import errors

**Cause**: Base image doesn't have required dependencies

**Check**: `Dockerfile.local` installs `azure-identity`:
```dockerfile
RUN pip install --no-cache-dir azure-identity>=1.15.0
```

**Solution**: Rebuild image:
```bash
docker-compose build --no-cache
```

---

### Issue: "Not recognized as being in a supported file format" (Transient)

**Symptom**: GDAL error when opening COG files:
```
GDAL signalled an error: err_no=4, msg="`/vsiaz/silver-cogs/file.tif'
not recognized as being in a supported file format."
```

**Critical Finding** (Nov 19, 2025): This error can be **transient** and often resolves after restarting the application.

**Root Causes**:
1. **RBAC propagation delay** - Role assignments can take 5-10 minutes to propagate in Azure
2. **OAuth token cache stale** - Cached tokens may need refresh
3. **Rasterio GDAL environment reset** - GDAL config gets cleared when Rasterio creates new environment contexts

**Symptoms that indicate this issue**:
- File worked before but now fails
- Same file works locally but fails in Azure
- Error occurs immediately without HTTP 403/401
- Logs show: `✓ Set OAuth token via GDAL config` but file still fails

**Solutions** (in order of effectiveness):

1. **⭐ Restart the web app** (fixes 90% of cases):
   ```bash
   # Production:
   az webapp restart --name geotiler --resource-group rmhazure_rg

   # Local development:
   docker-compose restart
   ```

   **Why this works**:
   - Forces new OAuth token acquisition from Azure MSI endpoint
   - Reloads RBAC permissions cache
   - Resets GDAL environment with fresh configuration
   - Clears any stale connection pools

2. **Wait for RBAC propagation** (if just uploaded files):
   ```bash
   # Check when role assignment was created
   az role assignment list \
     --assignee <principal-id> \
     --scope <storage-account-id> \
     --query "[].{role:roleDefinitionName, created:createdOn}"

   # If created in last 10 minutes, wait and retry
   sleep 300  # Wait 5 minutes
   az webapp restart --name geotiler --resource-group rmhazure_rg
   ```

3. **Verify file actually exists**:
   ```bash
   az storage blob show \
     --account-name rmhazuregeo \
     --container-name silver-cogs \
     --name "your-file.tif" \
     --auth-mode login
   ```

4. **Check OAuth token acquisition in logs**:
   ```bash
   # Production logs
   az webapp log tail --name geotiler --resource-group rmhazure_rg | grep "OAuth"

   # Look for:
   # ✅ "✓ Set OAuth token via GDAL config for storage account: rmhazuregeo"
   # ✅ "✓ Token length: 1958 chars"
   # ❌ "⚠ No OAuth token available"
   ```

**Important Notes**:
- This is **NOT** a GDAL version issue
- This is **NOT** a file format issue (magic bytes are correct)
- This is **NOT** a middleware implementation bug
- Files work perfectly once transient issue resolves

**Case Study** (Nov 19, 2025):
- Files `dctest_cog_analysis.tif` and `namangan14aug2019_R2C2cog_cog_analysis.tif` failed with GDAL error #4
- Same files were valid COGs (correct magic bytes, proper tiling, 4 overviews)
- Same files worked locally via `/vsiaz/` with GDAL 3.9.1
- After `az webapp restart`, all files worked perfectly
- Issue was transient RBAC/OAuth propagation delay

---

### Getting Help

1. **Check the logs** - Most issues show clear error messages:
   ```bash
   docker-compose logs -f titiler-pgstac
   ```

2. **Review documentation**:
   - [QA_DEPLOYMENT.md](QA_DEPLOYMENT.md) - Deployment and configuration
   - [docs/implementation/OAUTH-ARCHITECTURE.md](docs/implementation/OAUTH-ARCHITECTURE.md) - How OAuth works
   - [docs/historical/STAC-ETL-FIX.md](docs/historical/STAC-ETL-FIX.md) - ETL integration

3. **Test components individually**:
   ```bash
   # Test OAuth
   python scripts/test_oauth.py

   # Test database
   psql $DATABASE_URL -c "SELECT count(*) FROM pgstac.items;"

   # Test health
   curl http://localhost:8000/healthz | jq
   ```

---

## Additional Resources

### Official Documentation

- **TiTiler**: https://developmentseed.org/titiler/
- **TiTiler-pgSTAC**: https://stac-utils.github.io/titiler-pgstac/
- **pgSTAC**: https://github.com/stac-utils/pgstac
- **STAC Specification**: https://stacspec.org/
- **GDAL /vsiaz/**: https://gdal.org/user/virtual_file_systems.html#vsiaz

### Azure Documentation

- **Managed Identity**: https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/
- **DefaultAzureCredential**: https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential
- **Azure Blob Storage RBAC**: https://learn.microsoft.com/en-us/azure/storage/blobs/assign-azure-role-data-access

### Internal Documentation

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Quick start, features overview, usage examples |
| [QA_DEPLOYMENT.md](QA_DEPLOYMENT.md) | Complete production deployment guide |
| [ONBOARDING.md](ONBOARDING.md) | This document - developer onboarding |
| [docs/implementation/OAUTH-ARCHITECTURE.md](docs/implementation/OAUTH-ARCHITECTURE.md) | OAuth authentication architecture |
| [docs/analysis/CUSTOM_VS_DEFAULT_COMPARISON.md](docs/analysis/CUSTOM_VS_DEFAULT_COMPARISON.md) | Our modifications vs. base TiTiler |
| [docs/historical/STAC-ETL-FIX.md](docs/historical/STAC-ETL-FIX.md) | Critical ETL integration requirements |

---

## Quick Reference

### Environment Variables

| Variable | Local Dev | Production | Purpose |
|----------|-----------|------------|---------|
| `LOCAL_MODE` | `true` | `false` | Use Azure CLI vs. Managed Identity |
| `USE_AZURE_AUTH` | `true` | `true` | Enable OAuth for storage |
| `AZURE_STORAGE_ACCOUNT` | `rmhazuregeo` | `rmhazuregeo` | Storage account name |
| `DATABASE_URL` | Set in docker-compose | Set in App Service | PostgreSQL connection string |
| `POSTGRES_AUTH_MODE` | `password` | `managed_identity` | Database auth mode |

### Key Endpoints

| Endpoint | Purpose | Example |
|----------|---------|---------|
| `/healthz` | Health check | `GET /healthz` |
| `/cog/info` | COG metadata | `GET /cog/info?url=/vsiaz/container/file.tif` |
| `/cog/tiles/{z}/{x}/{y}.png` | Direct tile | `GET /cog/tiles/WebMercatorQuad/14/11454/6143.png?url=...` |
| `/searches/register` | Register search | `POST /searches/register` with JSON body |
| `/searches/{id}/tiles/{z}/{x}/{y}` | Search tiles | `GET /searches/{id}/tiles/WebMercatorQuad/14/11454/6143.png?assets=data` |
| `/docs` | API documentation | `GET /docs` |

### Common Commands

```bash
# Start development environment
docker-compose up

# Rebuild after changes
docker-compose build --no-cache

# View logs
docker-compose logs -f titiler-pgstac

# Test health
curl http://localhost:8000/healthz | jq

# Re-authenticate with Azure
az login

# Connect to database
docker-compose exec titiler-pgstac psql $DATABASE_URL
```

---

## Summary

You now understand:

1. **What this project does**: Serves geospatial tiles from COG files using OAuth authentication
2. **How we modified TiTiler-pgSTAC**: Added Azure OAuth, flexible database auth, additional endpoints, and production logging
3. **How it integrates with ETL**: Consumes STAC items from PostgreSQL, reads COGs using OAuth
4. **Key architecture concepts**: OAuth vs. SAS, GDAL virtual file systems, Managed Identity, access patterns
5. **How to develop locally**: Docker setup with Azure CLI credentials

**Next steps**:
- Set up your local development environment
- Explore the codebase starting with [custom_pgstac_main.py](custom_pgstac_main.py)
- Review [QA_DEPLOYMENT.md](QA_DEPLOYMENT.md) for production deployment
- Check [docs/historical/STAC-ETL-FIX.md](docs/historical/STAC-ETL-FIX.md) if working on ETL integration

**Welcome to the team!** Feel free to ask questions and consult the documentation as you get started.

---

**Document Version**: 1.0
**Last Updated**: November 18, 2025
**Maintainer**: Development Team
