# API URL Control — Hybrid Routing Design

**Created**: 02 MAR 2026
**Updated**: 24 MAR 2026
**Status**: APPROVED DESIGN — awaiting implementation
**Scope**: rmhgeoapi (ETL) + rmhtitiler (Service Layer)
**Supersedes**: `docs/archive/VERSIONED_ASSETS_IMPLEMENTATION.md` (31 JAN 2026) — outdated patterns

---

## Problem

The service layer (rmhtitiler) needs clean, human-readable API URLs for consumers.
The current raw endpoints expose infrastructure details:

| Component | Raw URL (current) | Problem |
|-----------|-------------------|---------|
| COG | `/cog/tiles/{z}/{x}/{y}?url=/vsiaz/silver/path.tif` | Blob paths leaked to clients |
| Xarray | `/xarray/tiles/{z}/{x}/{y}?url=abfs://container/path.zarr` | Blob paths leaked to clients |
| Vector | `/vector/collections/geo.t_floods_v3/items` | Table naming = infrastructure detail |
| STAC | `/stac/collections/floods-jakarta` | Already clean — ETL controls collection ID |

---

## Solution: Hybrid Approach

Different components get different URL control strategies based on what drives their URLs.

### Strategy Summary

| Component | URL Driver | Control Strategy | Needs Proxy Router? |
|-----------|-----------|-----------------|---------------------|
| **Vector (TiPG)** | PostGIS table name | ETL names tables with clean names | **No** — table name IS the URL |
| **STAC** | Collection ID | ETL sets collection IDs at ingest | **No** — collection ID IS the URL |
| **COG (TiTiler)** | Blob storage path | Slug → blob path lookup table | **Yes** — proxy hides blob URL |
| **Xarray (Zarr)** | Blob storage path | Slug → blob path lookup table | **Yes** — proxy hides blob URL |

### Why Hybrid?

The original design (Mar 2026 v1) proposed a proxy for all four components. But for
vector and STAC, the URLs are already controlled at the data layer:

- **Vector:** TiPG exposes tables as `/vector/collections/{schema}.{table_name}/...`.
  If ETL names the table `floods_jakarta_2024` in the `geo` schema, the URL is
  `/vector/collections/geo.floods_jakarta_2024/items` — no proxy needed.

- **STAC:** Collection IDs are set during STAC materialization in the ETL.
  `/stac/collections/fathom-pluvial-100yr` is already human-readable.

The proxy pattern is only needed where blob storage paths are in the URL (COG, Xarray),
because those paths contain infrastructure details that must stay internal.

---

## Strategy 1: ETL-Side Table/Collection Naming (Vector + STAC)

### Vector Tables

ETL controls the table name at creation time. Clean naming convention:

```
{dataset}_{resource}[_{version}]
```

Examples:
```
geo.floods_jakarta_2024        → /vector/collections/geo.floods_jakarta_2024/items
geo.parcels_fairfax             → /vector/collections/geo.parcels_fairfax/items
geo.infrastructure_roads_v2     → /vector/collections/geo.infrastructure_roads_v2/items
```

**Rules:**
- Lowercase, underscores (PostgreSQL convention)
- No `t_` prefix — the table name is the public-facing identifier
- Version suffix only when multiple versions coexist (otherwise just update in place)
- Must start with a letter (PostgreSQL constraint)

**Who:** rmhgeoapi `core/schema/sql_generator.py` already controls table naming.
Rename convention is the only change needed.

### STAC Collections

Collection IDs are set during `pgstac.collections` INSERT in the ETL:

```
fathom-pluvial-100yr           → /stac/collections/fathom-pluvial-100yr
era5-temperature-hourly         → /stac/collections/era5-temperature-hourly
```

**Who:** rmhgeoapi `services/stac_materializer.py` already controls this.
No change needed — collection IDs are already slugified.

---

## Strategy 2: Proxy Router with Route Tables (COG + Xarray)

