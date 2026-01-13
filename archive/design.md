# TiTiler with Azure Managed Identity - Implementation Guide

## Overview

This guide explains how to add Azure Managed Identity authentication to TiTiler so it can securely read Cloud-Optimized GeoTIFFs (COGs) from Azure Blob Storage without storing credentials.

## What We're Building

```
┌─────────────────────────────────────────────────────────────┐
│                     Azure Web App                            │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              TiTiler Container                         │ │
│  │                                                         │ │
│  │  1. Startup: Get Azure AD token via Managed Identity  │ │
│  │  2. Middleware: Refresh token before each request     │ │
│  │  3. Set AZURE_STORAGE_ACCESS_TOKEN env var           │ │
│  │  4. GDAL reads from /vsiaz/container/file.tif        │ │
│  │  5. TiTiler serves tiles normally                     │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────────┐
                    │  Azure Blob Storage  │
                    │  (with RBAC access)  │
                    └──────────────────────┘
```

## Key Concepts

### Managed Identity
- Azure Web Apps can have a "managed identity" (like a service account)
- This identity can be granted permissions to access Azure resources
- No passwords/keys needed in code - Azure handles authentication automatically

### GDAL /vsiaz/ Virtual File System
- GDAL (the library TiTiler uses) can read files from Azure Blob Storage
- Uses special paths like `/vsiaz/containername/path/to/file.tif`
- Authenticates using environment variables:
  - `AZURE_STORAGE_ACCOUNT` = storage account name
  - `AZURE_STORAGE_ACCESS_TOKEN` = OAuth token from managed identity

### FastAPI Middleware
- Code that runs before every HTTP request
- We use it to ensure the Azure token is fresh before TiTiler processes requests
- Token is cached and only refreshed when needed (every ~55 minutes)

## Project Structure

```
titiler-azure/
├── Dockerfile                 # Container definition
├── custom_main.py            # Modified TiTiler app with auth
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

## Implementation Steps

### Step 1: Create custom_main.py

This file wraps the standard TiTiler application with Azure authentication.

**What it does:**
1. Imports the standard TiTiler application
2. Adds a middleware that runs before each request
3. Gets Azure Storage tokens using managed identity
4. Caches tokens (they're valid for 60 minutes)
5. Sets environment variables that GDAL reads

**Key components:**

```python
# Token cache - stores token and expiry time
token_cache = {
    "token": None,           # The actual access token
    "expires_at": None,      # When it expires
    "lock": Lock()           # Prevents race conditions with multiple workers
}

# Function to get token (with caching)
def get_fresh_token() -> str:
    # Check if cached token is still valid
    # If not, get new token from Azure
    # Return token

# Middleware - runs on every request
class AzureAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Get fresh token
        # Set environment variables for GDAL
        # Continue with request

# Startup - runs once when app starts
@app.on_event("startup")
async def startup_event():
    # Get initial token
    # Log success
```

**Important details:**
- Uses `DefaultAzureCredential()` - automatically uses managed identity when running in Azure
- Tokens are refreshed 5 minutes before expiry to avoid races
- Thread-safe with Lock() to handle multiple uvicorn workers
- Graceful error handling - continues with cached token if refresh fails

### Step 2: Create Dockerfile

This defines how to build the container image.

**What it does:**
1. Starts from official TiTiler image (has GDAL, Python, etc.)
2. Installs Azure authentication libraries
3. Copies our custom main file
4. Configures uvicorn to use our custom app

**Key points:**
- `FROM ghcr.io/developmentseed/titiler:latest` - builds on official image
- `pip install azure-identity` - adds Azure authentication support
- `ENV MODULE_NAME=custom_main` - tells uvicorn to use our file
- `--workers 4` - runs 4 worker processes for performance

### Step 3: Create requirements.txt

Lists Python dependencies to install:

```
azure-identity>=1.15.0
azure-storage-blob>=12.19.0
```

**Why these packages:**
- `azure-identity` - Gets tokens from managed identity
- `azure-storage-blob` - Not directly used, but helpful for debugging

## Deployment to Azure

### Prerequisites
1. Azure Container Registry (ACR)
2. Azure App Service or App Service Environment
3. Azure Storage Account with blob container
4. Permissions to assign roles

### Step-by-Step Deployment

#### 1. Build and Push Container to ACR

```bash
# Login to your Azure Container Registry
az acr login --name yourregistryname

# Build and push in one command
az acr build \
  --registry yourregistryname \
  --image titiler-azure:latest \
  --file Dockerfile \
  .
