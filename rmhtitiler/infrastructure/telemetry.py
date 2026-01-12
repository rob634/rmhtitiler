# ============================================================================
# AZURE MONITOR OPENTELEMETRY SETUP
# ============================================================================
# STATUS: Infrastructure - Must be called BEFORE FastAPI import
# PURPOSE: Enable Application Insights telemetry for Docker/App Service
# ============================================================================
"""
Azure Monitor OpenTelemetry Configuration.

CRITICAL: configure_azure_monitor() must be called BEFORE importing FastAPI
otherwise the instrumentation won't capture FastAPI requests properly.

This enables:
- Logs -> Application Insights traces table
- HTTP requests -> Application Insights requests table
- Exceptions -> Application Insights exceptions table
- Custom metrics -> Application Insights customMetrics table

Environment Variables:
    APPLICATIONINSIGHTS_CONNECTION_STRING: App Insights connection string
    APP_NAME: Service name for correlation (default: rmhtitiler)
    ENVIRONMENT: Deployment environment (default: dev)
"""

import os

# Track if telemetry was successfully configured
_azure_monitor_enabled: bool = False


def configure_azure_monitor() -> bool:
    """
    Configure Azure Monitor OpenTelemetry for rmhtitiler.

    Must be called BEFORE FastAPI is imported to properly instrument HTTP requests.

    Returns:
        bool: True if configured successfully, False otherwise

    Example:
        # In app entry point, BEFORE other imports:
        from rmhtitiler.infrastructure.telemetry import configure_azure_monitor
        configure_azure_monitor()

        # Then import FastAPI and create app
        from fastapi import FastAPI
    """
    global _azure_monitor_enabled

    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")

    if not connection_string:
        print("INFO: APPLICATIONINSIGHTS_CONNECTION_STRING not set - telemetry disabled")
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor as _configure

        app_name = os.environ.get("APP_NAME", "rmhtitiler")
        environment = os.environ.get("ENVIRONMENT", "dev")

        _configure(
            connection_string=connection_string,
            resource_attributes={
                "service.name": app_name,
                "service.namespace": "rmhtitiler",
                "deployment.environment": environment,
            },
            enable_live_metrics=True,
        )

        print(f"Azure Monitor OpenTelemetry configured (app={app_name}, env={environment})")
        _azure_monitor_enabled = True
        return True

    except ImportError:
        print("WARN: azure-monitor-opentelemetry not installed - telemetry disabled")
        return False
    except Exception as e:
        print(f"WARN: Azure Monitor setup failed: {e} - telemetry disabled")
        return False


def is_telemetry_enabled() -> bool:
    """Check if Azure Monitor telemetry is enabled."""
    return _azure_monitor_enabled
