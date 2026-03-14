# AUTH & TRUST BOUNDARY — COMPETE REVIEW

**Pipeline**: COMPETE (Alpha + Beta + Gamma → Delta)
**Date**: 13 MAR 2026
**Split**: D (Security vs Functionality — Auth & Trust Boundary)
**Target files**: `auth/postgres.py`, `auth/storage.py`, `auth/cache.py`, `auth/admin_auth.py`, `config.py`
**Excludes**: Issues already resolved in COMPETE Run 8 (Pool Architecture)

---

## EXECUTIVE SUMMARY

The auth subsystem is well-structured: dual async/sync lock layers, live-credential reference design, and a clear separation of managed-identity, key-vault, and password modes. Two issues require immediate attention: the JWT audience bypass in `admin_auth.py` is a real security boundary failure that lets any token from the correct tenant pass, and the `lru_cache` on `get_jwks_client()` permanently locks in a `None` result when `AZURE_TENANT_ID` is absent at startup, silently disabling admin auth for the process lifetime. Three additional medium-priority findings — thundering-herd on async cache miss, JWT exception detail exposure, and torn reads in the sync refresh path — complete the fix set. All five are independent of the Run 8 fixes.

---

## TOP 5 FIXES

### Fix 1: Add audience validation to JWT decode

- **WHAT**: Enable `verify_aud: True` in `jwt.decode()` and pass the application's own client ID or App ID URI as the expected audience.
- **WHY**: `verify_aud: False` at line 99 means any Azure AD token issued to any resource in the tenant is accepted, provided the issuer matches. A token minted for `https://management.azure.com`, the Key Vault data plane, or any first-party service will pass signature and issuer checks and grant access to admin endpoints. The comment justifying the bypass (that MI tokens use "varying audience values") is accurate — but the correct fix is to configure a dedicated App Registration for geotiler and instruct callers to request tokens scoped to that registration's URI, not to skip audience validation entirely.
- **WHERE**: `geotiler/auth/admin_auth.py`, `jwt.decode()` call, lines 89–103.
- **HOW**:
  1. Add `geotiler_app_id: Optional[str]` to `Settings` (env `GEOTILER_APP_ID`).
  2. If `settings.geotiler_app_id` is set, pass `audience=settings.geotiler_app_id` and set `"verify_aud": True`.
  3. If not set, retain the current bypass but emit a `logger.warning()` at startup so the misconfiguration is visible in logs.
  4. Update `CLAUDE.md` env var table and `docs/WIKI.md` to document the new variable.
- **EFFORT**: Medium (2–4 hours including App Registration setup documentation).
- **RISK OF FIX**: Low for code changes; the main risk is operator error configuring the wrong audience. Document clearly. The fallback-with-warning path preserves backward compatibility while the App Registration is provisioned.

---

### Fix 2: Replace `lru_cache` on `get_jwks_client()` with instance-level lazy init or restartable cache

- **WHAT**: Remove the `@lru_cache(maxsize=1)` decorator from `get_jwks_client()` and replace it with a module-level singleton that can be reset, or use `functools.cached_property` on a settings-derived object.
- **WHY**: Two independent problems compound here. First (B-7 / F-7 / Gamma A-2): if `AZURE_TENANT_ID` is absent at startup the function returns `None`, and `lru_cache` permanently caches that `None`. Any later hot-reload of settings or fix of the env var has no effect — the process must restart. Second (B-5): `PyJWKClient(cache_keys=True)` + `lru_cache` means the JWKS key set is never re-fetched after initial load. Azure AD rotates signing keys roughly every 24 hours; a long-lived process will begin rejecting valid tokens once the cached key is retired. `PyJWKClient` itself supports periodic re-fetch, but only if it is allowed to be re-instantiated or if `cache_keys=False`.
- **WHERE**: `geotiler/auth/admin_auth.py`, lines 41–52.
- **HOW**:
  ```python
  _jwks_client: Optional[PyJWKClient] = None

  def get_jwks_client() -> Optional[PyJWKClient]:
      global _jwks_client
      if _jwks_client is None and settings.azure_tenant_id:
          jwks_url = AZURE_AD_JWKS_URL.format(tenant_id=settings.azure_tenant_id)
          # cache_keys=False: PyJWKClient re-fetches JWKS on each signing key
          # lookup, which handles key rotation automatically.
          _jwks_client = PyJWKClient(jwks_url, cache_keys=False)
      return _jwks_client
  ```
  The `cache_keys=False` change means the JWKS endpoint is contacted on each token validation. For low-volume admin endpoints this is acceptable; if latency is a concern, add a TTL-bounded in-process key cache via `PyJWKClient`'s built-in `lifespan` parameter (added in PyJWT 2.6).
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. The only regression risk is a slight increase in HTTPS calls to `login.microsoftonline.com` for the JWKS endpoint, which is negligible for admin traffic.

