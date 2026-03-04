# Design: SIEGE & ADVOCATE Pipeline Retooling for rmhtitiler

**Date**: 2026-03-04
**Status**: Approved
**Scope**: Retool SIEGE (smoke test) and ADVOCATE (DX audit) agent pipelines from rmhgeoapi's lifecycle-based platform API to rmhtitiler's stateless tile server surface.

---

## Context

The SIEGE and ADVOCATE pipelines were originally designed for rmhgeoapi — a B2B data delivery platform with a `submit → poll → approve → discover → render` lifecycle. rmhtitiler is a stateless read-only tile server with no mutations (except `/admin/refresh-collections`). The core pipeline structures are sound; the domain-specific content (endpoints, sequences, test data, personas) needs rewriting.

### Service Families in Scope

| Service | Prefix | Description |
|---------|--------|-------------|
| COG | `/cog/*` | Cloud Optimized GeoTIFF tiles via GDAL |
| Xarray/Zarr | `/xarray/*` | Zarr/NetCDF multidimensional tiles via xarray |
| Vector/TiPG | `/vector/*` | OGC Features API + Vector Tiles (MVT) |
| STAC | `/stac/*` | STAC catalog browsing and search |

H3 DuckDB and Downloads are out of scope for this retooling.

---

## SIEGE Pipeline Design

### Purpose

Fast sequential verification that all tile services function correctly after deployment. Linear sweep for speed — no information asymmetry.

### Endpoint Access Rules

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Consumer** | `/cog/*`, `/xarray/*`, `/vector/*`, `/stac/*` | Cartographer, Lancer | The surface a map app developer hits |
| **Verification** | `/health`, `/livez`, `/readyz`, `/vector/diagnostics` | Cartographer (health), Auditor | Health and metadata cross-checks |
| **Synthesis** | None | Scribe | Final report from other agents' data |

No prerequisites needed — stateless read-only server.

### Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| Sentinel | Define campaign from config + health check | Claude (no subagent) | siege_config_titiler.json |
| Cartographer | Probe every endpoint, map API surface | Task (sequential) | Campaign Brief |
| Lancer | Execute read chains per service family | Task (sequential) | Campaign Brief + test data |
| Auditor | Cross-validate metadata consistency | Task (sequential) | Lancer's output |
| Scribe | Synthesize final report | Task (sequential) | All outputs |

### Flow

```
Target: BASE_URL (Azure endpoint)
    |
    Sentinel (Claude — no subagent)
        Reads siege_config_titiler.json
        Verifies health endpoint reports all services healthy
        Outputs: Campaign Brief
    |
    Cartographer (Task)                          [sequential]
        Probes every known endpoint
        OUTPUT: Endpoint Map (URL → HTTP code → response schema → latency)
    |
    Lancer (Task)                                [sequential]
        Executes read chains per service family
        OUTPUT: Execution Log + State Checkpoint Map
    |
    Auditor (Task)                               [sequential]
        Cross-validates metadata consistency
        OUTPUT: Audit Report (matches, divergences)
    |
    Scribe (Task)                                [sequential]
        Synthesizes all outputs
        OUTPUT: Final SIEGE Report
```

### Cartographer Probe Table

**Tile services (consumer surface)**:

