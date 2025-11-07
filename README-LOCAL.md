# TiTiler Local Development Setup

This directory contains a local development setup for TiTiler with optional Azure Storage authentication support.

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose installed
- (Optional) Azure CLI installed for Azure Storage testing: `brew install azure-cli`

### 2. Set Up Local Data

Create a data directory and add some test COG files:

```bash
mkdir -p data
# Add your Cloud-Optimized GeoTIFF files to the data directory
```

Don't have test COGs? Download a sample:

```bash
curl -o data/example.tif \
  "https://oin-hotosm.s3.us-east-1.amazonaws.com/5afeda152b6a08001185f11a/0/5afeda152b6a08001185f11b.tif"
```

### 3. Start the Server

```bash
# Build and start the container
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build
```

The server will be available at http://localhost:8000

### 4. Test the Server

```bash
# Health check
curl http://localhost:8000/healthz

# API documentation
open http://localhost:8000/docs

# Get info about a local file
curl "http://localhost:8000/cog/info?url=/data/example.tif"

# View a tile (returns PNG image)
curl "http://localhost:8000/cog/tiles/WebMercatorQuad/14/3876/6325?url=/data/example.tif" \
  --output tile.png
```

## Development Modes

### Mode 1: Pure Local Development (Default)

Test with local files only, no Azure:

```yaml
# In docker-compose.yml
environment:
  - LOCAL_MODE=true
  - USE_AZURE_AUTH=false
```

**Test with:**
```bash
curl "http://localhost:8000/cog/info?url=/data/your-file.tif"
```

### Mode 2: Local Development with Azure Storage

Test Azure Storage access using your Azure CLI credentials:

```bash
# Step 1: Login to Azure
az login

# Step 2: Update docker-compose.yml
# Set USE_AZURE_AUTH=true and add your storage account name
environment:
  - LOCAL_MODE=true
  - USE_AZURE_AUTH=true
  - AZURE_STORAGE_ACCOUNT=yourstorageaccount

# Step 3: Restart
docker-compose down
docker-compose up --build
```

**Test with:**
```bash
curl "http://localhost:8000/cog/info?url=/vsiaz/yourcontainer/path/to/file.tif"
```

### Mode 3: Local with Service Principal

Use explicit Azure credentials (for CI/CD or when `az login` isn't available):

```bash
# Create .env.local from example
cp .env.local.example .env.local

# Edit .env.local and add:
# AZURE_CLIENT_ID=your_client_id
# AZURE_CLIENT_SECRET=your_client_secret
# AZURE_TENANT_ID=your_tenant_id
# AZURE_STORAGE_ACCOUNT=yourstorageaccount

# Update docker-compose.yml to use .env.local
env_file:
  - .env.local
```

## Development Workflow

### Making Code Changes

The local setup uses `--reload` flag, so code changes are automatically detected:

1. Edit `custom_main.py`
2. Save the file
3. Server automatically restarts
4. Test your changes

### Viewing Logs

```bash
# Follow logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f titiler
```

### Stopping the Server

```bash
# Stop but keep containers
docker-compose stop

# Stop and remove containers
docker-compose down

# Stop and remove everything including volumes
docker-compose down -v
```

## Testing Azure Storage Locally

### Prerequisites

1. **Azure Storage Account** with a blob container
2. **Azure CLI authenticated**: `az login`
3. **Permission to read blobs** - assign yourself the "Storage Blob Data Reader" role:

```bash
# Get your user ID
USER_ID=$(az ad signed-in-user show --query id -o tsv)

# Assign role
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $USER_ID \
  --scope /subscriptions/<subscription-id>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>
```

### Testing Steps

1. **Upload a test COG to Azure Storage:**

```bash
az storage blob upload \
  --account-name yourstorageaccount \
  --container-name yourcontainer \
  --name test/example.tif \
  --file data/example.tif \
  --auth-mode login
```

2. **Configure docker-compose.yml:**

```yaml
environment:
  - USE_AZURE_AUTH=true
  - AZURE_STORAGE_ACCOUNT=yourstorageaccount
```

3. **Restart and test:**

```bash
docker-compose up --build

# Test the Azure-stored file
curl "http://localhost:8000/cog/info?url=/vsiaz/yourcontainer/test/example.tif"
```

## Troubleshooting

### Issue: "DefaultAzureCredential failed to retrieve a token"

**Solution:**
```bash
# Make sure you're logged in
az login

# Verify your credentials work
az account show

# Restart the container
docker-compose restart
```

### Issue: "No module named 'azure.identity'"

**Solution:**
```bash
# Rebuild the image
docker-compose down
docker-compose up --build
```

### Issue: "403 Forbidden" when accessing Azure Storage

**Solutions:**

1. Check you have permission:
```bash
# List your role assignments
az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>
```

2. Check storage account allows your IP:
```bash
# Update storage firewall to allow your IP
az storage account network-rule add \
  --account-name yourstorageaccount \
  --ip-address $(curl -s ifconfig.me)
```

3. Wait 5-10 minutes for permissions to propagate

### Issue: Container keeps restarting

**Solution:**
```bash
# Check logs
docker-compose logs

# Remove volumes and rebuild
docker-compose down -v
docker-compose up --build
```

### Issue: "Cannot find file /data/example.tif"

**Solution:**
```bash
# Check data directory exists and has files
ls -la data/

# Make sure docker-compose.yml has the volume mount:
# volumes:
#   - ./data:/data:ro
```

## Performance Tips

### GDAL Configuration

The following environment variables are set for optimal performance:

```yaml
- CPL_VSIL_CURL_CACHE_SIZE=128000000  # 128MB cache for remote files
- GDAL_CACHEMAX=512                    # 512MB GDAL cache
- GDAL_HTTP_MULTIPLEX=YES              # Enable HTTP/2 multiplexing
- GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR  # Don't list directories
```

### Docker Resource Limits

If processing large COGs, increase Docker resources:

```bash
# Check current limits
docker info | grep -A 5 "CPUs\|Memory"

# Update Docker Desktop settings:
# - CPUs: 4+
# - Memory: 8GB+
```

## File Structure

```
rmhtitiler/
├── custom_main.py              # TiTiler app with Azure auth
├── Dockerfile.local            # Local development Docker image
├── docker-compose.yml          # Local development orchestration
├── requirements-local.txt      # Python dependencies
├── .env.local.example          # Example environment variables
├── README-LOCAL.md             # This file
├── data/                       # Local test COG files
│   └── example.tif
└── design.md                   # Architecture documentation
```

## Next Steps

Once local development is working:

1. Review [design.md](design.md) for production deployment
2. Create production Dockerfile (without --reload, more workers)
3. Deploy to Azure App Service
4. Configure Managed Identity
5. Test production endpoints

## Useful Commands

```bash
# Rebuild without cache
docker-compose build --no-cache

# Run with specific compose file
docker-compose -f docker-compose.yml up

# Execute commands in running container
docker-compose exec titiler bash

# Check GDAL version and drivers
docker-compose exec titiler gdalinfo --version
docker-compose exec titiler gdalinfo --formats | grep Azure

# View real-time logs with timestamps
docker-compose logs -f --timestamps

# Remove all stopped containers and images
docker system prune -a
```

## Resources

- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [GDAL Virtual File Systems](https://gdal.org/user/virtual_file_systems.html)
- [Azure DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
