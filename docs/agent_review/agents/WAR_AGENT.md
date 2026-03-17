# Pipeline 5: WARGAME (Red vs Blue State Divergence)

**Purpose**: Focused adversarial testing of state consistency for a read-only tile server. Red attacks internal state (connection pools, token caches, catalog consistency, response determinism) while Blue establishes ground truth through golden-path read chains. Oracle catches where system state diverges from expectations.

**Best for**: Pre-release state integrity check. Verifying that concurrent load, token refresh cycles, and catalog mutations do not cause observable response divergences.

---

## Tile Server State Model

Unlike an ETL platform with database mutations, a tile server has subtle internal state that can diverge under pressure:

| State Domain | Description | Failure Mode |
|-------------|-------------|--------------|
| **Connection Pools** | 3 independent pools: pgstac (psycopg), TiPG (asyncpg), STAC (asyncpg) with min/max sizes and token-based auth | Pool exhaustion, connection leak, stale auth in connection string |
| **Token Cache** | Storage OAuth and Postgres OAuth tokens refreshed every 45 min by background task. Token embedded in connection strings -- pool must be recreated on refresh | Stale token in pool, race during pool recreation, brief unavailability window |
| **TiPG Catalog** | In-memory collection catalog loaded at startup. Refreshed via `/admin/refresh-collections` or TTL middleware. Each instance has its own catalog | Catalog inconsistency across instances, stale catalog after refresh failure |
| **STAC Search Cache** | pgSTAC search hashes cached internally by search registration | Hash collision on identical-but-differently-ordered params, stale search results |
| **Response Consistency** | Same request should return same response (tile bytes, metadata, collection counts) | Non-deterministic tile rendering, floating-point drift, pool-dependent response differences |

---

## Endpoint Access Rules

Agents test through the **same API surface** that consumers use. No mutations exist except STAC search registration and catalog refresh.

