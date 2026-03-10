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

Version Scheme
--------------
v0.9.x  = pgstac 1.9.0 base (titiler-core 0.24.x, titiler.xarray 0.24.x)
v0.10.x = pgstac 2.1.0 base (titiler-core 1.2.x, titiler.xarray 1.2.x)

Supported Endpoints:
- /cog/* - COG tiles
- /xarray/* - Zarr/NetCDF multidimensional data
- /searches/* - pgSTAC dynamic mosaics
- /stac/* - STAC catalog browsing and search
- /vector/* - OGC Features + Vector Tiles via TiPG
"""

__version__ = "0.9.4.0"

__all__ = ["__version__"]
