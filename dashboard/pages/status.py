"""
System Status Page.

Displays:
- Architecture diagram with live status indicators
- TiTiler health status
- Platform API health status (if enabled)
- Component details
"""

from nicegui import ui
from typing import Any, Dict, Optional

from dashboard.client import TiTilerClient, PlatformClient
from dashboard.config import config
from dashboard.components.architecture_diagram import create_native_diagram
from dashboard.theme import status_badge, health_indicator, status_dot


# Status color mapping
STATUS_COLORS = {
    "healthy": {"bg": "bg-green-100", "text": "text-green-800", "border": "border-green-500", "icon": "check_circle"},
    "degraded": {"bg": "bg-yellow-100", "text": "text-yellow-800", "border": "border-yellow-500", "icon": "warning"},
    "unhealthy": {"bg": "bg-red-100", "text": "text-red-800", "border": "border-red-500", "icon": "error"},
    "disabled": {"bg": "bg-gray-100", "text": "text-gray-600", "border": "border-gray-400", "icon": "block"},
}


def get_status_style(status: str) -> Dict[str, str]:
    """Get color styles for a status."""
    return STATUS_COLORS.get(status.lower(), STATUS_COLORS["unhealthy"])


class StatusPage:
    """Status page state and logic."""

    def __init__(self, titiler_client: TiTilerClient, platform_client: Optional[PlatformClient]):
        self.titiler_client = titiler_client
        self.platform_client = platform_client
        self.titiler_health: Optional[Dict[str, Any]] = None
        self.platform_health: Optional[Dict[str, Any]] = None
        self.loading = True
        self.titiler_error: Optional[str] = None
        self.platform_error: Optional[str] = None

    async def load_titiler_health(self):
        """Load TiTiler health data."""
        try:
            self.titiler_health = await self.titiler_client.get_health()
            self.titiler_error = None
        except Exception as e:
            self.titiler_error = str(e)
            self.titiler_health = None

    async def load_platform_health(self):
        """Load Platform API health data."""
        if not self.platform_client:
            return

        try:
            self.platform_health = await self.platform_client.get_health()
            self.platform_error = None
        except Exception as e:
            self.platform_error = str(e)
            self.platform_health = None

    async def load_all(self):
        """Load all health data."""
        self.loading = True
        await self.load_titiler_health()
        if config.ENABLE_PLATFORM_API:
            await self.load_platform_health()
        self.loading = False


def create_page(titiler_client: TiTilerClient, platform_client: Optional[PlatformClient]):
    """Create the System Status page."""
    page = StatusPage(titiler_client, platform_client)

    with ui.column().classes("gap-6 p-6 w-full max-w-7xl mx-auto"):
        # Header
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("System Status").classes("text-2xl font-bold")
                ui.label("Real-time platform health monitoring").classes("text-gray-500")

            refresh_btn = ui.button("Refresh", icon="refresh", on_click=lambda: refresh())
            refresh_btn.props("outline")

        # Architecture Diagram
        diagram_container = ui.column().classes("w-full")

        # Status Banners
        status_container = ui.column().classes("w-full gap-4")

        # Component Details
        details_container = ui.column().classes("w-full gap-4")

    async def refresh():
        """Refresh all health data."""
        refresh_btn.disable()
        diagram_container.clear()
        status_container.clear()
        details_container.clear()

        # Show loading
        with status_container:
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.spinner()
                    ui.label("Loading health data...")

        await page.load_all()

        status_container.clear()
        diagram_container.clear()
        details_container.clear()

        # Build component status for diagram
        components = {}
        if page.platform_health:
            components = page.platform_health.get("components", {})

        # Add TiTiler status
        if page.titiler_health:
            titiler_status = page.titiler_health.get("status", "unknown")
            if titiler_status == "ok":
                titiler_status = "healthy"
            components["titiler"] = {"status": titiler_status}

        # Render architecture diagram
        with diagram_container:
            create_native_diagram(components)

        # Render status banners
        render_status_banners(status_container, page)

        # Render component details
        render_details(details_container, page)

        refresh_btn.enable()

    # Initial load
    ui.timer(0.1, refresh, once=True)


