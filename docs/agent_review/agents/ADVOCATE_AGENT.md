# Pipeline 7: ADVOCATE (Tile Server Developer Experience Audit)

**Purpose**: Evaluate the tile server API from the perspective of frontend developers trying to display tiles on a map. Two agents — a confused newcomer and a seasoned API architect — independently critique discoverability, error messages, consistency, and the path from "I have data" to "I see tiles on a map."

**Best for**: Pre-release polish. When correctness is proven (SIEGE/TOURNAMENT pass) but you need to know if the API is *pleasant* to integrate with.

---

## Endpoint Access Rules

Agents experience the API **exactly as a frontend map developer would**. No admin endpoints, no source code, no internal docs.

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Consumer** | `/cog/*`, `/xarray/*`, `/vector/*`, `/stac/*`, `/cog/`, `/xarray/`, `/viewer/*` | Intern, Architect | The full surface a frontend developer touches: tile endpoints, landing pages, viewers |
| **Synthesis** | None (reads agent outputs) | Editor | Merges findings, produces final report. No HTTP calls. |

**Hard rule**: Intern and Architect MUST NOT use `/health`, `/admin/*`, `/vector/diagnostics`, or any endpoint not on the consumer surface. If they need information that is not discoverable through the consumer surface, that is a finding — "poor discoverability" or "missing capability."

---

## Agent Roles

| Agent | Phase | Role | Persona | Runs As |
|-------|-------|------|---------|---------|
| Dispatcher | 0 | Define test data, write briefs | Campaign planner | Claude (no subagent) |
| Intern | 1 | First-impressions friction log | Frontend dev, first week, no docs | Task (sequential) |
| Architect | 2 | Structured DX audit against REST best practices | Senior API architect, 10 years REST experience | Task (sequential) |
| Editor | 3 | Merge, deduplicate, prioritize, produce report | Technical writer | Claude (synthesis) |

