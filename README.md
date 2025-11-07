# TiTiler with Azure Managed Identity

A production-ready TiTiler deployment that uses Azure Managed Identity to securely access Cloud-Optimized GeoTIFFs (COGs) in Azure Blob Storage.

## Features

- **Secure Authentication**: Uses Azure Managed Identity - no credentials in code
- **Local Development**: Full Docker Compose setup for local testing
- **Production Ready**: Optimized for Azure App Service deployment
- **Automatic Token Refresh**: Handles token expiration automatically
- **GDAL Integration**: Leverages GDAL's `/vsiaz/` virtual file system
- **Performance Optimized**: Multi-worker setup with GDAL caching

## Quick Start

### Local Development

See [README-LOCAL.md](README-LOCAL.md) for detailed local development instructions.

```bash
# Start local server
docker-compose up --build

# Test with local file
curl "http://localhost:8000/cog/info?url=/data/example.tif"
```

### Production Deployment

See [docs/design.md](docs/design.md) for detailed architecture and deployment guide.

```bash
# Build and push to Azure Container Registry
az acr build \
  --registry yourregistry \
  --image titiler-azure:latest \
  --file Dockerfile \
  .

# Deploy to Azure App Service (see docs/design.md for full steps)
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Azure Web App                            │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              TiTiler Container                         │ │
│  │                                                         │ │
│  │  1. Startup: Get Azure AD token via Managed Identity  │ │
│  │  2. Middleware: Refresh token before each request     │ │
│  │  3. Set AZURE_STORAGE_ACCESS_TOKEN env var           │ │
│  │  4. GDAL reads from /vsiaz/container/file.tif        │ │
│  │  5. TiTiler serves tiles normally                     │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────────┐
                    │  Azure Blob Storage  │
                    │  (with RBAC access)  │
                    └──────────────────────┘
```

## API Endpoints

### Health Check
```bash
GET /healthz
```

Returns server health and authentication status.

### Root Information
```bash
GET /
```

Returns API information and example endpoints.

### COG Info
```bash
GET /cog/info?url=<path>
```

Get metadata about a Cloud-Optimized GeoTIFF.

**Examples:**
```bash
# Local file
curl "http://localhost:8000/cog/info?url=/data/example.tif"

# Azure Blob Storage
curl "http://your-app.azurewebsites.net/cog/info?url=/vsiaz/container/path/to/file.tif"
```

### COG Tiles
```bash
GET /cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}.{format}?url=<path>
```

Get a tile from a COG.

**Examples:**
```bash
# Get tile from Azure Storage
curl "http://your-app.azurewebsites.net/cog/tiles/WebMercatorQuad/14/3876/6325.png?url=/vsiaz/container/path/to/file.tif"
```

### Interactive Map Viewer
```bash
GET /cog/{tileMatrixSetId}/map.html?url=<path>
```

View COG in an interactive web map with pan/zoom.

**Examples:**
```bash
# View in browser
https://your-app.azurewebsites.net/cog/WebMercatorQuad/map.html?url=/vsiaz/container/path/to/file.tif
```

**Note:** There is NO `/cog/viewer` endpoint - the viewer is at `/cog/{tileMatrixSetId}/map.html`

### Additional Endpoints

- **TileJSON**: `/cog/{tileMatrixSetId}/tilejson.json?url=<path>` - Get TileJSON spec
- **Preview**: `/cog/preview.png?url=<path>` - Get static preview image
- **Statistics**: `/cog/statistics?url=<path>` - Get band statistics
- **GeoJSON**: `/cog/info.geojson?url=<path>` - Get bounds as GeoJSON
- **WMTS**: `/cog/{tileMatrixSetId}/WMTSCapabilities.xml?url=<path>` - Get WMTS capabilities

For complete API reference, see [docs/TITILER-API-REFERENCE.md](docs/TITILER-API-REFERENCE.md)

### Interactive Documentation

