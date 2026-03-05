# Documentation Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Archive stale docs, fix dangerous env var naming in surviving docs, and consolidate scattered root-level files into `docs/`.

**Architecture:** Pure file moves + text edits. No code changes. Three phases: archive, fix, reorganize.

**Tech Stack:** git, markdown editing

---

## Context

An audit found 11 files that should be archived, 4 deployment docs with wrong env var names (dangerous — cause broken deployments), and several docs with wrong base URLs or missing `GEOTILER_` prefix. The agent pipeline docs (`docs/agent_review/`, `docs/plans/`, `docs/greenfield/`) are current and should not be touched.

### Env Var Mapping (old → new)

These are the renames that must be applied in surviving docs:

| Old Name | New Name |
|----------|----------|
| `POSTGRES_AUTH_MODE` | `GEOTILER_PG_AUTH_MODE` |
| `POSTGRES_HOST` | `GEOTILER_PG_HOST` |
| `POSTGRES_DB` | `GEOTILER_PG_DB` |
| `POSTGRES_USER` | `GEOTILER_PG_USER` |
| `POSTGRES_PASSWORD` | `GEOTILER_PG_PASSWORD` |
| `USE_AZURE_AUTH` | `GEOTILER_ENABLE_STORAGE_AUTH` |
| `LOCAL_MODE` | `GEOTILER_AUTH_USE_CLI` |
| `AZURE_STORAGE_ACCOUNT` | (no longer an env var — storage auth uses MI scope) |
| `ENABLE_H3_DUCKDB` | `GEOTILER_ENABLE_H3_DUCKDB` |
| `H3_PARQUET_URL` | `GEOTILER_H3_PARQUET_URL` |
| `H3_DATA_DIR` | `GEOTILER_H3_DATA_DIR` |
| `H3_PARQUET_FILENAME` | `GEOTILER_H3_PARQUET_FILENAME` |
| `ENABLE_TIPG` | `GEOTILER_ENABLE_TIPG` |
| `TIPG_CATALOG_TTL_ENABLED` | `GEOTILER_ENABLE_TIPG_CATALOG_TTL` |
| `TIPG_CATALOG_TTL` | `GEOTILER_TIPG_CATALOG_TTL_SEC` |

### Base URL Fix

Old: `geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net`
New: `rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net`

Old storage account: `rmhazuregeo`
New storage account: `rmhstorage123`

---

### Task 1: Archive 11 stale files

Move these files to `docs/archive/`:

**From root:**
- `GCS.md` → `docs/archive/GCS.md`
- `UI_SPEC.md` → `docs/archive/UI_SPEC.md`
- `V0.8_REVIEW.md` → `docs/archive/V0.8_REVIEW.md`
- `greenfield-download-initiator-briefing (2).md` → `docs/archive/greenfield-download-initiator-briefing.md`

**From docs/:**
- `docs/DOCUMENTATION_PLAN.md` → `docs/archive/DOCUMENTATION_PLAN.md`
- `docs/OAUTH-TOKEN-APPROACH.md` → `docs/archive/OAUTH-TOKEN-APPROACH.md`
- `docs/PGSTAC-IMPLEMENTATION.md` → `docs/archive/PGSTAC-IMPLEMENTATION.md`
- `docs/VERSIONED_ASSETS_IMPLEMENTATION.md` → `docs/archive/VERSIONED_ASSETS_IMPLEMENTATION.md`
- `docs/TITILER-API-REFERENCE.md` → `docs/archive/TITILER-API-REFERENCE.md`
- `docs/endpoints/custom/RASTER_QUERY_API.md` → `docs/archive/RASTER_QUERY_API.md`
- `docs/endpoints/custom/XARRAY_QUERY_API.md` → `docs/archive/XARRAY_QUERY_API.md`
- `docs/analysis/CUSTOM_VS_DEFAULT_COMPARISON.md` → `docs/archive/CUSTOM_VS_DEFAULT_COMPARISON.md`
- `docs/roadmap/ARCGIS_MIGRATION.md` → `docs/archive/ARCGIS_MIGRATION.md`

After moves, remove empty directories: `docs/endpoints/custom/`, `docs/endpoints/`, `docs/analysis/`, `docs/roadmap/`.

**Step 1:** Run all `git mv` commands.
**Step 2:** Remove empty directories with `rmdir`.
**Step 3:** Commit: `docs: archive 13 stale documentation files`

