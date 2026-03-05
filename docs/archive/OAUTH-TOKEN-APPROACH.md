# Simplified Azure Authentication: OAuth Tokens Instead of SAS

**Document Version**: 1.0
**Last Updated**: November 7, 2025
**Status**: Recommended Approach

---

## Key Insight

**Current Approach** (SAS Tokens):
- Complex: Generate user delegation key, then generate SAS token
- Limited scope: Must specify container name
- Multi-container problem: Need separate tokens per container

**Better Approach** (OAuth Tokens):
- Simple: Get OAuth token directly from Managed Identity
- Account-level scope: Works for ALL containers the identity has access to
- RBAC-based: Permissions match the Managed Identity's role assignments

---

## Why OAuth Tokens Are Better

### 1. Matches Your Use Case

**Your Goal**: Match the Web App's Managed Identity RBAC role (Storage Blob Data Reader)

**SAS Tokens**: Add an unnecessary layer of permission **restriction**
- SAS = "limit access to specific resources/operations"
- You don't need to limit - you want full RBAC permissions!

**OAuth Tokens**: Direct RBAC permission usage
- Token represents the identity's full permissions
- No additional restrictions needed

### 2. Solves Multi-Container Problem

**SAS Approach**:
```python
# Problem: Need different SAS tokens for different containers
sas_silver = generate_container_sas("silver-cogs")  # Only works for silver-cogs
sas_bronze = generate_container_sas("bronze-cogs")  # Only works for bronze-cogs
# GDAL can only use ONE token at a time!
```

**OAuth Approach**:
```python
# Solution: One token works for ALL containers
oauth_token = get_oauth_token("https://storage.azure.com/")
# Works for silver-cogs, bronze-cogs, gold-cogs, ANY container the identity has access to!
```

### 3. Much Simpler Code

**SAS Approach** (current):
- ~200 lines of code
- User delegation key generation
- Container-specific SAS generation
- Complex caching logic

**OAuth Approach** (proposed):
- ~50 lines of code
- Single token request
- Simple caching logic

---

## Implementation

### Simplified Code

```python
import os
import logging
from datetime import datetime, timedelta, timezone
from azure.identity import DefaultAzureCredential
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT", "rmhgeopipelines")
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "true").lower() == "true"
LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"

# Token cache
oauth_token_cache = {
    "token": None,
    "expires_at": None,
    "lock": Lock()
}

def get_azure_storage_oauth_token() -> Optional[str]:
    """Get OAuth token for Azure Storage using Managed Identity.

    This token grants access to ALL containers based on the Managed Identity's
    RBAC role assignments (e.g., Storage Blob Data Reader).

    Returns:
        str: OAuth bearer token for Azure Storage
        None: If authentication is disabled or fails
    """
    if not USE_AZURE_AUTH:
        logger.debug("Azure OAuth authentication disabled")
        return None

    with oauth_token_cache["lock"]:
        now = datetime.now(timezone.utc)

        # Check cached token
        if oauth_token_cache["token"] and oauth_token_cache["expires_at"]:
            time_until_expiry = (oauth_token_cache["expires_at"] - now).total_seconds()

            if time_until_expiry > 300:  # More than 5 minutes remaining
                logger.debug(f"✓ Using cached OAuth token, expires in {time_until_expiry:.0f}s")
                return oauth_token_cache["token"]
            else:
                logger.info(f"⚠ OAuth token expires in {time_until_expiry:.0f}s, refreshing...")

        # Generate new token
        logger.info("=" * 80)
        logger.info("🔑 Acquiring OAuth token for Azure Storage via Managed Identity")
        logger.info("=" * 80)

        try:
            # Get credential
            logger.debug("Step 1/2: Creating DefaultAzureCredential...")
            credential = DefaultAzureCredential()
            logger.info("✓ DefaultAzureCredential created")

            # Get token for Azure Storage scope
            logger.debug("Step 2/2: Requesting token for scope 'https://storage.azure.com/.default'...")
            token = credential.get_token("https://storage.azure.com/.default")

            # Extract token string and expiry
            access_token = token.token
            expires_on = datetime.fromtimestamp(token.expires_on, tz=timezone.utc)

            logger.info(f"✓ OAuth token acquired, expires at {expires_on.isoformat()}")

            # Cache token
            oauth_token_cache["token"] = access_token
            oauth_token_cache["expires_at"] = expires_on

            logger.info("=" * 80)
            logger.info(f"✅ OAuth token successfully generated")
            logger.info(f"   Storage Account: {AZURE_STORAGE_ACCOUNT}")
            logger.info(f"   Scope: https://storage.azure.com/.default")
            logger.info(f"   Valid until: {expires_on.isoformat()}")
            logger.info(f"   Grants access to: ALL containers per RBAC role")
            logger.info("=" * 80)

            return access_token

        except Exception as e:
            logger.error("=" * 80)
            logger.error("❌ FAILED TO ACQUIRE OAUTH TOKEN")
            logger.error(f"Error Type: {type(e).__name__}")
            logger.error(f"Error Message: {str(e)}")
            logger.error("Troubleshooting:")
            logger.error("  - Verify Managed Identity: az webapp identity show")
            logger.error("  - Verify RBAC Role: az role assignment list --assignee <principal-id>")
            logger.error("  - Ensure role is 'Storage Blob Data Reader' or higher")
            logger.error("=" * 80)
            logger.error("Full traceback:", exc_info=True)
            raise

@app.middleware("http")
async def azure_auth_middleware(request: Request, call_next):
    """Middleware to set OAuth token before each request.

    Sets AZURE_STORAGE_ACCESS_TOKEN which GDAL uses for /vsiaz/ authentication.
    """
    if USE_AZURE_AUTH and not LOCAL_MODE:
        token = get_azure_storage_oauth_token()
        if token:
            os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
            os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token

    response = await call_next(request)
    return response

@app.on_event("startup")
async def startup_event():
    """Pre-generate OAuth token at startup."""
    if USE_AZURE_AUTH and not LOCAL_MODE:
        logger.info("Initializing Azure OAuth authentication...")
        try:
            token = get_azure_storage_oauth_token()
            if token:
                logger.info("✓ Azure OAuth authentication initialized successfully")
                logger.info(f"✓ Storage account: {AZURE_STORAGE_ACCOUNT}")
                logger.info(f"✓ Access scope: ALL containers per RBAC role")
        except Exception as e:
            logger.error(f"✗ Failed to initialize Azure OAuth authentication: {e}")
            raise

@app.get("/healthz")
async def health_check():
    """Health check endpoint with OAuth token status."""
    status = {
        "status": "healthy",
        "azure_auth_enabled": USE_AZURE_AUTH,
        "local_mode": LOCAL_MODE,
        "storage_account": AZURE_STORAGE_ACCOUNT if USE_AZURE_AUTH else None
    }

    if USE_AZURE_AUTH and not LOCAL_MODE:
        if oauth_token_cache["token"] and oauth_token_cache["expires_at"]:
            time_until_expiry = (
                oauth_token_cache["expires_at"] - datetime.now(timezone.utc)
            ).total_seconds()
            status["token_expires_in_seconds"] = int(time_until_expiry)
            status["token_type"] = "OAuth Bearer Token"
            status["token_scope"] = "ALL containers (RBAC-based)"
        else:
            status["token_status"] = "not_initialized"

    return status
```

