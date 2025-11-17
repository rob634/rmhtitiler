# Production Dockerfile for TiTiler-pgSTAC with Azure Managed Identity OAuth
FROM --platform=linux/amd64 ghcr.io/stac-utils/titiler-pgstac:latest

# Install Azure authentication library (for Managed Identity OAuth)
RUN pip install --no-cache-dir azure-identity>=1.15.0

# Set working directory
WORKDIR /app

# Copy custom application
COPY custom_pgstac_main.py /app/custom_pgstac_main.py

# Production settings (no secrets in Dockerfile)
ENV LOCAL_MODE=false
ENV USE_AZURE_AUTH=true

# Environment variables set via Azure App Service Configuration:
# - DATABASE_URL: PostgreSQL connection string
# - AZURE_STORAGE_ACCOUNT: Storage account name (rmhazuregeo)
# - CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff
# - GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
# - GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES
# - GDAL_HTTP_MULTIPLEX=YES
# - GDAL_HTTP_VERSION=2
# - VSI_CACHE=TRUE
# - VSI_CACHE_SIZE=536870912

# Expose port
EXPOSE 8000

# Production command with multiple workers for concurrency
CMD ["uvicorn", "custom_pgstac_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
