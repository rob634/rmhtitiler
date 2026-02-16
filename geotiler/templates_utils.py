"""
Template utilities for geotiler.

Provides a centralized Jinja2Templates instance and helper functions
for rendering templates across all routers.
"""

from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from starlette.templating import Jinja2Templates

from geotiler import __version__
from geotiler.config import settings

# Initialize templates directory
_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)


def get_template_context(request: Request, **kwargs: Any) -> Dict[str, Any]:
    """
    Build a standard template context with common variables.

    Args:
        request: The FastAPI request object
        **kwargs: Additional context variables

    Returns:
        Dictionary with standard context variables plus any extras
    """
    context = {
        "request": request,
        "version": __version__,
        "stac_api_enabled": settings.enable_stac_api and settings.enable_tipg,
        "tipg_enabled": settings.enable_tipg,
        # Sample URLs from configuration
        "sample_zarr_urls": settings.sample_zarr_urls,
    }
    context.update(kwargs)
    return context


def render_template(
    request: Request,
    template_name: str,
    **kwargs: Any
):
    """
    Render a template with standard context.

    Args:
        request: The FastAPI request object
        template_name: Name of the template file
        **kwargs: Additional context variables

    Returns:
        TemplateResponse
    """
    context = get_template_context(request, **kwargs)
    return templates.TemplateResponse(template_name, context)
