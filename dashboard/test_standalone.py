#!/usr/bin/env python3
"""
Standalone Dashboard Test

Run this to test the dashboard locally without TiTiler dependencies.
Uses mock data for health checks.

Usage:
    cd /Users/robertharrison/python_builds/rmhtitiler
    python -m dashboard.test_standalone
    # Open http://localhost:8081/dashboard
"""

from nicegui import ui, app
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.config import config
from dashboard.theme import apply_theme, COLORS
from dashboard.components.architecture_diagram import create_native_diagram
from dashboard.pages import home, pipelines, explorer


# Mock TiTiler client that returns fake health data
class MockTiTilerClient:
    async def get_health(self):
        return {
            "status": "ok",
            "version": "0.4.1",
            "database": {"connected": True, "ping_ms": 12},
            "storage": {"token_valid": True, "expires_in_minutes": 45},
            "features": {"cog": True, "xarray": True, "planetary_computer": True},
            "hardware": {"cpu_percent": 15.2, "memory_percent": 42.5}
        }

    async def close(self):
        pass


# Mock Platform client
class MockPlatformClient:
    async def get_health(self):
        return {
            "status": "healthy",
            "components": {
                "database": {"status": "healthy", "description": "PostgreSQL connection"},
                "service_bus": {"status": "healthy", "description": "Azure Service Bus"},
                "storage_containers": {"status": "healthy", "description": "Azure Blob Storage"},
                "pgstac": {"status": "healthy", "description": "pgSTAC schema"},
                "jobs": {"status": "healthy", "description": "Job orchestration"},
            }
        }

    async def get_jobs(self, **kwargs):
        return {
            "jobs": [
                {
                    "job_id": "abc12345-1234-1234-1234-123456789abc",
                    "job_type": "process_raster_v2",
                    "status": "completed",
                    "created_at": "2025-12-24T10:00:00Z",
                    "stage": 4,
                    "total_stages": 4,
                    "task_counts": {"completed": 15, "failed": 0}
                },
                {
                    "job_id": "def45678-1234-1234-1234-123456789def",
                    "job_type": "process_vector",
                    "status": "processing",
                    "created_at": "2025-12-24T11:00:00Z",
                    "stage": 2,
                    "total_stages": 4,
                    "task_counts": {"processing": 3, "completed": 7}
                },
                {
                    "job_id": "ghi78901-1234-1234-1234-123456789ghi",
                    "job_type": "process_raster_collection_v2",
                    "status": "queued",
                    "created_at": "2025-12-24T12:00:00Z",
                    "stage": 0,
                    "total_stages": 4,
                    "task_counts": {"queued": 25}
                },
            ]
        }

    async def get_storage_zones(self):
        return {
            "zones": {
                "bronze": {"account": "itsesgddataintqastrg", "containers": ["raw", "incoming", "uploads"], "container_count": 3},
                "silver": {"account": "itsesgddataintqastrg", "containers": ["processed", "cogs"], "container_count": 2},
                "gold": {"account": "itsesgddataintqastrg", "containers": ["stac", "exports"], "container_count": 2},
            }
        }

    async def get_blobs(self, zone, container, prefix=None, limit=50):
        return {
            "blobs": [
                {"name": "data/maxar/tile_001.tif", "size": 1024*1024*50, "last_modified": "2025-12-24T10:00:00Z"},
                {"name": "data/maxar/tile_002.tif", "size": 1024*1024*48, "last_modified": "2025-12-24T10:01:00Z"},
                {"name": "data/sentinel/scene_2025.tif", "size": 1024*1024*125, "last_modified": "2025-12-23T15:00:00Z"},
            ]
        }

    async def get_stac_collections(self):
        return {
            "collections": [
                {"id": "maxar-imagery", "title": "Maxar Imagery", "description": "High-resolution satellite imagery from Maxar", "item_count": 1523},
                {"id": "sentinel-2-l2a", "title": "Sentinel-2 L2A", "description": "Sentinel-2 Level-2A surface reflectance", "item_count": 3247},
                {"id": "landsat-c2-l2", "title": "Landsat Collection 2", "description": "Landsat Collection 2 Level-2 products", "item_count": 892},
            ]
        }

    async def close(self):
        pass


# Create mock clients
titiler_client = MockTiTilerClient()
platform_client = MockPlatformClient()


