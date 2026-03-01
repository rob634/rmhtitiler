# Reflexion Agent #4: Vector/TiPG Pool

**Date**: 27 FEB 2026
**Pipeline**: Reflexion Agent (R → F → P → J)
**Scope**: `routers/vector.py`
**Chained from**: Compete Agent #3 (FIX 5: TiPG pool refresh window)

---

## EXECUTIVE SUMMARY

Agent R independently identified `refresh_tipg_pool` as BRITTLE — the most fragile component in the module — confirming Compete Agent #3's FIX 5 and Phase 1's F-11. Agent F enumerated 11 fault scenarios, finding one new issue beyond prior reviews: **Fault 8 — startup failure is permanent** because the `hasattr(app.state, "pool")` guard prevents retry when init fails. Agent P wrote 4 surgical patches targeting 5 faults. Agent J approved all 4.

---

## PIPELINE RESULTS

### Agent R — Key Insights

R's "no context" analysis independently identified:
- `refresh_tipg_pool` rated **BRITTLE**: no locking, no request draining, destroys pool before creating new one
- STAC pool sharing rated **FRAGILE**: aliases `app.state.pool` as `readpool`/`writepool`
- Unconditional `stac_fastapi.pgstac.db` import at line 25 even when STAC disabled
- DRY violation between `initialize_tipg` and `refresh_tipg_pool`
- `tipg_connect_to_db` writing to `app.state.pool` is an implicit TiPG library contract

### Agent F — Fault Scenarios

| # | Fault | Severity | Likelihood | Patched? |
|---|-------|----------|------------|----------|
| 1 | Non-atomic pool refresh (close-then-create gap) | CRITICAL | HIGH | **YES** (Patch A) |
| 2 | Failed pool creation leaves STAC aliases dangling | CRITICAL | MEDIUM | **YES** (Patch A) |
| 3 | Concurrent double-refresh (no lock) | HIGH | LOW | **YES** (Patch B) |
| 4 | Unconditional stac_fastapi import | HIGH | LOW | UNPATCHED |
| 5 | Token expiry between acquisition and pool use | HIGH | LOW | UNPATCHED |
| 6 | Stale diagnostic state after failed refresh | MEDIUM | MEDIUM | **YES** (Patch C) |
| 7 | CatalogUpdateMiddleware races with pool refresh | MEDIUM | LOW | UNPATCHED |
| 8 | Startup failure is permanent (no retry path) | MEDIUM | MEDIUM | **YES** (Patch D) |
| 9 | In-flight query aborted by pool close | MEDIUM | LOW | UNPATCHED |
| 10 | Health check false positive on closed pool | MEDIUM | MEDIUM | UNPATCHED |
| 11 | DRY violation between init and refresh | MEDIUM | MEDIUM | UNPATCHED |

### Agent P — Patches Applied

All 4 patches applied directly to `geotiler/routers/vector.py`.

#### Patch A: Atomic Pool Swap (Faults 1 + 2)
- **Before**: `tipg_close_db_connection(app)` → `tipg_connect_to_db(app)` — gap where pool is dead. If new pool fails, no pool at all.
- **After**: Save `old_pool` → `tipg_connect_to_db(app)` (overwrites `app.state.pool`) → update STAC aliases → `old_pool.close()`. Failure preserves old pool.
- **Lines**: 296-329 in `_refresh_tipg_pool_inner`

#### Patch B: Concurrency Lock (Fault 3)
- **Before**: No protection against concurrent admin webhook + background task calling `refresh_tipg_pool`.
- **After**: `asyncio.Lock` on `app.state._tipg_refresh_lock`. Non-blocking `locked()` check skips if refresh already in progress.
- **Lines**: 280-289 in `refresh_tipg_pool`

#### Patch C: Clear Stale Diagnostics (Fault 6)
- **Before**: `record_failure` set `init_success=False` but left `collections_discovered` and `collection_ids` at old values.
- **After**: Clears `collections_discovered = 0` and `collection_ids = []` on failure.
- **Lines**: 76-85 in `TiPGStartupState.record_failure`

