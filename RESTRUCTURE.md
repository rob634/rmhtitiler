# Restructuring Plan: rmhtitiler

> **Status:** Draft
> **Created:** 2026-01-05
> **Current State:** Single 1,663-line god file (`custom_pgstac_main.py`)

---

## Executive Summary

This document outlines a phased restructuring of the rmhtitiler codebase from a single monolithic file into a well-organized Python package. The restructuring preserves all existing functionality while improving maintainability, testability, and developer experience.

### Core Functionality (Must Preserve)

1. **Azure Storage OAuth** - Acquire MI tokens, set GDAL env vars (`AZURE_STORAGE_ACCESS_TOKEN`)
2. **TiTiler Integration** - Mount TiTiler-core, TiTiler-pgstac, TiTiler-xarray routers
3. **PostgreSQL Auth** - Three modes: managed identity, key vault, password
4. **Health Probes** - Kubernetes-style `/livez`, `/readyz`, `/healthz`
5. **Planetary Computer** - Credential provider for external climate data
6. **Background Token Refresh** - Proactive token refresh every 45 minutes
7. **NiceGUI Dashboard** - Admin UI mounted at `/dashboard`

---

## Target Architecture

```
rmhtitiler/
├── __init__.py                 # Package version
├── app.py                      # FastAPI app factory (~100 lines)
├── config.py                   # Configuration + constants (~80 lines)
├── auth/
│   ├── __init__.py
│   ├── cache.py                # TokenCache class (generic)
│   ├── storage.py              # Azure Storage OAuth
│   └── postgres.py             # PostgreSQL auth (MI, KeyVault, password)
├── routers/
│   ├── __init__.py
│   ├── health.py               # /livez, /readyz, /healthz
│   ├── planetary_computer.py   # /pc/* endpoints
│   └── root.py                 # / endpoint
├── middleware/
│   ├── __init__.py
│   └── azure_auth.py           # AzureAuthMiddleware
├── services/
│   ├── __init__.py
│   ├── database.py             # DB connection + health check helpers
│   └── background.py           # Background token refresh task
├── templates/
│   └── pc_map.html             # Leaflet map (extracted from inline)
├── dashboard/                  # (existing - no changes)
│   ├── main.py
│   ├── client.py
│   └── pages/
└── custom_pgstac_main.py       # DEPRECATED - redirect import only
```

### Entry Points

| Use Case | Entry Point |
|----------|-------------|
| Production (uvicorn) | `rmhtitiler.app:create_app()` or `rmhtitiler.app:app` |
| Docker | `uvicorn rmhtitiler.app:app --host 0.0.0.0 --port 8000` |
| Development | `python -m rmhtitiler` |
| Backwards compat | `custom_pgstac_main:app` (deprecated, imports from new location) |

---

## Phase 1: Foundation (Low Risk)

**Goal:** Extract configuration and create package structure without changing behavior.

### Task 1.1: Create Package Structure

```bash
mkdir -p rmhtitiler/{auth,routers,middleware,services,templates}
touch rmhtitiler/__init__.py
touch rmhtitiler/{auth,routers,middleware,services}/__init__.py
```

**Files to create:**
- `rmhtitiler/__init__.py` - Version and package metadata
- `rmhtitiler/config.py` - All configuration extraction

### Task 1.2: Extract Configuration (`config.py`)

Extract all configuration into a single module with:
- Environment variable loading
- Constants (magic numbers → named constants)
- Pydantic Settings class (optional, for validation)

**Before (scattered in custom_pgstac_main.py):**
```python
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"
# ... 15+ more env vars scattered throughout
```

