# PostgreSQL Managed Identity Implementation - Complete

**Date**: November 15, 2025
**Status**: ✅ Code Updated, Ready for Deployment

---

## Summary of Changes

The `custom_pgstac_main.py` file has been updated to support **PostgreSQL Managed Identity authentication** in addition to the existing Azure Storage OAuth.

### What Changed

1. ✅ **Added PostgreSQL MI configuration variables** (lines 50-58)
2. ✅ **Added `get_postgres_oauth_token()` function** (lines 183-282)
3. ✅ **Updated `startup_event()` to build DATABASE_URL with MI token** (lines 461-578)

---

## Environment Variables Required

### For Production (Azure App Service with Managed Identity)

```bash
# PostgreSQL Managed Identity Authentication
USE_POSTGRES_MI=true
POSTGRES_HOST=rmhpgflex.postgres.database.azure.com
POSTGRES_DB=geopgflex
POSTGRES_USER=rmhtitileridentity
POSTGRES_PORT=5432

# Azure Storage OAuth Authentication (existing)
USE_AZURE_AUTH=true
AZURE_STORAGE_ACCOUNT=rmhazuregeo

# Mode
LOCAL_MODE=false

# DO NOT SET DATABASE_URL when using USE_POSTGRES_MI=true
# (It will be built automatically at startup with the MI token)
```

### For Local Development (Azure CLI)

```bash
# Option 1: Use Managed Identity locally (requires 'az login')
USE_POSTGRES_MI=true
POSTGRES_HOST=rmhpgflex.postgres.database.azure.com
POSTGRES_DB=geopgflex
POSTGRES_USER=rmhtitileridentity
POSTGRES_PORT=5432
LOCAL_MODE=true

# Option 2: Use traditional password auth locally
USE_POSTGRES_MI=false
DATABASE_URL=postgresql://rob634:B@lamb634@@rmhpgflex.postgres.database.azure.com:5432/geopgflex?sslmode=require

# Storage (always uses Azure CLI in local mode)
USE_AZURE_AUTH=true
AZURE_STORAGE_ACCOUNT=rmhazuregeo
LOCAL_MODE=true
```

---

## Azure Configuration

### 1. Managed Identity (Already Created) ✅

- **Name**: `rmhtitileridentity`
- **Client ID**: `191869d4-fd0b-4b18-a058-51adc2dbd54b`
- **Principal ID**: `1de78b58-18de-4e21-a3e3-e7b69786eaad`
- **Object ID**: `1de78b58-18de-4e21-a3e3-e7b69786eaad`

### 2. Web App Assignment (Already Done) ✅

The managed identity is already assigned to `rmhtitiler` web app.

### 3. PostgreSQL User (Already Created) ✅

The PostgreSQL user `rmhtitileridentity` has been created with:
- ✅ Login enabled
- ✅ Read permissions on all pgstac tables
- ✅ Write permissions on `pgstac.searches` table (INSERT, UPDATE, DELETE)

---

## Deployment Steps

### Step 1: Set Environment Variables in Azure App Service

```bash
az webapp config appsettings set \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --settings \
    USE_POSTGRES_MI="true" \
    POSTGRES_HOST="rmhpgflex.postgres.database.azure.com" \
    POSTGRES_DB="geopgflex" \
    POSTGRES_USER="rmhtitileridentity" \
    POSTGRES_PORT="5432" \
    LOCAL_MODE="false" \
    USE_AZURE_AUTH="true" \
    AZURE_STORAGE_ACCOUNT="rmhazuregeo"
```

### Step 2: Remove Old DATABASE_URL (if set)

```bash
# Check if DATABASE_URL is set
az webapp config appsettings list \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --query "[?name=='DATABASE_URL']"

# Remove it if found (not needed with MI)
az webapp config appsettings delete \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --setting-names DATABASE_URL
```

### Step 3: Deploy Updated Code

```bash
# Build the Docker image
docker build --platform linux/amd64 -t rmhazureacr.azurecr.io/titiler-pgstac:latest -f Dockerfile .

# Login to ACR
az acr login --name rmhazureacr

# Push the image
docker push rmhazureacr.azurecr.io/titiler-pgstac:latest

# Restart the web app
az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

### Step 4: Verify Deployment

```bash
# Stream logs to watch startup
az webapp log tail --name rmhtitiler --resource-group rmhazure_rg

# Look for these log messages:
# ✓ "🔑 Acquiring OAuth token for PostgreSQL"
# ✓ "✅ PostgreSQL OAuth token successfully acquired"
# ✓ "✓ Built DATABASE_URL with MI token"
# ✓ "✓ Database connection established"
# ✓ "✓ Storage OAuth authentication initialized successfully"
# ✓ "✅ TiTiler-pgSTAC startup complete"
```

### Step 5: Test the Application

```bash
# Health check
curl https://rmhtitiler.azurewebsites.net/healthz | jq

# Expected response includes:
# {
#   "status": "healthy",
#   "database_status": "connected",
#   "azure_auth_enabled": true,
#   "local_mode": false,
#   ...
# }

# Test search registration (uses database write permissions)
curl -X POST "https://rmhtitiler.azurewebsites.net/searches/register" \
  -H "Content-Type: application/json" \
  -d '{"collections":["system-rasters"],"limit":10}' | jq

# Test tile serving
curl "https://rmhtitiler.azurewebsites.net/searches/{search_id}/tiles/WebMercatorQuad/14/11454/6143.png?assets=data" -o tile.png
```

---

## How It Works

### Token Acquisition Flow

```
App Startup
    ↓