| Endpoint | Method | Probe | Expected |
|----------|--------|-------|----------|
| `/cog/info` | GET | `?url={cog_url}` | 200 + bounds/dtype/bands |
| `/cog/WebMercatorQuad/tilejson.json` | GET | `?url={cog_url}` | 200 + TileJSON |
| `/cog/statistics` | GET | `?url={cog_url}` | 200 + band stats |
| `/cog/bounds` | GET | `?url={cog_url}` | 200 + bounds |
| `/cog/preview.png` | GET | `?url={cog_url}&max_size=256` | 200 + image |
| `/xarray/variables` | GET | `?url={zarr_url}` | 200 + variable list |
| `/xarray/info` | GET | `?url={zarr_url}&variable=tasmax` | 200 + bounds/dims |
| `/xarray/WebMercatorQuad/tilejson.json` | GET | `?url={zarr_url}&variable=tasmax&bidx=1&rescale=250,320` | 200 + TileJSON |
| `/xarray/bounds` | GET | `?url={zarr_url}&variable=tasmax` | 200 + bounds |
| `/vector/collections` | GET | No params | 200 + collection list |
| `/vector/collections/{id}` | GET | Known collection ID | 200 + metadata |
| `/vector/collections/{id}/items` | GET | `?limit=1` | 200 + features |
| `/vector/collections/{id}/tiles/WebMercatorQuad/tilejson.json` | GET | No extra params | 200 + TileJSON |
| `/stac/collections` | GET | No params | 200 + collection list |
| `/stac/collections/{id}` | GET | Known collection ID | 200 + extent |
| `/stac/collections/{id}/items` | GET | `?limit=3` | 200 + items |
| `/stac/search` | GET | `?limit=3` | 200 + items |

**Verification endpoints**:

| Endpoint | Method | Probe | Expected |
|----------|--------|-------|----------|
| `/health` | GET | No params | 200 + all services healthy |
| `/livez` | GET | No params | 200 |
| `/readyz` | GET | No params | 200 |

### Lancer Sequences

**Sequence 1: COG Read Chain**

1. `GET /cog/info?url={cog_url}` → capture bounds, dtype, band count
2. `GET /cog/WebMercatorQuad/tilejson.json?url={cog_url}` → capture tile URL template, minzoom, maxzoom
3. `GET /cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url={cog_url}` → verify 200 + `image/*` content-type
4. `GET /cog/statistics?url={cog_url}` → verify band stats
5. **CHECKPOINT C1**: bounds from info match tilejson, tile renders, stats valid

**Sequence 2: Zarr Read Chain**

1. `GET /xarray/variables?url={zarr_url}` → capture variable list
2. `GET /xarray/info?url={zarr_url}&variable=tasmax` → capture bounds, dims, time steps
3. `GET /xarray/WebMercatorQuad/tilejson.json?url={zarr_url}&variable=tasmax&bidx=1&rescale=250,320` → capture tile template
4. `GET /xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url={zarr_url}&variable=tasmax&bidx=1&colormap_name=viridis&rescale=250,320` → verify tile renders
5. **CHECKPOINT Z1**: variables match, bounds consistent, tile is valid image

**Sequence 3: Vector Read Chain**

1. `GET /vector/collections` → capture collection list
2. `GET /vector/collections/{id}` → capture collection metadata
3. `GET /vector/collections/{id}/items?limit=5` → verify features returned
4. `GET /vector/collections/{id}/tiles/WebMercatorQuad/tilejson.json` → capture tile template
5. `GET /vector/collections/{id}/tiles/WebMercatorQuad/{z}/{x}/{y}` → verify MVT tile
6. **CHECKPOINT V1**: features exist, tile renders, metadata consistent

**Sequence 4: STAC Discovery Chain**

1. `GET /stac/collections` → capture collection list
2. `GET /stac/collections/{id}` → capture spatial/temporal extent
3. `GET /stac/collections/{id}/items?limit=3` → capture item IDs, asset URLs
4. `GET /stac/search` with bbox from collection extent → verify search returns items
5. Extract COG URL from STAC asset → feed into `/cog/info` → verify service URL works
6. **CHECKPOINT S1**: catalog navigable, items have working service URLs

**Sequence 5: Cross-Service Consistency**

1. Take COG URL from STAC item asset
2. Get bounds from `/cog/info`
3. Get bounds from `/stac/collections/{id}` extent
4. Compare — should overlap
5. **CHECKPOINT X1**: STAC spatial extent consistent with actual data bounds

### Lancer Checkpoint Format

