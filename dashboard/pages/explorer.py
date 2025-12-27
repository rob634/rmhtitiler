"""
Data Explorer Page.

Explore the platform's data sources:
- Azure Blob Storage (Bronze, Silver, Gold zones)
- STAC Collections and Items
- Database tables and schemas
"""

from nicegui import ui
from typing import Any, Dict, List, Optional
from datetime import datetime

from dashboard.client import PlatformClient, TiTilerClient
from dashboard.config import config


class ExplorerPage:
    """Data Explorer page state and logic."""

    def __init__(self, platform_client: Optional[PlatformClient], titiler_client: TiTilerClient):
        self.platform_client = platform_client
        self.titiler_client = titiler_client

        # Storage state
        self.zones: Dict[str, Any] = {}
        self.blobs: List[Dict[str, Any]] = []
        self.selected_zone = ""
        self.selected_container = ""
        self.prefix = ""
        self.limit = 50

        # STAC state
        self.stac_collections: List[Dict[str, Any]] = []
        self.stac_items: List[Dict[str, Any]] = []
        self.selected_collection = ""

        # Common state
        self.loading = False
        self.error: Optional[str] = None
        self.active_tab = "storage"

    async def load_zones(self):
        """Load storage zones."""
        if not self.platform_client:
            self.error = "Platform API not configured"
            return

        try:
            data = await self.platform_client.get_storage_zones()
            self.zones = data.get("zones", {})
            self.error = None
        except Exception as e:
            self.error = str(e)
            self.zones = {}

    async def load_blobs(self):
        """Load blobs from selected container."""
        if not self.platform_client or not self.selected_zone or not self.selected_container:
            return

        self.loading = True
        try:
            data = await self.platform_client.get_blobs(
                zone=self.selected_zone,
                container=self.selected_container,
                prefix=self.prefix if self.prefix else None,
                limit=self.limit,
            )
            self.blobs = data.get("blobs", [])
            self.error = None
        except Exception as e:
            self.error = str(e)
            self.blobs = []
        finally:
            self.loading = False

    async def load_stac_collections(self):
        """Load STAC collections."""
        if not self.platform_client:
            return

        self.loading = True
        try:
            data = await self.platform_client.get_stac_collections()
            self.stac_collections = data.get("collections", [])
            self.error = None
        except Exception as e:
            self.error = str(e)
            self.stac_collections = []
        finally:
            self.loading = False

    async def load_stac_items(self, collection_id: str):
        """Load items for a STAC collection."""
        if not self.platform_client:
            return

        self.loading = True
        try:
            data = await self.platform_client.get_stac_items(collection_id, limit=50)
            self.stac_items = data.get("items", data.get("features", []))
            self.error = None
        except Exception as e:
            self.error = str(e)
            self.stac_items = []
        finally:
            self.loading = False


def create_page(platform_client: Optional[PlatformClient], titiler_client: TiTilerClient):
    """Create the Data Explorer page."""
    page = ExplorerPage(platform_client, titiler_client)

    with ui.column().classes("gap-6 p-6 w-full max-w-7xl mx-auto"):
        # Header
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("Data Explorer").classes("text-2xl font-bold")
                ui.label("Browse storage, STAC collections, and database tables").classes("text-gray-500")

        # Tabs
        with ui.tabs().classes("w-full") as tabs:
            storage_tab = ui.tab("storage", label="Object Storage", icon="storage")
            stac_tab = ui.tab("stac", label="STAC Catalog", icon="satellite_alt")
            db_tab = ui.tab("database", label="Database", icon="table_chart")

        # Tab Panels
        with ui.tab_panels(tabs, value="storage").classes("w-full"):
            # Storage Panel
            with ui.tab_panel("storage"):
                create_storage_panel(page)

            # STAC Panel
            with ui.tab_panel("stac"):
                create_stac_panel(page)

            # Database Panel
            with ui.tab_panel("database"):
                create_database_panel(page)