For raster (COG) and multidimensional (Xarray/Zarr) data, blob storage paths must be
hidden from clients. A proxy router resolves a friendly slug to a concrete blob path
and forwards the request to the native TiTiler handler internally.

### Route Tables: `geo.b2c_routes` + `geo.b2b_routes`

Route tables live in the `geo` schema so they replicate alongside vector data. The
orchestrator (rmhgeoapi) writes routes at approval time. The service layer (rmhtitiler)
reads them. ADF replicates `b2c_routes` to the external database.

```
INTERNAL                                  EXTERNAL
─────────────────────────────             ─────────────────────────
rmhpostgres (geopgflex)                   [external-server] (geopgflex)
├── app schema (NEVER leaves)
├── geo schema                            ├── geo schema (ADF replica)
│   ├── b2b_routes  ← internal routing    │   ├── b2c_routes  ← public routing
│   ├── b2c_routes  ← source of truth     │   ├── [user vector tables]
│   └── [user vector tables]              │   └── feature_collection_styles
├── pgstac schema                         ├── pgstac schema (ADF replica)
│   ├── collections                       │   ├── collections
│   └── items                             │   └── items
└── h3 schema (internal)                  └── (no h3)

Internal rmhtitiler                       External rmhtitiler
reads geo.b2b_routes                      reads geo.b2c_routes
from internal DB                          from external DB
(same code, different table)              (behind Cloudflare, no easy auth)
```

### Schema

Both `b2c_routes` and `b2b_routes` share the same structure. They are separate tables
(not filtered views) because they replicate to different databases.

```sql
CREATE TABLE geo.b2c_routes (
    -- Identity (composite PK)
    slug            VARCHAR(200)  NOT NULL,
    version_id      VARCHAR(50)   NOT NULL,

    -- Classification
    data_type       VARCHAR(20)   NOT NULL,  -- 'raster', 'zarr'

    -- Version resolution
    is_latest       BOOLEAN       NOT NULL DEFAULT FALSE,
    version_ordinal INTEGER       NOT NULL,

    -- Target resources
    blob_path       VARCHAR(500)  NOT NULL,  -- raster: /vsiaz/..., zarr: abfs://...
    stac_item_id    VARCHAR(200),            -- pgstac item (for metadata lookup)
    stac_collection_id VARCHAR(200),         -- STAC collection

    -- Display
    title           VARCHAR(300)  NOT NULL,
    description     TEXT,

    -- Provenance (denormalized for external audit — no app schema access)
    asset_id        VARCHAR(64),
    release_id      VARCHAR(64),
    cleared_by      VARCHAR(200),
    cleared_at      TIMESTAMPTZ,

    -- Timestamps
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    PRIMARY KEY (slug, version_id)
);

-- Exactly one latest per slug
CREATE UNIQUE INDEX idx_b2c_routes_latest
    ON geo.b2c_routes (slug) WHERE is_latest = TRUE;

-- Version ordering within a slug
CREATE INDEX idx_b2c_routes_slug_ordinal
    ON geo.b2c_routes (slug, version_ordinal DESC);

-- Data type filtering
CREATE INDEX idx_b2c_routes_data_type
    ON geo.b2c_routes (data_type);
```

`geo.b2b_routes` uses the identical DDL (different table name).

**Note:** `table_name` column removed from previous design. Vector routing is handled
by ETL naming (Strategy 1), not the proxy router. Only `blob_path` targets remain.

### Slug Generation

Deterministic from platform_refs, using existing `_slugify_for_stac()` from
`config/platform_config.py`:

```python
slug = _slugify_for_stac(f"{dataset_id}-{resource_id}")

# Examples:
#   dataset_id="fathom-flood", resource_id="pluvial-100yr"
#   → slug = "fathom-flood-pluvial-100yr"
#
#   dataset_id="Aerial Imagery", resource_id="Site Alpha"
#   → slug = "aerial-imagery-site-alpha"
```

### URL Patterns (Proxy Router)

All proxy endpoints are under `/assets/{slug}`. The service layer resolves the slug +
version from the routes table and **internally proxies** to the native TiTiler handler,
returning the response directly. No 307 redirects.

**Why internal proxy, not 307 redirect:**
- **Single round trip** — client gets the tile/data in one request
- **Blob URLs stay internal** — clients never see storage paths or `?url=` parameters
- **APIM-compatible** — works behind Azure API Management without redirect rewriting

#### Raster (COG)

| Endpoint | Proxies Internally To |
|---|---|
| `GET /assets/{slug}/tiles/{z}/{x}/{y}?version=latest` | `/cog/tiles/{z}/{x}/{y}?url={blob_url}` |
| `GET /assets/{slug}/tilejson.json?version=latest` | `/cog/tilejson.json?url={blob_url}` |
| `GET /assets/{slug}/preview?version=latest` | `/cog/preview?url={blob_url}` |
| `GET /assets/{slug}/info?version=latest` | `/cog/info?url={blob_url}` |

#### Xarray (Zarr/NetCDF)

| Endpoint | Proxies Internally To |
|---|---|
| `GET /assets/{slug}/xarray/tiles/{z}/{x}/{y}?version=latest` | `/xarray/tiles/{z}/{x}/{y}?url={zarr_url}` |
| `GET /assets/{slug}/xarray/tilejson.json?version=latest` | `/xarray/tilejson.json?url={zarr_url}` |

#### Metadata (returns JSON directly)

| Endpoint | Returns |
|---|---|
| `GET /assets/{slug}/versions` | All versions with ordinal, is_latest, created_at |
| `GET /assets/{slug}/info?version=latest` | Asset metadata + links to native endpoints |

### AssetResolver (rmhtitiler)

Zone-parameterized: same code, different backing table.

```python
class AssetResolver:
    """
    Resolves slug + version to concrete blob paths for COG/Xarray assets.

    Zone-parameterized: internal deployments use geo.b2b_routes,
    external deployments use geo.b2c_routes. Set via config.
    """

    def __init__(self, pool: asyncpg.Pool, routes_table: str = "geo.b2c_routes"):
        self._pool = pool
        self._table = routes_table

    async def resolve(self, slug: str, version: str = "latest") -> Optional[ResolvedAsset]:
        if version == "latest":
            query = f"""
                SELECT slug, version_id, data_type, blob_path,
                       stac_item_id, stac_collection_id,
                       title, version_ordinal
                FROM {self._table}
                WHERE slug = $1 AND is_latest = TRUE
            """
            row = await self._pool.fetchrow(query, slug)
        else:
            query = f"""
                SELECT slug, version_id, data_type, blob_path,
                       stac_item_id, stac_collection_id,
                       title, version_ordinal
                FROM {self._table}
                WHERE slug = $1 AND version_id = $2
            """
            row = await self._pool.fetchrow(query, slug, version)

        if not row:
            return None
        return ResolvedAsset(**dict(row))

    async def list_versions(self, slug: str) -> List[VersionInfo]:
        query = f"""
            SELECT version_id, version_ordinal, is_latest, created_at
            FROM {self._table}
            WHERE slug = $1
            ORDER BY version_ordinal DESC
        """
        rows = await self._pool.fetch(query, slug)
        return [VersionInfo(**dict(r)) for r in rows]
```

### Configuration (rmhtitiler `config.py`)

```python
# Which routes table to query — determines security zone
GEOTILER_ROUTES_TABLE: str = "geo.b2c_routes"  # external default
# Internal deployments override to "geo.b2b_routes"
```

---

## Who Does What

### rmhgeoapi (Orchestrator / ETL)