FastAPI provides automatic interactive documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Environment Variables

### Required (Production)

- `AZURE_STORAGE_ACCOUNT` - Your Azure Storage account name
- `USE_AZURE_AUTH` - Set to `true` to enable Azure authentication

### Optional (Production)

- `LOCAL_MODE` - Set to `false` for production (default in production Dockerfile)
- `CPL_VSIL_CURL_CACHE_SIZE` - GDAL cache size (default: 128000000)
- `GDAL_CACHEMAX` - GDAL max cache in MB (default: 512)
- `GDAL_HTTP_MULTIPLEX` - Enable HTTP/2 (default: YES)

### Local Development Only

- `AZURE_CLIENT_ID` - Service principal client ID (alternative to `az login`)
- `AZURE_CLIENT_SECRET` - Service principal secret
- `AZURE_TENANT_ID` - Azure tenant ID

## File Structure

```
rmhtitiler/
├── custom_main.py              # TiTiler app with Azure auth middleware
├── Dockerfile                  # Production Docker image
├── Dockerfile.local            # Local development Docker image
├── docker-compose.yml          # Local development orchestration
├── requirements.txt            # Production dependencies
├── requirements-local.txt      # Local development dependencies
├── .env.local.example          # Example environment variables
├── README.md                   # This file
├── README-LOCAL.md             # Local development guide
├── design.md                   # Detailed architecture guide
└── data/                       # Local test files (not in git)
```

## How It Works

### Authentication Flow

1. **Startup**: App acquires Azure Storage token via Managed Identity
2. **Request**: Middleware checks if token is still valid
3. **Refresh**: If token expires in <5 minutes, get new token
4. **Environment**: Set `AZURE_STORAGE_ACCESS_TOKEN` env var
5. **GDAL**: Reads file from `/vsiaz/` using the token
6. **Response**: TiTiler processes and returns tiles

### Token Caching

- Tokens are cached in memory with thread-safe locking
- Valid for ~60 minutes from Azure
- Refreshed automatically 5 minutes before expiry
- Shared across all uvicorn workers

### Managed Identity

Azure Web Apps can have a "managed identity" - like a service account:

- No passwords or keys needed in code
- Azure handles authentication automatically
- Can be granted RBAC permissions to resources
- Works seamlessly with `DefaultAzureCredential`

## Deployment

### Prerequisites

1. **Azure Container Registry (ACR)**
2. **Azure App Service** (Linux, container support)
3. **Azure Storage Account** with blob container
4. **Permissions** to assign roles

### Deployment Steps

See [design.md](design.md) for complete step-by-step instructions.

1. Build and push container to ACR
2. Create Azure Web App from container image
3. Enable system-assigned managed identity
4. Set `AZURE_STORAGE_ACCOUNT` environment variable
5. Grant "Storage Blob Data Reader" role to managed identity
6. Test endpoints

### Quick Deploy Commands

```bash
# 1. Build and push
az acr build --registry yourregistry --image titiler-azure:latest .

# 2. Create web app
az webapp create \
  --resource-group your-rg \
  --plan your-plan \
  --name your-titiler-app \
  --deployment-container-image-name yourregistry.azurecr.io/titiler-azure:latest

# 3. Enable managed identity
az webapp identity assign \
  --resource-group your-rg \
  --name your-titiler-app

# 4. Set storage account
az webapp config appsettings set \
  --resource-group your-rg \
  --name your-titiler-app \
  --settings AZURE_STORAGE_ACCOUNT=yourstorageaccount

# 5. Grant access (use principalId from step 3)
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee-object-id <principalId> \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>
```

## Monitoring

### View Logs

```bash
# Tail logs in real-time
az webapp log tail \
  --resource-group your-rg \
  --name your-titiler-app
```

**Look for:**
- "Azure authentication initialized successfully"
- "Token acquired, expires at ..."
- Token refresh messages every ~55 minutes

### Health Endpoint