def create_storage_panel(page: ExplorerPage):
    """Create the storage browser panel."""
    container_select = None
    files_container = None

    with ui.column().classes("gap-4 w-full"):
        # Controls
        with ui.card().classes("w-full"):
            with ui.row().classes("items-end gap-4 flex-wrap"):
                # Zone dropdown
                with ui.column().classes("gap-1"):
                    ui.label("Zone").classes("text-sm font-medium text-gray-600")
                    zone_select = ui.select(
                        options={},
                        value="",
                        on_change=lambda e: on_zone_change(e.value),
                    ).classes("w-48")

                # Container dropdown
                with ui.column().classes("gap-1"):
                    ui.label("Container").classes("text-sm font-medium text-gray-600")
                    container_select = ui.select(
                        options={"": "Select zone first"},
                        value="",
                        on_change=lambda e: setattr(page, "selected_container", e.value),
                    ).classes("w-48")

                # Path filter
                with ui.column().classes("gap-1"):
                    ui.label("Path Filter").classes("text-sm font-medium text-gray-600")
                    ui.input(
                        placeholder="e.g., data/2025/",
                        on_change=lambda e: setattr(page, "prefix", e.value),
                    ).classes("w-48")

                # Load button
                load_btn = ui.button("Load Files", icon="refresh", on_click=lambda: load_files())
                load_btn.props("color=primary")
                load_btn.disable()

        # Stats
        stats_container = ui.element("div").classes("w-full")

        # Files
        files_container = ui.column().classes("w-full")

    async def init_zones():
        """Initialize zones dropdown."""
        if not page.platform_client:
            with files_container:
                with ui.card().classes("w-full bg-yellow-50 border-l-4 border-yellow-500"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("warning", color="orange")
                        ui.label("Platform API not configured. Enable ENABLE_PLATFORM_API to browse storage.").classes("text-yellow-800")
            return

        await page.load_zones()

        if page.zones:
            options = {}
            for zone_name, zone_info in page.zones.items():
                if zone_info.get("error") or not zone_info.get("containers"):
                    continue
                account = zone_info.get("account", "")
                count = zone_info.get("container_count", 0)
                options[zone_name] = f"{zone_name.upper()} ({count} containers)"

            zone_select.options = options
            zone_select.value = ""

    async def on_zone_change(zone: str):
        """Handle zone selection."""
        page.selected_zone = zone
        page.selected_container = ""
        page.blobs = []

        if not zone or zone not in page.zones:
            container_select.options = {"": "Select zone first"}
            container_select.value = ""
            load_btn.disable()
            return

        zone_info = page.zones[zone]
        containers = zone_info.get("containers", [])

        if containers:
            container_select.options = {c: c for c in containers}
            container_select.value = ""
        else:
            container_select.options = {"": "No containers"}
            container_select.value = ""

        load_btn.enable()

    async def load_files():
        """Load files from selected container."""
        if not page.selected_zone or not page.selected_container:
            return

        load_btn.disable()
        files_container.clear()
        stats_container.clear()

        with files_container:
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center gap-2 justify-center p-8"):
                    ui.spinner()
                    ui.label("Loading files...")

        await page.load_blobs()

        files_container.clear()
        stats_container.clear()

        if page.error:
            with files_container:
                with ui.card().classes("w-full bg-red-50 border-l-4 border-red-500"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("error", color="red")
                        ui.label(f"Error: {page.error}").classes("text-red-800")
            load_btn.enable()
            return

        # Render stats
        total_size = sum(b.get("size", 0) for b in page.blobs) / (1024 * 1024)
        with stats_container:
            with ui.card().classes("w-full"):
                with ui.row().classes("gap-8"):
                    with ui.column().classes("text-center"):
                        ui.label("Files").classes("text-xs text-gray-500 uppercase")
                        ui.label(str(len(page.blobs))).classes("text-xl font-bold text-blue-600")
                    with ui.column().classes("text-center"):
                        ui.label("Total Size").classes("text-xs text-gray-500 uppercase")
                        ui.label(f"{total_size:.2f} MB").classes("text-xl font-bold text-gray-800")

        # Render files
        render_files(files_container, page.blobs)

        load_btn.enable()

    # Initialize zones
    ui.timer(0.1, init_zones, once=True)


def render_files(container, blobs: List[Dict[str, Any]]):
    """Render files table."""
    with container:
        if not blobs:
            with ui.card().classes("w-full text-center py-12"):
                ui.icon("folder_open", size="xl").classes("text-gray-300")
                ui.label("No Files Found").classes("text-xl font-bold text-gray-600 mt-4")
            return

        with ui.card().classes("w-full"):
            columns = [
                {"name": "name", "label": "Name", "field": "name", "align": "left", "sortable": True},
                {"name": "size", "label": "Size", "field": "size", "align": "right", "sortable": True},
                {"name": "modified", "label": "Modified", "field": "modified", "align": "left"},
                {"name": "type", "label": "Type", "field": "type", "align": "center"},
            ]

            rows = []
            for blob in blobs:
                name = blob.get("name", "")
                short_name = name.split("/")[-1] if "/" in name else name
                size = blob.get("size", 0)
                size_mb = size / (1024 * 1024)

                last_modified = blob.get("last_modified", "")
                if last_modified:
                    try:
                        dt = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
                        date_str = dt.strftime("%Y-%m-%d")
                    except Exception:
                        date_str = "N/A"
                else:
                    date_str = "N/A"

                ext = short_name.split(".")[-1].upper() if "." in short_name else "File"

                rows.append({
                    "name": short_name,
                    "full_name": name,
                    "size": f"{size_mb:.2f} MB",
                    "modified": date_str,
                    "type": ext,
                })

            ui.table(columns=columns, rows=rows, row_key="full_name").classes("w-full").props("flat bordered")


def create_stac_panel(page: ExplorerPage):
    """Create the STAC catalog panel."""
    collections_container = ui.column().classes("w-full")
    items_container = ui.column().classes("w-full")

    with ui.column().classes("gap-4 w-full"):
        # Header
        with ui.row().classes("items-center gap-4"):
            refresh_btn = ui.button("Load Collections", icon="refresh", on_click=lambda: load_collections())
            refresh_btn.props("color=primary")

        # Collections
        collections_container

        # Items
        items_container

    async def load_collections():
        """Load STAC collections."""
        if not page.platform_client:
            with collections_container:
                collections_container.clear()
                with ui.card().classes("w-full bg-yellow-50 border-l-4 border-yellow-500"):
                    ui.label("Platform API not configured").classes("text-yellow-800")
            return

        refresh_btn.disable()
        collections_container.clear()
        items_container.clear()

        with collections_container:
            with ui.row().classes("items-center gap-2"):
                ui.spinner()
                ui.label("Loading collections...")

        await page.load_stac_collections()

        collections_container.clear()

        if page.error:
            with collections_container:
                with ui.card().classes("w-full bg-red-50 border-l-4 border-red-500"):
                    ui.label(f"Error: {page.error}").classes("text-red-800")
            refresh_btn.enable()
            return

        # Render collections
        with collections_container:
            if not page.stac_collections:
                with ui.card().classes("w-full text-center py-8"):
                    ui.label("No STAC collections found").classes("text-gray-500")
            else:
                with ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"):
                    for collection in page.stac_collections:
                        coll_id = collection.get("id", "unknown")
                        title = collection.get("title", coll_id)
                        description = collection.get("description", "")[:100]
                        item_count = collection.get("item_count", "?")

                        with ui.card().classes("cursor-pointer hover:shadow-lg transition-all").on(
                            "click", lambda c=coll_id: on_collection_click(c)
                        ):
                            with ui.column().classes("gap-2"):
                                ui.label(title).classes("font-bold")
                                ui.label(description).classes("text-sm text-gray-600")
                                with ui.row().classes("gap-2"):
                                    ui.badge(coll_id).classes("bg-blue-100 text-blue-700 text-xs")
                                    ui.badge(f"{item_count} items").classes("bg-gray-100 text-gray-700 text-xs")

        refresh_btn.enable()

    async def on_collection_click(collection_id: str):
        """Handle collection click."""
        page.selected_collection = collection_id
        items_container.clear()

        with items_container:
            with ui.row().classes("items-center gap-2"):
                ui.spinner()
                ui.label(f"Loading items from {collection_id}...")

        await page.load_stac_items(collection_id)

        items_container.clear()

        with items_container:
            with ui.card().classes("w-full"):
                ui.label(f"Items in {collection_id}").classes("font-bold text-lg mb-4")

                if not page.stac_items:
                    ui.label("No items found").classes("text-gray-500")
                else:
                    for item in page.stac_items[:10]:  # Show first 10
                        item_id = item.get("id", "unknown")
                        props = item.get("properties", {})
                        datetime_str = props.get("datetime", "N/A")

                        with ui.row().classes("items-center gap-4 py-2 border-b"):
                            ui.label(item_id).classes("font-mono text-sm")
                            ui.label(datetime_str[:10] if datetime_str != "N/A" else "N/A").classes("text-sm text-gray-500")


def create_database_panel(page: ExplorerPage):
    """Create the database explorer panel."""
    with ui.column().classes("gap-4 w-full"):
        with ui.card().classes("w-full text-center py-12"):
            ui.icon("table_chart", size="xl").classes("text-gray-300")
            ui.label("Database Explorer").classes("text-xl font-bold text-gray-600 mt-4")
            ui.label("Coming soon - Browse PostgreSQL tables and schemas").classes("text-gray-500")

            with ui.row().classes("justify-center mt-4 gap-2"):
                ui.badge("pgstac").classes("bg-blue-100 text-blue-700")
                ui.badge("app.jobs").classes("bg-green-100 text-green-700")
                ui.badge("app.tasks").classes("bg-purple-100 text-purple-700")
