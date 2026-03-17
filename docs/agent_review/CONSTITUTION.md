# Constitution — Architectural Rules for Agent Review

**Last Updated**: 17 MAR 2026
**Applies To**: All code review agents (COMPETE, REFLEXION) and live testing agents (SIEGE, WARGAME, TOURNAMENT)

Agents MUST enforce these rules during review. Violations are classified by severity:
- **CRITICAL**: System will fail or produce incorrect results
- **HIGH**: System will degrade or behave unexpectedly under load
- **MEDIUM**: Maintainability or operational risk

---

## Section 1: Connection Pool Discipline

**Applies to**: COMPETE (Alpha, Beta), REFLEXION (F, P), WARGAME (Oracle), TOURNAMENT (Inspector)

### 1.1 Three Independent Pools — Never Share

The app maintains 3 separate connection pools. They must never be shared, merged, or cross-referenced:

| Pool | Library | Location | Purpose |
|------|---------|----------|---------|
| pgstac | psycopg (sync) | `app.state.dbpool` | titiler-pgstac mosaic tile rendering |
| TiPG | asyncpg | `app.state.pool` | OGC Features + Vector Tiles |
| STAC | asyncpg | `app.state.readpool` | STAC catalog browsing and search |

**Violation**: Any code that uses `app.state.pool` for STAC queries or `app.state.readpool` for TiPG operations. **Severity: CRITICAL**

### 1.2 Atomic Pool Refresh

Pool refresh (during MI token rotation) must follow the atomic swap pattern:
1. Create new pool with fresh credentials
2. Swap onto `app.state.*` (atomic assignment)
3. Close old pool only after new pool is live

**Violation**: Closing old pool before new pool is confirmed healthy, or any window where `app.state.*` holds a closed/None pool. **Severity: CRITICAL**

### 1.3 Pool Lifecycle Ownership

Pool lifecycle code lives in dedicated modules only:

| Pool | Owner Module |
|------|-------------|
| pgstac | `geotiler/services/background.py` (refresh), `geotiler/app.py` (init/close) |
| TiPG | `geotiler/routers/vector.py` |
| STAC | `geotiler/routers/stac.py` |

**Violation**: Raw pool access (acquiring connections, creating pools) from router handlers, templates, or utility modules. **Severity: HIGH**

---

## Section 2: Token & Auth Boundaries

**Applies to**: COMPETE (Alpha, Beta), REFLEXION (R, F), TOURNAMENT (Inspector)

### 2.1 Separate Token Caches

Two independent OAuth token caches exist — they must never be mixed:

| Cache | Scope | Purpose |
|-------|-------|---------|
| `storage_token_cache` | `https://storage.azure.com/.default` | GDAL/fsspec access to Azure Blob Storage |
| `postgres_token_cache` | `https://ossrdbms-aad.database.windows.net/.default` | PostgreSQL Managed Identity auth |

**Violation**: Using a storage token for database auth or vice versa. **Severity: CRITICAL**

### 2.2 Background-Only Token Refresh

Request handlers must never acquire fresh tokens. All token refresh happens in the background task (`token_refresh_background_task`), which runs every 45 minutes. Request handlers use whatever token is currently cached.

**Violation**: Calling `DefaultAzureCredential().get_token()` or any `refresh_*_token` function from a request handler. **Severity: HIGH**

### 2.3 Deferred Azure SDK Imports

All Azure Identity SDK imports must be deferred (inside functions, not at module level). This ensures the app can start even if Azure SDK initialization is slow or fails.

**Violation**: `from azure.identity import DefaultAzureCredential` at module level in any file except `auth/*.py`. **Severity: MEDIUM**

---

## Section 3: Configuration

**Applies to**: COMPETE (Alpha, Beta), REFLEXION (R, P)

### 3.1 Env Var Naming Convention

All application environment variables use `GEOTILER_COMPONENT_SETTING` with `env_prefix="GEOTILER_"` in Pydantic Settings:
- Boolean flags: `GEOTILER_ENABLE_*` (reads as a question)
- Time values include units: `*_SEC`, `*_MS`
- Pool sizes: `GEOTILER_POOL_{SERVICE}_MIN`, `GEOTILER_POOL_{SERVICE}_MAX`

**Exceptions** (not prefixed):
- `AZURE_TENANT_ID` — shared with Azure Identity SDK
- `APPLICATIONINSIGHTS_CONNECTION_STRING` — Azure Monitor convention
- `GDAL_*` — GDAL library convention