**After (config.py):**
```python
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Azure Storage
    use_azure_auth: bool = False
    azure_storage_account: Optional[str] = None
    local_mode: bool = True

    # PostgreSQL
    postgres_auth_mode: str = "password"
    postgres_host: Optional[str] = None
    postgres_db: Optional[str] = None
    postgres_user: Optional[str] = None
    postgres_port: int = 5432
    postgres_password: Optional[str] = None
    postgres_mi_client_id: Optional[str] = None

    # Key Vault
    key_vault_name: Optional[str] = None
    key_vault_secret_name: str = "postgres-password"

    # Features
    enable_planetary_computer: bool = True
    enable_dashboard: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = False

# Constants
TOKEN_REFRESH_BUFFER_SECS = 300  # Refresh 5 min before expiry
READYZ_MIN_TTL_SECS = 60         # Mark not ready if <1 min TTL
BACKGROUND_REFRESH_INTERVAL = 45 * 60  # 45 minutes
TILE_SIZE = 256

# Azure scopes
STORAGE_SCOPE = "https://storage.azure.com/.default"
POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

# Planetary Computer storage accounts
PC_STORAGE_ACCOUNTS = {
    "rhgeuwest": "cil-gdpcir-cc0",
    "ai4edataeuwest": "daymet-daily-na",
}

# Singleton settings instance
settings = Settings()
```

### Task 1.3: Fix Version Mismatch

**Problem:** `__version__ = "0.4.1"` but other places hardcode `"1.0.0"`

**Solution:**
```python
# rmhtitiler/__init__.py
__version__ = "0.5.0"  # Bump for restructure

# All other files import from here
from rmhtitiler import __version__
```

### Task 1.4: Remove Unused Imports

**File:** `custom_pgstac_main.py` line 58

```python
# Before
from titiler.core.factory import TilerFactory, MultiBaseTilerFactory, TMSFactory

# After
from titiler.core.factory import TilerFactory
```

---

## Phase 2: Authentication Module (Medium Risk)

**Goal:** Extract all authentication logic into `rmhtitiler/auth/`.

### Task 2.1: Create TokenCache Class (`auth/cache.py`)

**Problem:** Three nearly identical cache dictionaries with locks.

**Solution:** Generic reusable class.

```python
# rmhtitiler/auth/cache.py
from datetime import datetime, timezone
from threading import Lock
from typing import Optional, Any
from dataclasses import dataclass, field

@dataclass
class TokenCache:
    """Thread-safe cache for OAuth tokens with expiry tracking."""

    token: Optional[str] = None
    expires_at: Optional[datetime] = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def get_if_valid(self, min_ttl_seconds: int = 300) -> Optional[str]:
        """Return cached token if valid and not expiring soon."""
        with self._lock:
            if not self.token or not self.expires_at:
                return None

            ttl = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
            if ttl > min_ttl_seconds:
                return self.token
            return None

    def set(self, token: str, expires_at: datetime) -> None:
        """Update cached token."""
        with self._lock:
            self.token = token
            self.expires_at = expires_at

    def invalidate(self) -> None:
        """Force token refresh on next access."""
        with self._lock:
            self.expires_at = None

    def ttl_seconds(self) -> Optional[float]:
        """Return seconds until expiry, or None if no token."""
        with self._lock:
            if not self.expires_at:
                return None
            return (self.expires_at - datetime.now(timezone.utc)).total_seconds()


@dataclass
class ErrorCache:
    """Track last error for health reporting."""

    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_success(self) -> None:
        with self._lock:
            self.last_error = None
            self.last_success_time = datetime.now(timezone.utc)

    def record_error(self, error: str) -> None:
        with self._lock:
            self.last_error = error
            self.last_error_time = datetime.now(timezone.utc)

    def get_status(self) -> dict:
        with self._lock:
            return {
                "last_error": self.last_error,
                "last_error_time": self.last_error_time.isoformat() if self.last_error_time else None,
                "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
            }


# Global cache instances
storage_token_cache = TokenCache()
postgres_token_cache = TokenCache()
db_error_cache = ErrorCache()
```

### Task 2.2: Extract Storage Auth (`auth/storage.py`)

