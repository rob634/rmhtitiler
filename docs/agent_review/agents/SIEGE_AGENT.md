# Pipeline 4: SIEGE (Sequential Smoke Test)

**Purpose**: Fast sequential verification that all tile services function correctly after deployment. Linear sweep for speed — no information asymmetry.

**Best for**: Post-deployment smoke test, quick confidence check ("did that deploy break anything?"). Validates COG, Zarr, Vector, and STAC services end-to-end in a single pass.

---

## Endpoint Access Rules

Agents test through the **same API surface** that map application developers use. This ensures tests reflect real-world access patterns. No Setup tier — rmhtitiler is a stateless read-only tile server.

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Consumer** | `/cog/*`, `/xarray/*`, `/vector/*`, `/stac/*` | Cartographer (probes), Lancer | Tile rendering, metadata queries, catalog browsing. The surface a map app developer hits. |
| **Verification** | `/health`, `/livez`, `/readyz`, `/vector/diagnostics` | Cartographer (health only), Auditor | Health and metadata cross-checks. Read-only state verification. |
| **Synthesis** | None (reads other agents' outputs) | Scribe | Produces final report from other agents' data. No HTTP calls. |

**Hard rule**: Lancer MUST only use consumer endpoints (`/cog/*`, `/xarray/*`, `/vector/*`, `/stac/*`). Auditor may use verification endpoints for cross-validation. If a workflow needs a verification endpoint to function, flag it as a finding.

---

## Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| Sentinel | Define campaign from config + health check | Claude (no subagent) | siege_config_titiler.json |
| Cartographer | Probe every endpoint, map API surface | Task (sequential) | Campaign Brief |
| Lancer | Execute read chains per service family | Task (sequential) | Campaign Brief + test data |
| Auditor | Cross-validate metadata consistency | Task (sequential) | Lancer's State Checkpoint Map |
| Scribe | Synthesize all outputs into final report | Task (sequential) | All previous outputs |

**Maximum parallel agents**: 0 (all sequential)

---

## Flow

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

---

## Prerequisites

Health check only. No rebuild, no nuke — rmhtitiler is a stateless read-only tile server.

```bash
BASE_URL="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

# Health check — verify all services are up
curl -sf "${BASE_URL}/health"
```

---

## Campaign Config

All SIEGE runs reference a standalone config file: `docs/agent_review/siege_config_titiler.json`

The config contains:
- **`target`**: BASE_URL and storage account
- **`test_data`**: Known-good test URLs for each service family (COG, Zarr, Vector, STAC) with expected values
- **`endpoint_access_rules`**: Consumer and verification endpoint definitions with method, path, and parameter templates
- **`cartographer_probes`**: Structured probe definitions for each service family — method, path, params, expected HTTP status
- **`namespaces`**: Prefix conventions (`sg-` for SIEGE, `adv-` for ADVOCATE)

Sentinel MUST read this config before launching any agents. All test data URLs, collection IDs, and expected values come from this file.

---

## Step 1: Play Sentinel (No Subagent)

Claude plays Sentinel directly. Sentinel's job:

1. Read `siege_config_titiler.json` for test data and endpoint definitions.
2. Verify health endpoint returns all services healthy:
   ```bash
   curl -sf "${BASE_URL}/health" | jq
   ```
3. Define test data from config:
   - COG: `url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif` (3-band uint8, DC area)
   - Zarr: `url=abfs://silver-zarr/cmip6-tasmax-sample.zarr`, `variable=tasmax` (CMIP6, 12 time steps, Kelvin)
   - Vector: `collection_id=geo.sg7_vector_test_cutlines_ord1` (MultiPolygon, 1401+ features)
   - STAC: `collection_id=sg-raster-test-dctest`, `item_id=sg-raster-test-dctest-v1` (data + thumbnail assets)
4. Output the Campaign Brief:
   - BASE_URL
   - Test data table (service, URL/ID, description, expected values)
   - Full endpoint list for Cartographer
   - Read chain sequences for Lancer

---

## Step 2: Dispatch Cartographer

Cartographer probes every known endpoint with a minimal request to verify liveness.

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

**Total probes**: 20 (COG: 5, Xarray: 4, Vector: 4, STAC: 4, Health: 3)

### Cartographer Output Format

```markdown
## Endpoint Map

| # | Endpoint | Method | HTTP Code | Latency (ms) | Response Shape | Notes |
|---|----------|--------|-----------|-------------|----------------|-------|
...

## Health Assessment
{HEALTHY | DEGRADED | DOWN}
{Any endpoints that returned unexpected codes}
```

---

## Step 3: Dispatch Lancer

Lancer executes read chains per service family and records state checkpoints. Each sequence exercises a complete consumer workflow from metadata through tile rendering.

### Read Chain Sequences

**Sequence 1: COG Read Chain**

1. `GET /cog/info?url={cog_url}` -- capture bounds, dtype, band count
2. `GET /cog/WebMercatorQuad/tilejson.json?url={cog_url}` -- capture tile URL template, minzoom, maxzoom
3. `GET /cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url={cog_url}` -- verify 200 + `image/*` content-type
4. `GET /cog/statistics?url={cog_url}` -- verify band stats
5. **CHECKPOINT C1**: bounds from info match tilejson, tile renders, stats valid

**Sequence 2: Zarr Read Chain**

1. `GET /xarray/variables?url={zarr_url}` -- capture variable list
2. `GET /xarray/info?url={zarr_url}&variable=tasmax` -- capture bounds, dims, time steps
3. `GET /xarray/WebMercatorQuad/tilejson.json?url={zarr_url}&variable=tasmax&bidx=1&rescale=250,320` -- capture tile template
4. `GET /xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url={zarr_url}&variable=tasmax&bidx=1&colormap_name=viridis&rescale=250,320` -- verify tile renders
5. **CHECKPOINT Z1**: variables match, bounds consistent, tile is valid image

**Sequence 3: Vector Read Chain**

1. `GET /vector/collections` -- capture collection list
2. `GET /vector/collections/{id}` -- capture collection metadata
3. `GET /vector/collections/{id}/items?limit=5` -- verify features returned
4. `GET /vector/collections/{id}/tiles/WebMercatorQuad/tilejson.json` -- capture tile template
5. `GET /vector/collections/{id}/tiles/WebMercatorQuad/{z}/{x}/{y}` -- verify MVT tile
6. **CHECKPOINT V1**: features exist, tile renders, metadata consistent

**Sequence 4: STAC Discovery Chain**

1. `GET /stac/collections` -- capture collection list
2. `GET /stac/collections/{id}` -- capture spatial/temporal extent
3. `GET /stac/collections/{id}/items?limit=3` -- capture item IDs, asset URLs
4. `GET /stac/search` with bbox from collection extent -- verify search returns items
5. Extract COG URL from STAC asset -- feed into `/cog/info` -- verify service URL works
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

---

## Step 4: Dispatch Auditor

Auditor receives Lancer's State Checkpoint Map and cross-validates metadata consistency across services.

### Audit Checks

| Check | Method | What to Compare |
|-------|--------|-----------------|
| Bounds consistency | `/info` vs `/tilejson.json` | bounds arrays should match |
| Tile validity | Content-Type header | Must be `image/png`, `image/jpeg`, or `application/vnd.mapbox-vector-tile` |
| Response time | Latency from Lancer log | Flag anything >5s |
| STAC-to-Tile chain | Asset URL from STAC item fed to `/cog/info` | Must resolve, not 404 |
| Variable consistency | `/xarray/variables` list vs `/xarray/info` | Listed variable must work in info |
| Collection count | `/vector/collections` count | Must match `/health` reported count |
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

---

## Step 5: Dispatch Scribe

Scribe receives all outputs and produces the final report.

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

### Save Output

Save to `docs/agent_review/agent_docs/SIEGE_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Flow Summary

| Agent | Gets | Doesn't Get |
|-------|------|-------------|
| Sentinel | siege_config_titiler.json | Nothing (defines everything) |
| Cartographer | Campaign Brief, endpoint list | Test data, read chain sequences |
| Lancer | Campaign Brief, test data URLs, sequences | Cartographer's findings |
| Auditor | Lancer's Checkpoint Map, captured values | Lancer's raw HTTP responses |
| Scribe | All outputs from all agents | Nothing hidden |

**Note**: SIEGE has minimal information asymmetry by design. Its value is speed and completeness, not adversarial competition. For adversarial testing, use TOURNAMENT.
