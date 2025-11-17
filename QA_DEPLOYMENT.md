# TiTiler-pgSTAC Azure Deployment Guide (QA/Production)

**Date**: November 17, 2025
**Purpose**: Complete deployment guide for corporate Azure tenants
**Status**: Production-Ready Architecture

---

## 📋 Overview

This custom TiTiler-pgSTAC implementation provides **passwordless, enterprise-grade Azure integration** with dual managed identity support:

- **System-Assigned Managed Identity** → Azure Storage OAuth authentication
- **User-Assigned Managed Identity** → PostgreSQL OAuth authentication (optional, configurable)

**Key Benefits:**
- ✅ Zero secrets stored in configuration
- ✅ Automatic token rotation (every ~1 hour)
- ✅ Multi-container storage access via RBAC
- ✅ Comprehensive operational logging
- ✅ Flexible authentication modes (managed_identity, key_vault, password)

---

## 🔑 Part 1: Environment Variables

### Required Environment Variables

#### PostgreSQL Authentication (3 Modes Available)

**Mode 1: Managed Identity (Recommended for Production)**
```bash
POSTGRES_AUTH_MODE=managed_identity
POSTGRES_HOST=your-server.postgres.database.azure.com
POSTGRES_DB=geopgflex
POSTGRES_USER=your-mi-name         # Must match user-assigned MI name
POSTGRES_PORT=5432                  # Optional, defaults to 5432
```

**Mode 2: Key Vault (Fallback)**
```bash
POSTGRES_AUTH_MODE=key_vault
POSTGRES_HOST=your-server.postgres.database.azure.com
POSTGRES_DB=geopgflex
POSTGRES_USER=your_db_user
POSTGRES_PORT=5432
KEY_VAULT_NAME=your-vault-name
KEY_VAULT_SECRET_NAME=postgres-password  # Optional, defaults to this
```

**Mode 3: Environment Variable Password (Development/Debugging)**
```bash
POSTGRES_AUTH_MODE=password
POSTGRES_HOST=your-server.postgres.database.azure.com
POSTGRES_DB=geopgflex
POSTGRES_USER=your_db_user
POSTGRES_PORT=5432
POSTGRES_PASSWORD=your_password
```

#### Azure Storage Authentication

```bash
USE_AZURE_AUTH=true                 # Enable OAuth for storage
AZURE_STORAGE_ACCOUNT=your-storage  # Storage account name
LOCAL_MODE=false                    # false = Managed Identity, true = Azure CLI
```

#### GDAL Optimizations (Optional but Recommended)

```bash
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES
GDAL_HTTP_MULTIPLEX=YES
GDAL_HTTP_VERSION=2
VSI_CACHE=TRUE
VSI_CACHE_SIZE=536870912            # 512MB cache
```

### Environment Variable Reference Table

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_AUTH_MODE` | Yes | `password` | Authentication mode: `managed_identity`, `key_vault`, or `password` |
| `POSTGRES_HOST` | Yes | - | PostgreSQL server hostname |
| `POSTGRES_DB` | Yes | - | Database name |
| `POSTGRES_USER` | Yes | - | PostgreSQL username (should match MI name for MI auth) |
| `POSTGRES_PORT` | No | `5432` | PostgreSQL port |
| `POSTGRES_PASSWORD` | If `password` mode | - | Database password (only for password mode) |
| `KEY_VAULT_NAME` | If `key_vault` mode | - | Azure Key Vault name |
| `KEY_VAULT_SECRET_NAME` | If `key_vault` mode | `postgres-password` | Secret name in Key Vault |
| `USE_AZURE_AUTH` | Yes | `false` | Enable Azure Storage OAuth |
| `AZURE_STORAGE_ACCOUNT` | If `USE_AZURE_AUTH=true` | - | Storage account name |
| `LOCAL_MODE` | No | `true` | `false` for Managed Identity, `true` for Azure CLI |

---

## 🔐 Part 2: RBAC Permissions

### Storage Access: System-Assigned Managed Identity

The **web app's system-assigned managed identity** needs the following RBAC role:

#### Role Assignment: Storage Blob Data Reader

**Scope**: Storage account level
**Purpose**: Read-only access to all blob containers

```bash
# Get the web app's system-assigned managed identity principal ID
PRINCIPAL_ID=$(az webapp identity show \
  --name your-webapp \
  --resource-group your-rg \
  --query principalId -o tsv)