---

### Fix 3: Restore stale token on async cache-miss acquisition failure (thundering-herd protection)

- **WHAT**: In `_get_postgres_oauth_token_async()` and `get_storage_oauth_token_async()`, save the current cache state before entering the acquisition path, and restore it if acquisition fails, matching the intent of the sync `refresh_postgres_token()` restore logic.
- **WHY**: (F-5 / Gamma A-1 / B-10) When the async path has a cache miss it calls `_acquire_postgres_token()` (or `_acquire_storage_token()`) in a thread. If the thread raises, the function propagates the exception and leaves the cache empty. Any subsequent callers that entered after the lock was released see an empty cache, each triggers its own acquisition, and all fail against an unavailable IMDS endpoint — classic thundering herd. The sync path at `postgres.py:218–223` intentionally restores the old token; the async path has no equivalent.
- **WHERE**:
  - `geotiler/auth/postgres.py`, `_get_postgres_oauth_token_async()`, lines 261–277.
  - `geotiler/auth/storage.py`, `get_storage_oauth_token_async()`, lines 89–105.
- **HOW**: Before calling `asyncio.to_thread(...)`, snapshot `token = cache.token` and `expires_at = cache.expires_at` (caller holds the async lock, so no separate threading lock needed for the read). Wrap the thread call in try/except; on exception, if `token` is not None, call `cache.set_unlocked(token, expires_at)` to restore, then re-raise:
  ```python
  async with postgres_token_cache.async_lock:
      cached = postgres_token_cache.get_if_valid_unlocked(...)
      if cached:
          return cached
      # Snapshot for restore-on-failure
      old_token = postgres_token_cache.token
      old_expires = postgres_token_cache.expires_at
      try:
          token, expires_at = await asyncio.to_thread(_acquire_postgres_token)
          if token and expires_at:
              postgres_token_cache.set_unlocked(token, expires_at)
          return token
      except Exception:
          if old_token and old_expires:
              postgres_token_cache.set_unlocked(old_token, old_expires)
          raise
  ```
- **EFFORT**: Small (< 1 hour).
- **RISK OF FIX**: Low. This only changes error-path behavior; happy path is unchanged.

---

### Fix 4: Sanitize JWT exception detail before returning to HTTP callers

- **WHAT**: Replace `detail=f"Token validation failed: {str(e)}"` with a fixed generic string; log the full exception detail server-side only.
- **WHY**: (B-2) The `except jwt.PyJWTError` block at lines 121–127 of `admin_auth.py` forwards the raw exception message to the HTTP caller. PyJWT exception messages can include claim names, expected vs. received values, and key IDs — sufficient to fingerprint the validation logic and probe for weaknesses (e.g., discovering which claims are checked, what issuer format is expected). This is a low-effort oracle that aids targeted token forgery attempts.
- **WHERE**: `geotiler/auth/admin_auth.py`, lines 121–127.
- **HOW**:
  ```python
  except jwt.PyJWTError as e:
      logger.warning(f"Admin auth: Token validation failed: {e}")
      raise HTTPException(
          status_code=status.HTTP_401_UNAUTHORIZED,
          detail="Token validation failed",
          headers={"WWW-Authenticate": "Bearer"},
      )
  ```
  The existing `ExpiredSignatureError` and `InvalidIssuerError` branches (lines 107–120) are acceptable — "expired" and "wrong issuer" are standard 401 semantics that do not reveal implementation details.
