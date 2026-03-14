# pgSTAC SCHEMA SURFACE — COMPETE REVIEW

**Pipeline**: COMPETE (Omega → Alpha+Beta → Gamma → Delta)
**Date**: 13 MAR 2026
**Split**: C (Data vs Control Flow)
**Target**: pgSTAC function calls, schema compatibility, search_path handling
**Cross-repo**: rmhgeoapi (ETL/admin writes) ↔ rmhtitiler (tile server reads)

---

## EXECUTIVE SUMMARY

The pgSTAC surface is functionally correct — items are ingested, searches execute, collections resolve, and tiles render. However, cross-codebase inconsistencies have accumulated as the two repos (rmhgeoapi and rmhtitiler) evolved independently against different pgSTAC versions. The most impactful finding is that rmhgeoapi's health probes still check for the deprecated `all_collections()` function, which will produce false alarms when pgSTAC is upgraded to >=0.9.0 (where `collection_search()` replaces it). The `configure_pgstac_roles` function has a DuplicateObject exception that aborts the transaction without a savepoint, potentially leaving partial role configuration. Search hash deduplication relies on Python-side SHA256 matching pgSTAC's `search_tohash()` — a fragile coupling that could silently create duplicate searches if either side changes canonicalization. The GENERATED ALWAYS column workaround in search registration is well-engineered and correctly avoids the PostgreSQL inlining bug.

---

## TOP 5 FIXES

### Fix 1: Update rmhgeoapi health probe to use `collection_search` instead of `all_collections`

- **WHAT**: Replace the health check query that probes for `all_collections()` with one that probes for `collection_search()`.
- **WHY**: pgSTAC >=0.9.0 deprecates `all_collections()` in favor of `collection_search()`. rmhtitiler already uses `collection_search` via the CollectionSearchExtension. When pgSTAC is upgraded, the rmhgeoapi health probe will report pgSTAC as unhealthy (function not found) even though it's working correctly. This is a cross-codebase inconsistency — both repos should probe the same function.
- **WHERE**: `rmhgeoapi/triggers/health_checks/database.py`, the pgSTAC health check function.
- **HOW**: Change the probe query from checking for `all_collections` to `SELECT collection_search($1::text::jsonb)` with an empty search JSON `'{}'`. This matches what rmhtitiler's STAC router actually calls.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. The function exists in current pgSTAC and is the forward-compatible path.
- **REPO**: rmhgeoapi (not this repo).

### Fix 2: Fix `configure_pgstac_roles` savepoint handling for DuplicateObject

- **WHAT**: Wrap the `CREATE ROLE` statement in a savepoint so that a `DuplicateObject` exception doesn't abort the enclosing transaction.
- **WHY**: When `configure_pgstac_roles` encounters an already-existing role, PostgreSQL raises `DuplicateObject`. Without a savepoint, this aborts the current transaction. Subsequent statements in the same transaction (GRANT, ALTER DEFAULT PRIVILEGES) silently fail because the transaction is in an aborted state. The function appears to succeed but permissions are not applied.
- **WHERE**: `rmhgeoapi/services/service_stac_setup.py`, function `configure_pgstac_roles()`.
- **HOW**: Use `SAVEPOINT sp_create_role` before `CREATE ROLE`, catch `DuplicateObject`, `ROLLBACK TO SAVEPOINT sp_create_role`, then continue with GRANT statements. Alternatively, use `CREATE ROLE IF NOT EXISTS` (PostgreSQL 14+) or check `pg_roles` first.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Standard PostgreSQL savepoint pattern.
- **REPO**: rmhgeoapi (not this repo).

### Fix 3: Fix search hash deduplication to avoid silent duplicates

