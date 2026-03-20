# COMPETE Run: Database Interaction Layer

**Date**: 19 MAR 2026
**Split**: B (Internal vs External)
**Target**: Connection pools, credential refresh, health probes, codec/serialization boundaries
**Triggered by**: bytes-vs-str DataError in STAC probe queries (fixed in v0.10.0.3)

---

## EXECUTIVE SUMMARY

The rmhtitiler subsystem is a well-structured FastAPI tile server with solid separation of concerns, proper async patterns, and thoughtful health diagnostics. The most consequential finding is an unauthenticated admin webhook that triggers connection pool recreation, which is a real denial-of-service vector in network-exposed deployments. The token refresh path has a confirmed invalidate-before-acquire window, but it is mitigated by save-and-restore logic that limits blast radius to a brief gap. The STAC `collection_search()` result type ambiguity is a low-probability but real correctness bug in health reporting. Overall, the codebase is production-grade with a small number of hardening gaps.

## TOP 5 FIXES

### 1. Rate-limit or authenticate `/admin/refresh-collections`

- **WHAT**: Add authentication or rate-limiting to the admin refresh-collections webhook.
- **WHY**: Any network-reachable caller can trigger serial pool recreation, causing connection churn and potential denial of service. Each call tears down and rebuilds TiPG's asyncpg pool.
- **WHERE**: `geotiler/routers/admin.py`, function `refresh_collections()`, lines 105-182. Skip list at `geotiler/middleware/azure_auth.py` line 29 (`"/admin"` in `_SKIP_AUTH_PREFIXES`).
- **HOW**: Add a shared-secret header check (e.g., `X-Webhook-Secret` validated against `GEOTILER_ADMIN_WEBHOOK_SECRET` env var). Return 401 if missing/wrong. Alternatively, add a simple `asyncio.Lock` with a cooldown timer (e.g., reject calls within 30s of last successful refresh). Remove `"/admin"` from `_SKIP_AUTH_PREFIXES` if you go with Azure AD auth instead.
- **EFFORT**: Small.
- **RISK OF FIX**: Low.

### 2. Snapshot token+expiry atomically in `_CachedTokenCredential.get_token()`

- **WHAT**: Read `storage_token_cache.token` and `storage_token_cache.expires_at` as a single atomic snapshot.
- **WHY**: A background refresh could update `token` between reading `.token` and `.expires_at`, returning a new token paired with the old expiry (or vice versa). adlfs would then use a mismatched `AccessToken`.
- **WHERE**: `geotiler/auth/storage.py`, class `_CachedTokenCredential`, method `get_token()`, lines 180-187.
- **HOW**: Add a `get_snapshot() -> Tuple[Optional[str], Optional[datetime]]` method to `TokenCache` that reads both fields under its lock. Call that from `get_token()` instead of two separate attribute reads.
- **EFFORT**: Small.
- **RISK OF FIX**: Low.

### 3. Handle string result from `collection_search()` in health probe

- **WHAT**: Parse the `collection_search()` result when it is a JSON string rather than a dict.
- **WHY**: `asyncpg.fetchval` can return the jsonb value as a string depending on codec registration. When it does, `len(result)` counts characters, producing a misleading `collection_count` (e.g., 4500 instead of 12). The `isinstance(result, dict)` guard falls through to `len(result)` which silently counts characters.
- **WHERE**: `geotiler/routers/health.py`, lines 347-352. Also `geotiler/routers/stac.py`, lines 254-258.
- **HOW**: Add `if isinstance(result, (str, bytes)): result = json.loads(result)` before the dict check in both locations. Wrap in try/except for safety.
- **EFFORT**: Small.
- **RISK OF FIX**: Low.

### 4. Eliminate invalidate-before-acquire window in sync token refresh

