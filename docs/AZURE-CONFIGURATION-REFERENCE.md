# Azure Configuration Reference for TiTiler Deployment

**Purpose:** Complete reference of all Azure configurations needed for TiTiler deployment in a corporate environment.

**Date:** November 7, 2025
**Environment:** Production
**Deployment Type:** Docker Container on Azure App Service (Linux)

---

## 📋 Table of Contents

1. [Azure Container Registry (ACR) Configuration](#1-azure-container-registry-acr-configuration)
2. [Azure App Service Configuration](#2-azure-app-service-configuration)
3. [Managed Identity Configuration](#3-managed-identity-configuration)
4. [Storage Account Permissions](#4-storage-account-permissions)
5. [Application Settings (Environment Variables)](#5-application-settings-environment-variables)
6. [Container Configuration](#6-container-configuration)
7. [Complete Service Request Template](#7-complete-service-request-template)

---

## 1. Azure Container Registry (ACR) Configuration

### Resource Details
```
Resource Type: Container Registry
Name: rmhazureacr
Resource Group: rmhazure_rg
Location: East US
SKU: Basic
```

### Required Settings

**1.1 Admin User Access**
```
Setting: Admin User Enabled
Value: true
Reason: Required for App Service to authenticate and pull container images
```

**CLI Command:**
```bash
az acr update \
  --name rmhazureacr \
  --admin-enabled true
```

**Azure Portal Path:**
1. Navigate to: Azure Portal → Container Registry → rmhazureacr
2. Click: Settings → Access keys
3. Enable: Admin user

**Verification:**
```bash
az acr show --name rmhazureacr --query '{name:name,adminUserEnabled:adminUserEnabled}'
```

Expected Output:
```json
{
  "name": "rmhazureacr",
  "adminUserEnabled": true
}
```

### 1.2 Get ACR Credentials

**CLI Command:**
```bash
az acr credential show --name rmhazureacr
```

**Output Format:**
```json
{
  "passwords": [
    {
      "name": "password",
      "value": "<PRIMARY_PASSWORD>"
    },
    {
      "name": "password2",
      "value": "<SECONDARY_PASSWORD>"
    }
  ],
  "username": "rmhazureacr"
}
```

**Save These Values:**
- Username: `rmhazureacr`
- Password: `<PRIMARY_PASSWORD>` (from output above)
- Login Server: `rmhazureacr.azurecr.io`

---

## 2. Azure App Service Configuration

### Resource Details
```
Resource Type: App Service (Linux)
Name: rmhtitiler
Resource Group: rmhazure_rg
Location: East US
App Service Plan: ASP-rmhtitiler
Runtime: Docker Container (Linux)
```

### 2.1 Basic App Service Properties

**Property:** Operating System
- **Value:** Linux
- **Reason:** Docker container support

**Property:** Always On
- **Value:** Enabled
- **Reason:** Keeps app warm, prevents cold starts

**CLI Command:**
```bash
az webapp config set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --always-on true
```

**Azure Portal Path:**
1. Navigate to: App Service → rmhtitiler
2. Click: Settings → Configuration → General settings
3. Enable: Always On

---

## 3. Managed Identity Configuration

### 3.1 Enable System-Assigned Managed Identity

**Setting:** System-assigned managed identity
**Value:** Enabled
**Reason:** Allows App Service to authenticate to Azure Storage without storing credentials

**CLI Command:**
```bash
az webapp identity assign \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

**Azure Portal Path:**
1. Navigate to: App Service → rmhtitiler
2. Click: Settings → Identity
3. Tab: System assigned
4. Set Status: On
5. Click: Save

**Verification:**
```bash
az webapp identity show \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

**Expected Output:**
```json
{
  "principalId": "da61121c-aca8-4bc5-af05-eda4a1bc78a9",
  "tenantId": "086aef7e-db12-4161-8a9f-777deb499cfa",
  "type": "SystemAssigned"
}
```

**IMPORTANT:** Save the `principalId` value - needed for the next step.

---

## 4. Storage Account Permissions

### 4.1 Grant Storage Blob Data Reader Role

**Role Assignment Details:**
```
Role: Storage Blob Data Reader
Assignee: App Service Managed Identity (Principal ID from above)
Scope: Storage Account (rmhazuregeo)
Reason: Allows managed identity to read blobs and generate SAS tokens
```

**CLI Command (using variables):**
```bash
# Set the Principal ID (from step 3.1 output)
PRINCIPAL_ID="da61121c-aca8-4bc5-af05-eda4a1bc78a9"

# Get Storage Account Resource ID
STORAGE_ID=$(az storage account show \
  --name rmhazuregeo \
  --query id -o tsv)

# Grant role
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $PRINCIPAL_ID \
  --scope $STORAGE_ID
```

**CLI Command (with explicit values):**
```bash
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee da61121c-aca8-4bc5-af05-eda4a1bc78a9 \
  --scope /subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo
```

**Azure Portal Path:**
1. Navigate to: Storage Account → rmhazuregeo
2. Click: Access Control (IAM)
3. Click: + Add → Add role assignment
4. Select Role: Storage Blob Data Reader
5. Assign access to: Managed Identity
6. Select: rmhtitiler (System-assigned)
7. Click: Review + assign

**Verification:**
```bash
az role assignment list \
  --assignee da61121c-aca8-4bc5-af05-eda4a1bc78a9 \
  --scope /subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo \
  --output table
```

**Expected Output:**
```
Role                        PrincipalName                         Scope
--------------------------  ------------------------------------  -----------------------------------------------
Storage Blob Data Reader    rmhtitiler                           /subscriptions/.../storageAccounts/rmhazuregeo
```

**Role Permissions:**
This role provides the following permissions:
- `Microsoft.Storage/storageAccounts/blobServices/containers/read`
- `Microsoft.Storage/storageAccounts/blobServices/generateUserDelegationKey/action`
- `Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read`

---

## 5. Application Settings (Environment Variables)

### 5.1 Required Application Settings

All environment variables must be configured as **Application Settings** in the App Service.

**CLI Command (set all at once):**
```bash
az webapp config appsettings set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --settings \
    LOCAL_MODE=false \
    USE_AZURE_AUTH=true \
    USE_SAS_TOKEN=true \
    AZURE_STORAGE_ACCOUNT=rmhazuregeo \
    WEBSITES_PORT=8000 \
    WEBSITES_ENABLE_APP_SERVICE_STORAGE=false \
    CPL_VSIL_CURL_CACHE_SIZE=128000000 \
    GDAL_CACHEMAX=512 \
    GDAL_HTTP_MULTIPLEX=YES \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
```

**Azure Portal Path:**
1. Navigate to: App Service → rmhtitiler
2. Click: Settings → Configuration
3. Tab: Application settings
4. Click: + New application setting (for each setting below)
5. Click: Save (after adding all settings)
6. Click: Continue (to restart app)

### 5.2 Individual Setting Details

#### Critical Settings (Application Behavior)

**Setting Name:** `LOCAL_MODE`
- **Value:** `false`
- **Type:** String
- **Description:** Enables production mode (uses Managed Identity instead of storage key)
- **Required:** Yes
- **Slot Setting:** No

**Setting Name:** `USE_AZURE_AUTH`
- **Value:** `true`
- **Type:** String
- **Description:** Enables Azure Storage authentication
- **Required:** Yes
- **Slot Setting:** No

**Setting Name:** `USE_SAS_TOKEN`
- **Value:** `true`
- **Type:** String
- **Description:** Enables SAS token generation (instead of direct key access)
- **Required:** Yes
- **Slot Setting:** No

**Setting Name:** `AZURE_STORAGE_ACCOUNT`
- **Value:** `rmhazuregeo`
- **Type:** String
- **Description:** Name of the Azure Storage account containing COG files
- **Required:** Yes
- **Slot Setting:** No

#### App Service Settings

**Setting Name:** `WEBSITES_PORT`
- **Value:** `8000`
- **Type:** String
- **Description:** Port that the container listens on
- **Required:** Yes
- **Slot Setting:** No

**Setting Name:** `WEBSITES_ENABLE_APP_SERVICE_STORAGE`
- **Value:** `false`
- **Type:** String
- **Description:** Disables App Service storage mount (not needed for containers)
- **Required:** No (recommended)
- **Slot Setting:** No

#### GDAL Performance Settings

**Setting Name:** `CPL_VSIL_CURL_CACHE_SIZE`
- **Value:** `128000000`
- **Type:** String
- **Description:** GDAL CURL cache size in bytes (128MB) for better performance
- **Required:** No (recommended for performance)
- **Slot Setting:** No

**Setting Name:** `GDAL_CACHEMAX`
- **Value:** `512`
- **Type:** String
- **Description:** GDAL cache max size in MB
- **Required:** No (recommended for performance)
- **Slot Setting:** No

**Setting Name:** `GDAL_HTTP_MULTIPLEX`
- **Value:** `YES`
- **Type:** String
- **Description:** Enables HTTP multiplexing for better performance
- **Required:** No (recommended for performance)
- **Slot Setting:** No

**Setting Name:** `GDAL_DISABLE_READDIR_ON_OPEN`
- **Value:** `EMPTY_DIR`
- **Type:** String
- **Description:** Optimizes GDAL for cloud storage access
- **Required:** No (recommended for performance)
- **Slot Setting:** No

### 5.3 Settings That Should NOT Be Present

**CRITICAL:** These settings must NOT be configured:

❌ `AZURE_STORAGE_KEY` - Never set this in production
❌ `AZURE_STORAGE_ACCESS_KEY` - Never set this in production
❌ `AZURE_STORAGE_SAS_TOKEN` - Dynamically generated by the app

**Reason:** The application uses Managed Identity to generate SAS tokens dynamically. Hardcoded credentials are a security risk.

---

## 6. Container Configuration

### 6.1 Container Registry Settings

**CLI Command:**
```bash
az webapp config container set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --docker-custom-image-name rmhazureacr.azurecr.io/titiler-azure:latest \
  --docker-registry-server-url https://rmhazureacr.azurecr.io \
  --docker-registry-server-user rmhazureacr \
  --docker-registry-server-password <ACR_PASSWORD_FROM_STEP_1.2>
```

**Azure Portal Path:**
1. Navigate to: App Service → rmhtitiler
2. Click: Settings → Configuration
3. Tab: Application settings
4. Add the following settings:

**Setting Name:** `DOCKER_REGISTRY_SERVER_URL`
- **Value:** `https://rmhazureacr.azurecr.io`
- **Type:** String
- **Description:** URL of the container registry

**Setting Name:** `DOCKER_REGISTRY_SERVER_USERNAME`
- **Value:** `rmhazureacr`
- **Type:** String
- **Description:** ACR username

**Setting Name:** `DOCKER_REGISTRY_SERVER_PASSWORD`
- **Value:** `<PRIMARY_PASSWORD>` (from Step 1.2)
- **Type:** String
- **Description:** ACR password
- **Important:** Mark as "Deployment slot setting" if using slots

### 6.2 Container Image Configuration

**Image Name:** `rmhazureacr.azurecr.io/titiler-azure:latest`

**Azure Portal Path:**
1. Navigate to: App Service → rmhtitiler
2. Click: Deployment → Deployment Center
3. Set:
   - Source: Azure Container Registry
   - Registry: rmhazureacr
   - Image: titiler-azure
   - Tag: latest
4. Enable: Continuous Deployment (optional)
5. Click: Save

### 6.3 Health Check Configuration

**CLI Command:**
```bash
az webapp config set \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --health-check-path "/healthz"
```

**Azure Portal Path:**
1. Navigate to: App Service → rmhtitiler
2. Click: Monitoring → Health check
3. Enable: Health check
4. Set Path: `/healthz`
5. Click: Save

**Health Check Settings:**
- Path: `/healthz`
- Protocol: HTTP
- Interval: 30 seconds
- Unhealthy threshold: 3 consecutive failures

---

## 7. Complete Service Request Template

### Template for Corporate IT Service Request

```
SUBJECT: Azure Configuration Changes for TiTiler Application Deployment

REQUEST TYPE: Azure App Service Configuration

AFFECTED RESOURCES:
- App Service: rmhtitiler (rmhazure_rg)
- Container Registry: rmhazureacr (rmhazure_rg)
- Storage Account: rmhazuregeo (rmhazure_rg)

BUSINESS JUSTIFICATION:
Deploy secure TiTiler geospatial tile server using Managed Identity
authentication to eliminate hardcoded credentials and follow Azure
security best practices.

═══════════════════════════════════════════════════════════════════

REQUEST 1: Enable Azure Container Registry Admin Access
-----------------------------------------------------------
Resource: rmhazureacr (Container Registry)
Action: Enable admin user authentication
Reason: Required for App Service to pull container images

Configuration:
  Setting: Admin user enabled
  Value: true

Azure CLI Command:
  az acr update --name rmhazureacr --admin-enabled true

Azure Portal Path:
  Container Registry → rmhazureacr → Settings → Access keys →
  Enable "Admin user"

Verification:
  Admin user shows as "Enabled" in Access keys section

═══════════════════════════════════════════════════════════════════

REQUEST 2: Enable System-Assigned Managed Identity
-----------------------------------------------------------
Resource: rmhtitiler (App Service)
Action: Enable system-assigned managed identity
Reason: Secure authentication to Azure Storage without credentials

Configuration:
  Identity Type: System-assigned
  Status: On

Azure CLI Command:
  az webapp identity assign --resource-group rmhazure_rg --name rmhtitiler

Azure Portal Path:
  App Service → rmhtitiler → Settings → Identity → System assigned →
  Status: On → Save

Verification:
  Principal ID is displayed (save this value for next request)

═══════════════════════════════════════════════════════════════════

REQUEST 3: Grant Storage Account Permissions to Managed Identity
-----------------------------------------------------------
Resource: rmhazuregeo (Storage Account)
Action: Assign "Storage Blob Data Reader" role to App Service managed identity
Reason: Allow application to read blobs and generate SAS tokens

Configuration:
  Role: Storage Blob Data Reader
  Assignee Type: Managed Identity
  Assignee: rmhtitiler (use Principal ID from Request 2)
  Scope: Storage Account (rmhazuregeo)

Azure CLI Command:
  az role assignment create \
    --role "Storage Blob Data Reader" \
    --assignee <PRINCIPAL_ID_FROM_REQUEST_2> \
    --scope /subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo

Azure Portal Path:
  Storage Account → rmhazuregeo → Access Control (IAM) →
  Add role assignment → Role: Storage Blob Data Reader →
  Assign access to: Managed Identity → Select: rmhtitiler →
  Review + assign

Verification:
  Role assignment appears in IAM with rmhtitiler as assignee

═══════════════════════════════════════════════════════════════════

REQUEST 4: Configure Container Registry Authentication
-----------------------------------------------------------
Resource: rmhtitiler (App Service)
Action: Configure ACR credentials for container image pull
Reason: Allow App Service to pull Docker images from ACR

Configuration:
  Add the following Application Settings:

  DOCKER_REGISTRY_SERVER_URL = https://rmhazureacr.azurecr.io
  DOCKER_REGISTRY_SERVER_USERNAME = rmhazureacr
  DOCKER_REGISTRY_SERVER_PASSWORD = <FROM_REQUEST_1_CREDENTIALS>

Azure CLI Command:
  az webapp config container set \
    --resource-group rmhazure_rg \
    --name rmhtitiler \
    --docker-custom-image-name rmhazureacr.azurecr.io/titiler-azure:latest \
    --docker-registry-server-url https://rmhazureacr.azurecr.io \
    --docker-registry-server-user rmhazureacr \
    --docker-registry-server-password <ACR_PASSWORD>

Azure Portal Path:
  App Service → rmhtitiler → Settings → Configuration →
  Application settings → Add each setting above → Save

Verification:
  Settings appear in Configuration blade

═══════════════════════════════════════════════════════════════════

REQUEST 5: Configure Application Settings (Environment Variables)
-----------------------------------------------------------
Resource: rmhtitiler (App Service)
Action: Add required application settings
Reason: Configure application behavior for production deployment

Configuration:
  Add the following Application Settings (all Slot Setting = No):

  CRITICAL SETTINGS (Application Behavior):
    LOCAL_MODE = false
    USE_AZURE_AUTH = true
    USE_SAS_TOKEN = true
    AZURE_STORAGE_ACCOUNT = rmhazuregeo
    WEBSITES_PORT = 8000
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = false

  PERFORMANCE SETTINGS (GDAL Configuration):
    CPL_VSIL_CURL_CACHE_SIZE = 128000000
    GDAL_CACHEMAX = 512
    GDAL_HTTP_MULTIPLEX = YES
    GDAL_DISABLE_READDIR_ON_OPEN = EMPTY_DIR

Azure CLI Command:
  az webapp config appsettings set \
    --resource-group rmhazure_rg \
    --name rmhtitiler \
    --settings \
      LOCAL_MODE=false \
      USE_AZURE_AUTH=true \
      USE_SAS_TOKEN=true \
      AZURE_STORAGE_ACCOUNT=rmhazuregeo \
      WEBSITES_PORT=8000 \
      WEBSITES_ENABLE_APP_SERVICE_STORAGE=false \
      CPL_VSIL_CURL_CACHE_SIZE=128000000 \
      GDAL_CACHEMAX=512 \
      GDAL_HTTP_MULTIPLEX=YES \
      GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR

Azure Portal Path:
  App Service → rmhtitiler → Settings → Configuration →
  Application settings → Add each setting → Save → Continue (restart)

CRITICAL: Verify these settings are NOT present:
  ❌ AZURE_STORAGE_KEY
  ❌ AZURE_STORAGE_ACCESS_KEY
  ❌ AZURE_STORAGE_SAS_TOKEN
  (These are security risks and should not be configured)

Verification:
  All settings appear in Configuration blade with correct values

═══════════════════════════════════════════════════════════════════

REQUEST 6: Configure Health Check
-----------------------------------------------------------
Resource: rmhtitiler (App Service)
Action: Enable health check monitoring
Reason: Monitor application availability and auto-restart if unhealthy

Configuration:
  Health Check Path: /healthz
  Interval: 30 seconds
  Unhealthy Threshold: 3 consecutive failures

Azure CLI Command:
  az webapp config set \
    --resource-group rmhazure_rg \
    --name rmhtitiler \
    --health-check-path "/healthz"

Azure Portal Path:
  App Service → rmhtitiler → Monitoring → Health check →
  Enable health check → Path: /healthz → Save

Verification:
  Health check shows as enabled with path "/healthz"

═══════════════════════════════════════════════════════════════════

REQUEST 7: Enable Always On
-----------------------------------------------------------
Resource: rmhtitiler (App Service)
Action: Enable Always On setting
Reason: Prevent cold starts and keep application warm

Configuration:
  Always On: Enabled

Azure CLI Command:
  az webapp config set \
    --resource-group rmhazure_rg \
    --name rmhtitiler \
    --always-on true

Azure Portal Path:
  App Service → rmhtitiler → Settings → Configuration →
  General settings → Always On: On → Save

Verification:
  Always On shows as "On" in General settings

═══════════════════════════════════════════════════════════════════

POST-DEPLOYMENT VERIFICATION
-----------------------------------------------------------

After all changes are applied:

1. Restart the App Service:
   az webapp restart --resource-group rmhazure_rg --name rmhtitiler

2. Test health endpoint:
   curl https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz

   Expected Response:
   {
     "status": "healthy",
     "azure_auth_enabled": true,
     "use_sas_token": true,
     "local_mode": false,
     "storage_account": "rmhazuregeo"
   }

3. Check application logs:
   az webapp log tail --resource-group rmhazure_rg --name rmhtitiler

   Expected Log Messages:
   - "TiTiler with Azure SAS Token Auth - Starting up"
   - "Local mode: False"
   - "Azure auth enabled: True"
   - "Use SAS tokens: True"
   - "Generating new User Delegation SAS token (production mode)"
   - "SAS token generated, expires at..."
   - "Startup complete - Ready to serve tiles!"

4. Test COG access:
   curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"

   Expected: JSON response with COG metadata (bounds, bands, etc.)

═══════════════════════════════════════════════════════════════════

ROLLBACK PLAN
-----------------------------------------------------------

If deployment fails, rollback changes in reverse order:

1. Disable health check
2. Remove application settings
3. Remove container configuration
4. Remove role assignment from storage account
5. Disable managed identity
6. Disable ACR admin access

═══════════════════════════════════════════════════════════════════

SECURITY NOTES
-----------------------------------------------------------

✅ This configuration follows Azure security best practices:
   - Uses Managed Identity (no hardcoded credentials)
   - Uses SAS tokens (limited scope and auto-expiring)
   - Minimal permissions (Storage Blob Data Reader only)
   - No storage keys in environment variables

❌ Explicitly avoid these insecure practices:
   - Storing storage account keys in application settings
   - Using connection strings with embedded keys
   - Hardcoding SAS tokens

═══════════════════════════════════════════════════════════════════

ESTIMATED COMPLETION TIME: 30-45 minutes

DEPENDENCIES: None (all changes are independent)

MAINTENANCE WINDOW REQUIRED: No (changes can be applied without downtime)

BACKUP REQUIRED: No (configuration changes are non-destructive)

APPROVAL REQUIRED: Standard change approval for security configuration

═══════════════════════════════════════════════════════════════════
```

---

## 8. Verification Checklist

After all configurations are applied, verify each setting:

### 8.1 ACR Verification
- [ ] Admin user is enabled
- [ ] Can retrieve ACR credentials
- [ ] Can login to ACR: `az acr login --name rmhazureacr`

### 8.2 Managed Identity Verification
- [ ] System-assigned identity is enabled
- [ ] Principal ID is visible
- [ ] Identity shows in Azure AD

### 8.3 Storage Permissions Verification
- [ ] Role assignment exists: Storage Blob Data Reader
- [ ] Assignment scope is correct: rmhazuregeo
- [ ] Assignment target is correct: rmhtitiler managed identity

### 8.4 Application Settings Verification
- [ ] All required settings are present
- [ ] No prohibited settings exist (storage keys)
- [ ] Values are correct (especially LOCAL_MODE=false)

### 8.5 Container Configuration Verification
- [ ] ACR credentials are configured
- [ ] Image name is correct
- [ ] Container pulls successfully

### 8.6 Health Check Verification
- [ ] Health check is enabled
- [ ] Path is `/healthz`
- [ ] Health endpoint returns 200 OK

### 8.7 Application Verification
- [ ] App starts without errors
- [ ] Logs show "production mode"
- [ ] Logs show SAS token generation
- [ ] COG access works

---

## 9. Troubleshooting Common Issues

### Issue: Container fails to pull
**Symptoms:** "Failed to pull image" errors
**Solution:** Verify ACR credentials in step 6.1

### Issue: Authentication fails
**Symptoms:** 403 errors when accessing storage
**Solution:** Verify managed identity and role assignment (steps 3 & 4)

### Issue: App doesn't start
**Symptoms:** Container crashes, no logs
**Solution:** Verify WEBSITES_PORT=8000 setting

### Issue: SAS tokens not generated
**Symptoms:** "Failed to generate SAS token" in logs
**Solution:** Verify managed identity has "Storage Blob Data Reader" role

### Issue: Wrong mode detected
**Symptoms:** Logs show "development mode"
**Solution:** Verify LOCAL_MODE=false in application settings

---

## 10. Quick Reference Commands

### Get all current settings
```bash
az webapp config appsettings list \
  --resource-group rmhazure_rg \
  --name rmhtitiler \
  --output table
```

### Get managed identity info
```bash
az webapp identity show \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

### Check role assignments
```bash
az role assignment list \
  --assignee <PRINCIPAL_ID> \
  --output table
```

### View application logs
```bash
az webapp log tail \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

### Restart application
```bash
az webapp restart \
  --resource-group rmhazure_rg \
  --name rmhtitiler
```

---

**Document Version:** 1.0
**Last Updated:** November 7, 2025
**Maintained By:** Development Team
**Review Frequency:** After any production changes