```

**What this does:**
- Builds Docker image using your Dockerfile
- Pushes image to Azure Container Registry
- Tags it as `titiler-azure:latest`

#### 2. Create Web App

```bash
# Create web app using container from ACR
az webapp create \
  --resource-group your-resource-group \
  --plan your-app-service-plan \
  --name your-titiler-app \
  --deployment-container-image-name yourregistryname.azurecr.io/titiler-azure:latest
```

**Important:**
- Use an existing App Service Plan (or create one first)
- Name must be globally unique (becomes your-titiler-app.azurewebsites.net)
- Plan must support containers (Linux-based)

#### 3. Enable Managed Identity

```bash
# Enable system-assigned managed identity on the web app
az webapp identity assign \
  --resource-group your-resource-group \
  --name your-titiler-app
```

**This command returns JSON with principalId - SAVE THIS!** You need it for the next step.

Example output:
```json
{
  "principalId": "12345678-1234-1234-1234-123456789abc",
  "tenantId": "...",
  "type": "SystemAssigned"
}
```

#### 4. Set Environment Variables

```bash
# Tell the app which storage account to use
az webapp config appsettings set \
  --resource-group your-resource-group \
  --name your-titiler-app \
  --settings AZURE_STORAGE_ACCOUNT=yourstorageaccountname
```

**Why:** The app needs to know which storage account to authenticate against.

#### 5. Grant Storage Access

```bash
# Give the managed identity permission to read blobs
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee-object-id <principalId-from-step-3> \
  --scope /subscriptions/<subscription-id>/resourceGroups/<storage-rg>/providers/Microsoft.Storage/storageAccounts/yourstorageaccount
```

**Role options:**
- `Storage Blob Data Reader` - Read-only (recommended for TiTiler)
- `Storage Blob Data Contributor` - Read/write
- `Storage Blob Data Owner` - Full control

**Getting the scope:**
```bash
# Get full resource ID of storage account
az storage account show \
  --name yourstorageaccount \
  --resource-group storage-resource-group \
  --query id -o tsv
```

#### 6. Configure ACR Access (if using private registry)

```bash
# Allow web app to pull images from ACR
az webapp config container set \
  --resource-group your-resource-group \
  --name your-titiler-app \
  --docker-registry-server-url https://yourregistryname.azurecr.io \
  --enable-app-service-storage false
```

## Testing the Deployment

### 1. Check App Status

```bash
# View logs
az webapp log tail \
  --resource-group your-resource-group \
  --name your-titiler-app
```

**Look for:**
- "Initializing Azure auth for account: yourstorageaccount"
- "Azure authentication initialized successfully"
- "Token acquired, expires at ..."

### 2. Test TiTiler Endpoints

```bash
# Health check
curl https://your-titiler-app.azurewebsites.net/healthz

# Get info about a COG in Azure Storage
curl "https://your-titiler-app.azurewebsites.net/cog/info?url=/vsiaz/yourcontainer/path/to/file.tif"

# Get a tile
curl "https://your-titiler-app.azurewebsites.net/cog/tiles/WebMercatorQuad/14/3876/6325?url=/vsiaz/yourcontainer/path/to/file.tif"
```

**Expected behavior:**
- Info endpoint returns GeoJSON with raster metadata
- Tiles endpoint returns PNG/JPEG image data
- First request may be slower (token acquisition)
- Subsequent requests should be fast (<100ms)

### 3. View Token Refresh in Logs

```bash
# Watch logs in real-time
az webapp log tail --resource-group your-resource-group --name your-titiler-app
```

**Every ~55 minutes you should see:**
- "Acquiring new Azure Storage token"
- "Token acquired, expires at [timestamp]"

## Troubleshooting

### Error: "No module named 'azure.identity'"

**Problem:** Azure dependencies not installed

**Solution:** Rebuild container, ensure requirements.txt is copied and pip install runs

### Error: "DefaultAzureCredential failed to retrieve a token"

**Problem:** Managed identity not enabled or not working

**Solutions:**
1. Verify identity is enabled: `az webapp identity show --resource-group ... --name ...`
2. Restart web app: `az webapp restart --resource-group ... --name ...`
3. Check environment: Managed identity only works when running IN Azure

### Error: "AuthorizationPermissionMismatch" or "403 Forbidden"

**Problem:** Managed identity doesn't have permission to storage account

**Solutions:**
1. Verify role assignment exists:
   ```bash
   az role assignment list \
     --assignee <principalId> \
     --scope <storage-account-resource-id>
   ```
2. Wait 5-10 minutes for permission propagation
3. Check storage account firewall - ensure "Allow trusted Microsoft services" is checked

### Error: "AZURE_STORAGE_ACCOUNT environment variable not set"

**Problem:** Missing configuration

**Solution:**
```bash
az webapp config appsettings set \
  --resource-group your-resource-group \
  --name your-titiler-app \
  --settings AZURE_STORAGE_ACCOUNT=yourstorageaccount
