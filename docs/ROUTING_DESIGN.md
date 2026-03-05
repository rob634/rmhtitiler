# Versioned Asset Routing — Cross-Project Design

**Created**: 02 MAR 2026
**Status**: APPROVED DESIGN — awaiting implementation
**Scope**: rmhgeoapi (ETL) + rmhtitiler (Service Layer)
**Supersedes**: `docs/VERSIONED_ASSETS_IMPLEMENTATION.md` (31 JAN 2026) — outdated patterns

---

## Problem

The service layer (rmhtitiler) needs to resolve friendly URLs like
`/assets/fathom-pluvial-100yr/latest` to concrete TiTiler/TiPG endpoints without
crossing the internal/external security boundary.

The previous design (Jan 2026) had the external TiTiler querying `app.geospatial_assets`
on the internal database. This breaks the airgap — the `app` schema contains internal
infrastructure details and must never be replicated externally.

---

## Solution: `geo.b2c_routes` + `geo.b2b_routes`

Route tables live in the `geo` schema so they replicate alongside vector data. The
orchestrator (rmhgeoapi) writes routes at approval time. The service layer (rmhtitiler)
reads them. ADF replicates `b2c_routes` to the external database.

```
INTERNAL                                  EXTERNAL
─────────────────────────────             ─────────────────────────
rmhpostgres (geopgflex)                   [external-server] (geopgflex)
├── app schema (NEVER leaves)
├── geo schema                            ├── geo schema (ADF replica)
│   ├── table_catalog                     │   ├── table_catalog
│   ├── b2b_routes  ← internal routing    │   ├── b2c_routes  ← public routing
│   ├── b2c_routes  ← source of truth     │   ├── [user vector tables]
│   ├── feature_collection_styles         │   └── feature_collection_styles
│   └── [user vector tables]              │
├── pgstac schema                         ├── pgstac schema (ADF replica)
│   ├── collections                       │   ├── collections
│   └── items                             │   └── items
└── h3 schema (internal)                  └── (no h3)

Internal rmhtitiler                       External rmhtitiler
reads geo.b2b_routes                      reads geo.b2c_routes
from internal DB                          from external DB
(same code, different table)              (behind Cloudflare, no easy auth)
```

---

## Who Does What

### rmhgeoapi (Orchestrator / ETL)

| Responsibility | When | Where |
|---|---|---|
| DDL: create `geo.b2c_routes` + `geo.b2b_routes` tables | Schema ensure/rebuild | `core/schema/sql_generator.py` |
| Generate slug from platform_refs | At approval time | `services/asset_approval_service.py` |
| Write route record (b2c and/or b2b) | At approval time | `services/asset_approval_service.py` |
| Flip `is_latest` on new version approval | At approval time | `infrastructure/release_repository.py` |
| Clear route on revocation | At revoke time | `services/asset_approval_service.py` |
| Trigger ADF for PUBLIC releases | At approval time | `services/asset_approval_service.py` |
| ADF pipeline definition | Infrastructure | Azure Data Factory |

### rmhtitiler (Service Layer)

| Responsibility | When | Where |
|---|---|---|
| `AssetResolver` reads routes table | Per request | `geotiler/services/asset_resolver.py` |
| `/assets/{slug}/latest` endpoint | Per request | `geotiler/routers/versioned_assets.py` |
| 307 redirect to native TiTiler/TiPG | Per request | Router handlers |
| Zone selection (b2b vs b2c table) | At startup (config) | `geotiler/config.py` |
| Version listing endpoint | Per request | Router handlers |

### Neither (ADF Pipeline)

| Responsibility | When | Where |
|---|---|---|
| Copy `geo.b2c_routes` rows → external DB | Per PUBLIC approval | ADF `export_to_public` |
| Copy `pgstac.items` rows → external DB | Per PUBLIC approval | ADF `export_to_public` |
| Copy vector tables → external DB | Per PUBLIC approval | ADF `export_to_public` |
| Copy blobs silver → silver-ext | Per PUBLIC approval | ADF `export_to_public` |

