# CONNECTION & POOL ARCHITECTURE — COMPETE REVIEW

**Pipeline**: COMPETE (Omega → Alpha+Beta → Gamma → Delta)
**Date**: 13 MAR 2026
**Split**: B (Internal vs External)
**Target**: Connection pool lifecycle, credential refresh, pool swap atomicity

---

## EXECUTIVE SUMMARY

The connection and pool architecture is fundamentally sound. Three independent PostgreSQL pools (titiler-pgstac/psycopg, TiPG/asyncpg, STAC/asyncpg) are cleanly separated on `app.state` with no namespace collisions, degraded-mode startup works correctly, and the async token acquisition path is well-designed with proper lock coordination. The most significant defect is a race window in the **sync** token refresh functions for both postgres and storage: they invalidate the cache before acquiring a new token, creating a window where concurrent callers see an empty cache. The async refresh paths are already correct (acquire-then-swap), making this an inconsistency that should be resolved. The TiPG search_path mechanism uses URL `options` rather than asyncpg `server_settings`, which is theoretically vulnerable to `RESET ALL`, but TiPG owns its pool exclusively so the practical risk is bounded.

---

## TOP 5 FIXES

### Fix 1: Eliminate invalidate-then-acquire race in sync postgres token refresh

- **WHAT**: Refactor `refresh_postgres_token()` to acquire a new token before invalidating the old one, matching the already-correct async pattern in `refresh_postgres_token_async()`.
- **WHY**: Between `invalidate()` on line 212 and successful `set()` on line 222, any concurrent `_get_postgres_oauth_token()` call (from a request hitting `get_postgres_credential()`) sees an empty cache and triggers its own redundant token acquisition. If the background refresh fails, the window grows until the old token is restored. The async version at lines 335-346 already does this correctly.
- **WHERE**: `geotiler/auth/postgres.py`, function `refresh_postgres_token()`, lines 206-224.
- **HOW**: Remove the `invalidate()` call. Instead, call `_acquire_postgres_token()` (the internal tuple-returning helper) directly, then atomically swap with `postgres_token_cache.set(new_token, new_expires_at)`. On failure, the old cached token remains untouched. This mirrors the pattern already used by `refresh_postgres_token_async()` at lines 336-346.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. The async path already uses this pattern successfully.

### Fix 2: Eliminate invalidate-then-acquire race in sync storage token refresh

- **WHAT**: Refactor `refresh_storage_token()` to acquire before invalidating, matching `refresh_storage_token_async()`.
- **WHY**: Identical race to Fix 1. Between `invalidate()` on line 292 and successful `set()` via `get_storage_oauth_token()`, concurrent callers see an empty cache. The async version at lines 319-331 already does this correctly.
- **WHERE**: `geotiler/auth/storage.py`, function `refresh_storage_token()`, lines 286-305.
- **HOW**: Remove the `invalidate()` call. Call `_acquire_storage_token()` directly to get the (token, expires_at) tuple, then call `storage_token_cache.set(token, expires_at)` followed by `configure_gdal_auth(token)`. On failure, old token survives untouched.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 3: Add refresh lock for titiler-pgstac pool recreation

- **WHAT**: Add an asyncio.Lock guard to `_refresh_postgres_with_pool_recreation()` for the titiler-pgstac pool swap, consistent with TiPG and STAC.
- **WHY**: While the background task is currently the only caller, the pattern is inconsistent. If an admin endpoint or manual refresh is ever added, the unguarded path could cause a double pool swap.
- **WHERE**: `geotiler/services/background.py`, function `_refresh_postgres_with_pool_recreation()`, lines 91-112.
- **HOW**: Add `_pgstac_refresh_lock` on `app.state` (lazy-init like TiPG/STAC locks), wrap lines 97-112 in `async with app.state._pgstac_refresh_lock`. Add the `locked()` early-exit guard.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 4: Add lock to `_CachedTokenCredential.get_token()` reads