```markdown
## Checkpoint {ID}: {description}
AFTER: {step description}
EXPECTED STATE:
  Service: {cog|xarray|vector|stac}
  Bounds: [{minx}, {miny}, {maxx}, {maxy}]
  Tile rendered: {yes|no}
  Content-Type: {value}
  Response time: {ms}
  Metadata consistent: {yes|no}
  Captured values:
    - bounds={value}
    - tilejson_minzoom={value}
    - tilejson_maxzoom={value}
    - tile_content_type={value}
    - tile_size_bytes={value}
```

### Lancer HTTP Log Format

```
### Step {N}: {description}
REQUEST: {method} {url}
RESPONSE: HTTP {code}
CONTENT-TYPE: {value}
SIZE: {bytes}
LATENCY: {ms}
CAPTURED: {key}={value}
EXPECTED: {what should happen}
ACTUAL: {what did happen}
VERDICT: PASS | FAIL | UNEXPECTED
```

### Auditor Checks

| Check | Method | What to Compare |
|-------|--------|-----------------|
| Bounds consistency | `/info` vs `/tilejson.json` | bounds arrays should match |
| Tile validity | Content-Type header | Must be `image/png`, `image/jpeg`, or `application/vnd.mapbox-vector-tile` |
| Response time | Latency from Lancer log | Flag anything >5s |
| STAC→Tile chain | Asset URL from STAC → `/cog/info` | Must resolve, not 404 |
| Variable consistency | `/xarray/variables` → `/xarray/info` | Listed variable must work in info |
| Collection count | `/vector/collections` count | Must match /health reported count |
| TileJSON schema | All tilejson responses | Same schema across COG/Xarray/Vector |

### Auditor Output Format

```markdown
## State Audit

### Checkpoint {ID}: {description}
| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| COG bounds match | [-77.03, 38.91, -77.01, 38.93] | {actual} | PASS/FAIL |
| Tile content-type | image/png | {actual} | PASS/FAIL |
| TileJSON minzoom | 0 | {actual} | PASS/FAIL |

### Cross-Service Divergences
| Service A | Service B | Field | A Value | B Value | Severity |
...

### Response Time Flags
| Endpoint | Latency | Threshold | Verdict |
...
```

### Scribe Output Format

```markdown
# SIEGE Report — Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {version from /health}
**Pipeline**: SIEGE (Tile Server Smoke Test)

## Endpoint Health
| Endpoint | Status | Latency |
...
Assessment: {HEALTHY | DEGRADED | DOWN}

## Service Results
| Service | Steps | Pass | Fail | Unexpected |
|---------|-------|------|------|------------|
| COG Read Chain | {n} | {n} | {n} | {n} |
| Zarr Read Chain | {n} | {n} | {n} | {n} |
| Vector Read Chain | {n} | {n} | {n} | {n} |
| STAC Discovery | {n} | {n} | {n} | {n} |
| Cross-Service | {n} | {n} | {n} | {n} |

## Metadata Divergences
{from Auditor — expected vs actual for each failing check}

## Findings
| # | Severity | Service | Description | Reproduction |
...

## Verdict
{PASS | FAIL | NEEDS INVESTIGATION}
```

### Information Flow Summary

| Agent | Gets | Doesn't Get |
|-------|------|-------------|
| Sentinel | siege_config_titiler.json | Nothing (defines everything) |
| Cartographer | Campaign Brief, endpoint list | Test data, read chain sequences |
| Lancer | Campaign Brief, test data URLs, sequences | Cartographer's findings |
| Auditor | Lancer's Checkpoint Map, captured values | Lancer's raw HTTP responses |
| Scribe | All outputs from all agents | Nothing hidden |

---

## ADVOCATE Pipeline Design

### Purpose

Evaluate the tile server API from the perspective of a frontend developer trying to build a map application. Two agents — a confused newcomer and a seasoned API architect — independently critique discoverability, error messages, consistency, and the path from "I have data" to "I see tiles on a map."

