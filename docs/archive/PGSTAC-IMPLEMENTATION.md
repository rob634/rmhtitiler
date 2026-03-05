# TiTiler-pgSTAC with Azure Managed Identity Implementation Guide

**Document Version**: 1.0
**Last Updated**: November 7, 2025
**Status**: Research & Planning

---

## Overview

This document outlines the strategy for implementing Azure Managed Identity authentication for **TiTiler-pgSTAC**, comparing it to our existing TiTiler implementation and identifying key differences, similarities, and challenges.

## What is TiTiler-pgSTAC?

**TiTiler-pgSTAC** is a TiTiler extension that connects to a **pgSTAC** (PostgreSQL STAC) database to create dynamic mosaics based on STAC search queries.

### Key Components

1. **pgSTAC Database**: PostgreSQL database with STAC schema and functions
2. **TiTiler-pgSTAC**: FastAPI application serving tiles from STAC items
3. **STAC Items**: Metadata pointing to COGs in Azure Blob Storage
4. **COG Files**: Actual raster data stored in Azure Blob Storage

### Architecture Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    TiTiler-pgSTAC Application                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  1. Client requests tile for STAC search                   │ │
│  │  2. Query pgSTAC database for matching STAC items          │ │
│  │  3. Extract asset URLs from STAC items                     │ │
│  │  4. Generate SAS tokens for Azure Blob Storage             │ │
│  │  5. Read COGs from /vsiaz/ using SAS tokens                │ │
│  │  6. Create mosaic and return tile                          │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                         │                    │
                         ▼                    ▼
              ┌──────────────────┐  ┌──────────────────┐
              │  pgSTAC Database │  │  Azure Blob      │
              │  (PostgreSQL)    │  │  Storage (COGs)  │
              └──────────────────┘  └──────────────────┘
```

---

## Comparison: TiTiler vs TiTiler-pgSTAC

### Similarities

| Aspect | Both Implementations |
|--------|---------------------|
| **Base Technology** | FastAPI, rio-tiler, GDAL |
| **Authentication Method** | Azure Managed Identity + User Delegation SAS |
| **Storage Access** | GDAL `/vsiaz/` virtual file system |
| **Token Management** | Cache tokens, refresh before expiry |
| **Environment Variables** | `AZURE_STORAGE_ACCOUNT`, `AZURE_SAS_TOKEN` |
| **Deployment** | Azure App Service with Docker containers |
| **RBAC Role** | Storage Blob Data Reader |

### Key Differences

| Aspect | TiTiler (Current) | TiTiler-pgSTAC (Proposed) |
|--------|-------------------|---------------------------|
| **URL Input** | Direct COG URL via query parameter | STAC item/search query → extract URLs |
| **Database** | None | PostgreSQL with pgSTAC extension |
| **Data Flow** | URL → GDAL → Tile | Search → pgSTAC → URLs → GDAL → Mosaic Tile |
| **Complexity** | Single COG per request | Multiple COGs per mosaic request |
| **Authentication Scope** | Single container (hardcoded) | **Multiple containers** (from STAC metadata) |
| **Base Image** | `ghcr.io/developmentseed/titiler:latest` | `ghcr.io/stac-utils/titiler-pgstac:latest` |
| **Dependencies** | `azure-identity`, `azure-storage-blob` | + `psycopg2`, `asyncpg`, `titiler-pgstac` |
| **Configuration** | URL passed directly | Database connection string required |

---

## Critical Challenge: Multiple Container Support

### The Problem

**Current Implementation (TiTiler)**:
- Hardcoded to single container: `AZURE_CONTAINER=silver-cogs`
- Generates one SAS token scoped to that container
- Simple and straightforward

**TiTiler-pgSTAC Requirement**:
- STAC items may reference COGs across **multiple containers**
- Example STAC asset URLs:
  ```json
  {
    "assets": {
      "image": {
        "href": "https://rmhgeopipelines.blob.core.windows.net/silver-cogs/file1.tif"
      },
      "thumbnail": {
        "href": "https://rmhgeopipelines.blob.core.windows.net/bronze-cogs/thumb.png"
      }
    }
  }
  ```

### Solution Approaches

#### Option 1: Dynamic Container Detection and Token Generation

**Strategy**: Parse container name from asset URL and generate container-specific SAS tokens on-demand.

**Implementation**:
```python
from urllib.parse import urlparse
from typing import Dict