| Responsibility | When | Where |
|---|---|---|
| Name vector tables with clean conventions | At table creation | `core/schema/sql_generator.py` |
| Set STAC collection IDs as slugs | At STAC materialization | `services/stac_materializer.py` |
| DDL: create `geo.b2c_routes` + `geo.b2b_routes` | Schema ensure/rebuild | `core/schema/sql_generator.py` |
| Write route record for COG/Zarr assets | At approval time | `services/asset_approval_service.py` |
| Flip `is_latest` on new version approval | At approval time | `infrastructure/release_repository.py` |
| Clear route on revocation | At revoke time | `services/asset_approval_service.py` |
| Trigger ADF for PUBLIC releases | At approval time | `services/asset_approval_service.py` |

### rmhtitiler (Service Layer)

| Responsibility | When | Where |
|---|---|---|
| `AssetResolver` reads routes table (COG/Xarray only) | Per request | `geotiler/services/asset_resolver.py` |
| `/assets/{slug}/*` proxy endpoints | Per request | `geotiler/routers/versioned_assets.py` |
| Internal proxy to native TiTiler handlers | Per request | Router handlers |
| Zone selection (b2b vs b2c table) | At startup (config) | `geotiler/config.py` |
| Vector/STAC URLs work natively — no proxy needed | Always | TiPG + stac-fastapi |

### ADF Pipeline: `export_to_public`

| Responsibility | When | Where |
|---|---|---|
| Copy `geo.b2c_routes` rows → external DB | Per PUBLIC approval | ADF `export_to_public` |
| Copy `pgstac.items` rows → external DB | Per PUBLIC approval | ADF `export_to_public` |
| Copy vector tables → external DB | Per PUBLIC approval | ADF `export_to_public` |
| Copy blobs silver → silver-ext | Per PUBLIC approval | ADF `export_to_public` |

---

## Route Lifecycle (rmhgeoapi)

### On Approval (clearance_state = PUBLIC)

```python
# In asset_approval_service.py, after STAC materialization:
# Only for raster/zarr — vector URLs are controlled by table naming

if asset.data_type in ('raster', 'zarr'):
    slug = _slugify_for_stac(f"{asset.dataset_id}-{asset.resource_id}")

    route = {
        'slug': slug,
        'version_id': version_id,
        'data_type': asset.data_type,
        'is_latest': True,
        'version_ordinal': release.version_ordinal,
        'blob_path': release.blob_path,
        'stac_item_id': release.stac_item_id,
        'stac_collection_id': release.stac_collection_id,
        'title': asset.title or slug,
        'asset_id': asset.asset_id,
        'release_id': release.release_id,
        'cleared_by': reviewer,
        'cleared_at': now
    }

    # 1. Flip previous is_latest to FALSE for this slug
    route_repo.clear_latest(slug)

    # 2. Upsert new route
    route_repo.upsert_route('b2c_routes', route)
    route_repo.upsert_route('b2b_routes', route)
```

### On Approval (clearance_state = OUO)

```python
# Internal only — write b2b_routes, skip b2c_routes
if asset.data_type in ('raster', 'zarr'):
    route_repo.clear_latest(slug, table='b2b_routes')
    route_repo.upsert_route('b2b_routes', route)
```

### On Revocation

```python
# Remove route for this specific version
route_repo.delete_route(slug, version_id, table='b2c_routes')
route_repo.delete_route(slug, version_id, table='b2b_routes')

# If revoked version was is_latest, promote next most recent
route_repo.promote_next_latest(slug, table='b2c_routes')
route_repo.promote_next_latest(slug, table='b2b_routes')
```

---

## Security Zone Model

```
Zone         Table           Who Writes        Who Reads         Deployment
──────────── ─────────────── ───────────────── ───────────────── ──────────────────
Internal     geo.b2b_routes  Orchestrator      Internal TiTiler  rmhpostgres (internal)
Public       geo.b2c_routes  Orchestrator+ADF  External TiTiler  [ext-server] (external)
Restricted   geo.b2r_routes  Orchestrator+ADF  Restricted svc    [future ext-server]
```

