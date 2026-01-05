"""
Planetary Computer endpoints for climate data access.

Provides endpoints to access Zarr datasets hosted on Planetary Computer
storage accounts, with automatic SAS token handling via credential provider.
"""

import re
import io
import math
import logging
from pathlib import Path
from threading import Lock
from typing import Optional, Any, Dict, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request, Response

from rmhtitiler.config import settings, PC_STORAGE_ACCOUNTS, TILE_SIZE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pc", tags=["Planetary Computer"])

# Check if Planetary Computer libraries are available
try:
    from obstore.store import AzureStore
    from obstore.auth.planetary_computer import PlanetaryComputerCredentialProvider
    PC_AVAILABLE = True
except ImportError:
    PC_AVAILABLE = False
    AzureStore = None
    PlanetaryComputerCredentialProvider = None

# Credential provider cache
_credential_cache: Dict[str, Any] = {}
_credential_lock = Lock()


# =============================================================================
# Helper Functions (DRY)
# =============================================================================


def is_planetary_computer_url(url: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if a URL points to a Planetary Computer storage account.

    Args:
        url: The URL to check (can be https:// or abfs:// format)

    Returns:
        Tuple of (is_pc_url, storage_account, collection_id)
    """
    if not url:
        return False, None, None

    # Parse HTTPS URLs: https://{account}.blob.core.windows.net/...
    https_match = re.match(r"https://([^.]+)\.blob\.core\.windows\.net/", url)
    if https_match:
        account = https_match.group(1)
        if account in PC_STORAGE_ACCOUNTS:
            return True, account, PC_STORAGE_ACCOUNTS[account]

    # Parse ABFS URLs: abfs://{container}@{account}.dfs.core.windows.net/...
    abfs_match = re.match(r"abfs://[^@]+@([^.]+)\.dfs\.core\.windows\.net/", url)
    if abfs_match:
        account = abfs_match.group(1)
        if account in PC_STORAGE_ACCOUNTS:
            return True, account, PC_STORAGE_ACCOUNTS[account]

    return False, None, None


def get_credential_provider(url: str) -> Optional[Any]:
    """
    Get a cached PlanetaryComputerCredentialProvider for the given URL.

    Args:
        url: The full URL to the Planetary Computer Zarr data

    Returns:
        A PlanetaryComputerCredentialProvider instance, or None if not available
    """
    if not PC_AVAILABLE or not settings.enable_planetary_computer:
        logger.debug("Planetary Computer support not available or disabled")
        return None

    # Cache key is the base URL (storage account + container)
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/", 1)
    container = path_parts[0] if path_parts else ""
    cache_key = f"{parsed.netloc}/{container}"

    with _credential_lock:
        if cache_key not in _credential_cache:
            try:
                logger.info(f"Creating PlanetaryComputerCredentialProvider for: {cache_key}")
                provider = PlanetaryComputerCredentialProvider(url=url)
                _credential_cache[cache_key] = provider
                logger.info(f"Credential provider created for {cache_key}")
            except Exception as e:
                logger.error(f"Failed to create PC credential provider for {cache_key}: {e}")
                _credential_cache[cache_key] = None

        return _credential_cache.get(cache_key)


def open_pc_zarr_dataset(url: str):
    """
    Open a Planetary Computer Zarr dataset with credentials.

    Args:
        url: URL to the Zarr dataset

    Returns:
        xarray.Dataset

    Raises:
        RuntimeError: If credential provider cannot be created
        Exception: If dataset cannot be opened
    """
    import xarray as xr
    from zarr.storage import ObjectStore

    credential_provider = get_credential_provider(url)
    if not credential_provider:
        raise RuntimeError(f"Failed to get credential provider for URL: {url}")

    store = AzureStore(credential_provider=credential_provider)
    zarr_store = ObjectStore(store, read_only=True)

    return xr.open_zarr(zarr_store, consolidated=True, decode_times=False)


def create_transparent_tile() -> bytes:
    """Create a 256x256 transparent PNG tile."""
    from PIL import Image

    img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def tile_to_bbox(z: int, x: int, y: int) -> Tuple[float, float, float, float]:
    """Convert tile coordinates to WGS84 bounding box."""
    n = 2.0**z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/collections")
async def pc_collections():
    """List known Planetary Computer collections and their storage accounts."""
    return {
        "planetary_computer_enabled": settings.enable_planetary_computer,
        "credential_provider_available": PC_AVAILABLE,
        "storage_accounts": PC_STORAGE_ACCOUNTS,
        "documentation": "https://planetarycomputer.microsoft.com/catalog",
        "example_collections": {
            "cil-gdpcir-cc0": {
                "description": "Climate Impact Lab CMIP6 downscaled projections (Public Domain)",
                "variables": ["tasmax", "tasmin", "pr"],
                "example_url": "https://rhgeuwest.blob.core.windows.net/cil-gdpcir/ScenarioMIP/NUIST/NESM3/ssp585/r1i1p1f1/day/tasmax/v1.1.zarr",
            },
            "gridmet": {
                "description": "gridMET daily meteorological data",
                "example_url": "https://ai4edataeuwest.blob.core.windows.net/gridmet/gridmet.zarr",
            },
        },
    }


@router.get("/variables")
async def pc_variables(
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    collection: Optional[str] = Query(None, description="Collection ID for SAS token"),
):
    """List variables in a Planetary Computer Zarr dataset."""
    if not PC_AVAILABLE:
        return {"error": "Planetary Computer support not installed"}

    is_pc, storage_account, default_collection = is_planetary_computer_url(url)
    if not is_pc:
        return {
            "error": f"URL is not a Planetary Computer URL. Known accounts: {list(PC_STORAGE_ACCOUNTS.keys())}"
        }

    try:
        ds = open_pc_zarr_dataset(url)

        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/", 1)
        container = path_parts[0]
        zarr_path = path_parts[1] if len(path_parts) > 1 else ""

        return {
            "variables": list(ds.data_vars.keys()),
            "url": url,
            "collection": default_collection,
            "storage_account": storage_account,
            "container": container,
            "path": zarr_path,
        }

    except Exception as e:
        logger.error(f"Error accessing Planetary Computer data: {e}", exc_info=True)
        return {"error": str(e), "url": url, "collection": default_collection}


@router.get("/info")
async def pc_info(
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    variable: str = Query(..., description="Variable name to get info for"),
    collection: Optional[str] = Query(None, description="Collection ID for SAS token"),
):
    """Get metadata for a variable in a Planetary Computer Zarr dataset."""
    if not PC_AVAILABLE:
        return {"error": "Planetary Computer support not installed"}

    is_pc, _, _ = is_planetary_computer_url(url)
    if not is_pc:
        return {"error": "URL is not a Planetary Computer URL"}

    try:
        ds = open_pc_zarr_dataset(url)

        if variable not in ds.data_vars:
            return {
                "error": f"Variable '{variable}' not found. Available: {list(ds.data_vars.keys())}"
            }

        var = ds[variable]

        return {
            "variable": variable,
            "dims": list(var.dims),
            "shape": list(var.shape),
            "dtype": str(var.dtype),
            "attrs": dict(var.attrs),
            "coords": {
                coord: {
                    "min": (
                        float(ds[coord].min().values)
                        if ds[coord].dtype.kind in "iuf"
                        else str(ds[coord].values[0])
                    ),
                    "max": (
                        float(ds[coord].max().values)
                        if ds[coord].dtype.kind in "iuf"
                        else str(ds[coord].values[-1])
                    ),
                    "size": len(ds[coord]),
                }
                for coord in var.dims
                if coord in ds.coords
            },
        }

    except Exception as e:
        logger.error(f"Error getting PC variable info: {e}", exc_info=True)
        return {"error": str(e)}


@router.get("/tiles/{tileMatrixSetId}/{z}/{x}/{y}.png")
async def pc_tile(
    tileMatrixSetId: str,
    z: int,
    x: int,
    y: int,
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    variable: str = Query(..., description="Variable name"),
    time_idx: int = Query(0, description="Time index (0-based)"),
    colormap: str = Query("viridis", description="Matplotlib colormap name"),
    vmin: Optional[float] = Query(None, description="Min value for colormap"),
    vmax: Optional[float] = Query(None, description="Max value for colormap"),
):
    """
    Serve map tiles from Planetary Computer Zarr data.

    Renders a 256x256 PNG tile for the specified z/x/y coordinates.
    """
    import numpy as np
    from PIL import Image
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    if not PC_AVAILABLE:
        return Response(content="PC support not installed", status_code=500)

    try:
        # Get tile bounds
        lon_min, lat_min, lon_max, lat_max = tile_to_bbox(z, x, y)

        # Open dataset
        ds = open_pc_zarr_dataset(url)

        if variable not in ds.data_vars:
            return Response(content=f"Variable not found: {variable}", status_code=404)

        var = ds[variable]

        # Select time if present
        if "time" in var.dims:
            var = var.isel(time=time_idx)

        # Determine lat/lon dimension names
        lat_dim = (
            "lat" if "lat" in var.dims else "latitude" if "latitude" in var.dims else "y"
        )
        lon_dim = (
            "lon" if "lon" in var.dims else "longitude" if "longitude" in var.dims else "x"
        )

        # Slice to tile bounds
        try:
            lat_coords = ds[lat_dim].values
            if lat_coords[0] > lat_coords[-1]:
                # Lat is descending
                data = var.sel(
                    **{lat_dim: slice(lat_max, lat_min), lon_dim: slice(lon_min, lon_max)}
                )
            else:
                data = var.sel(
                    **{lat_dim: slice(lat_min, lat_max), lon_dim: slice(lon_min, lon_max)}
                )
        except Exception as slice_err:
            logger.warning(f"Slice failed: {slice_err}, returning empty tile")
            return Response(content=create_transparent_tile(), media_type="image/png")

        values = data.values

        if values.size == 0:
            return Response(content=create_transparent_tile(), media_type="image/png")

        # Calculate colormap bounds
        actual_vmin = vmin if vmin is not None else float(np.nanmin(values))
        actual_vmax = vmax if vmax is not None else float(np.nanmax(values))

        # Normalize and apply colormap
        norm = mcolors.Normalize(vmin=actual_vmin, vmax=actual_vmax)
        cmap = plt.get_cmap(colormap)
        colored = cmap(norm(values))

        # Handle NaN as transparent
        mask = np.isnan(values)
        colored[mask, 3] = 0

        # Convert to uint8 image
        colored_uint8 = (colored * 255).astype(np.uint8)
        img = Image.fromarray(colored_uint8, mode="RGBA")
        img = img.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.BILINEAR)

        # Save to buffer
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        return Response(content=buf.read(), media_type="image/png")

    except Exception as e:
        logger.error(f"Error generating PC tile: {e}", exc_info=True)
        return Response(content=str(e), status_code=500)


@router.get("/{tileMatrixSetId}/tilejson.json")
async def pc_tilejson(
    request: Request,
    tileMatrixSetId: str,
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    variable: str = Query(..., description="Variable name"),
    time_idx: int = Query(0, description="Time index"),
    colormap: str = Query("viridis", description="Colormap name"),
    vmin: Optional[float] = Query(None, description="Min value"),
    vmax: Optional[float] = Query(None, description="Max value"),
):
    """
    Return TileJSON for Planetary Computer Zarr data.

    TileJSON is used by map viewers (Leaflet, MapLibre) to configure tile layers.
    """
    base_url = str(request.base_url).rstrip("/")

    # Build tile URL with query params
    tile_url = f"{base_url}/pc/tiles/{tileMatrixSetId}/{{z}}/{{x}}/{{y}}.png"
    tile_url += f"?url={url}&variable={variable}&time_idx={time_idx}&colormap={colormap}"
    if vmin is not None:
        tile_url += f"&vmin={vmin}"
    if vmax is not None:
        tile_url += f"&vmax={vmax}"

    return {
        "tilejson": "2.2.0",
        "name": f"{variable} from Planetary Computer",
        "description": f"Climate data variable: {variable}",
        "version": "1.0.0",
        "attribution": "Microsoft Planetary Computer / Climate Impact Lab",
        "scheme": "xyz",
        "tiles": [tile_url],
        "minzoom": 0,
        "maxzoom": 8,
        "bounds": [-180, -90, 180, 90],
        "center": [0, 0, 2],
    }


@router.get("/{tileMatrixSetId}/map.html", response_class=Response)
async def pc_map(
    request: Request,
    tileMatrixSetId: str,
    url: str = Query(..., description="Planetary Computer Zarr URL"),
    variable: str = Query(..., description="Variable name"),
    time_idx: int = Query(0, description="Time index"),
    colormap: str = Query("viridis", description="Colormap name"),
    vmin: Optional[float] = Query(None, description="Min value"),
    vmax: Optional[float] = Query(None, description="Max value"),
):
    """
    Interactive map viewer for Planetary Computer Zarr data.

    Displays the data on a Leaflet map with the specified colormap.
    """
    base_url = str(request.base_url).rstrip("/")

    # Build tilejson URL
    tilejson_url = f"{base_url}/pc/{tileMatrixSetId}/tilejson.json"
    tilejson_url += f"?url={url}&variable={variable}&time_idx={time_idx}&colormap={colormap}"
    if vmin is not None:
        tilejson_url += f"&vmin={vmin}"
    if vmax is not None:
        tilejson_url += f"&vmax={vmax}"

    # Try to load template from file, fall back to inline
    template_path = Path(__file__).parent.parent / "templates" / "pc_map.html"
    if template_path.exists():
        html_template = template_path.read_text()
        html = html_template.replace("{{ variable }}", variable)
        html = html.replace("{{ time_idx }}", str(time_idx))
        html = html.replace("{{ colormap }}", colormap)
        html = html.replace("{{ tilejson_url }}", tilejson_url)
    else:
        # Inline fallback
        html = _get_map_html(variable, time_idx, colormap, tilejson_url)

    return Response(content=html, media_type="text/html")


def _get_map_html(variable: str, time_idx: int, colormap: str, tilejson_url: str) -> str:
    """Generate map HTML (inline fallback if template not found)."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>{variable} - Planetary Computer Viewer</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ position: absolute; top: 0; bottom: 0; width: 100%; }}
        .info-box {{
            position: absolute; top: 10px; right: 10px;
            background: white; padding: 10px 15px; border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.3); z-index: 1000;
            font-family: Arial, sans-serif; font-size: 12px; max-width: 300px;
        }}
        .info-box h3 {{ margin: 0 0 5px 0; font-size: 14px; }}
        .info-box p {{ margin: 2px 0; color: #666; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="info-box">
        <h3>Planetary Computer Data</h3>
        <p><strong>Variable:</strong> {variable}</p>
        <p><strong>Time Index:</strong> {time_idx}</p>
        <p><strong>Colormap:</strong> {colormap}</p>
        <p><strong>Source:</strong> CMIP6 Climate Projections</p>
    </div>
    <script>
        var map = L.map('map').setView([20, 0], 2);
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
            subdomains: 'abcd', maxZoom: 19
        }}).addTo(map);
        fetch('{tilejson_url}')
            .then(response => response.json())
            .then(tilejson => {{
                L.tileLayer(tilejson.tiles[0], {{
                    attribution: tilejson.attribution,
                    maxZoom: tilejson.maxzoom, minZoom: tilejson.minzoom, opacity: 0.7
                }}).addTo(map);
            }})
            .catch(err => console.error('Failed to load TileJSON:', err));
    </script>
</body>
</html>"""
