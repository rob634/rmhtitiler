"""
Configuration management for rmhtitiler.

Uses Pydantic Settings for type-safe configuration with environment variable support.
All magic numbers are extracted as named constants.

Key Configuration Notes:
    - Token TTL constants are tuned for Azure's 1-hour OAuth token lifetime
    - Storage tokens are refreshed in background to ensure GDAL always has valid credentials
    - MosaicJSON is intentionally unsupported (requires static tokens)
"""

import os
from typing import Optional, Dict
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
