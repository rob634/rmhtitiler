"""
Azure authentication middleware (pure ASGI).

Ensures Azure Storage OAuth authentication is configured before each request.
Uses pure ASGI middleware instead of Starlette's BaseHTTPMiddleware to avoid
the known exception-swallowing bug (encode/starlette#1012).
"""

import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from geotiler.config import settings
from geotiler.auth.storage import (
    get_storage_oauth_token_async,
    configure_storage_auth,
)

logger = logging.getLogger(__name__)


# Paths that never need storage auth — skip to avoid unnecessary work
_SKIP_AUTH_PREFIXES = (
    "/livez", "/readyz", "/health",
    "/static/", "/docs", "/redoc", "/openapi.json",
    "/api", "/_health-fragment",
    "/vector", "/h3",   # PostGIS/DuckDB — no blob storage auth needed
    "/admin",            # uses its own Azure AD auth
)


class AzureAuthMiddleware:
    """
    Pure ASGI middleware for Azure Storage OAuth authentication.

    Configures authentication for:
    - GDAL: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN (for /vsiaz/ COG access)
    - obstore: AZURE_STORAGE_ACCOUNT_NAME + AZURE_STORAGE_TOKEN (for abfs:// Zarr access)

    Skips paths that don't access storage (health probes, static files, docs).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        # Fast path: skip auth for non-storage endpoints
        if path.startswith(_SKIP_AUTH_PREFIXES):
            await self.app(scope, receive, send)
            return

        if settings.enable_storage_auth and settings.storage_account:
            try:
                token = await get_storage_oauth_token_async()

                if token:
                    configure_storage_auth(token)
                    logger.debug(f"Auth configured, token length: {len(token)} chars")
                else:
                    logger.warning("No OAuth token available for request")

            except Exception:
                logger.error("Error in Azure OAuth authentication", exc_info=True)
                # Return 503 directly via ASGI
                await _send_error(send, 503, "Storage authentication unavailable")
                return

        await self.app(scope, receive, send)


async def _send_error(send: Send, status: int, message: str) -> None:
    """Send an error response directly via ASGI."""
    body = message.encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            [b"content-type", b"text/plain; charset=utf-8"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })
