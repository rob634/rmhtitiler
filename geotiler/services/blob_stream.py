"""
Authenticated streaming reads from Azure Blob Storage.

Uses azure-storage-blob async SDK to stream blob data with chunked reads.
Token is passed explicitly from the storage_token_cache (not from env vars)
because /api/* endpoints skip the AzureAuthMiddleware.

Spec: Component 6 — Blob Stream Client
Handles: R2 (Partial file on mid-stream failure — token freshness check mitigates)
"""

import logging
import re
from typing import AsyncIterator, Optional
from urllib.parse import urlparse

from azure.core.exceptions import (
    HttpResponseError,
    ResourceNotFoundError,
)
from azure.storage.blob.aio import BlobServiceClient

logger = logging.getLogger(__name__)


class BlobStreamClient:
    """
    Authenticated streaming client for Azure Blob Storage.

    Validates URLs, checks blob size limits, and streams blob data
    in configurable chunks.

    Spec: Component 6 — BlobStreamClient class
    """

    def __init__(self, settings):
        """
        Initialize with application settings.

        Args:
            settings: geotiler Settings instance with download_blob_chunk_size,
                      download_proxy_max_size_mb, download_allowed_host_list.

        Spec: Component 6 — BlobStreamClient.__init__
        """
        self._chunk_size = settings.download_blob_chunk_size
        self._max_size_mb = settings.download_proxy_max_size_mb
        self._allowed_hosts = [h.lower() for h in settings.download_allowed_host_list]

    def validate_url(self, url: str) -> tuple[str, str, str]:
        """
        Parse and validate an Azure Blob Storage URL.

        Args:
            url: Full HTTPS URL to the blob.

        Returns:
            Tuple of (account_url, container_name, blob_path).

        Raises:
            ValueError: If URL is invalid or host not in allowlist.

        Spec: Component 6 — BlobStreamClient.validate_url
        Handles: R4 (SSRF — URL validation at blob level)
        """
        parsed = urlparse(url)

        if parsed.scheme != "https":
            raise ValueError(f"Only https:// URLs allowed, got {parsed.scheme}://")

        hostname = (parsed.hostname or "").lower()
        if hostname not in self._allowed_hosts:
            raise ValueError("asset_href must point to an allowed storage host")

        # Parse path: /{container}/{blob_path}
        path = parsed.path.lstrip("/")
        if "/" not in path:
            raise ValueError(f"URL must include container and blob path")

        parts = path.split("/", 1)
        container_name = parts[0]
        blob_path = parts[1] if len(parts) > 1 else ""

        if not container_name or not blob_path:
            raise ValueError("URL must include container name and blob path")

        account_url = f"https://{hostname}"
        return account_url, container_name, blob_path

    async def get_blob_properties(self, blob_url: str, token: str) -> dict:
        """
        Get blob properties (size, content type) without downloading.

        Args:
            blob_url: Full HTTPS URL to the blob.
            token: OAuth bearer token for Azure Blob Storage.

        Returns:
            Dict with 'size_bytes', 'size_mb', 'content_type', 'etag'.

        Raises:
            ResourceNotFoundError: Blob does not exist (maps to 404).
            HttpResponseError: Access denied or other HTTP error.
            ValueError: Invalid URL.

        Spec: Component 6 — BlobStreamClient.get_blob_properties
        """
        account_url, container_name, blob_path = self.validate_url(blob_url)

        async with self._create_client(account_url, token) as client:
            try:
                container_client = client.get_container_client(container_name)
                blob_client = container_client.get_blob_client(blob_path)
                props = await blob_client.get_blob_properties()

                size_bytes = props.size or 0
                return {
                    "size_bytes": size_bytes,
                    "size_mb": round(size_bytes / (1024 * 1024), 2),
                    "content_type": props.content_settings.content_type or "application/octet-stream",
                    "etag": props.etag,
                }
            except ResourceNotFoundError:
                raise
            except HttpResponseError as e:
                self._handle_http_error(e, blob_url)
                raise  # Re-raise if not handled

    async def stream_blob(
        self, blob_url: str, token: str, etag: Optional[str] = None
    ) -> AsyncIterator[bytes]:
        """
        Stream blob data in chunks.

        Caller must check blob size via get_blob_properties before calling
        this method to enforce size limits.

        Args:
            blob_url: Full HTTPS URL to the blob.
            token: OAuth bearer token for Azure Blob Storage.
            etag: Optional etag from get_blob_properties. When provided,
                  the download will fail with 412 if the blob was modified
                  between the properties check and the stream start (TOCTOU guard).

        Yields:
            Chunks of blob data (size controlled by download_blob_chunk_size).

        Raises:
            ResourceNotFoundError: Blob does not exist.
            HttpResponseError: Access denied or other HTTP error.

        Spec: Component 6 — BlobStreamClient.stream_blob
        """
        account_url, container_name, blob_path = self.validate_url(blob_url)

        async with self._create_client(account_url, token) as client:
            try:
                container_client = client.get_container_client(container_name)
                blob_client = container_client.get_blob_client(blob_path)

                download_kwargs = {}
                if etag:
                    from azure.core import MatchConditions
                    download_kwargs["etag"] = etag
                    download_kwargs["match_condition"] = MatchConditions.IfNotModified

                stream = await blob_client.download_blob(**download_kwargs)
                async for chunk in stream.chunks():
                    if chunk:
                        yield chunk

            except ResourceNotFoundError:
                logger.error(f"Blob not found during streaming: {blob_url}")
                raise
            except HttpResponseError as e:
                self._handle_http_error(e, blob_url)
                raise

    def check_size_limit(self, size_mb: float) -> None:
        """
        Check if blob size exceeds the configured proxy limit.

        Args:
            size_mb: Blob size in megabytes.

        Raises:
            ValueError: If size exceeds limit (caller maps to 400).

        Spec: Component 6 — size limit enforcement
        Handles: R1 (Memory pressure from large blobs — proxy size limit)
        """
        if size_mb > self._max_size_mb:
            raise ValueError(
                f"File exceeds download size limit: {size_mb:.1f} MB > {self._max_size_mb} MB"
            )

    def _create_client(self, account_url: str, token: str) -> BlobServiceClient:
        """
        Create an async BlobServiceClient with bearer token auth.

        Token is passed via a simple credential wrapper since we already
        have the token from storage_token_cache.

        Spec: Component 6 — token-based client creation
        """
        return BlobServiceClient(
            account_url=account_url,
            credential=_BearerTokenCredential(token),
            max_chunk_get_size=self._chunk_size,
        )

    @staticmethod
    def _handle_http_error(error: HttpResponseError, url: str) -> None:
        """
        Log and categorize Azure HTTP errors.

        Spec: Component 6 — error handling
        Handles: Critic concern — transparent error reporting
        """
        status = getattr(error, "status_code", None)
        if status == 403:
            logger.error(
                f"Access denied to blob: {url}",
                extra={"event": "blob_access_denied", "status": 403},
            )
        elif status == 429:
            retry_after = (getattr(error, "headers", None) or {}).get("Retry-After", "10")
            logger.warning(
                f"Blob storage throttled: {url}, retry_after={retry_after}",
                extra={"event": "blob_throttled", "status": 429},
            )
        else:
            error_msg = getattr(error, "message", None) or str(error)
            logger.error(
                f"Blob storage error: {url}, status={status}, error={error_msg}",
                extra={"event": "blob_error", "status": status},
            )


class _BearerTokenCredential:
    """
    Minimal credential wrapper that provides a pre-acquired bearer token
    to the Azure SDK's TokenCredential protocol.

    This avoids re-acquiring a token — we already have one from storage_token_cache.

    Spec: Component 6 — token credential wrapper
    """

    def __init__(self, token: str):
        self._token = token

    async def get_token(self, *scopes, **kwargs):
        """Return the pre-acquired token."""
        from azure.core.credentials import AccessToken
        # Use a far-future expiry — the caller manages token freshness
        return AccessToken(self._token, 9999999999)

    async def close(self):
        """No-op — nothing to clean up."""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
