# Production Dockerfile for TiTiler-pgSTAC with Azure Managed Identity OAuth
FROM ghcr.io/stac-utils/titiler-pgstac:latest

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
# See .env.template for full list of required variables
# Key variables: POSTGRES_*, AZURE_STORAGE_ACCOUNT, USE_AZURE_AUTH, LOCAL_MODE
# GDAL optimization: CPL_VSIL_*, GDAL_*, VSI_*

# Expose port
EXPOSE 8000

# Production command with multiple workers for concurrency
CMD ["uvicorn", "custom_pgstac_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
