# TiTiler-pgSTAC QA Deployment - Resume Guide

**Created**: December 2, 2025
**Updated**: December 2, 2025
**Status**: ✅ Docker image pushed to ACR successfully
**Next Step**: Request App Service creation from Azure admin

---

## 📋 Project Overview

This is a custom TiTiler-pgSTAC tile server with Azure Managed Identity OAuth authentication. It serves map tiles from Cloud Optimized GeoTIFF (COG) files stored in Azure Blob Storage, with metadata stored in a PostgreSQL pgSTAC database.

---

## ✅ Verified Azure Resources

| Resource Type | Name | Details |
|---------------|------|---------|
| **Resource Group** | `itses-gddatahub-qa-rg` | Location: **eastus** |
| **Container Registry** | `itsesgddatahubacrqa` | Login: `itsesgddatahubacrqa.azurecr.io` |
| **Storage Account** | `itsesgddataintqastrg` | StorageV2, eastus |
| **PostgreSQL Server** | `itses-gddatahub-pgsqlsvr-qa` | FQDN: `itses-gddatahub-pgsqlsvr-qa.postgres.database.azure.com`, State: Ready |
| **Database** | `geoapp` | **TO BE CREATED** with pgSTAC schema |
| **User-Assigned MI** | `migeoetldbreaderqa` | ClientId: `7704971b-b7fb-4951-9120-8471281a66fc`, PrincipalId: `3e2851b3-0215-442a-986f-18d4ba768cfa` |
| **ACR Images** | `titiler-pgstac` | Tags: `v1.0.0`, `latest` ✅ |
| **App Service** | *(to be created)* | Request from Azure admin |

---

## ✅ Completed: Docker Image Push to ACR

The image was successfully built and pushed on December 2, 2025.

### Verified in ACR:
```
az acr repository show-tags --name itsesgddatahubacrqa --repository titiler-pgstac --output table
Result
--------
latest
v1.0.0
```

---

## 🐳 Docker Build & Push Instructions (What Worked)

Due to corporate proxy issues, `az acr build` (cloud build) fails with permission errors. The working approach uses local Docker build + push from WSL.

### Prerequisites

1. **Use WSL** (corporate proxy issues with native Windows Azure CLI)
2. **Configure Docker daemon for insecure registry** (corporate proxy intercepts TLS):
   
   Edit `/etc/docker/daemon.json`:
   ```json
   {
     "insecure-registries": ["itsesgddatahubacrqa.azurecr.io"]
   }
   ```
   
   Then restart Docker:
   ```bash
   sudo systemctl restart docker
   ```

3. **Set Azure CLI SSL bypass**:
   ```bash
   export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1
   ```

### Step 1: Login to ACR

```bash
# Login to Azure (if needed)
az login

# Login to ACR using Azure CLI token
az acr login --name itsesgddatahubacrqa
```

Expected output: `Login Succeeded`

### Step 2: Build Docker Image Locally

```bash
# Navigate to project directory
cd /mnt/c/Users/WB489446/'OneDrive - WBG'/python_builds/rmhtitiler

# Build for linux/amd64 platform with ACR tags
docker build \
  --platform linux/amd64 \
  -t itsesgddatahubacrqa.azurecr.io/titiler-pgstac:v1.0.0 \
  -t itsesgddatahubacrqa.azurecr.io/titiler-pgstac:latest \
  -f Dockerfile .
```

### Step 3: Push to ACR

```bash
# Push both tags
docker push itsesgddatahubacrqa.azurecr.io/titiler-pgstac:v1.0.0
docker push itsesgddatahubacrqa.azurecr.io/titiler-pgstac:latest
```

### Step 4: Verify

```bash
az acr repository show-tags --name itsesgddatahubacrqa --repository titiler-pgstac --output table
```

---

## ⚠️ Why `az acr build` Failed

The `az acr build` command requires `Microsoft.ContainerRegistry/registries/listBuildSourceUploadUrl/action` permission, which is NOT included in the `AcrPush` role. This requires `Contributor` or custom role with that action.

