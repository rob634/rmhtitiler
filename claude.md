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
- Zarr/NetCDF via titiler.xarray
- pgSTAC mosaic searches for STAC item collections
- OGC Features API + Vector Tiles via TiPG for PostGIS tables
- `/health` endpoint with database ping, version, hardware info

**Key endpoints:**
- `GET /livez` - Liveness probe (simple OK)
- `GET /readyz` - Readiness probe (database connectivity)
- `GET /health` - Health check with full diagnostics
- `GET /cog/info?url=...` - COG metadata
- `GET /cog/tiles/{z}/{x}/{y}` - Tile rendering
- `POST /searches/register` - Create pgSTAC mosaic search
- `GET /stac/collections` - List STAC collections
- `GET|POST /stac/search` - Search STAC items
- `GET /vector/collections` - List PostGIS collections (TiPG)
- `GET /vector/collections/{id}/items` - Query features (GeoJSON)
- `GET /vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}` - Vector tiles (MVT)
- `GET /vector/diagnostics` - TiPG table-discovery diagnostics
- `GET /h3` - H3 Explorer (interactive map)
- `GET /h3/query` - H3 DuckDB server-side query
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
| `geotiler/openapi.py` | OpenAPI schema post-processor (fixes upstream tags/descriptions) |
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
uvicorn geotiler.main:app --reload --port 8000
```

### Build & Deploy

Always build in ACR — no local Docker builds.

```bash
# Build in Azure Container Registry
az acr build --registry rmhazureacr --resource-group rmhazure_rg \
  --image rmhtitiler:v<version> .

# Deploy to App Service
az webapp config container set --name rmhtitiler --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:v<version>
az webapp restart --name rmhtitiler --resource-group rmhazure_rg
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

All app vars use `GEOTILER_COMPONENT_SETTING` convention with units in names.

| Variable | Description |
|----------|-------------|
| `GEOTILER_ENABLE_STORAGE_AUTH` | Enable OAuth for blob storage |
| `GEOTILER_AUTH_USE_CLI` | Use Azure CLI instead of Managed Identity |
| `GEOTILER_PG_HOST` | PostgreSQL server hostname |
| `GEOTILER_PG_DB` | PostgreSQL database name |
| `GEOTILER_PG_USER` | PostgreSQL username |
| `GEOTILER_PG_AUTH_MODE` | Auth mode: `password`, `key_vault`, or `managed_identity` |
| `GEOTILER_ENABLE_TIPG` | Enable TiPG OGC Features + Vector Tiles (default: true) |
| `GEOTILER_TIPG_SCHEMAS` | Comma-separated PostGIS schemas to expose (default: "geo") |
| `GEOTILER_TIPG_PREFIX` | URL prefix for TiPG routes (default: "/vector") |
| `GEOTILER_ENABLE_TIPG_CATALOG_TTL` | Enable automatic catalog refresh (default: false) |
| `GEOTILER_TIPG_CATALOG_TTL_SEC` | Catalog refresh interval in seconds (default: 60) |
| `GEOTILER_ENABLE_ADMIN_AUTH` | Enable Azure AD auth for /admin/* endpoints (default: false) |
| `GEOTILER_ADMIN_ALLOWED_APP_IDS` | Comma-separated MI client IDs allowed to call /admin/* |
| `AZURE_TENANT_ID` | Azure AD tenant ID for token validation (third-party, not prefixed) |

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
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| `docs/WIKI.md` | Complete API wiki and reference |
| `docs/DEPLOYMENT.md` | Local dev, Azure setup, env vars, build/deploy, troubleshooting |
| `docs/xarray.md` | Zarr/NetCDF implementation guide |
| `docs/TIPG_CATALOG_ARCHITECTURE.md` | **IMPORTANT** - TiPG catalog, multi-instance behavior, refresh limitations |
| `docs/TIPG_BBOX_ISSUE.md` | TiPG ST_Transform ambiguity bug (upstream issue for DevSeed) |
| `docs/DEFERRED_BUGS.md` | ETL bug triage resolution log |
| `docs/ROUTING_DESIGN.md` | Versioned asset routing design (planned, not yet implemented) |
| `DUCKDB.md` | H3 Explorer server-side DuckDB architecture |

---

## Resume Instructions

When resuming work, tell Claude:

> "Continue working on geotiler. Check /health for current status."

Claude will:
1. Check the health endpoint for version and database status
2. Review recent git commits
3. Continue from context
