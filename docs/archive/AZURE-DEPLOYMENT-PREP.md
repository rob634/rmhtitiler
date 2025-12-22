# 🚀 Azure Deployment Preparation Checklist

**Status:** Ready for Production Deployment
**Date:** November 7, 2025
**Storage Account:** rmhazuregeo

---

## ✅ Pre-Deployment Checklist

### 1. Local Testing Completed
- [x] SAS token generation working locally
- [x] Azure Storage access verified
- [x] Security model confirmed (GDAL doesn't see key)
- [x] COG viewing in browser successful
- [x] Authentication verification documented

### 2. Azure Resources Needed

#### Required Resources:
- [ ] Azure Container Registry (ACR) - to host Docker image
- [ ] Azure App Service (Linux) - to run TiTiler
- [ ] Azure Storage Account (existing: `rmhazuregeo`)
- [ ] Resource Group (to organize resources)

#### Optional but Recommended:
- [ ] Application Insights - for monitoring
- [ ] Azure Key Vault - for additional secret management
- [ ] Azure CDN - for tile caching (performance)

---

## 📋 Step-by-Step Preparation

### Step 1: Check Existing Azure Resources

```bash
# Login to Azure (already done)
az login

# List your subscriptions
az account list --output table

# Set the active subscription
az account set --subscription "rmhazure"

# List existing resource groups
az group list --output table

# Check if storage account exists
az storage account show --name rmhazuregeo --query '{name:name,location:location,sku:sku.name}'
```

**Expected Output:**
```json
{
  "name": "rmhazuregeo",
  "location": "eastus",
  "sku": "Standard_LRS"
}
```

---

### Step 2: Create Resource Group (if needed)

```bash
# Check if you already have a resource group
az group list --query "[].name" -o table

# If you need to create one:
az group create \
  --name rg-titiler-prod \
  --location eastus \
  --tags purpose=geospatial app=titiler environment=production
```

**Decision Needed:**
- Use existing resource group? Or create new one?
- Recommended location: Same as storage account (eastus)

---

### Step 3: Create Azure Container Registry

```bash
# Create ACR (adjust name to be unique)
az acr create \
  --resource-group rg-titiler-prod \
  --name rmhtitileracr \
  --sku Basic \
  --location eastus \
  --admin-enabled true

# Login to ACR
az acr login --name rmhtitileracr

# Get ACR credentials (for deployment)
az acr credential show --name rmhtitileracr --query '{username:username,password:passwords[0].value}'
```

**Notes:**
- ACR name must be globally unique
- Basic SKU is sufficient for single instance
- Admin access needed for App Service pulls

---

### Step 4: Build Production Docker Image

```bash
# Navigate to project directory
cd /Users/robertharrison/python_builds/rmhtitiler

# Build production image
docker build \
  --platform linux/amd64 \
  -t rmhtitileracr.azurecr.io/titiler-azure:latest \
  -t rmhtitileracr.azurecr.io/titiler-azure:v1.0.0 \
  -f Dockerfile \
  .

# Test the production image locally (optional but recommended)
docker run -d \
  --name titiler-prod-test \
  -p 8001:8000 \
  -e LOCAL_MODE=false \
  -e USE_AZURE_AUTH=true \
  -e USE_SAS_TOKEN=true \
  -e AZURE_STORAGE_ACCOUNT=rmhazuregeo \
  rmhtitileracr.azurecr.io/titiler-azure:latest

# Test it
curl http://localhost:8001/healthz

# Stop test container
docker stop titiler-prod-test && docker rm titiler-prod-test
```

---

### Step 5: Push Image to Azure Container Registry

```bash
# Push to ACR
docker push rmhtitileracr.azurecr.io/titiler-azure:latest
docker push rmhtitileracr.azurecr.io/titiler-azure:v1.0.0

# Verify image is in ACR
az acr repository list --name rmhtitileracr --output table
az acr repository show-tags --name rmhtitileracr --repository titiler-azure --output table
```

---

### Step 6: Create Azure App Service Plan

```bash
# Create Linux App Service Plan (B1 Basic tier)
az appservice plan create \
  --name plan-titiler-prod \
  --resource-group rg-titiler-prod \
  --location eastus \
  --is-linux \
  --sku B1

# For production workload, consider P1V2 or higher:
# --sku P1V2  # Production: 1 core, 3.5GB RAM, $73/month
# --sku B1    # Basic: 1 core, 1.75GB RAM, ~$13/month
```

**SKU Recommendations:**
- **Development/Testing:** B1 Basic (~$13/month)
- **Production:** P1V2 Premium (~$73/month)
- **High Traffic:** P2V2 or P3V2

---

### Step 7: Create Web App

```bash
# Create Web App from ACR image
az webapp create \
  --resource-group rg-titiler-prod \
  --plan plan-titiler-prod \
  --name rmh-titiler-prod \
  --deployment-container-image-name rmhtitileracr.azurecr.io/titiler-azure:latest

# Configure ACR credentials
az webapp config container set \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --docker-custom-image-name rmhtitileracr.azurecr.io/titiler-azure:latest \
  --docker-registry-server-url https://rmhtitileracr.azurecr.io \
  --docker-registry-server-user $(az acr credential show --name rmhtitileracr --query username -o tsv) \
  --docker-registry-server-password $(az acr credential show --name rmhtitileracr --query 'passwords[0].value' -o tsv)
```

**Note:** App name must be globally unique. Adjust `rmh-titiler-prod` if needed.

---

### Step 8: Enable Managed Identity

```bash
# Enable system-assigned managed identity
az webapp identity assign \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod

# Get the managed identity principal ID
PRINCIPAL_ID=$(az webapp identity show \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --query principalId -o tsv)

echo "Managed Identity Principal ID: $PRINCIPAL_ID"
```

**Save this Principal ID** - you'll need it for the next step!

---

### Step 9: Grant Storage Permissions

```bash
# Get storage account resource ID
STORAGE_ID=$(az storage account show \
  --name rmhazuregeo \
  --query id -o tsv)

echo "Storage Account ID: $STORAGE_ID"

# Grant "Storage Blob Data Reader" role to managed identity
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $PRINCIPAL_ID \
  --scope $STORAGE_ID

# Verify role assignment
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --scope $STORAGE_ID \
  --output table
```

**Expected Output:**
```
Role                        Scope
--------------------------  --------------------------------------------------------
Storage Blob Data Reader    /subscriptions/.../storageAccounts/rmhazuregeo
```

---

### Step 10: Configure App Settings

```bash
# Set environment variables for production
az webapp config appsettings set \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --settings \
    LOCAL_MODE=false \
    USE_AZURE_AUTH=true \
    USE_SAS_TOKEN=true \
    AZURE_STORAGE_ACCOUNT=rmhazuregeo \
    CPL_VSIL_CURL_CACHE_SIZE=128000000 \
    GDAL_CACHEMAX=512 \
    GDAL_HTTP_MULTIPLEX=YES \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    WEBSITES_PORT=8000 \
    WEBSITES_ENABLE_APP_SERVICE_STORAGE=false

# Verify settings
az webapp config appsettings list \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --output table
```

**Critical Settings:**
- `LOCAL_MODE=false` - Use managed identity (not storage key)
- `USE_SAS_TOKEN=true` - Generate SAS tokens
- `AZURE_STORAGE_ACCOUNT=rmhazuregeo` - Your storage account
- `WEBSITES_PORT=8000` - TiTiler listens on port 8000
- **NO AZURE_STORAGE_KEY** - This is the key point!

---

### Step 11: Configure Container Settings

```bash
# Enable continuous deployment (auto-pull from ACR)
az webapp deployment container config \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --enable-cd true

# Get webhook URL for CI/CD (optional)
az webapp deployment container show-cd-url \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod
```

---

### Step 12: Configure Health Check

```bash
# Enable health check monitoring
az webapp config set \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --health-check-path "/healthz"

# Set always-on (keeps app warm)
az webapp config set \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --always-on true
```

---

### Step 13: Restart and Monitor

```bash
# Restart the web app to apply all settings
az webapp restart \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod

# Stream logs
az webapp log tail \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod

# Or view in real-time
az webapp log config \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --docker-container-logging filesystem

# Check app status
az webapp show \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --query '{name:name,state:state,url:defaultHostName}'
```

---

### Step 14: Test Deployment

```bash
# Get the app URL
APP_URL=$(az webapp show \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --query defaultHostName -o tsv)

echo "App URL: https://$APP_URL"

# Test health endpoint
curl "https://$APP_URL/healthz" | jq

# Test COG info
curl "https://$APP_URL/cog/info?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif" | jq

# Test tile (in browser)
echo "Tile URL: https://$APP_URL/cog/tiles/WebMercatorQuad/15/9373/12532.png?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"
```

**Expected Health Check Response:**
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "use_sas_token": true,
  "local_mode": false,
  "storage_account": "rmhazuregeo",
  "sas_token_expires_in_seconds": 3400
}
```

---

## 🔧 Troubleshooting Commands

### Check Container Logs
```bash
# Real-time logs
az webapp log tail --resource-group rg-titiler-prod --name rmh-titiler-prod

