# ============================================================================
# INFRASTRUCTURE MODULE
# ============================================================================
# Observability, logging, and metrics infrastructure for geotiler.
# ============================================================================
"""
Infrastructure components for observability and monitoring.

Exports:
    configure_azure_monitor: Setup Azure Monitor OpenTelemetry (call BEFORE FastAPI)
    LoggerFactory: Factory for creating structured JSON loggers
    track_latency: Decorator for service latency tracking
    timed_section: Context manager for timing code sections
    RequestTimingMiddleware: FastAPI middleware for request metrics
"""

from geotiler.infrastructure.telemetry import configure_azure_monitor
from geotiler.infrastructure.logging import LoggerFactory, ComponentType
from geotiler.infrastructure.latency import track_latency, timed_section
from geotiler.infrastructure.middleware import RequestTimingMiddleware

__all__ = [
    "configure_azure_monitor",
    "LoggerFactory",
    "ComponentType",
    "track_latency",
    "timed_section",
    "RequestTimingMiddleware",
]
