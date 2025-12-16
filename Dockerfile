# Production Dockerfile for TiTiler with Azure OAuth authentication
FROM ghcr.io/developmentseed/titiler:latest

# Install Azure authentication and xarray support
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0 \
    "titiler.xarray[full]>=0.18.0" \
    adlfs>=2024.4.1

# Set working directory
WORKDIR /app

# Copy custom application to working directory where uvicorn can find it
COPY custom_main.py /app/custom_main.py

# Production settings
ENV LOCAL_MODE=false
ENV USE_AZURE_AUTH=true

# Expose port
EXPOSE 8000

# Production command - using 1 worker for initial deployment
# Scale up to 2-4 workers after successful deployment
CMD ["uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
