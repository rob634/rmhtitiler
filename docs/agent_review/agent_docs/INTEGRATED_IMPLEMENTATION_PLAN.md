# Integrated Implementation Plan — Download Subsystem Hardening

**Date**: 28 FEB 2026
**Source**: Reflexion Runs 2, 3, 4 (merged)
**Status**: **ALL PHASES APPLIED** (28 FEB 2026)
**Total faults identified**: 38 across 8 files
**Patches approved**: 22 (7 from Run 3 + 13 from Runs 2/4)
**Patches applied**: 20/22 (remaining 2 were duplicates removed during deduplication)
**Files modified**: `blob_stream.py`, `download.py`, `routers/download.py`, `serializers.py`

---

## DEDUPLICATION LOG

Before merging, the following overlaps were resolved:

| Patch | Status | Notes |
|-------|--------|-------|
| R2-P2 (statement_timeout reset) | **ALREADY APPLIED** | Run 3 patched `vector_query.py` with RESET in finally blocks |
| R2-P4 (DNS fail-closed) | **ALREADY APPLIED** | Run 3 patched `asset_resolver.py` — raise ValueError instead of logging |
| R2-P5 + R4-P6 (Retry-After int() crash) | **DEDUPLICATED** | Same fault, same location (`download.py:538`). Apply once as Step 4 |
| R4-P1 extension | **MERGED** | J required extending R4-P1 to `download.py:543`. Included as Step 3 |

**Net result**: 15 approved patches from Runs 2+4 → 13 unique patches after removing 2 already-applied duplicates.

---

## IMPLEMENTATION STEPS

### Phase 1 — Error Handling Hardening (7 steps, no ordering dependencies) — APPLIED

Each patch is an independent error-path fix. Cannot affect happy-path behavior. Safe to apply in any order.

---

#### Step 1: Safe `error.message` access in blob_stream.py

**Origin**: Run 4 Patch 1 (FAULT-09)
**File**: `geotiler/services/blob_stream.py` — `_handle_http_error()` line 227
**Risk**: None

```python
# BEFORE
        else:
            logger.error(
                f"Blob storage error: {url}, status={status}, error={error.message}",
                extra={"event": "blob_error", "status": status},
            )

# AFTER
        else:
            error_msg = getattr(error, "message", None) or str(error)
            logger.error(
                f"Blob storage error: {url}, status={status}, error={error_msg}",
                extra={"event": "blob_error", "status": status},
            )
```

---

#### Step 2: Headers None safety on 429 in blob_stream.py

**Origin**: Run 4 Patch 2 (FAULT-11)
**File**: `geotiler/services/blob_stream.py` — `_handle_http_error()` line 220
**Risk**: None

```python
# BEFORE
            retry_after = getattr(error, "headers", {}).get("Retry-After", "10")

# AFTER
            retry_after = (getattr(error, "headers", None) or {}).get("Retry-After", "10")
```

---

#### Step 3: Safe `e.message` access in download.py

**Origin**: Run 4 Patch 1, J's required modification
**File**: `geotiler/services/download.py` — `handle_asset_download()` line 543
**Risk**: None

```python
# BEFORE
        raise HTTPException(
            status_code=502,
            detail={"detail": f"Storage error: {e.message}", "status": 502},
        )

# AFTER
        error_msg = getattr(e, "message", None) or str(e)
        raise HTTPException(
            status_code=502,
            detail={"detail": f"Storage error: {error_msg}", "status": 502},
        )
```

---

#### Step 4: Retry-After int() crash + headers safety in download.py

**Origin**: Run 2 Patch 5 (F-7) + Run 4 Patch 6 (FAULT-03) — deduplicated
**File**: `geotiler/services/download.py` — `handle_asset_download()` lines 531-539
**Risk**: None

```python
# BEFORE
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

# AFTER
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

#### Step 5: Rename `download_complete` → `download_started` for streaming endpoints

**Origin**: Run 2 Patch 6 (F-9)
**File**: `geotiler/services/download.py` — lines 468 and 580
**Risk**: None (log event name only — monitoring dashboards may need updating)

Only rename for **streaming** endpoints where logging happens before the client receives data. The raster crop endpoint (line 325) is correctly named `download_complete` because the crop is fully buffered before the response.

```python
# download.py line 468 (vector subset) — RENAME
"event": "download_complete"  →  "event": "download_started"

# download.py line 580 (asset download) — RENAME
"event": "download_complete"  →  "event": "download_started"

