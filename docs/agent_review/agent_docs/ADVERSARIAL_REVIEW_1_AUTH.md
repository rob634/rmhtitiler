# Adversarial Review #1: Auth & Token Lifecycle

**Date**: 26 FEB 2026
**Pipeline**: Adversarial Review (Omega → Alpha + Beta → Gamma → Delta)
**Scope**: `auth/cache.py`, `auth/storage.py`, `auth/postgres.py`, `services/background.py`, `middleware/azure_auth.py`

---

## EXECUTIVE SUMMARY

The auth subsystem is architecturally sound: async thundering-herd prevention, cache-check-under-lock, and `asyncio.to_thread()` for all blocking Azure SDK calls are all correctly implemented. However, two operational bugs pose real production risk: the pgSTAC pool can be destroyed and left dead for 45 minutes if reconnection fails during background refresh, and the storage auth middleware silently swallows exceptions producing opaque GDAL errors instead of a clean 503. Three medium-severity items (missing skip prefixes in middleware, a missing guard on `start_token_refresh` for pg-only MI, and a fragile Key Vault None-check) round out the actionable fixes. Everything else is either technical debt safe to defer or confirmed correct.

---

## TOP 5 FIXES

### FIX 1: Pool Destroyed With No Recovery on Reconnect Failure

**Severity**: HIGH | **Confidence**: CONFIRMED | **Source**: Beta BUG-5 + BUG-4

**What:** `_refresh_postgres_with_pool_recreation` calls `close_db_connection(app)` which destroys `app.state.dbpool`, then calls `connect_to_db(app)`. If `connect_to_db` raises, the pool stays `None` for 45 minutes until the next refresh cycle. All pgSTAC requests fail in the interim. Additionally, between close and reconnect, concurrent requests hit a missing pool.

**Why:** This is the highest-severity production bug. A transient Azure Postgres blip during token refresh kills tile serving for 45 minutes.

**Where:** `geotiler/services/background.py`, function `_refresh_postgres_with_pool_recreation`, lines 85-92.

**How:** Create the new pool first, then swap and close the old one. If creation fails, leave the old pool in place (stale token will expire naturally, but requests still work until it does).

```python
# Proposed pattern (background.py lines 81-93):
try:
    from titiler.pgstac.db import close_db_connection, connect_to_db
    from titiler.pgstac.settings import PostgresSettings

    # Create new pool BEFORE closing old one
    db_settings = PostgresSettings(database_url=new_database_url)
    old_pool = getattr(app.state, "dbpool", None)
    await connect_to_db(app, settings=db_settings)  # sets app.state.dbpool
    logger.debug("titiler-pgstac pool recreated with fresh token")

    # Close old pool AFTER new one is live
    if old_pool:
        try:
            await old_pool.close()
        except Exception:
            logger.warning("Failed to close old pgstac pool (non-fatal)")

except Exception as pool_err:
    logger.error(f"Failed to recreate titiler-pgstac pool: {pool_err}")
    # Old pool remains in place -- stale token better than no pool
```

**Effort:** ~1 hour. Requires checking whether `connect_to_db` is safe to call while an old pool exists on `app.state.dbpool`.

**Risk if unfixed:** A single transient Postgres error during any 45-minute refresh window takes out pgSTAC tile serving for the remainder of the cycle.

---

### FIX 2: Middleware Swallows Auth Errors — Fail-Open to GDAL

**Severity**: HIGH | **Confidence**: CONFIRMED | **Source**: Beta BUG-3, Gamma CONTRA-2

**What:** When `get_storage_oauth_token_async()` raises in the middleware, the `except` block at line 68 logs the error but lets the request proceed. GDAL then tries to access `/vsiaz/` with no token, producing cryptic rasterio errors instead of a clear HTTP 503.

**Why:** Users and monitoring see opaque tile errors instead of an actionable "auth unavailable" response.

**Where:** `geotiler/middleware/azure_auth.py`, method `dispatch`, lines 68-69.

