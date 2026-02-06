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
- `POST /admin/refresh-collections` - Webhook to refresh TiPG catalog (ETL integration, see note below)

**TiPG Multi-Instance Warning:** In multi-instance deployments (ASE), the refresh webhook only updates ONE instance. Other instances keep stale catalogs until they restart or TTL refresh triggers. See `docs/TIPG_CATALOG_ARCHITECTURE.md` for details and workarounds.

---

## Key Files

| File | Purpose |
|------|---------|
| `geotiler/app.py` | Main FastAPI app with OAuth |
| `geotiler/config.py` | Environment configuration |
| `geotiler/routers/health.py` | Health probe endpoints |
| `geotiler/routers/vector.py` | TiPG integration (OGC Features + Vector Tiles) |
| `geotiler/routers/admin.py` | Admin dashboard + refresh-collections webhook |
| `geotiler/auth/admin_auth.py` | Azure AD token validation for admin endpoints |
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

See [docs/WIKI.md](docs/WIKI.md) for complete list. Key variables:

| Variable | Description |
|----------|-------------|
| `USE_AZURE_AUTH` | Enable OAuth for blob storage |
| `LOCAL_MODE` | Use Azure CLI instead of Managed Identity |
| `DATABASE_URL` | PostgreSQL connection string |
| `ENABLE_PLANETARY_COMPUTER` | Enable PC credential provider for public data |
| `ENABLE_TIPG` | Enable TiPG OGC Features + Vector Tiles (default: true) |
| `TIPG_SCHEMAS` | Comma-separated PostGIS schemas to expose (default: "geo") |
| `TIPG_ROUTER_PREFIX` | URL prefix for TiPG routes (default: "/vector") |
| `TIPG_CATALOG_TTL_ENABLED` | Enable automatic catalog refresh (default: false) |
| `TIPG_CATALOG_TTL` | Catalog refresh interval in seconds when TTL enabled (default: 300) |
| `ADMIN_AUTH_ENABLED` | Enable Azure AD auth for /admin/* endpoints (default: false) |
| `ADMIN_ALLOWED_APP_IDS` | Comma-separated MI client IDs allowed to call /admin/* |
| `AZURE_TENANT_ID` | Azure AD tenant ID for token validation |
| `ENABLE_VERSIONED_ASSETS` | Enable `/assets/{dataset}/{resource}?version=latest` routing |
| `RMHGEOAPI_POSTGRES_HOST` | rmhgeoapi database host (for versioned assets) |
| `RMHGEOAPI_POSTGRES_DB` | rmhgeoapi database name |
| `RMHGEOAPI_POSTGRES_USER` | Database user (read-only access to app.geospatial_assets) |
| `RMHGEOAPI_POSTGRES_PASSWORD` | Database password |

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

# Refresh TiPG catalog (after ETL creates new tables)
curl -X POST http://localhost:8000/admin/refresh-collections | jq

# Versioned Assets (if ENABLE_VERSIONED_ASSETS=true)
curl "http://localhost:8000/assets/floods/jakarta/tiles/10/512/384?version=latest"
curl "http://localhost:8000/assets/floods/jakarta/versions"
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| `docs/WIKI.md` | Complete API wiki and reference |
| `docs/QA_DEPLOYMENT.md` | QA/Production deployment guide |
| `docs/README-LOCAL.md` | Local development setup |
| `docs/xarray.md` | Zarr/NetCDF implementation guide |
| `docs/NEW_TENANT_DEPLOYMENT.md` | Multi-tenant deployment |
| `docs/VERSIONED_ASSETS_IMPLEMENTATION.md` | `?version=latest` routing (V0.8) |
| `docs/TIPG_CATALOG_ARCHITECTURE.md` | **IMPORTANT** - TiPG catalog, multi-instance behavior, refresh limitations |

---

## Resume Instructions

When resuming work, tell Claude:

> "Continue working on geotiler. Check /health for current status."

Claude will:
1. Check the health endpoint for version and database status
2. Review recent git commits
3. Continue from context