```

### Tiles Return 500 Error

**Problem:** GDAL can't read the file

**Debug steps:**
1. Check logs for GDAL errors
2. Verify file path: `/vsiaz/containername/path/to/file.tif`
3. Test file directly with Azure CLI:
   ```bash
   az storage blob exists \
     --account-name youraccount \
     --container-name yourcontainer \
     --name path/to/file.tif
   ```
4. Ensure file is actually a COG (Cloud-Optimized GeoTIFF)

### Token Not Refreshing

**Problem:** Middleware not being called or token cache broken

**Debug:**
1. Check logs for "Acquiring new Azure Storage token" messages
2. Verify middleware is registered (check startup logs)
3. Restart app to reset token cache

## Performance Considerations

### Token Caching
- Tokens cached for ~55 minutes (refreshed 5 min before expiry)
- Cache is thread-safe with Lock()
- Minimal overhead: token check is <1ms

### Uvicorn Workers
- Default: 4 workers for parallel request handling
- Each worker shares the same token cache (via Python module)
- Increase workers for higher concurrency: `--workers 8`

### GDAL Configuration
- GDAL automatically uses cached HTTP connections for /vsiaz/
- Set these environment variables for better performance:
  ```bash
  CPL_VSIL_CURL_CACHE_SIZE=128000000
  GDAL_CACHEMAX=512
  GDAL_HTTP_MULTIPLEX=YES
  ```

### Scaling
- App Service can scale horizontally (multiple instances)
- Each instance gets its own managed identity token
- No shared state issues - each instance is independent

## Advanced Configuration

### Custom Token Scopes

If you need to access other Azure resources:

```python
# In custom_main.py, change token scope
token_response = credential.get_token("https://management.azure.com/.default")  # For ARM APIs
token_response = credential.get_token("https://vault.azure.net/.default")       # For Key Vault
```

### Multiple Storage Accounts

To support multiple storage accounts:

```python
# Modify middleware to accept storage account in query params
async def dispatch(self, request: Request, call_next):
    # Parse storage account from URL
    storage_account = request.query_params.get("storage_account", 
                                               os.getenv("AZURE_STORAGE_ACCOUNT"))
    os.environ["AZURE_STORAGE_ACCOUNT"] = storage_account
    
    # Get token (same as before)
    token = get_fresh_token()
    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
    
    response = await call_next(request)
    return response
```

### User-Assigned Managed Identity

Instead of system-assigned, use a specific identity:

```python
# In custom_main.py
from azure.identity import ManagedIdentityCredential

# Specify client ID of user-assigned identity
credential = ManagedIdentityCredential(client_id="your-identity-client-id")
```

### Integration with Application Insights

Add telemetry for token refresh:

```python
from applicationinsights import TelemetryClient

tc = TelemetryClient(os.getenv("APPINSIGHTS_INSTRUMENTATIONKEY"))

def get_fresh_token() -> str:
    with token_cache["lock"]:
        # ... existing code ...
        
        logger.info("Acquiring new Azure Storage token")
        tc.track_event("TokenRefresh", {"account": os.getenv("AZURE_STORAGE_ACCOUNT")})
        
        credential = DefaultAzureCredential()
        token_response = credential.get_token("https://storage.azure.com/.default")
        
        # ... rest of code ...
```

## Security Best Practices

1. **Least Privilege**: Use "Storage Blob Data Reader" role, not "Contributor" or "Owner"
2. **Network Security**: Configure storage account firewall to only allow traffic from your ASE/VNet
3. **Monitoring**: Enable Application Insights to track token refresh and access patterns
4. **Rotation**: Managed identity tokens auto-rotate - no manual intervention needed
5. **Audit**: Enable Azure Monitor logs on storage account to track access

## References

- [TiTiler Documentation](https://developmentseed.org/titiler/)
- [GDAL Azure Blob Storage](https://gdal.org/user/virtual_file_systems.html#vsiaz-microsoft-azure-blob-files)
- [Azure Managed Identities](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/overview)
- [DefaultAzureCredential](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential)

## Questions for Claude Code

When implementing this, here are helpful things to know:

1. **What is your storage account name?** (needed for AZURE_STORAGE_ACCOUNT env var)
2. **What is your container name?** (needed for /vsiaz/CONTAINER/... paths)
3. **What is your ACR name?** (for building and pushing images)
4. **What is your resource group name?** (for all az commands)
5. **What is your App Service Plan name?** (for deployment)
6. **Do you want to use system-assigned or user-assigned managed identity?** (system is simpler)

Good luck! This is a great learning experience - you're essentially building a production-grade geospatial tile server with enterprise authentication. 🚀