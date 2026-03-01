# Consolidated Implementation Plan

**Date**: 27 FEB 2026
**Source**: All 5 completed code review pipelines (#1–#5)
**Scope**: Full geotiler codebase

---

## STATUS LEGEND

- **PATCHED** — Code already modified (uncommitted changes in working tree)
- **TODO** — Needs implementation
- **ACCEPTED** — Intentional design or acceptable risk, no action needed

---

## ALREADY PATCHED (10 patches applied)

These patches were applied during the review sessions and exist as uncommitted changes.

### From Reflexion Agent #2 (Phase 1: Token Lifecycle) — 6 patches

| Patch | File | Description |
|-------|------|-------------|
| F-02 | `services/background.py` | Atomic pool swap for pgSTAC (create new → close old) |
| F-14 | `auth/storage.py`, `auth/postgres.py` | Acquire-before-invalidate (preserves valid token on refresh failure) |
| F-04 | `middleware/azure_auth.py` | Fail-closed middleware (503 instead of opaque GDAL errors) |
| F-01b | `services/background.py` | Resilient background loop (CancelledError + Exception handling) |
| F-03 | `app.py` | Expanded startup guard (`enable_storage_auth OR pg MI`) |
| F-10 | `services/database.py` | PoolClosed-aware health ping (transient, not recorded as error) |

### From Compete Agent #1 (Phase 1: Auth) — applied alongside Reflexion patches

| Fix | File | Description |
|-----|------|-------------|
| FIX 3 | `middleware/azure_auth.py` | Added `/vector`, `/h3`, `/admin` to skip prefixes |
| FIX 5 | `auth/postgres.py` | Key Vault secret None guard with clear error message |

### From Reflexion Agent #4 (Phase 2: Vector/TiPG Pool) — 4 patches

| Patch | File | Description |
|-------|------|-------------|
| A | `routers/vector.py` | Atomic pool swap for TiPG (create new → update aliases → close old) |
| B | `routers/vector.py` | asyncio.Lock with skip-if-locked concurrency guard |
| C | `routers/vector.py` | Clear stale diagnostics (collections_discovered=0) on failure |
| D | `routers/vector.py` | Startup recovery guard (check `tipg_state` not `pool`) |

---

## TODO: Implementation Queue

Ordered by severity, then by effort (quick wins first).

### CRITICAL

#### 1. SQL Injection in Diagnostics Endpoints
- **Source**: Compete #3, FIX 1
- **File**: `geotiler/routers/diagnostics.py`
- **Lines**: ~959, ~999, ~1235
- **Issue**: `table_name` and `schema` parameters interpolated into SQL f-strings. Unauthenticated endpoints (see #2) make exploitation trivial.
- **Fix**: Validate both parameters against `^[a-zA-Z_][a-zA-Z0-9_]*$` regex at the top of each endpoint. Return HTTP 400 for non-matching input.
- **Effort**: Small (< 1 hour)

#### 2. DuckDB Connection Thread Safety
- **Source**: Compete #3 FIX 3, Compete #1 F-06 (CRITICAL), Reflexion #2 F-06
- **File**: `geotiler/services/duckdb.py`
- **Lines**: ~260-267 (`_run_query`), ~310 (`query_h3_data`)
- **Issue**: Single `duckdb.DuckDBPyConnection` shared across `asyncio.to_thread()` calls without synchronization. Concurrent `/h3/query` requests can segfault.
- **Fix**: Add `threading.Lock` stored on `app.state`. Acquire inside `_run_query` before `conn.execute()`. In-memory reads are sub-ms; throughput impact negligible.
- **Effort**: Small (< 1 hour)

### HIGH

#### 3. Diagnostics Endpoints Unauthenticated
- **Source**: Compete #3, FIX 2
- **File**: `geotiler/routers/diagnostics.py`
- **Lines**: ~65-66, ~480-483, ~1062-1066
- **Issue**: Three diagnostics endpoints expose database metadata (user, version, schema, columns, row counts, sample data) with no auth.
- **Fix**: Add `dependencies=[Depends(require_admin_auth)]` to all three endpoint decorators.
- **Effort**: Small (< 1 hour)

#### 4. DuckDB Query Cache Thread Safety
- **Source**: Compete #3 FIX 4, Reflexion #2 F-07
- **File**: `geotiler/services/duckdb.py`
- **Lines**: ~293-316 (cache read/write), ~231 (init)
- **Issue**: Plain `dict` cache modified concurrently from thread pool. `next(iter(dict))` eviction can raise `RuntimeError`. Comment says "LRU" but implementation is FIFO.
- **Fix**: Either wrap in same `threading.Lock` from #2 (simplest — cache access inside same critical section), or replace with `functools.lru_cache`. Fix the misleading comment.
- **Effort**: Small (< 1 hour, combine with #2)

### MEDIUM

#### 5. Duplicate Jinja2Templates Instances
- **Source**: Compete #5, FIX 1
- **Files**: `geotiler/app.py` line 292, `geotiler/templates_utils.py` line 19
- **Issue**: Two `Jinja2Templates` instances pointing to same directory. Ambiguous which is canonical.
- **Fix**: Remove `app.state.templates = Jinja2Templates(directory=templates_dir)` from `app.py`. Verify no router uses `request.app.state.templates`. Remove `Jinja2Templates` import from `app.py` if unused.
- **Effort**: Small (< 1 hour)

#### 6. Cancel Background Refresh Task on Shutdown
- **Source**: Compete #5, FIX 2
- **File**: `geotiler/app.py`, shutdown block (after line 99)
- **Issue**: `app.state.refresh_task` never explicitly cancelled during shutdown. Can race with pool closure.
- **Fix**: Add at start of shutdown block:
  ```python
  if hasattr(app.state, "refresh_task"):
      app.state.refresh_task.cancel()
      try:
          await app.state.refresh_task
      except asyncio.CancelledError:
          pass
  ```
- **Effort**: Small (< 30 minutes)

### LOW

#### 7. Use Literal Type for pg_auth_mode
- **Source**: Compete #5, FIX 3
- **File**: `geotiler/config.py` line 74
- **Issue**: Accepts arbitrary strings; only 3 values valid. Typos fail cryptically at runtime.
- **Fix**: `pg_auth_mode: Literal["password", "key_vault", "managed_identity"] = "password"`
- **Effort**: Small (< 15 minutes)

#### 8. Fix __main__.py CLI Argument Documentation
- **Source**: Compete #5, FIX 4
- **File**: `geotiler/__main__.py`
- **Issue**: Docstring claims `--host`/`--port` support that doesn't exist.
- **Fix**: Update docstring to reflect env-var-only config, align PORT reading with `main.py`.
- **Effort**: Small (< 15 minutes)

#### 9. Update main.py Stale Env Var Names in Docstring
- **Source**: Compete #5, FIX 5
- **File**: `geotiler/main.py` lines 30-34
- **Issue**: References old variable names (`OBSERVABILITY_MODE`, `APP_NAME`, etc.) instead of actual `GEOTILER_OBS_*` names.
- **Fix**: Update to match actual config.py documentation.
- **Effort**: Small (< 15 minutes)

---

## ACCEPTED RISKS (No Action)

These were reviewed and explicitly accepted across all pipelines.

| Issue | Severity | Source | Rationale |
|-------|----------|--------|-----------|
| STAC/TiPG pool sharing coupling | MEDIUM | Compete #5 | Documented intentional design with guard and warning |
| Settings singleton (`lru_cache`) | MEDIUM | Compete #5 | Standard pattern; tests can `cache_clear()` |
| Inline Swagger HTML in app.py | MEDIUM | Compete #5 | Necessary to fix upstream double-encoding bug |
| Unconditional `stac_fastapi` import in vector.py | HIGH | Reflexion #4 | Architectural decision — move to conditional when STAC made optional |
| Token expiry between acquisition and pool use | HIGH | Reflexion #4 | 5-minute buffer in cache makes this low probability |
| CatalogUpdateMiddleware races with refresh | MEDIUM | Reflexion #4 | Lock doesn't protect middleware; increase TTL or use webhook only |
| In-flight queries aborted by old pool close | MEDIUM | Reflexion #4 | `asyncpg.Pool.close()` waits for released connections |
| Health check false positive on closed pool | MEDIUM | Reflexion #4 | Would require active ping; low impact |
| DRY violation between init and refresh | MEDIUM | Reflexion #4 | Extract helper when either function next modified |
| asyncio.Lock at import time | MEDIUM | Compete #1 | Safe under uvicorn; document as deployment constraint |
| os.environ writes not thread-locked | MEDIUM | Compete #1 | CPython GIL makes individual writes atomic |
| DuckDB f-string column interpolation | MEDIUM | Compete #1 | Two-layer frozen-set + schema validation prevents injection |
| DuckDB cache bounded by count not memory | LOW | Compete #1 | 100 entries well under 100MB |
| Readiness/health token TTL threshold disagreement | MEDIUM | Compete #3 | Different endpoints serve different purposes |
| STAC module-level global | MEDIUM | Compete #3 | Required by stac-fastapi library |
| Partial parquet on interrupted download | MEDIUM | Compete #3 | Non-fatal; H3 unavailable but app runs |
| psutil.cpu_percent blocks event loop | LOW | Compete #3 + #5 | Only in /health, 100ms acceptable |
| Module-level template/settings instantiation | LOW | Compete #5 | Normal Python/FastAPI pattern |

---

## IMPLEMENTATION ORDER

### Phase A: Security (items #1, #3) — Do First
SQL injection + unauthenticated endpoints are the only exploitable vulnerabilities. Fix before any deployment.

### Phase B: Thread Safety (items #2, #4) — Do Second
DuckDB segfault risk affects production stability. Natural to combine both fixes (same file, same lock).

### Phase C: Cleanup (items #5, #6, #7, #8, #9) — Do Third
All MEDIUM/LOW severity, all quick fixes. Can be batched into a single commit.

### Phase D: Commit existing patches
The 10 already-applied patches from Phases 1 and 2 should be committed.

---

## CROSS-REFERENCE MATRIX

Shows which issues were independently discovered by multiple pipelines (higher confidence).

| Issue | Compete #1 | Reflexion #2 | Compete #3 | Reflexion #4 | Compete #5 |
|-------|-----------|-------------|-----------|-------------|-----------|
| DuckDB thread-safety | — | F-06 | FIX 3 | — | B2 confirm |
| DuckDB cache race | — | F-07 | FIX 4 | — | B3 confirm |
| Pool atomic swap (pgSTAC) | FIX 1 | F-02 | — | — | — |
| Pool atomic swap (TiPG) | — | F-11 | FIX 5 | Patch A | — |
| Middleware fail-closed | FIX 2 | F-04 | — | — | — |
| Background task guard | FIX 4 | F-03 | — | — | — |
| SQL injection diagnostics | — | — | FIX 1 | — | — |
| Unauthenticated diagnostics | — | — | FIX 2 | — | — |
| Duplicate templates | — | — | — | — | FIX 1 |
| Background task shutdown | — | — | — | — | FIX 2 |

**Highest confidence findings** (3+ independent discoveries): DuckDB thread-safety, pool atomic swap patterns.

---

## SUMMARY

| Category | Count | Status |
|----------|-------|--------|
| Already patched | 10 | Uncommitted in working tree |
| TODO: CRITICAL | 2 | SQL injection, DuckDB thread-safety |
| TODO: HIGH | 2 | Diagnostics auth, DuckDB cache |
| TODO: MEDIUM | 2 | Duplicate templates, shutdown cleanup |
| TODO: LOW | 3 | Config types, docstring fixes |
| Accepted risks | 19 | Documented, no action needed |
| **Total findings** | **38** | **10 patched, 9 TODO, 19 accepted** |