```python
# rmhtitiler/auth/storage.py
import os
import logging
from datetime import datetime, timezone
from typing import Optional

from rmhtitiler.config import settings, STORAGE_SCOPE
from rmhtitiler.auth.cache import storage_token_cache

logger = logging.getLogger(__name__)

def get_storage_oauth_token() -> Optional[str]:
    """
    Get OAuth token for Azure Storage using Managed Identity.

    Token grants access to ALL containers based on RBAC role assignments.
    Automatically cached and refreshed 5 minutes before expiry.
    """
    if not settings.use_azure_auth:
        return None

    # Check cache first
    cached = storage_token_cache.get_if_valid()
    if cached:
        logger.debug(f"Using cached storage token, TTL: {storage_token_cache.ttl_seconds():.0f}s")
        return cached

    # Acquire new token
    logger.info("Acquiring Azure Storage OAuth token...")

    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    token = credential.get_token(STORAGE_SCOPE)
    expires_at = datetime.fromtimestamp(token.expires_on, tz=timezone.utc)

    storage_token_cache.set(token.token, expires_at)
    logger.info(f"Storage token acquired, expires: {expires_at.isoformat()}")

    return token.token


def configure_gdal_auth(token: str) -> None:
    """Set environment variables and GDAL config for Azure blob access."""
    os.environ["AZURE_STORAGE_ACCOUNT"] = settings.azure_storage_account
    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token

    try:
        from rasterio import _env
        _env.set_gdal_config("AZURE_STORAGE_ACCOUNT", settings.azure_storage_account)
        _env.set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token)
    except Exception as e:
        logger.warning(f"Could not set GDAL config directly: {e}")


def configure_fsspec_auth() -> None:
    """Configure fsspec/adlfs for Zarr access."""
    os.environ["AZURE_STORAGE_ACCOUNT_NAME"] = settings.azure_storage_account
```

### Task 2.3: Extract PostgreSQL Auth (`auth/postgres.py`)

```python
# rmhtitiler/auth/postgres.py
import logging
from datetime import datetime, timezone
from typing import Optional

from rmhtitiler.config import settings, POSTGRES_SCOPE
from rmhtitiler.auth.cache import postgres_token_cache

logger = logging.getLogger(__name__)

def get_postgres_credential() -> Optional[str]:
    """
    Get PostgreSQL credential based on configured auth mode.

    Returns:
        Password or OAuth token for PostgreSQL connection
    """
    if settings.postgres_auth_mode == "password":
        return settings.postgres_password

    elif settings.postgres_auth_mode == "key_vault":
        return _get_password_from_keyvault()

    elif settings.postgres_auth_mode == "managed_identity":
        return _get_postgres_oauth_token()

    else:
        raise ValueError(f"Invalid POSTGRES_AUTH_MODE: {settings.postgres_auth_mode}")


def _get_postgres_oauth_token() -> str:
    """Get OAuth token for Azure PostgreSQL using Managed Identity."""
    cached = postgres_token_cache.get_if_valid()
    if cached:
        return cached

    logger.info("Acquiring PostgreSQL OAuth token...")

    if settings.postgres_mi_client_id and not settings.local_mode:
        from azure.identity import ManagedIdentityCredential
        credential = ManagedIdentityCredential(client_id=settings.postgres_mi_client_id)
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()

    token = credential.get_token(POSTGRES_SCOPE)
    expires_at = datetime.fromtimestamp(token.expires_on, tz=timezone.utc)

    postgres_token_cache.set(token.token, expires_at)
    logger.info(f"PostgreSQL token acquired, expires: {expires_at.isoformat()}")

    return token.token


def _get_password_from_keyvault() -> str:
    """Retrieve PostgreSQL password from Azure Key Vault."""
    logger.info(f"Retrieving password from Key Vault: {settings.key_vault_name}")

    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    vault_url = f"https://{settings.key_vault_name}.vault.azure.net/"
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)

    secret = client.get_secret(settings.key_vault_secret_name)
    return secret.value


def build_database_url(password: str) -> str:
    """Build PostgreSQL connection URL."""
    return (
        f"postgresql://{settings.postgres_user}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}"
        f"/{settings.postgres_db}?sslmode=require"
    )
```

---

## Phase 3: Health Probes Module (Low Risk)

**Goal:** Extract health endpoints with shared helper functions.

### Task 3.1: Create Health Router (`routers/health.py`)