- **EFFORT**: Trivial (5 minutes).
- **RISK OF FIX**: None.

---

### Fix 5: Add threading lock to `_CachedTokenCredential.get_token()` reads

- **WHAT**: Replace the two bare attribute reads on `storage_token_cache` in `_CachedTokenCredential.get_token()` with a single locked read via a new `TokenCache` helper method.
- **WHY**: (F-10 / Gamma, distinct from Run 8 Fix 4) `_CachedTokenCredential.get_token()` at lines 183–186 of `storage.py` reads `storage_token_cache.token` and then `storage_token_cache.expires_at` as two separate attribute accesses without holding any lock. A concurrent write from `configure_gdal_auth()` or `storage_token_cache.set()` running in an `asyncio.to_thread()` context can produce a torn state: the token from one write and the expiry from another. This is different from the Run 8 Fix 4 scenario (which addressed `cache.clear()` during read); the concern here is any concurrent `set()` call, which is the normal token refresh path.
- **WHERE**: `geotiler/auth/storage.py`, `_CachedTokenCredential.get_token()`, lines 180–187. Also requires a new helper on `geotiler/auth/cache.py`.
- **HOW**: Add an atomic getter to `TokenCache`:
  ```python
  # cache.py
  def get_token_and_expiry(self) -> tuple[Optional[str], Optional[datetime]]:
      """Return (token, expires_at) under the threading lock."""
      with self._lock:
          return self.token, self.expires_at
  ```
  Then update `_CachedTokenCredential.get_token()`:
  ```python
  async def get_token(self, *scopes, **kwargs):
      from azure.core.credentials import AccessToken
      token, expires_at = storage_token_cache.get_token_and_expiry()
      if token and expires_at:
          return AccessToken(token, int(expires_at.timestamp()))
      raise Exception("No cached storage token available for adlfs")
  ```
- **EFFORT**: Small (< 30 minutes).
- **RISK OF FIX**: Low. Pure read-path improvement; no write behaviour changes.

---

## ACCEPTED RISKS

| ID | Finding | Why Accepted | Condition for Revisiting |
|----|---------|-------------|--------------------------|
| B-6 | `auth_use_cli=True` default enables `DefaultAzureCredential` in production | Pydantic `bool` field; production deployments must explicitly set `GEOTILER_AUTH_USE_CLI=false`. Documented in WIKI. | If a production incident is traced to a misconfigured instance that silently fell back to CLI auth. |
| B-7 (password length at DEBUG) | Password length logged at `DEBUG` level in `_get_password_from_env()` | DEBUG logs are not emitted in production (log level is INFO). Risk is confined to local dev environments where DEBUG is enabled. | If production log level is ever lowered to DEBUG. |
| B-8 (credential in DSN URL) | Full password embedded in `build_database_url()` return value | The DSN string is passed directly to the async pool constructor and is not persisted or serialized. asyncpg does not log the DSN by default. | If a framework upgrade changes asyncpg's error logging to include the full DSN in tracebacks. |
| B-9 (unauthenticated `/health`) | DB hostname, storage account, schema names exposed at `/health` | `/health` is intentionally diagnostic. The values are already embedded in App Service configuration visible to anyone with portal access. The information is not a credential. | If the app is ever deployed in a context where `/health` is internet-exposed without network-layer restrictions. |
| B-11 (keyvault_name URL interpolation) | `settings.keyvault_name` interpolated into vault URL without format validation | Pydantic loads the value from a controlled env var; the format is validated at Key Vault SDK call time with a clear error message. No injection vector exists via HTTP requests. | If the setting is ever sourced from an untrusted input channel. |
| G-7 (quote_plus for DSN password) | `quote_plus` encodes spaces as `+` not `%20` | PostgreSQL passwords containing literal spaces are extremely rare in practice. If a space-containing password fails, the error is immediate and obvious at startup. | If key_vault mode returns passwords from a system that generates space-containing values. |
| B-3 (`oid` fallback documented but absent) | Docstring lists `oid` as fallback claim for `get_app_id_from_token()`; code does not implement it | The three implemented claims (`azp`, `appid`, `app_id`) cover all live Azure AD token flows for service-to-service MI. The `oid` fallback would grant access by object ID rather than client ID, bypassing the intended `ADMIN_ALLOWED_APP_IDS` check semantics. The gap between docstring and code is documentation debt, not a security gap. | If a new token flow is encountered where only `oid` is present and the operator cannot control the token format. |
| G-6 (JWT claim key names in log on extraction failure) | `require_admin_auth` logs `list(claims.keys())` on app ID extraction failure | The log is at WARNING level, server-side only. Claim key names (`azp`, `sub`, `oid`, etc.) are public Azure AD token schema; they are not secrets. | No condition — this is a logging style issue, not a security risk. |