### Endpoint Access Rules

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Consumer** | `/cog/*`, `/xarray/*`, `/vector/*`, `/stac/*`, landing pages, viewers | Intern, Architect | Full surface a frontend dev touches |
| **Synthesis** | None | Editor | Merges findings, no HTTP calls |

**Hard rule**: Intern and Architect MUST NOT use `/health`, `/admin/*`, `/vector/diagnostics`, or any endpoint not on the consumer surface. If they need information that's not discoverable through the consumer surface, that is a finding.

### Agent Roles

| Agent | Phase | Role | Persona | Runs As |
|-------|-------|------|---------|---------|
| Dispatcher | 0 | Define test data, write briefs | Campaign planner | Claude (no subagent) |
| Intern | 1 | First-impressions friction log | Frontend dev, first week, no docs | Task (sequential) |
| Architect | 2 | Structured DX audit | Senior API architect, 10 years REST | Task (sequential) |
| Editor | 3 | Merge, deduplicate, prioritize | Technical writer | Claude (synthesis) |

### Flow

```
Target: BASE_URL (Azure endpoint)
    |
    Dispatcher (Claude — no subagent)
        Reads siege_config_titiler.json for test data
        Writes Intern Brief + Architect Brief skeleton
        Outputs: Campaign Brief
    |
    ======== PHASE 1: FIRST IMPRESSIONS ========
    |
    Intern (Task)                                    [sequential]
        Frontend dev. No docs, no hints.
        Attempts: discover API → get info → get tiles → render for each data type
        Records every friction point, confusion, WTF moment.
        OUTPUT: Friction Log
    |
    ======== PHASE 2: STRUCTURED AUDIT ========
    |
    Architect (Task)                                 [sequential]
        Senior API reviewer. Gets Intern's Friction Log.
        Replays same endpoints systematically.
        Evaluates against REST best practices.
        OUTPUT: DX Audit Report
    |
    ======== PHASE 3: SYNTHESIS ========
    |
    Editor (Claude — synthesis)
        Merges both reports, deduplicates, prioritizes.
        Assigns severity, groups by theme.
        OUTPUT: Final ADVOCATE Report
```

### Intern Persona

```
You are a frontend developer in your first week at a company building mapping
applications. Your team has geospatial data (satellite imagery as COGs, climate
data as Zarr, vector features in PostGIS) and you've been told "use the tile
server to display them."

You have:
- The BASE_URL
- A COG path: /vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif
- A Zarr path: abfs://silver-zarr/cmip6-tasmax-sample.zarr
- A vague understanding that there are tiles, collections, and a STAC catalog

You do NOT have:
- API documentation
- Source code access
- Admin endpoints
- Knowledge of TileMatrixSets, OGC standards, or titiler internals
- A colleague to ask

Your job: get tiles displaying on a map for each data type. Record every
moment of confusion, frustration, or surprise.
```

### Intern Instructions

**Task**: Get tiles rendering for COG, Zarr, and Vector data using ONLY the consumer API surface. No docs. Figure it out.

**Exploration strategy**:
1. Start with the base URL — what's at the root? Any landing pages?
2. Try `/cog/` — what do you see? Can you figure out how to get tiles?
3. Try getting info for the COG. What URL format does it expect?
4. Once you have info, how do you get a tile URL? What's a TileMatrixSet?
5. Now try Zarr. You have an `abfs://` URL — does `/xarray/` accept it?
6. What extra parameters does Zarr need? How do you know the variable name?
7. Try vector. How do you find collections? How do you get vector tiles?
8. Try STAC. Can you search the catalog? Can you go from STAC item → tiles?

**For each step, record**:

```
### Step {N}: {what I was trying to do}
TRIED: {method} {url}
SENT: {body, if any}
GOT: HTTP {code}
RESPONSE: {truncated to 500 chars}

CONFUSED BY: {what doesn't make sense}
EXPECTED: {what I thought would happen}
FRICTION: {what made this harder than it should be}
SUGGESTION: {what would have helped}
```

