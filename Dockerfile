# Production Dockerfile for TiTiler-pgSTAC with Azure OAuth authentication,
# Xarray/Zarr support, and Planetary Computer integration
FROM ghcr.io/stac-utils/titiler-pgstac:1.9.0
#Use the JFROG Artifactory image for production deployments
#FROM artifactory.worldbank.org/itsdt-docker-virtual/titiler-pgstac:1.9.0

# Install dependencies:
# - azure-identity: OAuth tokens via Managed Identity for storage and PostgreSQL
# - azure-keyvault-secrets: Key Vault access for password retrieval
# - titiler.xarray: Zarr/NetCDF support for multidimensional data
# - adlfs: Azure Data Lake filesystem for fsspec
# - obstore: High-performance storage with Planetary Computer credential provider
# - requests: Required by PlanetaryComputerCredentialProvider
# - pydantic-settings: Type-safe configuration management
# - azure-monitor-opentelemetry: Application Insights integration
# - tipg: OGC Features API + Vector Tiles for PostGIS
# - stac-fastapi.pgstac: STAC API for catalog browsing and search
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0 \
    azure-keyvault-secrets>=4.7.0 \
    "titiler.xarray>=0.18.0" \
    adlfs>=2024.4.1 \
    obstore>=0.6.0 \
    requests>=2.28.0 \
    psutil>=5.9.0 \
    pydantic-settings>=2.0.0 \
    azure-monitor-opentelemetry>=1.6.0 \
    "tipg>=0.12.0" \
    "stac-fastapi.pgstac>=4.0.0" \
    "duckdb>=1.0.0"

# Set working directory
WORKDIR /app

# Create data directory for DuckDB parquet cache
RUN mkdir -p /app/data

# Copy application package
COPY geotiler /app/geotiler

# Production settings
ENV LOCAL_MODE=false
ENV USE_AZURE_AUTH=true
ENV ENABLE_PLANETARY_COMPUTER=true
ENV ENABLE_TIPG=true
ENV TIPG_SCHEMAS=geo
ENV ENABLE_STAC_API=true
ENV STAC_ROUTER_PREFIX=/stac
ENV ENABLE_H3_DUCKDB=false

# Observability settings (set APPLICATIONINSIGHTS_CONNECTION_STRING to enable telemetry)
# OBSERVABILITY_MODE enables detailed request/latency logging
# SLOW_REQUEST_THRESHOLD_MS sets the slow request threshold (default: 2000ms)
ENV OBSERVABILITY_MODE=false
ENV SLOW_REQUEST_THRESHOLD_MS=2000

# Expose port
EXPOSE 8000

# Production command - uses main.py for proper telemetry initialization
# IMPORTANT: main.py configures Azure Monitor BEFORE FastAPI import
CMD ["uvicorn", "geotiler.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
