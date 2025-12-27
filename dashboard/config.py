"""
Dashboard configuration.

Connects to multiple platform APIs for comprehensive monitoring:
- TiTiler (local or same container)
- rmhazuregeoapi Azure Functions (external)
- Storage and database endpoints
"""

import os
from dataclasses import dataclass


@dataclass
class DashboardConfig:
    """Configuration for the Geospatial Platform Dashboard."""

    # TiTiler API (same container or external)
    TITILER_BASE_URL: str = os.environ.get(
        "TITILER_BASE_URL",
        "http://localhost:8000"  # Same container default
    )

    # Platform API - rmhazuregeoapi Azure Functions
    PLATFORM_API_URL: str = os.environ.get(
        "PLATFORM_API_URL",
        "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"
    )

    # Docker worker API (optional) - rmhheavyapi
    WORKER_BASE_URL: str = os.environ.get(
        "WORKER_BASE_URL",
        "https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net"
    )

    # Dashboard settings (only used in standalone mode)
    DASHBOARD_PORT: int = int(os.environ.get("DASHBOARD_PORT", "8081"))
    DASHBOARD_HOST: str = os.environ.get("DASHBOARD_HOST", "0.0.0.0")

    # Polling intervals (seconds)
    POLL_INTERVAL_HEALTH: float = float(os.environ.get("POLL_INTERVAL_HEALTH", "30.0"))
    POLL_INTERVAL_JOBS: float = float(os.environ.get("POLL_INTERVAL_JOBS", "10.0"))
    POLL_INTERVAL_QUEUES: float = float(os.environ.get("POLL_INTERVAL_QUEUES", "5.0"))

    # HTTP settings
    HTTP_TIMEOUT: float = float(os.environ.get("HTTP_TIMEOUT", "30.0"))

    # Feature flags
    ENABLE_PLATFORM_API: bool = os.environ.get("ENABLE_PLATFORM_API", "true").lower() == "true"
    ENABLE_WORKER_API: bool = os.environ.get("ENABLE_WORKER_API", "false").lower() == "true"

    def __post_init__(self):
        self.TITILER_BASE_URL = self.TITILER_BASE_URL.rstrip("/")
        self.PLATFORM_API_URL = self.PLATFORM_API_URL.rstrip("/")
        self.WORKER_BASE_URL = self.WORKER_BASE_URL.rstrip("/")


config = DashboardConfig()