### Intern Friction Categories

| Category | Code | What It Means |
|----------|------|---------------|
| **Discoverability** | DISC | "How was I supposed to know this endpoint/param exists?" |
| **Error Messages** | ERR | "This error message didn't help me fix the problem." |
| **Consistency** | CON | "This works differently from that other endpoint." |
| **Response Shape** | SHAPE | "This response has too much/too little/confusing data." |
| **Naming** | NAME | "This field/endpoint/param name is misleading." |
| **Workflow** | FLOW | "The steps to get tiles don't make sense." |
| **Missing Capability** | MISS | "I need to do X but there's no way to do it." |
| **Documentation** | DOC | "Even with docs, this would be confusing." |
| **Latency** | LAT | "This took surprisingly long." |
| **Silent Failure** | SILENT | "This appeared to succeed but actually didn't work." |

### Intern Output Format

```markdown
# Intern Friction Log — ADVOCATE Run {N}

## Overall Experience
{2-3 paragraphs: narrative. How did it feel? Where did you get stuck?}

## Lifecycle Walkthrough

### COG Tiles
{Step-by-step account with friction annotations}

### Zarr/NetCDF Tiles
{Step-by-step account}

### Vector Tiles
{Step-by-step account}

### STAC Discovery → Tiles
{Step-by-step account}

## Friction Summary

| # | Category | Severity | Endpoint | Description |
|---|----------|----------|----------|-------------|
...

## Top 5 "WTF Moments"
{The 5 most confusing things, ranked by how long they blocked progress}

## What Worked Well
{Things that were intuitive or pleasant}
```

### Architect Persona

```
You are a senior API architect with 10 years of experience designing and reviewing
REST APIs. You've worked with mapping APIs (Mapbox, Google Maps, ArcGIS REST Services)
and data APIs (Stripe, AWS). You know what good tile server DX looks like.

You have:
- The BASE_URL
- The test data URLs
- The Intern's Friction Log
- Your own expertise in REST and OGC standards

You do NOT have:
- Source code access
- Admin endpoints
- Internal architecture knowledge

Your job is to systematically audit the API against industry best practices. The
Intern's Friction Log tells you where the pain points are — use it as your
investigation queue, then go beyond it with your own systematic review.
```

### Architect Instructions

**Phase A: Replay Intern's Pain Points**

For each friction item in the Intern's log:
1. Reproduce the issue
2. Determine if it's a real problem or user error
3. If real, classify root cause and assess severity
4. Propose the fix pattern

**Phase B: Systematic REST Audit**

| Dimension | rmhtitiler-specific focus |
|-----------|--------------------------|
| **Naming** | Are `/cog/`, `/xarray/`, `/vector/` intuitive? Is `WebMercatorQuad` discoverable? |
| **HTTP Methods** | All GET — correct. Any POST where GET would work? |
| **Status Codes** | Bad URL → 400 or 500? Missing variable → what code? |
| **Error Format** | Consistent across titiler-core, titiler-xarray, TiPG, stac-fastapi? |
| **Pagination** | `/vector/collections` paginated? `/stac/search` paginated? |
| **Idempotency** | All reads — inherently idempotent. Any edge cases? |
| **HATEOAS / Links** | `/info` → `/tilejson.json`? STAC items → tile endpoints? |
| **Versioning** | Any API version signals? |
| **Response Bloat** | `/cog/info` right-sized? `/vector/collections` too verbose? |
| **Consistency** | Same query params across COG/Xarray? Same error shapes? |
| **Content Negotiation** | `.png` vs `.jpg` vs `.webp` — is format selection clear? |
| **Rate Limiting** | Headers present? Clear limits? |
| **Cacheability** | Tile responses cacheable? ETag headers? |

