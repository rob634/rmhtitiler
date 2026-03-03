"""
Viewer router for geotiler.

Serves map-based viewer pages for raster (COG), Zarr/NetCDF,
vector (OGC Features), and H3 hexagonal data.
"""

from fastapi import APIRouter, Request

from geotiler.templates_utils import render_template

router = APIRouter(prefix="/viewer", tags=["Viewers"], include_in_schema=False)


@router.get("/raster", include_in_schema=False)
async def raster_viewer(request: Request):
    """Render the COG raster tile viewer."""
    return render_template(request, "pages/viewer/raster.html", nav_active="/catalog")


@router.get("/zarr", include_in_schema=False)
async def zarr_viewer(request: Request):
    """Render the Zarr/NetCDF multidimensional viewer."""
    return render_template(request, "pages/viewer/zarr.html", nav_active="/catalog")


@router.get("/vector", include_in_schema=False)
async def vector_viewer(request: Request):
    """Render the OGC Features vector viewer."""
    return render_template(request, "pages/viewer/vector.html", nav_active="/catalog")


@router.get("/h3", include_in_schema=False)
async def h3_viewer(request: Request):
    """Render the H3 hexagonal choropleth viewer."""
    return render_template(request, "pages/viewer/h3.html", nav_active="/catalog")
