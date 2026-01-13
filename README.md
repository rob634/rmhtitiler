# TiTiler-pgSTAC with Azure OAuth Authentication

A production-ready TiTiler-pgSTAC deployment with Azure Managed Identity OAuth authentication for secure, multi-container access to Azure Blob Storage.

## 🚀 Quick Start

### Production Deployment

**Live Instance**: Configure your deployed App Service URL

**API Documentation**: `https://<your-app-name>.<ase-domain>/docs`

### Local Development

```bash
# Prerequisites: Docker, Docker Compose, Azure CLI
az login

# Build and run
docker-compose up --build

# Test locally
curl http://localhost:8000/health
```

## 📖 Features

- ✅ **Azure Managed Identity OAuth** - No secrets in code, RBAC-based access
- ✅ **Multi-Container Support** - Single OAuth token for ALL containers
- ✅ **Multiple Access Patterns** - Direct COG, pgSTAC Search, OGC Features + Vector Tiles
- ✅ **Production Ready** - 4 Uvicorn workers, GDAL optimizations
- ✅ **PostgreSQL pgSTAC** - Full STAC catalog integration
- ✅ **Interactive Viewers** - Built-in map viewers for all endpoints

## 🎯 Usage Examples

### 1. Direct COG Access

**Get COG Info:**
```bash
curl "https://<your-app-url>/cog/info?url=/vsiaz/<container>/<path-to-cog>.tif"
```

**Get Tile:**
```bash
curl "https://<your-app-url>/cog/tiles/WebMercatorQuad/14/11454/6143.png?url=/vsiaz/<container>/<path-to-cog>.tif" -o tile.png
```

**Interactive Viewer:**
```
https://<your-app-url>/cog/WebMercatorQuad/map.html?url=/vsiaz/<container>/<path-to-cog>.tif
```

### 2. pgSTAC Search

**Register Search:**
```bash
curl -X POST "https://<your-app-url>/searches/register" \
  -H "Content-Type: application/json" \
  -d '{"collections":["<collection-name>"],"limit":10}'
```

**Response:**
```json
{
  "id": "<search-hash-id>",
  "links": [
    {
      "href": "https://<your-app-url>/searches/<search-hash-id>/WebMercatorQuad/tilejson.json",
      "rel": "tilejson"
    }
  ]
}
```

**Get Tile from Search:**
```bash
curl "https://<your-app-url>/searches/<search-hash-id>/tiles/WebMercatorQuad/14/11454/6143.png?assets=data" -o search_tile.png
```

**Search Viewer:**
```
https://<your-app-url>/searches/{search_id}/WebMercatorQuad/map.html?assets=data
```

### 3. OGC Features + Vector Tiles (TiPG)

**List Collections:**
```bash
curl "https://<your-app-url>/vector/collections"
```

**Query Features (GeoJSON):**
```bash
curl "https://<your-app-url>/vector/collections/<table_name>/items?limit=100"
```

**Vector Tiles (MVT):**
```
https://<your-app-url>/vector/collections/<table_name>/tiles/WebMercatorQuad/{z}/{x}/{y}
```

**Interactive Viewer:**
```
https://<your-app-url>/vector/collections/<table_name>/map
```

## 🏗️ Architecture

### Authentication Flow

```
Azure App Service (Managed Identity)
    ↓
DefaultAzureCredential → get_token("https://storage.azure.com/.default")
    ↓
OAuth Bearer Token (24hr lifetime)
    ↓
GDAL /vsiaz/ handler → AZURE_STORAGE_ACCESS_TOKEN env var
    ↓
Azure Blob Storage (RBAC: Storage Blob Data Reader)
```

### Components

- **Application**: `rmhtitiler/` - Modular FastAPI package with OAuth middleware
- **Base Image**: `ghcr.io/stac-utils/titiler-pgstac:1.9.0`
- **Database**: Azure PostgreSQL with pgSTAC extension
- **Storage**: Azure Blob Storage (multi-container support)
- **Registry**: Azure Container Registry
- **Hosting**: Azure App Service (Linux, Docker)

## 📁 Project Structure

```
rmhtitiler/
├── rmhtitiler/                 # Main application package
│   ├── __init__.py             # Version (0.7.8.x)
│   ├── app.py                  # FastAPI factory with lifespan
│   ├── config.py               # Pydantic Settings
│   ├── auth/                   # TokenCache, storage, postgres auth
│   ├── routers/                # health, planetary_computer, root, vector
│   ├── middleware/             # AzureAuthMiddleware
│   ├── services/               # database, background refresh
│   └── templates/              # HTML templates
├── Dockerfile                  # Production image (Managed Identity)
├── Dockerfile.local            # Local dev image (Azure CLI)
├── docker-compose.yml          # Local development setup
├── requirements.txt            # Python dependencies
├── README.md                   # This file
└── docs/                       # Documentation
```

## 🔐 Security Features

1. **No Secrets in Code** - All authentication via Managed Identity
2. **RBAC Least Privilege** - Storage Blob Data Reader role only
3. **No Account Keys** - OAuth tokens only, no storage account keys
4. **HTTPS Only** - All production traffic encrypted
5. **Encrypted Connection Strings** - Database credentials in App Service config

## 🛠️ Development

### Local Setup

1. **Login to Azure:**
   ```bash
   az login
   ```

2. **Copy Azure credentials for Docker:**
   ```bash
   # Credentials are copied at build time (see Dockerfile.local)
   docker-compose up --build
   ```

3. **Test locally:**
   ```bash
   curl "http://localhost:8000/health"
   curl "http://localhost:8000/cog/info?url=/vsiaz/<container>/<path-to-cog>.tif"
   ```

### Hot Reload

Changes to `rmhtitiler/` are automatically detected via volume mount:

