"""
Health probe endpoints for Kubernetes and Azure App Service.

Provides three endpoints following Kubernetes probe conventions:
- /livez  - Liveness probe (is the container alive?)
- /readyz - Readiness probe (is the service ready for traffic?)
- /health - Full health check (detailed diagnostics)

The /health endpoint reports available_features which reflects the supported
endpoints in this deployment:
- cog_tiles: /cog/* endpoints (requires Azure OAuth)
- xarray_zarr: /xarray/* endpoints (requires Azure OAuth)
- pgstac_searches: /searches/* endpoints (requires database)
- planetary_computer: /pc/* endpoints (optional)
- mosaic_json: Always False - legacy endpoint, incompatible with OAuth/MI
"""

import sys
import os
import logging
from typing import Optional, Tuple

from fastapi import APIRouter, Response

from rmhtitiler import __version__
from rmhtitiler.config import settings, READYZ_MIN_TTL_SECS
from rmhtitiler.auth.cache import (
    storage_token_cache,
    postgres_token_cache,
    db_error_cache,
    TokenCache,
)
from rmhtitiler.services.database import ping_database, ping_database_with_timing, get_db_pool, get_app_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/livez")
async def liveness():
    """
    Liveness probe - responds immediately to indicate container is running.

    This endpoint is for Kubernetes/Azure App Service liveness probes. It responds
    before database connection is established, preventing the container from being
    killed during slow database connections or MI token acquisition.

    Use /readyz for readiness checks, /health for full diagnostics.
    """
    return {
        "status": "alive",
        "message": "Container is running",
    }


@router.get("/readyz")
async def readiness(response: Response):
    """
    Kubernetes-style readiness probe.

    Checks critical dependencies to determine if the service can handle traffic.
    Returns minimal response for efficiency - use /health for full diagnostics.

    Returns:
        HTTP 200: Ready to receive traffic
        HTTP 503: Not ready (dependency failure)

    Checks performed:
        1. Database connection with active ping (required for pgSTAC)
        2. Storage OAuth token validity (required for Azure blob access)
        3. PostgreSQL OAuth token validity (if using managed identity)
    """
    ready = True
    issues = []

    # Check 1: Database connection
    db_ok, db_error = ping_database()
    if not db_ok:
        ready = False
        issues.append(f"database: {db_error}")

    # Check 2: Storage OAuth token (if Azure auth enabled)
    if settings.use_azure_auth:
        token_ok, token_issue = _check_token_ready(storage_token_cache, "storage_oauth")
        if not token_ok:
            ready = False
            issues.append(token_issue)

    # Check 3: PostgreSQL OAuth token (if using managed identity)
    if settings.postgres_auth_mode == "managed_identity":
        pg_ok, pg_issue = _check_token_ready(postgres_token_cache, "postgres_oauth")
        if not pg_ok:
            ready = False
            issues.append(pg_issue)

    response.status_code = 200 if ready else 503
    return {
        "ready": ready,
        "version": __version__,
        "issues": issues if issues else None,
    }


