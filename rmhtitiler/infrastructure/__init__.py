# ============================================================================
# INFRASTRUCTURE MODULE
# ============================================================================
# Observability, logging, and metrics infrastructure for rmhtitiler.
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

from rmhtitiler.infrastructure.telemetry import configure_azure_monitor
from rmhtitiler.infrastructure.logging import LoggerFactory, ComponentType
from rmhtitiler.infrastructure.latency import track_latency, timed_section
from rmhtitiler.infrastructure.middleware import RequestTimingMiddleware

__all__ = [
    "configure_azure_monitor",
    "LoggerFactory",
    "ComponentType",
    "track_latency",
    "timed_section",
    "RequestTimingMiddleware",
]
