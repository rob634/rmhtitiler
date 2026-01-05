"""
rmhtitiler - TiTiler with Azure Managed Identity Authentication
===============================================================

A containerized geospatial tile server integrating:
- TiTiler-core (COG tiles)
- TiTiler-pgstac (STAC catalog searches)
- TiTiler-xarray (Zarr/NetCDF multidimensional data)

With Azure authentication:
- Managed Identity for Azure Blob Storage (GDAL env vars)
- Managed Identity for Azure PostgreSQL
- Key Vault integration for secrets
- Planetary Computer credential provider
"""

__version__ = "0.5.0"
__author__ = "Rob Harrison"

__all__ = ["__version__"]
