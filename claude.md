# TiTiler + Dashboard Container

A containerized geospatial platform with two integrated applications.

## Architecture

```
Container (Azure App Service / Docker)
├── TiTiler App (port 8000)
│   └── FastAPI tile server with pgSTAC + Azure OAuth
└── NiceGUI Dashboard (mounted at /dashboard)
    └── Admin UI for monitoring and data exploration
```

### 1. TiTiler App (`custom_pgstac_main.py`)

Dynamic tile server for Cloud Optimized GeoTIFFs (COGs) and Zarr/NetCDF arrays.

**Features:**
- COG tiles via GDAL with Azure Blob Storage OAuth
- Zarr/NetCDF via titiler.xarray with Planetary Computer support
- pgSTAC mosaic searches for STAC item collections
- `/healthz` endpoint with database ping, version, hardware info

**Key endpoints:**
- `GET /healthz` - Health check with full diagnostics
- `GET /cog/info?url=...` - COG metadata
- `GET /cog/tiles/{z}/{x}/{y}` - Tile rendering
- `GET /searches/register` - Create pgSTAC mosaic search

### 2. NiceGUI Dashboard (`dashboard/`)

Admin interface mounted onto TiTiler at `/dashboard`.

**Pages:**
- `/dashboard` - Home with architecture overview
- `/dashboard/status` - TiTiler + Platform API health
- `/dashboard/pipelines` - Job queue monitoring (requires Platform API)
- `/dashboard/explorer` - STAC collection browser

**Can run standalone:**
```bash
python -m dashboard.main  # Runs on port 8080
```

---

## Key Files

| File | Purpose |
|------|---------|
| `custom_pgstac_main.py` | Main FastAPI app with OAuth, mounts dashboard |
| `dashboard/main.py` | NiceGUI app entry point |
| `dashboard/client.py` | HTTP clients for TiTiler and Platform API |
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
uvicorn custom_pgstac_main:app --reload --port 8000
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

Single source of truth: `__version__` in `custom_pgstac_main.py`

```bash
# Check current version
grep "^__version__" custom_pgstac_main.py

# After incrementing, also update FastAPI version parameter
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
| `ENABLE_DASHBOARD` | Mount NiceGUI at /dashboard (default: true) |
| `PLATFORM_API_URL` | URL for job queue/pipeline monitoring |

---

## Testing

```bash
# Health check
curl http://localhost:8000/healthz | jq

# COG info
curl "http://localhost:8000/cog/info?url=https://example.com/file.tif"

# Dashboard
open http://localhost:8000/dashboard
```

---

## Archived Documentation

- [QA Deployment Dec 2025](docs/archive/QA-DEPLOYMENT-DEC2025.md) - QA environment specifics
- [Azure Deployment Prep](docs/archive/AZURE-DEPLOYMENT-PREP.md) - Initial setup notes

---

## Resume Instructions

When resuming work, tell Claude:

> "Continue working on rmhtitiler. Check /healthz for current status."

Claude will:
1. Check the health endpoint for version and database status
2. Review recent git commits
3. Continue from context