"""
rmhtitiler - TiTiler with Azure Managed Identity Authentication
===============================================================

A containerized geospatial tile server integrating:
- TiTiler-core (COG tiles via rio-tiler)
- TiTiler-pgstac (STAC catalog searches - dynamic mosaics)
- TiTiler-xarray (Zarr/NetCDF multidimensional data)

With Azure authentication:
- Managed Identity for Azure Blob Storage (GDAL env vars)
- Managed Identity for Azure PostgreSQL
- Key Vault integration for secrets
- Planetary Computer credential provider

Dependency Versions (as of v0.5.0)
----------------------------------
This package installs titiler.xarray>=0.18.0 which pulls in:
- titiler-core 1.0.2 (latest, released Dec 17, 2025)
- rio-tiler 8.0.5 (latest)

The base image (titiler-pgstac:1.9.0) was built against titiler-core 0.24.x.
pip warns about version constraints but all supported endpoints work correctly.

Supported Endpoints:
- /cog/* - COG tiles (works with rio-tiler 8.x)
- /xarray/* - Zarr/NetCDF (uses titiler.xarray's own rio-tiler 8.x)
- /searches/* - pgSTAC dynamic mosaics (forwards-compatible)

Unsupported Endpoints:
- /mosaicjson/* - Requires static tokens embedded in JSON files.
  Incompatible with our OAuth/Managed Identity security model.
  Use /searches/* for dynamic mosaics instead.
"""

__version__ = "0.5.2"
__author__ = "Rob Harrison"

__all__ = ["__version__"]
