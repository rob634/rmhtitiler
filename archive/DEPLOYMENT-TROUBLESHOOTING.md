# Azure Deployment Troubleshooting

**Date:** November 7, 2025
**Issue:** Container startup probe failing
**Status:** Diagnosed - Needs Fix

---

## Problem Summary

The Docker container is successfully pulled from ACR and started in Azure App Service, but the application inside is not responding to health check probes. Azure terminates the container after ~230 seconds.

### Error Symptoms:
- Health endpoint returns `504 Gateway Timeout`
- Container logs show: `Site startup probe failed after 230.6552666 seconds`
- Container is terminated and site shows as stopped

---

## Root Cause Analysis

### Issue #1: Module Import Path Problem

**Current Dockerfile:**
```dockerfile
# Copy custom application
COPY custom_main.py /tmp/custom_main.py

# Set the module name for uvicorn
ENV MODULE_NAME=custom_main

# Start command
CMD ["uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

**Problem:**
Uvicorn is trying to import `custom_main` as a Python module, but:
1. The file is copied to `/tmp/custom_main.py`
2. Python doesn't look in `/tmp` for modules by default
3. The module import fails silently, causing the app to never start

**Evidence from Local Tests:**
- Local Docker worked because we used a different Dockerfile (Dockerfile.local)
- Dockerfile.local uses different base and different command structure

---

## Solution Options

### Option 1: Copy to Working Directory (RECOMMENDED)

Change Dockerfile to copy custom_main.py to the working directory where uvicorn expects it:

```dockerfile
# Production Dockerfile for TiTiler with Azure Managed Identity
FROM --platform=linux/amd64 ghcr.io/developmentseed/titiler:latest

# Install Azure authentication libraries
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0 \
    azure-storage-blob>=12.19.0

# Set working directory (if not already set by base image)
WORKDIR /app

# Copy custom application to working directory
COPY custom_main.py /app/custom_main.py

# Production settings
ENV LOCAL_MODE=false
ENV USE_AZURE_AUTH=true
ENV USE_SAS_TOKEN=true

# Expose port
EXPOSE 8000

