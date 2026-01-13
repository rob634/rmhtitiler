# TiTiler-pgSTAC Azure Deployment Guide

## Prerequisites

- Azure Container Registry (ACR)
- Azure App Service (Linux, Docker container)
- Azure PostgreSQL with pgSTAC installed
- Azure Storage Account with COGs

## Step 1: Build and Push Docker Image

```bash
# Set variables
ACR_NAME="your-acr-name"
IMAGE_NAME="titiler-pgstac"
VERSION="1.0.0"

# Login to ACR
az acr login --name $ACR_NAME

# Build production image
docker build -t $ACR_NAME.azurecr.io/$IMAGE_NAME:$VERSION -f Dockerfile .
docker build -t $ACR_NAME.azurecr.io/$IMAGE_NAME:latest -f Dockerfile .

# Push to ACR
docker push $ACR_NAME.azurecr.io/$IMAGE_NAME:$VERSION
docker push $ACR_NAME.azurecr.io/$IMAGE_NAME:latest
```

## Step 2: Create App Service with Managed Identity

```bash
# Set variables
RESOURCE_GROUP="rmhazure_rg"
APP_SERVICE_PLAN="titiler-plan"
APP_NAME="titiler-pgstac"
STORAGE_ACCOUNT="rmhazuregeo"

# Create App Service Plan (if not exists)
az appservice plan create \
  --name $APP_SERVICE_PLAN \
  --resource-group $RESOURCE_GROUP \
  --is-linux \
  --sku B2

# Create Web App with ACR image
az webapp create \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --plan $APP_SERVICE_PLAN \
  --deployment-container-image-name $ACR_NAME.azurecr.io/$IMAGE_NAME:latest

# Enable System-Assigned Managed Identity
az webapp identity assign \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP

# Get the Managed Identity Principal ID
PRINCIPAL_ID=$(az webapp identity show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

echo "Managed Identity Principal ID: $PRINCIPAL_ID"
```

## Step 3: Grant RBAC Permissions

```bash
# Grant Storage Blob Data Reader role to Managed Identity
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $PRINCIPAL_ID \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT

# Wait 2-3 minutes for RBAC to propagate
echo "Waiting for RBAC propagation..."
sleep 180
```

## Step 4: Configure App Service Settings

```bash
# Set environment variables
az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    LOCAL_MODE="false" \
    USE_AZURE_AUTH="true" \
    AZURE_STORAGE_ACCOUNT="$STORAGE_ACCOUNT" \
    DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require" \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff" \
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR" \
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES" \
    GDAL_HTTP_MULTIPLEX="YES" \
    GDAL_HTTP_VERSION="2" \
    VSI_CACHE="TRUE" \
    VSI_CACHE_SIZE="536870912"

# Configure container settings
az webapp config container set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --docker-custom-image-name $ACR_NAME.azurecr.io/$IMAGE_NAME:latest \
  --docker-registry-server-url https://$ACR_NAME.azurecr.io

# Enable continuous deployment (optional)
az webapp deployment container config \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --enable-cd true
```

## Step 5: Configure ACR Access

```bash
# Enable admin user on ACR (for App Service pull)
az acr update --name $ACR_NAME --admin-enabled true

# Get ACR credentials
ACR_USERNAME=$(az acr credential show --name $ACR_NAME --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv)

# Set ACR credentials in App Service
az webapp config container set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --docker-registry-server-url https://$ACR_NAME.azurecr.io \
  --docker-registry-server-user $ACR_USERNAME \
  --docker-registry-server-password $ACR_PASSWORD
```

## Step 6: Restart and Verify

```bash
# Restart the app
az webapp restart --name $APP_NAME --resource-group $RESOURCE_GROUP

# Wait for startup
sleep 30

# Check logs
az webapp log tail --name $APP_NAME --resource-group $RESOURCE_GROUP

# Test health endpoint
APP_URL=$(az webapp show --name $APP_NAME --resource-group $RESOURCE_GROUP --query defaultHostName -o tsv)
curl https://$APP_URL/healthz
```

## Step 7: Test Endpoints

```bash
# Get app URL
APP_URL=$(az webapp show --name $APP_NAME --resource-group $RESOURCE_GROUP --query defaultHostName -o tsv)

# Test health endpoint
curl "https://$APP_URL/healthz" | python3 -m json.tool

# Test direct COG info
curl "https://$APP_URL/cog/info?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif" | python3 -m json.tool

# Test direct COG tile
curl "https://$APP_URL/cog/tiles/WebMercatorQuad/14/11454/6143.png?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif" -o test_tile.png

# Test pgSTAC search registration
SEARCH_ID=$(curl -s -X POST "https://$APP_URL/searches/register" \
  -H "Content-Type: application/json" \
  -d '{"collections":["system-rasters"],"limit":10}' | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

echo "Search ID: $SEARCH_ID"

# Test pgSTAC tile generation
curl "https://$APP_URL/searches/$SEARCH_ID/tiles/WebMercatorQuad/14/11454/6143.png?assets=data" -o pgstac_tile.png

# Open interactive viewer (Direct COG)
open "https://$APP_URL/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif"

# Open pgSTAC search viewer
open "https://$APP_URL/searches/$SEARCH_ID/WebMercatorQuad/map.html?assets=data"

# Open API docs
open "https://$APP_URL/docs"
```

