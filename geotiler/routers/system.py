"""
System page router for geotiler.

Serves the system health monitoring dashboard with auto-refreshing
HTMX fragments for live service status.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from geotiler.templates_utils import render_template, templates, get_template_context
from geotiler.routers.health import health as get_health_data

router = APIRouter(tags=["System"], include_in_schema=False)


@router.get("/system", include_in_schema=False)
async def system_page(request: Request):
    """Render the system health monitoring page."""
    return render_template(request, "pages/system/index.html", nav_active="/system")


@router.get("/system/_health-fragment", response_class=HTMLResponse, include_in_schema=False)
async def system_health_fragment(request: Request):
    """HTMX fragment: renders live health data into the system page."""
    response = Response()
    health_data = await get_health_data(request, response)
    context = get_template_context(request, health=health_data)
    return templates.TemplateResponse("pages/system/_health_fragment.html", context)