**Violation**: New env vars that don't follow the convention, or reading `os.environ` directly in service code. **Severity: MEDIUM**

### 3.2 No Hardcoded Azure Resource Names

Storage account names, database hostnames, Key Vault URLs, container names — all via env vars. Never hardcoded in Python code.

**Violation**: Any string literal that is an Azure resource identifier. **Severity: HIGH**

### 3.3 Version Single Source of Truth

`geotiler/__init__.py` is the only place the version string is defined. All other references import from there.

**Violation**: Version strings defined or hardcoded elsewhere. **Severity: MEDIUM**

---

## Section 4: Degraded Mode

**Applies to**: COMPETE (Beta), REFLEXION (F, P), SIEGE (Auditor), WARGAME (Oracle), TOURNAMENT (Inspector)

### 4.1 Non-Fatal Pool Initialization

If a connection pool fails to initialize (bad credentials, unreachable database), the app must:
1. Log the error clearly
2. Continue startup without that service
3. Report the service as unavailable in `/health`

**Violation**: Raising an exception that prevents app startup when a single pool fails. **Severity: CRITICAL**

### 4.2 Health Endpoint Always Responds

`/livez`, `/readyz`, and `/health` must always return HTTP 200 (or appropriate status) even when services are degraded. The response body reports what's broken — the endpoint itself must not fail.

**Violation**: Health endpoints that crash or timeout when a dependency is down. **Severity: HIGH**

### 4.3 Independent Feature Flags

Feature-flagged components must fail independently:

| Component | Flag | Failure Impact |
|-----------|------|---------------|
| TiPG | `GEOTILER_ENABLE_TIPG` | Vector endpoints unavailable, rest works |
| STAC API | `GEOTILER_ENABLE_STAC_API` | STAC endpoints unavailable, rest works |
| DuckDB | `GEOTILER_ENABLE_H3_DUCKDB` | H3 explorer unavailable, rest works |
| Downloads | `GEOTILER_ENABLE_DOWNLOADS` | Download endpoints unavailable, rest works |

**Violation**: One disabled/failed component taking down unrelated services. **Severity: CRITICAL**

---

## Section 5: No Mutation of External State

**Applies to**: All agents — especially WARGAME (Red), TOURNAMENT (Saboteur, Provocateur)

### 5.1 Read-Only Application

This application does not write to PostgreSQL and does not create or modify blobs in Azure Storage. It reads tiles, metadata, and catalog entries.

### 5.2 Permitted State Changes

Two operations create lightweight internal state:

| Operation | What It Creates | Scope |
|-----------|----------------|-------|
| `POST /searches/register` | pgSTAC search hash | Database row in `pgstac.searches` — a read-cache entry, not user data |
| `POST /admin/refresh-collections` | Refreshed TiPG in-memory catalog | Process memory only — no database writes |

### 5.3 Agent Testing Constraint

Live testing agents (SIEGE, WARGAME, TOURNAMENT) may only create state through the two operations above. They must never:
- Modify database tables directly
- Create or delete blobs
- Alter app configuration at runtime

**Violation**: Any agent step that writes to the database or storage beyond search registration. **Severity: CRITICAL**

---

## Quick Reference — Severity Mapping

| Severity | Examples |
|----------|---------|
| **CRITICAL** | Shared pools, token scope mixing, startup crash on pool failure, cross-service dependency failure |
| **HIGH** | Non-atomic pool swap, hardcoded Azure resources, background token in request path, health endpoint failure |
| **MEDIUM** | Env var naming violation, version duplication, module-level Azure imports |

## Scope Mapping — Which Sections Apply to Which Agents

### COMPETE
- **Alpha** (Architecture): Sections 1, 2, 3, 4
- **Beta** (Correctness): Sections 1, 2, 4, 5
- **Gamma** (Contradictions): All sections (cross-reference Alpha + Beta findings)

### REFLEXION
- **R** (Reverse-engineer): Sections 1, 2 (infer, don't enforce)
- **F** (Fault-find): Sections 1, 2, 4
- **P** (Patch): Sections 1, 2, 3, 4
- **J** (Judge): All sections

### SIEGE / WARGAME / TOURNAMENT
- All live testing agents: Section 5 (read-only constraint)
- Inspector / Oracle: Sections 1, 2, 4 (pool health, token state, degraded mode)
