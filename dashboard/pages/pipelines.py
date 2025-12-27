"""
Pipeline Workflows Dashboard Page.

Shows available ETL pipelines and recent job status.
"""

from nicegui import ui
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from dashboard.client import PlatformClient


# Pipeline definitions
PIPELINES = [
    {
        "id": "process_vector",
        "name": "Process Vector",
        "icon": "map",
        "description": "Ingest vector files (GeoJSON, Shapefile, GeoPackage) into PostGIS with automatic CRS detection.",
        "stages": ["Validate", "Transform", "Load PostGIS", "STAC Catalog"],
        "color": "blue",
    },
    {
        "id": "process_raster_v2",
        "name": "Process Raster",
        "icon": "satellite_alt",
        "description": "Convert raster files to Cloud-Optimized GeoTIFF (COG) format with automatic tiling and compression.",
        "stages": ["Validate", "COG Convert", "Upload Silver", "STAC Catalog"],
        "color": "green",
    },
    {
        "id": "process_raster_collection_v2",
        "name": "Raster Collection",
        "icon": "collections",
        "description": "Process multiple raster tiles as a collection with MosaicJSON for TiTiler visualization.",
        "stages": ["Validate All", "Parallel COG", "MosaicJSON", "STAC"],
        "color": "purple",
    },
]

# Status colors
STATUS_COLORS = {
    "queued": {"bg": "bg-gray-100", "text": "text-gray-600"},
    "pending": {"bg": "bg-yellow-100", "text": "text-yellow-700"},
    "processing": {"bg": "bg-blue-100", "text": "text-blue-700"},
    "completed": {"bg": "bg-green-100", "text": "text-green-700"},
    "failed": {"bg": "bg-red-100", "text": "text-red-700"},
}


class PipelinePage:
    """Pipeline page state and logic."""

    def __init__(self, client: Optional[PlatformClient]):
        self.client = client
        self.jobs: List[Dict[str, Any]] = []
        self.loading = True
        self.error: Optional[str] = None
        self.status_filter = ""
        self.hours_filter = 168
        self.limit = 25
        self.stats = {"total": 0, "queued": 0, "processing": 0, "completed": 0, "failed": 0}
        self.pipeline_stats: Dict[str, Dict] = {}

    async def load_jobs(self):
        """Load jobs from API."""
        if not self.client:
            self.error = "Platform API not configured"
            self.loading = False
            return

        self.loading = True
        self.error = None

        try:
            data = await self.client.get_jobs(
                limit=self.limit,
                status=self.status_filter if self.status_filter else None,
            )
            self.jobs = data.get("jobs", [])
            self._calculate_stats()
            self._calculate_pipeline_stats()
        except Exception as e:
            self.error = str(e)
            self.jobs = []
        finally:
            self.loading = False

    def _calculate_stats(self):
        """Calculate job status counts."""
        self.stats = {"total": 0, "queued": 0, "processing": 0, "completed": 0, "failed": 0}
        for job in self.jobs:
            self.stats["total"] += 1
            status = job.get("status", "unknown").lower()
            if status in self.stats:
                self.stats[status] += 1

    def _calculate_pipeline_stats(self):
        """Calculate per-pipeline statistics."""
        now = datetime.now()
        last_24h = now - timedelta(hours=24)

        for pipeline in PIPELINES:
            pid = pipeline["id"]
            pipeline_jobs = [j for j in self.jobs if j.get("job_type") == pid]
            recent = [j for j in pipeline_jobs if self._parse_date(j.get("created_at")) > last_24h]
            completed = [j for j in pipeline_jobs if j.get("status") == "completed"]

            success_rate = (len(completed) / len(pipeline_jobs) * 100) if pipeline_jobs else 0

            self.pipeline_stats[pid] = {
                "last_24h": len(recent),
                "success_rate": f"{success_rate:.0f}%" if pipeline_jobs else "--",
            }

    def _parse_date(self, date_str) -> datetime:
        """Parse date string to datetime."""
        if not date_str:
            return datetime.min
        try:
            if hasattr(date_str, "strftime"):
                return date_str
            return datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        except Exception:
            return datetime.min