**Maximum parallel agents**: 0 (strictly sequential — Architect needs Intern's output)

---

## Flow

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

---

## Campaign Config

Shared config file: `docs/agent_review/siege_config_titiler.json`

- **`test_data`**: COG, Zarr, Vector, and STAC URLs used by Intern and Architect
- **`namespaces.advocate`**: `adv-` prefix for test data references

---

## Prerequisites

None needed — rmhtitiler is a stateless read-only tile server. No database seeding, no schema rebuilds, no data submission.

Optional health check by Dispatcher only to confirm the app is live:

```bash
BASE_URL="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

# Health check (Dispatcher only — agents don't get this endpoint)
curl -sf "${BASE_URL}/health" | jq
```

---

## Step 1: Play Dispatcher (No Subagent)

Claude plays Dispatcher directly. Dispatcher's job:

1. Read `siege_config_titiler.json` for test data.
2. Define test data using `adv-` prefix:
   - **COG**: `url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif`
   - **Zarr**: `url=abfs://silver-zarr/cmip6-tasmax-sample.zarr`
   - **Vector**: `collection=geo.sg7_vector_test_cutlines_ord1`
   - **STAC**: `collection=sg-raster-test-dctest`
3. Write Intern Brief + Architect Brief skeleton.

---

## Step 2: Dispatch Intern (Phase 1)

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
1. Start with the base URL — what is at the root? Any landing pages?
2. Try `/cog/` — what do you see? Can you figure out how to get tiles?
3. Try getting info for the COG. What URL format does it expect?
4. Once you have info, how do you get a tile URL? What is a TileMatrixSet?
5. Now try Zarr. You have an `abfs://` URL — does `/xarray/` accept it?
6. What extra parameters does Zarr need? How do you know the variable name?
7. Try vector. How do you find collections? How do you get vector tiles?
8. Try STAC. Can you search the catalog? Can you go from STAC item to tiles?

**Lifecycle to attempt**:
```
Discover API → Get info → Get tile URL → Render tile → Find data via STAC → Repeat per data type
```

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

Record every finding under one of these categories:

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
{2-3 paragraphs: narrative of the experience. How did it feel? Where did you get
stuck? What was intuitive? What was baffling?}

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
| F-1 | DISC | HIGH | /cog/ | No hint about required TileMatrixSet name |
| F-2 | ERR | MEDIUM | /xarray/info | Error for missing variable param is cryptic |
...

## Top 5 "WTF Moments"
{The 5 most confusing things, ranked by how long they blocked progress}

## What Worked Well
{Things that were intuitive or pleasant — important for balance}
```

---

## Step 3: Dispatch Architect (Phase 2)

### Architect Persona

```
You are a senior API architect with 10 years of experience designing and reviewing
REST APIs. You've worked with mapping APIs (Mapbox, Google Maps, ArcGIS REST Services)
and data APIs (Stripe, AWS). You know what good tile server DX looks like.

You have:
- The BASE_URL
- The test data URLs
- The Intern's Friction Log (their first-impressions experience)
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

**Task**: Systematic DX audit of the full consumer surface. Use the Intern's Friction Log as your starting point, then evaluate holistically.

**Phase A: Replay Intern's Pain Points**

For each friction item in the Intern's log:
1. Reproduce the issue
2. Determine if it's a real problem or user error
3. If real, classify the root cause and assess severity
4. Propose the fix pattern (what should the response/behavior look like?)

**Phase B: Systematic REST Audit**

Evaluate every endpoint against these dimensions:

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

Compare response shapes across related endpoints:

```
/cog/info vs /xarray/info — same response shape?
/cog/WebMercatorQuad/tilejson.json vs /xarray/WebMercatorQuad/tilejson.json — same schema?
/cog/tiles error vs /xarray/tiles error — same error format?
/vector/collections (TiPG) vs /stac/collections (stac-fastapi) — naming/shape consistency?
Landing page /cog/ vs /xarray/ — same UX patterns?
```

For each pair: are the field names the same? Are the shapes consistent? Would a client need special handling for each?

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
| F-1 | {description} | YES/NO/PARTIAL | {why} | {sev} | {what good looks like} |
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
{Description of the pattern, affected endpoints, recommended fix}

### Theme 2: {name}
...

## Prioritized Recommendations

| Priority | Finding | Effort | Impact | Recommendation |
|----------|---------|--------|--------|----------------|
| P0 | {description} | {S/M/L} | {high/med/low} | {specific change} |
| P1 | {description} | ... | ... | ... |
...
```

---

## Step 4: Play Editor (Phase 3)

Claude plays Editor directly. Editor receives both outputs and produces the final report.

### Editor Procedure

1. **Deduplicate**: Merge findings where Intern and Architect identified the same issue.
2. **Validate**: If Architect downgraded an Intern finding, note the reasoning.
3. **Theme**: Group related findings into themes (e.g., "Error handling inconsistency" covering multiple endpoints).
4. **Prioritize**: Rank by (severity x breadth). A MEDIUM that affects all endpoints outranks a HIGH that affects one.
5. **Score**: Calculate an overall DX score.

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

### Theme 2: {name}
...

---

## All Findings

| # | ID | Severity | Category | Endpoint(s) | Description | Source |
|---|-----|----------|----------|-------------|-------------|--------|
| 1 | ADV-1 | HIGH | ERR | /xarray/info | {description} | Both |
| 2 | ADV-2 | MEDIUM | CON | /cog/, /xarray/ | {description} | Architect |
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
|---------|----------|-------------|-------|
...
```

### Save Output

Save to `docs/agent_review/agent_docs/ADVOCATE_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Asymmetry Summary

| Agent | Gets | Doesn't Get | Why |
|-------|------|-------------|-----|
| Dispatcher | Full context, config, prior findings | Nothing | Sets up the campaign |
| Intern | BASE_URL, test data URLs | Docs, source code, admin endpoints, Architect's expertise | Simulates genuine newcomer confusion |
| Architect | BASE_URL, test data, Intern's Friction Log | Source code, admin endpoints | Intern's pain points become investigation queue |
| Editor | Both outputs | Source code | Full picture for dedup/prioritize |

### Key Design Insight: Sequential Handoff

The Intern's Friction Log is the Architect's investigation queue. The Intern says *"this error message is useless"* — the Architect evaluates *why* and proposes the fix pattern. They complement rather than duplicate.

Without the Intern pass, the Architect would evaluate the API like an expert — missing the beginner friction. Without the Architect pass, the Intern's complaints would lack structural analysis and fix recommendations.

---

## Token Estimate

| Agent | Estimated Tokens | Notes |
|-------|-----------------|-------|
| Dispatcher | ~2K | Setup only |
| Intern | ~40-60K | Full lifecycle walkthrough, lots of HTTP calls |
| Architect | ~40-60K | Systematic audit + Intern replay |
| Editor | ~5-10K | Synthesis |
| **Total** | **~80-130K** | |

---

## When to Run ADVOCATE

| Scenario | Run ADVOCATE? |
|----------|---------------|
| After SIEGE/TOURNAMENT confirms correctness | **YES** — this is the sweet spot |
| Before UAT handoff | **YES** — catch DX issues before external testers see them |
| After major API refactor | **YES** — verify consistency was not broken |
| After adding new endpoints | **YES** — check new endpoints match existing patterns |
| During active development | **NO** — use SIEGE for functional correctness first |
| After crashes are found | **NO** — fix crashes first, then evaluate DX |
