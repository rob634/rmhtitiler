"""
TiTiler in-process client for raster crop operations.

Uses httpx ASGITransport to call TiTiler endpoints within the same process,
avoiding network roundtrips and uvicorn deadlocks (single worker).

Spec: Component 4 — TiTiler Client
Handles: T1 (HTTP delegation vs in-process TiTiler — ASGI transport as pragmatic middle ground)
"""

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from fastapi import FastAPI
    from geotiler.services.download import ParsedBbox

logger = logging.getLogger(__name__)


class TiTilerClient:
    """
    In-process TiTiler client using ASGI transport.

    Bypasses network and middleware to call TiTiler's /cog/bbox endpoint
    directly via the ASGI interface. This avoids deadlocks on the single
    uvicorn worker and eliminates network overhead.

    Spec: Component 4 — TiTilerClient class
    Handles: T1 (ASGI transport for in-process delegation)
    """

    def __init__(self, app: "FastAPI", timeout_sec: float = 200.0):
        """
        Initialize with the FastAPI application instance.

        Args:
            app: The running FastAPI application (used as ASGI transport target).
            timeout_sec: Request timeout in seconds.

        Spec: Component 4 — TiTilerClient.__init__
        """
        self._transport = httpx.ASGITransport(app=app)
        self._timeout = timeout_sec

    async def crop(
        self,
        asset_url: str,
        bbox: "ParsedBbox",
        format: str = "tif",
    ) -> tuple[bytes, dict[str, str]]:
        """
        Execute a TiTiler bbox crop and return the response bytes.

        TiTiler crop is buffered (not streamed) — the entire raster crop
        is held in memory. Bbox area limits in the download service
        mitigate memory pressure.

        Args:
            asset_url: Full URL to the raster asset (COG).
            bbox: Parsed bounding box with minx, miny, maxx, maxy.
            format: Output format — 'tif' or 'png'.

        Returns:
            Tuple of (response_bytes, response_headers dict).

        Raises:
            httpx.HTTPStatusError: If TiTiler returns 4xx or 5xx.
            httpx.TimeoutException: If the request exceeds timeout.

        Spec: Component 4 — TiTilerClient.crop
        Handles: R1 (TiTiler crop memory — bbox area limit mitigates)
        """
        # Build TiTiler /cog/bbox endpoint URL
        # Pattern: /cog/bbox/{minx},{miny},{maxx},{maxy}.{format}?url={asset_url}
        path = f"/cog/bbox/{bbox.minx},{bbox.miny},{bbox.maxx},{bbox.maxy}.{format}"

        logger.debug(
            f"TiTiler crop request: path={path} asset_url={asset_url[:80]}...",
            extra={"event": "titiler_crop_start"},
        )

        async with httpx.AsyncClient(
            transport=self._transport,
            base_url="http://app",  # Arbitrary — ASGI transport ignores hostname
            timeout=httpx.Timeout(self._timeout),
        ) as client:
            try:
                response = await client.get(
                    path,
                    params={"url": asset_url},
                )
                response.raise_for_status()

                # Extract useful headers from TiTiler response
                headers = {}
                for key in ("content-type", "content-length", "x-titiler-timing"):
                    if key in response.headers:
                        headers[key] = response.headers[key]

                logger.debug(
                    f"TiTiler crop complete: {len(response.content)} bytes, "
                    f"content-type={headers.get('content-type', 'unknown')}",
                    extra={"event": "titiler_crop_complete"},
                )

                return response.content, headers

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text[:500]

                if 400 <= status < 500:
                    # Client error from TiTiler (bad URL, unsupported format, etc.)
                    logger.warning(
                        f"TiTiler crop client error: status={status} body={body}",
                        extra={"event": "titiler_crop_client_error", "status": status},
                    )
                    raise
                else:
                    # Server error from TiTiler (GDAL crash, memory, etc.)
                    logger.error(
                        f"TiTiler crop server error: status={status} body={body}",
                        extra={"event": "titiler_crop_server_error", "status": status},
                    )
                    raise

            except httpx.TimeoutException:
                logger.error(
                    f"TiTiler crop timeout after {self._timeout}s",
                    extra={"event": "titiler_crop_timeout"},
                )
                raise