---

## Comparison: SAS vs OAuth

| Aspect | SAS Tokens (Current) | OAuth Tokens (Proposed) |
|--------|---------------------|------------------------|
| **Code Complexity** | ~200 lines | ~50 lines |
| **API Calls** | 2 (delegation key + SAS) | 1 (token) |
| **Scope** | Container-specific | Account-wide (all containers) |
| **Multi-container** | Complex (need multiple tokens) | Simple (one token) |
| **Permission Model** | Restrictive (limits RBAC) | Direct RBAC |
| **Use Case** | Delegating to untrusted clients | Service-to-service (your case) |
| **GDAL Env Var** | `AZURE_STORAGE_SAS_TOKEN` | `AZURE_STORAGE_ACCESS_TOKEN` |
| **Token Lifetime** | 1 hour (you set it) | 1 hour (Azure sets it) |
| **Security** | Extra restriction layer | Direct identity permissions |

---

## When to Use Each Approach

### Use OAuth Tokens When:
- ✅ Service-to-service authentication (your case)
- ✅ Managed Identity available
- ✅ Want to match RBAC permissions exactly
- ✅ Need access to multiple containers
- ✅ Simplicity is preferred

### Use SAS Tokens When:
- ❌ Delegating access to external/untrusted clients
- ❌ Need to restrict permissions beyond RBAC
- ❌ Need to limit to specific containers/objects
- ❌ Need to provide time-limited access to others
- ❌ No Managed Identity available (must use storage keys)

---

## TiTiler-pgSTAC Implications

### Problem Solved!

**Original Problem**: STAC items reference COGs in multiple containers

**SAS Approach**: Complex multi-token management
```python
# Would need:
sas_tokens = {
    "silver-cogs": generate_container_sas("silver-cogs"),
    "bronze-cogs": generate_container_sas("bronze-cogs"),
    "gold-cogs": generate_container_sas("gold-cogs")
}
# Then somehow switch tokens based on which container is accessed...
```

**OAuth Approach**: Just works!
```python
# One token for everything:
oauth_token = get_oauth_token("https://storage.azure.com/.default")
os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = oauth_token

# Now GDAL can access ANY container the identity has access to:
# /vsiaz/silver-cogs/file.tif  ✓
# /vsiaz/bronze-cogs/file.tif  ✓
# /vsiaz/gold-cogs/file.tif    ✓
# /vsiaz/any-other-container/file.tif  ✓
```

