# TiTiler-pgSTAC Configuration

**Status**: ✅ Ready for Testing
**Date**: November 8, 2025

## Current Configuration

### ✅ Database: Azure PostgreSQL

**Connection Details**:
```
Host: rmhpgflex.postgres.database.azure.com
Port: 5432
Database: geopgflex
User: rob634
Password: B@lamb634@
SSL Mode: require
```

**pgSTAC Status**: ✅ **INSTALLED AND POPULATED**
- Schema: `pgstac` (owned by pgstac_admin)
- Collections: 2
  - `system-vectors` (4 items)
  - `system-rasters` (1 item)
- Functions: 100+ pgSTAC functions available
- Tables: 18 pgSTAC tables

**Existing Data**:
```sql
-- Raster Item Example
ID: system-rasters-05APR13082706_cog_analysis-tif
Collection: system-rasters
Asset URL: https://rmhazuregeo.blob.core.windows.net/silver-cogs/05APR13082706_cog_analysis.tif
Type: Cloud-Optimized GeoTIFF
Bands: 4 (uint16)
```

### ✅ Storage: Azure Blob Storage

**Storage Account**: `rmhazuregeo`

**Authentication**: OAuth Bearer Token
- Local: Azure CLI (`az login`)
- Production: Managed Identity

**Containers**:
- `rmhazuregeobronze` - Bronze tier COG files
- `silver-cogs` - Silver tier COG files (referenced in existing STAC items)
- `rmhazuregeogold` - Gold tier
- And more...

**Access Method**:
- GDAL `/vsiaz/` paths
- OAuth token automatically injected via middleware
- Single token grants access to ALL containers (RBAC-based)

## Docker Compose Configuration

### Current Setup (Azure-Connected)

```yaml
services:
  titiler-pgstac:
    # Uses Dockerfile.local (includes Azure CLI)
    environment:
      LOCAL_MODE: "true"              # Use Azure CLI for OAuth
      USE_AZURE_AUTH: "true"          # Enable OAuth authentication
      AZURE_STORAGE_ACCOUNT: "rmhazuregeo"
      DATABASE_URL: "postgresql://rob634:B%40lamb634%40@rmhpgflex.postgres.database.azure.com:5432/geopgflex?sslmode=require"
      # GDAL optimizations for COG access
      VSI_CACHE_SIZE: "536870912"     # 512MB cache
    volumes:
      - ~/.azure:/root/.azure:ro      # Mount Azure CLI credentials
```

**Note**: No local PostgreSQL container - uses Azure PostgreSQL directly

## Verification

### Database Connection Test
```bash
PGPASSWORD='B@lamb634@' psql -h rmhpgflex.postgres.database.azure.com \
  -U rob634 -d geopgflex \
  -c "SELECT id FROM pgstac.collections;"

# Expected output:
#       id
# ----------------
# system-vectors
# system-rasters
```

### Storage Access Test
```bash
# After docker-compose up and az login
curl "http://localhost:8000/healthz" | jq .

# Expected:
# {
#   "azure_auth_enabled": true,
#   "token_status": "active",
#   "token_scope": "ALL containers (RBAC-based)",
#   "database_status": "connected"
# }
```

## API Endpoints Available

Once running, you can immediately test:

### List Existing Collections
```bash
curl http://localhost:8000/collections | jq .
```

### Search Existing Items
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"collections": ["system-rasters"]}' | jq .
```

### Get Mosaic from Existing Data
```bash
# Register search
SEARCH_ID=$(curl -X POST http://localhost:8000/searches/register \
  -H "Content-Type: application/json" \
  -d '{"collections": ["system-rasters"]}' | jq -r '.id')

# Get mosaic info
curl "http://localhost:8000/mosaic/${SEARCH_ID}/info" | jq .

# Get preview
curl "http://localhost:8000/mosaic/${SEARCH_ID}/preview.png?max_size=512" -o preview.png
```

## Key Differences from Blueprint

| Aspect | Blueprint Plan | Actual Implementation |
|--------|---------------|----------------------|
| **Database** | Local PostgreSQL container | ✅ Azure PostgreSQL (rmhpgflex) |
| **pgSTAC** | Need to install | ✅ Already installed |
| **Sample Data** | Need to load | ✅ Already has 5 items |
| **Collections** | `namangan-imagery` | ✅ `system-vectors`, `system-rasters` |
| **Storage** | `rmhazuregeobronze` | ✅ Multiple containers accessible |
| **OAuth** | Need to configure | ✅ Ready via az login |

## Next Steps

### 1. Verify Azure Login
```bash
az login
az account show
```

### 2. Start TiTiler-pgSTAC
```bash
cd /Users/robertharrison/python_builds/titilerpgstac
docker-compose up -d
```

### 3. Watch Logs
```bash
docker-compose logs -f
```

**Look for**:
```
✓ Database connection established
✓ OAuth authentication initialized successfully
✓ Using Azure CLI credentials (az login)
```

### 4. Test API
```bash
# Health check
curl http://localhost:8000/healthz | jq .

# Collections (should show system-vectors and system-rasters)
curl http://localhost:8000/collections | jq .

# Search raster items
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"collections": ["system-rasters"]}' | jq .

# API docs
open http://localhost:8000/docs
```

## Troubleshooting

### Database Connection Issues
```bash
# Test connection directly
PGPASSWORD='B@lamb634@' psql -h rmhpgflex.postgres.database.azure.com \
  -U rob634 -d geopgflex -c "SELECT 1;"

# Check Azure PostgreSQL firewall (allow your IP)
az postgres flexible-server firewall-rule list \
  --server-name rmhpgflex \
  --resource-group rmhazure_rg
```

### OAuth Issues
```bash
# Verify Azure login
az account show

# Test OAuth manually
python scripts/test_oauth.py
```

### Container Not Starting
```bash
# Check logs
docker-compose logs

# Rebuild
docker-compose build --no-cache
docker-compose up -d
```

## Production Deployment

The configuration is ready for production. To deploy:

1. Build and push Docker image to ACR
2. Create App Service with Managed Identity
3. Grant "Storage Blob Data Reader" RBAC role
4. Set environment variables (same as docker-compose, but `LOCAL_MODE=false`)
5. Deploy and verify

See [TITILER-PGSTAC-BLUEPRINT.md](TITILER-PGSTAC-BLUEPRINT.md) for detailed steps.

---

**Configuration Complete** ✅
**Database**: Azure PostgreSQL with pgSTAC and existing data
**Storage**: OAuth access to all containers
**Ready to Test**: `docker-compose up -d`
