# Health Endpoint Refactor Plan

**Date**: 13 JAN 2026
**Purpose**: Restructure `/health` response to cleanly report individual services for rmhgeoapi integration
**Implementer**: Docker Claude

---

## Background

The rmhgeoapi Function App needs to monitor the health of individual services within this Docker container. Currently the `/health` endpoint has good information but it's spread across `checks` and `available_features`. We need a cleaner `services` structure.

---

## Current vs Proposed Response Structure

### Current Response (Simplified)
```json
{
  "status": "healthy",
  "version": "0.7.x",
  "checks": {
    "database": { "status": "ok", "ping_time_ms": 12.5 },
    "storage_oauth": { "status": "ok", "expires_in_seconds": 3456 },
    "tipg": { "status": "ok", "collections_discovered": 42 },
    "stac_api": { "status": "ok" }
  },
  "available_features": {
    "cog_tiles": true,
    "xarray_zarr": true,
    "pgstac_searches": true,
    "ogc_features": true,
    "vector_tiles": true,
    "stac_api": true
  }
}
```

### Proposed Response
```json
{
  "status": "healthy",
  "version": "0.7.x",
  "services": {
    "cog": {
      "status": "healthy",
      "available": true,
      "description": "Cloud-Optimized GeoTIFF tile serving",
      "endpoints": ["/cog/info", "/cog/tiles/{z}/{x}/{y}", "/cog/statistics"]
    },
    "xarray": {
      "status": "healthy",
      "available": true,
      "description": "Zarr/NetCDF multidimensional array tiles",
      "endpoints": ["/xarray/info", "/xarray/tiles/{z}/{x}/{y}"]
    },
    "pgstac": {
      "status": "healthy",
      "available": true,
      "description": "STAC mosaic searches and dynamic tiling",
      "endpoints": ["/searches/{search_id}/tiles", "/mosaic/tiles"]
    },
    "tipg": {
      "status": "healthy",
      "available": true,
      "description": "OGC Features API + Vector Tiles (MVT)",
      "endpoints": ["/vector/collections", "/vector/collections/{id}/items", "/vector/collections/{id}/tiles/{z}/{x}/{y}"],
      "details": {
        "collections_discovered": 42,
        "schemas": ["geo"],
        "router_prefix": "/vector"
      }
    },
    "stac_api": {
      "status": "healthy",
      "available": true,
      "description": "STAC catalog browsing and search",
      "endpoints": ["/stac", "/stac/collections", "/stac/search"],
      "details": {
        "router_prefix": "/stac"
      }
    }
  },
  "dependencies": {
    "database": {
      "status": "ok",
      "ping_time_ms": 12.5,
      "host": "rmhpostgres...",
      "required_by": ["pgstac", "tipg", "stac_api"]
    },
    "storage_oauth": {
      "status": "ok",
      "expires_in_seconds": 3456,
      "storage_account": "rmhazureblobs",
      "required_by": ["cog", "xarray"]
    },
    "postgres_oauth": {
      "status": "ok",
      "expires_in_seconds": 3456,
      "required_by": ["database"]
    }
  },
  "hardware": { /* unchanged */ },
  "issues": [],
  "config": { /* unchanged */ }
}
```

---

## Implementation

### File: `geotiler/routers/health.py`

### Step 1: Add Service Status Helper Function

Add after `_check_token_ready()` function (around line 354):

```python
def _build_service_status(
    name: str,
    available: bool,
    description: str,
    endpoints: list,
    details: dict = None,
    disabled_reason: str = None
) -> dict:
    """
    Build consistent service status dict.

    Args:
        name: Service name (for logging)
        available: Whether service is operational
        description: Human-readable description
        endpoints: List of endpoint patterns
        details: Optional service-specific details
        disabled_reason: Reason if service is disabled (e.g., "ENABLE_TIPG=false")

    Returns:
        Service status dict with consistent structure
    """
    if disabled_reason:
        return {
            "status": "disabled",
            "available": False,
            "description": description,
            "disabled_reason": disabled_reason
        }

    result = {
        "status": "healthy" if available else "unavailable",
        "available": available,
        "description": description,
        "endpoints": endpoints
    }

    if details:
        result["details"] = details

    return result
```

