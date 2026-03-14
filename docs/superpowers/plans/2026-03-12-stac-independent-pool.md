# STAC Independent Pool + CollectionSearchExtension

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple STAC API from TiPG's asyncpg pool, giving STAC its own pool with protocol-level `server_settings` that survive asyncpg's `RESET ALL`. Enable `CollectionSearchExtension` so `/stac/collections` uses `collection_search()` instead of the missing `all_collections()`.

**Architecture:** STAC gets its own asyncpg pool created via `stac-fastapi-pgstac`'s native `connect_to_db()` with `server_settings={"search_path": "pgstac,public"}`. This eliminates the shared-pool workarounds (pool._setup patching, per-acquire SET search_path). TiPG keeps its own pool for geometry-heavy work. Background token refresh cycle refreshes both pools independently.

**Tech Stack:** stac-fastapi-pgstac (connect_to_db, CollectionSearchExtension, PostgresSettings, ServerSettings), asyncpg, FastAPI lifespan

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `geotiler/routers/stac.py` | **Rewrite** | Add CollectionSearchExtension, pool lifecycle (init/close/refresh/verify) |
| `geotiler/routers/vector.py` | **Modify** | Remove STAC workarounds (stac_get_connection, _patch_pool_search_path, pgstac schema injection, STAC aliases) |
| `geotiler/app.py` | **Modify** | Add STAC pool init/close to lifespan, decouple STAC from TiPG enable flag |
| `geotiler/routers/health.py` | **Modify** | Rewrite STAC canary for independent pool (app.state.readpool) |
| `geotiler/services/background.py` | **Modify** | Add STAC pool refresh to token refresh cycle |

---

## Task 1: Rewrite `stac.py` — Add CollectionSearchExtension + Independent Pool

**Files:**
- Rewrite: `geotiler/routers/stac.py`

The QA branch has the complete working version. We adopt it with our diagnostic enhancements (db_user, unqualified_call canary from earlier work).

- [ ] **Step 1: Replace stac.py with QA version**

Replace the entire file. Key changes from current:
- Import `CollectionSearchExtension` from `stac_fastapi.extensions.core`
- Import `PostgresSettings`, `ServerSettings`, `connect_to_db`, `close_db_connection` from `stac_fastapi.pgstac`
- Import `get_postgres_credential`, `build_database_url` from `geotiler.auth.postgres`
- Add `CollectionSearchExtension.from_extensions()` with Fields + Sort
- Pass `collections_get_request_model` to `StacApi()`
- Add `_build_stac_postgres_settings()` — constructs settings with `server_settings={"search_path": "pgstac,public", "application_name": "geotiler-stac"}`
- Add `initialize_stac_pool(app)` — creates pool via `stac_connect_to_db()`, calls `_verify_stac_pool()`
- Add `_verify_stac_pool(app)` — checks search_path, pgstac schema, `collection_search()`, `search()`
- Add `close_stac_pool(app)` — clean shutdown
- Add `refresh_stac_pool(app)` — credential rotation with `asyncio.Lock` concurrency guard

Source: QA branch `geotiler/routers/stac.py` (already fetched to `/tmp/qa_stac.py`)

- [ ] **Step 2: Verify imports resolve**

Run: `python -c "from geotiler.routers.stac import create_stac_api, initialize_stac_pool, close_stac_pool, refresh_stac_pool"`