**Workaround**: Use local Docker build + push (documented above), which only requires `AcrPush` role.

---

## 🛡️ Request for Azure Admin

The following App Service resources need to be created by an Azure admin since the current user doesn't have permission to create web apps.

### Step 1: Create App Service Plan

```bash
az appservice plan create \
  --name titiler-pgstac-plan \
  --resource-group itses-gddatahub-qa-rg \
  --is-linux \
  --sku B2 \
  --location eastus
```

### Step 2: Create Web App

```bash
az webapp create \
  --name titiler-pgstac-qa \
  --resource-group itses-gddatahub-qa-rg \
  --plan titiler-pgstac-plan \
  --deployment-container-image-name itsesgddatahubacrqa.azurecr.io/titiler-pgstac:latest
```

### Step 3: Enable System-Assigned Managed Identity (for Storage)

```bash
az webapp identity assign \
  --name titiler-pgstac-qa \
  --resource-group itses-gddatahub-qa-rg
```

### Step 4: Assign User-Assigned Managed Identity (for PostgreSQL)

```bash
az webapp identity assign \
  --name titiler-pgstac-qa \
  --resource-group itses-gddatahub-qa-rg \
  --identities /subscriptions/f2bde2ed-4d2d-416d-be06-bb76bb62dc85/resourcegroups/itses-gddatahub-qa-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/migeoetldbreaderqa
```

### Step 5: Grant Storage RBAC to System-Assigned MI

```bash
# Get system-assigned MI principal ID
SYSTEM_MI_PRINCIPAL=$(az webapp identity show \
  --name titiler-pgstac-qa \
  --resource-group itses-gddatahub-qa-rg \
  --query principalId -o tsv)

# Grant Storage Blob Data Reader
az role assignment create \
  --assignee $SYSTEM_MI_PRINCIPAL \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/f2bde2ed-4d2d-416d-be06-bb76bb62dc85/resourceGroups/itses-gddatahub-qa-rg/providers/Microsoft.Storage/storageAccounts/itsesgddataintqastrg

echo "⏳ Wait 3-5 minutes for RBAC propagation..."
```

### Step 6: Configure Environment Variables

```bash
az webapp config appsettings set \
  --name titiler-pgstac-qa \
  --resource-group itses-gddatahub-qa-rg \
  --settings \
    POSTGRES_AUTH_MODE="managed_identity" \
    POSTGRES_HOST="itses-gddatahub-pgsqlsvr-qa.postgres.database.azure.com" \
    POSTGRES_DB="geoapp" \
    POSTGRES_USER="migeoetldbreaderqa" \
    POSTGRES_PORT="5432" \
    USE_AZURE_AUTH="true" \
    AZURE_STORAGE_ACCOUNT="itsesgddataintqastrg" \
    LOCAL_MODE="false" \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff" \
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR" \
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES" \
    GDAL_HTTP_MULTIPLEX="YES" \
    GDAL_HTTP_VERSION="2" \
    VSI_CACHE="TRUE" \
    VSI_CACHE_SIZE="536870912"
```

### Step 7: Configure ACR Access for App Service

```bash
# Enable ACR admin (if not already)
az acr update --name itsesgddatahubacrqa --admin-enabled true

# Get ACR credentials
ACR_USERNAME=$(az acr credential show --name itsesgddatahubacrqa --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name itsesgddatahubacrqa --query passwords[0].value -o tsv)

# Configure App Service to pull from ACR
az webapp config container set \
  --name titiler-pgstac-qa \
  --resource-group itses-gddatahub-qa-rg \
  --docker-custom-image-name itsesgddatahubacrqa.azurecr.io/titiler-pgstac:latest \
  --docker-registry-server-url https://itsesgddatahubacrqa.azurecr.io \
  --docker-registry-server-user $ACR_USERNAME \
  --docker-registry-server-password $ACR_PASSWORD
```

### Step 8: Restart and Verify

