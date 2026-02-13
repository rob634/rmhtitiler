# Production Dockerfile for TiTiler-pgSTAC with Azure OAuth authentication,
# Xarray/Zarr support, and Planetary Computer integration
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
