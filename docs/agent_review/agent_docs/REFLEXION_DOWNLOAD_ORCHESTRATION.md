# Reflexion Agent #1: Download Orchestration

**Date**: 28 FEB 2026
**Pipeline**: Reflexion Agent (R → F → P → J)
**Scope**: `services/download.py` + `routers/download.py` + `services/serializers.py` (1,018 lines)
**Chained from**: Greenfield Run 1 (V findings C2, C3, C13)

---

## EXECUTIVE SUMMARY

Agent R independently confirmed both structural bugs from V's Greenfield analysis (semaphore timing, unreachable exception handlers) and discovered 4 additional issues: statement_timeout pool leaking, CSV column heterogeneity, database connection held for entire stream duration without concurrency protection, and per-request fallback semaphore. Agent F enumerated 14 fault scenarios (3 CRITICAL, 5 HIGH, 4 MEDIUM, 2 LOW). Agent P wrote 9 surgical patches targeting 11 faults (Patch 1 addresses F-1, F-2, and partially F-12). Agent J approved all 9: 7 as-written, 2 with modifications.

---

## TOKEN USAGE

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| R | Reverse Engineer | ~119,034 | 6m 47s |
| F | Fault Injector | 53,694 | 2m 19s |
| P | Patch Author | 56,577 | 2m 50s |
| J | Judge | 45,895 | 2m 51s |
| **Total** | | **~275,200** | **~14m 47s** |

---

## PIPELINE RESULTS

### Agent R — Key Insights

R independently identified (with no external context):
- **BRITTLE #12**: Semaphore released before streaming completes (matches V-C2)
- **BRITTLE #13**: try/except asyncpg unreachable during streaming (matches V-C3)
- **BRITTLE #14**: CSV header from first feature only — heterogeneous data loses columns
- **BRITTLE #15**: Database connection held for entire streaming duration without concurrency protection
- **FRAGILE #7**: statement_timeout without LOCAL leaks to connection pool (new finding)
- **FRAGILE #9**: Token expiry during long streams (_BearerTokenCredential fake expiry)
- **FRAGILE #11**: DNS fail-open bypasses SSRF protection (matches V-C5)

R correctly inferred the subsystem's purpose as a "data download proxy" with defense-in-depth security.

### Agent F — Fault Scenarios

| # | Fault | Severity | Likelihood | Patched? |
|---|-------|----------|------------|----------|
| F-1 | Semaphore released before streaming | CRITICAL | HIGH | **YES** (Patch 1) |
| F-2 | DB pool exhaustion from uncapped streams | CRITICAL | MEDIUM | **YES** (via Patch 1) |
| F-3 | DB exceptions uncatchable during streaming | CRITICAL | MEDIUM | **YES** (Patch 3) |
| F-4 | statement_timeout leaks to pool | HIGH | HIGH | **YES** (Patch 2) |
| F-5 | DNS failure bypasses SSRF | HIGH | LOW | **YES** (Patch 4) |
| F-6 | Token expiry during long blob streaming | HIGH | LOW | DEFERRED (Architectural) |
| F-7 | Retry-After int() crash on HTTP-date | MEDIUM | LOW | **YES** (Patch 5) |
| F-8 | CSV silently drops columns | MEDIUM | MEDIUM | **YES** (Patch 8, warning only) |
| F-9 | "download_complete" logged before streaming | MEDIUM | HIGH | **YES** (Patch 6) |
| F-10 | Fallback semaphore per-request | HIGH | LOW | **YES** (Patch 7) |
| F-11 | Raster crop buffers entire response in memory | HIGH | LOW | DEFERRED (Architectural) |
| F-12 | Client disconnect orphans DB connection | MEDIUM | MEDIUM | PARTIAL (via Patch 1 aclose) |
| F-13 | TOCTOU race on collection catalog | LOW | LOW | UNPATCHED (accepted risk) |
| F-14 | Tight semaphore timeout false rejections | LOW | MEDIUM | **YES** (Patch 9) |

### Agent J — Verdicts