**How:** Return a 503 with a clear message when token acquisition raises.

```python
# Replace lines 68-69 with:
except Exception as e:
    logger.error(f"Error in Azure OAuth authentication: {e}", exc_info=True)
    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=503,
        content={"detail": "Storage authentication unavailable"},
    )
```

**Effort:** 15 minutes.

---

### FIX 3: Add `/vector` and `/h3` to Middleware Skip Prefixes

**Severity**: MEDIUM | **Confidence**: CONFIRMED | **Source**: Gamma BLIND-7 + Alpha M3

**What:** Vector tile and H3 requests pass through the storage auth middleware unnecessarily. Each request acquires the async lock, checks the token cache, and calls `configure_gdal_auth` / `configure_fsspec_auth` — none of which are needed for PostGIS or DuckDB data.

**Why:** Wasted latency on every vector tile and H3 request. Under high load, creates unnecessary async lock contention.

**Where:** `geotiler/middleware/azure_auth.py`, `_SKIP_AUTH_PREFIXES` tuple, lines 23-27.

**How:**

```python
_SKIP_AUTH_PREFIXES = (
    "/livez", "/readyz", "/health",
    "/static/", "/docs", "/redoc", "/openapi.json",
    "/api", "/_health-fragment",
    "/vector", "/h3",          # <-- add these
    "/admin",                   # admin uses its own auth
)
```

**Effort:** 5 minutes.

---

### FIX 4: Background Refresh Not Started for pg MI When Storage Auth Disabled

**Severity**: HIGH (for affected config) | **Confidence**: CONFIRMED | **Source**: Beta EDGE-5

**What:** `start_token_refresh(app)` at `app.py:80-81` is guarded by `if settings.enable_storage_auth:`. If storage auth is disabled but `pg_auth_mode=managed_identity`, the background task never starts. Postgres tokens expire after ~1 hour and pool connections fail.

**Why:** This is a real configuration combination: vector-tiles-only deployments using MI for PostGIS with no blob storage.

**Where:** `geotiler/app.py`, lines 79-81.

**How:**

```python
# Replace lines 79-81:
if settings.enable_storage_auth or settings.pg_auth_mode == "managed_identity":
    app.state.refresh_task = start_token_refresh(app)
```

**Effort:** 5 minutes.

---

### FIX 5: Key Vault Secret `.value` Can Be None — Confusing TypeError

**Severity**: MEDIUM | **Confidence**: CONFIRMED | **Source**: Gamma BLIND-6, Beta EDGE-3

**What:** `_get_password_from_keyvault` at line 87 assigns `password = secret.value`. If the secret is disabled/empty, `None` flows into `build_database_url` where `quote_plus(None)` raises an unhelpful `TypeError`.

**Where:** `geotiler/auth/postgres.py`, function `_get_password_from_keyvault`, line 87.

**How:**

```python
password = secret.value
if not password:
    raise ValueError(
        f"Key Vault secret '{settings.keyvault_secret_name}' exists but has no value "
        f"(vault={settings.keyvault_name}). Check if the secret is disabled or empty."
    )
```

**Effort:** 5 minutes.

---

## ACCEPTED RISKS

| Finding | Rationale |
|---------|-----------|
| **asyncio.Lock at import time** (cache.py:46) | Safe under current uvicorn deployment. Would break under gunicorn `--preload` with fork — document as deployment constraint. |
| **os.environ writes not locked** (storage.py:155-165) | CPython GIL makes individual writes atomic. Both paths write valid tokens. Theoretical inconsistency window has no practical impact. |
| **DuckDB f-string column interpolation** (duckdb.py:262-263) | Two-layer validation (frozen sets + schema column check) makes injection impossible. DuckDB API doesn't support parameterized column identifiers. |
| **DuckDB cache bounded by count not memory** (duckdb.py:312-316) | 100 entries × a few thousand rows per query = well under 100MB. Over-engineering at this scale. |
| **String-matching credential dispatch** (postgres.py:33-48) | 3 modes, no plan to add more. Readable as-is. |
| **invalidate() clears expiry but not token** (cache.py:85-88) | Health check cosmetic issue only. `get_if_valid()` correctly returns None. |
| **DefaultAzureCredential() per-acquisition** | 45-minute refresh interval makes per-call instantiation cost negligible. |
| **No graceful CancelledError in background task** (background.py:39) | Event loop shutdown cancels the task cleanly. Add logging if needed for observability. |

