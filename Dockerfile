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
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0 \
    azure-keyvault-secrets>=4.7.0 \
    "titiler.xarray>=0.18.0" \
    adlfs>=2024.4.1 \
    obstore>=0.6.0 \
    requests>=2.28.0 \
    psutil>=5.9.0 \
    nicegui>=2.0.0 \
    httpx>=0.27.0

# Set working directory
WORKDIR /app

# Copy custom application and dashboard to working directory
COPY custom_pgstac_main.py /app/custom_pgstac_main.py
COPY dashboard /app/dashboard

# Production settings
ENV LOCAL_MODE=false
ENV USE_AZURE_AUTH=true
ENV ENABLE_PLANETARY_COMPUTER=true

# Expose port
EXPOSE 8000

# Production command - using 1 worker for initial deployment
CMD ["uvicorn", "custom_pgstac_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