# Production command with multiple workers
CMD ["uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### Option 2: Add /tmp to Python Path

```dockerfile
# Add /tmp to Python path
ENV PYTHONPATH=/tmp:$PYTHONPATH

# Copy custom application
COPY custom_main.py /tmp/custom_main.py
```

### Option 3: Use Absolute Python Path

```dockerfile
CMD ["python", "-m", "uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```
And ensure Python can find the module in /tmp.

**Recommendation:** Use **Option 1** - it's the cleanest and most standard approach.

---

## Additional Improvements

### 1. Reduce Number of Workers for Initial Deployment

The current configuration uses `--workers 4`, which might be too many for:
- Initial deployment testing
- Basic tier App Service (limited resources)
- Startup health check (multiple workers take longer to start)

**Recommendation for Testing:**
```dockerfile
CMD ["uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**Recommendation for Production (P1V2 or higher):**
```dockerfile
CMD ["uvicorn", "custom_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### 2. Add Startup Timeout Setting

In Azure App Service, increase the startup timeout:

```bash
az webapp config set \
  --resource-group rmhazure_rg \
  --name geotiler \
  --generic-configurations '{"healthCheckPath": "/healthz", "startupTime": 300}'
```

### 3. Add Container Startup Command Logging

Add a startup script to verify the environment before uvicorn starts:

```dockerfile
# Add startup script
COPY <<EOF /app/startup.sh
#!/bin/bash
echo "=== Container Startup ==="
echo "Python version: \$(python --version)"
echo "Working directory: \$(pwd)"
echo "Python path: \$PYTHONPATH"
echo "Files in /app: \$(ls -la /app)"
echo "Environment variables:"
env | grep -E '(AZURE|LOCAL_MODE|USE_)' | sort
echo "=== Starting uvicorn ==="
exec uvicorn custom_main:app --host 0.0.0.0 --port 8000 --workers 1
EOF

RUN chmod +x /app/startup.sh

CMD ["/app/startup.sh"]
```

---

## Deployment Steps to Fix

### Step 1: Update Dockerfile

```bash
cd /Users/robertharrison/python_builds/geotiler
```

Edit `Dockerfile` with the recommended changes (Option 1).

### Step 2: Rebuild and Push Image

```bash
# Rebuild with fix
docker build --platform linux/amd64 \
  -t rmhazureacr.azurecr.io/titiler-azure:latest \
  -t rmhazureacr.azurecr.io/titiler-azure:v1.0.1 \
  -f Dockerfile \
  .

# Login to ACR
az acr login --name rmhazureacr

# Push both tags
docker push rmhazureacr.azurecr.io/titiler-azure:latest
docker push rmhazureacr.azurecr.io/titiler-azure:v1.0.1
```

### Step 3: Force Pull Latest Image

```bash
# Force webapp to pull the new image
az webapp config container set \
  --resource-group rmhazure_rg \
  --name geotiler \
  --docker-custom-image-name rmhazureacr.azurecr.io/titiler-azure:latest

# Restart
az webapp restart --resource-group rmhazure_rg --name geotiler
```

### Step 4: Monitor Startup

```bash
# Stream logs in real-time
az webapp log tail --resource-group rmhazure_rg --name geotiler

# In another terminal, wait and test health check
sleep 30 && curl "https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz"
```

### Step 5: Verify Deployment

```bash
# Check health endpoint
curl "https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/healthz" | jq

# Expected response:
# {
#   "status": "healthy",
#   "azure_auth_enabled": true,
#   "use_sas_token": true,
#   "local_mode": false,
#   "storage_account": "rmhazuregeo",
#   "sas_token_expires_in_seconds": 3400
# }

# Test COG access
curl "https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif" | jq
```

---

## Verification Checklist

After fix is deployed:

- [ ] Health endpoint returns 200 OK
- [ ] Response shows `"status": "healthy"`
- [ ] Response shows `"local_mode": false` (production mode)
- [ ] Response shows `"use_sas_token": true`
- [ ] Logs show "Generating new User Delegation SAS token (production mode)"
- [ ] Logs show no errors about missing modules or authentication
- [ ] COG info endpoint returns metadata
- [ ] Tile endpoint returns PNG images
- [ ] Container stays running (not terminated by startup probe)

---

## Current Configuration Status

### What's Working:
- ✅ ACR image successfully pushed (rmhazureacr.azurecr.io/titiler-azure:latest)
- ✅ Web App pulling image from ACR
- ✅ Managed Identity enabled (Principal ID: da61121c-aca8-4bc5-af05-eda4a1bc78a9)
- ✅ Storage permissions granted (Storage Blob Data Reader)
- ✅ Environment variables configured correctly
- ✅ Health check path configured (/healthz)
- ✅ Always-on enabled
- ✅ HTTP logging enabled
- ✅ Container starts and port 8000 is detected

### What's Not Working:
- ❌ Application not responding inside container
- ❌ Python module import issue (custom_main not found)
- ❌ Startup probe failing after 230 seconds
- ❌ Container terminated by Azure

---

## Next Actions

1. **Fix Dockerfile** - Update COPY path for custom_main.py
2. **Rebuild and Push** - Create v1.0.1 with fix
3. **Deploy and Test** - Verify health check succeeds
4. **Monitor Logs** - Confirm production mode SAS token generation
5. **Test COG Access** - Verify Azure Storage integration works

---

## Additional Debugging Tips

### Check Base Image Working Directory

```bash
# Inspect the base image to see its WORKDIR
docker run --rm ghcr.io/developmentseed/titiler:latest pwd
docker run --rm ghcr.io/developmentseed/titiler:latest ls -la
```

### Test Module Import Locally

```bash
# Test if uvicorn can find the module
docker run --rm rmhazureacr.azurecr.io/titiler-azure:latest python -c "import custom_main; print('Module found!')"
```

### Check Container Startup Directly

```bash
# Run container locally with same environment
docker run -d \
  --name titiler-test \
  -p 8001:8000 \
  -e LOCAL_MODE=false \
  -e USE_AZURE_AUTH=true \
  -e USE_SAS_TOKEN=true \
  -e AZURE_STORAGE_ACCOUNT=rmhazuregeo \
  rmhazureacr.azurecr.io/titiler-azure:latest

# Check logs
docker logs titiler-test

# Test health
curl http://localhost:8001/healthz

# Cleanup
docker stop titiler-test && docker rm titiler-test
```

---

## Support Information

- **Azure Subscription:** rmhazure
- **Resource Group:** rmhazure_rg
- **Container Registry:** rmhazureacr
- **Web App:** geotiler
- **Storage Account:** rmhazuregeo
- **Web App URL:** https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net

---

**Status:** ✅ **RESOLVED** - Deployment successful!

---

## 🎉 Resolution Summary

**Date Resolved:** November 7, 2025

### Issues Found and Fixed:

#### Issue #1: Module Import Path ✅ FIXED
**Problem:** Dockerfile copied `custom_main.py` to `/tmp/` where uvicorn couldn't import it
**Solution:** Changed to copy to `/app/` working directory
**Fixed in:** v1.0.1

#### Issue #2: Wrong SAS Permission Type ✅ FIXED
**Problem:** Using `AccountSasPermissions` with `generate_container_sas()`
**Solution:** Changed to `ContainerSasPermissions` for container-level SAS
**Fixed in:** v1.0.2

#### Issue #3: Wildcard Container Name ✅ FIXED
**Problem:** Attempted to use `container_name="*"` which isn't supported
**Solution:** Changed to specific container name `"silver-cogs"`
**Note:** For multiple containers, would need separate SAS tokens per container
**Fixed in:** v1.0.2

### Final Working Configuration:

```python
# Production SAS token generation (custom_main.py)
from azure.storage.blob import BlobServiceClient, generate_container_sas, ContainerSasPermissions
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
blob_service_client = BlobServiceClient(
    account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net",
    credential=credential
)

user_delegation_key = blob_service_client.get_user_delegation_key(
    key_start_time=now,
    key_expiry_time=now + timedelta(hours=1)
)

sas_token = generate_container_sas(
    account_name=AZURE_STORAGE_ACCOUNT,
    container_name="silver-cogs",  # ✅ Specific container
    user_delegation_key=user_delegation_key,
    permission=ContainerSasPermissions(read=True, list=True),  # ✅ Correct type
    expiry=key_expiry_time
)
```

### Deployment Verification:

✅ Health endpoint: `200 OK`
```json
{
  "status": "healthy",
  "azure_auth_enabled": true,
  "use_sas_token": true,
  "local_mode": false,
  "storage_account": "rmhazuregeo",
  "sas_token_expires_in_seconds": 3585
}
```

✅ COG Info endpoint: Working
```bash
curl "https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/info?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif"
# Returns: bounds, crs, band_metadata, etc.
```

✅ Tile endpoint: Working
```bash
curl "https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/tiles/WebMercatorQuad/15/9373/12532.png?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif" --output tile.png
# Returns: 154KB PNG image (256x256 RGBA)
```

✅ Interactive Map Viewer: Working
```
https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=/vsiaz/silver-cogs/copy47_of_dctest3_R1C2_cog_analysis.tif
```
**Note:** The viewer is at `/cog/{tileMatrixSetId}/map.html`, NOT `/cog/viewer` (which doesn't exist)

### Production Deployment Details:

- **ACR Image:** rmhazureacr.azurecr.io/titiler-azure:v1.0.2
- **Web App:** geotiler
- **Container:** Running successfully
- **Managed Identity:** Working with Storage Blob Data Reader role
- **SAS Token:** Generating correctly with user delegation key
- **GDAL Access:** Successfully reading from Azure Blob Storage

---

**Status:** Production deployment complete and verified! 🚀
