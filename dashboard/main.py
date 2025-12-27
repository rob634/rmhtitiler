"""
Geospatial Platform Dashboard - NiceGUI Interface.

This module provides the NiceGUI dashboard that integrates with TiTiler.
It can run in two modes:
1. Integrated: Mounted onto the TiTiler FastAPI app using ui.run_with()
2. Standalone: Running as a separate NiceGUI application

Usage:
    # Integrated mode (called from custom_pgstac_main.py):
    from dashboard.main import mount_dashboard
    mount_dashboard(app)

    # Standalone mode:
    python -m dashboard.main
"""

from nicegui import ui, app
from typing import Optional

from dashboard.config import config
from dashboard.client import TiTilerClient, PlatformClient
from dashboard.theme import apply_theme, COLORS
from dashboard.pages import home, status, pipelines, explorer


# Global clients
_titiler_client: Optional[TiTilerClient] = None
_platform_client: Optional[PlatformClient] = None


def get_titiler_client() -> TiTilerClient:
    """Get or create the TiTiler client."""
    global _titiler_client
    if _titiler_client is None:
        _titiler_client = TiTilerClient(config.TITILER_BASE_URL, timeout=config.HTTP_TIMEOUT)
    return _titiler_client


def get_platform_client() -> Optional[PlatformClient]:
    """Get or create the Platform API client."""
    global _platform_client
    if config.ENABLE_PLATFORM_API and _platform_client is None:
        _platform_client = PlatformClient(config.PLATFORM_API_URL, timeout=config.HTTP_TIMEOUT)
    return _platform_client if config.ENABLE_PLATFORM_API else None


@app.on_startup
async def startup():
    """Initialize on startup."""
    print("=" * 60)
    print("Geospatial Platform Dashboard")
    print("=" * 60)
    print(f"TiTiler URL: {config.TITILER_BASE_URL}")
    if config.ENABLE_PLATFORM_API:
        print(f"Platform API: {config.PLATFORM_API_URL}")
    print("=" * 60)


@app.on_shutdown
async def shutdown():
    """Cleanup on shutdown."""
    if _titiler_client:
        await _titiler_client.close()
    if _platform_client:
        await _platform_client.close()


def create_header():
    """Create the common header with navigation."""
    apply_theme()

    with ui.header(elevated=True).classes("items-center justify-between").style(f"background: {COLORS['navy']}"):
        with ui.row().classes("items-center gap-4"):
            with ui.link(target="/dashboard").classes("no-underline"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("public", size="md").classes("text-white")
                    ui.label("Geospatial Platform").classes("text-xl font-bold text-white")

        with ui.row().classes("items-center gap-2"):
            nav_items = [
                ("Status", "/dashboard/status", "favorite"),
                ("Pipelines", "/dashboard/pipelines", "alt_route"),
                ("Explorer", "/dashboard/explorer", "storage"),
            ]
            for label, link, icon in nav_items:
                with ui.link(target=link).classes("no-underline"):
                    ui.button(label, icon=icon).props("flat").classes("text-white")

            # TiTiler API link
            with ui.link(target="/").classes("no-underline"):
                ui.button("API", icon="api").props("flat").classes("text-white")

            # Dark mode toggle
            dark = ui.dark_mode()
            ui.button(icon="dark_mode", on_click=lambda: dark.toggle()).props("flat round").classes("text-white")


def create_sidebar():
    """Create the left sidebar navigation."""
    with ui.left_drawer(value=False).classes("bg-gray-50") as drawer:
        with ui.column().classes("gap-2 p-4"):
            ui.label("Navigation").classes("text-lg font-bold mb-2")

            nav_items = [
                ("home", "Home", "/dashboard"),
                ("favorite", "System Status", "/dashboard/status"),
                ("alt_route", "Pipelines", "/dashboard/pipelines"),
                ("storage", "Data Explorer", "/dashboard/explorer"),
            ]

            for icon, label, link in nav_items:
                with ui.link(target=link).classes("no-underline w-full"):
                    with ui.row().classes("items-center gap-3 p-3 rounded-lg hover:bg-gray-200 w-full"):
                        ui.icon(icon).classes("text-gray-600")
                        ui.label(label).classes("text-gray-800")

            ui.separator().classes("my-4")

            # Connection info
            ui.label("Connected to:").classes("text-xs text-gray-500")
            ui.label("TiTiler (local)").classes("text-xs font-mono text-blue-600")
            if config.ENABLE_PLATFORM_API:
                ui.label(config.PLATFORM_API_URL.split("//")[1].split(".")[0]).classes("text-xs font-mono text-green-600")

    return drawer


# =============================================================================
# PAGES
# =============================================================================

@ui.page("/dashboard")
def dashboard_home():
    """Dashboard home page."""
    create_header()
    create_sidebar()
    with ui.column().classes("w-full"):
        home.create_page()


@ui.page("/dashboard/status")
def dashboard_status():
    """System status page."""
    create_header()
    create_sidebar()
    with ui.column().classes("w-full"):
        status.create_page(get_titiler_client(), get_platform_client())


@ui.page("/dashboard/pipelines")
def dashboard_pipelines():
    """Pipelines page."""
    create_header()
    create_sidebar()
    with ui.column().classes("w-full"):
        pipelines.create_page(get_platform_client())


@ui.page("/dashboard/explorer")
def dashboard_explorer():
    """Data explorer page."""
    create_header()
    create_sidebar()
    with ui.column().classes("w-full"):
        explorer.create_page(get_platform_client(), get_titiler_client())


# =============================================================================
# INTEGRATION FUNCTIONS
# =============================================================================

def mount_dashboard(fastapi_app, storage_secret: str = "geospatial-dashboard-secret"):
    """
    Mount the NiceGUI dashboard onto an existing FastAPI application.

    This is the recommended way to integrate the dashboard with TiTiler.
    Call this from custom_pgstac_main.py after creating the FastAPI app.

    Args:
        fastapi_app: The FastAPI application instance
        storage_secret: Secret for NiceGUI's storage feature

    Example:
        from dashboard.main import mount_dashboard
        mount_dashboard(app)
    """
    ui.run_with(
        fastapi_app,
        storage_secret=storage_secret,
        title="Geospatial Platform",
        favicon="https://cdn-icons-png.flaticon.com/512/2991/2991148.png",
    )


# =============================================================================
# STANDALONE MODE
# =============================================================================

if __name__ in {"__main__", "__mp_main__"}:
    # Standalone mode - run NiceGUI on its own port
    ui.run(
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        title="Geospatial Platform",
        favicon="https://cdn-icons-png.flaticon.com/512/2991/2991148.png",
        dark=None,
        reload=False,
        show=False,
    )