# Download logs
az webapp log download --resource-group rg-titiler-prod --name rmh-titiler-prod --log-file logs.zip
```

### Check Managed Identity
```bash
# Verify identity is assigned
az webapp identity show --resource-group rg-titiler-prod --name rmh-titiler-prod

# Check role assignments
az role assignment list --assignee $PRINCIPAL_ID --output table
```

### Check Container Status
```bash
# Get detailed app info
az webapp show --resource-group rg-titiler-prod --name rmh-titiler-prod

# Check container logs
az webapp log show --resource-group rg-titiler-prod --name rmh-titiler-prod
```

### Update Container Image
```bash
# Pull latest image
az webapp config container set \
  --resource-group rg-titiler-prod \
  --name rmh-titiler-prod \
  --docker-custom-image-name rmhtitileracr.azurecr.io/titiler-azure:latest

# Restart
az webapp restart --resource-group rg-titiler-prod --name rmh-titiler-prod
```

---

## 📊 Estimated Costs (Monthly)

| Resource | SKU/Tier | Estimated Cost |
|----------|----------|----------------|
| **Container Registry** | Basic | $5 |
| **App Service Plan (Basic)** | B1 | $13 |
| **App Service Plan (Production)** | P1V2 | $73 |
| **Storage Account** | Standard LRS (existing) | ~$0.02/GB |
| **Application Insights** | Pay-as-you-go | ~$2-10 |
| **Total (Basic)** | | **~$18-23/month** |
| **Total (Production)** | | **~$78-88/month** |

**Notes:**
- Storage costs depend on data volume and transactions
- Egress bandwidth is ~$0.09/GB after 5GB free
- Scale up to P1V2 or higher for production workloads

---

## 🎯 Pre-Deployment Decisions

### 1. Resource Naming
- [ ] **Resource Group Name:** `rg-titiler-prod` or `_______`
- [ ] **Container Registry Name:** `rmhtitileracr` or `_______` (must be globally unique)
- [ ] **Web App Name:** `rmh-titiler-prod` or `_______` (must be globally unique)
- [ ] **App Service Plan Name:** `plan-titiler-prod` or `_______`

### 2. SKU/Tier Selection
- [ ] **Development/Testing:** B1 Basic ($13/month)
- [ ] **Production:** P1V2 Premium ($73/month)
- [ ] **High Traffic:** P2V2 or P3V2

### 3. Location
- [ ] **Same as storage account:** eastus (recommended)
- [ ] **Other:** `_______`

### 4. Optional Features
- [ ] Enable Application Insights for monitoring
- [ ] Enable Azure CDN for tile caching
- [ ] Set up custom domain
- [ ] Configure SSL/TLS certificate (if custom domain)

---

## ✅ Deployment Verification Checklist

After deployment, verify:

- [ ] Health endpoint returns `"status": "healthy"`
- [ ] Logs show "Generating new User Delegation SAS token (production mode)"
- [ ] Logs show "SAS token generated, expires at..."
- [ ] Logs show NO errors about authentication
- [ ] COG info endpoint returns metadata
- [ ] Tile endpoint returns PNG images
- [ ] `/debug/env` shows `"local_mode": false`
- [ ] `/debug/env` shows `AZURE_STORAGE_ACCESS_KEY: "NOT PRESENT"`
- [ ] Viewer works with production URL

---

## 🔒 Security Checklist

Before going live:

- [ ] Disable `/debug/env` endpoint in production (or add auth)
- [ ] Verify no storage keys in environment variables
- [ ] Confirm managed identity has minimum required permissions
- [ ] Enable Application Insights for monitoring
- [ ] Set up alerts for authentication failures
- [ ] Review CORS settings if needed
- [ ] Consider rate limiting for tile endpoints

---

## 📚 Next Steps After Deployment

1. **Update Viewer** - Change endpoint to production URL
2. **Performance Testing** - Load test with actual traffic patterns
3. **Monitoring** - Set up Application Insights dashboards
4. **Backup Strategy** - Document disaster recovery plan
5. **CI/CD Pipeline** - Automate deployments with GitHub Actions
6. **Documentation** - Update production runbook

---

## 🆘 Support Resources

- **Azure CLI Reference:** https://docs.microsoft.com/cli/azure/
- **App Service Docker:** https://docs.microsoft.com/azure/app-service/containers/
- **Managed Identity:** https://docs.microsoft.com/azure/active-directory/managed-identities-azure-resources/
- **TiTiler Docs:** https://developmentseed.org/titiler/

---

**Ready to Deploy?** Follow the steps above in order, and you'll have TiTiler running in Azure with secure SAS token authentication! 🚀
