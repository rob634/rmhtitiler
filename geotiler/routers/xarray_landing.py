"""
XArray Landing Page.

Provides an interactive landing page for exploring Zarr and NetCDF datasets.
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(tags=["Landing Pages"])


@router.get("/xarray/", include_in_schema=False)
async def xarray_landing(request: Request):
    """
    XArray Explorer landing page.

    Provides an interface to explore Zarr and NetCDF datasets with:
    - URL input form with variable and time parameters
    - Quick action buttons (variables, info, viewer, tilejson)
    - Sample dataset URLs
    - Endpoint and parameter reference
    """
    return render_template(
        request,
        "pages/xarray/landing.html",
        nav_active="/xarray/"
    )
