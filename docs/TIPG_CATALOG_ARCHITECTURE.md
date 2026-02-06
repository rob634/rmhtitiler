# TiPG Catalog Architecture & Multi-Instance Behavior

**Created:** February 2026
**Status:** Investigation Complete
**Related Issues:** Table visibility inconsistency after ETL webhook refresh

---

## Table of Contents

1. [Overview](#overview)
2. [How TiPG Catalog Works](#how-tipg-catalog-works)
3. [The Multi-Instance Problem](#the-multi-instance-problem)
4. [Investigation Evidence](#investigation-evidence)
5. [Solutions](#solutions)
6. [Recommendations](#recommendations)
7. [Known Upstream Issues](#known-upstream-issues)

---

## Overview

TiPG (TiTiler for PostGIS) provides OGC Features API and Vector Tiles for PostGIS tables. It maintains an **in-memory catalog** of available tables, which creates challenges in multi-instance deployments like Azure App Service Environment (ASE).

### Key Behavior

- TiPG discovers tables at startup and caches metadata in `app.state.collection_catalog`
- Each application instance maintains its **own independent catalog**
- The `/admin/refresh-collections` webhook only refreshes the **single instance that receives the request**
- Load balancers distribute requests randomly across instances

---

## How TiPG Catalog Works

### Startup Initialization

```
App Start
    │
    ▼
register_collection_catalog()
    │
    ├── Connect to PostgreSQL
    ├── Query pg_temp.tipg_* functions for table metadata
    ├── Discover: schema, columns, primary key, geometry column, bounds
    └── Store in app.state.collection_catalog (in-memory dict)
```

### Catalog Contents

The catalog stores rich metadata for each table:

```python
app.state.collection_catalog = {
    "geo.my_table": Collection(
        id="geo.my_table",
        table="my_table",
        schema="geo",
        geometry_column="geom",
        geometry_type="POLYGON",
        srid=4326,
        bounds=[-180, -90, 180, 90],
        properties=[...],  # Column definitions
        id_column="id",    # Primary key
    ),
    ...
}
```

### Endpoint Behavior

| Endpoint | Catalog Usage |
|----------|---------------|
| `GET /vector/collections` | Lists all keys from `collection_catalog` |
| `GET /vector/collections/{id}` | Looks up `id` in catalog, returns metadata |
| `GET /vector/collections/{id}/items` | **Requires full catalog entry** - uses column info, pk, geometry to build SQL |
| `GET /vector/collections/{id}/tiles/{z}/{x}/{y}` | **Requires full catalog entry** - needs geometry column for MVT generation |

### Why `/collections/{id}` Works But `/items` Fails

The `/collections/{id}` endpoint can return partial metadata even if the catalog entry is incomplete or missing (it may dynamically check the database). However, `/items` requires the full catalog entry to:

1. Know which columns to SELECT
2. Know the primary key for feature IDs
3. Know the geometry column for GeoJSON generation
4. Build properly-quoted SQL queries

---

## The Multi-Instance Problem

### Architecture Diagram

```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    │  (Azure ASE)    │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
            ▼                ▼                ▼
    ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
    │  Instance A   │ │  Instance B   │ │  Instance C   │
    │               │ │               │ │               │
    │ catalog: {    │ │ catalog: {    │ │ catalog: {    │
    │   table1,     │ │   table1,     │ │   table1,     │
    │   table2      │ │   table2,     │ │   table2,     │
    │ }             │ │   table3      │ │   table3,     │
    │               │ │ }             │ │   table4  ✓   │
    │ (stale)       │ │ (partial)     │ │ (refreshed)   │
    └───────────────┘ └───────────────┘ └───────────────┘
            │                │                │
            └────────────────┴────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │    PostgreSQL   │
                    │  (has table4)   │
                    └─────────────────┘
```

### Problem Sequence

1. **ETL creates new table** `geo.table4` in PostgreSQL
2. **ETL calls webhook** `POST /admin/refresh-collections`
3. **Load balancer routes** request to Instance C
4. **Instance C refreshes** - now sees `table4`
5. **Instances A & B unchanged** - still have stale catalogs
6. **User requests** `GET /vector/collections/geo.table4/items`
7. **Load balancer routes** to Instance A (randomly)
8. **Instance A returns error** - "Table/Function not found"
9. **User retries** - might hit Instance C and succeed, or hit A/B and fail

### Symptoms

- `/vector/collections` returns different counts on each request
- `/vector/collections/{id}/items` intermittently fails with "Table/Function not found"
- App restart "fixes" the issue (all instances reinitialize)
- Webhook returns success but table still not visible

---

## Investigation Evidence

### Test: Multiple Requests Show Different Results

```bash
# 6 consecutive requests to /vector/collections
Request 1: 3 collections
Request 2: 4 collections  ← Has new table
Request 3: 4 collections  ← Has new table
Request 4: 2 collections  ← Stale
Request 5: 3 collections
Request 6: 3 collections
```

### Observed Instance States

| Instance State | Collections Visible |
|----------------|---------------------|
| Stale | `geo.t_11_v8_testing_v10`, `geo.t_3cutlines_v8_testing_v10` |
| Partial | Above + `geo.t_1neweleven_v8_testing_v10` |
| Refreshed | Above + `geo.t_19cutlines_v8_testing_v10` (new) |

### Error Message

```json
{
  "detail": "Table/Function 'geo.t_19cutlines_v8_testing_v10' not found."
}
```

This error comes from TiPG when the requested collection ID is not in `app.state.collection_catalog`.

---

## Solutions

### Option 1: Catalog TTL Auto-Refresh (Quick Fix)

Enable automatic periodic catalog refresh on all instances.

**Configuration:**
```bash
TIPG_CATALOG_TTL_ENABLED=true
TIPG_CATALOG_TTL=60  # seconds
```

**Pros:**
- Already implemented in code
- No code changes needed
- All instances eventually sync

**Cons:**
- Up to TTL seconds delay before new tables visible
- Unnecessary database queries when no changes
- Doesn't guarantee immediate consistency

### Option 2: Multiple Webhook Calls

Call the refresh webhook multiple times to hit different instances.

**Implementation:**
```python
# In ETL handler
for _ in range(instance_count * 2):  # Probabilistic coverage
    await client.refresh_tipg_collections()
    await asyncio.sleep(0.5)
```

**Pros:**
- Works with current architecture
- Higher probability of hitting all instances

**Cons:**
- Hacky, not guaranteed
- Wastes resources
- Doesn't scale with instance count

### Option 3: ARR Affinity Instance Targeting

Use Azure ARR affinity cookies to target specific instances.

**Pros:**
- Can guarantee hitting each instance

**Cons:**
- Requires knowing instance IDs
- Complex implementation
- Tightly coupled to Azure

### Option 4: Shared Catalog State (Best Long-Term)

Store catalog in shared storage instead of in-memory.

**Options:**
- **Redis:** Fast, supports pub/sub for invalidation
- **PostgreSQL table:** Already have connection, transactional
- **Azure Cache:** Managed Redis

**Architecture:**
```
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  Instance A   │ │  Instance B   │ │  Instance C   │
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │                 │                 │
        └─────────────────┴─────────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │  Shared Cache   │
                 │  (Redis/PG)     │
                 │                 │
                 │  catalog: {     │
                 │    table1,      │
                 │    table2,      │
                 │    table3,      │
                 │    table4       │
                 │  }              │
                 └─────────────────┘
```

**Pros:**
- True consistency across all instances
- Single source of truth
- Webhook refreshes once, all instances see it

**Cons:**
- Requires TiPG code changes (upstream or fork)
- Additional infrastructure (Redis)
- More complex deployment

### Option 5: Single Instance Mode

Scale to single instance to avoid the problem entirely.

**Pros:**
- Simple, guaranteed consistency

**Cons:**
- No high availability
- No horizontal scaling
- Single point of failure

---

## Recommendations

### Immediate (Production Workaround)

Enable TTL-based refresh with a reasonable interval:

```bash
# Azure App Service Configuration
TIPG_CATALOG_TTL_ENABLED=true
TIPG_CATALOG_TTL=60
```

This ensures all instances refresh their catalogs within 60 seconds, providing eventual consistency.

### Short-Term

1. Update ETL to call refresh webhook 3-5 times with small delays
2. Add retry logic in clients that hit "Table not found" errors
3. Document the eventual consistency behavior for users

### Long-Term

Implement shared catalog state using PostgreSQL:

1. Create `tipg.catalog_cache` table
2. Store serialized catalog entries
3. Modify TiPG initialization to read from table
4. Webhook updates table, instances poll or use LISTEN/NOTIFY

---

## Known Upstream Issues

### PostgreSQL Identifier Quoting (TiPG #195, #232)

Tables with names starting with numbers cause SQL syntax errors:

```
Error: "trailing junk after numeric literal at or near '.11_v8_testing'"
```

**Cause:** TiPG's `buildpg` library doesn't properly quote identifiers.

**Workaround:** Ensure table names start with a letter (enforce in ETL pipeline with `t_` prefix).

### buildpg Library Unmaintained

The `buildpg` library used by TiPG for SQL building is not actively maintained. Identifier quoting issues are unlikely to be fixed upstream.

---

## Related Files

| File | Purpose |
|------|---------|
| `geotiler/routers/vector.py` | TiPG initialization, `refresh_tipg_pool()` |
| `geotiler/routers/admin.py` | `/admin/refresh-collections` webhook |
| `geotiler/config.py` | `tipg_catalog_ttl_enabled`, `tipg_catalog_ttl` settings |

---

## Testing the Issue

### Verify Multi-Instance Inconsistency

```bash
# Run multiple times, observe different collection counts
for i in {1..10}; do
  curl -s "https://{your-app}/vector/collections" | jq '.collections | length'
  sleep 0.5
done
```

### Verify Specific Table Visibility

```bash
# Check if new table appears (run multiple times)
curl -s "https://{your-app}/vector/collections" | jq -r '.collections[].id' | grep "your_new_table"
```

### Test Items Endpoint

```bash
# May succeed or fail depending on which instance handles request
curl -s "https://{your-app}/vector/collections/geo.your_new_table/items?limit=1"
```
