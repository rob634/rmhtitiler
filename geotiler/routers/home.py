"""
Homepage router for geotiler.

Serves the main entry point with navigation cards to all major sections.
Route: /home (temporary — will move to / when admin dashboard moves to /system in Phase 3)
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(tags=["Home"], include_in_schema=False)


@router.get("/home", include_in_schema=False)
async def homepage(request: Request):
    """Render the geotiler homepage."""
    return render_template(request, "pages/home.html", nav_active="/")
