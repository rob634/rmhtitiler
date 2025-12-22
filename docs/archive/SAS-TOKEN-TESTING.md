# Testing SAS Token Workflow

This guide explains how to test the User Delegation SAS token workflow locally before deploying to production.

## 🎯 Why SAS Tokens?

**User Delegation SAS tokens are more secure than direct key access:**
- ✅ Uses Azure AD authentication (not storage keys)
- ✅ Tokens auto-expire and refresh
- ✅ Can be scoped to specific permissions
- ✅ Can be revoked by revoking the Azure AD identity
- ✅ Same workflow in dev and production

## 🔄 The Workflow

### Development (What we're testing):
```
Storage Account Key
    ↓
Generate SAS Token (1 hour validity)
    ↓
Pass SAS Token to GDAL via environment variable
    ↓
GDAL reads COGs from Azure Storage
    ↓
SAS Token auto-refreshes before expiry
```

### Production (Future):
```
Managed Identity
    ↓
Generate SAS Token (1 hour validity)
    ↓
Pass SAS Token to GDAL via environment variable
    ↓
GDAL reads COGs from Azure Storage
    ↓
SAS Token auto-refreshes before expiry
```

**Same code, different credential source!**

## 📋 Prerequisites

1. **Azure Storage Account** with a container
2. **Storage Account Key** (get from Azure Portal)
3. **A COG file** uploaded to your container

### Get Your Storage Account Key

```bash
# Via Azure CLI
az storage account keys list \
  --account-name yourstorageaccount \
  --resource-group yourresourcegroup \
  --query '[0].value' -o tsv

# Or get it from Azure Portal:
# Storage Account → Access Keys → key1 → Show → Copy
```

## 🚀 Step-by-Step Testing

### Step 1: Configure Environment

Create `.env.local` file:

```bash
cp .env.local.example .env.local
```

Edit `.env.local`:

```bash
# Enable Azure auth and SAS tokens
LOCAL_MODE=true
USE_AZURE_AUTH=true
USE_SAS_TOKEN=true

# Your Azure Storage details
AZURE_STORAGE_ACCOUNT=yourstorageaccount
AZURE_STORAGE_KEY=your_storage_key_here

# GDAL performance settings (optional)
CPL_VSIL_CURL_CACHE_SIZE=128000000
GDAL_CACHEMAX=512
```

### Step 2: Update docker-compose.yml

Edit `docker-compose.yml` to use your `.env.local`:

```yaml
services:
  titiler:
    # ... existing config ...
    env_file:
      - .env.local  # Add this line
```

Or set environment variables directly:

```yaml
environment:
  - LOCAL_MODE=true
  - USE_AZURE_AUTH=true
  - USE_SAS_TOKEN=true
  - AZURE_STORAGE_ACCOUNT=yourstorageaccount
  - AZURE_STORAGE_KEY=your_key_here
```

### Step 3: Upload a Test COG to Azure

```bash
# Create a container (if needed)
az storage container create \
  --name test-cogs \
  --account-name yourstorageaccount \
  --account-key your_key_here

# Upload a test COG
az storage blob upload \
  --account-name yourstorageaccount \
  --account-key your_key_here \
  --container-name test-cogs \
  --name example.tif \
  --file ./data/example.tif
```

### Step 4: Rebuild and Start TiTiler

```bash
# Rebuild with new code
docker-compose down
docker-compose up --build

# Or in detached mode
docker-compose up --build -d
```

### Step 5: Check the Logs

Watch for SAS token generation:

```bash
docker-compose logs -f titiler
```

**Look for:**
```
INFO:     TiTiler with Azure SAS Token Auth - Starting up
INFO:     Local mode: True
INFO:     Azure auth enabled: True
INFO:     Use SAS tokens: True
INFO:     Initializing Azure auth for account: yourstorageaccount
INFO:     Using storage account key credential (development mode)
INFO:     Generating new User Delegation SAS token
INFO:     SAS token generated, expires at 2025-11-07 12:05:00+00:00 (in 3600s)
INFO:     SAS token workflow: Storage Key -> SAS Token -> GDAL
INFO:     Startup complete - Ready to serve tiles!
```

### Step 6: Test with Your COG

```bash
# Health check (should show SAS token info)
curl "http://localhost:8000/healthz" | jq

# Test COG info
curl "http://localhost:8000/cog/info?url=/vsiaz/test-cogs/example.tif" | jq

# Get a tile
curl "http://localhost:8000/cog/tiles/WebMercatorQuad/10/100/100?url=/vsiaz/test-cogs/example.tif" \
  -o tile.png
```

**Expected output:**
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "use_sas_token": true,
  "local_mode": true,
  "storage_account": "yourstorageaccount",
  "sas_token_expires_in_seconds": 3400
}
```

## 🔍 Verify SAS Token Generation

### Check Environment Variables (Inside Container)

```bash
# Exec into container
docker-compose exec titiler bash