```python
# rmhtitiler/routers/health.py
from fastapi import APIRouter, Response
from datetime import datetime, timezone

from rmhtitiler import __version__
from rmhtitiler.config import settings, READYZ_MIN_TTL_SECS
from rmhtitiler.auth.cache import storage_token_cache, postgres_token_cache, db_error_cache
from rmhtitiler.services.database import ping_database

router = APIRouter(tags=["Health"])


@router.get("/livez")
async def liveness():
    """Liveness probe - container is running."""
    return {"status": "alive", "message": "Container is running"}


@router.get("/readyz")
async def readiness(response: Response):
    """Readiness probe - ready to receive traffic."""
    ready = True
    issues = []

    # Check database
    db_ok, db_error = ping_database()
    if not db_ok:
        ready = False
        issues.append(f"database: {db_error}")

    # Check storage OAuth
    if settings.use_azure_auth:
        storage_ok, storage_issue = _check_token_ready(storage_token_cache, "storage_oauth")
        if not storage_ok:
            ready = False
            issues.append(storage_issue)

    # Check postgres OAuth
    if settings.postgres_auth_mode == "managed_identity":
        pg_ok, pg_issue = _check_token_ready(postgres_token_cache, "postgres_oauth")
        if not pg_ok:
            ready = False
            issues.append(pg_issue)

    response.status_code = 200 if ready else 503
    return {
        "ready": ready,
        "version": __version__,
        "issues": issues or None
    }


@router.get("/healthz")
async def health(response: Response):
    """Full health check with diagnostics."""
    # ... (detailed implementation)
    pass


def _check_token_ready(cache, name: str) -> tuple[bool, str]:
    """Check if token cache is valid for readiness."""
    if not cache.token:
        return False, f"{name}: no token"

    ttl = cache.ttl_seconds()
    if ttl and ttl < READYZ_MIN_TTL_SECS:
        return False, f"{name}: expires in {int(ttl)}s"

    return True, ""
```

### Task 3.2: Extract Database Ping Helper (`services/database.py`)

```python
# rmhtitiler/services/database.py
from typing import Tuple, Optional
from rmhtitiler.auth.cache import db_error_cache

# Will be set during app startup
_app_state = None

def set_app_state(state):
    """Called during startup to provide access to app.state."""
    global _app_state
    _app_state = state


def ping_database() -> Tuple[bool, Optional[str]]:
    """
    Ping database and return (success, error_message).
    Updates error cache for health reporting.
    """
    if not _app_state or not hasattr(_app_state, "dbpool") or not _app_state.dbpool:
        return False, "pool not initialized"

    try:
        with _app_state.dbpool.connection() as conn:
            conn.execute("SELECT 1")
        db_error_cache.record_success()
        return True, None
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)}"
        db_error_cache.record_error(error)
        return False, type(e).__name__
```

---

## Phase 4: Planetary Computer Module (Medium Risk)

**Goal:** Extract PC endpoints and create reusable Zarr helpers.

### Task 4.1: Extract PC Helpers (`routers/planetary_computer.py`)

**Key refactoring:**
1. Create `open_pc_zarr_dataset()` helper (used 3 times)
2. Create `create_transparent_tile()` helper (used 2 times)
3. Move HTML template to file

```python
# rmhtitiler/routers/planetary_computer.py
from fastapi import APIRouter, Query, Request, Response
from typing import Optional
import xarray as xr

router = APIRouter(prefix="/pc", tags=["Planetary Computer"])

def open_pc_zarr_dataset(url: str) -> xr.Dataset:
    """Open a Planetary Computer Zarr dataset with credentials."""
    from obstore.store import AzureStore
    from obstore.auth.planetary_computer import PlanetaryComputerCredentialProvider
    from zarr.storage import ObjectStore

    credential_provider = PlanetaryComputerCredentialProvider(url=url)
    store = AzureStore(credential_provider=credential_provider)
    zarr_store = ObjectStore(store, read_only=True)

    return xr.open_zarr(zarr_store, consolidated=True, decode_times=False)


def create_transparent_tile() -> bytes:
    """Create a 256x256 transparent PNG tile."""
    from PIL import Image
    import io

    img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()


@router.get("/variables")
async def pc_variables(url: str = Query(...)):
    """List variables in a Planetary Computer Zarr dataset."""
    ds = open_pc_zarr_dataset(url)
    return {"variables": list(ds.data_vars.keys()), "url": url}

# ... other endpoints
```

### Task 4.2: Extract HTML Template

**Create:** `rmhtitiler/templates/pc_map.html`

```html
<!DOCTYPE html>
<html>
<head>
    <title>{{ variable }} - Planetary Computer Viewer</title>
    <!-- ... -->
</head>
<body>
    <!-- ... -->
    <script>
        fetch('{{ tilejson_url }}')
            .then(response => response.json())
            // ...
    </script>
</body>
</html>
```