### Verified Production Deployment

**Production URL**: `https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net`

All three tile access patterns verified working:

1. **Direct COG Access** ✅
   - Info: [/cog/info?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif](https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif)
   - Tile: [/cog/tiles/WebMercatorQuad/14/11454/6143.png?url=/vsiaz/...](https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/14/11454/6143.png?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif)
   - Viewer: [/cog/WebMercatorQuad/map.html?url=/vsiaz/...](https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/namangan14aug2019_R2C2cog_cog_analysis.tif)

2. **pgSTAC Search** ✅
   - Register: `POST /searches/register`
   - Tiles: `/searches/{search_id}/tiles/{z}/{x}/{y}.png?assets=data`
   - Viewer: `/searches/{search_id}/WebMercatorQuad/map.html?assets=data`

3. **MosaicJSON** ✅
   - Endpoints available at `/mosaicjson/...`

**OAuth Authentication**: Working via Managed Identity (da61121c-aca8-4bc5-af05-eda4a1bc78a9)
**Database**: Connected to `rmhpgflex.postgres.database.azure.com/geopgflex`
**Storage**: Multi-container access via RBAC to `rmhazuregeo`

## Environment Variables Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `LOCAL_MODE` | Use Azure CLI (true) or Managed Identity (false) | `false` |
| `USE_AZURE_AUTH` | Enable OAuth authentication | `true` |
| `AZURE_STORAGE_ACCOUNT` | Storage account name | `rmhazuregeo` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db?sslmode=require` |
| `CPL_VSIL_CURL_ALLOWED_EXTENSIONS` | GDAL file extensions | `.tif,.tiff` |
| `GDAL_DISABLE_READDIR_ON_OPEN` | Disable directory listing | `EMPTY_DIR` |
| `GDAL_HTTP_MERGE_CONSECUTIVE_RANGES` | HTTP range optimization | `YES` |
| `GDAL_HTTP_MULTIPLEX` | HTTP/2 multiplexing | `YES` |
| `GDAL_HTTP_VERSION` | HTTP version | `2` |
| `VSI_CACHE` | Enable GDAL cache | `TRUE` |
| `VSI_CACHE_SIZE` | Cache size in bytes | `536870912` (512MB) |

## RBAC Roles Required

The App Service Managed Identity needs:

1. **Storage Blob Data Reader** on the storage account
   - Grants read access to all containers
   - No account keys needed

2. **Optional: Reader** on storage account
   - For listing containers (if needed)

## Troubleshooting

### OAuth Token Acquisition Fails

```bash
# Check Managed Identity
az webapp identity show --name $APP_NAME --resource-group $RESOURCE_GROUP

# Check RBAC assignments
az role assignment list --assignee $PRINCIPAL_ID
```

### HTTP 403 Errors

- Verify RBAC role assignment
- Wait 5-10 minutes for propagation
- Check logs: `az webapp log tail --name $APP_NAME --resource-group $RESOURCE_GROUP`

### Container Won't Start

```bash
# Check container logs
az webapp log tail --name $APP_NAME --resource-group $RESOURCE_GROUP

# Verify ACR credentials
az acr credential show --name $ACR_NAME
```

## Scaling

```bash
# Scale up (vertical)
az appservice plan update \
  --name $APP_SERVICE_PLAN \
  --resource-group $RESOURCE_GROUP \
  --sku P1V2

# Scale out (horizontal)
az appservice plan update \
  --name $APP_SERVICE_PLAN \
  --resource-group $RESOURCE_GROUP \
  --number-of-workers 3
```

## Monitoring

```bash
# Enable Application Insights
az monitor app-insights component create \
  --app titiler-insights \
  --location eastus \
  --resource-group $RESOURCE_GROUP

# Link to App Service
INSTRUMENTATION_KEY=$(az monitor app-insights component show \
  --app titiler-insights \
  --resource-group $RESOURCE_GROUP \
  --query instrumentationKey -o tsv)

az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings APPINSIGHTS_INSTRUMENTATIONKEY=$INSTRUMENTATION_KEY
```

## Security Best Practices

1. ✅ **No secrets in code** - Using Managed Identity
2. ✅ **No secrets in Dockerfile** - Environment variables only
3. ✅ **RBAC least privilege** - Storage Blob Data Reader only
4. ✅ **SSL/TLS enforced** - HTTPS only in production
5. ✅ **Connection strings** - Stored in App Service Configuration (encrypted)

## Next Steps

1. Configure custom domain
2. Enable HTTPS with Let's Encrypt or Azure-managed certificate
3. Set up CI/CD pipeline (GitHub Actions or Azure DevOps)
4. Configure auto-scaling rules
5. Set up monitoring alerts