- **WHAT**: Use `storage_token_cache.get_if_valid()` (which holds the threading lock) instead of directly reading `storage_token_cache.token` and `storage_token_cache.expires_at` as separate unprotected attribute accesses.
- **WHY**: `_CachedTokenCredential.get_token()` at lines 183-186 reads `token` and `expires_at` as two separate attribute accesses without any lock. A concurrent write in `asyncio.to_thread()` could produce a torn read.
- **WHERE**: `geotiler/auth/storage.py`, class `_CachedTokenCredential`, method `get_token()`, lines 180-187.
- **HOW**: Replace the direct attribute reads with a single call to `storage_token_cache.get_status()` or add a `get_token_and_expiry()` method to `TokenCache` that returns both under the lock.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

### Fix 5: Add `_stac_api` reset path for lifecycle management

- **WHAT**: Add a `reset_stac_api()` function that sets the module-level `_stac_api` global back to `None`.
- **WHY**: The `_stac_api` global is set during `create_stac_api()` but has no reset path. Tests and pool lifecycle cannot cleanly reset state.
- **WHERE**: `geotiler/routers/stac.py`, module-level global `_stac_api`, line 47.
- **HOW**: Add `reset_stac_api()` (3 lines). Call it from `close_stac_pool()` at line 280 after pool close.
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low.

---

## ACCEPTED RISKS

**TiPG search_path via URL options (PROBABLE vulnerability to RESET ALL)**
TiPG sets `search_path` via the PostgreSQL connection URL `options` parameter (`-c search_path=geo,public`), which could theoretically be reset by asyncpg's `RESET ALL`. However, TiPG owns this pool exclusively and its internal query patterns are schema-qualified. **Revisit if**: schema resolution errors appear in TiPG query logs.

**STAC pool swap partial failure could leak old pools (PROBABLE)**
If `stac_connect_to_db()` partially succeeds, old pools might leak. Acceptable because asyncpg pool close failure is extremely rare and leaked connections time out naturally. **Revisit if**: memory pressure or connection exhaustion observed after extended uptime.

**`DefaultAzureCredential()` instantiated fresh on every cache miss (CONFIRMED)**
Acceptable because cache hits are the hot path (tokens live ~60 min, refresh every 45). **Revisit if**: profiling shows construction as bottleneck.

**OAuth tokens in environment variables (CONFIRMED)**
Inherent to GDAL's `/vsiaz/` auth model. Tokens rotate every 45 min. **Revisit if**: moving to multi-tenant deployment.

**`_check_token_ready` reads `cache.token` without lock (CONFIRMED)**
Health endpoint is informational only. Stale read causes at worst momentary incorrect readiness status. **Revisit if**: readiness probes drive critical routing.

---

## ARCHITECTURE WINS

**Async-first token acquisition with proper lock coordination.** The async token paths correctly use `async_lock` to prevent thundering herd. The `_unlocked` method variants are a clean API for callers holding the lock.

**Atomic pool swap pattern.** All three pool refresh paths follow save-old/create-new/close-old. If new pool creation fails, old pool survives. Eliminates the downtime window.

**Degraded-mode startup.** Both TiPG and pgstac initialization catch exceptions and allow the app to start without database connectivity. `TiPGStartupState` cleanly tracks success/failure for diagnostics.

**Dual-lock TokenCache design.** `threading.Lock` for sync startup, `asyncio.Lock` for async request handling, with clearly named `_unlocked` variants. Prevents the common mistake of mixing sync/async primitives.

**Clean `app.state` namespace separation.** Three pools use distinct attribute names (`dbpool`, `pool`, `readpool`/`writepool`) with no collisions. STAC pool verification (`_verify_stac_pool`) catches config errors at startup.

**Background task error isolation.** The refresh loop catches all non-cancellation exceptions. Each pool refresh is independently try/excepted so a failure in one does not block others.

---

## PIPELINE METADATA

| Agent | Findings | Key Contribution |
|-------|----------|-----------------|
| Alpha | 3 HIGH, 5 MEDIUM, 3 LOW | Pool lifecycle invariants, lock patterns, state machine gaps |
| Beta | 1 HIGH, 2 MEDIUM, 3 RISKS, 5 EDGE CASES | RESET ALL vulnerability, token timing, external failure modes |
| Gamma | 3 Contradictions resolved, 4 Agreement reinforcements, 6 Blind spots | Storage auth blind spot, torn read in _CachedTokenCredential |
| Delta | TOP 5 FIXES, 5 Accepted risks, 6 Architecture wins | Final synthesis |