---

## Schema: `geo.b2c_routes`

Both `b2c_routes` and `b2b_routes` share the same structure. They are separate tables
(not filtered views) because they replicate to different databases.

```sql
CREATE TABLE geo.b2c_routes (
    -- Identity (composite PK)
    slug            VARCHAR(200)  NOT NULL,
    version_id      VARCHAR(50)   NOT NULL,

    -- Classification
    data_type       VARCHAR(20)   NOT NULL,  -- 'raster', 'vector', 'zarr'

    -- Version resolution
    is_latest       BOOLEAN       NOT NULL DEFAULT FALSE,
    version_ordinal INTEGER       NOT NULL,

    -- Target resources (populated by data_type)
    table_name      VARCHAR(63),             -- vector: geo.{table_name}
    stac_item_id    VARCHAR(200),            -- raster/zarr: pgstac item
    stac_collection_id VARCHAR(200),         -- STAC collection
    blob_path       VARCHAR(500),            -- direct download path

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

---

## Slug Generation

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

The slug is a **flattened single-segment identifier**. External URLs use it directly:

```
GET /assets/fathom-flood-pluvial-100yr/latest
GET /assets/fathom-flood-pluvial-100yr/v1
GET /assets/fathom-flood-pluvial-100yr/v2
GET /assets/fathom-flood-pluvial-100yr/versions
```

---

## URL Patterns (rmhtitiler)

All endpoints are under `/assets/{slug}`. The service layer resolves the slug + version
from the routes table and redirects (307) to the native endpoint.

### Raster

| Endpoint | Redirects To |
|---|---|
| `GET /assets/{slug}/tiles/{z}/{x}/{y}?version=latest` | `/cog/tiles/{z}/{x}/{y}?url={blob_url}` |
| `GET /assets/{slug}/tilejson.json?version=latest` | `/cog/tilejson.json?url={blob_url}` |
| `GET /assets/{slug}/preview?version=latest` | `/cog/preview?url={blob_url}` |
| `GET /assets/{slug}/info?version=latest` | `/cog/info?url={blob_url}` |

### Vector

| Endpoint | Redirects To |
|---|---|
| `GET /assets/{slug}/vector/tiles/{z}/{x}/{y}?version=latest` | `/vector/collections/{schema.table}/tiles/{z}/{x}/{y}` |
| `GET /assets/{slug}/vector/items?version=latest` | `/vector/collections/{schema.table}/items` |
| `GET /assets/{slug}/vector/tilejson.json?version=latest` | `/vector/collections/{schema.table}/tilejson.json` |

### Zarr

| Endpoint | Redirects To |
|---|---|
| `GET /assets/{slug}/xarray/tiles/{z}/{x}/{y}?version=latest` | `/xarray/tiles/{z}/{x}/{y}?url={zarr_url}` |
| `GET /assets/{slug}/xarray/tilejson.json?version=latest` | `/xarray/tilejson.json?url={zarr_url}` |

### Metadata (no redirect — returns JSON directly)

| Endpoint | Returns |
|---|---|
| `GET /assets/{slug}/versions` | All versions with ordinal, is_latest, created_at |
| `GET /assets/{slug}/info?version=latest` | Asset metadata + links to native endpoints |

---

## AssetResolver (rmhtitiler)

Zone-parameterized: same code, different backing table.

```python
class AssetResolver:
    """
    Resolves slug + version to concrete asset targets.

    Zone-parameterized: internal deployments use geo.b2b_routes,
    external deployments use geo.b2c_routes. Set via config.
    """

    def __init__(self, pool: asyncpg.Pool, routes_table: str = "geo.b2c_routes"):
        self._pool = pool
        self._table = routes_table

    async def resolve(self, slug: str, version: str = "latest") -> Optional[ResolvedAsset]:
        if version == "latest":
            query = f"""
                SELECT slug, version_id, data_type, table_name,
                       stac_item_id, stac_collection_id, blob_path,
                       title, version_ordinal
                FROM {self._table}
                WHERE slug = $1 AND is_latest = TRUE
            """
            row = await self._pool.fetchrow(query, slug)
        else:
            query = f"""
                SELECT slug, version_id, data_type, table_name,
                       stac_item_id, stac_collection_id, blob_path,
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

No `lineage_id` hash computation needed. No cross-schema queries. No `app` schema
dependency. The slug IS the lookup key.

---

## Route Lifecycle (rmhgeoapi)

### On Approval (clearance_state = PUBLIC)

```python
# In asset_approval_service.py, after STAC materialization:

slug = _slugify_for_stac(f"{asset.dataset_id}-{asset.resource_id}")

route = {
    'slug': slug,
    'version_id': version_id,           # "v1", "v2"
    'data_type': asset.data_type,       # "raster", "vector", "zarr"
    'is_latest': True,
    'version_ordinal': release.version_ordinal,
    'table_name': table_name,           # vector only
    'stac_item_id': release.stac_item_id,
    'stac_collection_id': release.stac_collection_id,
    'blob_path': release.blob_path,     # raster/zarr blob
    'title': asset.title or slug,
    'asset_id': asset.asset_id,
    'release_id': release.release_id,
    'cleared_by': reviewer,
    'cleared_at': now
}

# 1. Flip previous is_latest to FALSE for this slug
route_repo.clear_latest(slug)

# 2. Upsert new route (INSERT ON CONFLICT UPDATE)
route_repo.upsert_route('b2c_routes', route)

# 3. Also write to b2b_routes (internal always gets a route)
route_repo.upsert_route('b2b_routes', route)
```

### On Approval (clearance_state = OUO)

```python
# Internal only — write b2b_routes, skip b2c_routes
route_repo.clear_latest(slug, table='b2b_routes')
route_repo.upsert_route('b2b_routes', route)
# No b2c_routes entry — not public
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

## ADF Pipeline: `export_to_public`

Triggered per PUBLIC approval. Copies only the specific release's artifacts.

### Pipeline Parameters (passed from rmhgeoapi)

```json
{
    "release_id": "abc123...",
    "asset_id": "def456...",
    "data_type": "raster|vector|zarr",
    "slug": "fathom-flood-pluvial-100yr",
    "version_id": "v1",

    "stac_item_id": "fathom-flood-pluvial-100yr-v1",
    "stac_collection_id": "fathom-flood-pluvial-100yr",

    "table_names": ["floods_pluvial_100yr_v1"],
    "blob_path": "silver-cogs/fathom-flood/pluvial-100yr/v1/data.cog.tif"
}
```

### Pipeline Activities

```
export_to_public
├── 1. Copy Route Record
│   INSERT INTO geo.b2c_routes (from internal geo.b2c_routes)
│   Target: external DB → geo.b2c_routes
│
├── 2. Copy Data (conditional on data_type)
│   ├── IF vector:
│   │   Copy geo.{table_name} → external DB geo.{table_name}
│   │   Copy geo.table_catalog row → external DB
│   │
│   ├── IF raster:
│   │   Copy blob: silver-cogs/{path} → silverext-cogs/{path}
│   │   Copy pgstac.items row → external DB
│   │   Copy pgstac.collections row → external DB (upsert)
│   │
│   └── IF zarr:
│       Copy blob: silver-zarr/{path} → silverext-zarr/{path}
│       Copy pgstac.items row → external DB
│       Copy pgstac.collections row → external DB (upsert)
│
├── 3. Copy Styles (if vector)
│   Copy geo.feature_collection_styles rows for this collection
│
└── 4. Audit Log
    Record: who approved, when, what was copied, ADF run_id
```

### ADF Connection Targets

| Source | Target | Method |
|---|---|---|
| Internal PostgreSQL `geo` schema | External PostgreSQL `geo` schema | ADF Copy Activity (PostgreSQL→PostgreSQL) |
| Internal PostgreSQL `pgstac` schema | External PostgreSQL `pgstac` schema | ADF Copy Activity |
| Internal blob `silver-cogs` | External blob `silverext-cogs` | ADF Copy Activity (Blob→Blob) |
| Internal blob `silver-zarr` | External blob `silverext-zarr` | ADF Copy Activity (Blob→Blob) |

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
- `POSTGRES_*` → which database to connect to
- `AZURE_STORAGE_ACCOUNT` → which blob storage to serve from

---

## Relationship to Previous Design

This design **supersedes** `docs/VERSIONED_ASSETS_IMPLEMENTATION.md` (31 JAN 2026).

| Aspect | Old Design (Jan 2026) | New Design (Mar 2026) |
|---|---|---|
| Lookup source | `app.geospatial_assets` | `geo.b2c_routes` / `geo.b2b_routes` |
| Identity | `lineage_id` (SHA256 hash) | `slug` (human-readable) |
| URL shape | `/assets/{dataset}/{resource}?version=latest` | `/assets/{slug}/latest` |
| Security boundary | Crosses it (reads `app` schema) | Respects it (reads `geo` schema) |
| Zone support | Single zone only | Multi-zone (b2b, b2c, future b2r) |
| DB dependency | TiTiler → internal rmhgeoapi DB | TiTiler → zone-local DB |
| Who writes | N/A (read from app) | Orchestrator at approval time |
| ADF integration | None | Routes replicated alongside data |

The `AssetResolver` class, 307 redirect pattern, and router structure carry forward.
The backing data source and URL shape change.

---

## Implementation Checklist

### rmhgeoapi (ETL — do first)

- [ ] Add `geo.b2c_routes` + `geo.b2b_routes` DDL to `core/schema/sql_generator.py`
- [ ] Create `infrastructure/route_repository.py` (upsert, delete, clear_latest, promote_next)
- [ ] Wire route creation into `services/asset_approval_service.py` (approve + revoke)
- [ ] Add `slug` parameter to ADF pipeline trigger
- [ ] Deploy + `action=ensure` to create tables
- [ ] Verify: approve a release → route record appears

### rmhtitiler (Service Layer — do second)

- [ ] Update `geotiler/config.py` with `GEOTILER_ROUTES_TABLE` setting
- [ ] Rewrite `geotiler/services/asset_resolver.py` to query routes table (not `app` schema)
- [ ] Update `geotiler/routers/versioned_assets.py` for slug-based URLs
- [ ] Add zarr endpoint support
- [ ] Register router in `geotiler/app.py`
- [ ] Health check: verify routes table connectivity

### ADF (Infrastructure — do when provisioned)

- [ ] Submit eService for ADF instance (T4.3.3)
- [ ] Configure ADF env vars (T4.3.4)
- [ ] Create `export_to_public` pipeline (T4.3.5)
- [ ] Provision external PostgreSQL server
- [ ] Provision external blob storage account
- [ ] Test end-to-end: approve PUBLIC → ADF copies → external TiTiler serves

---

## References

- `rmhgeoapi/services/asset_approval_service.py` — approval workflow
- `rmhgeoapi/infrastructure/data_factory.py` — ADF repository
- `rmhgeoapi/config/platform_config.py` — `_slugify_for_stac()`, naming patterns
- `rmhgeoapi/docs_claude/APPROVAL_WORKFLOW.md` — approval state machine
- `rmhtitiler/docs/VERSIONED_ASSETS_IMPLEMENTATION.md` — superseded design (reference only)
- `rmhtitiler/archive/SERVICE-LAYER-API-DESIGN.md` — service layer endpoints (still valid)