**Phase C: Cross-Endpoint Consistency Matrix**

```
/cog/info vs /xarray/info — same response shape?
/cog/WebMercatorQuad/tilejson.json vs /xarray/WebMercatorQuad/tilejson.json — same schema?
/cog/tiles error vs /xarray/tiles error — same error format?
/vector/collections (TiPG) vs /stac/collections (stac-fastapi) — naming/shape consistency?
Landing page /cog/ vs /xarray/ — same UX patterns?
```

**Phase D: Service URL Audit**

For each service family:
1. Can you go from "I have data" to "I see tiles" without guessing?
2. Is there a self-describing discovery path? (TileJSON → tile URL template)
3. Do the built-in viewers work? (`/cog/WebMercatorQuad/map.html`, `/xarray/WebMercatorQuad/map.html`)
4. Are error messages actionable when the URL format is wrong?

Evaluate:
- **COG**: `/cog/info`, `/cog/WebMercatorQuad/tilejson.json`, `/cog/tiles/...`, `/cog/preview.png`, `/cog/WebMercatorQuad/map.html`
- **Zarr**: `/xarray/variables`, `/xarray/info`, `/xarray/WebMercatorQuad/tilejson.json`, `/xarray/tiles/...`, `/xarray/WebMercatorQuad/map.html`
- **Vector**: `/vector/collections`, `/vector/collections/{id}/items`, `/vector/collections/{id}/tiles/...`
- **STAC**: `/stac/collections`, `/stac/search`, `/stac/collections/{id}/items`

### Architect Severity Scale

| Severity | Definition | Example |
|----------|------------|---------|
| **CRITICAL** | Blocks tile rendering entirely | "No way to discover the required `variable` param for Zarr" |
| **HIGH** | Causes significant developer time waste | "Error for wrong URL scheme says 'GroupNotFoundError' — meaningless" |
| **MEDIUM** | Inconsistency that requires workarounds | "COG uses `/vsiaz/` URLs, Zarr uses `abfs://` — no unified format" |
| **LOW** | Polish item, minor friction | "TileMatrixSet name `WebMercatorQuad` not obvious to non-OGC developers" |
| **INFO** | Observation, not a problem | "No CORS headers — fine if behind API gateway" |

### Architect Output Format

```markdown
# Architect DX Audit — ADVOCATE Run {N}

## Executive Summary
{3-5 sentences: overall tile server DX quality. How does this compare to
Mapbox GL tile APIs or ArcGIS REST Services?}

## Part A: Intern Pain Point Analysis

| # | Intern Finding | Confirmed? | Root Cause | Severity | Fix Pattern |
|---|----------------|------------|------------|----------|-------------|
...

## Part B: REST Best Practices Audit

### Naming & URL Structure
| Endpoint | Issue | Recommendation | Severity |
...

### Error Handling
| Endpoint | Error Scenario | Current Response | Ideal Response | Severity |
...

### Response Consistency
| Pair | Issue | Severity |
...

{Continue for each dimension}

## Part C: Cross-Endpoint Consistency Matrix

| Field | /cog/info | /xarray/info | /vector/collections/{id} | Consistent? |
|-------|-----------|--------------|--------------------------|-------------|
...

## Part D: Service URL Audit

### COG
| URL Type | URL | HTTP | Works? | Discoverable? | Notes |
...

### Zarr
...

### Vector
...

### STAC
...

## Findings by Theme

### Theme 1: {name}
{Description, affected endpoints, recommended fix}

## Prioritized Recommendations

| Priority | Finding | Effort | Impact | Recommendation |
...
```

### Editor Scoring Rubric

