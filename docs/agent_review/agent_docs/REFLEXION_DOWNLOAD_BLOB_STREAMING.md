# Reflexion Agent #3: Blob Streaming + TiTiler Client

**Date**: 28 FEB 2026
**Pipeline**: Reflexion Agent (R → F → P → J)
**Scope**: `services/blob_stream.py` + `services/download_clients.py` (394 lines)
**Chained from**: Greenfield Run 1 (V findings C9, C11, C12)

---

## EXECUTIVE SUMMARY

Agent R independently identified the dead `_chunk_size` configuration, `_BearerTokenCredential` fragility, async generator cleanup dependency, and full-response buffering in TiTiler crop — all without external context. Agent F enumerated 12 fault scenarios (1 CRITICAL, 3 HIGH, 5 MEDIUM, 3 LOW). Agent P wrote 6 surgical patches targeting 6 faults and correctly deferred 7 as Architectural. Agent J approved all 6: 5 as-written, 1 with modifications (extend error.message fix to download.py).

---

## TOKEN USAGE

| Agent | Role | Tokens | Duration |
|-------|------|--------|----------|
| R | Reverse Engineer | ~39,133 | ~1m 40s |
| F | Fault Injector | 56,763 | ~2m 54s |
| P | Patch Author | 38,951 | ~2m 29s |
| J | Judge | 53,387 | ~3m 34s |
| **Total** | | **~188,234** | **~10m 37s** |

---

## PIPELINE RESULTS

### Agent R — Key Insights

R independently identified (with no external context):

- **BRITTLE**: Hardcoded `/cog/bbox/` endpoint path — breaks if TiTiler changes URL structure
- **BRITTLE**: `_chunk_size` stored from config but NEVER passed to `download_blob()` — dead configuration
- **FRAGILE**: `_BearerTokenCredential` duck-types Azure SDK TokenCredential with far-future expiry (year 2286) — SDK never refreshes token
- **FRAGILE**: `stream_blob()` async generator uses `async with` — cleanup on early termination depends on Python's async generator finalization
- **FRAGILE**: Token validity not checked by either client — trusts caller
- **FRAGILE**: TiTiler `crop()` buffers entire response (`response.content`) — no size guard at this layer

R correctly inferred both components as parts of a "geospatial data proxy" mediating between browser users and backend storage/processing.

### Agent F — Fault Scenarios

| # | Fault | Severity | Likelihood | Patched? |
|---|-------|----------|------------|----------|
| FAULT-01 | Token expires mid-stream, partial file | HIGH | MEDIUM | DEFERRED (Architectural) |
| FAULT-02 | Async generator leak on client disconnect | HIGH | MEDIUM | DEFERRED (Architectural) |
| FAULT-03 | int(retry_after) crash on HTTP-date | MEDIUM | LOW | **YES** (Patch 6) |
| FAULT-04 | _chunk_size dead config | MEDIUM | HIGH | **YES** (Patch 3) |
| FAULT-05 | TiTiler crop OOM on large bboxes | CRITICAL | LOW | DEFERRED (Architectural) |
| FAULT-06 | TOCTOU between size check and stream | MEDIUM | LOW | **YES** (Patch 4+5) |
| FAULT-07 | Container recycling → partial download | MEDIUM | MEDIUM | DEFERRED (Infrastructure) |
| FAULT-08 | New BlobServiceClient per request | LOW | HIGH | DEFERRED (Architectural) |
| FAULT-09 | error.message may not exist | LOW | LOW | **YES** (Patch 1) |
| FAULT-10 | ASGI timeout races Gunicorn timeout | HIGH | LOW | DEFERRED (Configuration) |
| FAULT-11 | headers=None crashes .get() on 429 | LOW | LOW | **YES** (Patch 2) |
| FAULT-12 | Mid-stream errors bypass HTTP responses | MEDIUM | MEDIUM | DEFERRED (HTTP limitation) |

### Agent J — Verdicts

