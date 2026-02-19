"""
Configuration management for geotiler.

Uses Pydantic Settings for type-safe configuration with environment variable support.
All magic numbers are extracted as named constants.

Naming Convention:
    All application env vars follow GEOTILER_COMPONENT_SETTING with units in names.
    Third-party vars (AZURE_TENANT_ID, APPLICATIONINSIGHTS_CONNECTION_STRING,
    GDAL_*, POSTGRES_HOST/DB/USER/PORT/PASSWORD for pgSTAC container) are NOT prefixed.

    Boolean flags read as questions: GEOTILER_ENABLE_*
    Time values include units: *_SEC, *_MS

Key Configuration Notes:
    - Token TTL constants are tuned for Azure's 1-hour OAuth token lifetime
    - Storage tokens are refreshed in background to ensure GDAL always has valid credentials
    - MosaicJSON is intentionally unsupported (requires static tokens)

Observability (read via os.environ in infrastructure modules):
    - APPLICATIONINSIGHTS_CONNECTION_STRING: App Insights telemetry (third-party)
    - GEOTILER_ENABLE_OBSERVABILITY: Enable detailed request/latency logging
    - GEOTILER_OBS_SLOW_THRESHOLD_MS: Slow request threshold (default: 2000ms)
    - GEOTILER_OBS_SERVICE_NAME: Service name for correlation (default: geotiler)
    - GEOTILER_OBS_ENVIRONMENT: Deployment environment (default: dev)

UI Configuration:
    - GEOTILER_UI_SAMPLE_ZARR_URLS: JSON array of Zarr/NetCDF sample datasets for landing pages
"""

import json
import logging
import os
from typing import Optional, List
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    Boolean values accept: true/false, 1/0, yes/no (case-insensitive).

    Env var prefix: GEOTILER_ (auto-applied to all fields).
    """

    model_config = SettingsConfigDict(
        env_prefix="GEOTILER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # Auth — GEOTILER_ENABLE_STORAGE_AUTH, GEOTILER_STORAGE_ACCOUNT, GEOTILER_AUTH_USE_CLI
    # =========================================================================
    enable_storage_auth: bool = False
    """Enable Azure OAuth for blob storage access (was USE_AZURE_AUTH)."""

    storage_account: Optional[str] = None
    """Azure Storage account name for GDAL access."""

    auth_use_cli: bool = True
    """Use Azure CLI credentials instead of Managed Identity (for local dev)."""

    # =========================================================================
    # PostgreSQL — GEOTILER_PG_*
    # =========================================================================
    pg_auth_mode: str = "password"
    """Authentication mode: 'password', 'key_vault', or 'managed_identity'."""

    pg_host: Optional[str] = None
    """PostgreSQL server hostname."""

    pg_db: Optional[str] = None
    """PostgreSQL database name."""

    pg_user: Optional[str] = None
    """PostgreSQL username."""

    pg_port: int = 5432
    """PostgreSQL port."""

    pg_password: Optional[str] = None
    """PostgreSQL password (for 'password' auth mode)."""

    pg_mi_client_id: Optional[str] = None
    """User-assigned Managed Identity client ID for PostgreSQL auth."""

    # =========================================================================
    # Key Vault — GEOTILER_KEYVAULT_*
    # =========================================================================
    keyvault_name: Optional[str] = None
    """Azure Key Vault name (for 'key_vault' auth mode)."""

    keyvault_secret_name: str = "postgres-password"
    """Secret name in Key Vault containing PostgreSQL password."""

    # =========================================================================
    # Feature Flags — GEOTILER_ENABLE_*
    # =========================================================================
    enable_tipg: bool = True
    """Enable TiPG OGC Features + Vector Tiles API."""

    enable_stac_api: bool = True
    """Enable STAC API for catalog browsing and search."""

    enable_h3_duckdb: bool = False
    """Enable server-side DuckDB for H3 queries. Requires GEOTILER_H3_PARQUET_URL."""

    # =========================================================================
    # TiPG — GEOTILER_TIPG_*
    # =========================================================================
    tipg_schemas: str = "geo"
    """Comma-separated list of PostGIS schemas to expose via TiPG."""

    tipg_prefix: str = "/vector"
    """URL prefix for TiPG routes (e.g., /vector/collections)."""

    tipg_geometry_column: str = "geom"
    """Expected geometry column name (for diagnostics)."""

    enable_tipg_catalog_ttl: bool = False
    """Enable automatic catalog refresh via CatalogUpdateMiddleware.
    Disabled by default — use the /admin/refresh-collections webhook instead."""

    tipg_catalog_ttl_sec: int = 60
    """Catalog refresh interval in seconds.
    Only applies when GEOTILER_ENABLE_TIPG_CATALOG_TTL=true."""

    @property
    def tipg_schema_list(self) -> list[str]:
        """Parse comma-separated schemas into list."""
        return [s.strip() for s in self.tipg_schemas.split(",") if s.strip()]

    # =========================================================================
    # STAC — GEOTILER_STAC_*
    # =========================================================================
    stac_prefix: str = "/stac"
    """URL prefix for STAC API routes (e.g., /stac/collections)."""

    # =========================================================================
    # Admin — GEOTILER_ENABLE_ADMIN_AUTH, GEOTILER_ADMIN_ALLOWED_APP_IDS
    # =========================================================================
    enable_admin_auth: bool = False
    """Enable Azure AD authentication for /admin/* endpoints.
    When disabled, admin endpoints are open (for local dev)."""

    admin_allowed_app_ids: str = ""
    """Comma-separated list of Azure AD app/client IDs allowed to call /admin/*.
    Typically the Orchestrator app's Managed Identity client ID."""

    azure_tenant_id: Optional[str] = Field(
        default=None, validation_alias="AZURE_TENANT_ID"
    )
    """Azure AD tenant ID for token validation.
    Read from AZURE_TENANT_ID (shared with Azure Identity SDK)."""

    @property
    def admin_allowed_app_id_list(self) -> list[str]:
        """Parse comma-separated app IDs into list."""
        if not self.admin_allowed_app_ids:
            return []
        return [s.strip() for s in self.admin_allowed_app_ids.split(",") if s.strip()]

    # =========================================================================
    # UI — GEOTILER_UI_*
    # =========================================================================
    ui_sample_zarr_urls: str = "[]"
    """JSON array of Zarr/NetCDF sample URLs for the /xarray/ landing page."""

    @property
    def sample_zarr_urls(self) -> List[dict]:
        """Parse Zarr sample URLs from JSON environment variable."""
        return self._parse_json_list(self.ui_sample_zarr_urls, "GEOTILER_UI_SAMPLE_ZARR_URLS")

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
    # H3 Explorer — GEOTILER_H3_*
    # =========================================================================
    h3_parquet_url: str = ""
    """URL to the H3 Level 5 GeoParquet file for the crop/drought explorer."""

    h3_data_dir: str = "/app/data"
    """Local directory for cached parquet file."""

    h3_parquet_filename: str = "h3_data.parquet"
    """Filename for the local parquet cache."""

    # =========================================================================
    # Computed Properties
    # =========================================================================
    @property
    def has_postgres_config(self) -> bool:
        """Check if minimum PostgreSQL configuration is present."""
        return all([self.pg_host, self.pg_db, self.pg_user])


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

@lru_cache
def get_settings() -> Settings:
    """
    Get cached Settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Convenience alias for direct import
settings = get_settings()
