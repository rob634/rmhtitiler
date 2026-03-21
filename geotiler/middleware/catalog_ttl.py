"""
TTL-based TiPG catalog refresh middleware.

Replaces tipg's CatalogUpdateMiddleware with a version that reuses
geotiler's refresh_tipg_pool() — ensuring the TTL path gets the same
lock, credential refresh, and diagnostics tracking as the webhook path.

The upstream middleware has two issues:
1. No concurrency lock — multiple requests can trigger overlapping refreshes
2. No diagnostics — tipg_state is not updated on TTL-triggered refreshes
"""

import logging
from datetime import datetime, timedelta

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class CatalogTTLMiddleware:
    """Refresh TiPG catalog on a TTL schedule, using the same path as the webhook."""

    def __init__(self, app: ASGIApp, *, ttl: int = 60) -> None:
        self.app = app
        self.ttl = ttl
        self._last_refresh: datetime | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Check if TTL has expired
        now = datetime.now()
        needs_refresh = (
            self._last_refresh is None
            or now > self._last_refresh + timedelta(seconds=self.ttl)
        )

        # Serve the request first
        await self.app(scope, receive, send)

        # Then refresh in background if needed
        if needs_refresh:
            self._last_refresh = now
            request = Request(scope)
            try:
                from geotiler.routers.vector import refresh_tipg_pool
                await refresh_tipg_pool(request.app)
            except Exception as e:
                logger.warning(f"TTL catalog refresh failed: {e}")