---

### Task 2: Fix DUCKDB.md env var prefix

**Files:**
- Modify: `DUCKDB.md`

Find all instances of env var names missing the `GEOTILER_` prefix and fix them:

- `ENABLE_H3_DUCKDB` → `GEOTILER_ENABLE_H3_DUCKDB` (multiple occurrences)
- `H3_PARQUET_URL` → `GEOTILER_H3_PARQUET_URL` (multiple occurrences)
- `H3_DATA_DIR` → `GEOTILER_H3_DATA_DIR`
- `H3_PARQUET_FILENAME` → `GEOTILER_H3_PARQUET_FILENAME`
- Also fix the comparison table row: `ENABLE_TIPG` → `GEOTILER_ENABLE_TIPG`

**Step 1:** Apply all replacements.
**Step 2:** Commit: `docs: fix GEOTILER_ prefix in DUCKDB.md env var names`

---

### Task 3: Fix TIPG_CATALOG_ARCHITECTURE.md env var names

**Files:**
- Modify: `docs/TIPG_CATALOG_ARCHITECTURE.md`

Fix the env var names in the Solutions/Recommendations sections:

- `TIPG_CATALOG_TTL_ENABLED=true` → `GEOTILER_ENABLE_TIPG_CATALOG_TTL=true`
- `TIPG_CATALOG_TTL=60` → `GEOTILER_TIPG_CATALOG_TTL_SEC=60`

These appear on lines 187-188 and 297-298.

**Step 1:** Apply replacements.
**Step 2:** Commit: `docs: fix GEOTILER_ prefix in TIPG_CATALOG_ARCHITECTURE.md`

---

### Task 4: Fix base URLs in STAC-INTEGRATION-GUIDE.md

**Files:**
- Modify: `docs/STAC-INTEGRATION-GUIDE.md`

Replace all instances of:
- `geotiler-ghcyd7g0bxdvc2hc` → `rmhtitiler-ghcyd7g0bxdvc2hc`

**Step 1:** Apply replacement with replace_all.
**Step 2:** Commit: `docs: fix base URL in STAC-INTEGRATION-GUIDE.md`

---

### Task 5: Fix xarray.md — base URL and storage account

**Files:**
- Modify: `docs/xarray.md`

Replace:
- `geotiler-ghcyd7g0bxdvc2hc` → `rmhtitiler-ghcyd7g0bxdvc2hc` (all instances)
- `rmhazuregeo` → `rmhstorage123` (all instances)

Do NOT rewrite other content — the xarray doc is large (49KB) and mostly accurate. Just fix the two infrastructure references.

**Step 1:** Apply replacements with replace_all.
**Step 2:** Commit: `docs: fix base URL and storage account in xarray.md`

---

### Task 6: Move ROUTING_DESIGN.md from root to docs/

**Files:**
- Move: `ROUTING_DESIGN.md` → `docs/ROUTING_DESIGN.md`

**Step 1:** `git mv ROUTING_DESIGN.md docs/ROUTING_DESIGN.md`
**Step 2:** Commit: `docs: move ROUTING_DESIGN.md into docs/ directory`

---

### Task 7: Update README.md feature list

**Files:**
- Modify: `README.md`

The README only mentions COG and pgSTAC. It needs to list the current feature set. Read the current README, then update the features/capabilities section to include:
- Zarr/NetCDF via titiler.xarray
- OGC Features API + Vector Tiles via TiPG
- STAC catalog browsing and search
- H3 Explorer with server-side DuckDB
- Interactive map viewers for each data type

Keep the existing README structure and tone. Only update the feature list and any obviously wrong information. Do not add emoji if none are present.

**Step 1:** Read README.md fully.
**Step 2:** Update feature list.
**Step 3:** Commit: `docs: update README.md with current feature set`

---

## Task Dependency

Tasks 1-6 are independent of each other. Task 7 depends on nothing but should run last (it's the lowest priority fix).

## Not In Scope

- **Rewriting QA_DEPLOYMENT.md, NEW_TENANT_DEPLOYMENT.md, AZURE-CONFIGURATION-REFERENCE.md, README-LOCAL.md** — These 4 deployment docs need full rewrites (every env var is wrong), which is a separate effort. They are left as-is with their stale content for now.
- **Rewriting xarray.md content** — Only fixing infrastructure references, not restructuring the 49KB doc.
- **Agent review docs** — Confirmed current, not touched.