- **WHAT**: Acquire the new token before invalidating the old one, rather than invalidating first.
- **WHY**: Between `storage_token_cache.invalidate()` (line 292) and `get_storage_oauth_token()` returning (line 295), concurrent readers via `_CachedTokenCredential.get_token()` see no valid token and raise exceptions. The save-and-restore on failure mitigates partial risk, but the happy-path window remains.
- **WHERE**: `geotiler/auth/storage.py`, function `refresh_storage_token()`, lines 289-305. Same pattern in `geotiler/auth/postgres.py`, function `refresh_postgres_token()`, lines 213-228.
- **HOW**: Refactor to acquire the new token first (bypassing cache), then atomically swap via `cache.set(new_token, new_expires)`. Remove the `invalidate()` call entirely. If `get_storage_oauth_token()` checks cache internally, add a `force=True` parameter or call the underlying credential directly.
- **EFFORT**: Medium (need to understand `get_storage_oauth_token` internals and ensure `force` bypass works).
- **RISK OF FIX**: Medium (changing token acquisition flow requires careful testing with both CLI and MI auth modes).

### 5. Expand `readyz` to check TiPG and STAC pool health

- **WHAT**: Add TiPG and STAC pool connectivity checks to the readiness probe.
- **WHY**: Currently `readyz` only pings the pgSTAC database pool. If TiPG or STAC pools fail, the load balancer continues routing traffic to an instance that will return 500s on those endpoints.
- **WHERE**: `geotiler/routers/health.py`, function `readyz()`, lines 83-111.
- **HOW**: After the database ping, check `getattr(request.app.state, "pool", None)` (TiPG pool) and `getattr(request.app.state, "readpool", None)` (STAC pool) are not None when their respective features are enabled. Optionally do a lightweight `pool.fetchval("SELECT 1")` on each. Add failures to the `issues` list.
- **EFFORT**: Small.
- **RISK OF FIX**: Low (additive check, degrades gracefully if pools are optional).

## ACCEPTED RISKS

1. **Lazy lock creation via `hasattr`/`setattr` (vector.py:270-271, stac.py:312-313)**: Safe in practice because Python's cooperative async scheduling means no true concurrency between `hasattr` and `setattr`. Revisit only if moving to multi-process workers sharing app state.

2. **`_check_token_ready` TOCTOU (health.py:449-467)**: A concurrent refresh could cause momentary mismatch. Impact is one stale readiness check, self-corrects next probe. Revisit if readiness flapping observed.

3. **`/api` prefix in skip list is overly broad (azure_auth.py:27)**: Currently no unintended routes under `/api/*`. Revisit when adding any new `/api` routes.

4. **STAC requests going through storage auth middleware**: Overhead is negligible (cached token check). Revisit only if profiling shows measurable latency.

5. **`TiPGStartupState.record_failure()` leaves stale `schemas_configured` (vector.py:74-83)**: Only affects diagnostic output, not runtime. `init_success=False` is the authoritative signal.

6. **`error_response` `**context` allows arbitrary keys (errors.py:65)**: All callers are internal with known keys. Revisit if ever called with user-supplied data.

7. **Background task silently swallows errors (background.py:56-62)**: Logging and retrying is better than crashing the loop.

## ARCHITECTURE WINS

1. **Save-and-restore pattern in token refresh** (storage.py:289-304, postgres.py:213-228): Saving old token state before invalidation and restoring on failure limits blast radius of transient Azure Identity SDK failures.

2. **TiPGStartupState diagnostic model** (vector.py:40-95): Dedicated state object tracking init type, timing, success/failure, collection counts, and search path — excellent operational visibility without polluting business logic.

3. **Atomic pool swap in refresh paths** (vector.py:281+, stac.py:297+): Create new pool, swap onto app.state, then close old. Lock + locked() early-exit prevents pileup from concurrent webhook + background task.

4. **Structured health endpoint with service/dependency separation** (health.py:114-446): Clean separation of per-service status from shared dependency status with clear priority chain (unhealthy > degraded > healthy).

5. **Middleware skip-list pattern** (azure_auth.py:24-30): Tuple of prefixes for fast `startswith()` matching keeps the middleware hot path efficient.

6. **Environment variable naming conventions**: Consistent `GEOTILER_COMPONENT_SETTING` prefix with units in names (`_SEC`, `_MS`) prevents ambiguity and makes configuration self-documenting.
