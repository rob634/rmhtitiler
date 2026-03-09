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

Dependency Versions (as of v0.10.0)
------------------------------------
Base image: titiler-pgstac:2.1.0 (titiler-core 1.2.x, rio-tiler 8.x).
titiler.xarray pinned to >=1.2.0,<2.0 to match.

Supported Endpoints:
- /cog/* - COG tiles (works with rio-tiler 8.x)
- /xarray/* - Zarr/NetCDF (uses titiler.xarray's own rio-tiler 8.x)
- /searches/* - pgSTAC dynamic mosaics (forwards-compatible)
- /vector/* - OGC Features + Vector Tiles via TiPG (v0.7.0+)
"""

__version__ = "0.9.3.2"

__all__ = ["__version__"]