def create_header():
    """Create the header."""
    apply_theme()

    with ui.header(elevated=True).classes("items-center justify-between").style(f"background: {COLORS['navy']}"):
        with ui.row().classes("items-center gap-4"):
            with ui.link(target="/dashboard").classes("no-underline"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("public", size="md").classes("text-white")
                    ui.label("Geospatial Platform").classes("text-xl font-bold text-white")
                    ui.badge("TEST MODE").classes("bg-yellow-500 text-black ml-2")

        with ui.row().classes("items-center gap-2"):
            nav_items = [
                ("Status", "/dashboard/status", "favorite"),
                ("Pipelines", "/dashboard/pipelines", "alt_route"),
                ("Explorer", "/dashboard/explorer", "storage"),
            ]
            for label, link, icon in nav_items:
                with ui.link(target=link).classes("no-underline"):
                    ui.button(label, icon=icon).props("flat").classes("text-white")


@ui.page("/dashboard")
def dashboard_home():
    """Dashboard home."""
    create_header()
    with ui.column().classes("w-full"):
        home.create_page()


@ui.page("/dashboard/status")
def dashboard_status():
    """Status page with mock data."""
    create_header()

    with ui.column().classes("gap-6 p-6 w-full max-w-7xl mx-auto"):
        # Header
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("System Status").classes("text-2xl font-bold")
                ui.label("Real-time platform health monitoring").classes("text-gray-500")

            refresh_btn = ui.button("Refresh", icon="refresh")
            refresh_btn.props("outline")

        # Architecture diagram with mock healthy status
        mock_components = {
            "deployment_config": {"status": "healthy"},
            "service_bus": {"status": "healthy"},
            "jobs": {"status": "healthy"},
            "database": {"status": "healthy"},
            "imports": {"status": "healthy"},
            "storage_containers": {"status": "healthy"},
            "pgstac": {"status": "healthy"},
            "titiler": {"status": "healthy"},
            "ogc_features": {"status": "warning"},
        }

        with ui.card().classes("w-full"):
            ui.label("System Architecture").classes("text-lg font-bold mb-4 pb-2 border-b-2 border-blue-500")
            create_native_diagram(mock_components)

        # Status banners
        with ui.card().classes("w-full bg-green-100 border-l-4 border-green-500"):
            with ui.row().classes("items-center justify-between"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon("check_circle", size="lg").classes("text-green-800")
                    with ui.column().classes("gap-0"):
                        ui.label("TiTiler Tile Server").classes("text-lg font-bold text-green-800")
                        ui.label("Version 0.4.1").classes("text-sm text-gray-600")

                with ui.row().classes("gap-6"):
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("check_circle", size="xs", color="green")
                        ui.label("Database").classes("text-sm")
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("check_circle", size="xs", color="green")
                        ui.label("Storage (45m)").classes("text-sm")

        with ui.card().classes("w-full bg-green-100 border-l-4 border-green-500"):
            with ui.row().classes("items-center justify-between"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon("check_circle", size="lg").classes("text-green-800")
                    with ui.column().classes("gap-0"):
                        ui.label("Platform API").classes("text-lg font-bold text-green-800")
                        ui.label("5 components checked").classes("text-sm text-gray-600")

                with ui.row().classes("gap-4"):
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("check_circle", size="xs", color="green")
                        ui.label("4 healthy").classes("text-sm text-green-700")
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("warning", size="xs", color="orange")
                        ui.label("1 warning").classes("text-sm text-yellow-700")

        # Component Details
        with ui.card().classes("w-full"):
            ui.label("TiTiler Details").classes("text-lg font-bold mb-4 pb-2 border-b-2 border-blue-500")

            with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"):
                with ui.column().classes("gap-1"):
                    ui.label("Version").classes("text-xs text-gray-500 uppercase")
                    ui.label("0.4.1").classes("font-bold")

                with ui.column().classes("gap-1"):
                    ui.label("Database").classes("text-xs text-gray-500 uppercase")
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("check_circle", size="xs", color="green")
                        ui.label("Connected (12ms)").classes("font-bold text-green-600")

                with ui.column().classes("gap-1"):
                    ui.label("CPU").classes("text-xs text-gray-500 uppercase")
                    with ui.row().classes("items-center gap-2"):
                        ui.label("15.2%").classes("font-bold")
                        ui.linear_progress(value=0.152, show_value=False).classes("w-20").props("color=blue")

                with ui.column().classes("gap-1"):
                    ui.label("Memory").classes("text-xs text-gray-500 uppercase")
                    with ui.row().classes("items-center gap-2"):
                        ui.label("42.5%").classes("font-bold")
                        ui.linear_progress(value=0.425, show_value=False).classes("w-20").props("color=green")


@ui.page("/dashboard/pipelines")
def dashboard_pipelines():
    """Pipelines page with mock client."""
    create_header()
    with ui.column().classes("w-full"):
        pipelines.create_page(platform_client)


@ui.page("/dashboard/explorer")
def dashboard_explorer():
    """Explorer page with mock client."""
    create_header()
    with ui.column().classes("w-full"):
        explorer.create_page(platform_client, titiler_client)


@app.on_startup
async def startup():
    print("=" * 60)
    print("Dashboard TEST MODE")
    print("=" * 60)
    print("Open http://localhost:8081/dashboard")
    print("=" * 60)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0",
        port=8081,
        title="Geospatial Platform (TEST)",
        dark=None,
        reload=False,
        show=False,
    )
