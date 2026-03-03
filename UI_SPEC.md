design principles:
Minimal complexity - this is not a formal UI application just a helpful exploratory tool for admins, B2B clients, AND B2C clients

URL root should redirect to home page 
home page should be titled or refer to Geospatial Data Catalog and present users with interface to explore STAC and OGC Feature collections jointly as a single catalog. Separate pages for STAC and OGC Features specifically will also exist for more detailed  STAC-specific or OGC Feature-specific interface. 

Viewers
Map viewer templates should be build for each of the data type categories vector, raster and multidimensional

Vector viewer - consumes TiPG endpoints
pls use maplibre cus it looks beautiful. for a given OGC Feature collection the vector viewer should show teh OGC Features on a map. sidebar or diaglog of some type should show options to load features in chunks or all at once. Should also allow application of styles but this is a lower priority to revisit after basic viewer is made

Raster viewer - consumes Titiler vanilla or TiTiler-pgstac endpoints
no library constraints though Leaflet is the simplest. sidebar or dialog needs to allow selecting different bands and different color ramps (see api/interface/raster-viewer from /Users/robertharrison/python_builds/rmhgeoapi/web_interfaces)

Zarr viewer - consumes TiTiler-xarray
Same idea as raster but with variable selection instead of bands

H3 viewer - H3 viewer currently exists for a specific dataset and demo purpose but I want those libraries (beautiful) to be retained so we can have a special viewer for H3 data (this is for future features)


Pages needed:

Homepage/splash
Unified catalog
STAC catalog (raster and multidimensional data)
OGC Feature Catalog (vector data)
Map Viewer (one template that handles all data types or different viewer for each type?)
Documentation page- API docs with Swagger and ReDOC pages to consolidate TiPG, TiTiler, STAC API, and custom endpoints into one place

system page - currently what shows in the url root splash page- basic system diagnostics for admins this will be tucked away somewhere and removed before production but needs to be in place for QA and UAT environments. 