def create_page(client: Optional[PlatformClient]):
    """Create the Pipeline Workflows page."""
    page = PipelinePage(client)

    pipeline_cards = None
    stats_container = None
    jobs_container = None
    status_select = None
    hours_select = None
    limit_select = None

    with ui.column().classes("gap-6 p-6 w-full max-w-7xl mx-auto"):
        # Header
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("Pipeline Workflows").classes("text-2xl font-bold")
                ui.label("Monitor and manage ETL data processing pipelines").classes("text-gray-500")

            refresh_btn = ui.button("Refresh", icon="refresh", on_click=lambda: refresh())
            refresh_btn.props("outline")

        # Available Pipelines section
        with ui.card().classes("w-full"):
            ui.label("Available Pipelines").classes("text-lg font-bold mb-4 pb-2 border-b-2 border-blue-500")
            pipeline_cards = ui.element("div").classes("grid grid-cols-1 md:grid-cols-3 gap-4")

        # Recent Jobs section
        with ui.card().classes("w-full"):
            ui.label("Recent Jobs").classes("text-lg font-bold mb-4 pb-2 border-b-2 border-blue-500")

            # Filter bar
            with ui.row().classes("items-end gap-4 flex-wrap mb-4 p-4 bg-gray-50 rounded-lg"):
                with ui.column().classes("gap-1"):
                    ui.label("Status").classes("text-sm font-medium text-gray-600")
                    status_select = ui.select(
                        options={"": "All", "queued": "Queued", "processing": "Processing",
                                 "completed": "Completed", "failed": "Failed"},
                        value="",
                        on_change=lambda e: on_filter_change("status", e.value),
                    ).classes("w-32")

                with ui.column().classes("gap-1"):
                    ui.label("Time Range").classes("text-sm font-medium text-gray-600")
                    hours_select = ui.select(
                        options={24: "Last 24 hours", 72: "Last 3 days", 168: "Last 7 days",
                                 336: "Last 14 days", 720: "Last 30 days"},
                        value=168,
                        on_change=lambda e: on_filter_change("hours", e.value),
                    ).classes("w-36")

                with ui.column().classes("gap-1"):
                    ui.label("Limit").classes("text-sm font-medium text-gray-600")
                    limit_select = ui.select(
                        options={10: "10", 25: "25", 50: "50", 100: "100"},
                        value=25,
                        on_change=lambda e: on_filter_change("limit", e.value),
                    ).classes("w-20")

                ui.button("Clear Filters", icon="clear", on_click=lambda: clear_filters()).props("flat")

            # Stats banner
            stats_container = ui.element("div").classes("w-full mb-4")

            # Jobs container
            jobs_container = ui.column().classes("w-full gap-2")

    async def refresh():
        """Refresh all data."""
        refresh_btn.disable()
        await page.load_jobs()
        render_pipeline_cards()
        render_stats()
        render_jobs()
        refresh_btn.enable()

    async def on_filter_change(filter_type: str, value):
        """Handle filter changes."""
        if filter_type == "status":
            page.status_filter = value
        elif filter_type == "hours":
            page.hours_filter = value
        elif filter_type == "limit":
            page.limit = value
        await refresh()

    async def clear_filters():
        """Clear all filters."""
        page.status_filter = ""
        page.hours_filter = 168
        page.limit = 25
        status_select.value = ""
        hours_select.value = 168
        limit_select.value = 25
        await refresh()

    def render_pipeline_cards():
        """Render pipeline cards."""
        pipeline_cards.clear()
        with pipeline_cards:
            for pipeline in PIPELINES:
                pid = pipeline["id"]
                stats = page.pipeline_stats.get(pid, {"last_24h": "--", "success_rate": "--"})
                color = pipeline["color"]

                with ui.card().classes(f"border-2 border-{color}-200 hover:border-{color}-400 transition-all"):
                    # Header
                    with ui.row().classes("items-center gap-2 mb-2"):
                        ui.icon(pipeline["icon"], size="md").classes(f"text-{color}-600")
                        ui.label(pipeline["name"]).classes("text-lg font-bold")

                    # Description
                    ui.label(pipeline["description"]).classes("text-sm text-gray-600 mb-4")

                    # Stages
                    with ui.row().classes("items-center gap-1 flex-wrap mb-4"):
                        for i, stage in enumerate(pipeline["stages"]):
                            if i > 0:
                                ui.label("→").classes("text-blue-500 text-sm")
                            ui.badge(stage).classes("bg-white border text-gray-700 text-xs")

                    # Stats
                    with ui.row().classes("gap-8 pt-4 border-t"):
                        with ui.column().classes("text-center"):
                            ui.label(str(stats["last_24h"])).classes("text-xl font-bold text-blue-600")
                            ui.label("Last 24h").classes("text-xs text-gray-500 uppercase")
                        with ui.column().classes("text-center"):
                            ui.label(stats["success_rate"]).classes("text-xl font-bold text-green-600")
                            ui.label("Success Rate").classes("text-xs text-gray-500 uppercase")

    def render_stats():
        """Render stats banner."""
        stats_container.clear()
        with stats_container:
            with ui.element("div").classes("grid grid-cols-5 gap-4"):
                for label, key, color in [
                    ("Total Jobs", "total", "gray-800"),
                    ("Queued", "queued", "gray-600"),
                    ("Processing", "processing", "blue-600"),
                    ("Completed", "completed", "green-600"),
                    ("Failed", "failed", "red-600"),
                ]:
                    with ui.element("div").classes("text-center p-3 bg-gray-50 rounded-lg"):
                        ui.label(label).classes("text-xs text-gray-500 uppercase")
                        ui.label(str(page.stats[key])).classes(f"text-2xl font-bold text-{color}")

    def render_jobs():
        """Render jobs list."""
        jobs_container.clear()

        with jobs_container:
            if page.loading:
                with ui.row().classes("items-center gap-2 justify-center p-8"):
                    ui.spinner()
                    ui.label("Loading jobs...")
                return

            if page.error:
                with ui.card().classes("w-full bg-yellow-50 border-l-4 border-yellow-500"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("warning", color="orange")
                        with ui.column().classes("gap-1"):
                            ui.label("Platform API Unavailable").classes("font-bold text-yellow-800")
                            ui.label(f"{page.error}").classes("text-sm text-yellow-700")
                            ui.label("Enable ENABLE_PLATFORM_API to view pipeline jobs.").classes("text-xs text-yellow-600")
                return

            if not page.jobs:
                with ui.element("div").classes("text-center py-8"):
                    ui.icon("inbox", size="xl").classes("text-gray-300")
                    ui.label("No jobs found").classes("text-xl font-bold text-gray-600 mt-4")
                    ui.label("Try adjusting filters or submit a new job").classes("text-gray-500")
                return

            # Jobs as cards
            for job in page.jobs:
                render_job_row(job)

    def render_job_row(job: Dict[str, Any]):
        """Render a single job row."""
        job_id = job.get("job_id", job.get("id", ""))
        job_id_short = job_id[:8] if job_id else "--"
        status = job.get("status", "unknown").lower()
        style = STATUS_COLORS.get(status, {"bg": "bg-gray-100", "text": "text-gray-600"})

        created_at = job.get("created_at", "")
        if created_at:
            try:
                if hasattr(created_at, "strftime"):
                    created_str = created_at.strftime("%Y-%m-%d %H:%M")
                else:
                    dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                    created_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                created_str = str(created_at)[:16]
        else:
            created_str = "--"

        tc = job.get("task_counts", {})

        with ui.card().classes("w-full"):
            with ui.row().classes("items-center justify-between flex-wrap gap-4"):
                # Job ID and Type
                with ui.column().classes("gap-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(job_id_short).classes("font-mono font-bold text-blue-600").tooltip(job_id)
                        ui.badge(status.upper()).classes(f"{style['bg']} {style['text']} text-xs")
                    ui.label(job.get("job_type", "--")).classes("text-sm text-gray-600")

                # Stage
                with ui.column().classes("text-center"):
                    ui.label("Stage").classes("text-xs text-gray-400")
                    ui.label(f"{job.get('stage', 0)}/{job.get('total_stages', '?')}").classes("font-mono")

                # Tasks
                with ui.column().classes("text-center"):
                    ui.label("Tasks").classes("text-xs text-gray-400")
                    with ui.row().classes("gap-1"):
                        if tc.get("queued", 0) > 0:
                            ui.badge(f"Q:{tc['queued']}").classes("bg-gray-100 text-gray-600 text-xs")
                        if tc.get("processing", 0) > 0:
                            ui.badge(f"P:{tc['processing']}").classes("bg-blue-100 text-blue-700 text-xs")
                        if tc.get("completed", 0) > 0:
                            ui.badge(f"C:{tc['completed']}").classes("bg-green-100 text-green-700 text-xs")
                        if tc.get("failed", 0) > 0:
                            ui.badge(f"F:{tc['failed']}").classes("bg-red-100 text-red-700 text-xs")

                # Created
                with ui.column().classes("text-center"):
                    ui.label("Created").classes("text-xs text-gray-400")
                    ui.label(created_str).classes("text-sm")

                # Actions
                ui.button("View Tasks", icon="list", on_click=lambda jid=job_id: view_tasks(jid)).props("flat dense")

    def view_tasks(job_id: str):
        """Navigate to tasks page for a job."""
        ui.navigate.to(f"/dashboard/tasks?job_id={job_id}")

    # Initial load
    ui.timer(0.1, refresh, once=True)
