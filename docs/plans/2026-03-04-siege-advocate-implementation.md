# SIEGE & ADVOCATE Retooling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite SIEGE_AGENT.md, ADVOCATE_AGENT.md, and create siege_config_titiler.json for rmhtitiler's stateless tile server surface.

**Architecture:** Three standalone markdown/JSON files. No code changes — these are agent pipeline specifications consumed by Claude during pipeline runs. The design doc at `docs/plans/2026-03-04-siege-advocate-retool-design.md` contains all approved content.

**Tech Stack:** Markdown, JSON. No application code.

---

### Task 1: Create siege_config_titiler.json

**Files:**
- Create: `docs/agent_review/siege_config_titiler.json`

**Reference:** Design doc section "siege_config_titiler.json Design" has the approved schema. Live endpoint data confirmed:
- COG: `/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif` (3-band uint8, DC area)
- Zarr: `abfs://silver-zarr/cmip6-tasmax-sample.zarr` (variable=tasmax, 12 time steps, Kelvin)
- Vector: `geo.sg7_vector_test_cutlines_ord1` (1401 MultiPolygon features)
- STAC: `sg-raster-test-dctest` collection, item `sg-raster-test-dctest-v1`, assets: data + thumbnail

**Step 1: Write the config file**

Create `docs/agent_review/siege_config_titiler.json` with:
- `target`: base_url, storage_account
- `test_data`: cog, zarr, vector, stac sections with URLs, expected values, and descriptions
- `endpoint_access_rules`: consumer, verification, synthesis tiers with rmhtitiler endpoints
- `cartographer_probes`: full endpoint probe table (COG, Xarray, Vector, STAC, health)
- `namespaces`: siege (sg-), advocate (adv-)

The config must include ALL endpoints from the Cartographer Probe Table in the design doc. Structure the probes as objects with method, path, params, and expected HTTP code.

For `endpoint_access_rules`, model after rmhgeoapi's siege_config.json structure but replace all platform/dbadmin/storage endpoints with tile server endpoints:
- Consumer: `/cog/*`, `/xarray/*`, `/vector/*`, `/stac/*`
- Verification: `/health`, `/livez`, `/readyz`, `/vector/diagnostics`
- No setup endpoints needed (stateless server)

**Step 2: Validate JSON syntax**

Run: `python3 -c "import json; json.load(open('docs/agent_review/siege_config_titiler.json')); print('Valid JSON')"`
Expected: `Valid JSON`

**Step 3: Commit**

```bash
git add docs/agent_review/siege_config_titiler.json
git commit -m "feat: add siege_config_titiler.json for tile server agent pipelines"
```

---

### Task 2: Rewrite SIEGE_AGENT.md

**Files:**
- Modify: `docs/agent_review/agents/SIEGE_AGENT.md` (full rewrite)

**Reference:** Design doc sections "SIEGE Pipeline Design" through "Information Flow Summary". The existing file contains the rmhgeoapi version — replace entirely.

**Step 1: Write the new SIEGE_AGENT.md**

The document must contain these sections in order (all content is in the design doc):

1. **Header**: Title, purpose, best-for statement — adapted for "tile server smoke test"
2. **Endpoint Access Rules**: Consumer / Verification / Synthesis tiers (no Setup tier — stateless server)
3. **Agent Roles table**: Sentinel, Cartographer, Lancer, Auditor, Scribe — same structure, inputs reference siege_config_titiler.json
4. **Flow diagram**: ASCII flowchart showing linear Sentinel → Cartographer → Lancer → Auditor → Scribe
5. **Prerequisites**: Health check only — no schema rebuild, no STAC nuke. Just verify `/health` reports all services healthy.
6. **Campaign Config**: Reference `siege_config_titiler.json`, explain what it contains
7. **Step 1: Play Sentinel**: Read config, verify health, output Campaign Brief with BASE_URL, test data table, endpoint list, read chain sequences
8. **Step 2: Dispatch Cartographer**: Full probe table from design doc (COG, Xarray, Vector, STAC consumer endpoints + health/livez/readyz verification). Include Cartographer Output Format (Endpoint Map table + Health Assessment).
9. **Step 3: Dispatch Lancer**: All 5 sequences (COG Read Chain, Zarr Read Chain, Vector Read Chain, STAC Discovery Chain, Cross-Service Consistency). Include Checkpoint Format and HTTP Log Format from design doc.
10. **Step 4: Dispatch Auditor**: Audit checks table (bounds consistency, tile validity, response time, STAC→Tile chain, variable consistency, collection count, TileJSON schema). Include Auditor Output Format.
11. **Step 5: Dispatch Scribe**: Scribe Output Format with Service Results table (not Workflow Results). Save instructions: `SIEGE_RUN_{N}.md` + log in AGENT_RUNS.md.
12. **Information Flow Summary**: Who gets what, who doesn't get what.
13. **Closing note**: Minimal information asymmetry by design — speed and completeness, not adversarial. For adversarial, use TOURNAMENT.

Key differences from rmhgeoapi version to verify:
- No `/api/platform/*` endpoints anywhere
- No submit/approve/reject lifecycle sequences
- No prerequisites section with rebuild/nuke
- Lancer sequences are read chains, not mutation chains
- Auditor compares metadata (bounds, content-types) not DB rows (job status, approval state)
- Checkpoints capture tile rendering results, not workflow state

**Step 2: Verify no rmhgeoapi references remain**

Run: `grep -ci "platform\|submit\|approve\|reject\|unpublish\|dbadmin\|rmhgeoapi\|rmhazuregeo\|bronze" docs/agent_review/agents/SIEGE_AGENT.md`
Expected: `0` (no matches)

