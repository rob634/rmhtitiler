"""
Azure Architecture Diagram Component.

Interactive diagram showing the geospatial platform architecture
matching layout.txt with Azure-style icons and live status indicators.

Uses NiceGUI's ui.grid() for proper grid layout.

Layout from layout.txt:
     |    C1       |    C2       |      C3       |    C4       |     C5     |    C6
R1   |             |             |               | Input Data  | Output Data|
R2   |             |             | Task Table    |             | PostGIS    |
R3   |             | Job Table   | Parallel Task | I/O Worker  |            | OGC Feature
R4   | Platform API| Orchestrator| Compute Task  | RAM Worker  |            | STAC API
R5   |             | Job Queue   | Long Task     | Long Worker |            | TiTiler
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from nicegui import ui


# =============================================================================
# CONSTANTS
# =============================================================================

STATUS_COLORS = {
    "healthy": {"color": "#10B981", "tailwind": "green"},
    "degraded": {"color": "#F59E0B", "tailwind": "yellow"},
    "warning": {"color": "#F59E0B", "tailwind": "yellow"},
    "unhealthy": {"color": "#EF4444", "tailwind": "red"},
    "unknown": {"color": "#9CA3AF", "tailwind": "gray"},
    "disabled": {"color": "#D1D5DB", "tailwind": "gray"},
}

COMPONENT_STYLES = {
    "Function App": {
        "bg": "bg-amber-50",
        "border": "border-amber-400",
        "text": "text-amber-800",
        "icon": "bolt",
        "icon_color": "amber",
    },
    "Storage Account": {
        "bg": "bg-green-50",
        "border": "border-green-500",
        "text": "text-green-800",
        "icon": "inventory_2",
        "icon_color": "green",
    },
    "Azure Database for PostgreSQL": {
        "bg": "bg-blue-50",
        "border": "border-blue-600",
        "text": "text-blue-800",
        "icon": "storage",
        "icon_color": "blue",
    },
    "Service Bus Queue": {
        "bg": "bg-sky-50",
        "border": "border-sky-500",
        "text": "text-sky-800",
        "icon": "cloud_download",
        "icon_color": "primary",
    },
    "Web App": {
        "bg": "bg-purple-50",
        "border": "border-purple-500",
        "text": "text-purple-800",
        "icon": "public",
        "icon_color": "purple",
    },
}


# =============================================================================
# DATA LOADING
# =============================================================================

def load_components() -> Dict[str, Any]:
    """Load component definitions from components.json."""
    possible_paths = [
        Path(__file__).parent / "components.json",
        Path(__file__).parent.parent / "components.json",
    ]
    for json_path in possible_paths:
        if json_path.exists():
            with open(json_path) as f:
                data = json.load(f)
                return data.get("system", {}).get("diagram_components", {})
    return get_default_components()


def get_default_components() -> Dict[str, Any]:
    """Default component definitions."""
    return {
        "platform_api": {"label": "Platform API", "azure_type": "Function App", "desc": "REST API for job submission"},
        "orchestrator": {"label": "Orchestrator", "azure_type": "Function App", "desc": "Job orchestration engine"},
        "job_queue": {"label": "Job Queue", "azure_type": "Service Bus Queue", "desc": "Main job queue"},
        "job_table": {"label": "Job Table", "azure_type": "Azure Database for PostgreSQL", "desc": "Job state storage"},
        "task_table": {"label": "Task Table", "azure_type": "Azure Database for PostgreSQL", "desc": "Task state storage"},
        "bronze_storage": {"label": "Input Data", "azure_type": "Storage Account", "desc": "Raw data (Bronze)"},
        "silver_storage": {"label": "Output Data", "azure_type": "Storage Account", "desc": "Processed data (Silver)"},
        "geo_tables": {"label": "PostGIS", "azure_type": "Azure Database for PostgreSQL", "desc": "Geospatial database"},
        "parallel_task_queue": {"label": "Parallel Task", "azure_type": "Service Bus Queue", "desc": "I/O-bound tasks"},
        "parallel_task_worker": {"label": "I/O Worker", "azure_type": "Function App", "desc": "Handles I/O tasks"},
        "compute_task_queue": {"label": "Compute Task", "azure_type": "Service Bus Queue", "desc": "CPU-bound tasks"},
        "compute_task_worker": {"label": "RAM Worker", "azure_type": "Function App", "desc": "Handles compute tasks"},
        "long_task_queue": {"label": "Long Task", "azure_type": "Service Bus Queue", "desc": "Long-running tasks"},
        "long_task_worker": {"label": "Long Worker", "azure_type": "Web App", "desc": "Container app for long tasks"},
        "ogc_api": {"label": "OGC Features", "azure_type": "Function App", "desc": "OGC API - Features"},
        "aux_api": {"label": "STAC API", "azure_type": "Function App", "desc": "STAC metadata API"},
        "titiler_app": {"label": "TiTiler", "azure_type": "Web App", "desc": "Dynamic tile server"},
    }


# =============================================================================
# HELPERS
# =============================================================================

def get_status_color(status: str) -> Dict[str, str]:
    """Get color info for a status value."""
    return STATUS_COLORS.get(status.lower(), STATUS_COLORS["unknown"])


def get_component_style(azure_type: str) -> Dict[str, str]:
    """Get style dict for an Azure component type."""
    return COMPONENT_STYLES.get(azure_type, {
        "bg": "bg-gray-50",
        "border": "border-gray-300",
        "text": "text-gray-700",
        "icon": "help_outline",
        "icon_color": "gray",
    })


# =============================================================================
# COMPONENT DIALOG
# =============================================================================

def show_component_detail(component_id: str, config: Dict[str, Any], status: str = "unknown"):
    """Show a dialog with component details."""
    azure_type = config.get("azure_type", "Unknown")
    style = get_component_style(azure_type)
    status_info = get_status_color(status)

    with ui.dialog() as dialog, ui.card().classes("p-6 min-w-96"):
        with ui.row().classes("w-full items-center justify-between mb-4"):
            with ui.row().classes("items-center gap-3"):
                ui.icon(style["icon"], size="md", color=style["icon_color"])
                ui.label(config.get("label", component_id)).classes("text-xl font-bold")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")

        ui.separator()

        with ui.column().classes("gap-4 mt-4"):
            with ui.row().classes("items-center gap-3"):
                ui.label("Type:").classes("font-semibold text-gray-600 w-20")
                ui.badge(azure_type).classes(f"{style['bg']} {style['text']} border {style['border']}")

            with ui.row().classes("items-center gap-3"):
                ui.label("Status:").classes("font-semibold text-gray-600 w-20")
                with ui.row().classes("items-center gap-2"):
                    ui.icon("circle", size="xs", color=status_info["tailwind"])
                    ui.label(status.capitalize()).classes(f"font-medium text-{status_info['tailwind']}-600")

            desc = config.get("desc", "")
            if desc:
                with ui.row().classes("items-start gap-3"):
                    ui.label("Info:").classes("font-semibold text-gray-600 w-20")
                    ui.label(desc).classes("text-gray-700")

            with ui.row().classes("items-center gap-3"):
                ui.label("ID:").classes("font-semibold text-gray-600 w-20")
                ui.label(component_id).classes("font-mono text-sm text-gray-500 bg-gray-100 px-2 py-1 rounded")

        with ui.row().classes("w-full justify-end mt-6"):
            ui.button("Close", on_click=dialog.close).props("flat color=primary")

    dialog.open()


# =============================================================================
# COMPONENT BOX
# =============================================================================

def create_component_box(
    component_id: str,
    components: Dict[str, Any],
    status_data: Dict[str, Any],
    row: int,
    col: int,
) -> Optional[ui.element]:
    """Create an interactive component box positioned in the grid."""
    if component_id not in components:
        return None

    config = components[component_id]
    azure_type = config.get("azure_type", "Unknown")
    label = config.get("label", component_id)
    desc = config.get("desc", "")
    style = get_component_style(azure_type)

    status = "unknown"
    if component_id in status_data:
        status = status_data[component_id].get("status", "unknown")
    status_info = get_status_color(status)

    # Create square component card with grid positioning
    # Fixed size: 90x90px for uniform squares
    with ui.card().classes(
        f"cursor-pointer {style['bg']} border-2 {style['border']} "
        f"hover:shadow-lg transition-all duration-200 relative "
        f"flex items-center justify-center"
    ).style(
        f"grid-row: {row}; grid-column: {col}; "
        f"width: 90px; height: 90px; padding: 8px;"
    ).on("click", lambda: show_component_detail(component_id, config, status)) as card:

        # Status indicator dot
        ui.icon("circle", size="xs", color=status_info["tailwind"]).classes(
            "absolute -top-1 -right-1"
        )

        with ui.column().classes("items-center justify-center gap-1"):
            ui.icon(style["icon"], size="md", color=style["icon_color"])
            ui.label(label).classes(
                f"text-xs font-semibold text-center leading-tight {style['text']}"
            ).style("max-width: 74px;")

        card.tooltip(desc if desc else label)

    return card


# =============================================================================
# LEGEND
# =============================================================================

def create_legend():
    """Create the legend showing Azure types and status indicators."""
    with ui.row().classes("w-full flex-wrap gap-6 p-4 bg-gray-50 rounded-lg border mb-4"):
        # Azure Resource Types
        with ui.column().classes("gap-2"):
            ui.label("Azure Resources").classes("text-xs font-bold text-gray-500 uppercase tracking-wide")
            with ui.row().classes("flex-wrap gap-2"):
                legend_items = [
                    ("Function App", "bolt", "amber"),
                    ("Object Storage", "inventory_2", "green"),
                    ("PostgreSQL", "storage", "blue"),
                    ("Service Bus", "cloud_download", "primary"),
                    ("Web App", "public", "purple"),
                ]
                for name, icon, color in legend_items:
                    with ui.row().classes("items-center gap-1 px-2 py-1 rounded bg-white border text-xs"):
                        ui.icon(icon, size="xs", color=color)
                        ui.label(name)

        # Status Indicators
        with ui.column().classes("gap-2"):
            ui.label("Status").classes("text-xs font-bold text-gray-500 uppercase tracking-wide")
            with ui.row().classes("gap-4 text-xs"):
                for status_name, color in [("Healthy", "green"), ("Warning", "yellow"), ("Unhealthy", "red"), ("Unknown", "gray")]:
                    with ui.row().classes("items-center gap-1"):
                        ui.icon("circle", size="xs", color=color)
                        ui.label(status_name)


# =============================================================================
# MAIN DIAGRAM - Using NiceGUI ui.grid()
# =============================================================================

@ui.refreshable
def create_architecture_diagram(status_data: Optional[Dict[str, Any]] = None):
    """
    Create the architecture diagram using NiceGUI's ui.grid().

    Layout from layout.txt (6 columns x 5 rows):
         |    C1       |    C2       |      C3       |    C4       |     C5     |    C6
    R1   |             |             |               | Input Data  | Output Data|
    R2   |             |             | Task Table    |             | PostGIS    |
    R3   |             | Job Table   | Parallel Task | I/O Worker  |            | OGC Feature
    R4   | Platform API| Orchestrator| Compute Task  | RAM Worker  |            | STAC API
    R5   |             | Job Queue   | Long Task     | Long Worker |            | TiTiler
    """
    status_data = status_data or {}
    components = load_components()

    def comp(comp_id: str, row: int, col: int):
        """Helper to create a component at grid position."""
        create_component_box(comp_id, components, status_data, row, col)

    with ui.card().classes("w-full"):
        # Header
        with ui.row().classes("w-full items-center justify-between mb-4"):
            ui.label("System Architecture").classes("text-xl font-bold text-gray-800")

        # Legend
        create_legend()

        # Main diagram using CSS Grid - square layout
        # 6 columns x 5 rows, all cells same size
        with ui.element("div").classes("p-6 bg-slate-50 rounded-xl").style(
            "display: grid; "
            "grid-template-columns: repeat(6, 100px); "
            "grid-template-rows: repeat(5, 100px); "
            "gap: 12px; "
            "justify-content: center; "
            "align-items: center; "
            "justify-items: center;"
        ):
            # Row 1: Input Data (C4), Output Data (C5)
            comp("bronze_storage", 1, 4)
            comp("silver_storage", 1, 5)

            # Row 2: Task Table (C3), PostGIS (C5)
            comp("task_table", 2, 3)
            comp("geo_tables", 2, 5)

            # Row 3: Job Table (C2), Parallel Task (C3), I/O Worker (C4), OGC Features (C6)
            comp("job_table", 3, 2)
            comp("parallel_task_queue", 3, 3)
            comp("parallel_task_worker", 3, 4)
            comp("ogc_api", 3, 6)

            # Row 4: Platform API (C1), Orchestrator (C2), Compute Task (C3), RAM Worker (C4), STAC API (C6)
            comp("platform_api", 4, 1)
            comp("orchestrator", 4, 2)
            comp("compute_task_queue", 4, 3)
            comp("compute_task_worker", 4, 4)
            comp("aux_api", 4, 6)

            # Row 5: Job Queue (C2), Long Task (C3), Long Worker (C4), TiTiler (C6)
            comp("job_queue", 5, 2)
            comp("long_task_queue", 5, 3)
            comp("long_task_worker", 5, 4)
            comp("titiler_app", 5, 6)


# =============================================================================
# PUBLIC API - Backwards Compatible
# =============================================================================

def create_native_diagram(components: Optional[Dict[str, Any]] = None):
    """Create the architecture diagram with optional status data."""
    status_data = {}
    if components:
        for comp_id, comp_info in components.items():
            if isinstance(comp_info, dict) and "status" in comp_info:
                status_data[comp_id] = {"status": comp_info["status"]}
    return create_architecture_diagram(status_data)


def create_mermaid_diagram(components: Optional[Dict[str, Any]] = None):
    """Legacy function - redirects to native diagram."""
    return create_native_diagram(components)


def create_azure_architecture_diagram(status_data: Optional[Dict[str, Any]] = None):
    """Alias for the main diagram function."""
    return create_architecture_diagram(status_data)