# download.py line 325 (raster crop) — DO NOT CHANGE (buffered, genuinely complete)
```

---

#### Step 6: CSV extra columns warning log

**Origin**: Run 2 Patch 8 (F-8)
**File**: `geotiler/services/serializers.py` — `serialize_csv()` line 116
**Risk**: None

When a feature has keys not in the header (derived from first feature), log a warning so operators can detect heterogeneous schemas.

```python
# BEFORE (in the async for feature loop, after header_written=True)
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
            writer.writerow(row)

# AFTER
            extra_keys = set(row.keys()) - set(fieldnames)
            if extra_keys:
                logger.warning(
                    f"CSV row has {len(extra_keys)} columns not in header: {sorted(extra_keys)[:5]}",
                    extra={"event": "serialize_csv_extra_columns", "extra_count": len(extra_keys)},
                )
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
            writer.writerow(row)
```

---

#### Step 7: Semaphore timeout 10ms → 100ms

**Origin**: Run 2 Patch 9 (F-14)
**File**: `geotiler/routers/download.py` — `_try_acquire_semaphore()` line 273
**Risk**: None (increases wait tolerance from 10ms to 100ms, reduces false rejections)

```python
# BEFORE
        await asyncio.wait_for(semaphore.acquire(), timeout=0.01)

# AFTER
        await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
```

---

### Phase 2 — Streaming Concurrency Fix (3 steps, ORDERED) — APPLIED

**This is the critical phase.** These patches fix the broken semaphore that makes `download_max_concurrent` a no-op. Applied in exact order.

**Implementation note**: An `acquired` flag was added to all 3 endpoints to prevent semaphore over-release when `_try_acquire_semaphore` returns False (503 capacity exceeded). The plan's `except HTTPException: semaphore.release()` would have corrupted the semaphore count without this guard.

---

#### Step 8: Module-level fallback semaphore singleton

**Origin**: Run 2 Patch 7 (F-10)
**File**: `geotiler/routers/download.py` — `_get_semaphore()` lines 249-258
**Risk**: Low

The current code creates a new `asyncio.Semaphore(100)` on every request when `app.state.download_semaphore` is missing. This means the fallback provides zero concurrency control.

```python
# BEFORE
def _get_semaphore(request: Request) -> asyncio.Semaphore:
    semaphore = getattr(request.app.state, "download_semaphore", None)
    if semaphore is None:
        logger.warning(
            "Download semaphore not found on app.state, using fallback",
            extra={"event": "semaphore_fallback"},
        )
        return asyncio.Semaphore(100)
    return semaphore

# AFTER
_fallback_semaphore: asyncio.Semaphore | None = None

def _get_semaphore(request: Request) -> asyncio.Semaphore:
    global _fallback_semaphore
    semaphore = getattr(request.app.state, "download_semaphore", None)
    if semaphore is None:
        logger.warning(
            "Download semaphore not found on app.state, using fallback",
            extra={"event": "semaphore_fallback"},
        )
        if _fallback_semaphore is None:
            _fallback_semaphore = asyncio.Semaphore(100)
        return _fallback_semaphore
    return semaphore
```

---

#### Step 9: Stream error wrapper for DB exceptions

**Origin**: Run 2 Patch 3 (F-3), with J's modification (asyncpg-only, logger.error)
**File**: `geotiler/services/download.py` — new function + integration
**Risk**: Medium — wraps the streaming async generator, must preserve iteration semantics
**MUST BE APPLIED BEFORE STEP 10**

Add a wrapper that catches asyncpg exceptions during streaming iteration (which are unreachable by the router's try/except because generators are lazy):

```python
# NEW FUNCTION in download.py (after imports)
async def _wrap_stream_with_db_error_logging(
    stream: AsyncIterator[bytes],
    endpoint: str,
) -> AsyncIterator[bytes]:
    """Catch database errors during streaming iteration and log them."""
    import asyncpg as _asyncpg
    try:
        async for chunk in stream:
            yield chunk
    except (_asyncpg.PostgresError, _asyncpg.InterfaceError) as e:
        logger.error(
            f"Database error during stream: {type(e).__name__}: {e}",
            extra={"event": "stream_db_error", "endpoint": endpoint, "error_type": type(e).__name__},
        )
        raise