### Step 2: Refactor `/health` Endpoint

Replace the existing `/health` endpoint function (lines 105-332) with:

```python
@router.get("/health")
async def health(response: Response):
    """
    Full health check with diagnostic details for monitoring and debugging.

    Returns a structured response with:
    - services: Status of each service (cog, xarray, pgstac, tipg, stac_api)
    - dependencies: Status of shared dependencies (database, oauth tokens)
    - hardware: Runtime environment info
    - issues: List of any problems detected

    Status levels:
        - healthy: All systems operational (HTTP 200)
        - degraded: App running but some features unavailable (HTTP 503)
    """
    services = {}
    dependencies = {}
    issues = []

    # =========================================================================
    # DEPENDENCY CHECKS
    # =========================================================================

    # Database connection
    db_ok, db_error, ping_ms = ping_database_with_timing()
    pool_exists = get_db_pool() is not None

    dependencies["database"] = {
        "status": "ok" if db_ok else "fail",
        "pool_exists": pool_exists,
        "ping_success": db_ok,
        "required_by": ["pgstac", "tipg", "stac_api"],
    }

    if ping_ms is not None:
        dependencies["database"]["ping_time_ms"] = ping_ms
    if settings.postgres_host:
        dependencies["database"]["host"] = settings.postgres_host
    if db_error:
        dependencies["database"]["error"] = db_error
        issues.append(f"Database ping failed: {db_error}")
    elif not pool_exists:
        error_status = db_error_cache.get_status()
        if error_status["last_error"]:
            dependencies["database"]["error"] = error_status["last_error"]
            issues.append(f"Database connection failed: {error_status['last_error']}")
        else:
            issues.append("Database pool not initialized")

    # Add last success time
    error_status = db_error_cache.get_status()
    if error_status["last_success_time"]:
        dependencies["database"]["last_success"] = error_status["last_success_time"]

    # Storage OAuth token
    storage_oauth_ok = False
    if settings.use_azure_auth:
        token_status = storage_token_cache.get_status()
        if token_status["has_token"]:
            ttl = token_status["ttl_seconds"]
            storage_oauth_ok = ttl > 60  # At least 1 minute remaining
            dependencies["storage_oauth"] = {
                "status": "ok" if ttl > 300 else "warning",
                "expires_in_seconds": ttl,
                "storage_account": settings.azure_storage_account,
                "required_by": ["cog", "xarray"],
            }
            if ttl <= 300:
                issues.append(f"Storage OAuth token expires soon ({ttl}s)")
        else:
            dependencies["storage_oauth"] = {
                "status": "fail",
                "storage_account": settings.azure_storage_account,
                "required_by": ["cog", "xarray"],
            }
            issues.append("Storage OAuth token not initialized")
    else:
        storage_oauth_ok = True  # Not needed
        dependencies["storage_oauth"] = {
            "status": "disabled",
            "note": "Azure auth disabled - using anonymous/SAS access",
            "required_by": ["cog", "xarray"],
        }

    # PostgreSQL OAuth token (managed_identity mode only)
    if settings.postgres_auth_mode == "managed_identity":
        pg_status = postgres_token_cache.get_status()
        if pg_status["has_token"]:
            ttl = pg_status["ttl_seconds"]
            dependencies["postgres_oauth"] = {
                "status": "ok" if ttl > 300 else "warning",
                "expires_in_seconds": ttl,
                "required_by": ["database"],
            }
            if ttl <= 300:
                issues.append(f"PostgreSQL OAuth token expires soon ({ttl}s)")
        else:
            dependencies["postgres_oauth"] = {
                "status": "fail",
                "required_by": ["database"],
            }
            issues.append("PostgreSQL OAuth token not initialized")

    # =========================================================================
    # SERVICE STATUS
    # =========================================================================

    # COG Tiles (TiTiler core)
    cog_available = settings.use_azure_auth and storage_oauth_ok
    if not settings.use_azure_auth:
        # If no Azure auth, COG tiles work with public URLs
        cog_available = True

    services["cog"] = _build_service_status(
        name="cog",
        available=cog_available,
        description="Cloud-Optimized GeoTIFF tile serving",
        endpoints=["/cog/info", "/cog/tiles/{z}/{x}/{y}", "/cog/statistics", "/cog/preview"]
    )

    # XArray (Zarr/NetCDF)
    xarray_available = settings.use_azure_auth and storage_oauth_ok
    if not settings.use_azure_auth:
        xarray_available = True

    services["xarray"] = _build_service_status(
        name="xarray",
        available=xarray_available,
        description="Zarr/NetCDF multidimensional array tiles",
        endpoints=["/xarray/info", "/xarray/tiles/{z}/{x}/{y}"]
    )

    # pgSTAC Mosaic
    pgstac_available = db_ok
    services["pgstac"] = _build_service_status(
        name="pgstac",
        available=pgstac_available,
        description="STAC mosaic searches and dynamic tiling",
        endpoints=["/searches/{search_id}/info", "/searches/{search_id}/tiles/{z}/{x}/{y}", "/mosaic/tiles/{z}/{x}/{y}"]
    )
    if not pgstac_available:
        issues.append("pgSTAC mosaic unavailable - database connection required")

    # TiPG (OGC Features + Vector Tiles)
    tipg_ok = False
    if settings.enable_tipg:
        app_state = get_app_state()
        tipg_pool = getattr(app_state, "pool", None) if app_state else None
        tipg_catalog = getattr(app_state, "collection_catalog", None) if app_state else None

        if tipg_pool:
            tipg_ok = True
            collection_count = len(tipg_catalog) if tipg_catalog else 0
            services["tipg"] = _build_service_status(
                name="tipg",
                available=True,
                description="OGC Features API + Vector Tiles (MVT)",
                endpoints=[
                    "/vector/collections",
                    "/vector/collections/{id}",
                    "/vector/collections/{id}/items",
                    "/vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}"
                ],
                details={
                    "collections_discovered": collection_count,
                    "schemas": settings.tipg_schema_list,
                    "router_prefix": settings.tipg_router_prefix
                }
            )
        else:
            services["tipg"] = _build_service_status(
                name="tipg",
                available=False,
                description="OGC Features API + Vector Tiles (MVT)",
                endpoints=[],
                details={
                    "schemas": settings.tipg_schema_list,
                    "router_prefix": settings.tipg_router_prefix
                }
            )
            issues.append("TiPG pool not initialized - vector endpoints will fail")
    else:
        services["tipg"] = _build_service_status(
            name="tipg",
            available=False,
            description="OGC Features API + Vector Tiles (MVT)",
            endpoints=[],
            disabled_reason="ENABLE_TIPG=false"
        )

    # STAC API
    stac_ok = False
    if settings.enable_stac_api:
        if settings.enable_tipg and tipg_ok:
            stac_ok = True
            services["stac_api"] = _build_service_status(
                name="stac_api",
                available=True,
                description="STAC catalog browsing and search",
                endpoints=[
                    "/stac",
                    "/stac/collections",
                    "/stac/collections/{id}",
                    "/stac/collections/{id}/items",
                    "/stac/search"
                ],
                details={
                    "router_prefix": settings.stac_router_prefix,
                    "pool_shared_with": "tipg"
                }
            )
        elif not settings.enable_tipg:
            services["stac_api"] = _build_service_status(
                name="stac_api",
                available=False,
                description="STAC catalog browsing and search",
                endpoints=[],
                disabled_reason="Requires ENABLE_TIPG=true (shared database pool)"
            )
            issues.append("STAC API requires ENABLE_TIPG=true")
        else:
            services["stac_api"] = _build_service_status(
                name="stac_api",
                available=False,
                description="STAC catalog browsing and search",
                endpoints=[]
            )
            issues.append("STAC API pool not available")
    else:
        services["stac_api"] = _build_service_status(
            name="stac_api",
            available=False,
            description="STAC catalog browsing and search",
            endpoints=[],
            disabled_reason="ENABLE_STAC_API=false"
        )

    # Planetary Computer (optional)
    if settings.enable_planetary_computer:
        services["planetary_computer"] = _build_service_status(
            name="planetary_computer",
            available=True,
            description="Microsoft Planetary Computer data access",
            endpoints=["/pc/item/tiles", "/pc/item/info"]
        )

    # =========================================================================
    # OVERALL STATUS
    # =========================================================================
    has_critical_failure = not db_ok or (
        settings.use_azure_auth and not storage_token_cache.is_valid
    )

    if not issues:
        overall_status = "healthy"
        response.status_code = 200
    elif has_critical_failure:
        overall_status = "degraded"
        response.status_code = 503
    else:
        overall_status = "healthy"  # Warnings but functional
        response.status_code = 200

    # =========================================================================
    # RESPONSE
    # =========================================================================
    return {
        "status": overall_status,
        "version": __version__,
        "services": services,
        "dependencies": dependencies,
        "hardware": _get_hardware_info(),
        "issues": issues if issues else None,
        "config": {
            "postgres_auth_mode": settings.postgres_auth_mode,
            "azure_auth_enabled": settings.use_azure_auth,
            "local_mode": settings.local_mode,
            "tipg_enabled": settings.enable_tipg,
            "tipg_schemas": settings.tipg_schema_list if settings.enable_tipg else None,
            "stac_api_enabled": settings.enable_stac_api,
        },
    }
```

