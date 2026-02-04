"""
Configuration management for geotiler.

Uses Pydantic Settings for type-safe configuration with environment variable support.
All magic numbers are extracted as named constants.

Key Configuration Notes:
    - Token TTL constants are tuned for Azure's 1-hour OAuth token lifetime
    - Storage tokens are refreshed in background to ensure GDAL always has valid credentials
    - MosaicJSON is intentionally unsupported (requires static tokens)

Observability Configuration:
    See infrastructure/telemetry.py for Azure Monitor OpenTelemetry setup.
    Key environment variables:
    - APPLICATIONINSIGHTS_CONNECTION_STRING: Enable App Insights telemetry
    - OBSERVABILITY_MODE: Enable detailed request/latency logging
    - SLOW_REQUEST_THRESHOLD_MS: Slow request threshold (default: 2000ms)

UI Configuration:
    Sample URLs for landing pages are configured via JSON environment variables:
    - SAMPLE_COG_URLS: JSON array of COG sample datasets
    - SAMPLE_ZARR_URLS: JSON array of Zarr/NetCDF sample datasets
    - SAMPLE_STAC_COLLECTIONS: JSON array of STAC collections to highlight
"""

import json
import logging
import os
from typing import Optional, Dict, List
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    Boolean values accept: true/false, 1/0, yes/no (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # Azure Storage Authentication
    # =========================================================================
    use_azure_auth: bool = False
    """Enable Azure OAuth for blob storage access."""

    azure_storage_account: Optional[str] = None
    """Azure Storage account name for GDAL access."""

    local_mode: bool = True
    """Use Azure CLI credentials instead of Managed Identity (for local dev)."""

    # =========================================================================
    # PostgreSQL Authentication
    # =========================================================================
    postgres_auth_mode: str = "password"
    """Authentication mode: 'password', 'key_vault', or 'managed_identity'."""

    postgres_host: Optional[str] = None
    """PostgreSQL server hostname."""

    postgres_db: Optional[str] = None
    """PostgreSQL database name."""

    postgres_user: Optional[str] = None
    """PostgreSQL username."""

    postgres_port: int = 5432
    """PostgreSQL port."""

    postgres_password: Optional[str] = None
    """PostgreSQL password (for 'password' auth mode)."""

    postgres_mi_client_id: Optional[str] = None
    """User-assigned Managed Identity client ID for PostgreSQL auth."""

    # =========================================================================
    # Azure Key Vault
    # =========================================================================
    key_vault_name: Optional[str] = None
    """Azure Key Vault name (for 'key_vault' auth mode)."""

    key_vault_secret_name: str = "postgres-password"
    """Secret name in Key Vault containing PostgreSQL password."""

    # =========================================================================
    # Feature Flags
    # =========================================================================
    enable_planetary_computer: bool = True
    """Enable Planetary Computer credential provider for climate data."""

    enable_tipg: bool = True
    """Enable TiPG OGC Features + Vector Tiles API."""

    # =========================================================================
    # TiPG Configuration (OGC Features + Vector Tiles)
    # =========================================================================
    tipg_schemas: str = "geo"
    """Comma-separated list of PostGIS schemas to expose via TiPG."""

    tipg_router_prefix: str = "/vector"
    """URL prefix for TiPG routes (e.g., /vector/collections)."""

    ogc_geometry_column: str = "geom"
    """Expected geometry column name (for diagnostics). Should match ETL app's OGC_GEOMETRY_COLUMN."""

    tipg_catalog_ttl_enabled: bool = False
    """Enable automatic catalog refresh via CatalogUpdateMiddleware.
    When enabled, TiPG will periodically re-scan the database for new tables.
    Disabled by default - use the /admin/refresh-collections webhook for explicit control."""

    tipg_catalog_ttl: int = 300
    """Catalog refresh interval in seconds (default: 300 = 5 minutes).
    Only applies when tipg_catalog_ttl_enabled=true.
    Lower values = faster new table detection but more DB queries."""

    @property
    def tipg_schema_list(self) -> list[str]:
        """Parse comma-separated schemas into list."""
        return [s.strip() for s in self.tipg_schemas.split(",") if s.strip()]

    # =========================================================================
    # STAC API Configuration (stac-fastapi-pgstac)
    # =========================================================================
    enable_stac_api: bool = True
    """Enable STAC API for catalog browsing and search."""

    stac_router_prefix: str = "/stac"
    """URL prefix for STAC API routes (e.g., /stac/collections)."""

    # =========================================================================
    # Admin Endpoint Authentication (Azure AD)
    # =========================================================================
    admin_auth_enabled: bool = False
    """Enable Azure AD authentication for /admin/* endpoints.
    When disabled, admin endpoints are open (for local dev)."""

    admin_allowed_app_ids: str = ""
    """Comma-separated list of Azure AD app/client IDs allowed to call /admin/* endpoints.
    Typically the Orchestrator app's Managed Identity client ID."""

    azure_tenant_id: Optional[str] = None
    """Azure AD tenant ID for token validation. Required when admin_auth_enabled=true."""

    @property
    def admin_allowed_app_id_list(self) -> list[str]:
        """Parse comma-separated app IDs into list."""
        if not self.admin_allowed_app_ids:
            return []
        return [s.strip() for s in self.admin_allowed_app_ids.split(",") if s.strip()]

    # =========================================================================
    # UI Sample URLs (Landing Pages)
    # =========================================================================
    # These are JSON arrays passed via environment variables.
    # Example: SAMPLE_COG_URLS='[{"label": "...", "url": "...", "description": "..."}]'

    sample_cog_urls_json: str = "[]"
    """JSON array of COG sample URLs for the /cog/ landing page."""

    sample_zarr_urls_json: str = "[]"
    """JSON array of Zarr/NetCDF sample URLs for the /xarray/ landing page."""

    sample_stac_collections_json: str = "[]"
    """JSON array of STAC collections to highlight in the explorer."""

    @property
    def sample_cog_urls(self) -> List[dict]:
        """Parse COG sample URLs from JSON environment variable."""
        return self._parse_json_list(self.sample_cog_urls_json, "SAMPLE_COG_URLS")

    @property
    def sample_zarr_urls(self) -> List[dict]:
        """Parse Zarr sample URLs from JSON environment variable."""
        return self._parse_json_list(self.sample_zarr_urls_json, "SAMPLE_ZARR_URLS")

    @property
    def sample_stac_collections(self) -> List[dict]:
        """Parse STAC collection highlights from JSON environment variable."""
        return self._parse_json_list(self.sample_stac_collections_json, "SAMPLE_STAC_COLLECTIONS")

    def _parse_json_list(self, json_str: str, var_name: str) -> List[dict]:
        """Safely parse a JSON array, returning empty list on error."""
        if not json_str or json_str.strip() == "":
            return []
        try:
            result = json.loads(json_str)
            if not isinstance(result, list):
                logging.warning(f"{var_name} must be a JSON array, got {type(result).__name__}")
                return []
            return result
        except json.JSONDecodeError as e:
            logging.warning(f"Failed to parse {var_name} as JSON: {e}")
            return []

    # =========================================================================
    # Observability (see also: infrastructure/telemetry.py)
    # =========================================================================
    # Note: These are read directly via os.environ in infrastructure modules
    # for zero-import-overhead when disabled. Listed here for documentation.
    #
    # APPLICATIONINSIGHTS_CONNECTION_STRING: App Insights connection string
    #   - When set, enables Azure Monitor OpenTelemetry integration
    #   - Logs, traces, and HTTP requests flow to App Insights
    #
    # OBSERVABILITY_MODE: Enable detailed request/latency logging
    #   - Default: false (zero overhead)
    #   - When true: Logs request timing, status codes, response sizes
    #
    # SLOW_REQUEST_THRESHOLD_MS: Slow request threshold in milliseconds
    #   - Default: 2000
    #   - Requests exceeding this are logged as warnings with [SLOW] tag
    #
    # APP_NAME: Service name for correlation (default: geotiler)
    # ENVIRONMENT: Deployment environment (default: dev)

    # =========================================================================
    # Computed Properties
    # =========================================================================
    @property
    def has_postgres_config(self) -> bool:
        """Check if minimum PostgreSQL configuration is present."""
        return all([self.postgres_host, self.postgres_db, self.postgres_user])


# =============================================================================
# Constants (extracted magic numbers)
# =============================================================================

# Token refresh timing
TOKEN_REFRESH_BUFFER_SECS: int = 300
"""Refresh tokens when less than 5 minutes until expiry."""

READYZ_MIN_TTL_SECS: int = 60
"""Mark not ready if token expires in less than 1 minute."""

BACKGROUND_REFRESH_INTERVAL_SECS: int = 45 * 60
"""Background token refresh interval (45 minutes)."""

# Tile rendering
TILE_SIZE: int = 256
"""Standard web map tile size in pixels."""

# Azure OAuth scopes
STORAGE_SCOPE: str = "https://storage.azure.com/.default"
"""OAuth scope for Azure Blob Storage."""

POSTGRES_SCOPE: str = "https://ossrdbms-aad.database.windows.net/.default"
"""OAuth scope for Azure Database for PostgreSQL."""

# Planetary Computer storage accounts
# Maps storage account name -> default collection ID
PC_STORAGE_ACCOUNTS: Dict[str, str] = {
    "rhgeuwest": "cil-gdpcir-cc0",  # Climate Impact Lab CMIP6 projections
    "ai4edataeuwest": "daymet-daily-na",  # gridMET, Daymet climate data
}


@lru_cache
def get_settings() -> Settings:
    """
    Get cached Settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Convenience alias for direct import
settings = get_settings()
