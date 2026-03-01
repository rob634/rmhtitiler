# Kludge Hardener #1: Token Lifecycle

**Date**: 26 FEB 2026
**Pipeline**: Kludge Hardener (R → F → P → J)
**Scope**: `auth/cache.py`, `services/background.py`, `middleware/azure_auth.py` (+ `auth/storage.py`, `auth/postgres.py` for token refresh patterns)
**Chained from**: Adversarial Review #1 (Delta recommendation)

---

## EXECUTIVE SUMMARY

Agent R reverse-engineered the token lifecycle from code alone and independently confirmed the Adversarial Review's critical findings (pool destruction, background task vulnerability). Agent F enumerated 15 fault scenarios, finding 6 new issues beyond the prior review — most notably a **critical DuckDB thread-safety bug** (F-06). Agent P wrote surgical patches for 6 faults. Agent J verified all patches are correctly applied.

---

## PIPELINE RESULTS

### Agent R — Key Insight

R's "no context" analysis independently identified the same top risks as the Adversarial Review, validating them as genuine concerns rather than review artifacts:
- Pool recreation window (non-atomic close/connect)
- Background task silent death (no top-level exception handler)
- Middleware fail-open design
- GDAL env var race during token rotation

R also surfaced that `invalidate()` clears expiry but not token — creating a misleading health status window.

### Agent F — New Findings (beyond Adversarial Review)

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| **F-06** | CRITICAL | DuckDB connection shared across `asyncio.to_thread` without lock — can segfault | **UNPATCHED** (out of scope) |
| **F-14** | HIGH | Cache invalidated before refill — transient IMDS outage empties still-valid cache | **PATCHED** |
| **F-10** | HIGH | Health check races pool recreation → Azure may restart instance | **PATCHED** |
| **F-11** | HIGH | Stale STAC pool aliases after TiPG refresh failure | **UNPATCHED** (out of scope) |
| **F-01b** | HIGH | CancelledError (BaseException) kills background task forever | **PATCHED** |
| **F-07** | MEDIUM | DuckDB query cache race — `next(iter(dict))` during concurrent modification | **UNPATCHED** (out of scope) |

### Agent P — Patches Applied

All 6 patches were applied directly to the codebase as uncommitted changes.

#### Patch F-02: Atomic pool swap (background.py)
- **Before**: `close_db_connection(app)` → `connect_to_db(app)` — gap where pool is dead
- **After**: Save old pool → `connect_to_db(app)` → close old pool. Failure preserves old pool.
- **Files**: `geotiler/services/background.py` lines 88-104

#### Patch F-14: Acquire-before-invalidate (storage.py, postgres.py)
- **Async paths**: Removed `invalidate_unlocked()`. `set_unlocked()` atomically overwrites.
- **Sync paths**: Save old token/expires → invalidate → acquire → restore on failure.
- **Files**: `geotiler/auth/storage.py` lines 225-266, `geotiler/auth/postgres.py` lines 200-337

#### Patch F-04: Fail-closed middleware (azure_auth.py)
- **Before**: Auth exception logged, request proceeds → opaque GDAL errors
- **After**: Returns 503 `{"detail": "Storage authentication unavailable"}`
- **Files**: `geotiler/middleware/azure_auth.py` lines 68-76

#### Patch F-01b: Resilient background loop (background.py)
- **Before**: Bare `while True` — any unhandled exception kills task forever
- **After**: `CancelledError` → log + re-raise. `Exception` → log + continue next iteration.
- **Files**: `geotiler/services/background.py` lines 40-61

#### Patch F-03: Expanded startup guard (app.py)
- **Before**: `if settings.enable_storage_auth:`
- **After**: `if settings.enable_storage_auth or settings.pg_auth_mode == "managed_identity":`
- **Files**: `geotiler/app.py` lines 80-85

#### Patch F-10: PoolClosed-aware health ping (database.py)
- **Before**: PoolClosed treated as real DB error → recorded in error cache → Azure may restart
- **After**: PoolClosed caught as transient → not recorded → returns "pool_recreating"
- **Files**: `geotiler/services/database.py` lines 109-116, 144-152

### Agent J — Verification

J confirmed all 6 patches are correctly applied and match the proposed fixes. No conflicts between patches. Happy-path behavior unchanged.

---

## RESIDUAL RISKS (Unpatched)

| ID | Severity | File | Description | Recommended Action |
|----|----------|------|-------------|-------------------|
| **F-06** | CRITICAL | `duckdb.py:310` | `app.state.duckdb_conn` shared across `asyncio.to_thread()` calls without lock. DuckDB Python API is NOT thread-safe. Concurrent `/h3/query` requests can segfault. | Add `threading.Lock` around `_run_query` calls, or create per-thread connections. Target for Kludge Hardener #3. |
| **F-11** | HIGH | `vector.py:297-300` | `app.state.readpool`/`writepool` aliases only reassigned after successful TiPG reconnect. On failure, aliases point to closed pool. | Move alias assignment or add rollback. Target for Adversarial Review #3. |
| **F-07** | MEDIUM | `duckdb.py:314-316` | Query cache is a plain dict modified concurrently. `next(iter(dict))` FIFO eviction can raise `RuntimeError: dictionary changed size during iteration`. | Wrap cache access in `threading.Lock` or use `functools.lru_cache`. Target for Kludge Hardener #3. |

---

## MONITORING RECOMMENDATIONS

After deploying these patches, watch:
1. **Background task health** — Verify via `/health` that token TTLs stay fresh (should never drop below refresh buffer)
2. **503 responses from middleware** — New signal: `"Storage authentication unavailable"` indicates IMDS/credential issues
3. **`pool_recreating` in readiness** — Brief occurrences during refresh cycles are now expected and healthy
4. **Old pool close warnings** — `"Error closing old pgstac pool"` warnings indicate pool lifecycle issues
5. **Token restore warnings** — `"Restored previous cached token"` means a refresh failed but the old token was preserved

---

## KEY INSIGHT

The single most important discovery from this pipeline is **F-06: DuckDB thread-safety**. This is a latent segfault-level bug that neither the Adversarial Review nor this Kludge Hardener's scope covered. It should be the #1 priority for the DuckDB-focused Kludge Hardener (#3 in the tracker). The token lifecycle code, by contrast, is now well-hardened after these patches.
