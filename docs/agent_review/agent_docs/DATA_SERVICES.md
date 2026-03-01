# Compete Agent #3: Data Services & Routing

**Date**: 27 FEB 2026
**Pipeline**: Compete Agent (Omega → Alpha+Beta → Gamma → Delta)
**Scope**: `routers/health.py`, `routers/vector.py`, `routers/diagnostics.py`, `routers/stac.py`, `services/database.py`, `services/duckdb.py`
**Scope Split**: Split B (Internal vs External) — Alpha reviewed internal logic/invariants, Beta reviewed external interfaces/boundaries

---

## EXECUTIVE SUMMARY

The Data Services & Routing subsystem is architecturally sound in its core design patterns — frozen-set input validation, async-first token caching, and graceful degradation on init failure are all well-executed. However, the diagnostics router has two security issues (SQL injection via f-string interpolation and unauthenticated exposure of database metadata) that should be addressed before any public-facing deployment. The DuckDB query layer has a thread-safety gap: a single `duckdb.DuckDBPyConnection` is shared across `asyncio.to_thread()` calls with no serialization, meaning concurrent requests can corrupt DuckDB's internal state. The TiPG pool refresh uses a close-then-create pattern that creates a brief window where incoming requests will hit a closed pool, though this only triggers during the 45-minute background token rotation cycle.

---

## TOP 5 FIXES

### FIX 1: SQL Injection in Diagnostics Endpoints
- **WHAT**: The `table_diagnostics` and `verbose_diagnostics` endpoints interpolate user-supplied `table_name` and `schema` parameters directly into SQL f-strings.
- **WHY**: An attacker can craft a `table_name` path parameter to execute arbitrary SQL. The endpoints are unauthenticated (see FIX 2), making exploitation trivial.
- **WHERE**: `geotiler/routers/diagnostics.py`, function `table_diagnostics` line 1235: `f'SELECT * FROM "{schema}"."{table_name}" LIMIT 1'`. Also `verbose_diagnostics` line 999 and line 959.
- **HOW**: Validate `schema` and `table_name` against a strict regex (`^[a-zA-Z_][a-zA-Z0-9_]*$`) at the top of each endpoint function, returning HTTP 400 for non-matching input.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — adding input validation at the boundary has no effect on valid identifiers.

### FIX 2: Diagnostics Endpoints Unauthenticated
- **WHAT**: Three diagnostics endpoints expose comprehensive database metadata (current user, server version, schema structure, table columns, row counts, sample data) with no authentication.
- **WHY**: Information disclosure gives an attacker a detailed map of the database. Combined with FIX 1, this is a significant attack surface.
- **WHERE**: `geotiler/routers/diagnostics.py`, lines 65-66 (`tipg_diagnostics`), lines 480-483 (`verbose_diagnostics`), lines 1062-1066 (`table_diagnostics`). No `Depends(require_admin_auth)` present.
- **HOW**: Add `dependencies=[Depends(require_admin_auth)]` to all three endpoint decorators, matching the `/admin/*` pattern. When `GEOTILER_ENABLE_ADMIN_AUTH=false` (local dev), this is a no-op.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — `require_admin_auth` is already proven in the admin router.

### FIX 3: DuckDB Connection Thread Safety
- **WHAT**: A single `duckdb.DuckDBPyConnection` is accessed concurrently from multiple `asyncio.to_thread()` calls with no synchronization.
- **WHY**: DuckDB's Python connection is not thread-safe. Concurrent HTTP requests can dispatch `_run_query` into the thread pool simultaneously, causing corrupt results or segfaults.
- **WHERE**: `geotiler/services/duckdb.py`, function `_run_query` lines 260-267, function `query_h3_data` line 310.
- **HOW**: Add a `threading.Lock` stored on `app.state`. Acquire inside `_run_query` before `conn.execute()`. In-memory reads complete in single-digit ms; throughput impact is negligible.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — serializes DuckDB queries but these are fast in-memory reads.

### FIX 4: DuckDB Query Cache Thread Safety
- **WHAT**: The query cache (plain `dict`) is read/written from multiple threads without synchronization. Comment says "LRU" but implementation is FIFO.
- **WHY**: Concurrent read-then-write sequences can exceed `_QUERY_CACHE_MAX` or evict entries unpredictably. FIFO mislabeled as LRU is misleading.
- **WHERE**: `geotiler/services/duckdb.py`, function `query_h3_data` lines 293-316, line 231 (`app.state.duckdb_query_cache = {}`).
- **HOW**: Replace with `functools.lru_cache` on a helper, or use `OrderedDict` with a `threading.Lock`. If adopting the lock from FIX 3, cache access can be in the same critical section. Fix the comment regardless.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — cache is a performance optimization; worst case is cache misses during transition.

### FIX 5: TiPG Pool Refresh Close-Then-Create Window
- **WHAT**: `refresh_tipg_pool` closes the existing asyncpg pool before creating the new one, leaving a window where requests hit a closed pool.
- **WHY**: During token refresh (every 45 min), TiPG and STAC API requests fail. STAC aliases (`readpool`/`writepool`) also become stale.
- **WHERE**: `geotiler/routers/vector.py`, function `refresh_tipg_pool` lines 276-300. Contrast with `services/background.py` lines 96-107 (correct atomic swap).
- **HOW**: Follow the pgstac atomic swap pattern: store old pool ref → `tipg_connect_to_db(app)` (overwrites `app.state.pool`) → update STAC aliases → close old pool. Failure preserves old pool.
- **EFFORT**: Medium (1-4 hours) — requires careful testing of pool lifecycle and STAC alias updates.
- **RISK OF FIX**: Medium — pool lifecycle changes affect all database-backed endpoints; requires integration testing.

