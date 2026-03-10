# Production Dockerfile for TiTiler-pgSTAC with Azure OAuth authentication
# and Xarray/Zarr support
#
# Build args:
#   BASE_TAG       - titiler-pgstac image tag (default: 1.9.0)
#   REQUIREMENTS   - requirements file to use (default: requirements.txt)
#
# v9 build:  az acr build ... --build-arg BASE_TAG=1.9.0
# v10 build: az acr build ... --build-arg BASE_TAG=2.1.0 --build-arg REQUIREMENTS=requirements-v10.txt
#
ARG BASE_TAG=1.9.0
FROM ghcr.io/stac-utils/titiler-pgstac:${BASE_TAG}
#Use the JFROG Artifactory image for production deployments
#FROM artifactory.worldbank.org/itsdt-docker-virtual/titiler-pgstac:${BASE_TAG}

# Switch to root for installs (base image 2.x runs as non-root)
USER root

# Set working directory
WORKDIR /app

# Install dependencies
ARG REQUIREMENTS=requirements.txt
COPY ${REQUIREMENTS} requirements.txt
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
