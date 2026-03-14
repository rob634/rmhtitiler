# V10 Integration — Cross-Repo Fixes for rmhgeoapi

Fixes and accepted risks identified by COMPETE adversarial review (Runs 8-10) that target **rmhgeoapi**, not this repo. These should be addressed before or during the v0.10.x upgrade (pgSTAC 2.1.0).

**Source**: COMPETE Run 9 (pgSTAC Schema Surface, Split C: Data vs Control Flow)
**Report**: `docs/agent_review/agent_docs/COMPETE_PGSTAC_SCHEMA.md`

---

## Fixes

### FIX-1: Health probe uses deprecated `all_collections` [HIGH]

**File**: `rmhgeoapi/triggers/health_checks/database.py`

The pgSTAC health check probes for `all_collections()`, which is deprecated in pgSTAC >=0.9.0 and replaced by `collection_search()`. rmhtitiler already uses `collection_search` via CollectionSearchExtension. On pgSTAC upgrade, the health probe will report pgSTAC as unhealthy even though it's working.

**Fix**: Change probe query to `SELECT collection_search($1::text::jsonb)` with `'{}'`.

**Effort**: Small (< 1 hour) | **Risk**: Low

---

### FIX-2: `configure_pgstac_roles` transaction abort on DuplicateObject [HIGH]

**File**: `rmhgeoapi/services/service_stac_setup.py`, function `configure_pgstac_roles()`

`CREATE ROLE` raises `DuplicateObject` if the role already exists. Without a savepoint, this aborts the enclosing transaction. Subsequent GRANT and ALTER DEFAULT PRIVILEGES statements silently fail — the function appears to succeed but permissions are not applied.

**Fix**: Wrap `CREATE ROLE` in a savepoint, catch `DuplicateObject`, rollback to savepoint, then continue with GRANTs. Or use `CREATE ROLE IF NOT EXISTS` (PostgreSQL 14+).

**Effort**: Small (< 1 hour) | **Risk**: Low

---

### FIX-3: Search hash deduplication uses Python SHA256 instead of DB-side `search_tohash` [HIGH]

**File**: `rmhgeoapi/services/pgstac_search_registration.py`

Python computes `hashlib.sha256(json.dumps(search, sort_keys=True))` and compares against the `hash` column, which is `GENERATED ALWAYS AS (search_tohash(search, metadata))`. If pgSTAC's canonicalization differs from Python's `json.dumps(sort_keys=True)` (key ordering, whitespace, null handling), hashes won't match. The dedup check passes, a new row is inserted, and pgSTAC computes a different hash — creating a logical duplicate.

**Fix**: Query `SELECT search_tohash($1::jsonb, $2::jsonb)` to get the DB-computed hash, then check `SELECT 1 FROM pgstac.searches WHERE hash = $computed_hash`.

**Effort**: Small-Medium (1-2 hours) | **Risk**: Low

---

### FIX-4: Raw INSERT bypasses pgSTAC triggers and reconstitution [MEDIUM]

**File**: `rmhgeoapi/infrastructure/pgstac_bootstrap.py`, functions `search_items()` and `get_items_by_bbox()`

These functions use raw `INSERT INTO pgstac.items` with manual column mapping, while `pgstac_repository.py` correctly uses `pgstac.upsert_item()`. The raw paths skip pgSTAC triggers (partition routing, datetime extraction, geometry validation) and don't reconstitute the full STAC item JSON (`content || jsonb_build_object('type','Feature', 'stac_version','1.0.0', ...)`).

**Fix**: Route through `pgstac_repository.upsert_item()` or call `pgstac.upsert_item($1::jsonb)` directly. Ensure reconstitution pattern is applied to results.

**Effort**: Medium (2-3 hours) | **Risk**: Low-Medium

---

### FIX-5: Manual coordinate aggregation for collection extents [MEDIUM]

**File**: `rmhgeoapi/infrastructure/pgstac_bootstrap.py`, extent computation functions

Manual `MIN(ST_XMin(...)), MAX(ST_XMax(...))` doesn't handle antimeridian-crossing geometries, multi-polygon collections, or CRS transforms. Collections spanning the antimeridian get incorrect bounding boxes.

**Fix**: Use `SELECT ST_Extent(ST_Transform(geometry, 4326))::box2d FROM pgstac.items WHERE collection = $1`. Falls back to NULL for empty collections.

**Effort**: Small (< 1 hour) | **Risk**: Low

---

## Accepted Risks

### Non-fatal pgSTAC block creating partial state (CONFIRMED)

The 3-stage setup pipeline (install → roles → verify) can leave pgSTAC installed but roles unconfigured if stage 2 fails. Acceptable because the verify stage catches this and setup is idempotent — re-running completes remaining stages.

**Revisit if**: automated deployment pipelines don't retry on partial failure.

---

### `search_items` missing reconstitution (CONFIRMED)

Raw SELECT from `pgstac.items` returns stored `content` JSONB without reconstituting `type`, `stac_version`, `stac_extensions`, `geometry`, `bbox`, and `assets` from normalized columns. Acceptable for internal ETL use where the consumer knows the format.

**Revisit if**: these results are ever exposed via a STAC-compliant API endpoint.

---

### First-item bbox for tiled materialization (PROBABLE)

Collection extent is sometimes computed from only the first item rather than aggregating across all items. Acceptable for collections with spatially uniform items (e.g., global grids).

**Revisit if**: collections with spatially diverse items show incorrect map extents.

---

### Zarr detection ordering dependency (CONFIRMED)

Asset type detection checks `.zarr` extension before STAC media type. An asset with a non-zarr extension but zarr media type won't be detected. Acceptable because all current zarr assets use `.zarr`.

**Revisit if**: zarr assets with non-standard extensions are ingested.

---

### GENERATED column ON CONFLICT workaround (CONFIRMED — WORKING)

The SELECT-then-INSERT/UPDATE pattern in search registration correctly avoids PostgreSQL's GENERATED column inlining bug with ON CONFLICT. Well-documented in code. No action needed.

**Revisit if**: PostgreSQL fixes the underlying bug (tracked upstream).