# Cache: {container_name: {token: str, expires_at: datetime}}
container_sas_cache: Dict[str, dict] = {}

def extract_container_from_url(url: str) -> tuple[str, str]:
    """Extract storage account and container from Azure blob URL.

    Example:
        https://account.blob.core.windows.net/container/path/file.tif
        Returns: ("account", "container")
    """
    parsed = urlparse(url)
    # Format: account.blob.core.windows.net
    storage_account = parsed.netloc.split('.')[0]
    # Format: /container/path/file.tif
    container = parsed.path.split('/')[1]
    return storage_account, container

def generate_container_sas(container_name: str) -> Optional[str]:
    """Generate User Delegation SAS token for specific container.

    Similar to current implementation but accepts container parameter.
    """
    # Check cache
    if container_name in container_sas_cache:
        cached = container_sas_cache[container_name]
        time_until_expiry = (cached['expires_at'] - datetime.now(timezone.utc)).total_seconds()
        if time_until_expiry > 300:
            logger.debug(f"Using cached SAS for container '{container_name}'")
            return cached['token']

    # Generate new token (same logic as current implementation)
    logger.info(f"Generating new SAS token for container: {container_name}")

    credential = DefaultAzureCredential()
    blob_service_client = BlobServiceClient(
        account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=credential
    )

    # Get user delegation key (can be reused across containers)
    delegation_key = blob_service_client.get_user_delegation_key(
        key_start_time=datetime.now(timezone.utc),
        key_expiry_time=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    # Generate container-scoped SAS
    sas_token = generate_container_sas(
        container_name=container_name,
        account_name=AZURE_STORAGE_ACCOUNT,
        user_delegation_key=delegation_key,
        permission=ContainerSasPermissions(read=True, list=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    # Cache token
    container_sas_cache[container_name] = {
        'token': sas_token,
        'expires_at': datetime.now(timezone.utc) + timedelta(hours=1)
    }

    return sas_token

@app.middleware("http")
async def azure_auth_middleware(request: Request, call_next):
    """Middleware to set AZURE_SAS_TOKEN before each request.

    Challenge: GDAL expects single token in environment variable,
    but we may need tokens for multiple containers in one request.
    """
    # This is where it gets complex...
    # How do we set the token when we don't know which containers
    # will be accessed until we read the STAC items?

    response = await call_next(request)
    return response
```

**Challenges with Option 1**:
1. **Timing**: We don't know which containers until AFTER we query pgSTAC
2. **GDAL Limitation**: `AZURE_SAS_TOKEN` environment variable is global, not per-container
3. **Middleware Problem**: Middleware runs BEFORE request processing, but we need STAC data FIRST

#### Option 2: Pre-generate Tokens for All Known Containers

**Strategy**: Generate SAS tokens for all containers at startup/refresh time.

**Implementation**:
```python
from typing import List

# Configuration: List all containers that might be referenced
AZURE_CONTAINERS = ["silver-cogs", "bronze-cogs", "gold-cogs"]

# Cache: {container_name: {token: str, expires_at: datetime}}
container_sas_cache: Dict[str, dict] = {}

def generate_all_container_sas_tokens():
    """Generate SAS tokens for all configured containers."""
    logger.info(f"Generating SAS tokens for {len(AZURE_CONTAINERS)} containers")

    credential = DefaultAzureCredential()
    blob_service_client = BlobServiceClient(
        account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=credential
    )

    # Get user delegation key once (valid for all containers)
    delegation_key = blob_service_client.get_user_delegation_key(
        key_start_time=datetime.now(timezone.utc),
        key_expiry_time=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    for container_name in AZURE_CONTAINERS:
        sas_token = generate_container_sas(
            container_name=container_name,
            account_name=AZURE_STORAGE_ACCOUNT,
            user_delegation_key=delegation_key,
            permission=ContainerSasPermissions(read=True, list=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1)
        )

        container_sas_cache[container_name] = {
            'token': sas_token,
            'expires_at': datetime.now(timezone.utc) + timedelta(hours=1)
        }

        logger.info(f"✓ Generated SAS token for container: {container_name}")

@app.on_event("startup")
async def startup_event():
    """Generate tokens for all containers at startup."""
    generate_all_container_sas_tokens()
```

**Challenges with Option 2**:
1. **GDAL Limitation**: Still only supports ONE token in `AZURE_SAS_TOKEN` environment variable
2. **Configuration Management**: Must maintain list of all possible containers
3. **Token Usage**: Can't set multiple tokens simultaneously

#### Option 3: Account-Level SAS Token with User Delegation Key (RECOMMENDED)

**Research Question**: Can we generate a User Delegation SAS token scoped to the **entire storage account** rather than individual containers?

**Hypothesis**:
- Azure supports account-level SAS with storage account keys
- User Delegation SAS *might* support account-level scope with managed identity
- This would solve the multi-container problem elegantly

**Implementation (if supported)**:
```python
def generate_account_level_user_delegation_sas() -> Optional[str]:
    """Generate User Delegation SAS token scoped to entire storage account.

    This would allow access to ALL containers the managed identity has permissions for.
    """
    credential = DefaultAzureCredential()
    blob_service_client = BlobServiceClient(
        account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=credential
    )

    delegation_key = blob_service_client.get_user_delegation_key(
        key_start_time=datetime.now(timezone.utc),
        key_expiry_time=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    # Question: Is this possible?
    # generate_account_sas() exists, but does it work with user_delegation_key?
    sas_token = generate_account_sas(
        account_name=AZURE_STORAGE_ACCOUNT,
        user_delegation_key=delegation_key,  # Does this parameter exist?
        resource_types=ResourceTypes(container=True, object=True),
        permission=AccountSasPermissions(read=True, list=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    return sas_token
```

**Advantages**:
- Single token for all containers
- No container name parsing needed
- Works with existing middleware pattern
- Scales to unlimited containers

**Need to Research**:
- ✅ Does `generate_account_sas()` accept `user_delegation_key` parameter?
- ✅ Is account-level User Delegation SAS supported by Azure?
- ✅ What are the security implications?
- ✅ Does GDAL `/vsiaz/` work with account-level SAS?

#### Option 4: Custom URL Rewriter with Container-Specific Tokens

**Strategy**: Intercept asset URLs before passing to GDAL and append container-specific SAS tokens as query parameters.

**Implementation**:
```python
def rewrite_url_with_sas(url: str) -> str:
    """Append container-specific SAS token to blob URL.

    Transforms:
        /vsiaz/container/path/file.tif
    To:
        /vsiaz/container/path/file.tif?<sas_token>
    """
    storage_account, container_name = extract_container_from_url(url)
    sas_token = get_or_generate_container_sas(container_name)

    # Append SAS as query parameter
    separator = '&' if '?' in url else '?'
    return f"{url}{separator}{sas_token}"

# Custom reader that rewrites URLs
class AzureSASReader(rio_tiler.io.Reader):
    """Custom reader that appends SAS tokens to Azure URLs."""

    def __init__(self, input: str, *args, **kwargs):
        # Rewrite URL to include SAS token
        modified_input = rewrite_url_with_sas(input)
        super().__init__(modified_input, *args, **kwargs)
```

**Challenges with Option 4**:
1. **Complexity**: Requires custom reader implementation
2. **TiTiler-pgSTAC Integration**: Must inject custom reader into mosaic backend
3. **URL Format**: Need to ensure `/vsiaz/` paths are rewritten correctly

---

## Recommended Implementation Path

### Phase 1: Research and Validation (1-2 days)

**Objective**: Determine if account-level User Delegation SAS is possible

**Tasks**:
1. Review Azure SDK documentation for `generate_account_sas()` with user delegation key
2. Test account-level SAS generation with managed identity in local environment
3. Verify GDAL `/vsiaz/` compatibility with account-level SAS
4. Document security implications and RBAC requirements

**Validation Script**:
```python
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, generate_account_sas
from datetime import datetime, timedelta, timezone

def test_account_level_user_delegation_sas():
    """Test if account-level User Delegation SAS is supported."""

    credential = DefaultAzureCredential()
    blob_service_client = BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=credential
    )

    # Get user delegation key
    delegation_key = blob_service_client.get_user_delegation_key(
        key_start_time=datetime.now(timezone.utc),
        key_expiry_time=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    # Attempt to generate account-level SAS
    try:
        sas_token = generate_account_sas(
            account_name=STORAGE_ACCOUNT,
            user_delegation_key=delegation_key,
            resource_types=ResourceTypes(container=True, object=True),
            permission=AccountSasPermissions(read=True, list=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        print(f"✓ Account-level SAS generated: {sas_token[:50]}...")
        return sas_token
    except Exception as e:
        print(f"✗ Failed to generate account-level SAS: {e}")
        return None

if __name__ == "__main__":
    token = test_account_level_user_delegation_sas()

    # Test with GDAL
    if token:
        import os
        os.environ['AZURE_STORAGE_ACCOUNT'] = STORAGE_ACCOUNT
        os.environ['AZURE_SAS_TOKEN'] = token

        # Try accessing multiple containers
        for container in ['silver-cogs', 'bronze-cogs']:
            test_url = f"/vsiaz/{container}/test.tif"
            # Test GDAL access...
```

### Phase 2: Architecture Design (Based on Phase 1 Results)

**If Account-Level SAS Works** → Simple implementation, reuse most of current code

**If Account-Level SAS Doesn't Work** → Implement Option 2 (pre-generate) or Option 4 (custom reader)

### Phase 3: Implementation Components

#### 3.1 Database Connection

```python
import asyncpg
from typing import Optional

# Environment variables
PGSTAC_DATABASE_URL = os.getenv("DATABASE_URL")

# Connection pool
db_pool: Optional[asyncpg.Pool] = None

@app.on_event("startup")
async def startup_event():
    """Initialize database connection pool."""
    global db_pool

    logger.info("Connecting to pgSTAC database...")
    db_pool = await asyncpg.create_pool(
        PGSTAC_DATABASE_URL,
        min_size=2,
        max_size=10
    )
    logger.info("✓ Database connection pool created")

    # Generate SAS tokens
    generate_all_container_sas_tokens()

@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection pool."""
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("✓ Database connection pool closed")
```

#### 3.2 TiTiler-pgSTAC Factory Setup

```python
from titiler.pgstac.factory import MosaicTilerFactory
from titiler.pgstac.dependencies import PgSTACParams

# Create mosaic tiler factory
mosaic = MosaicTilerFactory(
    router_prefix="/mosaic",
    add_viewer=True
)

# Add to app
app.include_router(mosaic.router, prefix="/mosaic", tags=["Mosaic"])
```

#### 3.3 Custom Middleware for Token Management

```python
@app.middleware("http")
async def azure_auth_middleware(request: Request, call_next):
    """Middleware to ensure valid SAS token is set."""

    if USE_AZURE_AUTH and not LOCAL_MODE:
        # Option A: Account-level SAS
        token = generate_account_level_sas()

        # Option B: Pre-generated container tokens
        # We'd need to determine container from request and set appropriate token
        # This is complex and may require custom reader

        if token:
            os.environ["AZURE_SAS_TOKEN"] = token

    response = await call_next(request)
    return response
```

#### 3.4 STAC Item URL Handling

```python
from titiler.pgstac.reader import PgSTACReader

# If using custom reader approach
class AzurePgSTACReader(PgSTACReader):
    """Custom reader that handles Azure SAS tokens for multiple containers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _read(self, asset_url: str, *args, **kwargs):
        """Override read to inject SAS token based on container."""
        # Extract container from URL
        container = self._extract_container(asset_url)

        # Get container-specific SAS token
        sas_token = get_or_generate_container_sas(container)

        # Set environment variable (or rewrite URL)
        os.environ["AZURE_SAS_TOKEN"] = sas_token

        # Call parent read
        return super()._read(asset_url, *args, **kwargs)
```

---

## Deployment Differences

### Docker Image

**Current (TiTiler)**:
```dockerfile
FROM ghcr.io/developmentseed/titiler:latest
```

**TiTiler-pgSTAC**:
```dockerfile
FROM ghcr.io/stac-utils/titiler-pgstac:latest

# Install Azure libraries
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0 \
    azure-storage-blob>=12.19.0 \
    asyncpg>=0.29.0
```

### Environment Variables

**Additional for pgSTAC**:
```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/pgstac

# Azure (same as current)
AZURE_STORAGE_ACCOUNT=rmhgeopipelines
USE_AZURE_AUTH=true
USE_SAS_TOKEN=true
LOCAL_MODE=false

# Container list (if using Option 2)
AZURE_CONTAINERS=silver-cogs,bronze-cogs,gold-cogs
```

### Azure Resources

**Additional Requirements**:
1. **Azure Database for PostgreSQL Flexible Server**
   - pgSTAC extension installed
   - STAC collections and items ingested
   - Managed Identity authentication (optional, can use password)

2. **RBAC Roles**:
   - Storage Blob Data Reader (same as current)
   - Optionally: PostgreSQL Database Contributor

---

## Security Considerations

### Current Implementation (Single Container)

- Least privilege: SAS token scoped to one container
- Managed Identity has read access to one container
- Clear audit trail

### TiTiler-pgSTAC Options

| Approach | Security Level | Complexity |
|----------|---------------|------------|
| **Account-level SAS** | Lower (broader access) | Low |
| **Pre-generate per container** | Medium (multiple tokens) | Medium |
| **Dynamic per-request** | Highest (just-in-time) | High |
| **Custom URL rewriter** | Highest (per-asset tokens) | Highest |

**Recommendation**:
- **Development/Testing**: Account-level SAS for simplicity
- **Production**: Pre-generate per-container if account-level not supported
- **High Security**: Dynamic per-request with custom reader

---

## Migration Path from Current Implementation

### Code Reusability

**Can be reused with minimal changes** (90%):
- SAS token generation logic
- Token caching mechanism
- Middleware pattern
- Health check endpoint
- Logging and error handling
- GDAL environment variable management

**Needs modification** (10%):
- Container scope handling
- Database connection management
- TiTiler factory setup (different base class)

### Step-by-Step Migration

1. **Copy `custom_main.py` to `custom_pgstac_main.py`**
2. **Add database connection logic**
3. **Modify SAS generation for multiple containers**
4. **Replace TiTiler factory with PgSTAC factory**
5. **Update Dockerfile base image**
6. **Add DATABASE_URL environment variable**
7. **Test with sample STAC data**

---

## Testing Strategy

### Unit Tests

```python
def test_extract_container_from_url():
    url = "https://account.blob.core.windows.net/container/path/file.tif"
    account, container = extract_container_from_url(url)
    assert account == "account"
    assert container == "container"

def test_container_sas_caching():
    token1 = generate_container_sas("silver-cogs")
    token2 = generate_container_sas("silver-cogs")
    assert token1 == token2  # Should use cached token

def test_multi_container_sas_generation():
    containers = ["silver-cogs", "bronze-cogs"]
    tokens = {c: generate_container_sas(c) for c in containers}
    assert len(tokens) == 2
    assert all(tokens.values())
```

### Integration Tests

```python
async def test_pgstac_connection():
    """Test database connection and basic query."""
    pool = await asyncpg.create_pool(DATABASE_URL)
    result = await pool.fetchval("SELECT COUNT(*) FROM pgstac.collections")
    assert result > 0
    await pool.close()

async def test_mosaic_tile_generation():
    """Test generating tile from STAC search."""
    response = await client.get(
        "/mosaic/tiles/WebMercatorQuad/14/3876/6325.png",
        params={"collection": "test-collection"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"

async def test_multi_container_asset_access():
    """Test accessing assets from multiple containers in one mosaic."""
    # STAC search that returns items from multiple containers
    response = await client.post(
        "/mosaic/register",
        json={
            "collections": ["silver-cogs", "bronze-cogs"],
            "bbox": [-180, -90, 180, 90]
        }
    )
    assert response.status_code == 200
```

---

## Performance Considerations

### Token Generation Overhead

**Current (single container)**:
- 1 delegation key request
- 1 SAS token generation
- ~500ms total

**Multi-container (pre-generate)**:
- 1 delegation key request
- N SAS token generations (one per container)
- ~500ms + (N × 50ms)

**For 10 containers**: ~1000ms at startup (acceptable)

### Caching Strategy

```python
# Per-container cache
container_sas_cache = {
    "silver-cogs": {"token": "...", "expires_at": datetime},
    "bronze-cogs": {"token": "...", "expires_at": datetime}
}

# User delegation key cache (can be reused across containers)
delegation_key_cache = {
    "key": UserDelegationKey,
    "expires_at": datetime
}
```

### Database Connection Pooling

```python
# Connection pool sizing
MIN_POOL_SIZE = 2
MAX_POOL_SIZE = 10

# For production with high traffic
MAX_POOL_SIZE = os.getenv("DB_POOL_SIZE", 20)
```

---

## Open Questions and Next Steps

### Critical Research Items

1. **Account-Level User Delegation SAS**
   - [ ] Test if `generate_account_sas()` accepts `user_delegation_key`
   - [ ] Verify GDAL compatibility
   - [ ] Document security implications

2. **GDAL Multi-Token Support**
   - [ ] Research if GDAL can use different tokens per container
   - [ ] Test custom URL schemes with embedded tokens

3. **Performance Testing**
   - [ ] Benchmark token generation for 10+ containers
   - [ ] Test mosaic generation with assets from multiple containers
   - [ ] Measure memory usage with multiple cached tokens

### Development Priorities

1. **Phase 1** (Research): Answer account-level SAS question
2. **Phase 2** (Prototype): Implement chosen approach locally
3. **Phase 3** (Testing): Validate with real STAC data
4. **Phase 4** (Production): Deploy to Azure App Service

---

## References

- [TiTiler-pgSTAC Documentation](https://stac-utils.github.io/titiler-pgstac/)
- [pgSTAC GitHub Repository](https://github.com/stac-utils/pgstac)
- [Azure User Delegation SAS](https://learn.microsoft.com/en-us/rest/api/storageservices/create-user-delegation-sas)
- [GDAL /vsiaz/ Documentation](https://gdal.org/user/virtual_file_systems.html#vsiaz-microsoft-azure-blob-files)
- [Rio-tiler Custom Readers](https://cogeotiff.github.io/rio-tiler/advanced/custom_readers/)

---

## Summary

### Similarities to Current Implementation
- ✅ Same authentication mechanism (Managed Identity + SAS)
- ✅ Same middleware pattern for token injection
- ✅ Same GDAL virtual file system
- ✅ ~90% of current code can be reused

### Key Difference
- ❌ **Multiple container support** is the main challenge
- ❌ Requires new strategy for managing tokens per container
- ❌ May need custom reader or account-level SAS approach

### Recommended Next Step
**Run validation script** to determine if account-level User Delegation SAS is supported. This single test will determine whether implementation is simple (account-level) or complex (per-container tokens).

---

**Document Status**: Ready for Phase 1 Research
**Estimated Implementation Time**:
- Phase 1 (Research): 1-2 days
- Phase 2 (Implementation): 3-5 days
- Phase 3 (Testing): 2-3 days
- **Total**: 6-10 days