---

## ARCHITECTURE WINS (Preserve These)

| Pattern | Where | Why It Matters |
|---------|-------|----------------|
| **Async thundering-herd prevention** | storage.py:89-105, postgres.py:246-262 | Textbook: `async with lock` → check cache → acquire. One coroutine hits Azure AD; others wait. |
| **Dual-lock TokenCache design** | cache.py:44-46 | threading.Lock for sync startup, asyncio.Lock for async runtime. `_unlocked` variants with explicit contract docs. |
| **Non-fatal degraded startup** | app.py:110-172 | Container stays alive for health probes and non-DB endpoints when Postgres is unreachable. Critical for Azure App Service. |
| **`asyncio.to_thread()` everywhere** | storage.py:100, postgres.py:257,325 | All blocking Azure SDK calls wrapped. Event loop never blocked. |
| **Explicit app passing** | background.py:26,55 | No module-level mutable state. `app` passed explicitly to all functions. Testable and predictable. |
| **Config as single source of truth** | config.py | Named constants for magic numbers (`TOKEN_REFRESH_BUFFER_SECS`, `BACKGROUND_REFRESH_INTERVAL_SECS`). |
| **Frozen-set input validation** | duckdb.py:87-106 | Two independent barriers against DuckDB injection without parameterized-query overhead. |

---

## FULL FINDINGS REFERENCE

### All Findings by Severity (Gamma-recalibrated)

| ID | Severity | Confidence | Description | Fix # |
|----|----------|------------|-------------|-------|
| BUG-5 | HIGH | CONFIRMED | Pool destroyed with no recovery on reconnect failure | Fix 1 |
| BUG-4 | HIGH | CONFIRMED | Pool recreation not atomic — requests hit closed pool | Fix 1 |
| BUG-3/CONTRA-2 | HIGH | CONFIRMED | Middleware swallows auth failure, fail-open to GDAL | Fix 2 |
| EDGE-5 | HIGH* | CONFIRMED | Background refresh not started for pg MI when storage auth disabled | Fix 4 |
| BLIND-7 | MEDIUM | CONFIRMED | /vector and /h3 needlessly pass through storage auth middleware | Fix 3 |
| BLIND-6 | MEDIUM | CONFIRMED | Key Vault secret None → confusing TypeError | Fix 5 |
| BLIND-1 | MEDIUM | CONFIRMED | DuckDB f-string column interpolation (accepted risk) | — |
| AGREE-2/BUG-1 | MEDIUM | CONFIRMED | asyncio.Lock at import time (accepted risk) | — |
| BUG-2 | MEDIUM | CONFIRMED | os.environ concurrent writes (accepted risk) | — |
| Alpha M1 | MEDIUM | CONFIRMED | String-matching credential dispatch (accepted risk) | — |
| BUG-6 | LOW | CONFIRMED | Sync path lacks thundering-herd (startup-only path) | — |
| EDGE-4 | LOW | PROBABLE | TypeError in TTL format string under narrow race | — |
| Alpha L3 | LOW | CONFIRMED | No CancelledError handling in background task | — |

*HIGH for the specific `enable_storage_auth=false` + `pg_auth_mode=managed_identity` configuration.

---

## PIPELINE CHAIN RECOMMENDATION

**Kludge Hardener target**: `geotiler/services/background.py` (FIX 1 area) — run Agent F focused on:
- Partial pool-recreation failure scenarios
- Token refresh timing edge cases
- Connection pool state machine transitions
