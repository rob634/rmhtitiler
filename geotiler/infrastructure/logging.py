# ============================================================================
# STRUCTURED LOGGING SYSTEM
# ============================================================================
# STATUS: Infrastructure - JSON logging for Azure Application Insights
# PURPOSE: Component-based structured logging with global context
# ============================================================================
"""
Structured Logging System for geotiler.

Provides JSON-formatted logging that flows to Azure Application Insights,
enabling powerful Kusto queries for performance analysis.

Design Principles:
    - Component-based loggers (COG, Xarray, pgSTAC, Auth, Health)
    - Global context injection (app_name, environment, instance)
    - custom_dimensions support for Application Insights
    - Zero dependencies beyond stdlib + optional psutil

Global Log Context:
    Every log entry automatically includes:
    - app_name: Application identifier (APP_NAME env var)
    - app_instance: Azure instance ID (WEBSITE_INSTANCE_ID)
    - environment: Deployment environment (ENVIRONMENT env var)

    This enables filtering logs in multi-app deployments:
        traces | where customDimensions.app_name == "geotiler"

Exports:
    ComponentType: Enum for component types
    LoggerFactory: Factory for creating component loggers
    get_global_log_context: Get global context fields
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


# ============================================================================
# COMPONENT TYPES
# ============================================================================

class ComponentType(Enum):
    """Component types for categorizing log sources."""
    COG = "cog"              # Cloud Optimized GeoTIFF endpoints
    XARRAY = "xarray"        # Zarr/NetCDF endpoints
    PGSTAC = "pgstac"        # pgSTAC search endpoints
    PC = "pc"                # Planetary Computer endpoints
    AUTH = "auth"            # Authentication (storage, postgres)
    HEALTH = "health"        # Health probe endpoints
    MIDDLEWARE = "middleware"  # Request middleware
    DATABASE = "database"    # Database operations
    BACKGROUND = "background"  # Background tasks
    APP = "app"              # Application lifecycle


# ============================================================================
# GLOBAL LOG CONTEXT
# ============================================================================

_GLOBAL_LOG_CONTEXT: Optional[Dict[str, str]] = None


def get_global_log_context() -> Dict[str, str]:
    """
    Get global log context fields for multi-app filtering.

    Returns cached context containing:
    - app_name: Application identifier (APP_NAME env var)
    - app_instance: Azure instance ID (truncated to 16 chars)
    - environment: Deployment environment (dev/qa/prod)

    These fields are automatically injected into every log entry
    by LoggerFactory, enabling queries like:
        traces | where customDimensions.app_name == "geotiler"

    Returns:
        Dict with app_name, app_instance, environment
    """
    global _GLOBAL_LOG_CONTEXT

    if _GLOBAL_LOG_CONTEXT is None:
        _GLOBAL_LOG_CONTEXT = {
            "app_name": os.environ.get("GEOTILER_OBS_SERVICE_NAME", "geotiler"),
            "app_instance": os.environ.get("WEBSITE_INSTANCE_ID", "local")[:16],
            "environment": os.environ.get("GEOTILER_OBS_ENVIRONMENT", "dev"),
        }

    return _GLOBAL_LOG_CONTEXT


# ============================================================================
# JSON FORMATTER
# ============================================================================

class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging to Application Insights.

    Formats log records as JSON with:
    - Standard fields (timestamp, level, message, logger)
    - Global context (app_name, environment, instance)
    - Custom dimensions (via extra={'custom_dimensions': {...}})

    Application Insights automatically parses JSON logs into the
    customDimensions column for Kusto queries.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Base log entry
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add global context
        log_entry.update(get_global_log_context())

        # Add component if present
        if hasattr(record, "component"):
            log_entry["component"] = record.component

        # Add custom dimensions if present
        if hasattr(record, "custom_dimensions"):
            log_entry["custom_dimensions"] = record.custom_dimensions

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


# ============================================================================
# LOGGER FACTORY
# ============================================================================

class LoggerFactory:
    """
    Factory for creating component-specific structured loggers.

    Creates loggers that:
    - Output JSON for Application Insights compatibility
    - Include global context (app_name, environment)
    - Support custom_dimensions for per-log metadata

    Usage:
        from geotiler.infrastructure.logging import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.COG, "TileRenderer")

        # Simple logging
        logger.info("Rendering tile")

        # With custom dimensions (for App Insights queries)
        logger.info("Tile rendered", extra={
            "custom_dimensions": {
                "z": 10, "x": 512, "y": 384,
                "duration_ms": 145.2,
                "url": "https://storage.blob.core.windows.net/..."
            }
        })
    """

    _configured: bool = False
    _use_json: bool = True

    @classmethod
    def configure(cls, use_json: bool = True, level: int = logging.INFO) -> None:
        """
        Configure the logging system.

        Args:
            use_json: Use JSON formatting (for App Insights). Default True.
            level: Root log level. Default INFO.
        """
        if cls._configured:
            return

        cls._use_json = use_json

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        # Remove existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Add stdout handler with appropriate formatter
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        if use_json:
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))

        root_logger.addHandler(handler)

        # Configure uvicorn loggers to use same handler
        for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
            uvi_logger = logging.getLogger(logger_name)
            uvi_logger.handlers = []
            uvi_logger.addHandler(handler)
            uvi_logger.propagate = False

        cls._configured = True

    @classmethod
    def create_logger(
        cls,
        component: ComponentType,
        name: str,
        level: Optional[int] = None
    ) -> logging.Logger:
        """
        Create a component-specific logger.

        Args:
            component: Component type for categorization
            name: Logger name (typically class or module name)
            level: Optional log level override

        Returns:
            Configured logger instance

        Example:
            logger = LoggerFactory.create_logger(ComponentType.COG, "TileRenderer")
            logger.info("Starting render")
        """
        # Ensure logging is configured
        if not cls._configured:
            cls.configure()

        # Create logger with component prefix
        logger_name = f"geotiler.{component.value}.{name}"
        logger = logging.getLogger(logger_name)

        if level is not None:
            logger.setLevel(level)

        # Add component attribute via filter (scoped to this logger only)
        logger.addFilter(_ComponentFilter(component.value))

        return logger


class _ComponentFilter(logging.Filter):
    """Injects a component attribute into log records for App Insights filtering."""

    def __init__(self, component_value: str):
        super().__init__()
        self._component = component_value

    def filter(self, record: logging.LogRecord) -> bool:
        record.component = self._component
        return True


# ============================================================================
# MEMORY STATS (Optional - requires psutil)
# ============================================================================

def get_memory_stats() -> Optional[Dict[str, float]]:
    """
    Get current process memory and CPU statistics.

    Useful for tracking resource usage during tile rendering.

    Returns:
        dict with resource stats or None if psutil unavailable:
        {
            'process_rss_mb': float,      # Resident Set Size (actual RAM used)
            'process_vms_mb': float,      # Virtual Memory Size
            'process_cpu_percent': float, # Process CPU usage %
            'system_available_mb': float, # Available system memory
            'system_percent': float,      # System memory usage %
        }
    """
    try:
        import psutil

        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        system_mem = psutil.virtual_memory()

        return {
            "process_rss_mb": round(mem_info.rss / 1024 / 1024, 2),
            "process_vms_mb": round(mem_info.vms / 1024 / 1024, 2),
            "process_cpu_percent": round(process.cpu_percent(interval=None), 1),
            "system_available_mb": round(system_mem.available / 1024 / 1024, 2),
            "system_percent": round(system_mem.percent, 1),
        }
    except ImportError:
        return None
    except Exception:
        return None