```bash
# Restart
az webapp restart --name titiler-pgstac-qa --resource-group itses-gddatahub-qa-rg

# Wait for startup
sleep 30

# Get URL
APP_URL=$(az webapp show \
  --name titiler-pgstac-qa \
  --resource-group itses-gddatahub-qa-rg \
  --query defaultHostName -o tsv)

echo "App URL: https://$APP_URL"

# Health check
curl https://$APP_URL/healthz

# Stream logs
az webapp log tail --name titiler-pgstac-qa --resource-group itses-gddatahub-qa-rg
```

---

## 🗄️ PostgreSQL Setup (Separate Task)

The `geoapp` database with pgSTAC schema needs to be created. Once created:

### Create PostgreSQL User for Managed Identity

Connect as admin and run:

```sql
-- Enable Entra ID authentication
SET aad_validate_oids_in_tenant = off;

-- Create user matching managed identity name
SELECT * FROM pgaadauth_create_principal('migeoetldbreaderqa', false, false);

-- Grant permissions (read-write for search registration)
GRANT USAGE ON SCHEMA pgstac TO "migeoetldbreaderqa";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "migeoetldbreaderqa";
GRANT INSERT, UPDATE, DELETE ON pgstac.searches TO "migeoetldbreaderqa";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA pgstac TO "migeoetldbreaderqa";

-- Verify
SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'migeoetldbreaderqa';
```

---

## 📁 Key Files in This Project

| File | Purpose |
|------|---------|
| `custom_pgstac_main.py` | Main FastAPI application with OAuth middleware |
| `Dockerfile` | Production Docker image (Managed Identity) |
| `Dockerfile.local` | Local development image (Azure CLI) |
| `docker-compose.yml` | Local development setup |
| `QA_DEPLOYMENT.md` | Detailed deployment guide |
| `ONBOARDING.md` | Project overview for new developers |

---

## 🔧 Troubleshooting

### Check Permissions
```bash
az role assignment list \
  --assignee edff3959-ed21-4975-8b8a-013d8319c569 \
  --scope /subscriptions/f2bde2ed-4d2d-416d-be06-bb76bb62dc85/resourceGroups/itses-gddatahub-qa-rg/providers/Microsoft.ContainerRegistry/registries/itsesgddatahubacrqa \
  -o table
```

### Verify ACR Image
```bash
az acr repository list --name itsesgddatahubacrqa -o table
az acr repository show-tags --name itsesgddatahubacrqa --repository titiler-pgstac -o table
```

### Check App Service Logs
```bash
az webapp log tail --name titiler-pgstac-qa --resource-group itses-gddatahub-qa-rg
```

---

## 📞 Resume Instructions for Claude

When resuming this deployment, tell Claude:

> "Please read claude.md and continue the TiTiler-pgSTAC QA deployment. The App Service has been created."

Claude will then:
1. Verify the App Service exists
2. Verify managed identities are assigned
3. Verify environment variables are set
4. Test the health endpoint
5. Help troubleshoot any issues

---

## 📝 Deployment Status Summary

| Step | Status | Notes |
|------|--------|-------|
| Azure Resources Verified | ✅ Complete | RG, ACR, Storage, PostgreSQL, MI confirmed |
| Docker Image Built | ✅ Complete | Built locally in WSL |
| Image Pushed to ACR | ✅ Complete | `v1.0.0` and `latest` tags |
| App Service Created | ⏳ Pending | Requires Azure admin |
| Managed Identities Assigned | ⏳ Pending | After App Service created |
| Environment Variables Set | ⏳ Pending | After App Service created |
| Database Created | ⏳ Pending | `geoapp` with pgSTAC schema |
| PostgreSQL User Created | ⏳ Pending | `migeoetldbreaderqa` Entra user |
| Deployment Verified | ⏳ Pending | Health check after all above complete |

---

**Last Updated**: December 2, 2025
**Subscription**: WBG AZ ITSOC QA PDMZ (`f2bde2ed-4d2d-416d-be06-bb76bb62dc85`)
