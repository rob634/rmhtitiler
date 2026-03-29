"""
geotiler - TiTiler with Azure Managed Identity Authentication
===============================================================

A containerized geospatial tile server integrating:
- TiTiler-core (COG tiles via rio-tiler)
- TiTiler-pgstac (STAC catalog searches - dynamic mosaics)
- TiTiler-xarray (Zarr/NetCDF multidimensional data)
- TiPG (OGC Features API + Vector Tiles for PostGIS)

With Azure authentication:
- Managed Identity for Azure Blob Storage (GDAL env vars)
- Managed Identity for Azure PostgreSQL
- Key Vault integration for secrets

Base Image: titiler-pgstac 2.1.0 (titiler-core 1.2.x, titiler.xarray 1.2.x)

Supported Endpoints:
- /cog/* - COG tiles
- /xarray/* - Zarr/NetCDF multidimensional data
- /searches/* - pgSTAC dynamic mosaics
- /stac/* - STAC catalog browsing and search
- /vector/* - OGC Features + Vector Tiles via TiPG
"""

__version__ = "0.10.5.3"

__all__ = ["__version__"]