---

## Phase 5: Application Factory (Low Risk)

**Goal:** Create clean app factory with lifespan handler.

### Task 5.1: Create App Factory (`app.py`)

```python
# rmhtitiler/app.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rmhtitiler import __version__
from rmhtitiler.config import settings
from rmhtitiler.middleware.azure_auth import AzureAuthMiddleware
from rmhtitiler.routers import health, planetary_computer, root
from rmhtitiler.services.database import set_app_state
from rmhtitiler.services.background import start_token_refresh

# TiTiler imports
from titiler.core.factory import TilerFactory
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.pgstac.factory import MosaicTilerFactory, add_search_list_route, add_search_register_route
from titiler.pgstac.db import close_db_connection, connect_to_db
from titiler.pgstac.dependencies import SearchIdParams
from titiler.pgstac.settings import PostgresSettings
from titiler.xarray.factory import TilerFactory as XarrayTilerFactory
from titiler.xarray.extensions import VariablesExtension
from titiler.mosaic.factory import MosaicTilerFactory as BaseMosaicTilerFactory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown logic."""
    # Startup
    logger.info(f"Starting rmhtitiler v{__version__}")

    await _initialize_database(app)
    await _initialize_storage_auth()

    if settings.use_azure_auth:
        start_token_refresh(app)

    set_app_state(app.state)

    logger.info("Startup complete")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down...")
    await close_db_connection(app)
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="TiTiler-pgSTAC with Azure OAuth",
        description="STAC catalog tile server with Managed Identity authentication",
        version=__version__,
        lifespan=lifespan,
    )

    # Middleware
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(AzureAuthMiddleware)

    # Exception handlers
    add_exception_handlers(app, DEFAULT_STATUS_CODES)

    # Health probes
    app.include_router(health.router)

    # TiTiler routers
    _mount_titiler_routers(app)

    # Planetary Computer
    if settings.enable_planetary_computer:
        app.include_router(planetary_computer.router)

    # Root info
    app.include_router(root.router)

    # Dashboard
    if settings.enable_dashboard:
        _mount_dashboard(app)

    return app


def _mount_titiler_routers(app: FastAPI) -> None:
    """Mount all TiTiler routers."""

    # COG tiles
    cog = TilerFactory(router_prefix="/cog", add_viewer=True)
    app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])

    # Xarray/Zarr
    xarray = XarrayTilerFactory(
        router_prefix="/xarray",
        extensions=[VariablesExtension()],
    )
    app.include_router(xarray.router, prefix="/xarray", tags=["Multidimensional (Zarr/NetCDF)"])

    # MosaicJSON
    mosaic = BaseMosaicTilerFactory(router_prefix="/mosaicjson", add_viewer=True)
    app.include_router(mosaic.router, prefix="/mosaicjson", tags=["MosaicJSON"])

    # pgSTAC
    pgstac = MosaicTilerFactory(
        path_dependency=SearchIdParams,
        router_prefix="/searches/{search_id}",
        add_statistics=True,
        add_viewer=True,
    )
    app.include_router(pgstac.router, prefix="/searches/{search_id}", tags=["STAC Search"])
    add_search_list_route(app, prefix="/searches", tags=["STAC Search"])
    add_search_register_route(app, prefix="/searches", tile_dependencies=[...], tags=["STAC Search"])


def _mount_dashboard(app: FastAPI) -> None:
    """Mount NiceGUI dashboard."""
    try:
        from dashboard.main import mount_dashboard
        mount_dashboard(app)
        logger.info("Dashboard mounted at /dashboard")
    except ImportError as e:
        logger.warning(f"Dashboard not available: {e}")


# Create app instance for uvicorn
app = create_app()
```

### Task 5.2: Create Backwards-Compatible Entry Point

```python
# custom_pgstac_main.py (DEPRECATED)
"""
DEPRECATED: This file is maintained for backwards compatibility.
Use `rmhtitiler.app:app` instead.
"""
import warnings

warnings.warn(
    "custom_pgstac_main is deprecated. Use 'rmhtitiler.app:app' instead.",
    DeprecationWarning,
    stacklevel=2
)

from rmhtitiler.app import app

__all__ = ["app"]
```

---

## Phase 6: Cleanup & Testing (Low Risk)