| Patch | Fault | Verdict | Phase |
|-------|-------|---------|-------|
| Patch 1 | FAULT-09 | APPROVE WITH MODIFICATIONS | Phase 1 (Quick Win) |
| Patch 2 | FAULT-11 | APPROVE | Phase 1 (Quick Win) |
| Patch 3 | FAULT-04 | APPROVE | Phase 2 (Careful) |
| Patch 4 | FAULT-06 | APPROVE | Phase 2 (Careful) |
| Patch 5 | FAULT-06 | APPROVE (requires Patch 4) | Phase 2 (Careful) |
| Patch 6 | FAULT-03 | APPROVE | Phase 1 (Quick Win) |

### J's Modifications Required

**Patch 1**: Must also apply the same `getattr(e, "message", None) or str(e)` pattern to `download.py` line 543 which has the same vulnerability:
```python
error_msg = getattr(e, "message", None) or str(e)
detail={"detail": f"Storage error: {error_msg}", "status": 502},
```

---

## IMPLEMENTATION PLAN

### Phase 1 — Quick Wins (no ordering dependencies)

1. Patch 1 (FAULT-09): Safe `error.message` access with `getattr` fallback in `blob_stream.py` + `download.py`
2. Patch 2 (FAULT-11): `or {}` fallback for None headers on 429 in `blob_stream.py`
3. Patch 6 (FAULT-03): `try/except` around `int(retry_after)` + `or {}` for headers in `download.py`

### Phase 2 — Careful Changes (ordering matters)

4. Patch 3 (FAULT-04): Pass `max_chunk_get_size` to BlobServiceClient (changes `@staticmethod` to instance method)
5. Patch 4 + 5 (FAULT-06): Etag-based TOCTOU mitigation (Patch 4 adds param to `stream_blob`, Patch 5 passes etag from caller — MUST apply together)

### Phase 3 — Architectural (design discussion)

- FAULT-01: Token expiry mid-stream (credential lifecycle redesign or chunked retry with range requests)
- FAULT-02: Async generator leak (Starlette disconnect behavior validation + explicit cleanup)
- FAULT-05: TiTiler crop OOM (per-resolution pixel budget or streaming crop response)
- FAULT-08: Connection pooling (singleton client with token rotation)
- FAULT-10: Timeout alignment (coordinated config between ASGI/httpx/Gunicorn/platform)

---

## PATCH DETAILS

### Patch 1 — Safe error.message access (FAULT-09)

**Location:** `blob_stream.py` — `_handle_http_error()` — line 227

**Before:**
```python
        else:
            logger.error(
                f"Blob storage error: {url}, status={status}, error={error.message}",
                extra={"event": "blob_error", "status": status},
            )
```

**After:**
```python
        else:
            error_msg = getattr(error, "message", None) or str(error)
            logger.error(
                f"Blob storage error: {url}, status={status}, error={error_msg}",
                extra={"event": "blob_error", "status": status},
            )
```

**J's modification — also apply to `download.py` line 543:**
```python
error_msg = getattr(e, "message", None) or str(e)
detail={"detail": f"Storage error: {error_msg}", "status": 502},
```

### Patch 2 — Headers None safety on 429 (FAULT-11)

**Location:** `blob_stream.py` — `_handle_http_error()` — line 220

**Before:**
```python
            retry_after = getattr(error, "headers", {}).get("Retry-After", "10")
```

**After:**
```python
            retry_after = (getattr(error, "headers", None) or {}).get("Retry-After", "10")
```

### Patch 3 — Apply configured chunk_size (FAULT-04)

**Location:** `blob_stream.py` — `_create_client()` — lines 186-203

**Before:**
```python
    @staticmethod
    def _create_client(account_url: str, token: str) -> BlobServiceClient:
        return BlobServiceClient(
            account_url=account_url,
            credential=_BearerTokenCredential(token),
        )
```

**After:**
```python
    def _create_client(self, account_url: str, token: str) -> BlobServiceClient:
        return BlobServiceClient(
            account_url=account_url,
            credential=_BearerTokenCredential(token),
            max_chunk_get_size=self._chunk_size,
        )
```

### Patch 4 — Etag parameter for TOCTOU mitigation (FAULT-06)

**Location:** `blob_stream.py` — `stream_blob()` — lines 129-166

