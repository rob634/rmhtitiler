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

Dependency Versions (as of v0.8.19)
-----------------------------------
This package installs titiler.xarray>=0.24.0,<0.25.0 which is pinned
to match the base image (titiler-pgstac:1.9.0, built against titiler-core 0.24.x).
Upgrading to titiler.xarray 1.x requires migrating to titiler-pgstac 2.0.0.

Supported Endpoints:
- /cog/* - COG tiles (works with rio-tiler 8.x)
- /xarray/* - Zarr/NetCDF (uses titiler.xarray's own rio-tiler 8.x)
- /searches/* - pgSTAC dynamic mosaics (forwards-compatible)
- /vector/* - OGC Features + Vector Tiles via TiPG (v0.7.0+)
"""

__version__ = "0.8.20.0"

__all__ = ["__version__"]