# Assign Storage Blob Data Reader role
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/your-rg/providers/Microsoft.Storage/storageAccounts/your-storage
```

**What This Enables:**
- ✅ Read access to ALL containers in the storage account
- ✅ No SAS tokens or account keys needed
- ✅ GDAL can access `/vsiaz/container-name/file.tif` paths
- ✅ Automatic token refresh (middleware handles this)

**Propagation Time**: 2-5 minutes after role assignment

---

### Database Access: User-Assigned Managed Identity (Optional)

If using `POSTGRES_AUTH_MODE=managed_identity`, you need a **user-assigned managed identity** for PostgreSQL access.

#### Why User-Assigned?

| Aspect | System-Assigned | User-Assigned |
|--------|----------------|---------------|
| **Lifecycle** | Tied to web app | Independent resource |
| **Naming** | Auto-generated | Predictable, controlled |
| **Reusability** | Single web app | Multiple apps/environments |
| **IaC Friendly** | Harder to reference | Explicit resource ID |
| **PostgreSQL User** | Random name | Controlled name |

#### Step 1: Create User-Assigned Managed Identity

```bash
# Create the managed identity
az identity create \
  --name titiler-db-access \
  --resource-group your-rg \
  --location eastus

# Get the client ID (needed for explicit authentication)
CLIENT_ID=$(az identity show \
  --name titiler-db-access \
  --resource-group your-rg \
  --query clientId -o tsv)

PRINCIPAL_ID=$(az identity show \
  --name titiler-db-access \
  --resource-group your-rg \
  --query principalId -o tsv)

echo "Client ID: $CLIENT_ID"
echo "Principal ID: $PRINCIPAL_ID"
```

#### Step 2: Assign Identity to Web App

```bash
# Assign the user-assigned managed identity to your web app
az webapp identity assign \
  --name your-webapp \
  --resource-group your-rg \
  --identities /subscriptions/YOUR_SUBSCRIPTION_ID/resourcegroups/your-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/titiler-db-access

# Verify assignment
az webapp identity show \
  --name your-webapp \
  --resource-group your-rg
```

**Result**: Web app now has BOTH identities:
- System-assigned → Storage access
- User-assigned → PostgreSQL access

---

## 🗄️ Part 3: PostgreSQL Managed Identity Setup

### Prerequisites

- Azure Database for PostgreSQL Flexible Server
- pgSTAC extension installed
- Admin access to the database
- User-assigned managed identity created and assigned to web app

### Step 1: Enable Entra ID Authentication

Connect to PostgreSQL as an admin user:

```bash
PGPASSWORD='your-admin-password' psql \
  -h your-server.postgres.database.azure.com \
  -U admin_user \
  -d your_database
```

Enable Azure Active Directory (Entra ID) authentication:

```sql
-- Enable managed identity authentication
SET aad_validate_oids_in_tenant = off;
```

### Step 2: Create PostgreSQL User for Managed Identity

**IMPORTANT**: The PostgreSQL username **MUST** exactly match the managed identity name.

```sql
-- Create the database user matching your managed identity name
-- Replace 'titiler-db-access' with YOUR managed identity name
SELECT * FROM pgaadauth_create_principal('titiler-db-access', false, false);

-- Verify user was created
SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'titiler-db-access';
```

**Expected Output:**
```
      rolname       | rolcanlogin
--------------------+-------------
 titiler-db-access  | t
(1 row)
```

### Step 3: Grant Permissions

#### Option A: Read-Only Access (Production Recommended)

**Use Case**: Public-facing API, tile serving only

```sql
-- Grant read permissions on pgstac schema
GRANT USAGE ON SCHEMA pgstac TO "titiler-db-access";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-access";
GRANT SELECT ON ALL SEQUENCES IN SCHEMA pgstac TO "titiler-db-access";

-- Future-proof: Grant SELECT on future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
GRANT SELECT ON TABLES TO "titiler-db-access";

-- OR use pgSTAC's built-in read-only role
GRANT pgstac_read TO "titiler-db-access";
```

**What This Enables:**
- ✅ Tile serving: `/searches/{search_id}/tiles/{z}/{x}/{y}`
- ✅ Collection info: `/collections`
- ✅ Statistics endpoints
- ✅ Read pre-registered searches from `pgstac.searches`

**What This Blocks:**
- ❌ `/searches/register` endpoint (cannot write to `pgstac.searches`)
- ❌ Modifying STAC items or collections

#### Option B: Read-Write Access (Admin/Internal APIs)

**Use Case**: Internal tools, search registration service

```sql
-- Grant read permissions (same as read-only)
GRANT USAGE ON SCHEMA pgstac TO "titiler-db-access";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-access";

-- Grant write permissions on searches table
GRANT INSERT, UPDATE, DELETE ON pgstac.searches TO "titiler-db-access";