**Change:** Add `etag: Optional[str] = None` parameter. When provided, pass `etag` + `match_condition=MatchConditions.IfNotModified` to `download_blob()`.

### Patch 5 — Pass etag from caller (FAULT-06 companion)

**Location:** `download.py` — line 568

**Before:**
```python
    stream = blob_client.stream_blob(resolved.blob_url, token)
```

**After:**
```python
    stream = blob_client.stream_blob(resolved.blob_url, token, etag=props.get("etag"))
```

### Patch 6 — Retry-After int() crash fix (FAULT-03)

**Location:** `download.py` — line 538

**Before:**
```python
            elif status == 429:
                retry_after = getattr(e, "headers", {}).get("Retry-After", "10")
                raise HTTPException(
                    status_code=503,
                    detail={
                        "detail": "Storage throttled",
                        "status": 503,
                        "retry_after_seconds": int(retry_after),
                    },
                )
```

**After:**
```python
            elif status == 429:
                retry_after_raw = (getattr(e, "headers", None) or {}).get("Retry-After", "10")
                try:
                    retry_after_sec = int(retry_after_raw)
                except (ValueError, TypeError):
                    retry_after_sec = 10
                raise HTTPException(
                    status_code=503,
                    detail={
                        "detail": "Storage throttled",
                        "status": 503,
                        "retry_after_seconds": retry_after_sec,
                    },
                )
```

---

## RESIDUAL RISKS

| # | Severity | Description | Recommended Action |
|---|----------|-------------|-------------------|
| FAULT-01 | HIGH | Token expiry during long blob streams | Monitor `token_low_ttl` events. 260s TTL check provides 4.3min buffer. Consider reducing `download_proxy_max_size_mb` for large files. |
| FAULT-02 | HIGH | Async generator connection leak on disconnect | Monitor connection counts and memory usage. Python GC will eventually clean up, but under load this could exhaust connections. |
| FAULT-05 | CRITICAL | TiTiler crop OOM on high-res COGs | Monitor container memory. 25 sq deg area limit is coarse proxy for pixel count. Alert on >50MB crop responses. |
| FAULT-07 | MEDIUM | Container recycling → partial download | Content-Length header allows client-side truncation detection. Monitor during deployments. |
| FAULT-10 | HIGH | ASGI/Gunicorn timeout race | Monitor for Gunicorn worker kills without corresponding app-level timeout logs. |
| FAULT-12 | MEDIUM | Mid-stream errors invisible to client | Track Content-Length vs actual bytes sent discrepancies. |

---

## MONITORING RECOMMENDATIONS

1. **`blob_error` with empty error field**: After Patch 1, `error_msg` should never be empty. Alert if null/empty.
2. **`blob_throttled` frequency**: After Patch 2, 429 handling is robust. Alert if >5/minute.
3. **Download latency by size bucket**: Track P95 for 0-10MB, 10-100MB, 100-500MB. Reveals chunk size (Patch 3) effectiveness.
4. **412 Precondition Failed rate**: After Patch 4+5, etag mismatches produce 412→502. Should be near zero.
5. **`download_timeout_sec` proximity**: Alert if P99 download duration exceeds 180s (approaching 200s timeout).
6. **`token_low_ttl` events**: Any occurrence means download started with potentially expiring token.

---

## KEY INSIGHT

The codebase has two parallel error-handling paths for the same Azure Blob Storage errors — one in `blob_stream.py` (`_handle_http_error`, which only logs) and one in `download.py` (`handle_asset_download`, which maps errors to HTTP responses). These two paths have independently drifted: `download.py` has `e.message` directly (FAULT-09), `getattr(e, "headers", {})` (FAULT-11), and `int(retry_after)` (FAULT-03) — all vulnerable. The blob_stream.py `_handle_http_error` is called first (for logging), then the same exception is re-raised and caught again in `download.py` (for HTTP response mapping). This dual-catch architecture means every error-handling bug must be fixed in two places, and the two files can silently diverge. The six patches correctly identify the individual vulnerabilities, but the architectural lesson is clear: error categorization and response mapping should be consolidated into a single location to prevent future paired divergence.