**Step 3: Commit**

```bash
git add docs/agent_review/agents/SIEGE_AGENT.md
git commit -m "feat: rewrite SIEGE_AGENT.md for tile server smoke testing"
```

---

### Task 3: Rewrite ADVOCATE_AGENT.md

**Files:**
- Modify: `docs/agent_review/agents/ADVOCATE_AGENT.md` (full rewrite)

**Reference:** Design doc sections "ADVOCATE Pipeline Design" through the end. The existing file contains the rmhgeoapi version — replace entirely.

**Step 1: Write the new ADVOCATE_AGENT.md**

The document must contain these sections in order (all content is in the design doc):

1. **Header**: Title, purpose ("evaluate tile server from frontend developer perspective"), best-for statement
2. **Endpoint Access Rules**: Consumer (tile endpoints + landing pages + viewers) / Synthesis. No Setup tier. Hard rule: no `/health`, `/admin/*`, `/vector/diagnostics`.
3. **Agent Roles table**: Dispatcher, Intern, Architect, Editor — with rmhtitiler personas
4. **Flow diagram**: ASCII flowchart showing Dispatcher → Phase 1 (Intern) → Phase 2 (Architect) → Phase 3 (Editor)
5. **Campaign Config**: Reference `siege_config_titiler.json`
6. **Prerequisites**: None needed — stateless server. Optional health check by Dispatcher only.
7. **Step 1: Play Dispatcher**: Read config, define adv- namespace test data, write Intern Brief + Architect Brief skeleton
8. **Step 2: Dispatch Intern**: Full Intern Persona (frontend dev building map app), Intern Instructions (exploration strategy for COG/Zarr/Vector/STAC), step recording format, all 10 Friction Categories, Intern Output Format (with COG/Zarr/Vector/STAC walkthrough sections instead of Raster/Vector/NetCDF)
9. **Step 3: Dispatch Architect**: Full Architect Persona (senior API architect, mapping API experience), Phase A–D instructions with rmhtitiler-specific dimension focus table, Cross-Endpoint Consistency comparisons (cog/info vs xarray/info, etc.), Service URL Audit per family, Severity Scale, Architect Output Format
10. **Step 4: Play Editor**: Editor Procedure (deduplicate, validate, theme, prioritize, score), Scoring Rubric (6 categories with tile-server-specific descriptions), Editor Output Format with DX Score table, Themes, All Findings, What Works Well, Prioritized Action Plan (P0/P1/P2), Pipeline Chain Recommendations
11. **Save Output**: `ADVOCATE_RUN_{N}.md` + log in AGENT_RUNS.md
12. **Information Asymmetry Summary**: 4-row table (Dispatcher/Intern/Architect/Editor) with Gets/Doesn't Get/Why
13. **Key Design Insight**: Sequential Handoff explanation — Intern's friction → Architect's investigation queue
14. **Token Estimate**: Estimated tokens per agent
15. **When to Run ADVOCATE**: Scenario table (after SIEGE passes = YES, during active dev = NO, etc.)

Key differences from rmhgeoapi version to verify:
- Intern persona is "frontend dev building a map app", not "junior dev at DDH integrating platform API"
- Intern lifecycle is "discover → info → tiles → render" not "submit → poll → approve → discover → render"
- Architect Phase D evaluates tile rendering chain, not platform workflow state
- No `/api/platform/*` endpoints anywhere
- Cross-endpoint consistency compares COG/Xarray/Vector/STAC, not status/approvals/catalog
- Test data is COG URL + Zarr URL + vector collection, not dataset_id + resource_id + file_name

**Step 2: Verify no rmhgeoapi references remain**

Run: `grep -ci "platform\|submit\|approve\|reject\|unpublish\|dbadmin\|rmhgeoapi\|rmhazuregeo\|bronze\|DDH\|Data Delivery Hub" docs/agent_review/agents/ADVOCATE_AGENT.md`
Expected: `0` (no matches)

**Step 3: Commit**

```bash
git add docs/agent_review/agents/ADVOCATE_AGENT.md
git commit -m "feat: rewrite ADVOCATE_AGENT.md for tile server DX audit"
```

---

### Task 4: Final verification and summary commit

**Files:**
- Verify: `docs/agent_review/siege_config_titiler.json`
- Verify: `docs/agent_review/agents/SIEGE_AGENT.md`
- Verify: `docs/agent_review/agents/ADVOCATE_AGENT.md`

**Step 1: Cross-reference config and specs**

Verify that:
- Every endpoint in siege_config_titiler.json is referenced in SIEGE_AGENT.md's Cartographer probe table
- Every test data URL in the config matches what SIEGE Lancer and ADVOCATE Intern use
- Both specs reference `siege_config_titiler.json` (not `siege_config.json`)

Run: `grep -c "siege_config_titiler.json" docs/agent_review/agents/SIEGE_AGENT.md docs/agent_review/agents/ADVOCATE_AGENT.md`
Expected: Both files show at least 1 match

**Step 2: Verify no rmhgeoapi references in any of the three files**

Run: `grep -rci "platform/submit\|platform/approve\|platform/reject\|dbadmin\|rmhazuregeo\|bronze\|DDH" docs/agent_review/agents/SIEGE_AGENT.md docs/agent_review/agents/ADVOCATE_AGENT.md docs/agent_review/siege_config_titiler.json`
Expected: All show `0`

**Step 3: Verify JSON is valid**

Run: `python3 -c "import json; json.load(open('docs/agent_review/siege_config_titiler.json')); print('Valid JSON')"`
Expected: `Valid JSON`
