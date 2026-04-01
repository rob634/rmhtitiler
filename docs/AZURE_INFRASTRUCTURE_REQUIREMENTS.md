# Azure Infrastructure Requirements — rmhtitiler

Technical configuration outline for deploying rmhtitiler to a new Azure environment (QA, UAT, etc).

---

## App Service

- **OS/Type**: Linux, Container
- **SKU**: PremiumV3 or equivalent (~4 GB RAM minimum)
- **Always On**: enabled
- **HTTPS Only**: enabled
- **Minimum TLS**: 1.2
- **Client Affinity**: disabled (no sticky sessions)
- **Container source**: Azure Container Registry

## Container Registry (ACR)

- App Service needs **AcrPull** role on the registry
- Alternatively: set `DOCKER_REGISTRY_SERVER_URL`, `_USERNAME`, `_PASSWORD` in app settings

## CORS

- **Allowed Origins**: `*` (or restrict to specific front-end domains)
- **Support Credentials**: `false`
- If traffic passes through Azure Front Door or APIM, CORS must also be configured there — App Service CORS alone won't apply behind a proxy

## Iframe Embedding (/preview/* endpoints)

The app sets `Content-Security-Policy: frame-ancestors *` and `X-Frame-Options: ALLOWALL` in code on `/preview/*` responses. No Azure-level configuration needed **unless**:

- A WAF, Front Door, or APIM policy injects `X-Frame-Options: DENY` or a restrictive `Content-Security-Policy` globally — this would override the app's headers and block iframe embedding
- Confirm no upstream proxy strips or overrides these headers

## Managed Identities

| Identity | Type | Purpose | RBAC Role Required |
|----------|------|---------|-------------------|
| System-assigned | System | General App Service identity | — |
| PostgreSQL reader | User-assigned | Database auth (Entra token) | PostgreSQL Flexible Server reader |
| Storage reader | User-assigned | Blob storage OAuth | Storage Blob Data Reader on storage account |

The **client IDs** of user-assigned identities must be provided for app configuration (`GEOTILER_PG_MI_CLIENT_ID`, etc).

## Networking

- **Outbound from App Service**: must reach PostgreSQL Flexible Server and Azure Storage
- **If VNet-integrated**: configure subnet delegation for App Service, ensure outbound routes
- **If using Private Endpoints** for PostgreSQL or Storage: configure matching Private DNS zones
- **Inbound IP restrictions**: apply per corporate policy (e.g., allow only APIM/Front Door)

## PostgreSQL Flexible Server

- **pgSTAC extension**: `pgstac` schema with version 0.9.x installed
- **PostGIS**: required for TiPG vector tile serving
- **Firewall**: allow inbound from App Service subnet or VNet
- **Entra ID auth**: enabled (for Managed Identity token-based login)
- **Search path**: `pgstac,public` for STAC; `geo` schema for TiPG vector collections

## Storage Account

- **Container(s)**: for COGs, Zarr stores, and any parquet files (H3)
- **Auth**: Managed Identity with Storage Blob Data Reader (no access keys in config)
- **Firewall**: if restricted, allow App Service subnet

## Application Insights

- Provide `APPLICATIONINSIGHTS_CONNECTION_STRING` for telemetry
- Optional — app runs without it, but no request tracing

## Environment Variables

~45 app settings. Key categories:

| Category | Variables |
|----------|-----------|
| **Database** | `GEOTILER_PG_HOST`, `GEOTILER_PG_DB`, `GEOTILER_PG_USER`, `GEOTILER_PG_PORT`, `GEOTILER_PG_AUTH_MODE`, `GEOTILER_PG_MI_CLIENT_ID` |
| **Storage** | `GEOTILER_ENABLE_STORAGE_AUTH`, `GEOTILER_STORAGE_ACCOUNT` |
| **Connection pools** | `GEOTILER_POOL_TIPG_MIN/MAX`, `GEOTILER_POOL_STAC_MIN/MAX`, `GEOTILER_POOL_PGSTAC_MIN/MAX` |
| **Timeouts** | `GEOTILER_DB_STATEMENT_TIMEOUT_MS` |
| **Feature flags** | `GEOTILER_ENABLE_TIPG_CATALOG_TTL`, `GEOTILER_ENABLE_H3_DUCKDB`, `GEOTILER_ENABLE_OBSERVABILITY` |
| **GDAL** | `GDAL_CACHEMAX`, `GDAL_DISABLE_READDIR_ON_OPEN`, `GDAL_HTTP_MERGE_CONSECUTIVE_RANGES`, `GDAL_HTTP_MULTIPLEX`, `GDAL_HTTP_VERSION` |
| **Container** | `WEBSITES_PORT=8000`, `WEBSITES_ENABLE_APP_SERVICE_STORAGE=false` |
| **Observability** | `APPLICATIONINSIGHTS_CONNECTION_STRING`, `GEOTILER_OBS_*` |

Full variable list available via `az webapp config appsettings list` on the reference deployment.