| Tier | Endpoints | Who Uses | Purpose |
|------|-----------|----------|---------|
| **Consumer** | `/cog/*`, `/xarray/*`, `/vector/*`, `/stac/*`, `/searches/*` | Blue, Red | All tile-serving and catalog-browsing endpoints. The consumer surface. |
| **Verification** | `/health`, `/readyz`, `/livez`, `/vector/diagnostics` | Oracle only | Read-only state auditing after the battle phase. |
| **Admin** | `/admin/refresh-collections` | Red (attacks), Oracle (post-battle verification) | Catalog refresh webhook. Red uses it as an attack vector; Oracle uses it to verify post-battle state. |
| **Synthesis** | None (reads other agents' outputs) | Coroner | Root-cause analysis and report. Documents reproduction curls but does not execute them. |

**Hard rule**: Blue MUST only use consumer endpoints. Red uses consumer endpoints plus `/admin/refresh-collections` as an attack vector. Oracle may use all endpoints for deep verification.

---

## Agent Roles

| Agent | Role | Runs As | Input |
|-------|------|---------|-------|
| Strategist | Define campaign scope, split into Red + Blue briefs | Claude (no subagent) | siege_config_titiler.json, API docs, COMPETE findings |
| Blue | Execute golden-path read chains, record expected state as response checksums and metadata values | Task (parallel with Red) | Blue Brief only |
| Red | Execute adversarial attack sequences targeting state consistency | Task (parallel with Blue) | Red Brief only |
| Oracle | Re-execute Blue's chains, compare responses to Blue's checkpoints, cross-reference Red's attack log | Task (sequential) | Blue's checkpoints + Red's attack log |
| Coroner | Root-cause analysis, reproduction scripts, pipeline chain recommendations | Task (sequential) | Oracle's findings + both logs |

**Maximum parallel agents**: 2 (Blue + Red only)

---

## Pipeline Flow

```
Target: BASE_URL (Azure endpoint)
    |
    Strategist (Claude -- no subagent)
        Reads siege_config_titiler.json, API docs, prior COMPETE findings
        Defines: campaign scope, shared wg- namespace (for STAC searches)
        Outputs: Blue Brief + Red Brief
    |
    ======== BATTLE PHASE ========
    |
    +--- Blue (Task) ---------+--- Red (Task) -----------+  [parallel]
    |    Golden-path executor   |    State attacker        |
    |    Runs canonical read    |    Runs attacks on       |
    |    chains across all 4    |    pools, tokens,        |
    |    service families       |    catalog, cache,       |
    |    Records response       |    response consistency  |
    |    checksums + metadata   |    Records attack log    |
    +---------------------------+--------------------------+
    |
    ======== JUDGMENT PHASE ========
    |
    Oracle (Task)                                           [sequential]
        Queries /health for pool and token state
        Re-executes Blue's exact request chains
        Compares responses to Blue's checkpoints
        Cross-references Red's attacks for causation
        OUTPUT: Divergence Report
    |
    Coroner (Task)                                          [sequential]
        Root-cause analysis per divergence
        OUTPUT: Final WARGAME Report with reproduction curls
```

---

## Campaign Configuration

Shared config file: `docs/agent_review/siege_config_titiler.json`

- **`test_data.cog`**: COG URL, bounds, bands, dtype for Blue's COG chain
- **`test_data.zarr`**: Zarr URL, variable, rescale, bidx for Blue's Zarr chain
- **`test_data.vector`**: Collection ID, geometry type, min features for Blue's Vector chain
- **`test_data.stac`**: Collection ID, item ID, assets for Blue's STAC chain
- **`endpoint_access_rules`**: Canonical endpoint patterns for all service families

---

## Prerequisites

```bash
BASE_URL="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

# Health check -- verify all services are healthy before launching
curl -sf "${BASE_URL}/health" | jq '.status, .services | to_entries[] | {(.key): .value.status}'

# Readiness probe -- confirm database connectivity
curl -sf "${BASE_URL}/readyz" | jq

# Vector diagnostics -- confirm TiPG catalog is populated
curl -sf "${BASE_URL}/vector/diagnostics" | jq

# Verify test data is accessible
curl -sf "${BASE_URL}/cog/info?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif" | jq '.band_metadata'
curl -sf "${BASE_URL}/vector/collections/geo.sg7_vector_test_cutlines_ord1" | jq '.id'
curl -sf "${BASE_URL}/stac/collections/sg-raster-test-dctest" | jq '.id'
```

No schema rebuild or data nuke is needed. This is a read-only tile server. The only mutable state is STAC search registrations (namespaced with `wg-` prefix) and the TiPG in-memory catalog.

---

## Step 1: Play Strategist (No Subagent)

Claude plays Strategist directly. Two jobs:

### 1. Define the Campaign

1. Read `siege_config_titiler.json` and the Attack Catalog (below).
2. Set the shared namespace: `wg-` prefix for any STAC searches registered during the test.
3. Choose attack categories for Red based on context:
   - **Default**: All 5 categories (POOL_STRESS, TOKEN_RACE, CATALOG_CONTENTION, CACHE_POISON, RESPONSE_DRIFT)
   - **Focused** (after COMPETE): Target categories that match COMPETE findings
4. Define test data from `siege_config_titiler.json`:
   - COG: `/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif`
   - Zarr: `abfs://silver-zarr/cmip6-tasmax-sample.zarr` (variable=tasmax, bidx=1, rescale=250,320)
   - Vector: `geo.sg7_vector_test_cutlines_ord1`
   - STAC: `sg-raster-test-dctest` collection

### 2. Write the Two Briefs

**Blue Brief** contains:
- BASE_URL and test data (all 4 service families)
- Canonical read chain sequences to execute (info -> tilejson -> tiles for each family)
- State checkpoint instructions (what to record after each step)
- Blue does NOT see the attack catalog or Red's categories

**Red Brief** contains:
- BASE_URL and SAME test data (same endpoints, same `wg-` namespace for searches)
- Attack categories to execute with minimum counts per category
- Reference to the Attack Catalog
- Red does NOT see Blue's checkpoint map or expected state

---

## Step 2: Dispatch Blue + Red (Parallel)

Dispatch both agents simultaneously using the Agent tool. Both run in parallel.

### Blue Instructions

Execute canonical read chain sequences from the Blue Brief. After each step:

1. Record the full HTTP request and response status
2. Record response metadata (bounds, band count, collection count, content-type, content-length)
3. For tile responses, record a SHA-256 hash of the response body
4. Record response time in milliseconds
5. Record the **expected system state** at this checkpoint

**Sequences to execute**:

1. **COG lifecycle**: info -> bounds -> tilejson -> statistics -> 3 tiles at zoom levels 10, 12, 14 -> preview
   - Checkpoint: bounds, band_count, dtype, tile content-type, tile content-length, response times
2. **Zarr lifecycle**: variables -> info -> bounds -> tilejson -> 3 tiles at zoom levels 0, 2, 4
   - Checkpoint: variable list, bounds, tile dimensions, tile content-type
3. **Vector lifecycle**: collections list -> collection detail -> items (limit=10) -> tilejson -> 3 vector tiles
   - Checkpoint: collection count, feature count, geometry type, tile content-type (application/x-protobuf), tile content-length
4. **STAC lifecycle**: collections list -> collection detail -> items -> search (bbox filter) -> register mosaic search (with `wg-` prefix metadata) -> mosaic tilejson
   - Checkpoint: collection count, item count, search result count, mosaic search_id, tilejson bounds

Blue records ALL response bodies (or SHA-256 hashes for binary tile responses) as "expected state".

### Blue Checkpoint Format

```
## Checkpoint {N}: {service_family} - {description}
AFTER: {step description}
REQUEST: {method} {full_url_with_params}
RESPONSE: HTTP {code}
EXPECTED STATE:
  Content-Type: {value}
  Content-Length: {value}
  Response-Time-Ms: {value}
  Body-Hash: {sha256 for binary, or full body for JSON < 500 chars}
  Metadata:
    - bounds: {value}
    - band_count: {value}
    - collection_count: {value}
    - feature_count: {value}
    - {other service-specific fields}
```

### Blue HTTP Log Format

```
### Step {N}: {service_family} - {description}
REQUEST: {method} {url}
PARAMS: {query_params}
RESPONSE: HTTP {code}
CONTENT-TYPE: {value}
CONTENT-LENGTH: {value}
RESPONSE-TIME-MS: {value}
BODY-HASH: {sha256 for binary responses}
BODY: {truncated to 500 chars for JSON responses}
VERDICT: PASS | FAIL
```

---

### Red Instructions

Execute attacks from the Red Brief targeting the SAME endpoints and test data as Blue. Red's attacks target availability and consistency, not data corruption (this is a read-only API).

**Minimum attacks**: 3 per assigned category, chosen from the Attack Catalog.

**Key rules**:
- Red MUST use the same test data URLs and collection IDs as Blue
- Red should vary timing -- some attacks early (while Blue is mid-chain), some late (after Blue completes a chain)
- Red should try attacks that could interfere with Blue's response consistency (e.g., refresh catalog during Blue's vector chain, exhaust pools during Blue's tile requests)
- For STAC search registration, Red MUST use the `wg-` namespace prefix

### Red Attack Log Format

```
## Attack {category}{number}: {description}
CATEGORY: POOL_STRESS | TOKEN_RACE | CATALOG_CONTENTION | CACHE_POISON | RESPONSE_DRIFT
REQUEST: {method} {url}
PARAMS: {query_params}
BODY: {json if POST}
RESPONSE: HTTP {code}
CONTENT-TYPE: {value}
RESPONSE-TIME-MS: {value}
EXPECTED: {succeed | fail | degrade} -- {reason}
ACTUAL: {what happened}
VERDICT: EXPECTED | UNEXPECTED | INTERESTING
NOTES: {observations about response time spikes, error messages, etc.}
```

---

## Attack Catalog (Reference)

### POOL_STRESS (PS) -- Connection Pool Exhaustion

| # | Attack | Method | Expected |
|---|--------|--------|----------|
| PS1 | Rapid sequential requests | 20 rapid-fire requests to `/cog/tiles` (same tile, no pause) | All succeed, no pool errors |
| PS2 | Cross-family simultaneous | Request COG tile + Vector tile + STAC search simultaneously | All 3 pools serve independently |
| PS3 | Large tile barrage | Request multiple tiles at high zoom (z=18+) to hold pool connections longer | Responses arrive, possibly slower |
| PS4 | Vector items + tiles interleaved | Alternate `/vector/.../items?limit=100` with tile requests | Items and tiles both return correctly |
| PS5 | Pool size probe | Request `/health` after barrage, check pool free counts | Pools recover to pre-barrage levels |

### TOKEN_RACE (TR) -- OAuth Token Refresh Window

| # | Attack | Method | Expected |
|---|--------|--------|----------|
| TR1 | Token expiry monitor | Poll `/health` to find `expires_in_seconds` for storage_oauth and postgres_oauth | Tokens have > 0 TTL |
| TR2 | Refresh window probe | Time requests to land when token TTL < 300s (warning zone from /health) | Requests still succeed (token valid until 0) |
| TR3 | Post-refresh burst | If token refresh observed (TTL resets), immediately send 10 rapid requests | All succeed with new token |
| TR4 | Cross-service during refresh | During low-TTL window, request COG (needs storage token) and Vector (needs pg token) simultaneously | Both services respond, possibly with brief latency |
| TR5 | Health during refresh | Request `/health` repeatedly during token transition | Token status transitions cleanly, no "fail" flicker |

### CATALOG_CONTENTION (CC) -- TiPG Catalog Refresh Race

| # | Attack | Method | Expected |
|---|--------|--------|----------|
| CC1 | Refresh during Blue's vector chain | Call `/admin/refresh-collections` while Blue is requesting vector tiles | Blue's requests complete; collection count may change |
| CC2 | Rapid refresh spam | Call `/admin/refresh-collections` 10x in rapid succession | All return success, collection counts stable |
| CC3 | Request after refresh | Call `/admin/refresh-collections`, then immediately request `/vector/collections` | Collections list reflects refreshed catalog |
| CC4 | Tile during refresh | Call `/admin/refresh-collections` and simultaneously request a vector tile | Tile request succeeds (existing collection persists through refresh) |
| CC5 | Diagnostics during refresh | Call `/admin/refresh-collections` and simultaneously request `/vector/diagnostics` | Diagnostics returns consistent snapshot |

### CACHE_POISON (CP) -- STAC Search and Response Caching

| # | Attack | Method | Expected |
|---|--------|--------|----------|
| CP1 | Duplicate search registration | Register STAC mosaic search with identical params as Blue's search | Returns same search_id (idempotent hash) or new ID |
| CP2 | Param ordering variation | Request same tile URL with query params in different order | Same tile bytes returned |
| CP3 | Rescale variation | Request tilejson, then immediately request tiles with different `rescale` values | Each rescale produces different (correct) tiles |
| CP4 | Conflicting search bbox | Register search with overlapping but different bbox than Blue's | Separate search_id, no interference with Blue's search |
| CP5 | Collection items with varied limits | Request `/stac/collections/{id}/items` with limit=1, limit=10, limit=100 | Item lists are consistent subsets of each other |

### RESPONSE_DRIFT (RD) -- Response Determinism

| # | Attack | Method | Expected |
|---|--------|--------|----------|
| RD1 | Tile idempotency | Request same COG tile 10x in sequence, hash each response | All 10 hashes identical |
| RD2 | Health stability | Request `/health` 10x in sequence | Pool stats stable (free connections +/- 1), no status flicker |
| RD3 | Collection count consistency | Request `/vector/collections` 10x in sequence | Collection count identical all 10 times |
| RD4 | STAC search consistency | Execute same `/stac/search` query 10x | Result count and item IDs identical |
| RD5 | Info endpoint consistency | Request `/cog/info?url=...` 10x | Bounds, bands, dtype identical all 10 times |
| RD6 | Vector items consistency | Request same items endpoint 10x with same limit | Feature count and feature IDs identical |
| RD7 | Cross-zoom tile independence | Request z=10 tile, then z=12 tile, then z=10 again | First and third responses byte-identical |

---

## Step 3: Dispatch Oracle (Sequential, After Battle Phase)

Oracle receives Blue's State Checkpoint Map and Red's Attack Log. Oracle verifies system state and re-executes Blue's chains to detect divergences.

### Oracle Procedure

**Step 1: System State Audit**

Query `/health` and record post-battle state:

```bash
# Full health -- verify all 3 pools healthy, token TTL > 0, no error spikes
curl -sf "${BASE_URL}/health" | jq '{
  status,
  services: (.services | to_entries | map({key, status: .value.status, available: .value.available})),
  pool_states: {
    stac_pool_size: .services.stac_api.details.pool_size,
    stac_pool_free: .services.stac_api.details.pool_free,
    tipg_collections: .services.tipg.details.collections_discovered
  },
  token_ttl: {
    storage: .dependencies.storage_oauth.expires_in_seconds,
    postgres: .dependencies.postgres_oauth.expires_in_seconds
  },
  issues
}'

# Readiness -- confirm service can handle traffic
curl -sf "${BASE_URL}/readyz" | jq

# Vector diagnostics -- catalog integrity
curl -sf "${BASE_URL}/vector/diagnostics" | jq
```

**Step 2: Re-Execute Blue's Read Chains**

For each of Blue's checkpoints, re-execute the exact same request and compare:

- HTTP status code (must match)
- Content-Type header (must match)
- Content-Length header (must match for deterministic responses)
- Response body hash (must match for tile responses)
- JSON metadata values (bounds, band_count, collection_count, feature_count must match)
- Response time (flag if > 3x Blue's recorded time)

```bash
# Example: Re-execute Blue's COG info checkpoint
curl -sf "${BASE_URL}/cog/info?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif" | jq

# Example: Re-execute Blue's tile and hash it
curl -sf "${BASE_URL}/cog/tiles/WebMercatorQuad/14/4686/6267?url=/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif" | sha256sum

# Example: Re-execute Blue's vector collections
curl -sf "${BASE_URL}/vector/collections" | jq '.collections | length'

# Example: Re-execute Blue's STAC search
curl -sf "${BASE_URL}/stac/search?limit=10&collections=sg-raster-test-dctest" | jq '.numberMatched'
```

**Step 3: Detect Divergences**

For each comparison, flag divergences:

- Different HTTP status code -> SERVICE_FAILURE
- Different collection count -> CATALOG_INCONSISTENCY
- Different tile bytes (hash mismatch) -> RESPONSE_INSTABILITY
- Different bounds or metadata -> DATA_DRIFT
- Different STAC search results -> CACHE_INCOHERENCE
- Response time > 3x Blue's time -> POOL_DEGRADATION
- Token TTL = 0 or negative -> TOKEN_FAILURE

**Step 4: Cross-Reference Red's Attacks**

For each of Red's attacks, check:
- Did attacks that should have been harmless actually cause divergences?
- Did any CATALOG_CONTENTION attacks correlate with CATALOG_INCONSISTENCY divergences?
- Did any POOL_STRESS attacks correlate with POOL_DEGRADATION divergences?
- Did any TOKEN_RACE attacks correlate with TOKEN_FAILURE divergences?
- Did any CACHE_POISON attacks correlate with CACHE_INCOHERENCE divergences?
- Did any RESPONSE_DRIFT attacks reveal non-determinism?

**Step 5: Classify Divergences**

| Classification | Description | Trigger |
|----------------|-------------|---------|
| POOL_DEGRADATION | Pool connections exhausted or slow to recover | Response times spiked, pool_free = 0 post-battle |
| CATALOG_INCONSISTENCY | TiPG catalog changed between Blue's run and Oracle's verification | Collection count differs, collection missing |
| TOKEN_FAILURE | OAuth token expired or invalid during requests | 401/403 responses, token TTL = 0 |
| CACHE_INCOHERENCE | STAC search results or tile responses changed for identical queries | Search result count differs, tile hash mismatch |
| RESPONSE_INSTABILITY | Same request returns different response bytes | Tile hash mismatch on identical request |

### Oracle Output Format

```markdown
## System State Audit

### Post-Battle Health
| Metric | Value | Verdict |
|--------|-------|---------|
| Overall status | {healthy|degraded|unhealthy} | {PASS|FAIL} |
| pgSTAC pool | {size}/{max} ({free} free) | {PASS|FAIL} |
| TiPG pool | {available} | {PASS|FAIL} |
| STAC pool | {size}/{max} ({free} free) | {PASS|FAIL} |
| Storage token TTL | {seconds}s | {PASS|WARN|FAIL} |
| Postgres token TTL | {seconds}s | {PASS|WARN|FAIL} |
| TiPG collections | {count} | {PASS|FAIL} |
| Issues | {list or none} | {PASS|FAIL} |

## Checkpoint Verification

### Checkpoint {N}: {service_family} - {description}
| Check | Blue Expected | Oracle Actual | Verdict |
|-------|---------------|---------------|---------|
| HTTP Status | {code} | {code} | {MATCH|DIVERGE} |
| Content-Type | {value} | {value} | {MATCH|DIVERGE} |
| Body Hash | {hash} | {hash} | {MATCH|DIVERGE} |
| {metadata_key} | {value} | {value} | {MATCH|DIVERGE} |
| Response Time | {ms}ms | {ms}ms | {OK|DEGRADED} |

## State Divergences
| Checkpoint | Expected | Actual | Classification |
|------------|----------|--------|----------------|
...

## Attack Correlation
| Red Attack | Blue Checkpoint Affected | Divergence Type | Confidence |
|------------|--------------------------|-----------------|------------|
...

## Red Attack Audit
| Attack | Expected Outcome | Actual Outcome | Verdict |
|--------|------------------|----------------|---------|
...
```

---

## Step 4: Dispatch Coroner (Sequential, After Oracle)

Coroner receives Oracle's full output, Red's attack log, and Blue's execution log.

### Coroner Procedure

For each divergence from Oracle:

1. **Root-cause hypothesis**: Which internal state domain failed? Reference specific files/functions:
   - Pool issues -> `geotiler/services/database.py`, `geotiler/app.py` (startup/shutdown)
   - Token issues -> `geotiler/auth/cache.py`, background refresh task in `geotiler/app.py`
   - Catalog issues -> `geotiler/routers/vector.py` (refresh_tipg_pool), `geotiler/routers/admin.py`
   - Cache issues -> pgSTAC internal search hashing, titiler-pgstac search registration
   - Response drift -> GDAL rendering non-determinism, connection-dependent state

2. **Reproduction steps**: Exact curl sequence to reproduce the divergence.

3. **Severity classification**:
   - CRITICAL: Data corruption -- different tile bytes for same request (wrong map rendered to user)
   - HIGH: Intermittent failures -- requests fail during token refresh or catalog reload
   - MEDIUM: Degraded performance -- pool exhaustion causes timeouts under load
   - LOW: Cosmetic -- health endpoint flickers, diagnostics show transient state

4. **Pipeline chain**: Suggest which code-review pipeline (COMPETE or REFLEXION) to run, on which files, with what scope.

### Coroner Output Format

```markdown
# WARGAME Report -- Run {N}

**Date**: {date}
**Target**: {BASE_URL}
**Version**: {deployed version from /health}
**Pipeline**: WARGAME
**State Model**: Read-only tile server (pools, tokens, catalog, response determinism)

## Executive Summary
{2-3 sentences summarizing findings}

## Findings

### Finding {N}: {title}
**Severity**: CRITICAL | HIGH | MEDIUM | LOW
**Classification**: POOL_DEGRADATION | CATALOG_INCONSISTENCY | TOKEN_FAILURE | CACHE_INCOHERENCE | RESPONSE_INSTABILITY
**Root Cause**: {hypothesis -- file, function, mechanism}
**Red Attack Correlation**: {which Red attack(s) triggered this, or "independent"}
**Reproduction**:
```bash
BASE_URL="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"
# Step 1: Establish baseline
curl -sf "${BASE_URL}/health" | jq '.status'
# Step 2: Execute attack
curl ... # the attack sequence
# Step 3: Verify divergence
curl ... # the failing check
```

**Suggested Follow-Up**: Run {COMPETE|REFLEXION} on `{file_path}` with scope `{scope}`

## Summary
| Classification | Findings | Critical | High | Medium | Low |
|----------------|----------|----------|------|--------|-----|
| POOL_DEGRADATION | {n} | ... | ... | ... | ... |
| CATALOG_INCONSISTENCY | {n} | ... | ... | ... | ... |
| TOKEN_FAILURE | {n} | ... | ... | ... | ... |
| CACHE_INCOHERENCE | {n} | ... | ... | ... | ... |
| RESPONSE_INSTABILITY | {n} | ... | ... | ... | ... |

## Pipeline Chain Recommendations
| Finding | Pipeline | Target Files | Scope |
|---------|----------|--------------|-------|
| ... | COMPETE | geotiler/auth/cache.py | Token refresh race condition |
| ... | REFLEXION | geotiler/routers/vector.py | Catalog refresh atomicity |

## Verdict
{PASS | FAIL | NEEDS INVESTIGATION}
```

### Save Output

Save to `docs/agent_review/agent_docs/WARGAME_RUN_{N}.md`.
Log the run in `docs/agent_review/AGENT_RUNS.md`.

---

## Information Asymmetry Summary

| Agent | Gets | Doesn't Get | What This Reveals |
|-------|------|-------------|-------------------|
| Strategist | Full context (config, attack catalog, endpoints) | -- | Defines the campaign |
| Blue | Blue Brief (canonical read chains, test data) | Red's attack plan, attack catalog | Unbiased ground truth for response checksums |
| Red | Red Brief (attacks + same test data) | Blue's checkpoint map, expected checksums | Attacks without gaming oracle comparisons |
| Oracle | Blue checkpoints + Red log + verification endpoints | -- | Divergences, attack correlations |
| Coroner | Oracle findings + both logs | -- | Root causes, reproduction steps |

### Why Cross-Contamination Detection Works

Red and Blue use the **SAME endpoints and test data**. This means:

1. Blue requests `/vector/collections` and records count = 15
2. Red calls `/admin/refresh-collections` 10x in rapid succession during Blue's chain
3. Oracle re-executes Blue's `/vector/collections` request and gets count = 15
4. If Red's catalog refresh caused a transient catalog inconsistency (e.g., collection briefly missing during refresh), Oracle detects it through:
   - Blue's vector tile requests failing mid-chain (Blue logs FAIL verdict)
   - Oracle's re-execution returning a different count than Blue recorded

For STAC searches, the shared `wg-` namespace means:
1. Blue registers a mosaic search with specific params
2. Red registers a search with the same params (hash collision test) or overlapping bbox
3. Oracle verifies Blue's search_id still returns the expected tilejson and tiles

The core mechanism is **response determinism**: a read-only tile server should return identical responses for identical requests, regardless of concurrent load. Any divergence between Blue's recorded state and Oracle's verification is a finding.

---

## Test Data Reference

From `docs/agent_review/siege_config_titiler.json`:

| Family | Test Data | Key Params |
|--------|-----------|------------|
| COG | `/vsiaz/silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif` | 3-band uint8, bounds: [-77.03, 38.91, -77.01, 38.93] |
| Zarr | `abfs://silver-zarr/cmip6-tasmax-sample.zarr` | variable=tasmax, bidx=1, rescale=250,320, colormap=viridis |
| Vector | `geo.sg7_vector_test_cutlines_ord1` | MultiPolygon, 1401+ features |
| STAC | `sg-raster-test-dctest` collection | item: sg-raster-test-dctest-v1, assets: [data, thumbnail] |

### Tile Coordinates for Testing

Derive tile coordinates from test data bounds. Example for COG (DC area, bounds [-77.03, 38.91, -77.01, 38.93]):

| Zoom | x | y | Coverage |
|------|---|---|----------|
| 10 | 292 | 391 | Regional context |
| 12 | 1170 | 1565 | Neighborhood level |
| 14 | 4686 | 6262 | Street level |

For Zarr (global, bounds [-181.25, -91.25, 178.75, 91.25]):

| Zoom | x | y | Coverage |
|------|---|---|----------|
| 0 | 0 | 0 | Full globe |
| 2 | 2 | 1 | Quadrant |
| 4 | 8 | 5 | Continental |

Vector tile coordinates should be derived from the collection's tilejson bounds at runtime.
