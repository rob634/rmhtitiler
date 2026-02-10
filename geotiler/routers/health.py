"""
Health probe endpoints for Kubernetes and Azure App Service.

Provides three endpoints following Kubernetes probe conventions:
- /livez  - Liveness probe (is the container alive?)
- /readyz - Readiness probe (is the service ready for traffic?)
- /health - Full health check (detailed diagnostics)

The /health endpoint returns a structured response with:
- services: Status of each service (cog, xarray, pgstac, tipg, stac_api)
  - Each service has: status, available, description, endpoints, details
- dependencies: Status of shared dependencies (database, oauth tokens)
  - Each dependency has: status, required_by
- hardware: Runtime environment info (CPU, RAM, Azure metadata)
- issues: List of any problems detected
- config: Current configuration flags
"""

import sys
import os
import logging
from typing import Optional, Tuple

from fastapi import APIRouter, Request, Response

from geotiler import __version__
from geotiler.config import settings, READYZ_MIN_TTL_SECS
from geotiler.auth.cache import (
    storage_token_cache,
    postgres_token_cache,
    db_error_cache,
    TokenCache,
)
from geotiler.services.database import (
    ping_database_async,
    ping_database_with_timing_async,
    get_db_pool_from_request,
    get_app_state_from_request,
)

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
async def readiness(request: Request, response: Response):
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

    # Check 1: Database connection (async to avoid blocking event loop)
    db_ok, db_error = await ping_database_async(request)
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
async def health(request: Request, response: Response):
    """
    Full health check with diagnostic details for monitoring and debugging.

    Returns a structured response with:
    - services: Status of each service (cog, xarray, pgstac, tipg, stac_api)
    - dependencies: Status of shared dependencies (database, oauth tokens)
    - hardware: Runtime environment info
    - issues: List of any problems detected

    Use /readyz for Kubernetes readiness probes (faster, minimal response).
    Use this endpoint for dashboards, monitoring systems, and troubleshooting.

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

    # Database connection (async to avoid blocking event loop)
    db_ok, db_error, ping_ms = await ping_database_with_timing_async(request)
    pool_exists = get_db_pool_from_request(request) is not None

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
    cog_available = True
    if settings.use_azure_auth:
        cog_available = storage_oauth_ok

    services["cog"] = _build_service_status(
        name="cog",
        available=cog_available,
        description="Cloud-Optimized GeoTIFF tile serving",
        endpoints=["/cog/info", "/cog/tiles/{z}/{x}/{y}", "/cog/statistics", "/cog/preview"],
    )

    # XArray (Zarr/NetCDF)
    xarray_available = True
    if settings.use_azure_auth:
        xarray_available = storage_oauth_ok

    services["xarray"] = _build_service_status(
        name="xarray",
        available=xarray_available,
        description="Zarr/NetCDF multidimensional array tiles",
        endpoints=["/xarray/info", "/xarray/tiles/{z}/{x}/{y}"],
    )

    # pgSTAC Mosaic
    services["pgstac"] = _build_service_status(
        name="pgstac",
        available=db_ok,
        description="STAC mosaic searches and dynamic tiling",
        endpoints=[
            "/searches/{search_id}/info",
            "/searches/{search_id}/tiles/{z}/{x}/{y}",
            "/mosaic/tiles/{z}/{x}/{y}",
        ],
    )
    if not db_ok:
        issues.append("pgSTAC mosaic unavailable - database connection required")

    # TiPG (OGC Features + Vector Tiles)
    tipg_ok = False
    if settings.enable_tipg:
        app_state = get_app_state_from_request(request)
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
                    "/vector/collections/{id}/tiles/{tms}/{z}/{x}/{y}",
                ],
                details={
                    "collections_discovered": collection_count,
                    "schemas": settings.tipg_schema_list,
                    "router_prefix": settings.tipg_router_prefix,
                },
            )
        else:
            services["tipg"] = _build_service_status(
                name="tipg",
                available=False,
                description="OGC Features API + Vector Tiles (MVT)",
                endpoints=[],
                details={
                    "schemas": settings.tipg_schema_list,
                    "router_prefix": settings.tipg_router_prefix,
                },
            )
            issues.append("TiPG pool not initialized - vector endpoints will fail")
    else:
        services["tipg"] = _build_service_status(
            name="tipg",
            available=False,
            description="OGC Features API + Vector Tiles (MVT)",
            endpoints=[],
            disabled_reason="ENABLE_TIPG=false",
        )

    # H3 DuckDB (server-side query engine)
    if settings.enable_h3_duckdb:
        duckdb_state = getattr(request.app.state, "duckdb_state", None)
        if duckdb_state and duckdb_state.init_success:
            services["h3_duckdb"] = _build_service_status(
                name="h3_duckdb",
                available=True,
                description="H3 server-side DuckDB query engine",
                endpoints=["/h3/query"],
                details=duckdb_state.to_dict(),
            )
        else:
            services["h3_duckdb"] = _build_service_status(
                name="h3_duckdb",
                available=False,
                description="H3 server-side DuckDB query engine",
                endpoints=[],
                details=duckdb_state.to_dict() if duckdb_state else None,
            )
            issues.append("H3 DuckDB initialization failed")
    else:
        services["h3_duckdb"] = _build_service_status(
            name="h3_duckdb",
            available=False,
            description="H3 server-side DuckDB query engine",
            endpoints=[],
            disabled_reason="ENABLE_H3_DUCKDB=false",
        )

    # STAC API
    if settings.enable_stac_api:
        if settings.enable_tipg and tipg_ok:
            services["stac_api"] = _build_service_status(
                name="stac_api",
                available=True,
                description="STAC catalog browsing and search",
                endpoints=[
                    "/stac",
                    "/stac/collections",
                    "/stac/collections/{id}",
                    "/stac/collections/{id}/items",
                    "/stac/search",
                ],
                details={
                    "router_prefix": settings.stac_router_prefix,
                    "pool_shared_with": "tipg",
                },
            )
        elif not settings.enable_tipg:
            services["stac_api"] = _build_service_status(
                name="stac_api",
                available=False,
                description="STAC catalog browsing and search",
                endpoints=[],
                disabled_reason="Requires ENABLE_TIPG=true (shared database pool)",
            )
            issues.append("STAC API requires ENABLE_TIPG=true")
        else:
            services["stac_api"] = _build_service_status(
                name="stac_api",
                available=False,
                description="STAC catalog browsing and search",
                endpoints=[],
            )
            issues.append("STAC API pool not available")
    else:
        services["stac_api"] = _build_service_status(
            name="stac_api",
            available=False,
            description="STAC catalog browsing and search",
            endpoints=[],
            disabled_reason="ENABLE_STAC_API=false",
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
            "planetary_computer_enabled": settings.enable_planetary_computer,
            "h3_duckdb_enabled": settings.enable_h3_duckdb,
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


def _build_service_status(
    name: str,
    available: bool,
    description: str,
    endpoints: list,
    details: dict = None,
    disabled_reason: str = None,
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
            "disabled_reason": disabled_reason,
        }

    result = {
        "status": "healthy" if available else "unavailable",
        "available": available,
        "description": description,
        "endpoints": endpoints,
    }

    if details:
        result["details"] = details

    return result


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