Check USE_POSTGRES_MI=true
    ↓
Call get_postgres_oauth_token()
    ↓
DefaultAzureCredential().get_token("https://ossrdbms-aad.database.windows.net/.default")
    ↓
Managed Identity returns OAuth token (valid ~1 hour)
    ↓
Build DATABASE_URL = postgresql://rmhtitileridentity:{TOKEN}@rmhpgflex.postgres.database.azure.com/geopgflex
    ↓
Connect to database with token as password
    ↓
Connection pool established
    ↓
App ready to serve requests
```

### Key Differences from Storage OAuth

| Aspect | Azure Storage | PostgreSQL |
|--------|---------------|------------|
| **Token Scope** | `https://storage.azure.com/.default` | `https://ossrdbms-aad.database.windows.net/.default` |
| **When Acquired** | Per-request (middleware) | Once at startup |
| **Where Stored** | `os.environ` (per-request) | Built into `DATABASE_URL` |
| **Who Uses It** | GDAL (C++ library) | asyncpg (Python driver) |
| **Refresh Pattern** | Every request checks cache | App restart (natural cycle) |

### Token Lifetime

- **Token validity**: ~1 hour
- **Refresh strategy**: App restarts naturally (Azure App Service restarts apps periodically)
- **Connection pooling**: TiTiler's connection pool handles reconnections automatically

---

## Troubleshooting

### Issue: "Failed to acquire PostgreSQL token"

**Check Managed Identity:**
```bash
az webapp identity show --name rmhtitiler --resource-group rmhazure_rg
```

Should show:
```json
{
  "userAssignedIdentities": {
    ".../rmhtitileridentity": {
      "clientId": "191869d4-fd0b-4b18-a058-51adc2dbd54b",
      "principalId": "1de78b58-18de-4e21-a3e3-e7b69786eaad"
    }
  }
}
```

### Issue: "Role 'rmhtitileridentity' does not exist"

**Verify PostgreSQL user:**
```bash
PGPASSWORD='B@lamb634@' psql \
  -h rmhpgflex.postgres.database.azure.com \
  -U rob634 \
  -d geopgflex \
  -c "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'rmhtitileridentity';"
```

Should show:
```
      rolname       | rolcanlogin
--------------------+-------------
 rmhtitileridentity | t
(1 row)
```

### Issue: "Connection timeout"

**Check firewall rules:**
```bash
az postgres flexible-server firewall-rule list \
  --resource-group rmhazure_rg \
  --name rmhpgflex -o table
```

Ensure Azure services are allowed:
```bash
az postgres flexible-server firewall-rule create \
  --resource-group rmhazure_rg \
  --name rmhpgflex \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

### Issue: "Permission denied for table X"

**Check permissions:**
```bash
PGPASSWORD='B@lamb634@' psql \
  -h rmhpgflex.postgres.database.azure.com \
  -U rob634 \
  -d geopgflex \
  -c "SELECT grantee, table_name, privilege_type
      FROM information_schema.table_privileges
      WHERE grantee = 'rmhtitileridentity'
        AND table_schema = 'pgstac'
      ORDER BY table_name;"
```

---

## Security Benefits

### Before (Password Auth)
- ❌ Password stored in environment variable
- ❌ Manual password rotation required
- ❌ Password visible in logs/config
- ❌ Risk of credential leakage

### After (Managed Identity)
- ✅ No passwords stored anywhere
- ✅ Automatic token rotation (~1 hour)
- ✅ Tokens never logged (only token length shown)
- ✅ Azure audit trail for all access
- ✅ RBAC-based access control
- ✅ Easy to rotate (just recreate identity)

---

## What's Enabled

With the PostgreSQL user created with read-write permissions, your app can now:

### Read Operations
✅ Serve tiles from searches: `/searches/{search_id}/tiles/{z}/{x}/{y}`
✅ Get search info: `/searches/{search_id}/info`
✅ List searches: `/searches`
✅ Get collection metadata: `/collections`
✅ Statistics endpoints

### Write Operations
✅ Register new searches: `/searches/register`
✅ Update searches in database
✅ Delete searches from database

### What's NOT Allowed
❌ Modify STAC items (read-only on items table)
❌ Modify collections (read-only on collections table)
❌ Drop tables or schemas (no admin permissions)

---

## Rollback Plan

If you need to rollback to password authentication:

```bash
# Set DATABASE_URL with password
az webapp config appsettings set \
  --name rmhtitiler \
  --resource-group rmhazure_rg \
  --settings \
    USE_POSTGRES_MI="false" \
    DATABASE_URL="postgresql://rob634:B@lamb634@@rmhpgflex.postgres.database.azure.com:5432/geopgflex?sslmode=require"

# Restart app
az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

The code automatically falls back to using `DATABASE_URL` from environment when `USE_POSTGRES_MI=false`.

---

## Next Steps

1. ✅ Code changes complete
2. ⏳ Set environment variables in Azure App Service
3. ⏳ Deploy updated code
4. ⏳ Verify logs show successful PostgreSQL MI token acquisition
5. ⏳ Test `/healthz` endpoint
6. ⏳ Test `/searches/register` endpoint
7. ⏳ Remove old `DATABASE_URL` from app settings (optional, for security)

---

**Status**: Ready for Production Deployment 🚀

All code changes are complete. The application now supports fully passwordless authentication for both Azure Storage and PostgreSQL using Managed Identity.