---

## ACCEPTED RISKS

| Issue | Severity | Why Acceptable | Revisit When |
|-------|----------|----------------|--------------|
| Readiness/health token TTL threshold disagreement | MEDIUM | `/readyz` uses 60s threshold, `/health` uses graduated thresholds — they serve different purposes | Adding auto-scaling rules based on health status |
| STAC API module-level global `_stac_api` | MEDIUM | `stac-fastapi` requires this pattern for route registration | Adopting parallel test execution or multi-app patterns |
| DuckDB partial parquet file on interrupted download | MEDIUM | Startup error caught non-fatally; H3 remains unavailable but app runs | H3 becomes a critical-path feature |
| `psutil.cpu_percent(interval=0.1)` blocks event loop 100ms | LOW | Only affects `/health` (not `/readyz`), within acceptable diagnostics latency | Health probes called at >10/sec |
| ErrorCache preserves `last_error_time` after success | LOW | Intentional for post-mortem debugging in `/health` output | Downstream systems misinterpret as active error |
| Health endpoint no rate-limiting | LOW | Typically behind Azure APIM; db ping is lightweight | Direct public exposure without gateway |
| Diagnostics return HTTP 200 on error conditions | LOW | Diagnostic endpoints are operator-facing, not probe targets | Monitoring tools parse diagnostics HTTP codes |

---

## ARCHITECTURE WINS

1. **Frozen-set input validation for DuckDB queries** (`duckdb.py` lines 87-119). Two-layer defense: allowlist validation + parquet schema column check (lines 301-308) makes SQL injection impossible for H3 queries.

2. **Async-first token caching with sync fallback** (`cache.py`). `TokenCache` provides `asyncio.Lock` for request-time and `threading.Lock` for startup-time, with explicitly documented `_unlocked` variants. Clean solution to async/sync initialization.

3. **Non-fatal startup with structured state tracking** (`TiPGStartupState`/`DuckDBStartupState`). Init failures captured into state objects, `/health` reports exactly what failed. COG serving remains available even if PostGIS or DuckDB fails.

4. **pgstac pool atomic swap** (`background.py` lines 96-107). Creates new pool before closing old. This is the reference pattern for FIX 5.

5. **Clean auth separation** — admin auth uses `Depends()` injection with dev-mode bypass; token caches are independent instances with separate refresh cycles. Modular enough to extend to diagnostics endpoints (FIX 2) trivially.

---

## PIPELINE METADATA

| Agent | Key Finding |
|-------|------------|
| **Omega** | Chose Split B (Internal vs External) to create tension between state management and boundary resilience |
| **Alpha** | Token TTL threshold disagreement (H1), DuckDB cache mislabeled (H2), diagnostics SQL injection (H3) |
| **Beta** | DuckDB thread-safety CRITICAL (C1), TiPG pool window (H1), partial parquet corruption (R3) |
| **Gamma** | Confirmed Beta C1 over Alpha M2, found unauthenticated diagnostics (BS-2), confirmed SQL injection severity |
| **Delta** | Top 5 fixes: SQL injection, auth on diagnostics, DuckDB thread-safety, cache thread-safety, TiPG atomic swap |

### All Recalibrated Findings

| # | Severity | Source | Description | Confidence |
|---|----------|--------|-------------|------------|
| 1 | CRITICAL | Beta C1 | DuckDB connection thread-safety | CONFIRMED |
| 2 | HIGH | Alpha H3 + Gamma BS-1 | SQL injection in diagnostics `table_diagnostics` | CONFIRMED |
| 3 | HIGH | Gamma BS-2 | Diagnostics endpoints unauthenticated | CONFIRMED |
| 4 | HIGH | Beta H1 + Alpha M3 | TiPG pool refresh close-then-create window | CONFIRMED |
| 5 | HIGH | Beta H3 + Alpha H2 | DuckDB query cache not thread-safe (FIFO mislabeled LRU) | CONFIRMED |
| 6 | MEDIUM | Alpha H1 | Readiness/health token TTL threshold disagreement | CONFIRMED |
| 7 | MEDIUM | Beta R3 + Gamma BS-4 | DuckDB parquet file corruption on interrupted download | CONFIRMED |
| 8 | MEDIUM | Beta H2 + Alpha M5 | STAC API module-level global | CONFIRMED |
| 9 | MEDIUM | Beta M1 | Parquet download no retry logic | CONFIRMED |
| 10 | MEDIUM | Beta M2 | No timeout on TiPG pool creation during refresh | PROBABLE |
| 11 | MEDIUM | Beta M3 | `configure_gdal_auth` uses `os.environ` (process-global) | CONFIRMED |
| 12 | MEDIUM | Alpha L3 + Gamma BS-5 | Verbose diagnostics fix SQL unsanitized `schema` | CONFIRMED |
| 13 | MEDIUM | Alpha M5 | STAC API health reports healthy when TiPG init failed | CONFIRMED |
| 14 | LOW | Beta E3 | `psutil.cpu_percent` blocks event loop 100ms | CONFIRMED |
| 15 | LOW | Alpha M4 | ErrorCache preserves `last_error_time` after success | CONFIRMED |
| 16 | LOW | Beta M4 | Health endpoint no rate-limiting | CONFIRMED |
| 17 | LOW | Alpha L1 | `_get_hardware_info` catches all exceptions | CONFIRMED |
| 18 | LOW | Beta E4 | TiPG refresh failure leaves STAC aliases to closed pool | CONFIRMED |
| 19 | LOW | Alpha M6 | Diagnostics return HTTP 200 on error | CONFIRMED |