# INTEGRATION: Wrap the stream in handle_vector_subset before returning
# (in the serialize block, after stream = serialize_geojson/csv)
stream = _wrap_stream_with_db_error_logging(stream, endpoint="vector/subset")
```

---

#### Step 10: Guarded stream wrapper (THE SEMAPHORE FIX)

**Origin**: Run 2 Patch 1 (F-1, F-2, F-12), with J's modifications
**File**: `geotiler/routers/download.py` — ALL THREE endpoint functions
**Risk**: HIGH — this restructures the concurrency control for all download endpoints
**CRITICAL**: Must also remove old `semaphore.release()` from each endpoint's `finally` block

The core bug: `finally: semaphore.release()` runs when `StreamingResponse(...)` is constructed as a Python object, not when the HTTP body finishes streaming to the client. The semaphore slot is released immediately, making concurrency control a no-op.

The fix: Move semaphore release into the streaming generator itself, so it runs when iteration completes (or the client disconnects).

```python
# NEW FUNCTION in routers/download.py
async def _guarded_stream(
    stream: AsyncIterator[bytes],
    semaphore: asyncio.Semaphore,
    endpoint: str,
) -> AsyncIterator[bytes]:
    """
    Wrap a stream to hold the semaphore for the FULL duration of streaming,
    releasing only when iteration completes or the client disconnects.
    """
    t0 = time.monotonic()
    try:
        async for chunk in stream:
            yield chunk
    finally:
        semaphore.release()
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        logger.debug(
            f"Stream completed, semaphore released",
            extra={
                "event": "stream_complete",
                "endpoint": endpoint,
                "stream_ms": elapsed,
            },
        )

# EACH ENDPOINT CHANGES FROM:
    try:
        if not await _try_acquire_semaphore(semaphore):
            raise HTTPException(503, ...)
        try:
            result = await handle_xxx(...)
            logger.info(...)
            return StreamingResponse(result.stream, ...)
        finally:
            semaphore.release()      # ← REMOVE THIS
    except HTTPException:
        ...

# TO:
    try:
        if not await _try_acquire_semaphore(semaphore):
            raise HTTPException(503, ...)

        result = await handle_xxx(...)
        logger.info(...)

        guarded = _guarded_stream(result.stream, semaphore, endpoint="xxx")
        return StreamingResponse(guarded, ...)

    except HTTPException:
        # Semaphore was acquired but handler raised before stream started — release here
        semaphore.release()
        ...
        raise
```

**J's critical warning**: The old `finally: semaphore.release()` in each endpoint MUST be removed. If both the old `finally` release and the new `_guarded_stream` release run, the semaphore count is permanently corrupted (double-release). On error paths where the handler raises before the stream starts, the `except HTTPException` block releases instead.

---

### Phase 3 — Blob Stream Hardening (3 steps, Steps 12-13 ordered) — APPLIED

---

#### Step 11: Apply configured chunk_size to BlobServiceClient

**Origin**: Run 4 Patch 3 (FAULT-04)
**File**: `geotiler/services/blob_stream.py` — `_create_client()` lines 186-203
**Risk**: Low (default matches SDK default; only matters when operator tunes config)

```python
# BEFORE
    @staticmethod
    def _create_client(account_url: str, token: str) -> BlobServiceClient:
        ...
        return BlobServiceClient(
            account_url=account_url,
            credential=_BearerTokenCredential(token),
        )

# AFTER
    def _create_client(self, account_url: str, token: str) -> BlobServiceClient:
        ...
        return BlobServiceClient(
            account_url=account_url,
            credential=_BearerTokenCredential(token),
            max_chunk_get_size=self._chunk_size,
        )
```

Note: Changes `@staticmethod` to instance method. All call sites already use `self._create_client(...)`.

---

#### Step 12: Add etag parameter to stream_blob

**Origin**: Run 4 Patch 4 (FAULT-06)
**File**: `geotiler/services/blob_stream.py` — `stream_blob()` line 129
**Risk**: Low (optional param, no change when not provided)
**MUST BE APPLIED BEFORE STEP 13**

```python
# BEFORE
    async def stream_blob(self, blob_url: str, token: str) -> AsyncIterator[bytes]:
        ...
        async with self._create_client(account_url, token) as client:
            try:
                ...
                stream = await blob_client.download_blob()

# AFTER
    async def stream_blob(self, blob_url: str, token: str, etag: Optional[str] = None) -> AsyncIterator[bytes]:
        ...
        async with self._create_client(account_url, token) as client:
            try:
                ...
                download_kwargs = {}
                if etag:
                    from azure.core import MatchConditions
                    download_kwargs["etag"] = etag
                    download_kwargs["match_condition"] = MatchConditions.IfNotModified

                stream = await blob_client.download_blob(**download_kwargs)
```

---

#### Step 13: Pass etag from caller in download.py

**Origin**: Run 4 Patch 5 (FAULT-06 companion)
**File**: `geotiler/services/download.py` — `handle_asset_download()` line 568
**Risk**: Low (412 on blob replacement between check and stream → maps to existing 502 handler)

```python
# BEFORE
    stream = blob_client.stream_blob(resolved.blob_url, token)

# AFTER
    stream = blob_client.stream_blob(resolved.blob_url, token, etag=props.get("etag"))
