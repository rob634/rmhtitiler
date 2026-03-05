# New Tenant Deployment Guide

**Purpose**: Deploy TiTiler-pgSTAC to a completely new Azure tenant
**Prerequisite**: Azure subscription with Owner or Contributor access

---

## Quick Start Checklist

```
[ ] 1. Create Azure resources (Resource Group, Storage, PostgreSQL, ACR, App Service)
[ ] 2. Configure pgSTAC extension in PostgreSQL
[ ] 3. Create and assign Managed Identities
[ ] 4. Configure RBAC permissions
[ ] 5. Build and push Docker image
[ ] 6. Configure App Service environment variables
[ ] 7. Deploy and verify
```

---

## Part 1: Environment Variables Reference

All environment variables are consolidated in `.env.template`. Copy it to `.env` for local development.

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `POSTGRES_AUTH_MODE` | Auth mode: `managed_identity`, `key_vault`, `password` | `managed_identity` |
| `POSTGRES_HOST` | PostgreSQL server hostname | `myserver.postgres.database.azure.com` |
| `POSTGRES_DB` | Database name | `geopgflex` |
| `POSTGRES_USER` | Database username (must match MI name for MI auth) | `titiler-db-identity` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `USE_AZURE_AUTH` | Enable Azure Storage OAuth | `true` |
| `AZURE_STORAGE_ACCOUNT` | Storage account name | `mystorageaccount` |
| `LOCAL_MODE` | `true` for Azure CLI auth, `false` for Managed Identity | `false` |

### Conditional Variables

| Variable | When Required | Description |
|----------|---------------|-------------|
| `POSTGRES_PASSWORD` | `POSTGRES_AUTH_MODE=password` | Database password |
| `KEY_VAULT_NAME` | `POSTGRES_AUTH_MODE=key_vault` | Key Vault name |
| `KEY_VAULT_SECRET_NAME` | `POSTGRES_AUTH_MODE=key_vault` | Secret name (default: `postgres-password`) |

### GDAL Optimization Variables (Recommended)

```bash
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES
GDAL_HTTP_MULTIPLEX=YES
GDAL_HTTP_VERSION=2
VSI_CACHE=TRUE
VSI_CACHE_SIZE=536870912
```

---

## Part 2: Azure Resource Creation

### Step 2.1: Set Variables

```bash
# Customize these for your tenant
SUBSCRIPTION_ID="your-subscription-id"
RESOURCE_GROUP="titiler-rg"
LOCATION="eastus"
STORAGE_ACCOUNT="mystorageaccount"      # Must be globally unique, lowercase
POSTGRES_SERVER="mypostgres"            # Must be globally unique
POSTGRES_ADMIN_USER="pgadmin"
POSTGRES_ADMIN_PASSWORD="YourSecurePassword123!"
POSTGRES_DB="geopgflex"
ACR_NAME="myacr"                        # Must be globally unique
APP_SERVICE_PLAN="titiler-plan"
APP_NAME="titiler-api"                  # Must be globally unique
USER_MI_NAME="titiler-db-identity"      # User-assigned managed identity name
```

### Step 2.2: Create Resource Group

```bash
az group create \
  --name $RESOURCE_GROUP \
  --location $LOCATION
```

### Step 2.3: Create Storage Account

```bash
# Create storage account
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false

# Create container for COG files
az storage container create \
  --name silver-cogs \
  --account-name $STORAGE_ACCOUNT \
  --auth-mode login
```

### Step 2.4: Create PostgreSQL Flexible Server

```bash
# Create PostgreSQL server
az postgres flexible-server create \
  --name $POSTGRES_SERVER \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --admin-user $POSTGRES_ADMIN_USER \
  --admin-password "$POSTGRES_ADMIN_PASSWORD" \
  --sku-name Standard_B2s \
  --tier Burstable \
  --storage-size 32 \
  --version 15

# Create database
az postgres flexible-server db create \
  --resource-group $RESOURCE_GROUP \
  --server-name $POSTGRES_SERVER \
  --database-name $POSTGRES_DB

# Allow Azure services (required for App Service access)
az postgres flexible-server firewall-rule create \
  --resource-group $RESOURCE_GROUP \
  --name $POSTGRES_SERVER \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

### Step 2.5: Install pgSTAC Extension

Connect to PostgreSQL and install pgSTAC:

```bash
PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" psql \
  -h ${POSTGRES_SERVER}.postgres.database.azure.com \
  -U $POSTGRES_ADMIN_USER \
  -d $POSTGRES_DB \
  -c "CREATE EXTENSION IF NOT EXISTS postgis;"

PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" psql \
  -h ${POSTGRES_SERVER}.postgres.database.azure.com \
  -U $POSTGRES_ADMIN_USER \
  -d $POSTGRES_DB \
  -c "CREATE EXTENSION IF NOT EXISTS pgstac;"
```

### Step 2.6: Create Container Registry

```bash
az acr create \
  --name $ACR_NAME \
  --resource-group $RESOURCE_GROUP \
  --sku Basic \
  --admin-enabled true
```

### Step 2.7: Create App Service

```bash
# Create App Service Plan
az appservice plan create \
  --name $APP_SERVICE_PLAN \
  --resource-group $RESOURCE_GROUP \
  --is-linux \
  --sku B2

# Create Web App (placeholder image, will update later)
az webapp create \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --plan $APP_SERVICE_PLAN \
  --deployment-container-image-name mcr.microsoft.com/appsvc/staticsite:latest
```

---

## Part 3: Managed Identity Setup

### Step 3.1: Enable System-Assigned MI (for Storage)

```bash
az webapp identity assign \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP

# Get principal ID
SYSTEM_MI_PRINCIPAL=$(az webapp identity show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

echo "System-Assigned MI Principal ID: $SYSTEM_MI_PRINCIPAL"
```

### Step 3.2: Create User-Assigned MI (for PostgreSQL)

```bash
# Create user-assigned managed identity
az identity create \
  --name $USER_MI_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

# Get IDs
USER_MI_CLIENT_ID=$(az identity show \
  --name $USER_MI_NAME \
  --resource-group $RESOURCE_GROUP \
  --query clientId -o tsv)

USER_MI_PRINCIPAL_ID=$(az identity show \
  --name $USER_MI_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

USER_MI_RESOURCE_ID=$(az identity show \
  --name $USER_MI_NAME \
  --resource-group $RESOURCE_GROUP \
  --query id -o tsv)

echo "User-Assigned MI Client ID: $USER_MI_CLIENT_ID"
echo "User-Assigned MI Principal ID: $USER_MI_PRINCIPAL_ID"
```

### Step 3.3: Assign User MI to App Service

```bash
az webapp identity assign \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --identities $USER_MI_RESOURCE_ID
```

---

## Part 4: RBAC Configuration

### Step 4.1: Storage Blob Data Reader

Grant the **system-assigned MI** access to read blobs:

```bash
az role assignment create \
  --assignee $SYSTEM_MI_PRINCIPAL \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT
```

### Step 4.2: PostgreSQL User for Managed Identity

Connect to PostgreSQL as admin and create the user:

```bash
PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" psql \
  -h ${POSTGRES_SERVER}.postgres.database.azure.com \
  -U $POSTGRES_ADMIN_USER \
  -d $POSTGRES_DB
```

Run in psql:

```sql
-- Enable Entra ID authentication
SET aad_validate_oids_in_tenant = off;

-- Create PostgreSQL user matching the managed identity name
-- IMPORTANT: Name MUST match USER_MI_NAME exactly
SELECT * FROM pgaadauth_create_principal('titiler-db-identity', false, false);

-- Grant permissions on pgSTAC schema
GRANT USAGE ON SCHEMA pgstac TO "titiler-db-identity";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-identity";
GRANT SELECT ON ALL SEQUENCES IN SCHEMA pgstac TO "titiler-db-identity";

-- For search registration (optional - enables /searches/register endpoint)
GRANT INSERT, UPDATE, DELETE ON pgstac.searches TO "titiler-db-identity";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA pgstac TO "titiler-db-identity";

-- Future-proof
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT ON TABLES TO "titiler-db-identity";

-- Verify
SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'titiler-db-identity';
```

### Step 4.3: Wait for RBAC Propagation

```bash
echo "Waiting 3 minutes for RBAC propagation..."
sleep 180
```

---

## Part 5: Build and Deploy

### Step 5.1: Build Docker Image

```bash
# Login to ACR
az acr login --name $ACR_NAME

# Build for linux/amd64
docker build --platform linux/amd64 \
  -t ${ACR_NAME}.azurecr.io/titiler-pgstac:1.0.0 \
  -t ${ACR_NAME}.azurecr.io/titiler-pgstac:latest \
  -f Dockerfile .

# Push
docker push ${ACR_NAME}.azurecr.io/titiler-pgstac:1.0.0
docker push ${ACR_NAME}.azurecr.io/titiler-pgstac:latest
```

### Step 5.2: Configure ACR Access

```bash
# Get ACR credentials
ACR_USERNAME=$(az acr credential show --name $ACR_NAME --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)

# Configure App Service to pull from ACR
az webapp config container set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --docker-custom-image-name ${ACR_NAME}.azurecr.io/titiler-pgstac:latest \
  --docker-registry-server-url https://${ACR_NAME}.azurecr.io \
  --docker-registry-server-user $ACR_USERNAME \
  --docker-registry-server-password "$ACR_PASSWORD"
```

### Step 5.3: Configure Environment Variables

```bash
az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    POSTGRES_AUTH_MODE="managed_identity" \
    POSTGRES_HOST="${POSTGRES_SERVER}.postgres.database.azure.com" \
    POSTGRES_DB="$POSTGRES_DB" \
    POSTGRES_USER="$USER_MI_NAME" \
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

### Step 5.4: Restart and Verify

```bash
# Restart
az webapp restart --name $APP_NAME --resource-group $RESOURCE_GROUP

# Wait for startup
sleep 30

# Get URL
APP_URL=$(az webapp show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query defaultHostName -o tsv)

echo "App URL: https://$APP_URL"

# Health check
curl https://$APP_URL/healthz | jq
```

---

## Part 6: Verification Tests

### Test 1: Health Endpoint

```bash
curl https://$APP_URL/healthz | jq
```

Expected response:
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "local_mode": false,
  "auth_type": "OAuth Bearer Token",
  "storage_account": "mystorageaccount",
  "token_status": "active",
  "database_status": "connected"
}
```

### Test 2: COG Info (after uploading a test file)

```bash
# Upload a test COG first
az storage blob upload \
  --account-name $STORAGE_ACCOUNT \
  --container-name silver-cogs \
  --name test.tif \
  --file /path/to/your/test.tif \
  --auth-mode login

# Test COG info endpoint
curl "https://$APP_URL/cog/info?url=/vsiaz/silver-cogs/test.tif" | jq
```

### Test 3: Tile Rendering

```bash
curl "https://$APP_URL/cog/tiles/WebMercatorQuad/14/11454/6143.png?url=/vsiaz/silver-cogs/test.tif" -o test_tile.png
```

### Test 4: Interactive Map

Open in browser:
```
https://$APP_URL/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/test.tif
```

---

## Part 7: Troubleshooting

### View Logs

```bash
az webapp log tail --name $APP_NAME --resource-group $RESOURCE_GROUP
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Failed to acquire PostgreSQL OAuth token" | MI not assigned or user not created | Verify `az webapp identity show` and PostgreSQL user exists |
| "Role 'xxx' does not exist" | PostgreSQL user name doesn't match MI name | Recreate user with exact MI name |
| "HTTP 403" on storage | RBAC not propagated or wrong scope | Wait 5-10 mins, verify role assignment scope |
| "Connection timeout" | Firewall rules | Add App Service IPs or allow Azure services |

### Reset to Password Mode (Fallback)

```bash
az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    POSTGRES_AUTH_MODE="password" \
    POSTGRES_PASSWORD="$POSTGRES_ADMIN_PASSWORD" \
    POSTGRES_USER="$POSTGRES_ADMIN_USER"

az webapp restart --name $APP_NAME --resource-group $RESOURCE_GROUP
```

---

## Part 8: Files Modified for New Tenant

When deploying to a new tenant, you only need to configure environment variables. The codebase is tenant-agnostic.

**DO NOT modify these files** - they contain no hardcoded values:
- `custom_pgstac_main.py` - Application code
- `Dockerfile` - Production image
- `.env.template` - Configuration template

**Template files** (copy and customize):
- `.env.template` → `.env` (for local development)
- `docker-compose.yml.template` → `docker-compose.yml` (for local Docker)

---

## Hardcoded Values Audit

The following files in this repository contain hardcoded Azure resource names from the original development environment. These are for **documentation/example purposes only** and should be ignored when deploying to a new tenant:

| File | Contains | Purpose |
|------|----------|---------|
| `README.md` | URLs, resource names | Usage examples |
| `ONBOARDING.md` | Resource names | Developer onboarding |
| `docker-compose.yml` | Connection string | Local dev (git-ignored) |
| `.env.example` | Storage account | Example values |
| `.env.test` | All config | Test environment |
| `scripts/*.py` | Default values | Testing scripts |
| `docs/*` | Various | Implementation history |

**Production deployments** use only environment variables configured in Azure App Service - no hardcoded values.

---

## Support

- **Documentation**: See `QA_DEPLOYMENT.md` for detailed architecture
- **Issues**: Check troubleshooting section above
- **Logs**: Use `az webapp log tail` for real-time debugging