### Task 6.1: Update Dockerfile

```dockerfile
# Before
CMD ["uvicorn", "custom_pgstac_main:app", "--host", "0.0.0.0", "--port", "8000"]

# After
CMD ["uvicorn", "rmhtitiler.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Task 6.2: Update CLAUDE.md

Update documentation to reflect new structure.

### Task 6.3: Add Unit Tests

```python
# tests/test_auth_cache.py
from rmhtitiler.auth.cache import TokenCache
from datetime import datetime, timezone, timedelta

def test_token_cache_empty():
    cache = TokenCache()
    assert cache.get_if_valid() is None

def test_token_cache_valid():
    cache = TokenCache()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    cache.set("test_token", expires)
    assert cache.get_if_valid() == "test_token"

def test_token_cache_expired():
    cache = TokenCache()
    expires = datetime.now(timezone.utc) + timedelta(seconds=60)
    cache.set("test_token", expires)
    # Default min_ttl is 300 seconds, so this should return None
    assert cache.get_if_valid() is None
```

---

## Implementation Order

| Phase | Tasks | Risk | Effort | Dependencies |
|-------|-------|------|--------|--------------|
| **1** | Config, Package structure, Version fix | Low | 2-3 hours | None |
| **2** | Auth module (cache, storage, postgres) | Medium | 4-5 hours | Phase 1 |
| **3** | Health probes router | Low | 2-3 hours | Phase 2 |
| **4** | Planetary Computer module | Medium | 3-4 hours | Phase 1 |
| **5** | App factory with lifespan | Low | 2-3 hours | Phases 2-4 |
| **6** | Cleanup, Dockerfile, tests | Low | 2-3 hours | Phase 5 |

**Total estimated effort:** 15-21 hours

---

## Migration Checklist

- [ ] Phase 1: Foundation
  - [ ] Create package directory structure
  - [ ] Create `rmhtitiler/__init__.py` with version
  - [ ] Create `rmhtitiler/config.py` with Settings class
  - [ ] Fix version mismatch (use `__version__` everywhere)
  - [ ] Remove unused imports (MultiBaseTilerFactory, TMSFactory)

- [ ] Phase 2: Authentication
  - [ ] Create `auth/cache.py` with TokenCache class
  - [ ] Create `auth/storage.py` with storage OAuth functions
  - [ ] Create `auth/postgres.py` with PostgreSQL auth functions
  - [ ] Update imports in main file to use new modules
  - [ ] Test: Verify token caching still works

- [ ] Phase 3: Health Probes
  - [ ] Create `routers/health.py` with all probe endpoints
  - [ ] Create `services/database.py` with ping helper
  - [ ] Extract `_check_token_ready()` helper
  - [ ] Test: Verify /livez, /readyz, /healthz responses

- [ ] Phase 4: Planetary Computer
  - [ ] Create `routers/planetary_computer.py`
  - [ ] Extract `open_pc_zarr_dataset()` helper
  - [ ] Extract `create_transparent_tile()` helper
  - [ ] Move HTML template to `templates/pc_map.html`
  - [ ] Test: Verify PC endpoints work

- [ ] Phase 5: App Factory
  - [ ] Create `app.py` with lifespan handler
  - [ ] Create `middleware/azure_auth.py`
  - [ ] Create `services/background.py` for token refresh
  - [ ] Create backwards-compat `custom_pgstac_main.py`
  - [ ] Test: Full application startup/shutdown

- [ ] Phase 6: Cleanup
  - [ ] Update Dockerfile CMD
  - [ ] Update docker-compose.yml
  - [ ] Update CLAUDE.md documentation
  - [ ] Add basic unit tests
  - [ ] Remove deprecated code after transition period

---

## Rollback Plan

If issues arise during migration:

1. **Phase 1-4:** Simply revert to `custom_pgstac_main.py` - no breaking changes
2. **Phase 5:** The backwards-compat shim ensures `custom_pgstac_main:app` still works
3. **Phase 6:** Dockerfile changes can be reverted independently

---

## Success Criteria

1. All endpoints return identical responses before/after restructure
2. Health probes pass in Kubernetes/Azure App Service
3. Token caching and refresh work correctly
4. No increase in startup time
5. All existing functionality preserved
6. Code coverage > 80% for new modules