- **WHAT**: Replace the Python-side SHA256 hash computation with a database-side call to `search_tohash()` for deduplication.
- **WHY**: `rmhgeoapi/services/pgstac_search_registration.py` computes `hashlib.sha256(canonical_json)` in Python and compares it against the `hash` column (which is `GENERATED ALWAYS AS (search_tohash(search, metadata))`). If pgSTAC's `search_tohash` uses different canonicalization (key ordering, whitespace, null handling) than Python's `json.dumps(sort_keys=True)`, the hashes won't match. The deduplication check passes, a new row is inserted, and pgSTAC computes a different hash via the GENERATED column — creating a logical duplicate with a different hash.
- **WHERE**: `rmhgeoapi/services/pgstac_search_registration.py`, the deduplication check before INSERT.
- **HOW**: Query `SELECT search_tohash($1::jsonb, $2::jsonb)` to get the database-computed hash, then use that for the existence check: `SELECT 1 FROM pgstac.searches WHERE hash = $computed_hash`. This guarantees hash agreement.
- **EFFORT**: Small-Medium (1-2 hours, needs testing with real searches).
- **RISK OF FIX**: Low. Uses the authoritative hash function.
- **REPO**: rmhgeoapi (not this repo).

### Fix 4: Use `upsert_item` consistently instead of raw INSERT

- **WHAT**: Replace raw `INSERT INTO pgstac.items` calls in `pgstac_bootstrap.py` with calls to `pgstac.upsert_item()` or the repository's `upsert_item()` method.
- **WHY**: `pgstac_bootstrap.py` uses raw INSERT with manual column mapping in some code paths (e.g., `search_items()`, `get_items_by_bbox()`), while `pgstac_repository.py` correctly uses `pgstac.upsert_item()`. The raw INSERT paths skip pgSTAC's internal triggers (partition routing, datetime extraction, geometry validation) and don't reconstitute the full STAC item JSON (missing `content || jsonb_build_object('type','Feature', 'stac_version','1.0.0', ...)`). This creates items that look correct in raw queries but fail STAC spec validation.
- **WHERE**: `rmhgeoapi/infrastructure/pgstac_bootstrap.py`, functions `search_items()` and `get_items_by_bbox()`.
- **HOW**: Route through `pgstac_repository.upsert_item()` or call `pgstac.upsert_item($1::jsonb)` directly. Ensure results include the reconstitution pattern from the repository.
- **EFFORT**: Medium (2-3 hours, need to verify all call sites).
- **RISK OF FIX**: Low-Medium. Need to confirm upsert semantics match existing behavior.
- **REPO**: rmhgeoapi (not this repo).

### Fix 5: Use `ST_Extent(geometry)` for collection extent computation

- **WHAT**: Replace manual min/max coordinate aggregation with `ST_Extent(geometry)` or `ST_Extent(ST_Transform(geometry, 4326))` for computing collection spatial extents.
- **WHY**: Manual coordinate aggregation (`MIN(ST_XMin(...)), MAX(ST_XMax(...))`) doesn't handle antimeridian-crossing geometries, multi-polygon collections, or CRS transforms correctly. `ST_Extent` is PostGIS's native aggregate that handles these edge cases. Collections with items spanning the antimeridian will get incorrect bounding boxes with the manual approach.
- **WHERE**: `rmhgeoapi/infrastructure/pgstac_bootstrap.py`, extent computation functions.
- **HOW**: Use `SELECT ST_Extent(ST_Transform(geometry, 4326))::box2d FROM pgstac.items WHERE collection = $1` and extract the bbox from the resulting box2d. Falls back gracefully to NULL for empty collections.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. Standard PostGIS function.
- **REPO**: rmhgeoapi (not this repo).

---

## ACCEPTED RISKS

**Non-fatal pgSTAC block creating partial state (CONFIRMED)**
The 3-stage setup pipeline (install → roles → verify) can leave pgSTAC installed but roles unconfigured if stage 2 fails. Acceptable because the verify stage catches this, and the setup is idempotent — re-running completes the remaining stages. **Revisit if**: automated deployment pipelines don't retry on partial failure.