| Category | Weight | What It Measures |
|----------|--------|------------------|
| Discoverability | 20% | Can a dev figure out URL format, required params, TileMatrixSet? |
| Error Quality | 20% | When `https://` used instead of `abfs://`, does error explain why? |
| Consistency | 20% | Same patterns across COG/Xarray/Vector? Same error shapes? |
| Response Design | 15% | Info responses right-sized? TileJSON complete? |
| Service URL Integrity | 15% | Tiles render? Viewers work? TileJSON→tiles chain unbroken? |
| Workflow Clarity | 10% | Clear path from STAC discovery → tile rendering? |

### Editor Output Format

```markdown
# ADVOCATE Report — Run {N}

**Date**: {date}
**Version**: {version}
**Target**: {BASE_URL}
**Pipeline**: ADVOCATE (Tile Server DX Audit)
**Agents**: Intern (first impressions) → Architect (structured audit)

---

## Executive Summary
{3-5 sentences: overall DX quality, biggest themes}

---

## DX Score: {score}%

| Category | Weight | Score | Notes |
|----------|--------|-------|-------|
| Discoverability | 20% | {n}% | {brief} |
| Error Quality | 20% | {n}% | {brief} |
| Consistency | 20% | {n}% | {brief} |
| Response Design | 15% | {n}% | {brief} |
| Service URL Integrity | 15% | {n}% | {brief} |
| Workflow Clarity | 10% | {n}% | {brief} |

---

## Themes
### Theme 1: {name}
**Severity**: {CRITICAL/HIGH/MEDIUM/LOW}
**Affected endpoints**: {list}
**Intern's experience**: {what they hit}
**Architect's analysis**: {root cause}
**Recommendation**: {specific fix}
**Effort**: {S/M/L}

---

## All Findings
| # | ID | Severity | Category | Endpoint(s) | Description | Source |
...

---

## What Works Well
{Positive patterns to protect from regression}

---

## Prioritized Action Plan

### P0 — Fix Before Release
| # | Finding | Effort | Change |
...

### P1 — Next Sprint
| # | Finding | Effort | Change |
...

### P2 — Backlog
| # | Finding | Effort | Change |
...

---

## Pipeline Chain Recommendations
| Finding | Pipeline | Target Files | Notes |
...
```

### Save Output

Save to `docs/agent_review/agent_docs/ADVOCATE_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## siege_config_titiler.json Design

Standalone config file at `docs/agent_review/siege_config_titiler.json`.

```json
{
  "target": {
    "base_url": "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net",
    "storage_account": "rmhstorage123"
  },
  "test_data": {
    "cog": {
      "url": "/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif",
      "description": "3-band uint8 COG, DC area, WGS84",
      "expected_bounds": [-77.03, 38.91, -77.01, 38.93],
      "expected_bands": 3,
      "expected_dtype": "uint8"
    },
    "zarr": {
      "url": "abfs://silver-zarr/cmip6-tasmax-sample.zarr",
      "variable": "tasmax",
      "description": "CMIP6 daily max temperature, 12 time steps, global, Kelvin",
      "expected_bounds": [-181.25, -91.25, 178.75, 91.25],
      "expected_variables": ["tasmax"],
      "expected_time_steps": 12,
      "rescale": "250,320",
      "colormap": "viridis",
      "bidx": 1
    },
    "vector": {
      "collection_id": "geo.sg7_vector_test_cutlines_ord1",
      "description": "MultiPolygon cutlines, 1401 features",
      "expected_feature_count_min": 1000
    },
    "stac": {
      "collection_id": "sg-raster-test-dctest",
      "item_id": "sg-raster-test-dctest-v1",
      "description": "Raster STAC item with COG data asset and thumbnail",
      "expected_assets": ["data", "thumbnail"]
    }
  },
  "namespaces": {
    "siege": "sg-",
    "advocate": "adv-"
  }
}
```

---

## Deliverables

1. `docs/agent_review/agents/SIEGE_AGENT.md` — rewritten for rmhtitiler
2. `docs/agent_review/agents/ADVOCATE_AGENT.md` — rewritten for rmhtitiler
3. `docs/agent_review/siege_config_titiler.json` — new standalone config
