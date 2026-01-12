#!/usr/bin/env python3
# ============================================================================
# RMHTITILER ENTRY POINT
# ============================================================================
# STATUS: Core - Application entry point with telemetry initialization
# PURPOSE: Configure Azure Monitor BEFORE FastAPI import for proper instrumentation
# ============================================================================
"""
rmhtitiler Application Entry Point.

This module handles the critical initialization order:
1. Configure Azure Monitor OpenTelemetry (BEFORE FastAPI import)
2. Configure structured logging
3. Import and create the FastAPI application

CRITICAL: Azure Monitor must be configured before FastAPI is imported,
otherwise HTTP request instrumentation won't work properly.

Usage:
    # Production (uvicorn)
    uvicorn rmhtitiler.main:app --host 0.0.0.0 --port 8000

    # Development
    uvicorn rmhtitiler.main:app --reload --port 8000

    # Docker
    CMD ["uvicorn", "rmhtitiler.main:app", "--host", "0.0.0.0", "--port", "8000"]

Environment Variables:
    APPLICATIONINSIGHTS_CONNECTION_STRING: Enable App Insights telemetry
    OBSERVABILITY_MODE: Enable detailed request/latency logging (default: false)
    SLOW_REQUEST_THRESHOLD_MS: Slow request threshold in ms (default: 2000)
    APP_NAME: Service name for correlation (default: rmhtitiler)
    ENVIRONMENT: Deployment environment (default: dev)
"""

import os
import sys

# ============================================================================
# STEP 1: CONFIGURE AZURE MONITOR (MUST BE FIRST)
# ============================================================================
# This must happen BEFORE importing FastAPI or any modules that import it.
# Otherwise, the OpenTelemetry auto-instrumentation won't capture HTTP requests.

from rmhtitiler.infrastructure.telemetry import configure_azure_monitor

_telemetry_enabled = configure_azure_monitor()

# ============================================================================
# STEP 2: CONFIGURE STRUCTURED LOGGING
# ============================================================================
# Now that telemetry is configured, set up logging

from rmhtitiler.infrastructure.logging import LoggerFactory

# Use JSON logging if App Insights is enabled, plain text otherwise
LoggerFactory.configure(use_json=_telemetry_enabled)

# ============================================================================
# STEP 3: IMPORT AND CREATE APPLICATION
# ============================================================================
# Now it's safe to import FastAPI and create the app

from rmhtitiler.app import create_app

# Create the application instance
app = create_app()

# Log startup info
import logging
logger = logging.getLogger(__name__)
logger.info(f"rmhtitiler initialized (telemetry={'enabled' if _telemetry_enabled else 'disabled'})")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "rmhtitiler.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