```

---

### Phase 4 — Architectural (Deferred — Design Discussion Required)

These faults have no approved patches. Each requires architectural decisions beyond surgical patching.

| # | Source | Severity | Fault | Recommended Action |
|---|--------|----------|-------|-------------------|
| R2-F6 | Run 2 | HIGH | Token expiry mid-stream | Redesign `_BearerTokenCredential` to accept a refresh callback or inject `storage_token_cache` directly. Current 260s TTL threshold provides ~4min buffer. |
| R2-F11 | Run 2 | HIGH | Raster crop buffers entire response in memory | TiTiler crop returns full bytes. Options: (a) tighter bbox area limit, (b) streaming ASGI delegation, (c) per-resolution pixel budget. Monitor crop response sizes. |
| R2-F12 | Run 2 | MEDIUM | Client disconnect orphans DB connection | Verify Starlette calls `aclose()` on async generator disconnect. Step 10's `_guarded_stream` partially mitigates by releasing semaphore on disconnect. |
| R4-F1 | Run 4 | HIGH | Token expiry during blob streaming | Same root cause as R2-F6. Monitor `token_low_ttl` events. |
| R4-F2 | Run 4 | HIGH | Async generator connection leak on disconnect | `stream_blob()` yields inside `async with`. Verify Python/Starlette finalization behavior. Consider explicit `try/finally` with client close. |
| R4-F5 | Run 4 | CRITICAL | TiTiler crop OOM on high-res COGs | Overlaps R2-F11. The 25 sq deg area limit is a coarse proxy for pixel count. Alert on >50MB crop responses. |
| R4-F7 | Run 4 | MEDIUM | Container recycling → partial download | Infrastructure concern. Content-Length already set; clients can detect truncation. |
| R4-F8 | Run 4 | LOW | No BlobServiceClient connection pooling | Per-request pattern is correct for low concurrency. Revisit if download volume increases. |
| R4-F10 | Run 4 | HIGH | ASGI timeout (200s) races Gunicorn (240s) | Configuration alignment. The 40s gap may be insufficient if GDAL hangs. |
| R4-F12 | Run 4 | MEDIUM | Mid-stream errors invisible to client | HTTP/1.1 limitation. Content-Length mismatch is the only detection mechanism. |

---

## FILE CHANGE MAP

| File | Steps | Lines Changed (est.) |
|------|-------|---------------------|
| `geotiler/services/blob_stream.py` | 1, 2, 11, 12 | ~20 |
| `geotiler/services/download.py` | 3, 4, 5, 9, 13 | ~30 |
| `geotiler/routers/download.py` | 7, 8, 10 | ~60 |
| `geotiler/services/serializers.py` | 6 | ~5 |
| **Total** | **13 steps** | **~115 lines** |

---

## DEPENDENCY GRAPH

```
Phase 1 (no dependencies — all independent)
  Steps 1-7: Apply in any order

Phase 2 (strict ordering)
  Step 8 → Step 9 → Step 10
  ┌──────────────────────────────────────────────┐
  │ Step 8: Fallback semaphore singleton          │
  │ Step 9: Stream error wrapper (download.py)    │  ← BEFORE Step 10
  │ Step 10: Guarded stream (routers/download.py) │  ← CRITICAL, removes old finally blocks
  └──────────────────────────────────────────────┘

Phase 3 (partial ordering)
  Step 11: Independent (chunk_size)
  Step 12 → Step 13: etag param before caller passes it
```

---

## RISK MATRIX

| Phase | Steps | Risk Level | Rollback Strategy |
|-------|-------|-----------|-------------------|
| Phase 1 | 1-7 | **LOW** | Revert individual commits. Error paths only. |
| Phase 2 | 8-10 | **HIGH** | Revert all 3 as a unit. Step 10 changes concurrency semantics. |
| Phase 3 | 11-13 | **MEDIUM** | Revert individually. Step 11 changes chunk behavior (config-dependent). |

---

## MONITORING AFTER DEPLOYMENT

| Priority | Metric | Source Step | Alert Condition |
|----------|--------|------------|-----------------|
| P1 | `event: "stream_complete"` + `stream_ms` | Step 10 | Absent = guarded stream not running |
| P1 | Semaphore utilization | Step 10 | Approaching `download_max_concurrent` |
| P2 | `event: "stream_db_error"` | Step 9 | Any occurrence |
| P2 | `event: "download_started"` replacing old `download_complete` | Step 5 | Verify transition in logs |
| P3 | `event: "serialize_csv_extra_columns"` | Step 6 | Frequency indicates schema heterogeneity |
| P3 | HTTP 412 → 502 on asset downloads | Step 12-13 | Non-zero = blob mutation during download |
| P3 | `event: "blob_error"` with empty error field | Step 1 | Should never happen post-patch |
