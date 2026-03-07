# SIEGE Report — Run 2

**Date**: 2026-03-07
**Target**: https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net
**Image**: rmhtitiler:pgstac2-test (titiler-pgstac:2.1.0)
**Version**: 0.9.2.6
**Pipeline**: SIEGE (Tile Server Smoke Test)
**Purpose**: Post-upgrade verification — titiler-pgstac 1.9.0 → 2.1.0

---

## Endpoint Health

| Service | Endpoint | Status | Latency |
|---------|----------|--------|---------|
| COG | /cog/info | 200 | 687ms |
| COG | /cog/tilejson | 200 | 619ms |
| COG | /cog/statistics | 200 | 1114ms |
| COG | /cog/bounds | 404 (removed) | 290ms |
| COG | /cog/preview.png | 200 | 506ms |
| Xarray | /xarray/variables | 200 | 611ms |
| Xarray | /xarray/info | 200 | 393ms |
| Xarray | /xarray/tilejson | 200 | 603ms |
| Xarray | /xarray/bounds | 404 (removed) | 252ms |
| Vector | /vector/collections | 200 | 331ms |
| Vector | /vector/collection | 200 | 180ms |
| Vector | /vector/items | 200 | 276ms |
| Vector | /vector/tilejson | 200 | 232ms |
| STAC | /stac/collections | 200 | 305ms |
| STAC | /stac/collection | 200 | 308ms |
| STAC | /stac/items | 200 | 387ms |
| STAC | /stac/search | 200 | 228ms |
| Health | /health | 200 | 315ms |
| Health | /livez | 200 | 145ms |
| Health | /readyz | 200 | 166ms |

**Summary**: 18/20 HTTP 200, 2/20 HTTP 404 (both expected route removals in titiler-core 1.2.0). Active routes: 18/18 = 100%.

**Assessment**: HEALTHY

---

## Service Results

| Service | Steps | Pass | Fail | Unexpected |
|---------|-------|------|------|------------|
| Sentinel (Health) | 6 | 6 | 0 | 0 |
| Cartographer (Probes) | 20 | 18 | 0 | 2 (expected 404s) |
| COG (C1) | 4 | 4 | 0 | 0 |
| Zarr/Xarray (Z1) | 4 | 4 | 0 | 0 |
| Vector/TiPG (V1) | 4 | 4 | 0 | 0 |
| STAC (S1) | 5 | 5 | 0 | 0 |
| Cross-Service (X1) | 1 | 1 | 0 | 0 |
| **Totals** | **22** | **22** | **0** | **2** |

---

## Read Chain Details

**C1 — COG Read Chain**: PASS
- Bounds resolved: [-77.028398, 38.908233, -77.012914, 38.932173]
- Tile rendered: image/png, 117,634 bytes
- Statistics valid for b1, b2, b3 (band names now use "b" prefix per titiler-core 1.2.0)

**Z1 — Zarr Read Chain**: PASS
- Variables: ["tasmax"]
- Bounds: [-181.25, -91.25, 178.75, 91.25] (slight overshoot — expected CMIP6 grid cell padding)
- Grid: 144 x 73
- Tile rendered: image/png, 28,385 bytes

**V1 — Vector Read Chain**: PASS
- 27 collections discovered via live TiPG router
- 1,401 features in test collection
- Tile rendered: application/vnd.mapbox-vector-tile, 221,223 bytes

**S1 — STAC Read Chain**: PASS
- 7 STAC collections enumerated
- Item sg-raster-test-dctest-v1 has data and thumbnail assets
- Asset URL resolves correctly through /cog/info

**X1 — Cross-Service Read Chain**: PASS
- STAC collection extent matches COG bounds exactly

---

## Metadata Consistency

| Check | Result | Notes |
|-------|--------|-------|
| COG bounds consistency (info vs tilejson) | PASS | Exact match |
| Vector bounds consistency (collection vs tilejson) | PASS | Exact match |
| STAC extent vs COG bounds | PASS | Exact match |
| Tile content types | PASS | PNG for raster, MVT for vector |
| Response times (all under 5s) | PASS | Max observed ~2s (Vector MVT tile) |
| STAC-to-Tile asset resolution chain | PASS | Full round-trip verified |
| Zarr variable consistency (variables list vs info) | PASS | tasmax present in both |
| TiPG collection count discrepancy | INFO | /health reports 2 (startup count), /vector/collections returns 27 (live discovery). Pre-existing behavior, unrelated to upgrade. |

---

## Upgrade-Specific Findings

| Area | Change | Impact |
|------|--------|--------|
| Band naming | /cog/info and /cog/statistics now return "b1","b2","b3" instead of "1","2","3" | Breaking for clients that key on bare numeric band names. Expected titiler-core 1.2.0 behavior. |
| Removed routes | /cog/bounds and /xarray/bounds removed | Bounds data now available in /info responses. SIEGE probe config should be updated to remove these. |
| Build | No rio-tiler version conflict warnings during image build | Primary motivation for upgrade resolved. |
| Python runtime | 3.14.3 (upgraded from 3.12.x in previous base image) | No functional regressions observed. |
| Non-root base image | titiler-pgstac:2.1.0 runs as non-root user | Dockerfile updated with `USER root` for pip install and mkdir. |

---

## Findings

1. **[EXPECTED / LOW]** `/cog/bounds` and `/xarray/bounds` return HTTP 404. These routes were removed in titiler-core 1.2.0. Bounds are now included in the `/info` response body. No action required on the server; SIEGE probe config should be updated to retire these two checks.

2. **[EXPECTED / LOW]** Band names in `/cog/info` and `/cog/statistics` changed from bare integers ("1", "2", "3") to "b"-prefixed strings ("b1", "b2", "b3"). This is a titiler-core 1.2.0 behavior change. Any downstream client code or ETL pipelines that key on band names by exact string should be audited and updated.

3. **[INFO / NONE]** Zarr bounds [-181.25, -91.25, 178.75, 91.25] slightly exceed the WGS84 envelope. This is normal for CMIP6 data with 2.5-degree grid cell half-width padding applied. No action required.

4. **[INFO / NONE]** `/health` reports 2 TiPG collections_discovered while `/vector/collections` returns 27. This is pre-existing behavior: the health endpoint counts tables found at startup, while TiPG's live router enumerates all tables and views dynamically at request time. Unrelated to this upgrade.

5. **[RESOLVED]** The rio-tiler version conflict that motivated this upgrade produced no warnings during the ACR build of rmhtitiler:pgstac2-test. The conflict is resolved by the titiler-pgstac 2.1.0 dependency tree.

---

## Verdict

**PASS**

All 6 services healthy. All 22 read-chain steps passed. The 2 HTTP 404 responses are expected and documented route removals in titiler-core 1.2.0, not regressions. The primary motivation for the upgrade (rio-tiler version conflict) is resolved. No blocking issues found.

**Recommended next steps:**
1. Update SIEGE probe config to remove `/cog/bounds` and `/xarray/bounds` checks.
2. Audit any client code or ETL pipelines that reference band names as bare integers ("1", "2", "3") and update to "b1", "b2", "b3".
3. Merge `upgrade/pgstac-2.1` → `master`, bump version to v0.10.0.0, build and deploy final tagged image.
