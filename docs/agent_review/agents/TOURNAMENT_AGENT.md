# Pipeline 6: TOURNAMENT (Full-Spectrum Adversarial)

**Purpose**: Maximum-coverage adversarial testing of a read-only tile server across response consistency, connection pool stability, token cache integrity, catalog state, and input validation. 4 specialist agents in 2 phases, synthesized by a Tribunal. The most thorough live API testing pipeline.

**Best for**: Full adversarial regression before deployment. When you need confidence that concurrent load, malformed inputs, and catalog refreshes do not degrade tile serving or leak errors.

**Key difference from ETL TOURNAMENT**: This tile server has no create/approve/reject mutations. The "state" under test is: 3 independent connection pools, OAuth token cache, TiPG in-memory catalog, and response consistency across COG, Zarr, Vector, and STAC endpoints.

---

## Endpoint Access Rules

This is a **stateless tile server** -- all agents test through the same consumer endpoints. There is no privileged B2B surface.

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Consumer** | `/cog/*`, `/xarray/*`, `/vector/*`, `/stac/*`, `/searches/*` | Pathfinder, Saboteur, Provocateur | Tile serving, metadata, search. The consumer surface. |
| **Verification** | `/health`, `/livez`, `/readyz`, `/vector/diagnostics` | Inspector | Read-only state auditing in Phase 2. Pool stats, token expiry, catalog counts. |
| **Admin** | `/admin/refresh-collections` (POST) | Saboteur (catalog attacks), Inspector (verification) | Catalog refresh -- the only mutating endpoint on this server. |
| **Synthesis** | None (reads other agents' outputs) | Tribunal | Correlates findings, scores, and produces final report. No HTTP calls. |

**Hard rule**: Pathfinder and Provocateur MUST only use consumer endpoints. Saboteur may use `/admin/refresh-collections` for catalog attack sequences. Inspector uses verification endpoints plus `/admin/refresh-collections` for catalog state checks. Tribunal does not make HTTP calls.

---

## Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| General | Define campaign, write 4 specialist briefs | Claude (no subagent) | siege_config_titiler.json, API docs, prior findings |
| Pathfinder | Execute golden-path read chains, record response checkpoints | Task (Phase 1, parallel with Saboteur) | Pathfinder Brief |
| Saboteur | Execute adversarial attacks against same endpoints and data | Task (Phase 1, parallel with Pathfinder) | Saboteur Brief |
| Inspector | Audit server state against Pathfinder's checkpoints | Task (Phase 2, parallel with Provocateur) | Pathfinder's checkpoint map (NOT Saboteur's log) |
| Provocateur | Test input validation with boundary-value inputs | Task (Phase 2, parallel with Inspector) | Endpoint list only |
| Tribunal | Synthesize all findings, correlate, score, produce report | Task (Phase 3, sequential) | All 4 specialist outputs |

**Maximum parallel agents**: 2 (within each phase)

---

## Flow

```
Target: BASE_URL (Azure endpoint)
    |
    General (Claude -- no subagent)
        Reads siege_config_titiler.json, API docs, prior findings
        Outputs: 4 Specialist Briefs
    |
    ======== PHASE 1: EXERCISE ========
    |
    +--- Pathfinder (Task) ----+--- Saboteur (Task) --------+  [parallel]
    |    Golden-path executor   |    Adversarial attacker     |
    |    Runs 4 canonical       |    Runs 5 attack categories |
    |    read chains with       |    against SAME test data   |
    |    known test data        |    and endpoints             |
    |    OUTPUT:                |    OUTPUT:                  |
    |    Response Checkpoint    |    Attack Log per category  |
    |    Map                    |                             |
    +---------------------------+-----------------------------+
    |
    ======== PHASE 2: AUDIT ========
    |
    +--- Inspector (Task) -----+--- Provocateur (Task) -----+  [parallel]
    |    State auditor          |    Input validation tester  |
    |    Gets Pathfinder's      |    Gets endpoint list ONLY  |
    |    checkpoints            |    No campaign context      |
    |    Does NOT see Saboteur  |    Own tp- namespace        |
    |    OUTPUT:                |    OUTPUT:                  |
    |    State Audit Report     |    Error Behavior Map       |
    +---------------------------+-----------------------------+
    |
    ======== PHASE 3: JUDGMENT ========
    |
    Tribunal (Task)                                            [sequential]
        Receives ALL 4 outputs
        Correlates Inspector's divergences with Saboteur's attacks
        Scores all findings
        OUTPUT: Final TOURNAMENT Report
```

---

## Campaign Config

Shared config file: `docs/agent_review/siege_config_titiler.json`

- **`test_data.cog`**: COG file URL, bands, bounds, dtype
- **`test_data.zarr`**: Zarr store URL, variable, rescale, bidx
- **`test_data.vector`**: Vector collection ID, geometry type, feature count
- **`test_data.stac`**: STAC collection and item IDs, asset keys
- **`endpoint_access_rules`**: Consumer and verification endpoint inventory
- **`cartographer_probes`**: Smoke-test probe table with expected statuses

---

## Prerequisites

```bash
BASE_URL="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

# Health check -- verify all 5 services are healthy
curl -sf "${BASE_URL}/health" | jq '.status, .services | to_entries[] | {(.key): .value.status}'

# Verify test data is accessible
curl -sf "${BASE_URL}/cog/info?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif" | jq '.band_metadata'
curl -sf "${BASE_URL}/vector/collections/geo.sg7_vector_test_cutlines_ord1" | jq '.id'
curl -sf "${BASE_URL}/stac/collections/sg-raster-test-dctest" | jq '.id'

# Readiness probe
curl -sf "${BASE_URL}/readyz" | jq
```

No schema rebuild or nuke required -- this is a read-only tile server. Prerequisites only verify that the server is healthy and test data exists.

---

## Step 1: Play General (No Subagent)

Claude plays General directly. General's job:

1. Read `siege_config_titiler.json` for test data coordinates and endpoint inventory.
2. Read any prior SIEGE, ADVOCATE, or TOURNAMENT findings for context.
3. Define the test data references (from config):
   - COG: `url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif`
   - Zarr: `url=abfs://silver-zarr/cmip6-tasmax-sample.zarr`, `variable=tasmax`, `bidx=1`, `rescale=250,320`
   - Vector: `collection_id=geo.sg7_vector_test_cutlines_ord1`
   - STAC: `collection_id=sg-raster-test-dctest`, `item_id=sg-raster-test-dctest-v1`
4. Write 4 specialist briefs:

### Pathfinder Brief

Contains:
- BASE_URL, all test data references from config
- 4 canonical read chain sequences to execute
- Response checkpoint instructions (status codes, content-types, bounds, counts)
- Does NOT contain any information about attacks

### Saboteur Brief

Contains:
- BASE_URL, SAME test data references
- All 5 attack categories with minimum counts
- Reference to the Saboteur Attack Catalog (below)
- `tn-` namespace prefix for any registered mosaic searches
- Does NOT contain Pathfinder's checkpoint map or expected responses

### Inspector Brief

Prepared but NOT dispatched until Phase 1 completes. Will contain:
- Pathfinder's Response Checkpoint Map (output of Phase 1)
- `/health` query instructions for pool stats, token expiry, service status
- Does NOT contain Saboteur's attack log

### Provocateur Brief

Contains:
- BASE_URL
- Full endpoint list with methods and expected parameters
- Payload attack catalog (P1-P10)
- `tp-` namespace prefix for any registered searches
- Does NOT contain any campaign state, test data, or other agent context

---

## Step 2: Dispatch Pathfinder + Saboteur (Phase 1, Parallel)

Dispatch both simultaneously using the Agent tool. Wait for both to complete before Phase 2.

### Pathfinder Instructions

Execute these read chain sequences using the test data from config. Record response checkpoints after every step.

**Sequence 1: COG Chain**
1. `GET /cog/info?url={cog_url}` -- capture bands, dtype, bounds, width, height
2. `GET /cog/bounds?url={cog_url}` -- capture bounds, verify matches info
3. `GET /cog/WebMercatorQuad/tilejson.json?url={cog_url}` -- capture minzoom, maxzoom, tile URL template
4. `GET /cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url={cog_url}` -- use z/x/y within bounds, verify content-type is image/*, verify non-zero content-length
5. `GET /cog/statistics?url={cog_url}` -- capture band statistics (min, max, mean)
6. `GET /cog/preview.png?url={cog_url}&max_size=256` -- verify content-type image/png, non-zero content-length
7. **CHECKPOINT P-COG1**: All captured metadata, response codes, content-types

**Sequence 2: Zarr Chain**
1. `GET /xarray/variables?url={zarr_url}` -- capture variable list, verify "tasmax" present
2. `GET /xarray/info?url={zarr_url}&variable=tasmax` -- capture bounds, dtype, dimensions
3. `GET /xarray/bounds?url={zarr_url}&variable=tasmax` -- capture bounds, verify matches info
4. `GET /xarray/WebMercatorQuad/tilejson.json?url={zarr_url}&variable=tasmax&bidx=1&rescale=250,320` -- capture minzoom, maxzoom, tile URL
5. `GET /xarray/tiles/WebMercatorQuad/{z}/{x}/{y}?url={zarr_url}&variable=tasmax&bidx=1&rescale=250,320&colormap_name=viridis` -- verify image response
6. **CHECKPOINT P-ZARR1**: All captured metadata, response codes, content-types

**Sequence 3: Vector Chain**
1. `GET /vector/collections` -- capture collection count, verify test collection present
2. `GET /vector/collections/{collection_id}` -- capture geometry type, spatial extent, CRS
3. `GET /vector/collections/{collection_id}/items?limit=5` -- capture feature count, verify GeoJSON structure, verify numberMatched >= min_features
4. `GET /vector/collections/{collection_id}/tiles/WebMercatorQuad/tilejson.json` -- capture minzoom, maxzoom
5. `GET /vector/collections/{collection_id}/tiles/WebMercatorQuad/{z}/{x}/{y}` -- use z/x/y within extent, verify content-type contains `application/vnd.mapbox-vector-tile` or binary response
6. **CHECKPOINT P-VEC1**: Collection count, feature count, geometry type, tile response

**Sequence 4: STAC + Mosaic Chain**
1. `GET /stac/collections` -- capture collection count, verify test collection present
2. `GET /stac/collections/{collection_id}` -- capture extent, item count, license
3. `GET /stac/collections/{collection_id}/items?limit=3` -- capture item IDs, verify features array
4. `GET /stac/search?collections={collection_id}&limit=3` -- capture matched count, verify same items
5. `POST /stac/search` with body `{"collections":["{collection_id}"],"limit":3}` -- verify POST search matches GET search
6. `POST /searches/register` with body `{"collections":["{collection_id}"],"metadata":{"name":"tn-tournament-test"}}` -- capture search_id
7. `GET /searches/{search_id}/WebMercatorQuad/tilejson.json` -- capture minzoom, maxzoom, bounds
8. `GET /searches/{search_id}/tiles/WebMercatorQuad/{z}/{x}/{y}` -- verify mosaic tile renders
9. **CHECKPOINT P-STAC1**: Collection count, item IDs, search_id, mosaic tile response

**Polling**: No polling needed -- this is a read-only server. All requests are synchronous.

### Pathfinder Checkpoint Format

```
## Checkpoint {ID}: {description}
AFTER: {step}
EXPECTED RESPONSES:
  Metadata:
    - bounds={value}
    - bands={value}
    - collection_count={value}
    - feature_count={value}
  HTTP Responses:
    - {endpoint} -> HTTP {code}, content-type={type}, content-length>{min}
  Consistency:
    - bounds from /info matches bounds from /bounds: {yes|no}
    - collection present in /collections list: {yes|no}
    - GET /stac/search matches POST /stac/search: {yes|no}
  Captured Values:
    search_id={value} (if mosaic registered)
    tile_url_template={value}
    minzoom={value}, maxzoom={value}
```

### Pathfinder HTTP Log Format

```
### Step {N}: {description}
REQUEST: {method} {url}
RESPONSE: HTTP {code}
CONTENT-TYPE: {type}
CONTENT-LENGTH: {bytes}
BODY: {json truncated to 500 chars, or "(binary image)" for tiles}
CAPTURED: {key}={value}
EXPECTED: {description}
ACTUAL: {description}
VERDICT: PASS | FAIL | UNEXPECTED
```

---

### Saboteur Instructions

Execute attacks from ALL 5 categories against the SAME test data and endpoints Pathfinder uses. This creates realistic contention for connection pools and token cache.

Use `tn-` namespace prefix for any registered mosaic searches (e.g., `metadata.name` starts with `tn-`).

**Minimum attacks per category**:

| Category | Min | Priority Attacks |
|----------|-----|------------------|
| CONCURRENCY | 5 | C1, C2, C3, C4, C5 |
| RESOURCE | 5 | R1, R2, R3, R4, R5 |
| IDENTITY | 5 | I1, I2, I3, I4, I5 |
| PARAMETER | 5 | P1, P2, P3, P4, P5 |
| CATALOG | 4 | L1, L2, L3, L4 |
| **Total** | **24** | |

### Saboteur Attack Catalog

**CONCURRENCY (C1-C5): Pool and token contention**

| # | Attack | Description | Expected |
|---|--------|-------------|----------|
| C1 | Parallel same tile | 10 concurrent requests for same COG tile | All succeed or graceful 429/503 |
| C2 | Cross-pool burst | Simultaneous requests to COG + Vector + STAC endpoints | All 3 pools respond independently |
| C3 | Token refresh window | Rapid requests during expected 45-min token refresh cycle | No auth failures leak to client |
| C4 | Pool exhaustion attempt | 20+ rapid sequential requests to `/cog/tiles/...` | Pool queues or returns 503, no hang |
| C5 | Mixed read burst | 10 concurrent: 3 COG info + 3 vector items + 2 STAC search + 2 Zarr tiles | All respond, no cross-contamination |

**RESOURCE (R1-R5): Boundary and overload**

| # | Attack | Description | Expected |
|---|--------|-------------|----------|
| R1 | Oversized bbox | `/cog/preview.png?url={url}&max_size=10000` | 400 or capped, not OOM |
| R2 | Extreme zoom high | `/cog/tiles/WebMercatorQuad/30/0/0?url={url}` | 400 or empty tile, not crash |
| R3 | Extreme zoom low | `/cog/tiles/WebMercatorQuad/0/0/0?url={url}` on large dataset | Responds (possibly slow), no timeout cascade |
| R4 | Out-of-bounds tile | `/cog/tiles/WebMercatorQuad/10/999/999?url={url}` | 404 or empty tile, not 500 |
| R5 | Rapid sequential | 50 sequential tile requests as fast as possible | No connection leak, pool recovers |

**IDENTITY (I1-I5): Non-existent resources**

| # | Attack | Description | Expected |
|---|--------|-------------|----------|
| I1 | Fake collection | `/vector/collections/nonexistent.fake_table` | 404 with useful error, not 500 |
| I2 | Fake search ID | `/searches/00000000-0000-0000-0000-000000000000/info` | 404 or meaningful error |
| I3 | Malformed COG path | `/cog/info?url=/vsiaz/nonexistent-container/fake.tif` | Error with clear message, not hang |
| I4 | Wrong Zarr variable | `/xarray/info?url={zarr_url}&variable=nonexistent_var` | 400 or 422, not 500 |
| I5 | Invalid TMS | `/vector/collections/{id}/tiles/FakeTMS/10/512/384` | 400 or 422, not 500 |

**PARAMETER (P1-P5): Injection and malformation**

| # | Attack | Description | Expected |
|---|--------|-------------|----------|
| P1 | SQL injection in URL | `/cog/info?url='; DROP TABLE pgstac.items;--` | 400 or safe error, NOT 500 |
| P2 | Path traversal | `/cog/info?url=/vsiaz/../../etc/passwd` | 400 or sanitized, no file leak |
| P3 | Extremely long URL | `/cog/info?url=/vsiaz/{10000 chars}` | 400 or 414, not crash |
| P4 | Unicode/null bytes | `/cog/info?url=/vsiaz/test%00.tif` | 400, no null byte injection |
| P5 | Negative tile coords | `/cog/tiles/WebMercatorQuad/-1/-1/-1?url={url}` | 400 or 422, not 500 |

**CATALOG (L1-L4): TiPG catalog state attacks**

| # | Attack | Description | Expected |
|---|--------|-------------|----------|
| L1 | Tile after refresh | `POST /admin/refresh-collections`, then immediately request vector tile | Tile still served (catalog survives refresh) |
| L2 | Ghost collection | Request tiles from collection that may not exist after refresh | 404, not 500 or stale data |
| L3 | Rapid refresh | 5 rapid `POST /admin/refresh-collections` calls | All succeed or rate-limited, no pool corruption |
| L4 | Interleaved refresh | Alternate refresh-collections with vector tile requests | Both succeed, no deadlock or stale response |

**Timing strategy**: Vary timing relative to Pathfinder's expected progress:
- **Early attacks** (while Pathfinder runs COG chain): C1, C4, R2, R3
- **Mid attacks** (while Pathfinder runs Vector/Zarr): C2, C5, I1, I5, L1
- **Late attacks** (while Pathfinder runs STAC/Mosaic): C3, L3, L4, R5

**Key rules**:
- MUST use the same test data URLs as Pathfinder (from config)
- MUST use `tn-` prefix for any registered searches
- MUST record expected outcome (succeed/fail) for every attack
- MUST note any behavior that is surprising or undocumented

### Saboteur Attack Log Format

```
## Attack {CATEGORY}{NUMBER}: {description}
CATEGORY: CONCURRENCY | RESOURCE | IDENTITY | PARAMETER | CATALOG
TIMING: EARLY | MID | LATE
REQUEST: {method} {url}
RESPONSE: HTTP {code}
CONTENT-TYPE: {type}
BODY: {truncated to 500 chars}
EXPECTED: {succeed | fail} -- {reason}
ACTUAL: {what happened}
VERDICT: EXPECTED | UNEXPECTED | INTERESTING
NOTES: {observations, undocumented behavior, pool impact}
```

---

## Step 3: Dispatch Inspector + Provocateur (Phase 2, Parallel)

After both Phase 1 agents complete, dispatch Phase 2 agents simultaneously.

**Critical**: Inspector receives Pathfinder's checkpoint map but NOT Saboteur's attack log. This means any pool exhaustion, catalog corruption, or token expiry caused by Saboteur appears as unexplained divergences.

### Inspector Instructions

Receives Pathfinder's Response Checkpoint Map and captured values. Does NOT know about Saboteur.

**For each checkpoint -- re-execute Pathfinder's requests**:

```bash
# Re-run the same requests Pathfinder made and compare responses
# COG chain
curl -s "${BASE_URL}/cog/info?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif"
curl -s "${BASE_URL}/cog/bounds?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif"

# Vector chain
curl -s "${BASE_URL}/vector/collections" | jq '.collections | length'
curl -s "${BASE_URL}/vector/collections/geo.sg7_vector_test_cutlines_ord1/items?limit=1" | jq '.numberMatched'

# STAC chain
curl -s "${BASE_URL}/stac/collections" | jq '.collections | length'

# Mosaic (if Pathfinder registered one)
curl -s "${BASE_URL}/searches/{search_id}/info"
```

**Server state checks -- verification endpoints**:

```bash
# Full health diagnostics
curl -s "${BASE_URL}/health" | jq

# Key fields to extract:
# .status                                    -> "healthy" | "degraded" | "unhealthy"
# .services.cog.available                    -> true
# .services.xarray.available                 -> true
# .services.pgstac.available                 -> true
# .services.tipg.available                   -> true
# .services.tipg.details.collections_discovered -> {count}
# .services.stac_api.available               -> true
# .services.stac_api.details.pool_size       -> {n}
# .services.stac_api.details.pool_free       -> {n}
# .services.stac_api.details.collection_count -> {n}
# .dependencies.database.status              -> "ok"
# .dependencies.database.ping_time_ms        -> {ms}
# .dependencies.storage_oauth.status         -> "ok"
# .dependencies.storage_oauth.expires_in_seconds -> {n}
# .dependencies.postgres_oauth.status        -> "ok" (if managed_identity mode)
# .dependencies.postgres_oauth.expires_in_seconds -> {n}
# .issues                                    -> null or [...]

# Liveness + readiness
curl -s "${BASE_URL}/livez"
curl -s "${BASE_URL}/readyz"

# TiPG catalog diagnostics
curl -s "${BASE_URL}/vector/diagnostics"

# Catalog refresh state (read the response, don't actually refresh)
# Only check collection counts via /vector/collections
curl -s "${BASE_URL}/vector/collections" | jq '.collections | length'
```

**What to look for**:
- Response consistency: Pathfinder's bounds == Inspector's bounds? -> PASS
- Collection count stable: same count as Pathfinder recorded? -> PASS or DIVERGENCE
- Pool health: all pools have free connections? -> PASS or POOL_EXHAUSTION
- Token expiry: storage_oauth.expires_in_seconds > 300? -> PASS or TOKEN_WARNING
- Service availability: all 5 services available=true? -> PASS or SERVICE_DEGRADATION
- Issues array: null (no issues)? -> PASS or flag each issue
- Response times: /health response_time_ms < 5000? -> PASS or LATENCY_SPIKE
- STAC pool: pool_free > 0? -> PASS or STAC_POOL_EXHAUSTION
- Database ping: ping_time_ms < 1000? -> PASS or DB_LATENCY

### Inspector Output Format

```markdown
## State Audit

### Checkpoint {ID}: {description}
| Check | Pathfinder Value | Inspector Value | Verdict |
|-------|-----------------|-----------------|---------|
| COG bounds | {expected} | {actual} | PASS/DIVERGENCE |
| COG bands | {expected} | {actual} | PASS/DIVERGENCE |
| Vector collection count | {expected} | {actual} | PASS/DIVERGENCE |
| Vector feature count | {expected} | {actual} | PASS/DIVERGENCE |
| STAC collection count | {expected} | {actual} | PASS/DIVERGENCE |
| Mosaic search_id accessible | {yes} | {yes/no} | PASS/FAIL |

## Server Health Assessment

### Pool Status
| Pool | Available | Size | Free | Assessment |
|------|-----------|------|------|------------|
| pgstac (psycopg) | {yes/no} | {n} | {n} | {ok/exhausted/degraded} |
| STAC (asyncpg) | {yes/no} | {n} | {n} | {ok/exhausted/degraded} |
| TiPG (asyncpg) | {yes/no} | — | — | {ok/failed} |

### Token Status
| Token | Status | Expires In | Assessment |
|-------|--------|------------|------------|
| storage_oauth | {ok/warning/fail} | {n}s | {ok/expiring/expired} |
| postgres_oauth | {ok/warning/fail} | {n}s | {ok/expiring/expired} |

### Service Availability
| Service | Available | Collections/Details | Assessment |
|---------|-----------|---------------------|------------|
| cog | {true/false} | — | {ok/unavailable} |
| xarray | {true/false} | — | {ok/unavailable} |
| pgstac | {true/false} | — | {ok/unavailable} |
| tipg | {true/false} | {n} collections | {ok/unavailable/count_changed} |
| stac_api | {true/false} | {n} collections | {ok/unavailable/count_changed} |

## Unexplained Divergences
{Response values that differ from Pathfinder's checkpoints without known cause}
| Check | Pathfinder | Inspector | Severity |
...

## Issues Detected
{Items from /health issues array}
| Issue | Severity | Impact |
...

## Divergence Summary
| Checkpoint | Expected | Actual | Severity |
...
```

---

### Provocateur Instructions

Provocateur operates **completely independently** with its own `tp-` namespace. It receives only the endpoint list and fires boundary-value inputs. No knowledge of campaign state, test data, or other agents.

**Execute ALL attacks (P1-P10) against these endpoint categories**:

| Target Category | Endpoints | Method |
|----------------|-----------|--------|
| COG metadata | `/cog/info`, `/cog/bounds`, `/cog/statistics` | GET |
| COG tiles | `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}` | GET |
| COG preview | `/cog/preview.png` | GET |
| Zarr metadata | `/xarray/info`, `/xarray/variables` | GET |
| Zarr tiles | `/xarray/tiles/WebMercatorQuad/{z}/{x}/{y}` | GET |
| Vector metadata | `/vector/collections/{id}`, `/vector/collections/{id}/items` | GET |
| Vector tiles | `/vector/collections/{id}/tiles/WebMercatorQuad/{z}/{x}/{y}` | GET |
| STAC browsing | `/stac/collections`, `/stac/search` | GET |
| STAC search | `/stac/search` | POST |
| Mosaic register | `/searches/register` | POST |
| Admin refresh | `/admin/refresh-collections` | POST |

### Payload Attack Catalog

| # | Attack | Input | Target Endpoints | Expected Response |
|---|--------|-------|------------------|-------------------|
| P1 | Path traversal in URL param | `?url=/vsiaz/../../etc/passwd` | COG info, Zarr info | 400 or sanitized, no file contents |
| P2 | SQL injection in filter | `?url='; DROP TABLE pgstac.items;--` | COG info, STAC search | 400 or safe error, NOT 500 |
| P3 | XSS in query string | `?url=<script>alert(1)</script>` | COG info | 400 or escaped, no reflection |
| P4 | Large POST body | 1MB JSON to `/stac/search` | STAC search | 400 or 413, not OOM |
| P5 | Invalid GeoJSON bbox | `{"bbox": [999,999,-999,-999]}` to `/stac/search` | STAC search | 400 or empty results, not 500 |
| P6 | Negative tile coords | `/cog/tiles/WebMercatorQuad/-1/-1/-1?url=...` | COG tiles, Vector tiles | 400 or 422, not 500 |
| P7 | Non-numeric z/x/y | `/cog/tiles/WebMercatorQuad/abc/def/ghi?url=...` | COG tiles, Vector tiles | 400 or 422, not 500 |
| P8 | Missing required params | `/cog/info` (no `url=`) | COG info, Zarr info | 400 or 422 with field name |
| P9 | Binary/null bytes | `?url=/vsiaz/test%00%01%02.tif` | COG info | 400, no null byte injection |
| P10 | HTTP method abuse | `POST /cog/info`, `POST /vector/collections`, `GET /searches/register` | All GET-only and POST-only endpoints | 405 Method Not Allowed |

**Additional Provocateur-designed attacks**:
- Empty body POST to `/searches/register` -- expect 400 or 422
- Empty body POST to `/stac/search` -- expect 400 or 422
- POST with `Content-Type: text/plain` to `/searches/register` -- expect 400 or 415
- Extremely long collection ID: `/vector/collections/{10000 chars}/items` -- expect 404 or 414
- Invalid `rescale` format: `/xarray/tiles/...?rescale=not,a,number` -- expect 400
- Invalid `bidx`: `/xarray/tiles/...?bidx=-1` or `bidx=9999` -- expect 400 or 422
- `colormap_name=nonexistent` -- expect 400 or fallback
- Register search with `tp-` prefix, then immediately request tiles (race condition)
- POST to `/admin/refresh-collections` repeatedly (10x) -- expect all succeed or rate limit

### Provocateur Output Format

```markdown
## Error Behavior Map

### Category: COG Endpoints

| # | Attack | Input Summary | HTTP Code | Response Body (truncated) | Expected | Verdict |
|---|--------|---------------|-----------|---------------------------|----------|---------|
| P1 | Path traversal | `?url=../../etc/passwd` | {code} | {body} | 400 | PASS/FAIL |
...

### Category: Zarr Endpoints
...

### Category: Vector Endpoints
...

### Category: STAC Endpoints
...

### Category: Mosaic Endpoints
...

### Category: Admin Endpoints
...

## Crash Log (500 responses)
| # | Endpoint | Attack | Input | Response |
...

## Missing Validations
| # | Endpoint | Input | What's Missing | Severity |
...

## Inconsistent Error Formats
| Endpoint A | Error Format | Endpoint B | Error Format | Issue |
...
```

---

## Step 4: Dispatch Tribunal (Phase 3, Sequential)

Tribunal receives ALL 4 specialist outputs and General's scoring rubric.

### Tribunal Procedure

**Step 1: Correlation**

Cross-reference Inspector's divergences with Saboteur's attack log:
- For each Inspector divergence (e.g., pool exhausted, collection count changed), check if a Saboteur attack explains it
- Divergences explained by Saboteur attacks = INTERLEAVING DEFECTS
- Divergences NOT explained by Saboteur = INDEPENDENT BUGS

**Step 2: Classification**

Every finding classified into one of:

| Category | Source | Meaning |
|----------|--------|---------|
| RESPONSE DIVERGENCE | Inspector | Pathfinder's expected response != Inspector's observed response |
| LEAKED ATTACK | Saboteur | Attack should have failed but succeeded (e.g., SQL injection returned 200) |
| INTERLEAVING DEFECT | Inspector + Saboteur correlation | Saboteur's load caused pool exhaustion or catalog corruption visible to Inspector |
| INPUT VALIDATION GAP | Provocateur | Missing validation, 500, or insecure response |
| POOL/STATE ISSUE | Inspector | Pool exhausted, token expired, service degraded -- cause unknown or independent |
| CATALOG CORRUPTION | Inspector + Saboteur | TiPG catalog state inconsistent after refresh attacks |

**Step 3: Severity Scoring**

| Severity | Definition |
|----------|------------|
| CRITICAL | Pool exhaustion under moderate load, token leak, path traversal succeeds, SQL injection returns data |
| HIGH | 500 errors from malformed input, catalog corruption after refresh, cross-pool interference |
| MEDIUM | Wrong HTTP status code, inconsistent error format across endpoint families, slow recovery |
| LOW | Misleading error message, undocumented behavior, cosmetic inconsistency |

**Step 4: Scoreboard**

Count findings per specialist. "Unique" = only this agent's lens could catch it.

**Step 5: Pipeline Chain Recommendations**

For each HIGH or CRITICAL finding, recommend:
- Which code-review pipeline (COMPETE or REFLEXION) to run
- Which files to target (e.g., `geotiler/routers/vector.py`, `geotiler/auth/cache.py`, `geotiler/services/database.py`)
- What scope split to use (for COMPETE)

### Tribunal Output Format

```markdown
# TOURNAMENT Report -- Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {deployed version from /health}
**Pipeline**: TOURNAMENT (Tile Server)

## Executive Summary
{2-3 sentences: what was tested, what was found, overall verdict}

## Response Divergences
| # | Checkpoint | Pathfinder Value | Inspector Value | Caused by Saboteur? | Severity |
...

## Leaked Attacks
| # | Attack | Category | Expected | Actual | Severity |
...

## Interleaving Defects
| # | Saboteur Attack | Inspector Observation | How State Diverged | Severity |
...

## Input Validation Gaps
| # | Endpoint | Attack | Input | HTTP Code | Expected | Severity |
...

## Pool/State Issues
| # | Pool/Component | Observation | Impact | Severity |
...

## Catalog Corruption
| # | Attack Sequence | Before State | After State | Impact | Severity |
...

## Specialist Scoreboard
| Agent | Findings | Critical | High | Medium | Low | Unique |
|-------|----------|----------|------|--------|-----|--------|
| Pathfinder | (ground truth) | -- | -- | -- | -- | -- |
| Saboteur | {n} | {n} | {n} | {n} | {n} | {n} |
| Inspector | {n} | {n} | {n} | {n} | {n} | {n} |
| Provocateur | {n} | {n} | {n} | {n} | {n} | {n} |
| **Tribunal** | {n} | {n} | {n} | {n} | {n} | {n} |

## Reproduction Commands
### Finding {N}: {title}
```bash
BASE_URL="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"
# Reproduce:
curl -s "${BASE_URL}/{endpoint}?{params}" | jq
```

## Pipeline Chain Recommendations
| Finding | Severity | Pipeline | Target Files | Scope |
...

## Verdict
{PASS | FAIL | NEEDS INVESTIGATION}
Total findings: {N} ({N} critical, {N} high, {N} medium, {N} low)
```

### Save Output

Save to `docs/agent_review/agent_docs/TOURNAMENT_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Asymmetry Summary

| Agent | Gets | Doesn't Get | What This Reveals |
|-------|------|-------------|-------------------|
| General | Full context | -- | Defines the campaign |
| Pathfinder | Canonical read chains only | Saboteur's attack plan | Unbiased ground truth for response consistency |
| Saboteur | Attack categories + test data | Pathfinder's checkpoints | Attacks without gaming audit |
| Inspector | Pathfinder's checkpoints only | Saboteur's attacks | Divergences without knowing cause |
| Provocateur | Endpoint list only | Everything else | Input validation in pure isolation |
| Tribunal | ALL outputs | -- | Full picture with correlations |

### Key Design Insight: Inspector's Deliberate Blindness

Unlike WARGAME's Oracle (who sees both Blue and Red outputs), TOURNAMENT's Inspector sees ONLY Pathfinder's checkpoints. This means:

1. Saboteur exhausts a connection pool -> Inspector sees degraded health or slow responses
2. Inspector reports it as "expected healthy, found pool_free=0, cause unknown"
3. Tribunal correlates with Saboteur's C4 (pool exhaustion) attack to find the cause
4. This two-step process catches issues that a single agent seeing everything might rationalize away

The gap between "what Inspector reports" and "what Tribunal determines" is itself a quality signal. If Inspector reports many divergences that Tribunal can't correlate to Saboteur's attacks, those are independent bugs -- the most valuable findings.

### Tile Server Adaptation: What "State" Means Here

In the ETL TOURNAMENT, "state" means database rows (jobs, releases, STAC items). In this tile server TOURNAMENT, "state" means:

| State Component | What Pathfinder Records | What Saboteur Attacks | What Inspector Checks |
|-----------------|------------------------|----------------------|----------------------|
| **Connection pools** | Implicit (requests succeed) | C1-C5 (concurrency, exhaustion) | `/health` pool_size, pool_free |
| **Token cache** | Implicit (auth works) | C3 (token refresh window) | `/health` expires_in_seconds |
| **TiPG catalog** | Collection count, IDs | L1-L4 (refresh, interleave) | `/vector/collections` count, `/vector/diagnostics` |
| **Response consistency** | Bounds, bands, counts, content-types | R1-R5 (boundary values) | Same requests, compare values |
| **Error handling** | N/A (happy path) | I1-I5, P1-P5 (bad input) | N/A (Provocateur covers this) |
