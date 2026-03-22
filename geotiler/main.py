#!/usr/bin/env python3
# ============================================================================
# RMHTITILER ENTRY POINT
# ============================================================================
# STATUS: Core - Application entry point with telemetry initialization
# PURPOSE: Configure Azure Monitor BEFORE FastAPI import for proper instrumentation
# ============================================================================
"""
geotiler Application Entry Point.

This module handles the critical initialization order:
1. Configure Azure Monitor OpenTelemetry (BEFORE FastAPI import)
2. Configure structured logging
3. Import and create the FastAPI application

CRITICAL: Azure Monitor must be configured before FastAPI is imported,
otherwise HTTP request instrumentation won't work properly.

Usage:
    # Production (uvicorn)
    uvicorn geotiler.main:app --host 0.0.0.0 --port 8000

    # Development
    uvicorn geotiler.main:app --reload --port 8000

    # Docker
    CMD ["uvicorn", "geotiler.main:app", "--host", "0.0.0.0", "--port", "8000"]

Environment Variables:
    APPLICATIONINSIGHTS_CONNECTION_STRING: Enable App Insights telemetry
    GEOTILER_ENABLE_OBSERVABILITY: Enable detailed request/latency logging (default: false)
    GEOTILER_OBS_SLOW_THRESHOLD_MS: Slow request threshold in ms (default: 2000)
    GEOTILER_OBS_SERVICE_NAME: Service name for correlation (default: geotiler)
    GEOTILER_OBS_ENVIRONMENT: Deployment environment (default: dev)
"""

import os
import sys

# ============================================================================
# STEP 1: CONFIGURE AZURE MONITOR (MUST BE FIRST)
# ============================================================================
# This must happen BEFORE importing FastAPI or any modules that import it.
# Otherwise, the OpenTelemetry auto-instrumentation won't capture HTTP requests.

from geotiler.infrastructure.telemetry import configure_azure_monitor

_telemetry_enabled = configure_azure_monitor()

# ============================================================================
# STEP 2: CONFIGURE STRUCTURED LOGGING
# ============================================================================
# Now that telemetry is configured, set up logging

from geotiler.infrastructure.logging import LoggerFactory

# Use JSON logging if App Insights is enabled, plain text otherwise
# Log level read directly from env (config.py not yet importable here)
import logging as _logging
_log_level = getattr(_logging, os.environ.get("GEOTILER_LOG_LEVEL", "INFO").upper(), _logging.INFO)
LoggerFactory.configure(use_json=_telemetry_enabled, level=_log_level)

# ============================================================================
# STEP 3: IMPORT AND CREATE APPLICATION
# ============================================================================
# Now it's safe to import FastAPI and create the app

from geotiler.app import create_app

# Create the application instance
app = create_app()

# Log startup info
import logging
logger = logging.getLogger(__name__)
logger.info(f"geotiler initialized (telemetry={'enabled' if _telemetry_enabled else 'disabled'})")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "geotiler.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
