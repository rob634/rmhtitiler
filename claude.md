# TiTiler Container

A containerized geospatial tile server for Azure App Service.

## Architecture

```
Container (Azure App Service / Docker)
└── TiTiler App (port 8000)
    └── FastAPI tile server with pgSTAC + Azure OAuth
```

### TiTiler App (`geotiler/`)

Dynamic tile server for Cloud Optimized GeoTIFFs (COGs), Zarr/NetCDF arrays, and PostGIS vector data.

**Features:**
- COG tiles via GDAL with Azure Blob Storage OAuth
- Zarr/NetCDF via titiler.xarray with Planetary Computer support
- pgSTAC mosaic searches for STAC item collections
- OGC Features API + Vector Tiles via TiPG for PostGIS tables
- `/health` endpoint with database ping, version, hardware info

**Key endpoints:**
- `GET /health` - Health check with full diagnostics
- `GET /cog/info?url=...` - COG metadata
- `GET /cog/tiles/{z}/{x}/{y}` - Tile rendering
- `GET /searches/register` - Create pgSTAC mosaic search
- `GET /vector/collections` - List PostGIS collections (TiPG)
- `GET /vector/collections/{id}/items` - Query features (GeoJSON)
- `GET /vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}` - Vector tiles (MVT)

---

## Key Files

| File | Purpose |
|------|---------|
| `geotiler/app.py` | Main FastAPI app with OAuth |
| `geotiler/config.py` | Environment configuration |
| `geotiler/routers/health.py` | Health probe endpoints |
| `geotiler/routers/vector.py` | TiPG integration (OGC Features + Vector Tiles) |
| `Dockerfile` | Production image (Managed Identity) |
| `Dockerfile.local` | Local dev image (Azure CLI credentials) |
| `docker-compose.yml` | Local development setup |

---

## Development

### Run Locally

```bash
# Option 1: Docker Compose (recommended)
docker-compose up --build

# Option 2: Direct Python (requires local PostgreSQL)
uvicorn geotiler.app:app --reload --port 8000
```

### Build & Deploy

```bash
# Build for Azure
docker build --platform linux/amd64 -t <acr>.azurecr.io/titiler-pgstac:v<version> .

# Push to ACR
az acr login --name <acr>
docker push <acr>.azurecr.io/titiler-pgstac:v<version>

# Update App Service
az webapp config container set --name <app> --resource-group <rg> \
  --docker-custom-image-name <acr>.azurecr.io/titiler-pgstac:v<version>
```

### Version Management

Single source of truth: `__version__` in `geotiler/__init__.py`

```bash
# Check current version
grep "__version__" geotiler/__init__.py
```

---

## Environment Variables

See [WIKI.md](WIKI.md) for complete list. Key variables:

| Variable | Description |
|----------|-------------|
| `USE_AZURE_AUTH` | Enable OAuth for blob storage |
| `LOCAL_MODE` | Use Azure CLI instead of Managed Identity |
| `DATABASE_URL` | PostgreSQL connection string |
| `ENABLE_PLANETARY_COMPUTER` | Enable PC credential provider for public data |
| `ENABLE_TIPG` | Enable TiPG OGC Features + Vector Tiles (default: true) |
| `TIPG_SCHEMAS` | Comma-separated PostGIS schemas to expose (default: "geo") |
| `TIPG_ROUTER_PREFIX` | URL prefix for TiPG routes (default: "/vector") |

---

## Testing

```bash
# Health check
curl http://localhost:8000/health | jq

# COG info
curl "http://localhost:8000/cog/info?url=https://example.com/file.tif"

# TiPG - List vector collections
curl http://localhost:8000/vector/collections | jq

# TiPG - Query features from a collection
curl "http://localhost:8000/vector/collections/my_table/items?limit=10" | jq

# TiPG - Get vector tile
curl "http://localhost:8000/vector/collections/my_table/tiles/WebMercatorQuad/10/512/384"
```

---

## Archived Documentation

- [QA Deployment Dec 2025](docs/archive/QA-DEPLOYMENT-DEC2025.md) - QA environment specifics
- [Azure Deployment Prep](docs/archive/AZURE-DEPLOYMENT-PREP.md) - Initial setup notes

---

## Resume Instructions

When resuming work, tell Claude:

> "Continue working on geotiler. Check /health for current status."

Claude will:
1. Check the health endpoint for version and database status
2. Review recent git commits
3. Continue from context