#### Patch D: Startup Recovery (Fault 8)
- **Before**: `if not hasattr(app.state, "pool")` — if startup failed (pool never created), guard returns True and skips refresh forever.
- **After**: `if not hasattr(app.state, "tipg_state")` — checks for `tipg_state` instead, which IS set during `initialize_tipg` even on failure. Background refresh can now retry pool creation.
- **Lines**: 274-278 in `refresh_tipg_pool`

### Agent J — Verification

All 4 patches **APPROVED**.

- Patch A: Confirmed `tipg_connect_to_db` atomically overwrites `app.state.pool`. Old pool close is graceful (asyncpg.Pool.close() waits for released connections).
- Patch B: Confirmed `asyncio.Lock` + `locked()` skip pattern is safe for single-threaded event loop. TOCTOU not possible due to GIL.
- Patch C: Noted minor inconsistency with DuckDB's `record_failure` (doesn't clear row_count) but acceptable.
- Patch D: Verified `tipg_state` is the correct sentinel — set unconditionally at line 175 before try block.

No conflicts between patches. Complementary pipeline: D (guard) → B (lock) → A (swap) → C (diagnostics).

---

## RESIDUAL RISKS (Unpatched)

| # | Severity | Description | Recommended Action |
|---|----------|-------------|-------------------|
| 4 | HIGH | Unconditional `stac_fastapi.pgstac.db` import at line 25 — if package missing, all TiPG fails to import | Move to conditional import inside `if settings.enable_stac_api:` blocks. Architectural decision. |
| 5 | HIGH | Token expiry between acquisition and pool use — admin webhook doesn't force token refresh | Low risk due to 5-minute buffer in token cache. Monitor for auth failures after webhook-triggered refresh. |
| 7 | MEDIUM | `CatalogUpdateMiddleware` can race with `refresh_tipg_pool` (both call `register_collection_catalog`) | Patch B's lock doesn't protect against middleware. If `enable_tipg_catalog_ttl` enabled, increase TTL or rely solely on webhook. |
| 9 | MEDIUM | In-flight queries aborted by old pool close | Low risk — `asyncpg.Pool.close()` waits for connections to be released. Most TiPG queries are sub-second. |
| 10 | MEDIUM | Health check false positive — closed pool object is truthy | Would require adding active ping for TiPG pool in health.py. Target for Compete Agent #5 (App Core). |
| 11 | MEDIUM | DRY violation between `initialize_tipg` and `refresh_tipg_pool` | Maintenance risk. Extract shared helper when either function next needs modification. |

---

## MONITORING RECOMMENDATIONS

After deploying these patches, watch:
1. **`"TiPG pool refresh failed"`** — Alert on this. Old pool remains live (Patch A) but repeated failures indicate credential or DB issues.
2. **`"TiPG pool refresh already in progress, skipping"`** — Informational. Frequent occurrences indicate webhook/background timing collisions.
3. **`"Error closing old TiPG pool"`** — Warning. Investigate if persistent — may indicate connection leak.
4. **`tipg_state.collections_discovered` dropping to 0** — Patch C now correctly reports this on failure.
5. **Startup recovery** — After Patch D, verify TiPG recovers from startup failure on next 45-minute background refresh. Look for `last_init_type: "refresh"` after a failed `"startup"`.

---

## KEY INSIGHT

The codebase manages multiple asyncpg connection pools (`app.state.pool` for TiPG, `app.state.dbpool` for pgstac) that must be atomically swapped during credential rotation, and the TiPG pool is additionally shared via aliases with the STAC API. The original code treated pool refresh as a simple close-and-reopen, but this is fundamentally fragile in a system where pools are shared across subsystems via aliasing, multiple callers can trigger refresh concurrently, and startup failure should not be permanent. The four patches converge TiPG's pool lifecycle onto the same atomic swap pattern already proven in `background.py` for the pgstac pool — the codebase now has a single, consistent approach to pool management.