| Patch | Fault | Verdict | Phase |
|-------|-------|---------|-------|
| Patch 1 | F-1, F-2, F-12 | APPROVE WITH MODIFICATIONS | Phase 2 (Careful) |
| Patch 2 | F-4 | APPROVE | Phase 2 (Careful) |
| Patch 3 | F-3 | APPROVE WITH MODIFICATIONS | Phase 2 (Careful) |
| Patch 4 | F-5 | APPROVE | Phase 2 (Careful) |
| Patch 5 | F-7 | APPROVE | Phase 1 (Quick Win) |
| Patch 6 | F-9 | APPROVE | Phase 1 (Quick Win) |
| Patch 7 | F-10 | APPROVE | Phase 1 (Quick Win) |
| Patch 8 | F-8 | APPROVE | Phase 1 (Quick Win) |
| Patch 9 | F-14 | APPROVE | Phase 1 (Quick Win) |

### J's Modifications Required

**Patch 1**: Must explicitly remove `semaphore.release()` from each router endpoint's `finally` block. Double-release would permanently corrupt semaphore count. Error path: release in except block before stream starts.

**Patch 3**: Catch only `asyncpg` exception types (not bare Exception). Log with `logger.error` not warning.

---

## IMPLEMENTATION PLAN

### Phase 1 — Quick Wins (no ordering dependencies)

1. Patch 5 (F-7): Retry-After int() crash fix
2. Patch 6 (F-9): Rename download_complete → download_started for streaming endpoints
3. Patch 9 (F-14): Increase semaphore timeout 10ms → 100ms
4. Patch 7 (F-10): Module-level fallback semaphore singleton
5. Patch 8 (F-8): CSV extra columns warning log

### Phase 2 — Careful Changes (ordering matters)

6. Patch 4 (F-5): DNS fail-closed
7. Patch 2 (F-4): Reset statement_timeout in finally
8. Patch 3 (F-3): Stream error wrapper (BEFORE Patch 1)
9. Patch 1 (F-1): Guarded stream wrapper (AFTER Patch 3, critical)

### Phase 3 — Architectural (design discussion)

- F-6: Token expiry mid-stream (credential lifecycle redesign)
- F-11: Raster crop memory buffering (ASGI streaming or temp file)
- F-12: Full client disconnect handling (verify asyncpg cursor cleanup)

---

## RESIDUAL RISKS

| # | Severity | Description | Recommended Action |
|---|----------|-------------|-------------------|
| F-6 | HIGH | Token expiry during long blob streams | Monitor `event: "token_low_ttl"`. Existing 260s TTL check provides 4.3min buffer. |
| F-11 | HIGH | Raster crop memory buffering | Monitor `size_bytes` in raster crop logs. Alert on >50MB. Consider tightening bbox area limit. |
| F-13 | LOW | TOCTOU race on collection catalog | Accepted risk. Existing `vector_query_table_not_found` log covers this. |

---

## MONITORING RECOMMENDATIONS

1. **Semaphore utilization**: Instrument `_guarded_stream` with active-stream count. Watch for approaching `download_max_concurrent`.
2. **Stream duration histogram**: Timer in `_guarded_stream` from entry to finally. Compare with pre-patch handler times.
3. **DB timeout reset failures**: Alert on failures in Patch 2's reset-in-finally.
4. **Stream error events**: Alert on `event: "stream_db_error"` from Patch 3.
5. **DNS resolution failures**: Alert on "DNS resolution failed" after Patch 4.
6. **False rejection rate**: Monitor "Download capacity exceeded" events pre/post Patch 9.
7. **CSV column mismatch**: Monitor `event: "serialize_csv_extra_columns"` from Patch 8.

---

## KEY INSIGHT

The semaphore-based concurrency control has been fundamentally broken since the code was written. The `finally: semaphore.release()` pattern fires when `StreamingResponse(...)` is constructed as a Python object, not when the HTTP response body finishes streaming to the client. Every streaming download endpoint immediately releases its slot, making `download_max_concurrent` a no-op. The database pool (not the semaphore) has been the only real concurrency gate — and pool exhaustion under load would cascade as 503s on TiPG and health endpoints rather than graceful rejection. Patch 1 is the highest-priority fix because without it, all other concurrency-related patches operate on a mechanism that provides no protection.
