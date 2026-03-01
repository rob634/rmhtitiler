# Compete Agent #5: App Core & Startup Orchestration

**Date**: 27 FEB 2026
**Pipeline**: Compete Agent (Omega → Alpha+Beta → Gamma → Delta)
**Scope**: `main.py`, `app.py`, `config.py`, `openapi.py`, `templates_utils.py`, `__main__.py`
**Scope Split**: Split A (Design vs Runtime) — Alpha reviewed architecture/design patterns, Beta reviewed correctness/reliability

---

## EXECUTIVE SUMMARY

The App Core & Startup subsystem is well-architected. The critical initialization ordering in `main.py` (Telemetry → Logging → App Factory) is correct and well-documented. The non-fatal startup pattern allows degraded mode when database or TiPG initialization fails. The OpenAPI post-processor cleanly fixes upstream library quirks. However, there is a duplicate `Jinja2Templates` instance (one in `app.py`, one in `templates_utils.py`) that should be consolidated, and the background refresh task is not explicitly cancelled during shutdown. Several minor documentation issues exist (`__main__.py` claims CLI arg support that doesn't exist, `main.py` docstring has stale env var names). The codebase would benefit from using `Literal` for `pg_auth_mode` to catch typos at startup.

---

## TOP 5 FIXES

### FIX 1: Consolidate Duplicate Jinja2Templates Instances
- **WHAT**: Two `Jinja2Templates` instances exist — `app.state.templates` (`app.py` line 292) and module-level `templates` (`templates_utils.py` line 19). Both point to the same directory.
- **WHY**: Ambiguous which is canonical. If a router uses `request.app.state.templates` and another imports `templates_utils.templates`, they're different objects. Could diverge if directory paths change. `templates_utils.py` also provides `get_template_context()` and `render_template()` — it's the intended canonical source.
- **WHERE**: `geotiler/app.py` line 292, `geotiler/templates_utils.py` line 19
- **HOW**: Remove `app.state.templates = Jinja2Templates(directory=templates_dir)` from `app.py`. If any router accesses `request.app.state.templates`, change it to import from `templates_utils`. Remove the `from starlette.templating import Jinja2Templates` import in `app.py` if no longer needed.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — verify no router uses `request.app.state.templates` first.

### FIX 2: Cancel Background Refresh Task on Shutdown
- **WHAT**: `app.state.refresh_task` (set at `app.py` line 85) is never explicitly cancelled during shutdown.
- **WHY**: During shutdown, pools are closed (lines 103-110) but the background refresh task may still be running. If its next cycle fires between pool closure and event loop shutdown, it will encounter closed connections and log errors. While asyncio cleanup handles eventual cancellation, explicit cancellation is cleaner.
- **WHERE**: `geotiler/app.py`, shutdown block (after line 99)
- **HOW**: Add at the start of the shutdown block:
  ```python
  if hasattr(app.state, "refresh_task"):
      app.state.refresh_task.cancel()
      try:
          await app.state.refresh_task
      except asyncio.CancelledError:
          pass
  ```
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — `CancelledError` is the expected outcome.

### FIX 3: Use Literal Type for pg_auth_mode
- **WHAT**: `pg_auth_mode: str = "password"` in `config.py` line 74 accepts any string value, but only 3 values are valid: `password`, `key_vault`, `managed_identity`.
- **WHY**: A typo like `"managd_identity"` would silently fall through conditionals, likely defaulting to password auth and failing cryptically.
- **WHERE**: `geotiler/config.py` line 74
- **HOW**: Change to `pg_auth_mode: Literal["password", "key_vault", "managed_identity"] = "password"`. Pydantic will reject invalid values at startup with a clear error.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — existing valid configs are unchanged. Invalid configs get a clear startup error instead of cryptic runtime failure.

### FIX 4: Fix __main__.py CLI Argument Documentation
- **WHAT**: `__main__.py` docstring claims `python -m geotiler --host 0.0.0.0 --port 8000` works, but `main()` hardcodes `host="0.0.0.0"` and `port=8000` with no argument parsing.
- **WHY**: Misleading for developers. Passing `--host` or `--port` has no effect — uvicorn may error on unknown args depending on how they're forwarded.
- **WHERE**: `geotiler/__main__.py` lines 5-7 (docstring) and line 12-18 (function)
- **HOW**: Either add `argparse` with defaults matching the hardcoded values, or remove the `--host`/`--port` claims from the docstring. Given `main.py` already reads `PORT` from env, prefer aligning: use `os.environ.get("PORT", "8000")` and update docstring to reflect env-var-only config.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — dev convenience only.

### FIX 5: Update main.py Stale Docstring Env Var Names
- **WHAT**: `main.py` docstring (lines 30-34) references old env var names: `OBSERVABILITY_MODE`, `SLOW_REQUEST_THRESHOLD_MS`, `APP_NAME`, `ENVIRONMENT`.
- **WHY**: These don't match actual config. The real variables are `GEOTILER_ENABLE_OBSERVABILITY`, `GEOTILER_OBS_SLOW_THRESHOLD_MS`, `GEOTILER_OBS_SERVICE_NAME`, `GEOTILER_OBS_ENVIRONMENT` (read via `os.environ` in infrastructure modules, per config.py docstring).
- **WHERE**: `geotiler/main.py` lines 30-34
- **HOW**: Update to correct variable names.
- **EFFORT**: Small (< 30 minutes)
- **RISK OF FIX**: None — documentation only.

---

## ACCEPTED RISKS

| Issue | Severity | Why Acceptable | Revisit When |
|-------|----------|----------------|--------------|
| STAC/TiPG pool sharing coupling | MEDIUM | Documented intentional design (app.py:354-365). Guard prevents STAC without TiPG. Warning logged. | Needing to run STAC independently of TiPG |
| Settings singleton (`lru_cache`) | MEDIUM | Standard Pydantic Settings pattern. Tests can `get_settings.cache_clear()`. | Adding parallel test execution |
| Inline Swagger HTML in app.py | MEDIUM | Necessary to fix Swagger UI double-encoding bug (`%2F` → `%252F`). Well-commented. | Swagger UI fixes the upstream double-encoding |
| Module-level template/settings import | LOW | Normal Python/FastAPI pattern. Only matters for isolated unit tests. | Adding unit tests for template rendering |
| `psutil.cpu_percent(interval=0.1)` blocks event loop | LOW | Only in `/health` endpoint (already noted in Compete #3). 100ms acceptable. | Health probes called >10/sec |
| `config.py` logging uses root logger in `_parse_json_list` | LOW | Only fires on malformed JSON env vars — rare. Uses `logging.warning()` not `logger.warning()`. | Adding structured logging requirements for all modules |

---

## ARCHITECTURE WINS

1. **Critical import ordering in `main.py`**: Telemetry → Logging → App Factory. Azure Monitor OpenTelemetry must configure before FastAPI is imported for HTTP request instrumentation. This ordering is correct, documented, and enforced by the module structure.

2. **Non-fatal startup with structured state tracking**: Both `_initialize_database` (app.py:114-176) and `initialize_tipg` (vector.py:162-246) catch failures and allow degraded mode. The `db_error_cache.record_error()` pattern means `/health` can report exactly what failed.

3. **`templates_utils.py` centralization**: Provides `get_template_context()` with standard variables (version, feature flags) and `render_template()` helper. All routers get consistent context without duplication.

4. **OpenAPI post-processor pattern** (`openapi.py`): Clean approach to fixing upstream library tags/descriptions without vendored patches. The `_fix_operation` function handles deduplication, renaming, and description replacement in a maintainable way.

5. **Lifespan context manager**: Correctly replaces deprecated `@app.on_event()` pattern. Startup and shutdown are co-located for readability.

---

## PIPELINE METADATA

| Agent | Key Finding |
|-------|------------|
| **Omega** | Chose Split A (Design vs Runtime) to separate architectural patterns from operational correctness |
| **Alpha** | Duplicate templates (A1), settings singleton (A2), STAC/TiPG coupling (A3), untyped app.state (A4), __main__ CLI args (A5), inline Swagger HTML (A6) |
| **Beta** | Background task not cancelled (B1), DuckDB thread-safety confirmed (B2), DuckDB cache confirmed (B3), GDAL env race (B4), TiPG refresh lock lazy-init race (B5) |
| **Gamma** | Recalibrated A1 MEDIUM (no functional bug), reclassified A3 as accepted risk (documented design), promoted B1 to MEDIUM, found stale docstring env vars (G-5), confirmed A5 |
| **Delta** | Top 5 fixes: consolidate templates, cancel background task, Literal auth mode, __main__ args, stale docstring |

### All Recalibrated Findings

| # | Severity | Source | Description | Confidence |
|---|----------|--------|-------------|------------|
| 1 | MEDIUM | Alpha A1 + Gamma G-1 | Duplicate Jinja2Templates instances (app.py + templates_utils.py) | CONFIRMED |
| 2 | MEDIUM | Beta B1 + Gamma G-3 | Background refresh task not cancelled on shutdown | CONFIRMED |
| 3 | MEDIUM | Alpha A2 | Settings singleton hinders testability (lru_cache) | CONFIRMED (accepted risk) |
| 4 | MEDIUM | Alpha A3 + Gamma G-2 | STAC/TiPG coupling — reclassified as accepted risk | CONFIRMED (accepted risk) |
| 5 | MEDIUM | Alpha A4 | Untyped app.state as service locator | CONFIRMED (accepted risk — standard FastAPI) |
| 6 | MEDIUM | Alpha A6 | Inline Swagger HTML string | CONFIRMED (accepted risk — necessary fix) |
| 7 | MEDIUM | Beta B4 | GDAL env var `os.environ` is process-global | CONFIRMED (accepted risk — GDAL constraint) |
| 8 | LOW | Alpha A5 + Gamma G-6 | __main__.py claims CLI args not implemented | CONFIRMED |
| 9 | LOW | Gamma G-5 | main.py docstring stale env var names | CONFIRMED |
| 10 | LOW | Beta B2 | DuckDB thread-safety (confirmed from Compete #3) | CONFIRMED |
| 11 | LOW | Beta B3 | DuckDB cache FIFO mislabeled LRU (confirmed from Compete #3) | CONFIRMED |
| 12 | LOW | Beta B5 | TiPG refresh lock lazy-init TOCTOU race | PROBABLE (mitigated by single event loop) |
| 13 | LOW | Config review | pg_auth_mode accepts arbitrary strings | CONFIRMED |
| 14 | LOW | Config review | config.py _parse_json_list uses root logger | CONFIRMED |