Each zone gets:
- Its own routes table (same schema)
- Its own database server (or at minimum, separate database)
- Its own TiTiler deployment (same container image, different config)
- Its own blob storage account (or at minimum, separate containers)

The service layer code is **identical** across zones. Only the config changes:
- `GEOTILER_ROUTES_TABLE` → which routes table to read
- `GEOTILER_PG_*` → which database to connect to
- `GEOTILER_STORAGE_ACCOUNT` → which blob storage to serve from

---

## Implementation Checklist

### rmhgeoapi (ETL — do first)

- [ ] Adopt clean table naming convention (drop `t_` prefix, use `{dataset}_{resource}` pattern)
- [ ] Add `geo.b2c_routes` + `geo.b2b_routes` DDL to `core/schema/sql_generator.py`
- [ ] Create `infrastructure/route_repository.py` (upsert, delete, clear_latest, promote_next)
- [ ] Wire route creation into `services/asset_approval_service.py` (raster/zarr only)
- [ ] Add `slug` parameter to ADF pipeline trigger
- [ ] Deploy + `action=ensure` to create tables
- [ ] Verify: approve a raster release → route record appears

### rmhtitiler (Service Layer — do second)

- [ ] Update `geotiler/config.py` with `GEOTILER_ROUTES_TABLE` setting
- [ ] Rewrite `geotiler/services/asset_resolver.py` to query routes table
- [ ] Create `geotiler/routers/versioned_assets.py` for `/assets/{slug}/*` proxy endpoints
- [ ] Register router in `geotiler/app.py` behind `GEOTILER_ENABLE_ASSETS` feature flag
- [ ] Health check: verify routes table connectivity

### ADF (Infrastructure — do when provisioned)

- [ ] Submit eService for ADF instance (T4.3.3)
- [ ] Configure ADF env vars (T4.3.4)
- [ ] Create `export_to_public` pipeline (T4.3.5)
- [ ] Provision external PostgreSQL server
- [ ] Provision external blob storage account
- [ ] Test end-to-end: approve PUBLIC → ADF copies → external TiTiler serves

---

## Relationship to Previous Designs

| Aspect | Old Design (Jan 2026) | Proxy-Only (Mar 2026 v1) | Hybrid (Mar 2026 v2, current) |
|---|---|---|---|
| Vector URL control | Proxy via lineage ID | Proxy via slug | ETL table naming (no proxy) |
| STAC URL control | N/A | Proxy via slug | ETL collection ID (no proxy) |
| COG URL control | Proxy via lineage ID | Proxy via slug | Proxy via slug (unchanged) |
| Xarray URL control | N/A | Proxy via slug | Proxy via slug (unchanged) |
| Route table scope | All data types | All data types | Raster + Zarr only |
| Lookup source | `app.geospatial_assets` | `geo.b2c_routes` | `geo.b2c_routes` (unchanged) |
| Security boundary | Crosses it | Respects it | Respects it |

**Key insight:** For vector and STAC, the "URL" is the data identifier itself (table name,
collection ID). Controlling the name at creation time is simpler and more reliable than
routing through a lookup table. The proxy pattern is reserved for COG/Xarray where the
URL contains an opaque blob storage path that must be hidden from clients.

---

## References

- `rmhgeoapi/services/asset_approval_service.py` — approval workflow
- `rmhgeoapi/infrastructure/data_factory.py` — ADF repository
- `rmhgeoapi/config/platform_config.py` — `_slugify_for_stac()`, naming patterns
- `rmhgeoapi/docs_claude/APPROVAL_WORKFLOW.md` — approval state machine
- `rmhtitiler/docs/archive/VERSIONED_ASSETS_IMPLEMENTATION.md` — superseded design (reference only)
- `rmhtitiler/archive/SERVICE-LAYER-API-DESIGN.md` — service layer endpoints (still valid)
