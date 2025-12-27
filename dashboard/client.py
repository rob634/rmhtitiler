"""
HTTP clients for the Geospatial Platform Dashboard.

Provides async clients for:
- TiTiler endpoints (health, COG info, etc.)
- Platform API (jobs, tasks, storage, etc.)
"""

import httpx
from typing import Any, Dict, List, Optional


class TiTilerClient:
    """
    Async HTTP client for TiTiler endpoints.

    Used for checking TiTiler health and querying tile metadata.
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_health(self) -> Dict[str, Any]:
        """Get TiTiler health status from /healthz."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/healthz")
        response.raise_for_status()
        return response.json()

    async def get_liveness(self) -> Dict[str, Any]:
        """Get TiTiler liveness from /livez."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/livez")
        response.raise_for_status()
        return response.json()

    async def get_root(self) -> Dict[str, Any]:
        """Get TiTiler root info."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/")
        response.raise_for_status()
        return response.json()

    async def get_cog_info(self, url: str) -> Dict[str, Any]:
        """Get COG info for a given URL."""
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/cog/info",
            params={"url": url}
        )
        response.raise_for_status()
        return response.json()

    async def get_searches(self) -> Dict[str, Any]:
        """Get pgSTAC searches."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/searches/list")
        response.raise_for_status()
        return response.json()


class PlatformClient:
    """
    Async HTTP client for rmhazuregeoapi platform.

    Provides methods for:
    - Health monitoring (/api/health)
    - Jobs & Tasks (/api/dbadmin/jobs, /api/dbadmin/tasks)
    - Queues (/api/servicebus)
    - Storage (/api/storage)
    - STAC collections (/api/stac)
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # =========================================================================
    # HEALTH
    # =========================================================================

    async def get_health(self) -> Dict[str, Any]:
        """Get full system health status."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/health")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # JOBS & TASKS
    # =========================================================================

    async def get_jobs(
        self,
        limit: int = 25,
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        hours_back: int = 168,
    ) -> Dict[str, Any]:
        """Get jobs list with optional filters."""
        client = await self._get_client()
        params = {"limit": limit, "hours_back": hours_back}
        if status:
            params["status"] = status
        if job_type:
            params["job_type"] = job_type

        response = await client.get(f"{self.base_url}/api/dbadmin/jobs", params=params)
        response.raise_for_status()
        return response.json()

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get a single job by ID."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/dbadmin/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    async def get_tasks(self, job_id: str) -> Dict[str, Any]:
        """Get tasks for a specific job."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/dbadmin/tasks/{job_id}")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # QUEUES
    # =========================================================================

    async def get_queues(self) -> Dict[str, Any]:
        """Get Service Bus queue status."""
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/servicebus",
            params={"type": "queues"}
        )
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # STORAGE
    # =========================================================================

    async def get_storage_zones(self) -> Dict[str, Any]:
        """Get available storage zones."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/storage/zones")
        response.raise_for_status()
        return response.json()

    async def get_blobs(
        self,
        zone: str,
        container: str,
        prefix: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get blobs in a container."""
        client = await self._get_client()
        params = {"limit": limit}
        if prefix:
            params["prefix"] = prefix

        response = await client.get(
            f"{self.base_url}/api/storage/{zone}/{container}/blobs",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # STAC
    # =========================================================================

    async def get_stac_collections(self) -> Dict[str, Any]:
        """Get all STAC collections."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/stac/collections")
        response.raise_for_status()
        return response.json()

    async def get_stac_items(self, collection_id: str, limit: int = 50) -> Dict[str, Any]:
        """Get items in a STAC collection."""
        client = await self._get_client()
        response = await client.get(
            f"{self.base_url}/api/stac/collections/{collection_id}/items",
            params={"limit": limit}
        )
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # VECTOR (OGC Features)
    # =========================================================================

    async def get_vector_collections(self) -> Dict[str, Any]:
        """Get OGC Features collections."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/features/collections")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # H3
    # =========================================================================

    async def get_h3_stats(self) -> Dict[str, Any]:
        """Get H3 grid statistics."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/h3/stats")
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # PLATFORM
    # =========================================================================

    async def get_platform_health(self) -> Dict[str, Any]:
        """Get platform health status."""
        client = await self._get_client()
        response = await client.get(f"{self.base_url}/api/platform/health")
        response.raise_for_status()
        return response.json()