---

## Migration from Current Implementation

### What Changes

**Remove**:
```python
from azure.storage.blob import BlobServiceClient, generate_container_sas, ContainerSasPermissions

def generate_user_delegation_sas():
    # All this code can be deleted!
    # ~150 lines removed
```

**Replace with**:
```python
from azure.identity import DefaultAzureCredential

def get_azure_storage_oauth_token():
    credential = DefaultAzureCredential()
    token = credential.get_token("https://storage.azure.com/.default")
    return token.token
```

**Environment Variable Change**:
```python
# Old
os.environ["AZURE_STORAGE_SAS_TOKEN"] = sas_token

# New
os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = oauth_token
```

### What Stays the Same

- ✅ Middleware pattern
- ✅ Token caching logic
- ✅ Automatic refresh before expiry
- ✅ Health check endpoint
- ✅ Startup initialization
- ✅ RBAC role requirements (Storage Blob Data Reader)
- ✅ Managed Identity setup

---

## Testing OAuth Approach

### Local Testing Script

```python
#!/usr/bin/env python3
"""Test OAuth token approach with GDAL."""

import os
from azure.identity import DefaultAzureCredential
from osgeo import gdal

def test_oauth_authentication():
    """Test OAuth token with GDAL /vsiaz/."""

    # Get OAuth token
    print("Acquiring OAuth token...")
    credential = DefaultAzureCredential()
    token = credential.get_token("https://storage.azure.com/.default")

    print(f"✓ Token acquired (expires in {token.expires_on - token.expires_on} seconds)")

    # Set GDAL environment variables
    os.environ["AZURE_STORAGE_ACCOUNT"] = "rmhgeopipelines"
    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token.token

    # Test multiple containers
    containers = ["silver-cogs", "bronze-cogs", "gold-cogs"]

    for container in containers:
        print(f"\nTesting container: {container}")

        # List files (assuming you have test files)
        vsiaz_path = f"/vsiaz/{container}/"

        try:
            file_list = gdal.ReadDir(vsiaz_path)
            if file_list:
                print(f"  ✓ Successfully listed {len(file_list)} files")
            else:
                print(f"  ⚠ Container is empty or inaccessible")
        except Exception as e:
            print(f"  ✗ Error accessing container: {e}")

if __name__ == "__main__":
    test_oauth_authentication()
```

### Expected Results

```bash
$ python test_oauth.py

Acquiring OAuth token...
✓ Token acquired (expires in 3599 seconds)

Testing container: silver-cogs
  ✓ Successfully listed 150 files

Testing container: bronze-cogs
  ✓ Successfully listed 75 files

Testing container: gold-cogs
  ✓ Successfully listed 42 files
```

---

## Security Considerations

### OAuth Token Security

**Advantages**:
- Tied to Managed Identity (can't be used outside Azure)
- Respects RBAC permissions exactly
- Automatically rotated/managed by Azure
- Can be revoked by disabling Managed Identity

**Important**:
- Token is a **bearer token** - anyone with the token can use it
- Should be kept in memory only (not logged or persisted)
- Use HTTPS for all requests
- Monitor token usage via Azure Monitor

### RBAC Best Practices

**Least Privilege**:
```bash
# Minimum required role
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee-object-id <managed-identity-principal-id> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>
```

**Container-Specific** (if needed):
```bash
# Limit to specific container
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee-object-id <managed-identity-principal-id> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>/blobServices/default/containers/<container>
```

---

## Recommendation

### Immediate Action

1. **Test OAuth approach locally** (5 minutes)
2. **If successful, replace SAS code** (30 minutes)
3. **Deploy and verify** (15 minutes)
4. **Update documentation** (15 minutes)

**Total time**: ~1 hour (vs. 6-10 days for SAS multi-container solution)

### Long-term Benefits

- **Simplicity**: 75% less code to maintain
- **Performance**: Fewer API calls
- **Scalability**: Works for any number of containers automatically
- **Security**: Direct RBAC permission model
- **Compliance**: Easier to audit (one permission model, not two)

---

## Conclusion

**You were absolutely right!** SAS tokens are for *limiting* access, which is not what you need. You want to *grant* access based on RBAC roles. OAuth tokens do exactly that, much more simply.

**Key Insight**:
- **SAS tokens** = Delegation with restrictions (for untrusted clients)
- **OAuth tokens** = Identity authentication (for trusted services)

Your use case is clearly the latter. Switch to OAuth tokens for a simpler, more maintainable solution that solves the multi-container problem automatically.

---

**Next Steps**:
1. Test OAuth token locally
2. Update `custom_main.py` to use OAuth approach
3. Deploy new version
4. Celebrate simplicity!

