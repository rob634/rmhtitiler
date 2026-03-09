# TiPG bbox ST_Transform Ambiguity with postgis_raster

**Status:** Workaround applied (dropped `postgis_raster`). Upstream issue to be filed at `developmentseed/tipg`.

---

## Summary

TiPG 1.3.1 generates SQL for `?bbox=` filtering that calls `ST_Transform()` without explicit type casting on the geometry parameter. When PostgreSQL has both `postgis` and `postgis_raster` extensions installed, this causes an `AmbiguousFunctionError` because PostgreSQL cannot determine which `ST_Transform` overload to use.

This is a regression introduced in TiPG PR [#251](https://github.com/developmentseed/tipg/pull/251) (merged 2026-02-26, released in 1.3.1), which added `ST_Transform` to bbox queries to fix non-EPSG:4326 geometry filtering.

---

## The Problem

### Function overloading

PostgreSQL's `postgis` extension registers:
```
ST_Transform(geometry, integer) -> geometry
```

PostgreSQL's `postgis_raster` extension registers:
```
ST_Transform(raster, integer) -> raster
```

### TiPG's bbox SQL (tipg/collections.py, `_where` method)

After PR #251, TiPG generates bbox queries like:

```python
# tipg/collections.py line ~570 (v1.3.1)
logic.Func(
    "ST_Intersects",
    logic.V(geometry_column.name),
    logic.Func(
        "ST_Transform",
        logic.S(bbox_to_wkt(bbox)),    # <-- type is "unknown" at plan time
        logic.Func("ST_SRID", logic.V(geometry_column.name)),
    ),
)
```

Which produces SQL like:

```sql
SELECT * FROM geo.my_table
WHERE ST_Intersects(
    geom,
    ST_Transform(
        'SRID=4326;POLYGON((-120 10, -85 10, -85 35, -120 35, -120 10))',
        ST_SRID(geom)
    )
)
```

### Why it fails

The WKT string `'SRID=4326;POLYGON(...)'` is passed as a text literal. PostgreSQL can implicitly cast text to either `geometry` or `raster`. With both casts available, the planner sees:

```
ST_Transform(unknown, integer)
```

Two candidate functions match:
1. `ST_Transform(geometry, integer)` — requires `unknown -> geometry` cast
2. `ST_Transform(raster, integer)` — requires `unknown -> raster` cast

Neither is a "better" match, so PostgreSQL throws:

```
ERROR: function st_transform(unknown, integer) is not unique
HINT: Could not choose a best candidate function. You might need to add explicit type casts.
```

### Before PR #251

The old TiPG code (pre-1.3.1) used plain `ST_Intersects(bbox_wkt, geom)` without `ST_Transform`. The bbox WKT was passed to `ST_Intersects` which only has geometry overloads, so the implicit cast was unambiguous. PR #251 wrapped the bbox in `ST_Transform()` to handle non-EPSG:4326 geometries, inadvertently introducing the ambiguity.

---

## The Fix (upstream)

Add an explicit `::geometry` cast to the bbox WKT in `tipg/collections.py`:

```python
# Current (broken with postgis_raster):
logic.Func(
    "ST_Transform",
    logic.S(bbox_to_wkt(bbox)),
    logic.Func("ST_SRID", logic.V(geometry_column.name)),
)

# Fixed:
logic.Func(
    "ST_Transform",
    logic.Cast(logic.S(bbox_to_wkt(bbox)), "geometry"),  # explicit cast
    logic.Func("ST_SRID", logic.V(geometry_column.name)),
)
```

Or equivalently in raw SQL:

```sql
-- Current (ambiguous):
ST_Transform('SRID=4326;POLYGON(...)', ST_SRID(geom))

-- Fixed (unambiguous):
ST_Transform('SRID=4326;POLYGON(...)'::geometry, ST_SRID(geom))
```

This resolves the overload unambiguously regardless of what extensions are installed.

---

## Our Workaround

Dropped the `postgis_raster` extension from Azure PostgreSQL Flexible Server:

```sql
DROP EXTENSION postgis_raster CASCADE;
```

This is safe for our deployment because:
- We serve raster tiles through TiTiler/GDAL (COG via `/vsiaz/`), not PostGIS raster
- No application code references any PostGIS raster functions
- The only codebase reference to `postgis_raster` is a diagnostic query that *lists* installed extensions

---

## Environment

| Component | Version |
|-----------|---------|
| TiPG | 1.3.1 |
| PostgreSQL | Azure Flexible Server |
| PostGIS | 3.5.2 |
| postgis_raster | 3.5.2 (was installed, now dropped) |
| postgis_topology | 3.5.2 (still installed, no conflict) |

---

## Reproduction

Requires a PostgreSQL database with both `postgis` and `postgis_raster` extensions:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;

-- This fails:
SELECT ST_Transform('SRID=4326;POINT(0 0)', 3857);
-- ERROR: function st_transform(unknown, integer) is not unique

-- This works:
SELECT ST_Transform('SRID=4326;POINT(0 0)'::geometry, 3857);
-- Returns geometry in EPSG:3857
```

Then query any TiPG collection with `?bbox=`:

```bash
curl "https://your-tipg-server/collections/your_collection/items?bbox=-120,10,-85,35"
# Returns 500: AmbiguousFunctionError
```

---

## GitHub Issue Template

**Title:** `bbox filter fails with AmbiguousFunctionError when postgis_raster extension is installed`

**Labels:** `bug`

**Body:**

> ### Description
>
> The bbox filter added in #251 calls `ST_Transform(bbox_wkt, ST_SRID(geom))` where `bbox_wkt` is a text literal. When PostgreSQL has both `postgis` and `postgis_raster` extensions installed, the implicit cast from text is ambiguous — PostgreSQL cannot choose between `ST_Transform(geometry, integer)` and `ST_Transform(raster, integer)`.
>
> ### Error
>
> ```
> function st_transform(unknown, integer) is not unique
> HINT: Could not choose a best candidate function. You might need to add explicit type casts.
> ```
>
> ### Environment
>
> - tipg 1.3.1
> - PostgreSQL (Azure Flexible Server)
> - PostGIS 3.5.2 + postgis_raster 3.5.2
>
> ### Reproduction
>
> Any `?bbox=` query on any collection when `postgis_raster` is installed.
>
> ### Suggested Fix
>
> Add explicit `::geometry` cast to the bbox WKT in `tipg/collections.py` `_where()` method (~line 570):
>
> ```python
> logic.Func(
>     "ST_Transform",
>     logic.Cast(logic.S(bbox_to_wkt(bbox)), "geometry"),
>     logic.Func("ST_SRID", logic.V(geometry_column.name)),
> )
> ```