---

## Key Changes Summary

| Change | Before | After |
|--------|--------|-------|
| Service status location | `available_features` (booleans) | `services` (rich objects) |
| Dependency status location | `checks` | `dependencies` |
| Service descriptions | None | Each service has description |
| Endpoint documentation | None | Each service lists its endpoints |
| Service-specific details | Mixed in `checks` | Nested in `services.{name}.details` |
| `available_features` | Top-level object | **Removed** (replaced by `services.{name}.available`) |

---

## Response Size Impact

- **Before**: ~1.5KB typical response
- **After**: ~2.5KB typical response (+1KB for endpoint lists and descriptions)

This is acceptable for a monitoring endpoint called every 30-60 seconds.

---

## rmhgeoapi Integration

After this change, rmhgeoapi can consume the response like this:

```python
# In rmhgeoapi health check
health_body = response.json()

# Check overall container health
container_healthy = health_body["status"] == "healthy"

# Check individual services
tipg_available = health_body["services"]["tipg"]["available"]
stac_available = health_body["services"]["stac_api"]["available"]
cog_available = health_body["services"]["cog"]["available"]

# Get service details
tipg_collections = health_body["services"]["tipg"]["details"]["collections_discovered"]

# Check dependencies
db_ok = health_body["dependencies"]["database"]["status"] == "ok"
db_ping_ms = health_body["dependencies"]["database"].get("ping_time_ms")
```

---

## Testing

After implementation, verify:

```bash
# Local test
curl http://localhost:8000/health | jq

# Check services structure
curl http://localhost:8000/health | jq '.services'

# Check specific service
curl http://localhost:8000/health | jq '.services.tipg'

# Check dependencies
curl http://localhost:8000/health | jq '.dependencies'
```

---

## Version Bump

After implementing, bump version in `geotiler/__init__.py`:

```python
__version__ = "0.7.9.1"  # or next appropriate version
```

---

## Notes for Docker Claude

1. Keep the existing `/livez` and `/readyz` endpoints unchanged
2. The `_get_hardware_info()` function remains unchanged
3. The `_check_token_ready()` function remains unchanged
4. Remove the `available_features` section entirely - it's replaced by `services.{name}.available`
5. Test with `ENABLE_TIPG=false` to ensure disabled services report correctly
