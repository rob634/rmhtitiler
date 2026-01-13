# OAuth Authentication Architecture

## Overview

TiTiler-pgSTAC uses Azure Managed Identity for OAuth-based authentication to Azure Blob Storage. This document explains how OAuth works in different environments.

## Local Development vs Azure Production

### **Local Development** (Current Implementation)

**Problem Solved:**
- Docker volume mounts on macOS sometimes create read-only file system issues
- Azure CLI needs to write session files (`/root/.azure/az.sess`)
- Mounting `~/.azure` as a volume causes `OSError: [Errno 30] Read-only file system`

**Solution:**
```dockerfile
# Dockerfile.local
COPY --chown=root:root .azure /root/.azure
```

**How It Works:**
1. **Before Docker build:** Run `az login` on host machine
2. **During Docker build:** Copy `~/.azure` directory into image
3. **At runtime:** Azure SDK uses `AzureCliCredential`
4. **Credential chain:**
   ```
   DefaultAzureCredential tries:
   1. EnvironmentCredential ❌ (no env vars set)
   2. ManagedIdentityCredential ❌ (no IMDS endpoint locally)
   3. SharedTokenCacheCredential ❌ (no cache)
   4. AzureCliCredential ✅ (uses copied /root/.azure)
   ```
5. **Token acquisition:** Reads Azure CLI session from `/root/.azure`
6. **Token usage:** Sets `os.environ["AZURE_STORAGE_ACCESS_TOKEN"]`
7. **GDAL access:** GDAL reads token from environment, uses for `/vsiaz/` paths

**Security Note:**
- `.azure/` directory contains sensitive credentials
- Added to `.gitignore` to prevent accidental commits
- Only used for local development

---

### **Azure Production** (App Service with Managed Identity)

**How It Works:**
1. **App Service Configuration:**
   - System-assigned Managed Identity enabled
   - Identity granted "Storage Blob Data Reader" RBAC role on storage account

2. **No credentials needed in code:**
   ```python
   # No secrets, no keys, no tokens in environment variables
   credential = DefaultAzureCredential()  # Automatically uses Managed Identity
   ```

3. **Credential chain (production):**
   ```
   DefaultAzureCredential tries:
   1. EnvironmentCredential ❌ (optional, not needed)
   2. ManagedIdentityCredential ✅ (Azure provides via IMDS endpoint)
      - App Service has IMDS at http://169.254.169.254
      - Returns OAuth token for the Managed Identity
   3. (other credentials not tried - already succeeded)
   ```

4. **Token acquisition:**
   - App makes HTTP request to `http://169.254.169.254/metadata/identity/oauth2/token`
   - Azure responds with OAuth token for scope `https://storage.azure.com/.default`
   - Token is automatically rotated by Azure (lasts ~24 hours)

5. **Token usage:** Same as local - sets `os.environ["AZURE_STORAGE_ACCESS_TOKEN"]`

6. **GDAL access:** Same as local - GDAL uses token for `/vsiaz/` paths

---

## Why `/vsiaz/` Paths Are Required

### GDAL Virtual File System

GDAL supports multiple "virtual file systems" for cloud storage:

- `/vsicurl/` - Generic HTTPS with custom headers
- `/vsis3/` - AWS S3 (uses AWS credentials)
- `/vsiaz/` - Azure Blob Storage (uses Azure credentials)
- `/vsigs/` - Google Cloud Storage

### How /vsiaz/ Uses OAuth Tokens

When GDAL opens a path like `/vsiaz/silver-cogs/file.tif`:

1. **Path parsing:**
   ```
   /vsiaz/silver-cogs/file.tif
   ↓
   Container: silver-cogs
   Blob: file.tif
   ```

2. **Environment variable lookup:**
   ```python
   account = os.environ["AZURE_STORAGE_ACCOUNT"]  # rmhazuregeo
   token = os.environ["AZURE_STORAGE_ACCESS_TOKEN"]  # eyJ0eXAi...
   ```

3. **HTTP request construction:**
   ```http
   GET https://rmhazuregeo.blob.core.windows.net/silver-cogs/file.tif
   Host: rmhazuregeo.blob.core.windows.net
   Authorization: Bearer eyJ0eXAiOi...
   x-ms-version: 2021-08-06
   ```

4. **Azure validates:**
   - Token signature (cryptographically signed by Azure AD)
   - Token expiration (typically 1 hour)
   - RBAC permissions (Storage Blob Data Reader role)

5. **Returns blob data** if authorized

### Why HTTPS URLs Don't Work

If we used plain HTTPS URLs in STAC items:
```json
"href": "https://rmhazuregeo.blob.core.windows.net/silver-cogs/file.tif"
```

GDAL would:
1. Treat it as a regular HTTP request (no special Azure handling)
2. Not automatically add `Authorization` header
3. Azure would return `404` or `403` (no authentication)

---

## Authentication Flow Comparison