-- Grant usage on sequences (for auto-increment IDs)
GRANT USAGE ON ALL SEQUENCES IN SCHEMA pgstac TO "titiler-db-access";

-- OR use broader pgSTAC role
GRANT pgstac_ingest TO "titiler-db-access";
```

**What This Adds:**
- ✅ `/searches/register` endpoint (create search queries)
- ✅ Dynamic mosaic generation

### Step 4: Verify Permissions

```sql
-- Check granted permissions
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'titiler-db-access'
  AND table_schema = 'pgstac'
ORDER BY table_name, privilege_type;
```

**Example Read-Write Output:**
```
      grantee       | table_name | privilege_type
--------------------+------------+----------------
 titiler-db-access  | collections| SELECT
 titiler-db-access  | items      | SELECT
 titiler-db-access  | searches   | SELECT
 titiler-db-access  | searches   | INSERT
 titiler-db-access  | searches   | UPDATE
 titiler-db-access  | searches   | DELETE
```

### Step 5: Test Token Acquisition (Optional)

Test that the managed identity can acquire PostgreSQL tokens:

```python
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
print(f"Token acquired: {token.token[:20]}...")
print(f"Expires at: {token.expires_on}")
```

### PostgreSQL Firewall Rules

Ensure the web app can reach PostgreSQL:

```bash
# Allow Azure services
az postgres flexible-server firewall-rule create \
  --resource-group your-rg \
  --name your-server \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

# Or add specific outbound IPs from App Service
az webapp show \
  --name your-webapp \
  --resource-group your-rg \
  --query outboundIpAddresses -o tsv
```

---

## 📦 Part 4: Deployment Workflow

### Phase 1: Build and Push Docker Image

```bash
# Set variables
ACR_NAME="your-acr"
IMAGE_NAME="titiler-pgstac"
VERSION="1.0.0"

# Build for linux/amd64 (required for Azure App Service)
docker build --platform linux/amd64 \
  -t $ACR_NAME.azurecr.io/$IMAGE_NAME:$VERSION \
  -t $ACR_NAME.azurecr.io/$IMAGE_NAME:latest \
  -f Dockerfile .

# Login to ACR
az acr login --name $ACR_NAME

# Push images
docker push $ACR_NAME.azurecr.io/$IMAGE_NAME:$VERSION
docker push $ACR_NAME.azurecr.io/$IMAGE_NAME:latest
```

### Phase 2: Create/Configure App Service

```bash
# Set variables
RESOURCE_GROUP="your-rg"
APP_SERVICE_PLAN="titiler-plan"
APP_NAME="titiler-api"
STORAGE_ACCOUNT="your-storage"

# Create App Service Plan (if not exists)
az appservice plan create \
  --name $APP_SERVICE_PLAN \
  --resource-group $RESOURCE_GROUP \
  --is-linux \
  --sku B2

# Create Web App
az webapp create \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --plan $APP_SERVICE_PLAN \
  --deployment-container-image-name $ACR_NAME.azurecr.io/$IMAGE_NAME:latest

# Enable SYSTEM-assigned managed identity (for Storage)
az webapp identity assign \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP

# Assign USER-assigned managed identity (for PostgreSQL)
az webapp identity assign \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --identities /subscriptions/YOUR_SUB_ID/resourcegroups/$RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/titiler-db-access
```

### Phase 3: Configure RBAC

```bash
# Get system-assigned MI principal ID
SYSTEM_MI_PRINCIPAL=$(az webapp identity show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

# Grant Storage Blob Data Reader
az role assignment create \
  --assignee $SYSTEM_MI_PRINCIPAL \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT

echo "⏳ Waiting 3 minutes for RBAC propagation..."
sleep 180
```

### Phase 4: Configure Environment Variables

**For Managed Identity Mode (Production):**

```bash
az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    POSTGRES_AUTH_MODE="managed_identity" \
    POSTGRES_HOST="your-server.postgres.database.azure.com" \
    POSTGRES_DB="geopgflex" \
    POSTGRES_USER="titiler-db-access" \
    POSTGRES_PORT="5432" \
    USE_AZURE_AUTH="true" \
    AZURE_STORAGE_ACCOUNT="$STORAGE_ACCOUNT" \
    LOCAL_MODE="false" \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff" \
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR" \
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES" \
    GDAL_HTTP_MULTIPLEX="YES" \
    GDAL_HTTP_VERSION="2" \
    VSI_CACHE="TRUE" \
    VSI_CACHE_SIZE="536870912"
```

**For Password Mode (Development/Fallback):**

```bash
az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    POSTGRES_AUTH_MODE="password" \
    POSTGRES_HOST="your-server.postgres.database.azure.com" \
    POSTGRES_DB="geopgflex" \
    POSTGRES_USER="your_user" \
    POSTGRES_PORT="5432" \
    POSTGRES_PASSWORD="your_password" \
    USE_AZURE_AUTH="true" \
    AZURE_STORAGE_ACCOUNT="$STORAGE_ACCOUNT" \
    LOCAL_MODE="false"
```

### Phase 5: Configure Container Registry Access

```bash
# Enable ACR admin user
az acr update --name $ACR_NAME --admin-enabled true

# Get credentials
ACR_USERNAME=$(az acr credential show --name $ACR_NAME --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)

# Configure App Service to pull from ACR
az webapp config container set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --docker-custom-image-name $ACR_NAME.azurecr.io/$IMAGE_NAME:latest \
  --docker-registry-server-url https://$ACR_NAME.azurecr.io \
  --docker-registry-server-user $ACR_USERNAME \
  --docker-registry-server-password $ACR_PASSWORD
```

### Phase 6: Restart and Monitor

```bash
# Restart the web app
az webapp restart --name $APP_NAME --resource-group $RESOURCE_GROUP

# Wait for startup
echo "⏳ Waiting 30 seconds for app to start..."
sleep 30

# Stream logs
az webapp log tail --name $APP_NAME --resource-group $RESOURCE_GROUP
```

**Look for Success Messages:**

```
============================================================
TiTiler-pgSTAC with Azure OAuth Auth - Starting up
============================================================
PostgreSQL auth mode: managed_identity
🔐 PostgreSQL Authentication Mode: Managed Identity
✅ PostgreSQL OAuth token successfully acquired
✓ Built DATABASE_URL with managed_identity authentication
✓ Database connection established
✓ Storage OAuth authentication initialized successfully
✅ TiTiler-pgSTAC startup complete
============================================================
```

### Phase 7: Verify Deployment

```bash
# Get app URL
APP_URL=$(az webapp show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query defaultHostName -o tsv)

# Health check
curl https://$APP_URL/healthz | jq

# Test COG info endpoint
curl "https://$APP_URL/cog/info?url=%2Fvsiaz%2Fyour-container%2Ffile.tif" | jq

# Test tile rendering
curl "https://$APP_URL/cog/tiles/WebMercatorQuad/14/11454/6143.png?url=%2Fvsiaz%2Fyour-container%2Ffile.tif" -o test_tile.png

# Test search registration (if write permissions granted)
curl -X POST "https://$APP_URL/searches/register" \
  -H "Content-Type: application/json" \
  -d '{"collections":["your-collection"],"limit":10}' | jq

# Open API documentation
open "https://$APP_URL/docs"

# Open interactive map viewer
open "https://$APP_URL/cog/WebMercatorQuad/map.html?url=%2Fvsiaz%2Fyour-container%2Ffile.tif"
```

---

## 🔧 Part 5: Troubleshooting

### Issue: "Failed to acquire PostgreSQL OAuth token"

**Check Managed Identity:**
```bash
az webapp identity show --name $APP_NAME --resource-group $RESOURCE_GROUP
```

Should show both system and user-assigned identities.

**Test Token Acquisition Locally:**
```bash
az account get-access-token --resource https://ossrdbms-aad.database.windows.net
```

### Issue: "Role 'your-mi-name' does not exist"

**Verify PostgreSQL user exists:**
```bash
PGPASSWORD='admin-password' psql \
  -h your-server.postgres.database.azure.com \
  -U admin_user \
  -d your_database \
  -c "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'titiler-db-access';"
```

**Recreate if missing:**
```sql
SELECT * FROM pgaadauth_create_principal('titiler-db-access', false, false);
```

### Issue: "HTTP 403 Forbidden" on Storage

**Check RBAC assignment:**
```bash
# List role assignments for the system-assigned MI
az role assignment list --assignee $SYSTEM_MI_PRINCIPAL --all
```

**Verify propagation (wait 5-10 minutes):**
```bash
# Force restart after RBAC changes
az webapp restart --name $APP_NAME --resource-group $RESOURCE_GROUP
```

### Issue: "Connection timeout" to PostgreSQL

**Check firewall rules:**
```bash
az postgres flexible-server firewall-rule list \
  --resource-group $RESOURCE_GROUP \
  --name your-server -o table
```

**Add App Service outbound IPs:**
```bash
OUTBOUND_IPS=$(az webapp show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query outboundIpAddresses -o tsv)

echo "Outbound IPs: $OUTBOUND_IPS"
```

### Issue: "Permission denied for table X"

**Check granted permissions:**
```sql
SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'titiler-db-access'
  AND table_schema = 'pgstac'
ORDER BY table_name;
```

**Grant missing permissions:**
```sql
-- For read-only
GRANT pgstac_read TO "titiler-db-access";

-- For read-write
GRANT INSERT, UPDATE, DELETE ON pgstac.searches TO "titiler-db-access";
```

---

## 📊 Part 6: Architecture Summary

### Authentication Flow

```
┌─────────────────────────────────────────────────────────┐
│ HTTP Request → Web App                                  │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ AzureAuthMiddleware (per-request)                       │
│  ↓ Get Storage OAuth token                              │
│  ↓ DefaultAzureCredential (System-Assigned MI)          │
│  ↓ Set GDAL environment variables                       │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ FastAPI Endpoint Handler                                │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ PostgreSQL Connection (startup)                         │
│  ↓ Get PostgreSQL OAuth token                           │
│  ↓ DefaultAzureCredential (User-Assigned MI)            │
│  ↓ Build DATABASE_URL with token as password            │
│  ↓ Connect to database                                  │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ GDAL/Rasterio reads /vsiaz/ COG files                   │
│  ↓ Uses storage OAuth token from middleware             │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Response → User                                          │
└─────────────────────────────────────────────────────────┘
```

### Managed Identity Responsibilities

| Component | Identity Type | Scope | Purpose |
|-----------|--------------|-------|---------|
| **Storage Access** | System-Assigned | Storage account | GDAL `/vsiaz/` authentication |
| **PostgreSQL Access** | User-Assigned | PostgreSQL server | Database connection |

### Token Lifecycle

| Token | Acquired When | Validity | Refresh Strategy |
|-------|--------------|----------|------------------|
| **Storage OAuth** | Per-request (cached) | ~1 hour | Middleware checks cache, refreshes if needed |
| **PostgreSQL OAuth** | Once at startup | ~1 hour | App restarts naturally refresh (Azure App Service cycles) |

---

## 🎯 Part 7: Production Checklist

### Security
- [ ] System-assigned MI enabled on web app
- [ ] User-assigned MI created and assigned to web app
- [ ] Storage RBAC role assigned (Storage Blob Data Reader)
- [ ] PostgreSQL user created matching MI name
- [ ] PostgreSQL permissions granted (read-only recommended)
- [ ] No passwords in environment variables (if using MI mode)
- [ ] HTTPS enforced on App Service

### Configuration
- [ ] Environment variables set in App Service
- [ ] `POSTGRES_AUTH_MODE` configured correctly
- [ ] `LOCAL_MODE=false` for production
- [ ] GDAL optimizations configured
- [ ] Container registry credentials configured

### Infrastructure
- [ ] PostgreSQL firewall allows Azure services
- [ ] App Service plan sized appropriately (B2 or higher)
- [ ] Docker image pushed to ACR
- [ ] Continuous deployment enabled (optional)

### Testing
- [ ] Health endpoint returns healthy
- [ ] Direct COG access works (`/cog/info`)
- [ ] Tile rendering works (`/cog/tiles/...`)
- [ ] Search registration works (if write permissions granted)
- [ ] Interactive map viewer loads
- [ ] No 403 errors in logs

### Monitoring
- [ ] Application Insights enabled (optional)
- [ ] Log streaming tested
- [ ] Alerts configured for failures
- [ ] Auto-scaling rules configured (optional)

---

## 📝 Part 8: Rollback Plan

If deployment fails, rollback to password authentication:

```bash
# Switch to password mode
az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    POSTGRES_AUTH_MODE="password" \
    POSTGRES_PASSWORD="your-password"

# Restart app
az webapp restart --name $APP_NAME --resource-group $RESOURCE_GROUP
```

Or rollback to previous Docker image:

```bash
# Use previous image version
az webapp config container set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --docker-custom-image-name $ACR_NAME.azurecr.io/$IMAGE_NAME:previous-version

# Restart
az webapp restart --name $APP_NAME --resource-group $RESOURCE_GROUP
```

---

## 🚀 Next Steps

1. **Custom Domain**: Configure custom domain and SSL certificate
2. **CI/CD**: Set up GitHub Actions or Azure DevOps pipeline
3. **Monitoring**: Enable Application Insights for detailed telemetry
4. **Scaling**: Configure auto-scaling rules based on CPU/memory
5. **Caching**: Add CDN for tile caching (optional)
6. **Documentation**: Document specific corporate security requirements

---

**Status**: ✅ Ready for Corporate Azure Deployment
**Security**: ✅ Passwordless, Zero-Trust Architecture
**Scalability**: ✅ Production-Grade with RBAC
**Maintainability**: ✅ Comprehensive Logging and Monitoring
