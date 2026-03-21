# Deployment Guide

**Covers:** Local development, Azure resource setup, environment variables, build/deploy, and troubleshooting.

**Replaces:** `QA_DEPLOYMENT.md`, `NEW_TENANT_DEPLOYMENT.md`, `AZURE-CONFIGURATION-REFERENCE.md`, `README-LOCAL.md` (all archived).

---

## Table of Contents

1. [Local Development](#1-local-development)
2. [Azure Resource Setup](#2-azure-resource-setup)
3. [Managed Identity Configuration](#3-managed-identity-configuration)
4. [PostgreSQL Setup](#4-postgresql-setup)
5. [Environment Variables](#5-environment-variables)
6. [Build and Deploy](#6-build-and-deploy)
7. [Verification](#7-verification)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Local Development

### Prerequisites

- Docker and Docker Compose
- (Optional) Azure CLI for authenticated storage testing: `brew install azure-cli`

### Quick Start

```bash
# Start the server
docker-compose up --build

# Server available at http://localhost:8000
```

For Azure Storage access locally, log in to Azure CLI first:

```bash
az login
```

The app uses `GEOTILER_AUTH_USE_CLI=true` (the default) to pick up Azure CLI credentials via `DefaultAzureCredential`. No secrets needed.

### Service Principal Auth (CI/CD)

When `az login` isn't available (CI pipelines), set these standard Azure Identity SDK variables:

```bash
AZURE_CLIENT_ID=your_client_id
AZURE_CLIENT_SECRET=your_client_secret
AZURE_TENANT_ID=your_tenant_id
```

These are picked up automatically by `DefaultAzureCredential` — no code changes needed.

### Test Endpoints

```bash
# Health check
curl http://localhost:8000/health | jq

# COG info (requires storage access)
curl "http://localhost:8000/cog/info?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif"

# Vector collections (requires PostgreSQL)
curl http://localhost:8000/vector/collections | jq

# Liveness (always works, no dependencies)
curl http://localhost:8000/livez
```

---

## 2. Azure Resource Setup

This section is for standing up a brand new environment from scratch.

### Resource Group

```bash
az group create --name rmhazure_rg --location eastus
```

### Azure Container Registry

```bash
az acr create --name rmhazureacr --resource-group rmhazure_rg \
  --sku Basic --admin-enabled true
```

Admin must be enabled for App Service to pull images.

### App Service

```bash
# Create App Service Plan (Linux, B2 or higher recommended)
az appservice plan create --name rmhtitiler-plan --resource-group rmhazure_rg \
  --is-linux --sku B2

# Create Web App
az webapp create --name rmhtitiler --resource-group rmhazure_rg \
  --plan rmhtitiler-plan \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:v<version>

# Required App Service settings
az webapp config set --resource-group rmhazure_rg --name rmhtitiler \
  --always-on true

az webapp config appsettings set --resource-group rmhazure_rg --name rmhtitiler \
  --settings WEBSITES_PORT=8000 WEBSITES_ENABLE_APP_SERVICE_STORAGE=false
```

### PostgreSQL Flexible Server

```bash
az postgres flexible-server create \
  --name <server-name> --resource-group rmhazure_rg \
  --location eastus --admin-user pgadmin \
  --admin-password "..." --sku-name Standard_B2s \
  --tier Burstable --storage-size 32 --version 15

# Enable required extensions
psql -h <server>.postgres.database.azure.com -U pgadmin -d geopgflex -c \
  "CREATE EXTENSION IF NOT EXISTS postgis;"
psql -h <server>.postgres.database.azure.com -U pgadmin -d geopgflex -c \
  "CREATE EXTENSION IF NOT EXISTS pgstac;"
```

### Firewall — Allow Azure Services

```bash
az postgres flexible-server firewall-rule create \
  --resource-group rmhazure_rg --name <server-name> \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
```

---

## 3. Managed Identity Configuration

### System-Assigned MI (for Azure Blob Storage)

```bash
# Enable system-assigned MI
az webapp identity assign --name rmhtitiler --resource-group rmhazure_rg

# Get the principal ID
SYSTEM_MI_PRINCIPAL=$(az webapp identity show \
  --name rmhtitiler --resource-group rmhazure_rg --query principalId -o tsv)

# Grant Storage Blob Data Reader on the storage account
az role assignment create \
  --assignee $SYSTEM_MI_PRINCIPAL \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/$(az account show --query id -o tsv)/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhstorage123
```

### User-Assigned MI (for PostgreSQL)

```bash
# Create the identity
az identity create --name titiler-db-access --resource-group rmhazure_rg --location eastus

# Get the resource ID
USER_MI_RESOURCE_ID=$(az identity show --name titiler-db-access \
  --resource-group rmhazure_rg --query id -o tsv)

# Assign to web app
az webapp identity assign --name rmhtitiler --resource-group rmhazure_rg \
  --identities $USER_MI_RESOURCE_ID

# Verify both identities
az webapp identity show --name rmhtitiler --resource-group rmhazure_rg
```

RBAC propagation can take 5-10 minutes. Restart the app after assigning roles.

---

## 4. PostgreSQL Setup

### Create the MI Database User

The PostgreSQL username **must exactly match** the Managed Identity name.

```sql
-- Connect as admin to the target database
SET aad_validate_oids_in_tenant = off;

-- Create AAD principal (name MUST match MI name exactly)
SELECT * FROM pgaadauth_create_principal('titiler-db-access', false, false);
```

### Grant Permissions

**Read-only (recommended for production):**

```sql
-- pgSTAC schema (for COG tiles, STAC catalog)
GRANT USAGE ON SCHEMA pgstac TO "titiler-db-access";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-access";
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT ON TABLES TO "titiler-db-access";

-- geo schema (for TiPG vector tiles)
GRANT USAGE ON SCHEMA geo TO "titiler-db-access";
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO "titiler-db-access";
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO "titiler-db-access";

-- For /searches/register (mosaic search write access)
GRANT INSERT, UPDATE, DELETE ON pgstac.searches TO "titiler-db-access";
```

### The ALTER DEFAULT PRIVILEGES Per-Grantor Gotcha

`ALTER DEFAULT PRIVILEGES` only applies to tables created by the user who ran the command. If an ETL identity creates tables, the reader identity won't have access.

**Diagnose:**

```sql
-- See which roles own tables:
SELECT tableowner, COUNT(*) as table_count
FROM pg_tables WHERE schemaname = 'geo'
GROUP BY tableowner ORDER BY table_count DESC;

-- See existing default privilege grants:
SELECT pg_get_userbyid(defaclrole) as grantor,
       defaclnamespace::regnamespace as schema,
       defaclobjtype as object_type,
       defaclacl as privileges
FROM pg_default_acl
WHERE defaclnamespace = 'geo'::regnamespace;
```

**Fix — grant on behalf of the ETL role:**

```sql
-- As superadmin: grant defaults for tables created by the ETL identity
ALTER DEFAULT PRIVILEGES FOR ROLE "etl-admin-identity" IN SCHEMA geo
GRANT SELECT ON TABLES TO "titiler-db-access";

-- Backfill existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO "titiler-db-access";
```

**Alternative — shared owner role:**

```sql
CREATE ROLE geo_table_owner;
GRANT geo_table_owner TO "etl-admin-identity";
GRANT geo_table_owner TO "titiler-db-access";
ALTER DEFAULT PRIVILEGES FOR ROLE geo_table_owner IN SCHEMA geo
GRANT SELECT ON TABLES TO "titiler-db-access";
-- ETL then: SET ROLE geo_table_owner; CREATE TABLE ...; RESET ROLE;
```

### Verify

```sql
SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'titiler-db-access';

SELECT grantee, table_name, privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'titiler-db-access' AND table_schema = 'pgstac'
ORDER BY table_name, privilege_type;
```

You can also use the app's built-in diagnostics endpoint:

```bash
curl "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/vector/diagnostics" | jq
```

---

## 5. Environment Variables

### Naming Convention

All application settings use the `GEOTILER_` prefix: `GEOTILER_COMPONENT_SETTING`.

- Boolean flags: `GEOTILER_ENABLE_*`
- Time values include units: `*_SEC`, `*_MS`
- Third-party vars are NOT prefixed: `APPLICATIONINSIGHTS_CONNECTION_STRING`, `GDAL_*`

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| **Auth** | | |
| `GEOTILER_ENABLE_STORAGE_AUTH` | `false` | Enable Azure OAuth for blob storage |
| `GEOTILER_STORAGE_ACCOUNT` | — | Azure Storage account name |
| `GEOTILER_AUTH_USE_CLI` | `true` | Use Azure CLI credentials (local dev). Set `false` for MI in production. |
| **PostgreSQL** | | |
| `GEOTILER_PG_AUTH_MODE` | `password` | Auth mode: `password`, `key_vault`, `managed_identity` |
| `GEOTILER_PG_HOST` | — | PostgreSQL server hostname |
| `GEOTILER_PG_DB` | — | Database name |
| `GEOTILER_PG_USER` | — | Username (must match MI name for MI auth) |
| `GEOTILER_PG_PORT` | `5432` | PostgreSQL port |
| `GEOTILER_PG_PASSWORD` | — | Password (for `password` auth mode only) |
| `GEOTILER_PG_MI_CLIENT_ID` | — | User-assigned MI client ID (for `managed_identity` mode) |
| **Key Vault** | | |
| `GEOTILER_KEYVAULT_NAME` | — | Azure Key Vault name (for `key_vault` auth mode) |
| `GEOTILER_KEYVAULT_SECRET_NAME` | `postgres-password` | Secret name containing PG password |
| **Feature Flags** | | |
| `GEOTILER_ENABLE_COG` | `true` | Enable COG tile endpoints (`/cog/*`) |
| `GEOTILER_ENABLE_XARRAY` | `true` | Enable Zarr/NetCDF tile endpoints (`/xarray/*`) |
| `GEOTILER_ENABLE_PGSTAC_SEARCH` | `true` | Enable pgSTAC mosaic search endpoints (`/searches/*`) |
| `GEOTILER_ENABLE_TIPG` | `true` | Enable TiPG (OGC Features + Vector Tiles) |
| `GEOTILER_ENABLE_STAC_API` | `true` | Enable STAC catalog API |
| `GEOTILER_ENABLE_H3_DUCKDB` | `false` | Enable server-side DuckDB for H3 queries |
| `GEOTILER_ENABLE_DOWNLOADS` | `false` | Enable download endpoints |
| **TiPG** | | |
| `GEOTILER_TIPG_SCHEMAS` | `geo` | Comma-separated PostGIS schemas to expose |
| `GEOTILER_TIPG_PREFIX` | `/vector` | URL prefix for TiPG routes |
| `GEOTILER_ENABLE_TIPG_CATALOG_TTL` | `false` | Enable automatic catalog refresh |
| `GEOTILER_TIPG_CATALOG_TTL_SEC` | `60` | Refresh interval in seconds |
| **STAC** | | |
| `GEOTILER_STAC_PREFIX` | `/stac` | URL prefix for STAC routes |
| **Connection Pools** | | |
| `GEOTILER_POOL_TIPG_MIN` | `1` | TiPG asyncpg pool minimum connections |
| `GEOTILER_POOL_TIPG_MAX` | `7` | TiPG asyncpg pool maximum connections |
| `GEOTILER_POOL_STAC_MIN` | `1` | STAC asyncpg pool minimum connections |
| `GEOTILER_POOL_STAC_MAX` | `7` | STAC asyncpg pool maximum connections |
| `GEOTILER_POOL_PGSTAC_MIN` | `1` | titiler-pgstac psycopg pool minimum connections |
| `GEOTILER_POOL_PGSTAC_MAX` | `7` | titiler-pgstac psycopg pool maximum connections |
| `GEOTILER_DB_STATEMENT_TIMEOUT_MS` | `30000` | Per-connection query timeout (ms). Kills stuck queries. Set 0 to disable. |
| **H3 Explorer** | | |
| `GEOTILER_H3_PARQUET_URL` | — | Azure Blob URL to the H3 GeoParquet file |
| `GEOTILER_H3_DATA_DIR` | `/app/data` | Local directory for cached parquet file |
| `GEOTILER_H3_PARQUET_FILENAME` | `h3_data.parquet` | Filename for the local cache |
| **Observability** | | |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | — | App Insights connection string (third-party, not prefixed) |
| `GEOTILER_ENABLE_OBSERVABILITY` | `false` | Enable detailed request/latency logging |
| `GEOTILER_OBS_SLOW_THRESHOLD_MS` | `2000` | Slow request threshold |

### GDAL Environment Variables

These are third-party variables (no `GEOTILER_` prefix) that tune COG tile performance:

| Variable | Recommended Value | Purpose |
|----------|-------------------|---------|
| `GDAL_DISABLE_READDIR_ON_OPEN` | `EMPTY_DIR` | Skip directory listing on open — critical for cloud storage |
| `GDAL_HTTP_MERGE_CONSECUTIVE_RANGES` | `YES` | Merge adjacent byte-range requests |
| `GDAL_HTTP_MULTIPLEX` | `YES` | Enable HTTP/2 multiplexing |
| `GDAL_HTTP_VERSION` | `2` | Force HTTP/2 |
| `VSI_CACHE` | `TRUE` | Enable GDAL virtual filesystem caching |
| `VSI_CACHE_SIZE` | `536870912` | 512 MB VSICURL cache |
| `GDAL_CACHEMAX` | `512` | GDAL raster block cache in MB |

### App Service Platform Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `WEBSITES_PORT` | `8000` | Container listen port |
| `WEBSITES_ENABLE_APP_SERVICE_STORAGE` | `false` | Disable unnecessary storage mount |

---

## 6. Build and Deploy

### Build in ACR (no local Docker needed)

```bash
az acr build --registry rmhazureacr --resource-group rmhazure_rg \
  --image rmhtitiler:v<version> .
```

### Deploy to App Service

```bash
az webapp config container set --name rmhtitiler --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:v<version>

az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

### Set Environment Variables

```bash
az webapp config appsettings set --resource-group rmhazure_rg --name rmhtitiler \
  --settings \
    GEOTILER_ENABLE_STORAGE_AUTH=true \
    GEOTILER_AUTH_USE_CLI=false \
    GEOTILER_PG_AUTH_MODE=managed_identity \
    GEOTILER_PG_HOST=<server>.postgres.database.azure.com \
    GEOTILER_PG_DB=geopgflex \
    GEOTILER_PG_USER=titiler-db-access \
    GEOTILER_PG_MI_CLIENT_ID=<mi-client-id>
```

### Rollback

```bash
# Deploy previous version
az webapp config container set --name rmhtitiler --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/rmhtitiler:v<previous-version>

az webapp restart --name rmhtitiler --resource-group rmhazure_rg
```

---

## 7. Verification

### Health Check

```bash
curl https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/health | jq
```

Expected: all services `healthy`, correct version number.

### Smoke Test — All Service Families

```bash
BASE=https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net

# COG
curl -sf "$BASE/cog/info?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif" | jq .bounds

# Zarr
curl -sf "$BASE/xarray/variables?url=abfs://silver-zarr/cmip6-tasmax-sample.zarr" | jq

# Vector
curl -sf "$BASE/vector/collections" | jq '.collections | length'

# STAC
curl -sf "$BASE/stac/collections" | jq '.collections | length'

# Probes
curl -sf "$BASE/livez"
curl -sf "$BASE/readyz"
```

### Audit Current Settings

```bash
az webapp config appsettings list \
  --resource-group rmhazure_rg --name rmhtitiler --output table
```

### Stream Logs

```bash
az webapp log tail --name rmhtitiler --resource-group rmhazure_rg
```

---

## 8. Troubleshooting

| Symptom | Diagnosis | Fix |
|---------|-----------|-----|
| "Failed to acquire PostgreSQL OAuth token" | MI not assigned or PG user missing | `az webapp identity show`, verify `pg_roles` |
| "Role 'xxx' does not exist" in PG | Username doesn't match MI name exactly | Recreate with `pgaadauth_create_principal` using exact MI name |
| HTTP 403 on storage | RBAC not propagated yet | Wait 5-10 min, restart app, `az role assignment list` |
| Connection timeout to PostgreSQL | Firewall blocking | Add AllowAzureServices rule |
| "Permission denied for table X" | ETL per-grantor issue (see Section 4) | Run `/vector/diagnostics`, check tableowner |
| Container fails to pull from ACR | Admin not enabled or wrong credentials | `az acr update --admin-enabled true` |
| App doesn't start / no logs | Wrong port config | Ensure `WEBSITES_PORT=8000` |
| Vector tiles stale after ETL | Multi-instance catalog issue | See `docs/TIPG_CATALOG_ARCHITECTURE.md` |
| Zarr tiles fail with auth error | Using `https://` URL instead of `abfs://` | Use `abfs://container/path.zarr` scheme |
