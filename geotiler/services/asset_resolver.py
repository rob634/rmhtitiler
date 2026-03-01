"""
Asset resolver for download endpoints.

Validates and normalizes STAC asset hrefs. Enforces URL allowlist
and blocks private IP ranges for SSRF protection.

Spec: Component 7 — Asset Resolver
Handles: R4 (SSRF via crafted asset_href) — allowlist + blocked private ranges + https-only
"""

import ipaddress
import logging
import mimetypes
import re
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedAsset:
    """
    A validated and normalized asset reference.

    Spec: Component 7 — ResolvedAsset dataclass
    """

    blob_url: str
    """Full HTTPS URL to the blob."""

    account_name: str
    """Azure Storage account name."""

    container_name: str
    """Azure Blob container name."""

    blob_path: str
    """Path within the container (without leading slash)."""

    content_type_hint: str
    """MIME type inferred from file extension."""


class AssetResolver:
    """
    Validate and resolve STAC asset hrefs to Azure Blob Storage URLs.

    Enforces:
    - HTTPS-only scheme
    - Hostname in allowlist
    - Block private/reserved IP ranges (SSRF protection)
    - Support for /vsiaz/ paths (GDAL virtual filesystem notation)

    Spec: Component 7 — AssetResolver class
    Handles: R4 (SSRF via crafted asset_href)
    """

    # Private and reserved IP ranges to block
    _BLOCKED_NETWORKS = [
        ipaddress.ip_network("127.0.0.0/8"),       # Loopback
        ipaddress.ip_network("10.0.0.0/8"),         # Private Class A
        ipaddress.ip_network("172.16.0.0/12"),      # Private Class B
        ipaddress.ip_network("192.168.0.0/16"),     # Private Class C
        ipaddress.ip_network("169.254.0.0/16"),     # Link-local / IMDS
        ipaddress.ip_network("::1/128"),            # IPv6 loopback
        ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
        ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
    ]

    # Pattern to match /vsiaz/ paths: /vsiaz/{container}/{blob_path}
    _VSIAZ_PATTERN = re.compile(r"^/vsiaz/([^/]+)/(.+)$")

    def __init__(self, allowed_hosts: list[str], storage_account: Optional[str] = None):
        """
        Initialize with list of allowed hostnames.

        Args:
            allowed_hosts: Hostnames permitted for asset downloads.
            storage_account: Azure Storage account name for /vsiaz/ path conversion.

        Spec: Component 7 — AssetResolver.__init__
        """
        self._allowed_hosts = set(h.lower() for h in allowed_hosts)
        self._storage_account = storage_account

    def resolve(self, asset_href: str) -> ResolvedAsset:
        """
        Validate and resolve an asset href to a ResolvedAsset.

        Supports both https:// URLs and /vsiaz/ virtual paths.

        Args:
            asset_href: The asset URL or /vsiaz/ path to resolve.

        Returns:
            ResolvedAsset with validated blob URL and parsed components.

        Raises:
            ValueError: If the asset_href fails validation.

        Spec: Component 7 — AssetResolver.resolve
        Handles: R4 (SSRF protection via allowlist + private IP blocking)
        """
        # Handle /vsiaz/ paths by converting to https:// URL
        if asset_href.startswith("/vsiaz/"):
            asset_href = self._convert_vsiaz(asset_href)

        # Parse URL
        parsed = urlparse(asset_href)

        # Enforce HTTPS-only
        if parsed.scheme != "https":
            raise ValueError(
                f"Only https:// URLs are allowed, got {parsed.scheme}://"
            )

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL has no hostname")

        hostname_lower = hostname.lower()

        # Check allowlist
        if hostname_lower not in self._allowed_hosts:
            raise ValueError(
                "asset_href must point to an allowed storage host"
            )

        # Block private/reserved IPs (SSRF protection)
        self._check_not_private(hostname)

        # Parse Azure Blob Storage URL components
        # Expected format: https://{account}.blob.core.windows.net/{container}/{path}
        account_name, container_name, blob_path = self._parse_blob_url(parsed)

        content_type = self.infer_content_type(blob_path)

        return ResolvedAsset(
            blob_url=asset_href,
            account_name=account_name,
            container_name=container_name,
            blob_path=blob_path,
            content_type_hint=content_type,
        )

    def _convert_vsiaz(self, vsiaz_path: str) -> str:
        """
        Convert /vsiaz/{container}/{path} to https://{account}.blob.core.windows.net/{container}/{path}.

        Spec: Component 7 — /vsiaz/ path conversion
        """
        match = self._VSIAZ_PATTERN.match(vsiaz_path)
        if not match:
            raise ValueError(
                f"Invalid /vsiaz/ path format: expected /vsiaz/{{container}}/{{path}}"
            )

        if not self._storage_account:
            raise ValueError(
                "Cannot resolve /vsiaz/ path: no storage_account configured"
            )

        container = match.group(1)
        blob_path = match.group(2)
        return f"https://{self._storage_account}.blob.core.windows.net/{container}/{blob_path}"

    def _check_not_private(self, hostname: str) -> None:
        """
        Verify hostname does not resolve to a private/reserved IP.

        Spec: Component 7 — SSRF private IP blocking
        Handles: R4 (block private IP ranges)
        """
        try:
            # Try parsing as IP address directly
            ip = ipaddress.ip_address(hostname)
            if any(ip in network for network in self._BLOCKED_NETWORKS):
                raise ValueError(
                    f"Hostname resolves to blocked private/reserved IP range"
                )
            return
        except ValueError as e:
            # Re-raise if it was our own ValueError
            if "blocked" in str(e).lower():
                raise
            # Not an IP address — it's a hostname, try DNS resolution
            pass

        try:
            addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
            for family, type_, proto, canonname, sockaddr in addr_info:
                ip = ipaddress.ip_address(sockaddr[0])
                if any(ip in network for network in self._BLOCKED_NETWORKS):
                    raise ValueError(
                        f"Hostname resolves to blocked private/reserved IP range"
                    )
        except socket.gaierror:
            # DNS resolution failed — fail closed to prevent SSRF bypass
            raise ValueError(
                f"DNS resolution failed for hostname — cannot verify it is not a private IP"
            )

    @staticmethod
    def _parse_blob_url(parsed) -> tuple[str, str, str]:
        """
        Parse Azure Blob Storage URL into (account_name, container_name, blob_path).

        Expected: https://{account}.blob.core.windows.net/{container}/{path}

        Spec: Component 7 — Azure Blob URL parsing
        """
        hostname = parsed.hostname or ""

        # Extract account name from hostname
        if hostname.endswith(".blob.core.windows.net"):
            account_name = hostname.replace(".blob.core.windows.net", "")
        else:
            # Non-Azure host — use hostname as account_name placeholder
            account_name = hostname

        # Parse path: /{container}/{blob_path}
        path = parsed.path.lstrip("/")
        if "/" not in path:
            raise ValueError(
                f"URL path must contain container and blob path: /{path}"
            )

        parts = path.split("/", 1)
        container_name = parts[0]
        blob_path = parts[1] if len(parts) > 1 else ""

        if not container_name:
            raise ValueError("URL has no container name in path")
        if not blob_path:
            raise ValueError("URL has no blob path after container")

        return account_name, container_name, blob_path

    @staticmethod
    def infer_content_type(path: str) -> str:
        """
        Infer MIME type from file extension.

        Spec: Component 7 — content type inference
        """
        content_type, _ = mimetypes.guess_type(path)
        if content_type:
            return content_type

        # Common geospatial types not in mimetypes registry
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        geo_types = {
            "tif": "image/tiff",
            "tiff": "image/tiff",
            "geojson": "application/geo+json",
            "gpkg": "application/geopackage+sqlite3",
            "parquet": "application/vnd.apache.parquet",
            "zarr": "application/x-zarr",
            "nc": "application/x-netcdf",
            "nc4": "application/x-netcdf",
            "cog": "image/tiff",
        }
        return geo_types.get(ext, "application/octet-stream")