```yaml
volumes:
  - ./rmhtitiler:/app/rmhtitiler
command: ["uvicorn", "rmhtitiler.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

## 🚢 Deployment

**For QA/Production Deployment**: See [QA_DEPLOYMENT.md](QA_DEPLOYMENT.md) for the **complete deployment guide** including:
- All required environment variables
- RBAC permissions setup (system-assigned + user-assigned managed identities)
- PostgreSQL managed identity configuration
- Step-by-step deployment workflow
- Troubleshooting guide

**Quick Deploy:**

```bash
# Set variables (replace with your values)
ACR_NAME="<your-acr-name>"
IMAGE_NAME="titiler-pgstac"
APP_NAME="<your-app-name>"
RESOURCE_GROUP="<your-resource-group>"

# Build and push
docker build --platform linux/amd64 -t $ACR_NAME.azurecr.io/$IMAGE_NAME:latest -f Dockerfile .
docker push $ACR_NAME.azurecr.io/$IMAGE_NAME:latest

# Update App Service
az webapp config appsettings set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings DOCKER_CUSTOM_IMAGE_NAME="$ACR_NAME.azurecr.io/$IMAGE_NAME:latest"

az webapp restart --name $APP_NAME --resource-group $RESOURCE_GROUP
```

## 📊 Monitoring

### Health Endpoint

The application provides a comprehensive health endpoint at `/health`:

```bash
curl https://<your-app-url>/health
```

**Response (healthy):**
```json
{
  "status": "healthy",
  "version": "0.7.8.1",
  "checks": {
    "storage": {"status": "ok", "account": "<storage-account>"},
    "database": {"status": "ok", "connected": true},
    "tipg": {"status": "ok", "pool_exists": true}
  },
  "available_features": {
    "cog_tiles": true,
    "xarray": true,
    "pgstac_searches": true,
    "planetary_computer": true,
    "ogc_features": true,
    "vector_tiles": true
  }
}
```

**Response (degraded):**
```json
{
  "status": "degraded",
  "version": "0.7.8.1",
  "checks": {
    "database": {"status": "error", "error": "connection failed"}
  }
}
```

Configure Azure App Service to use `/health` for health checks:
```bash
az webapp config set --name <app-name> --resource-group <rg> \
  --generic-configurations '{"healthCheckPath": "/health"}'
```

### Logs

```bash
# Stream logs
az webapp log tail --name <your-app-name> --resource-group <your-resource-group>

# Download logs
az webapp log download --name <your-app-name> --resource-group <your-resource-group> --log-file logs.zip
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Local | Production |
|----------|-------------|-------|------------|
| `LOCAL_MODE` | Use Azure CLI credentials | `true` | `false` |
| `USE_AZURE_AUTH` | Enable OAuth authentication | `true` | `true` |
| `AZURE_STORAGE_ACCOUNT` | Storage account name | `<your-storage-account>` | `<your-storage-account>` |
| `DATABASE_URL` | PostgreSQL connection string | Set in docker-compose.yml | Set in App Service |
| `ENABLE_PLANETARY_COMPUTER` | Enable PC credential provider | `true` | `true` |
| `ENABLE_TIPG` | Enable OGC Features + Vector Tiles | `true` | `true` |
| `TIPG_SCHEMAS` | PostGIS schemas to expose | `geo,public` | `geo,public` |
| `GDAL_*` | GDAL optimizations | Auto | Auto |

### GDAL Optimizations

```bash
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff"
GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"
GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES"
GDAL_HTTP_MULTIPLEX="YES"
GDAL_HTTP_VERSION="2"
VSI_CACHE="TRUE"
VSI_CACHE_SIZE="536870912"  # 512MB
```

## 🐛 Troubleshooting

### OAuth Token Issues

**Check Managed Identity:**
```bash
az webapp identity show --name <your-app-name> --resource-group <your-resource-group>
```

**Check RBAC Assignments:**
```bash
PRINCIPAL_ID=$(az webapp identity show --name <your-app-name> --resource-group <your-resource-group> --query principalId -o tsv)
az role assignment list --assignee $PRINCIPAL_ID
```

### Container Won't Start

**Check logs:**
```bash
az webapp log tail --name <your-app-name> --resource-group <your-resource-group>
```

**Common issues:**
- Missing DATABASE_URL environment variable
- RBAC permissions not propagated (wait 5-10 minutes)
- ACR credentials not set

### HTTP 403 Errors

1. Verify RBAC role assignment exists
2. Wait 5-10 minutes for propagation
3. Check storage account firewall rules
4. Verify OAuth token is being acquired (check logs)

## 📚 Resources

- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [TiTiler-pgSTAC](https://stac-utils.github.io/titiler-pgstac/)
- [TiPG Documentation](https://developmentseed.org/tipg/)
- [pgSTAC](https://github.com/stac-utils/pgstac)
- [GDAL /vsiaz/](https://gdal.org/user/virtual_file_systems.html#vsiaz-microsoft-azure-blob-files)
- [Azure Managed Identity](https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/)
- [Azure DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential)

## 📝 License

This project uses:
- TiTiler (MIT License)
- TiTiler-pgSTAC (MIT License)
- TiPG (MIT License)
- GDAL (MIT/X License)

## 🙏 Acknowledgments

Built with:
- [TiTiler](https://github.com/developmentseed/titiler) by Development Seed
- [TiTiler-pgSTAC](https://github.com/stac-utils/titiler-pgstac) by STAC Utils
- [TiPG](https://github.com/developmentseed/tipg) by Development Seed
- [pgSTAC](https://github.com/stac-utils/pgstac) by STAC Utils
- [Azure SDK for Python](https://github.com/Azure/azure-sdk-for-python) by Microsoft