@router.get("/health")
async def health(response: Response):
    """
    Full health check with diagnostic details for monitoring and debugging.

    Use /readyz for Kubernetes readiness probes (faster, minimal response).
    Use this endpoint for dashboards, monitoring systems, and troubleshooting.

    Returns HTTP 200 for healthy, HTTP 503 for degraded/unhealthy.
    Response body always includes detailed status for debugging.

    Status levels:
        - healthy: All systems operational (HTTP 200)
        - degraded: App running but some features unavailable (HTTP 503)

    Checks performed:
        1. Database connection with active ping
        2. Storage OAuth token validity
        3. PostgreSQL OAuth token (if using managed identity)
        4. Hardware/runtime info
    """
    checks = {}
    issues = []

    # =========================================================================
    # Check 1: Database connection
    # =========================================================================
    db_ok, db_error, ping_ms = ping_database_with_timing()
    pool_exists = get_db_pool() is not None

    checks["database"] = {
        "status": "ok" if db_ok else "fail",
        "pool_exists": pool_exists,
        "ping_success": db_ok,
        "required_for": ["pgSTAC searches", "mosaic endpoints"],
    }

    if ping_ms is not None:
        checks["database"]["ping_time_ms"] = ping_ms

    # Add host info if available
    if settings.postgres_host:
        checks["database"]["host"] = settings.postgres_host

    # Add error details
    if db_error:
        checks["database"]["error"] = db_error
        issues.append(f"Database ping failed: {db_error}")
    elif not pool_exists:
        error_status = db_error_cache.get_status()
        if error_status["last_error"]:
            checks["database"]["error"] = error_status["last_error"]
            if error_status["last_error_time"]:
                checks["database"]["error_time"] = error_status["last_error_time"]
            issues.append(f"Database connection failed: {error_status['last_error']}")
        else:
            issues.append("Database pool not initialized - pgSTAC endpoints will fail")

    # Add last success time
    error_status = db_error_cache.get_status()
    if error_status["last_success_time"]:
        checks["database"]["last_success"] = error_status["last_success_time"]

    # =========================================================================
    # Check 2: Storage OAuth token
    # =========================================================================
    if settings.use_azure_auth:
        token_status = storage_token_cache.get_status()
        if token_status["has_token"]:
            ttl = token_status["ttl_seconds"]
            checks["storage_oauth"] = {
                "status": "ok" if ttl > 300 else "warning",
                "expires_in_seconds": ttl,
                "storage_account": settings.azure_storage_account,
                "required_for": ["Azure blob storage access"],
            }
            if ttl <= 300:
                issues.append(f"OAuth token expires soon ({ttl}s) - may cause access issues")
        else:
            checks["storage_oauth"] = {
                "status": "fail",
                "storage_account": settings.azure_storage_account,
                "required_for": ["Azure blob storage access"],
            }
            issues.append("Storage OAuth token not initialized - cannot access Azure blobs")
    else:
        checks["storage_oauth"] = {
            "status": "disabled",
            "note": "Azure auth disabled - using anonymous/SAS access",
        }

    # =========================================================================
    # Check 3: PostgreSQL OAuth token (managed_identity mode only)
    # =========================================================================
    if settings.postgres_auth_mode == "managed_identity":
        pg_status = postgres_token_cache.get_status()
        if pg_status["has_token"]:
            ttl = pg_status["ttl_seconds"]
            checks["postgres_oauth"] = {
                "status": "ok" if ttl > 300 else "warning",
                "expires_in_seconds": ttl,
                "required_for": ["PostgreSQL database connection"],
            }
            if ttl <= 300:
                issues.append(f"PostgreSQL OAuth token expires soon ({ttl}s)")
        else:
            checks["postgres_oauth"] = {
                "status": "fail",
                "required_for": ["PostgreSQL database connection"],
            }
            issues.append("PostgreSQL OAuth token not initialized")

    # =========================================================================
    # Check 4: TiPG pool (OGC Features + Vector Tiles)
    # =========================================================================
    tipg_ok = False
    if settings.enable_tipg:
        app_state = get_app_state()
        tipg_pool = getattr(app_state, "pool", None) if app_state else None
        tipg_catalog = getattr(app_state, "collection_catalog", None) if app_state else None

        if tipg_pool:
            tipg_ok = True
            collection_count = len(tipg_catalog) if tipg_catalog else 0
            checks["tipg"] = {
                "status": "ok",
                "pool_exists": True,
                "collections_discovered": collection_count,
                "schemas": settings.tipg_schema_list,
                "router_prefix": settings.tipg_router_prefix,
                "required_for": ["OGC Features API", "Vector Tiles"],
            }
        else:
            checks["tipg"] = {
                "status": "fail",
                "pool_exists": False,
                "schemas": settings.tipg_schema_list,
                "required_for": ["OGC Features API", "Vector Tiles"],
            }
            issues.append("TiPG pool not initialized - vector endpoints will fail")
    else:
        checks["tipg"] = {
            "status": "disabled",
            "note": "TiPG disabled via ENABLE_TIPG=false",
        }

    # =========================================================================
    # Determine overall status
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
    # Hardware/runtime info
    # =========================================================================
    hardware = _get_hardware_info()

    return {
        "status": overall_status,
        "version": __version__,
        "checks": checks,
        "hardware": hardware,
        "issues": issues if issues else None,
        "config": {
            "postgres_auth_mode": settings.postgres_auth_mode,
            "azure_auth_enabled": settings.use_azure_auth,
            "local_mode": settings.local_mode,
            "tipg_enabled": settings.enable_tipg,
            "tipg_schemas": settings.tipg_schema_list if settings.enable_tipg else None,
        },
        "available_features": {
            "cog_tiles": settings.use_azure_auth and storage_token_cache.is_valid,
            "xarray_zarr": settings.use_azure_auth and storage_token_cache.is_valid,
            "planetary_computer": settings.enable_planetary_computer,
            "pgstac_searches": db_ok,
            # MosaicJSON requires static tokens - incompatible with OAuth/MI
            "mosaic_json": False,  # Legacy endpoint, use pgstac_searches instead
            # TiPG OGC Features + Vector Tiles
            "ogc_features": settings.enable_tipg and tipg_ok,
            "vector_tiles": settings.enable_tipg and tipg_ok,
        },
    }


def _check_token_ready(cache: TokenCache, name: str) -> Tuple[bool, str]:
    """
    Check if token cache is valid for readiness.

    Args:
        cache: TokenCache instance to check.
        name: Name for error messages (e.g., "storage_oauth").

    Returns:
        Tuple of (is_ready: bool, error_message: str)
    """
    if not cache.token:
        return False, f"{name}: no token"

    ttl = cache.ttl_seconds()
    if ttl is not None and ttl < READYZ_MIN_TTL_SECS:
        return False, f"{name}: expires in {int(ttl)}s"

    return True, ""


def _get_hardware_info() -> dict:
    """
    Get hardware and runtime environment info.

    Returns:
        Dict with CPU, memory, and Azure environment details.
    """
    try:
        import psutil

        mem = psutil.virtual_memory()
        process = psutil.Process()

        return {
            "cpu_count": psutil.cpu_count() or 0,
            "total_ram_gb": round(mem.total / (1024**3), 2),
            "available_ram_mb": round(mem.available / (1024**2), 1),
            "ram_utilization_percent": round(mem.percent, 1),
            "cpu_utilization_percent": round(psutil.cpu_percent(interval=None), 1),
            "process_rss_mb": round(process.memory_info().rss / (1024**2), 1),
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            # Azure App Service environment variables
            "azure_site_name": os.environ.get("WEBSITE_SITE_NAME", "local"),
            "azure_sku": os.environ.get("WEBSITE_SKU", "unknown"),
            "azure_instance_id": (
                os.environ.get("WEBSITE_INSTANCE_ID", "")[:16]
                if os.environ.get("WEBSITE_INSTANCE_ID")
                else None
            ),
            "azure_region": os.environ.get("REGION_NAME", "unknown"),
        }
    except Exception as e:
        return {"error": str(e)}
