"""Authentication modules for Azure Storage and PostgreSQL."""

from geotiler.auth.cache import (
    TokenCache,
    ErrorCache,
    storage_token_cache,
    postgres_token_cache,
    db_error_cache,
)
from geotiler.auth.storage import (
    get_storage_oauth_token,
    get_storage_oauth_token_async,
    configure_gdal_auth,
    configure_fsspec_auth,
    initialize_storage_auth,
    refresh_storage_token,
    refresh_storage_token_async,
)
from geotiler.auth.postgres import (
    get_postgres_credential,
    get_postgres_credential_async,
    build_database_url,
    refresh_postgres_token,
    refresh_postgres_token_async,
)

__all__ = [
    # Cache classes
    "TokenCache",
    "ErrorCache",
    # Cache instances
    "storage_token_cache",
    "postgres_token_cache",
    "db_error_cache",
    # Storage auth (sync)
    "get_storage_oauth_token",
    "configure_gdal_auth",
    "configure_fsspec_auth",
    "initialize_storage_auth",
    "refresh_storage_token",
    # Storage auth (async)
    "get_storage_oauth_token_async",
    "refresh_storage_token_async",
    # Postgres auth (sync)
    "get_postgres_credential",
    "build_database_url",
    "refresh_postgres_token",
    # Postgres auth (async)
    "get_postgres_credential_async",
    "refresh_postgres_token_async",
]
