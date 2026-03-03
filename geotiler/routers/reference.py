"""
Reference page router for geotiler.

Serves the API documentation hub with links to Swagger UI, user guide,
and endpoint overview.
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(tags=["Reference"], include_in_schema=False)


@router.get("/reference", include_in_schema=False)
async def reference_page(request: Request):
    """Render the API reference documentation page."""
    return render_template(request, "pages/reference/index.html", nav_active="/reference")
