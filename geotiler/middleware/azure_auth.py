"""
Azure authentication middleware.

Ensures Azure Storage OAuth authentication is configured before each request.
"""

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from geotiler.config import settings
from geotiler.auth.storage import (
    get_storage_oauth_token_async,
    configure_gdal_auth,
    configure_fsspec_auth,
)

logger = logging.getLogger(__name__)


# Paths that never need storage auth — skip to avoid unnecessary work
_SKIP_AUTH_PREFIXES = (
    "/livez", "/readyz", "/health",
    "/static/", "/docs", "/redoc", "/openapi.json",
    "/api", "/_health-fragment",
)


class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage OAuth authentication is set before each request.

    Configures authentication for:
    - GDAL: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN (for /vsiaz/ COG access)
    - fsspec/adlfs: AZURE_STORAGE_ACCOUNT_NAME (for abfs:// Zarr access)

    Skips paths that don't access storage (health probes, static files, docs).

    Note: Token acquisition uses asyncio.to_thread() to avoid blocking the event loop
    when the Azure SDK makes HTTP calls to acquire/refresh tokens.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Fast path: skip auth for non-storage endpoints
        if path.startswith(_SKIP_AUTH_PREFIXES):
            return await call_next(request)

        if settings.use_azure_auth and settings.azure_storage_account:
            try:
                # Get OAuth token (uses cache if valid)
                # Runs in thread pool to avoid blocking event loop during token refresh
                token = await get_storage_oauth_token_async()

                if token:
                    # Configure GDAL for COG access via /vsiaz/
                    configure_gdal_auth(token)

                    # Configure fsspec/adlfs for Zarr access
                    configure_fsspec_auth()

                    logger.debug(f"Auth configured, token length: {len(token)} chars")
                else:
                    logger.warning("No OAuth token available for request")

            except Exception as e:
                logger.error(f"Error in Azure OAuth authentication: {e}", exc_info=True)

        response = await call_next(request)
        return response
