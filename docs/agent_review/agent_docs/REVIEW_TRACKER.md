# Code Review Execution Tracker

**Created**: 26 FEB 2026
**Pipelines**: Compete Agent + Reflexion Agent (see `docs/agent_review/`)

---

## Execution Order

### Phase 1: Auth & Token Lifecycle

| # | Pipeline | Target | Files | Status |
|---|----------|--------|-------|--------|
| 1 | Compete Agent | Auth & Token Lifecycle | `auth/cache.py`, `auth/storage.py`, `auth/postgres.py`, `services/background.py`, `middleware/azure_auth.py` | **Complete** |
| 2 | Reflexion Agent | Token Lifecycle (chained from #1, Delta rec.) | `auth/cache.py`, `services/background.py`, `middleware/azure_auth.py` | **Complete** (6 patches applied) |

### Phase 2: Data Services & Routing

| # | Pipeline | Target | Files | Status |
|---|----------|--------|-------|--------|
| 3 | Compete Agent | Data Services & Routing | `routers/health.py`, `routers/vector.py`, `routers/diagnostics.py`, `routers/stac.py`, `services/database.py`, `services/duckdb.py` | **Complete** |
| 4 | Reflexion Agent | Vector/TiPG Pool (chained from #3) | `routers/vector.py` | **Complete** (4 patches applied) |

### Phase 3: App Core & Startup

| # | Pipeline | Target | Files | Status |
|---|----------|--------|-------|--------|
| 5 | Compete Agent | App Core & Startup Orchestration | `main.py`, `app.py`, `config.py`, `openapi.py`, `templates_utils.py`, `__main__.py` | **Complete** |
| 6 | Reflexion Agent | DuckDB + H3 (newest code) | `services/duckdb.py`, `routers/h3_explorer.py` | **Skipped** (user decision) |

---

## Chaining Logic

```
Compete #1 (Auth broad)  ──findings──▶ Reflexion #1 (cache.py focused)
Compete #3 (Data broad)  ──findings──▶ Reflexion #3 (vector.py focused)
Compete #5 (App Core)    ──standalone
Reflexion #6 (DuckDB)    ──standalone (newest, least battle-tested)
```

---

## Out of Scope

Low-risk template renderers excluded from review:
- `routers/cog_landing.py`, `routers/xarray_landing.py`, `routers/searches_landing.py`
- `routers/stac_explorer.py`, `routers/map_viewer.py`, `routers/docs_guide.py`
- `routers/admin.py`

`infrastructure/` module (logging, telemetry, latency, middleware) — review only if Compete Agent reviews surface concerns.

---

## Residual Risks (from Phase 1)

Carried forward from Reflexion Agent #2 — unpatched issues to target in later phases:

| ID | Severity | Target Phase | File | Description |
|----|----------|-------------|------|-------------|
| F-06 | CRITICAL | Phase 3 (#6) | `services/duckdb.py` | DuckDB connection shared across `asyncio.to_thread()` without lock — can segfault |
| F-11 | HIGH | Phase 2 (#4) | `routers/vector.py` | Stale STAC pool aliases after TiPG refresh failure |
| F-07 | MEDIUM | Phase 3 (#6) | `services/duckdb.py` | DuckDB query cache race — `next(iter(dict))` during concurrent modification |

---

## Results

| # | Pipeline | Output File | Written |
|---|----------|-------------|---------|
| 1 | Compete Agent | `ADVERSARIAL_REVIEW_1_AUTH.md` | 26 FEB 2026 |
| 2 | Reflexion Agent | `KLUDGE_HARDENER_1_CACHE.md` | 26 FEB 2026 |
| 3 | Compete Agent | `docs/agent_review/DATA_SERVICES.md` | 27 FEB 2026 |
| 4 | Reflexion Agent | `REFLEXION_AGENT_VECTOR.md` | 27 FEB 2026 |
| 5 | Compete Agent | `docs/agent_review/APP_CORE.md` | 27 FEB 2026 |
| 6 | Reflexion Agent | — | Skipped |