### Local Development
```
Host Machine                    Docker Container                Azure Storage
    │                                 │                              │
    │  1. az login                    │                              │
    │──────────────>                  │                              │
    │  (saves to ~/.azure)            │                              │
    │                                 │                              │
    │  2. docker build                │                              │
    │─────────(copies .azure)────────>│                              │
    │                                 │                              │
    │  3. App starts                  │                              │
    │                                 │  4. AzureCliCredential       │
    │                                 │      reads /root/.azure      │
    │                                 │                              │
    │                                 │  5. get_token()              │
    │                                 │─────(uses CLI token)────────>│
    │                                 │<────(OAuth token)────────────│
    │                                 │                              │
    │                                 │  6. os.environ["...TOKEN"]   │
    │                                 │                              │
    │  7. Tile request                │                              │
    │────────────────────────────────>│                              │
    │                                 │  8. GDAL opens /vsiaz/       │
    │                                 │─────(with OAuth header)─────>│
    │                                 │<────(blob data)──────────────│
    │<────(PNG tile)──────────────────│                              │
```

### Azure Production
```
App Service                     IMDS Endpoint               Azure Storage
    │                                 │                              │
    │  1. App starts                  │                              │
    │     (Managed Identity enabled)  │                              │
    │                                 │                              │
    │  2. get_token()                 │                              │
    │──────────────────────────────>│                              │
    │     (scope: storage.azure.com)  │                              │
    │                                 │  3. Validates identity       │
    │<─────(OAuth token)──────────────│                              │
    │                                 │                              │
    │  4. os.environ["...TOKEN"]      │                              │
    │     (cached for ~1 hour)        │                              │
    │                                 │                              │
    │  5. Tile request arrives        │                              │
    │                                 │                              │
    │  6. GDAL opens /vsiaz/          │                              │
    │────────────────────(with OAuth header)──────────────────────>│
    │<───────────────────(blob data)───────────────────────────────│
    │                                 │                              │
    │  7. Return PNG tile             │                              │
```

---

## Key Differences: Local vs Production

| Aspect | Local Development | Azure Production |
|--------|------------------|------------------|
| **Credential Source** | Azure CLI (`~/.azure`) | Managed Identity (IMDS) |
| **How Provided** | Copied at build time | Provided by Azure platform |
| **Token Acquisition** | `AzureCliCredential` | `ManagedIdentityCredential` |
| **Configuration** | `LOCAL_MODE=true` | `LOCAL_MODE=false` |
| **Secrets Management** | User's Azure login | No secrets needed |
| **RBAC** | User's permissions | Service Principal permissions |
| **Token Refresh** | Manual (`az login` again) | Automatic (every ~1 hour) |

---

## Why This is Better Than SAS Tokens

### OAuth Bearer Tokens (Current)
```python
# One token, all containers (based on RBAC)
os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = oauth_token
# Access any container the identity has permissions for
```

**Advantages:**
- ✅ Identity-based (who you are)
- ✅ RBAC-controlled (what you can do)
- ✅ Multi-container access automatically
- ✅ Centralized permission management
- ✅ Auto-rotates (no expiration management)
- ✅ Simpler code (36% fewer lines than SAS)

### SAS Tokens (Alternative)
```python
# Per-container or per-blob tokens
os.environ["AZURE_STORAGE_SAS_TOKEN"] = "?se=2025-11-09&sp=r&sig=..."
# Appended to URL: /vsiaz/container/blob.tif?se=2025-11-09&sp=r&sig=...
```

**Disadvantages:**
- ❌ Token-based (what you have, not who you are)
- ❌ Need storage account key to generate
- ❌ Per-container tokens (management overhead)
- ❌ Fixed expiration (need to regenerate)
- ❌ More complex code

---

## Security Best Practices

### Local Development
1. ✅ `.azure/` in `.gitignore` - prevents credential leaks
2. ✅ Build-time copy (not runtime mount) - avoids file system issues
3. ✅ Uses user's own Azure permissions - no shared credentials
4. ⚠️ Image contains credentials - don't push to registry

### Production
1. ✅ System-assigned Managed Identity - no credentials in code
2. ✅ RBAC roles - principle of least privilege
3. ✅ No secrets in environment variables
4. ✅ Automatic token rotation
5. ✅ Azure AD audit logs

---

## Troubleshooting

### Local: "Read-only file system" Error
**Problem:** Docker volume mount creates read-only files on macOS

**Solution:** Copy credentials at build time (current implementation)
```dockerfile
COPY --chown=root:root .azure /root/.azure
```

### Local: "No credentials found"
**Problem:** Haven't run `az login` on host

**Solution:**
```bash
az login
az account show  # Verify logged in
docker-compose build --no-cache  # Rebuild to copy new credentials
```

### Production: "ManagedIdentityCredential authentication unavailable"
**Problem:** Managed Identity not enabled or RBAC not assigned

**Solution:**
```bash
# Enable Managed Identity
az webapp identity assign --name <app> --resource-group <rg>

# Grant Storage Blob Data Reader
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee <principal-id> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/rmhazuregeo
```

### Both: HTTP 403 Forbidden
**Problem:** OAuth token not being passed to GDAL

**Check:**
1. Token acquired? (check startup logs for "✓ OAuth token acquired")
2. Environment variable set? (`os.environ["AZURE_STORAGE_ACCESS_TOKEN"]`)
3. Asset href correct format? (must be `/vsiaz/container/blob`, not `https://...`)

---

## References

- [Azure Managed Identity](https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/)
- [GDAL /vsiaz/ driver](https://gdal.org/en/latest/user/virtual_file_systems.html#vsiaz-microsoft-azure-blob-files)
- [Azure Identity Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme)
- [DefaultAzureCredential chain](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential)