```bash
curl https://your-app.azurewebsites.net/healthz
```

Returns:
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "local_mode": false,
  "storage_account": "yourstorageaccount",
  "token_expires_in_seconds": 3300
}
```

## Troubleshooting

### Local Development Issues

See [README-LOCAL.md](README-LOCAL.md) for local troubleshooting.

### Production Issues

#### "DefaultAzureCredential failed to retrieve a token"

**Causes:**
- Managed identity not enabled
- App restarted before identity propagated

**Solutions:**
```bash
# Verify identity is enabled
az webapp identity show --resource-group your-rg --name your-app

# Restart app
az webapp restart --resource-group your-rg --name your-app
```

#### "403 Forbidden" accessing storage

**Causes:**
- No role assignment
- Permissions not propagated yet
- Storage firewall blocking traffic

**Solutions:**
```bash
# Verify role assignment
az role assignment list \
  --assignee <principalId> \
  --scope <storage-account-resource-id>

# Wait 5-10 minutes for propagation

# Check storage firewall
az storage account show \
  --name youraccount \
  --query networkRuleSet
```

#### Slow Performance

**Solutions:**

1. **Increase workers:**
```dockerfile
CMD ["uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "8"]
```

2. **Tune GDAL cache:**
```bash
az webapp config appsettings set \
  --settings CPL_VSIL_CURL_CACHE_SIZE=256000000 GDAL_CACHEMAX=1024
```

3. **Scale up App Service Plan:**
```bash
az appservice plan update \
  --name your-plan \
  --resource-group your-rg \
  --sku P2V2
```

## Security Best Practices

1. **Least Privilege**: Use "Storage Blob Data Reader" role, not broader roles
2. **Network Security**: Configure storage account firewall to only allow App Service
3. **Monitoring**: Enable Application Insights for tracking and alerts
4. **Updates**: Regularly rebuild container with latest base image
5. **Audit**: Enable Azure Monitor logs on storage account

## Performance Optimization

### GDAL Configuration

The following environment variables optimize performance:

```bash
CPL_VSIL_CURL_CACHE_SIZE=128000000  # 128MB cache for remote files
GDAL_CACHEMAX=512                    # 512MB GDAL cache
GDAL_HTTP_MULTIPLEX=YES              # HTTP/2 multiplexing
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR  # Don't list directories
```

### Uvicorn Workers

- Default: 4 workers
- Recommendation: 2-4x number of CPU cores
- Modify in Dockerfile CMD line

### Scaling

- **Vertical**: Increase App Service Plan size (more CPU/RAM)
- **Horizontal**: Enable auto-scale rules based on CPU/memory
- Each instance gets its own managed identity token

## Advanced Topics

### Multiple Storage Accounts

See [docs/design.md](docs/design.md#multiple-storage-accounts) for supporting multiple accounts.

### User-Assigned Managed Identity

See [docs/design.md](docs/design.md#user-assigned-managed-identity) for using specific identities.

### Application Insights Integration

See [docs/design.md](docs/design.md#integration-with-application-insights) for telemetry.

## Resources

- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [GDAL Virtual File Systems](https://gdal.org/user/virtual_file_systems.html#vsiaz-microsoft-azure-blob-files)
- [Azure Managed Identities](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/overview)
- [DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential)
- [Azure App Service Containers](https://learn.microsoft.com/en-us/azure/app-service/configure-custom-container)

## Support

For issues specific to this implementation, please refer to:
- [docs/design.md](docs/design.md) - Architecture and implementation details
- [README-LOCAL.md](README-LOCAL.md) - Local development troubleshooting
- [docs/DOCUMENTATION-INDEX.md](docs/DOCUMENTATION-INDEX.md) - Complete documentation index

For TiTiler issues, see the [TiTiler GitHub repository](https://github.com/developmentseed/titiler).

## License

This implementation builds on TiTiler, which is licensed under the MIT License.