def render_status_banners(container, page: StatusPage):
    """Render the status banners for TiTiler and Platform API."""
    with container:
        # TiTiler Status
        if page.titiler_error:
            with ui.card().classes("w-full bg-red-50 border-l-4 border-red-500"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon("error", color="red", size="lg")
                    with ui.column().classes("gap-0"):
                        ui.label("TiTiler Unavailable").classes("text-lg font-bold text-red-800")
                        ui.label(f"Error: {page.titiler_error}").classes("text-sm text-red-600")
        elif page.titiler_health:
            status = page.titiler_health.get("status", "unknown")
            if status == "ok":
                status = "healthy"
            style = get_status_style(status)

            with ui.card().classes(f"w-full {style['bg']} border-l-4 {style['border']}"):
                with ui.row().classes("items-center justify-between"):
                    with ui.row().classes("items-center gap-3"):
                        ui.icon(style["icon"], size="lg").classes(style["text"])
                        with ui.column().classes("gap-0"):
                            ui.label("TiTiler Tile Server").classes(f"text-lg font-bold {style['text']}")
                            version = page.titiler_health.get("version", "unknown")
                            ui.label(f"Version {version}").classes("text-sm text-gray-600")

                    # Quick stats
                    with ui.row().classes("gap-6"):
                        db = page.titiler_health.get("database", {})
                        storage = page.titiler_health.get("storage", {})

                        if db.get("connected"):
                            with ui.row().classes("items-center gap-1"):
                                ui.icon("check_circle", size="xs", color="green")
                                ui.label("Database").classes("text-sm")

                        if storage.get("token_valid"):
                            with ui.row().classes("items-center gap-1"):
                                ui.icon("check_circle", size="xs", color="green")
                                ui.label("Storage").classes("text-sm")

        # Platform API Status (if enabled)
        if config.ENABLE_PLATFORM_API:
            if page.platform_error:
                with ui.card().classes("w-full bg-yellow-50 border-l-4 border-yellow-500"):
                    with ui.row().classes("items-center gap-3"):
                        ui.icon("warning", color="orange", size="lg")
                        with ui.column().classes("gap-0"):
                            ui.label("Platform API Unavailable").classes("text-lg font-bold text-yellow-800")
                            ui.label(f"Error: {page.platform_error}").classes("text-sm text-yellow-600")
            elif page.platform_health:
                overall_status = page.platform_health.get("status", "unknown")
                components = page.platform_health.get("components", {})
                style = get_status_style(overall_status)

                # Count component statuses
                status_counts = {"healthy": 0, "degraded": 0, "unhealthy": 0}
                for comp in components.values():
                    s = comp.get("status", "unknown").lower()
                    if s in status_counts:
                        status_counts[s] += 1

                with ui.card().classes(f"w-full {style['bg']} border-l-4 {style['border']}"):
                    with ui.row().classes("items-center justify-between"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon(style["icon"], size="lg").classes(style["text"])
                            with ui.column().classes("gap-0"):
                                ui.label("Platform API").classes(f"text-lg font-bold {style['text']}")
                                ui.label(f"{sum(status_counts.values())} components checked").classes("text-sm text-gray-600")

                        with ui.row().classes("gap-4"):
                            for status, count in status_counts.items():
                                if count > 0:
                                    s = get_status_style(status)
                                    with ui.row().classes("items-center gap-1"):
                                        ui.icon(s["icon"], size="xs").classes(s["text"])
                                        ui.label(f"{count} {status}").classes(f"text-sm {s['text']}")


def render_details(container, page: StatusPage):
    """Render detailed component information."""
    with container:
        # TiTiler Details
        if page.titiler_health:
            with ui.card().classes("w-full"):
                ui.label("TiTiler Details").classes("text-lg font-bold mb-4")

                with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"):
                    # Version info
                    with ui.column().classes("gap-1"):
                        ui.label("Version").classes("text-xs text-gray-500 uppercase")
                        ui.label(page.titiler_health.get("version", "N/A")).classes("font-bold")

                    # Database
                    db = page.titiler_health.get("database", {})
                    with ui.column().classes("gap-1"):
                        ui.label("Database").classes("text-xs text-gray-500 uppercase")
                        if db.get("connected"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("check_circle", size="xs", color="green")
                                ui.label("Connected").classes("font-bold text-green-600")
                        else:
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("error", size="xs", color="red")
                                ui.label("Disconnected").classes("font-bold text-red-600")

                    # Storage Token
                    storage = page.titiler_health.get("storage", {})
                    with ui.column().classes("gap-1"):
                        ui.label("Storage Token").classes("text-xs text-gray-500 uppercase")
                        if storage.get("token_valid"):
                            expires = storage.get("expires_in_minutes", 0)
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("check_circle", size="xs", color="green")
                                ui.label(f"Valid ({expires:.0f}m remaining)").classes("font-bold text-green-600")
                        else:
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("warning", size="xs", color="orange")
                                ui.label("Not configured").classes("font-bold text-orange-600")

                    # Features
                    features = page.titiler_health.get("features", {})
                    if features:
                        with ui.column().classes("gap-1"):
                            ui.label("Features").classes("text-xs text-gray-500 uppercase")
                            with ui.row().classes("gap-2 flex-wrap"):
                                for feature, enabled in features.items():
                                    if enabled:
                                        ui.badge(feature).classes("bg-blue-100 text-blue-700 text-xs")

                    # Hardware
                    hw = page.titiler_health.get("hardware", {})
                    if hw:
                        with ui.column().classes("gap-1"):
                            ui.label("CPU").classes("text-xs text-gray-500 uppercase")
                            cpu = hw.get("cpu_percent", 0)
                            with ui.row().classes("items-center gap-2"):
                                ui.label(f"{cpu:.1f}%").classes("font-bold")
                                ui.linear_progress(value=cpu/100, show_value=False).classes("w-20").props("color=blue")

                        with ui.column().classes("gap-1"):
                            ui.label("Memory").classes("text-xs text-gray-500 uppercase")
                            mem = hw.get("memory_percent", 0)
                            color = "green" if mem < 70 else "orange" if mem < 85 else "red"
                            with ui.row().classes("items-center gap-2"):
                                ui.label(f"{mem:.1f}%").classes("font-bold")
                                ui.linear_progress(value=mem/100, show_value=False).classes("w-20").props(f"color={color}")

        # Platform API Component Details
        if page.platform_health and config.ENABLE_PLATFORM_API:
            components = page.platform_health.get("components", {})
            if components:
                with ui.card().classes("w-full"):
                    ui.label("Platform Components").classes("text-lg font-bold mb-4")

                    with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 gap-4"):
                        priority_order = [
                            "hardware", "database", "service_bus", "storage_containers",
                            "pgstac", "jobs", "imports"
                        ]

                        sorted_components = []
                        for name in priority_order:
                            if name in components:
                                sorted_components.append((name, components[name]))
                        for name, comp in components.items():
                            if name not in priority_order:
                                sorted_components.append((name, comp))

                        for name, comp in sorted_components:
                            status = comp.get("status", "unknown")
                            description = comp.get("description", "")
                            style = get_status_style(status)

                            with ui.card().classes(f"border-l-4 {style['border']}"):
                                with ui.row().classes("items-center justify-between w-full"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.icon(style["icon"], size="sm").classes(style["text"])
                                        ui.label(name.replace("_", " ").title()).classes("font-bold")
                                    ui.badge(status.upper()).classes(f"{style['bg']} {style['text']} text-xs")

                                if description:
                                    ui.label(description).classes("text-sm text-gray-600 mt-1")
