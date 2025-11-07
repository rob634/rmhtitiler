# Production Dockerfile for TiTiler with Azure Managed Identity
# Use platform flag for cross-platform builds
FROM --platform=linux/amd64 ghcr.io/developmentseed/titiler:latest

# Install Azure authentication libraries
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0 \
    azure-storage-blob>=12.19.0

# Set working directory
WORKDIR /app

# Copy custom application to working directory where uvicorn can find it
COPY custom_main.py /app/custom_main.py

# Production settings
ENV LOCAL_MODE=false
ENV USE_AZURE_AUTH=true
ENV USE_SAS_TOKEN=true

# Expose port
EXPOSE 8000

# Production command - using 1 worker for initial deployment
# Scale up to 2-4 workers after successful deployment
CMD ["uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