**`search_items` missing reconstitution (CONFIRMED)**
Raw SELECT from `pgstac.items` returns the stored `content` JSONB without reconstituting `type`, `stac_version`, `stac_extensions`, `geometry`, `bbox`, and `assets` from their normalized columns. Acceptable for internal ETL use where the consumer knows the format. **Revisit if**: these results are ever exposed via a STAC-compliant API endpoint.

**First-item bbox for tiled materialization (PROBABLE)**
Collection extent is sometimes computed from only the first item in a collection rather than aggregating across all items. Acceptable for collections with spatially uniform items (e.g., global grids). **Revisit if**: collections with spatially diverse items show incorrect map extents.

**Zarr detection ordering dependency (CONFIRMED)**
Asset type detection checks `.zarr` extension before checking STAC media type. If an asset has a non-zarr extension but a zarr media type, it won't be detected. Acceptable because all current zarr assets use the `.zarr` extension. **Revisit if**: zarr assets with non-standard extensions are ingested.

**GENERATED column ON CONFLICT workaround (CONFIRMED — WORKING)**
The SELECT-then-INSERT/UPDATE pattern in search registration avoids PostgreSQL's GENERATED column inlining bug with ON CONFLICT. This is the correct workaround and is well-documented in the code. No action needed unless PostgreSQL fixes the underlying bug (tracked upstream).

---

## ARCHITECTURE WINS

**GENERATED ALWAYS column for search hash.** Using `GENERATED ALWAYS AS (search_tohash(search, metadata))` ensures the hash is always consistent with the stored search JSON. The database is the single source of truth for hash computation, preventing drift between application-computed and database-computed hashes (when used correctly — see Fix 3).

**CollectionSearchExtension adoption.** rmhtitiler correctly uses stac-fastapi-pgstac's `CollectionSearchExtension` to route `/stac/collections` through `collection_search()` instead of the deprecated `all_collections()`. This is forward-compatible with pgSTAC >=0.9.0.

**Non-fatal pgSTAC design.** Both rmhgeoapi's setup pipeline and rmhtitiler's startup handle pgSTAC unavailability gracefully — the app starts in degraded mode and reports status through health endpoints. No hard dependency on pgSTAC being present at boot.

**Explicit `SET search_path` in pool configuration.** Both TiPG and STAC pools set `search_path` at the connection level (`server_settings` for STAC/asyncpg, URL `options` for TiPG), ensuring schema resolution is deterministic regardless of database-level defaults.

**Repository separation pattern.** `pgstac_repository.py` provides a clean data-access layer with consistent item reconstitution, schema-qualified calls, and proper use of pgSTAC functions. The pattern should be extended to replace raw SQL in `pgstac_bootstrap.py` (see Fix 4).

**Schema-qualified function calls.** All pgSTAC function calls in the repository use `pgstac.function_name()` syntax, preventing search_path injection or accidental resolution to wrong-schema functions.

---

## PIPELINE METADATA

| Agent | Findings | Key Contribution |
|-------|----------|-----------------|
| Alpha (Data) | 3 HIGH, 4 MEDIUM, 2 LOW | Schema validation gaps, function signature mismatches, type safety issues, hash deduplication fragility |
| Beta (Control Flow) | 2 HIGH, 3 MEDIUM, 2 LOW, 3 EDGE CASES | DuplicateObject transaction abort, non-atomic schema drops, retry gap in setup pipeline, partial state risks |
| Gamma | 3 Contradictions resolved, 3 Agreement reinforcements, 3 Blind spots | First-item bbox, non-fatal partial state, zarr detection ordering |
| Delta | TOP 5 FIXES, 5 Accepted risks, 6 Architecture wins | Final synthesis with cross-repo prioritization |

**Note**: All TOP 5 FIXES target rmhgeoapi, not rmhtitiler. The rmhtitiler side of the pgSTAC surface is well-architected — CollectionSearchExtension, server_settings search_path, and non-fatal startup are all correct patterns. The inconsistencies originate in the ETL/admin codebase.
