"""
Home page - navigation hub for the dashboard.
"""

from nicegui import ui


def create_page():
    """Create the home/landing page."""
    with ui.column().classes("gap-8 p-6 w-full max-w-6xl mx-auto"):
        # Hero section
        with ui.column().classes("items-center text-center gap-4 py-8"):
            ui.icon("public", size="xl").classes("text-blue-600")
            ui.label("Geospatial Platform Dashboard").classes("text-3xl font-bold")
            ui.label(
                "TiTiler tile server with integrated monitoring for the geospatial ETL platform"
            ).classes("text-gray-600 max-w-2xl")

        # Navigation cards
        with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"):
            # System Status
            create_nav_card(
                icon="favorite",
                title="System Status",
                description="Architecture diagram with live health indicators and component monitoring",
                link="/dashboard/status",
                color="green",
            )

            # Pipelines
            create_nav_card(
                icon="alt_route",
                title="ETL Pipelines",
                description="Monitor vector and raster data processing workflows",
                link="/dashboard/pipelines",
                color="blue",
            )

            # Data Explorer
            create_nav_card(
                icon="storage",
                title="Data Explorer",
                description="Browse Azure Blob Storage, STAC collections, and databases",
                link="/dashboard/explorer",
                color="purple",
            )

            # TiTiler API
            create_nav_card(
                icon="api",
                title="TiTiler API",
                description="COG endpoints, pgSTAC searches, and Xarray tiles",
                link="/",
                color="orange",
            )

            # STAC Catalog
            create_nav_card(
                icon="satellite_alt",
                title="STAC Catalog",
                description="Browse raster dataset metadata and collections",
                link="/dashboard/explorer",
                color="cyan",
            )

            # Health Check
            create_nav_card(
                icon="health_and_safety",
                title="Health Check",
                description="API health endpoint with database and storage status",
                link="/healthz",
                color="gray",
            )

        # Architecture info
        with ui.card().classes("w-full mt-4"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("architecture", size="sm").classes("text-gray-500")
                ui.label("Architecture").classes("font-semibold")

            ui.label(
                "TiTiler-pgSTAC + NiceGUI | Azure Managed Identity | PostgreSQL/PostGIS + pgSTAC | "
                "STAC v1.0 | Cloud Optimized GeoTIFF"
            ).classes("text-sm text-gray-600 mt-2")

            with ui.row().classes("gap-4 mt-3"):
                with ui.column().classes("gap-1"):
                    ui.badge("Bronze").classes("bg-amber-100 text-amber-800")
                    ui.label("Raw input data").classes("text-xs text-gray-500")
                with ui.column().classes("gap-1"):
                    ui.badge("Silver").classes("bg-gray-200 text-gray-700")
                    ui.label("Processed COGs").classes("text-xs text-gray-500")
                with ui.column().classes("gap-1"):
                    ui.badge("Gold").classes("bg-yellow-100 text-yellow-800")
                    ui.label("STAC cataloged").classes("text-xs text-gray-500")

        # Quick Links
        with ui.card().classes("w-full"):
            ui.label("Quick Links").classes("text-lg font-bold mb-4 pb-2 border-b-2 border-blue-500")
            with ui.row().classes("gap-4 flex-wrap"):
                quick_links = [
                    ("COG Tiles", "/cog/", "image"),
                    ("Xarray Tiles", "/xarray/", "grid_on"),
                    ("pgSTAC Searches", "/searches/list", "search"),
                    ("MosaicJSON", "/mosaicjson/", "layers"),
                    ("API Docs", "/docs", "description"),
                ]
                for label, link, icon in quick_links:
                    with ui.link(target=link).classes("no-underline"):
                        ui.button(label, icon=icon).props("outline").classes("text-blue-600")


def create_nav_card(icon: str, title: str, description: str, link: str, color: str):
    """Create a navigation card."""
    color_classes = {
        "green": "hover:border-green-500 hover:bg-green-50",
        "blue": "hover:border-blue-500 hover:bg-blue-50",
        "purple": "hover:border-purple-500 hover:bg-purple-50",
        "orange": "hover:border-orange-500 hover:bg-orange-50",
        "cyan": "hover:border-cyan-500 hover:bg-cyan-50",
        "gray": "hover:border-gray-500 hover:bg-gray-50",
    }

    icon_colors = {
        "green": "text-green-600",
        "blue": "text-blue-600",
        "purple": "text-purple-600",
        "orange": "text-orange-600",
        "cyan": "text-cyan-600",
        "gray": "text-gray-600",
    }

    with ui.link(target=link).classes("no-underline"):
        with ui.card().classes(
            f"cursor-pointer transition-all duration-200 border-2 border-transparent h-32 {color_classes.get(color, '')}"
        ):
            with ui.column().classes("gap-2 h-full"):
                # Icon and title in same row
                with ui.row().classes("items-center gap-2"):
                    ui.icon(icon, size="md").classes(icon_colors.get(color, "text-gray-600"))
                    ui.label(title).classes("font-bold text-gray-800")
                # Description below
                ui.label(description).classes("text-sm text-gray-600")
