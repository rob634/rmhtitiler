"""Authentication modules for Azure Storage and PostgreSQL."""

from rmhtitiler.auth.cache import (
    TokenCache,
    ErrorCache,
    storage_token_cache,
    postgres_token_cache,
    db_error_cache,
)
from rmhtitiler.auth.storage import (
    get_storage_oauth_token,
    configure_gdal_auth,
    configure_fsspec_auth,
    initialize_storage_auth,
    refresh_storage_token,
)
from rmhtitiler.auth.postgres import (
    get_postgres_credential,
    build_database_url,
    refresh_postgres_token,
)

__all__ = [
    # Cache classes
    "TokenCache",
    "ErrorCache",
    # Cache instances
    "storage_token_cache",
    "postgres_token_cache",
    "db_error_cache",
    # Storage auth
    "get_storage_oauth_token",
    "configure_gdal_auth",
    "configure_fsspec_auth",
    "initialize_storage_auth",
    "refresh_storage_token",
    # Postgres auth
    "get_postgres_credential",
    "build_database_url",
    "refresh_postgres_token",
]