Expected: No import errors (may warn about missing DB, that's fine)

- [ ] **Step 3: Commit**

```bash
git add geotiler/routers/stac.py
git commit -m "feat: independent STAC pool + CollectionSearchExtension

Decouple STAC API from TiPG's shared asyncpg pool. STAC now gets
its own pool via stac-fastapi-pgstac's connect_to_db() with
server_settings that survive asyncpg's RESET ALL.

Enable CollectionSearchExtension so /stac/collections uses
collection_search() instead of the deprecated all_collections()."
```

---

## Task 2: Clean up `vector.py` — Remove STAC Workarounds

**Files:**
- Modify: `geotiler/routers/vector.py`

Remove all STAC-specific code from vector.py. TiPG should only care about TiPG.

- [ ] **Step 1: Remove STAC imports and stac_get_connection wrapper (lines 25-48)**

Remove:
```python
# Import STAC API database function for pool sharing
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Literal
from asyncpg import Connection
from fastapi import Request
from stac_fastapi.pgstac.db import get_connection as _stac_get_connection_raw


@asynccontextmanager
async def stac_get_connection(
    request: Request,
    readwrite: Literal["r", "w"] = "r",
) -> AsyncIterator[Connection]:
    """..."""
    async with _stac_get_connection_raw(request, readwrite) as conn:
        await conn.execute("SET search_path TO pgstac, public;")
        yield conn
```

- [ ] **Step 2: Remove `_patch_pool_search_path()` function (lines 60-85)**

Remove the entire function. No longer needed — each pool manages its own search_path.

- [ ] **Step 3: Remove pgstac schema injection from `initialize_tipg()` (lines 232-235)**

Remove:
```python
        # Add pgstac schema if STAC API is enabled (stac-fastapi-pgstac needs it in search_path)
        if settings.enable_stac_api and "pgstac" not in schemas:
            schemas.append("pgstac")
            logger.debug("Added pgstac schema for STAC API support")
```

- [ ] **Step 4: Remove pool patching and STAC aliases from `initialize_tipg()` (lines 246-255)**

Remove:
```python
        # Patch pool with setup callback to set search_path on every acquire
        # (survives asyncpg's RESET ALL on connection return)
        _patch_pool_search_path(app.state.pool, schemas)

        # Set up STAC API database aliases to share the pool
        # stac-fastapi-pgstac expects readpool/writepool and get_connection
        if settings.enable_stac_api:
            app.state.readpool = app.state.pool
            app.state.writepool = app.state.pool
            app.state.get_connection = stac_get_connection
            logger.debug("STAC API database aliases configured")
```

- [ ] **Step 5: Remove pgstac injection and STAC aliases from `_refresh_tipg_pool_inner()` (lines 358-380)**

Remove the pgstac schema append block:
```python
        # Add pgstac schema if STAC API is enabled
        if settings.enable_stac_api and "pgstac" not in schemas:
            schemas.append("pgstac")
```

Remove the pool patching:
```python
        # Patch new pool with setup callback (same as startup)
        _patch_pool_search_path(app.state.pool, schemas)
```

Remove the STAC alias re-establishment:
```python
        # Re-establish STAC API database aliases (pointing to new pool)
        if settings.enable_stac_api:
            app.state.readpool = app.state.pool
            app.state.writepool = app.state.pool
            app.state.get_connection = stac_get_connection
```

- [ ] **Step 6: Verify imports resolve**

Run: `python -c "from geotiler.routers.vector import initialize_tipg, close_tipg, refresh_tipg_pool"`

Expected: No import errors

- [ ] **Step 7: Commit**

```bash
git add geotiler/routers/vector.py
git commit -m "refactor: remove STAC workarounds from vector.py

STAC has its own pool now — remove stac_get_connection wrapper,
_patch_pool_search_path hack, pgstac schema injection, and
STAC pool aliases from TiPG initialization and refresh."
```

---

## Task 3: Update `app.py` — STAC Pool Lifecycle + Decouple from TiPG

**Files:**
- Modify: `geotiler/app.py`

- [ ] **Step 1: Add STAC pool init to lifespan startup (after TiPG init, before storage auth)**

After the TiPG initialization block (line ~73), add:

```python
    # Initialize STAC API pool (own asyncpg pool with native server_settings)
    if settings.enable_stac_api and settings.has_postgres_config:
        try:
            await stac.initialize_stac_pool(app)
        except Exception:
            logger.warning("STAC API pool failed - endpoints will be unavailable")
```

- [ ] **Step 2: Add STAC pool close to lifespan shutdown (before TiPG close)**

Before the TiPG close block, add:

```python
    # Close STAC pool (before TiPG - STAC is independent now)
    if settings.enable_stac_api:
        await stac.close_stac_pool(app)
```

- [ ] **Step 3: Decouple STAC router from TiPG enable flag**

Change:
```python
    if settings.enable_stac_api and settings.enable_tipg:
```
To:
```python
    if settings.enable_stac_api:
```

Remove the `elif` warning block:
```python
    elif settings.enable_stac_api and not settings.enable_tipg:
        logger.warning("STAC API requires TiPG to be enabled (shared pool)")
        logger.warning("Set GEOTILER_ENABLE_TIPG=true to enable STAC API")
```

Also update the STAC Explorer guard from `if settings.enable_stac_api and settings.enable_tipg:` to `if settings.enable_stac_api:`.

- [ ] **Step 4: Commit**

```bash
git add geotiler/app.py
git commit -m "feat: STAC pool lifecycle in lifespan, decouple from TiPG

STAC API no longer requires enable_tipg=true. Initialize and close
STAC's independent pool in the app lifespan handler."
```

---

## Task 4: Update `health.py` — STAC Canary for Independent Pool

**Files:**
- Modify: `geotiler/routers/health.py`

Replace the current STAC API health check block (which uses TiPG's shared pool + our earlier diagnostic additions) with the independent pool version that checks `app.state.readpool` directly.

- [ ] **Step 1: Replace the STAC API section**

Replace the entire `# STAC API` block (from `if settings.enable_stac_api:` through the final `else` block) with the QA version that:
- Checks `app.state.readpool` instead of TiPG's `app.state.pool`
- Reports `pool: "independent (asyncpg)"` with pool size diagnostics
- Does a live probe with `collection_search()` (unqualified — should work since pool has correct server_settings)
- Removes the "requires GEOTILER_ENABLE_TIPG" disabled reason
- Keeps our db_user and search_path diagnostics
- Adds the unqualified_call secondary canary we built earlier

- [ ] **Step 2: Commit**

```bash
git add geotiler/routers/health.py
git commit -m "feat: health check uses STAC's independent pool

Check app.state.readpool directly. Report pool diagnostics,
search_path, db_user, and collection_search() probe results."
```

---

## Task 5: Update `background.py` — Add STAC Pool Refresh

**Files:**
- Modify: `geotiler/services/background.py`

- [ ] **Step 1: Import refresh_stac_pool**

Add to imports:
```python
from geotiler.routers.stac import refresh_stac_pool
```

- [ ] **Step 2: Add STAC pool refresh after TiPG refresh**

In `_refresh_postgres_with_pool_recreation()`, after the TiPG refresh block (line ~118), add:

```python
        # 3. Refresh STAC pool (asyncpg, app.state.readpool)
        if settings.enable_stac_api:
            try:
                await refresh_stac_pool(app)
            except Exception as stac_err:
                logger.error(f"Failed to refresh STAC pool: {stac_err}")
```

- [ ] **Step 3: Commit**

```bash
git add geotiler/services/background.py
git commit -m "feat: refresh STAC pool during token rotation

Add STAC pool refresh alongside TiPG pool refresh in the
background token rotation cycle."
```

---

## Task 6: Version Bump + Final Verification

- [ ] **Step 1: Bump version**

In `geotiler/__init__.py`, bump from `0.9.4.0` to `0.9.5.0`.

- [ ] **Step 2: Verify all imports**

Run:
```bash
python -c "
from geotiler.routers.stac import create_stac_api, initialize_stac_pool, close_stac_pool, refresh_stac_pool
from geotiler.routers.vector import initialize_tipg, close_tipg, refresh_tipg_pool
from geotiler.services.background import start_token_refresh
from geotiler.app import create_app
print('All imports OK')
"
```

- [ ] **Step 3: Commit version bump**

```bash
git add geotiler/__init__.py
git commit -m "v0.9.5.0"
```