# Check what GDAL sees
env | grep AZURE

# Should show:
# AZURE_STORAGE_ACCOUNT=yourstorageaccount
# AZURE_STORAGE_SAS_TOKEN=sv=2023-01-03&ss=...
# (NO AZURE_STORAGE_ACCESS_KEY - key is not exposed to GDAL!)
```

### Monitor Token Refresh

The SAS token auto-refreshes every 55 minutes. Watch the logs:

```bash
docker-compose logs -f titiler | grep "SAS token"
```

After 55 minutes, you should see:
```
INFO: Generating new User Delegation SAS token
INFO: SAS token generated, expires at ...
```

## 🐛 Troubleshooting

### Error: "AZURE_STORAGE_KEY not set"

**Solution:** Add your storage key to `.env.local`:
```bash
AZURE_STORAGE_KEY=your_key_here
```

### Error: "Failed to generate SAS token"

**Check:**
1. Storage account name is correct
2. Storage account key is valid
3. Storage account exists and is accessible

**Test manually:**
```bash
az storage account show \
  --name yourstorageaccount \
  --query 'name'
```

### Error: "AuthorizationPermissionMismatch"

This means the SAS token doesn't have the right permissions.

**Check:**
1. Token includes `read` and `list` permissions
2. Container name matches
3. Token hasn't expired

### COG Not Found / 404 Error

**Check:**
1. Container name: `/vsiaz/CONTAINER/path/to/file.tif`
2. File exists: `az storage blob list --container-name yourcontainer`
3. Path is correct (case-sensitive!)

## ✅ Success Criteria

You've successfully tested SAS tokens if:

1. ✅ Logs show "SAS token generated"
2. ✅ Health endpoint shows `sas_token_expires_in_seconds`
3. ✅ GDAL can read your COG via `/vsiaz/` path
4. ✅ No `AZURE_STORAGE_ACCESS_KEY` in environment (only `AZURE_STORAGE_SAS_TOKEN`)
5. ✅ Token auto-refreshes every hour

## 🚀 Next Steps: Production Deployment

Once local testing works, deploy to production:

### Update Dockerfile for Production

The production `Dockerfile` should have:

```dockerfile
# Production settings
ENV LOCAL_MODE=false
ENV USE_AZURE_AUTH=true
ENV USE_SAS_TOKEN=true
```

### Azure App Service Configuration

1. **Enable Managed Identity:**
```bash
az webapp identity assign \
  --resource-group your-rg \
  --name your-titiler-app
```

2. **Set Environment Variables:**
```bash
az webapp config appsettings set \
  --resource-group your-rg \
  --name your-titiler-app \
  --settings \
    AZURE_STORAGE_ACCOUNT=yourstorageaccount \
    USE_AZURE_AUTH=true \
    USE_SAS_TOKEN=true \
    LOCAL_MODE=false
```

3. **Grant Storage Permissions:**
```bash
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee <managed-identity-principal-id> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>
```

### Code Changes for Production

**None!** The same code works in production. It automatically detects:
- `LOCAL_MODE=false` → Uses Managed Identity instead of storage key
- `USE_SAS_TOKEN=true` → Generates SAS tokens same way
- GDAL receives SAS tokens the same way

## 📊 Comparison: Development vs Production

| Aspect | Development | Production |
|--------|------------|------------|
| **Credential Source** | Storage Account Key | Managed Identity |
| **Token Generation** | ✅ Same code | ✅ Same code |
| **Token Type** | SAS Token | SAS Token |
| **Token Lifetime** | 1 hour | 1 hour |
| **Auto-Refresh** | ✅ Yes | ✅ Yes |
| **GDAL Integration** | ✅ Same | ✅ Same |
| **Security** | Key in .env (gitignored) | No keys anywhere! |

## 🎓 What You're Testing

By testing SAS tokens locally, you're validating:

1. ✅ **Token Generation** - Can generate valid SAS tokens
2. ✅ **Token Caching** - Tokens are cached and reused
3. ✅ **Token Refresh** - Tokens refresh before expiry
4. ✅ **GDAL Integration** - GDAL can use SAS tokens
5. ✅ **Production Workflow** - Same code path as production

The only difference in production is the credential source (Managed Identity vs Storage Key), which is handled automatically by the code!

## 📚 Additional Resources

- [Azure Storage SAS Documentation](https://docs.microsoft.com/azure/storage/common/storage-sas-overview)
- [User Delegation SAS](https://docs.microsoft.com/azure/storage/common/storage-sas-overview#user-delegation-sas)
- [GDAL /vsiaz/ Driver](https://gdal.org/user/virtual_file_systems.html#vsiaz)
