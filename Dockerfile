# Production Dockerfile for TiTiler-pgSTAC with Azure OAuth authentication
# and Xarray/Zarr support
FROM ghcr.io/stac-utils/titiler-pgstac:1.9.0
#Use the JFROG Artifactory image for production deployments
#FROM artifactory.worldbank.org/itsdt-docker-virtual/titiler-pgstac:1.9.0

# Set working directory
WORKDIR /app

# Install dependencies (requirements.txt is the single source of truth)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory for DuckDB parquet cache
RUN mkdir -p /app/data

# Copy application package
COPY geotiler /app/geotiler

# Production settings — GEOTILER_COMPONENT_SETTING convention
ENV GEOTILER_AUTH_USE_CLI=false
ENV GEOTILER_ENABLE_STORAGE_AUTH=true
ENV GEOTILER_ENABLE_TIPG=true
ENV GEOTILER_TIPG_SCHEMAS=geo
ENV GEOTILER_ENABLE_STAC_API=true
ENV GEOTILER_STAC_PREFIX=/stac
ENV GEOTILER_ENABLE_H3_DUCKDB=false

# Observability (set APPLICATIONINSIGHTS_CONNECTION_STRING to enable telemetry)
ENV GEOTILER_ENABLE_OBSERVABILITY=false
ENV GEOTILER_OBS_SLOW_THRESHOLD_MS=2000

# Expose port
EXPOSE 8000

# Production command - uses main.py for proper telemetry initialization
# IMPORTANT: main.py configures Azure Monitor BEFORE FastAPI import
CMD ["uvicorn", "geotiler.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