---

## ARCHITECTURE WINS

**Dual-layer lock design**: `TokenCache` cleanly separates the `threading.Lock` (for sync startup code) from the `asyncio.Lock` (for async request handling). The unlocked `_unlocked` method variants make the locking contract explicit at call sites. This is a considered design, not an accident.

**Live-reference credential (`_CachedTokenCredential`)**: Rather than re-configuring fsspec on every token refresh, the `_CachedTokenCredential` singleton holds a live reference to `storage_token_cache`. Background token refreshes are automatically visible to all adlfs requests without clearing the filesystem instance cache. This elegantly avoids the fsspec re-configuration problem identified by Gamma (C-3).

**Acquire-before-swap in async refresh paths**: Both `refresh_postgres_token_async()` and `refresh_storage_token_async()` acquire the new token before touching the cached value. If acquisition fails, the old token survives untouched. This is the correct pattern for zero-downtime credential rotation.

**`auth_use_cli` as explicit escape hatch**: The `DefaultAzureCredential` chain is gated behind an explicit boolean that is `True` locally and must be set to `False` in production. The intent is clear and the guard is present at every acquisition site.

**Config validation at the boundary**: `pg_auth_mode` using a Pydantic `Literal` type means invalid mode strings are rejected at startup with a clear Pydantic validation error, before any database connection is attempted.

**Minimal token scope**: `POSTGRES_SCOPE` and `STORAGE_SCOPE` are single `.default` scopes for their respective services. No over-scoped or multi-resource tokens are requested.

**No token stored in config**: Tokens are managed entirely in `TokenCache` instances; `Settings` only holds static credentials (password, Key Vault name). There is a clean separation between configuration (cold, at startup) and live credentials (warm, managed at runtime).

---

## PIPELINE METADATA

| Agent | Role | Findings Contributed | Key Contributions |
|-------|------|---------------------|-------------------|
| Alpha | Functionality | 5 HIGH, 5 MEDIUM, 2 LOW | Identified async lock module-import issue (F-1), torn read in sync refresh (F-4), cache-miss thundering herd (F-5), JWKS lru_cache None permanence (F-7), `asyncpg` search_path options silently ignored (F-9) |
| Beta | Security | 1 CRITICAL, 4 HIGH, 5 MEDIUM, 3 LOW | Identified `verify_aud: False` as CRITICAL (B-1), JWT exception detail oracle (B-2), lru_cache blocking key rotation (B-5), password length debug log (B-7), credential in DSN URL (B-8) |
| Gamma | Contradictions / Blind Spots | 3 contradictions, 3 agreements, 7 blind spots | Downgraded F-2 and F-8 to LOW; partially resolved F-3 (live-reference design); identified torn read in sync storage refresh (G-3), `_fsspec_configured` flag not thread-safe (G-4), PyJWKClient compound cache blind spot (G-5) |
| Delta | Synthesis (this document) | 5 prioritized fixes, 8 accepted risks | De-duplicated overlapping B-5/F-7/G-5 into single Fix 2; separated Run 8 carry-overs; grounded all findings in exact source lines |

**Run 8 carry-overs explicitly excluded from Top 5**: sync invalidate-then-acquire race (Run 8 Fix 1 & Fix 2), `_CachedTokenCredential` torn read via `clear()` (Run 8 Fix 4), OAuth tokens in env vars (Run 8 accepted risk), `_check_token_ready` lockless read (Run 8 accepted risk).
