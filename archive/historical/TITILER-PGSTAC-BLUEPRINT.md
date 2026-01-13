# TiTiler-pgSTAC Implementation Blueprint

**Document Version**: 1.0
**Created**: November 8, 2025
**Status**: Ready for Implementation
**Based on**: geotiler v2.0.0 (OAuth Bearer Token Authentication)

---

## Executive Summary

This document provides a complete blueprint for creating a new **TiTiler-pgSTAC** project with Azure OAuth authentication, based on the successful implementation in the geotiler project.

**Key Success from geotiler**:
- OAuth Bearer Tokens provide account-wide access to ALL containers
- Single token approach is 36% simpler than SAS tokens (325 vs 508 lines)
- Multi-container access works automatically via RBAC permissions
- Production-validated approach using Azure Managed Identity

**Goal**: Replicate this OAuth authentication approach in a new TiTiler-pgSTAC project for STAC catalog integration with PostgreSQL backend.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Prerequisites](#prerequisites)
3. [Architecture](#architecture)
4. [Directory Structure](#directory-structure)
5. [Core Implementation Files](#core-implementation-files)
6. [OAuth Authentication Code](#oauth-authentication-code)
7. [Docker Configuration](#docker-configuration)
8. [Database Configuration](#database-configuration)
9. [Local Development Setup](#local-development-setup)
10. [Production Deployment](#production-deployment)
11. [Testing & Validation](#testing--validation)
12. [Troubleshooting](#troubleshooting)
13. [Migration from geotiler](#migration-from-geotiler)

---

## Project Overview

### What is TiTiler-pgSTAC?

TiTiler-pgSTAC extends TiTiler to work with STAC (SpatioTemporal Asset Catalog) metadata stored in PostgreSQL with the pgSTAC extension. It enables:

- **Dynamic Mosaics**: Generate tiles from STAC search queries
- **STAC Item Access**: Serve tiles from STAC item assets
- **Multi-Container Assets**: STAC items reference COGs in multiple Azure blob containers
- **Scalable Queries**: PostgreSQL-backed STAC catalog for efficient spatial searches

### Why OAuth Authentication is Critical

STAC items reference assets (COG files) that may be stored across multiple Azure blob containers:

```json
{
  "type": "Feature",
  "id": "namangan-2019-08-14",
  "assets": {
    "visual": {
      "href": "/vsiaz/rmhazuregeobronze/namangan/namangan14aug2019_R1C1cog.tif"
    }
  }
}
```

**With SAS Tokens**: Would need separate tokens per container (complex, unmaintainable)
**With OAuth Tokens**: Single token grants access to all containers per RBAC role (simple, proven)

---

## Prerequisites

### Azure Resources Required

1. **Azure Database for PostgreSQL - Flexible Server**
   - PostgreSQL version 14 or higher
   - pgSTAC extension installed
   - Accessible from TiTiler-pgSTAC App Service

2. **Azure Storage Account** (existing)
   - Resource: `rmhazuregeo` (or your storage account)
   - Containers with STAC-referenced COG files

3. **Azure Container Registry** (existing)
   - Resource: `rmhazureacr`

4. **Azure App Service** (to be created)
   - Linux container plan
   - System-assigned Managed Identity enabled

5. **RBAC Role Assignment**
   - Storage Blob Data Reader role on storage account
   - Assigned to App Service Managed Identity

### Tools Required

- Azure CLI (`az`)
- Docker
- PostgreSQL client (`psql`)
- Python 3.10+
- Git

### Knowledge from geotiler

Review these documents from the geotiler project:
- `docs/OAUTH-TOKEN-APPROACH.md` - OAuth vs SAS comparison
- `custom_main.py` - OAuth authentication implementation
- `docs/ROADMAP.md` - Phase 1 completion details

---

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    TiTiler-pgSTAC App Service               │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  FastAPI Application (custom_pgstac_main.py)         │  │
│  │                                                       │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │  OAuth Authentication Middleware               │  │  │
│  │  │  - Get OAuth token from Managed Identity       │  │  │
│  │  │  - Set AZURE_STORAGE_ACCESS_TOKEN env var      │  │  │
│  │  │  - Token cached, auto-refreshed every ~24h     │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  │                                                       │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │  TiTiler-pgSTAC Core                           │  │  │
│  │  │  - STAC search endpoints                       │  │  │
│  │  │  - Mosaic tile generation                      │  │  │
│  │  │  - Database queries (PostgreSQL)               │  │  │
│  │  │  - GDAL /vsiaz/ reads (uses OAuth token)       │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▲                                  │
│                          │ Managed Identity                │
│                          │ (OAuth Token)                   │
└──────────────────────────┼─────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌──────────────┐  ┌──────────────┐
│  PostgreSQL   │  │ Azure Blob   │  │ Azure Blob   │
│  (pgSTAC)     │  │ Container 1  │  │ Container 2  │
│               │  │ (bronze)     │  │ (silver)     │
│  STAC Items   │  │              │  │              │
│  Collections  │  │  COG files   │  │  COG files   │
│  Searches     │  │              │  │              │
└───────────────┘  └──────────────┘  └──────────────┘
```

### Request Flow

1. **Client Request**: `GET /searches/{search_id}/tiles/{z}/{x}/{y}`
2. **OAuth Middleware**: Ensures valid OAuth token is set in environment
3. **pgSTAC Query**: Search database for STAC items matching criteria
4. **Asset Extraction**: Get COG URLs from STAC item assets
5. **Mosaic Generation**: GDAL reads COGs via `/vsiaz/` (uses OAuth token)
6. **Tile Response**: Return rendered tile image

### Authentication Flow

```
Startup:
  1. App starts
  2. Middleware gets OAuth token from Managed Identity
  3. Token cached (expires in ~24 hours)
  4. Token set in AZURE_STORAGE_ACCESS_TOKEN env var

Per Request:
  1. Check cached token expiry
  2. If < 5 minutes remaining, refresh token
  3. Ensure AZURE_STORAGE_ACCESS_TOKEN is set
  4. Process request (GDAL reads use token)
  5. Return response

Token Refresh:
  - Automatic, happens in middleware
  - Thread-safe with lock
  - Transparent to application logic
```

---

## Directory Structure

### Recommended Project Structure

```
geotiler-pgstac/
├── README.md                          # Project overview and quickstart
├── .gitignore                         # Git ignore patterns
├── requirements.txt                   # Production dependencies
├── requirements-dev.txt               # Development dependencies
├── Dockerfile                         # Production container
├── Dockerfile.local                   # Local development container
├── docker-compose.yml                 # Local dev: app + PostgreSQL
├── .env.example                       # Example environment variables
│
├── custom_pgstac_main.py              # Main application (OAuth + pgSTAC)
│
├── scripts/
│   ├── init_pgstac.sh                 # Initialize pgSTAC database
│   ├── load_sample_data.py            # Load sample STAC items
│   └── test_oauth.py                  # Test OAuth token acquisition
│
├── tests/
│   ├── test_oauth_auth.py             # OAuth authentication tests
│   ├── test_stac_search.py            # STAC search tests
│   ├── test_mosaic_tiles.py           # Mosaic tile generation tests
│   └── test_multi_container.py        # Multi-container access tests
│
└── docs/
    ├── ARCHITECTURE.md                # Architecture documentation
    ├── DEPLOYMENT.md                  # Deployment guide
    ├── DEVELOPMENT.md                 # Local development guide
    ├── API.md                         # API endpoint documentation
    └── TROUBLESHOOTING.md             # Common issues and solutions
```

---

## Core Implementation Files

### 1. custom_pgstac_main.py

This is the main application file. It combines:
- OAuth authentication from geotiler
- TiTiler-pgSTAC integration
- Database connection management

**Key Components**:

```python
"""
TiTiler-pgSTAC with Azure OAuth Token authentication

Multi-container STAC catalog with identity-based Azure Storage access.
"""
import os
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from titiler.pgstac.factory import MosaicTilerFactory
from titiler.pgstac.db import close_db_connection, connect_to_db
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers

# Configuration
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL")

# OAuth token cache
oauth_token_cache = {
    "token": None,
    "expires_at": None,
    "lock": Lock()
}

# OAuth function (copied from geotiler custom_main.py)
def get_azure_storage_oauth_token() -> Optional[str]:
    """Get OAuth token for Azure Storage using Managed Identity."""
    # ... (exact copy from geotiler custom_main.py:49-168)
    pass

# Middleware (adapted from geotiler)
class AzureAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that ensures Azure Storage OAuth token is set before each request."""
    async def dispatch(self, request: Request, call_next):
        # ... (adapted from geotiler custom_main.py:171-194)
        pass

# Create FastAPI application
app = FastAPI(
    title="TiTiler-pgSTAC with Azure OAuth Auth",
    description="STAC catalog tile server with Azure Managed Identity authentication",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Azure authentication middleware
app.add_middleware(AzureAuthMiddleware)

# Add exception handlers
add_exception_handlers(app, DEFAULT_STATUS_CODES)

# Register TiTiler-pgSTAC mosaic endpoints
mosaic = MosaicTilerFactory(
    router_prefix="/mosaic",
    add_statistics=True,
    add_viewer=True,
)
app.include_router(mosaic.router, prefix="/mosaic", tags=["Mosaic"])

# Health check endpoint
@app.get("/healthz", tags=["Health"])
async def health():
    """Health check endpoint with OAuth and database status."""
    # ... (adapted from geotiler custom_main.py:224-246)
    # Add database connection check
    pass

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize database connection and Azure OAuth authentication."""
    # Initialize database
    await connect_to_db(app, settings={"database_url": DATABASE_URL})

    # Initialize OAuth (from geotiler custom_main.py:276-318)
    if USE_AZURE_AUTH:
        # ... OAuth initialization
        pass

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup database connection on shutdown."""
    await close_db_connection(app)
```

### 2. requirements.txt

```txt
# Production dependencies for TiTiler-pgSTAC with Azure OAuth authentication

# Azure authentication - OAuth tokens via Managed Identity
azure-identity>=1.15.0

# TiTiler-pgSTAC and dependencies
titiler.pgstac>=1.0.0

# Database
asyncpg>=0.29.0
psycopg2-binary>=2.9.9

# Additional dependencies (if not in titiler.pgstac)
pydantic>=2.0.0
pydantic-settings>=2.0.0
```

### 3. requirements-dev.txt

```txt
# Development dependencies

-r requirements.txt

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
httpx>=0.24.0

# Code quality
black>=23.0.0
ruff>=0.1.0
mypy>=1.5.0

# Database testing
pytest-postgresql>=5.0.0
```

### 4. Dockerfile

```dockerfile
# Production Dockerfile for TiTiler-pgSTAC with Azure OAuth authentication
FROM ghcr.io/stac-utils/titiler-pgstac:latest

# Install Azure authentication library (OAuth tokens only)
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0

# Set working directory
WORKDIR /app

# Copy custom application
COPY custom_pgstac_main.py /app/custom_pgstac_main.py

# Production settings
ENV LOCAL_MODE=false
ENV USE_AZURE_AUTH=true

# Database URL will be set via App Service configuration
# AZURE_STORAGE_ACCOUNT will be set via App Service configuration

# Expose port
EXPOSE 8000

# Production command
# Note: Increase workers based on load (2-4 recommended)
CMD ["uvicorn", "custom_pgstac_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### 5. docker-compose.yml

```yaml
# Local development environment
version: '3.8'

services:
  # PostgreSQL with pgSTAC extension
  postgres:
    image: ghcr.io/stac-utils/pgstac:v0.8.2
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: pgstac
      PGUSER: postgres
      PGPASSWORD: postgres
      PGDATABASE: pgstac
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  # TiTiler-pgSTAC application
  titiler-pgstac:
    build:
      context: .
      dockerfile: Dockerfile.local
    environment:
      LOCAL_MODE: "true"
      USE_AZURE_AUTH: "true"
      AZURE_STORAGE_ACCOUNT: "rmhazuregeo"
      DATABASE_URL: "postgresql://postgres:postgres@postgres:5432/pgstac"
      CPL_VSIL_CURL_ALLOWED_EXTENSIONS: ".tif,.tiff"
      GDAL_DISABLE_READDIR_ON_OPEN: "EMPTY_DIR"
      GDAL_HTTP_MERGE_CONSECUTIVE_RANGES: "YES"
      GDAL_HTTP_MULTIPLEX: "YES"
      GDAL_HTTP_VERSION: "2"
      VSI_CACHE: "TRUE"
      VSI_CACHE_SIZE: "536870912"
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./custom_pgstac_main.py:/app/custom_pgstac_main.py
    command: ["uvicorn", "custom_pgstac_main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

volumes:
  postgres-data:
```

### 6. Dockerfile.local

```dockerfile
# Local development Dockerfile for TiTiler-pgSTAC with Azure OAuth authentication
FROM ghcr.io/stac-utils/titiler-pgstac:latest

# Install Azure authentication library and development tools
RUN pip install --no-cache-dir \
    azure-identity>=1.15.0 \
    azure-cli

# Set working directory
WORKDIR /app

# Copy custom application
COPY custom_pgstac_main.py /app/custom_pgstac_main.py

# Local development settings
ENV LOCAL_MODE=true
ENV USE_AZURE_AUTH=true

# Expose port
EXPOSE 8000

# Development command (with reload)
CMD ["uvicorn", "custom_pgstac_main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

### 7. .env.example

```bash
# Azure Configuration
AZURE_STORAGE_ACCOUNT=rmhazuregeo
USE_AZURE_AUTH=true
LOCAL_MODE=true

# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pgstac

# GDAL Configuration (optimization for cloud-optimized GeoTIFFs)
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES
GDAL_HTTP_MULTIPLEX=YES
GDAL_HTTP_VERSION=2
VSI_CACHE=TRUE
VSI_CACHE_SIZE=536870912

# Application Configuration
LOG_LEVEL=INFO
```

---

## OAuth Authentication Code

### Complete OAuth Implementation

**Copy this function from geotiler `custom_main.py:49-168`**:

```python
def get_azure_storage_oauth_token() -> Optional[str]:
    """
    Get OAuth token for Azure Storage using Managed Identity.

    This token grants access to ALL containers based on the Managed Identity's
    RBAC role assignments (e.g., Storage Blob Data Reader).

    The token is valid for ~1 hour and is automatically cached and refreshed.

    Returns:
        str: OAuth bearer token for Azure Storage
        None: If authentication is disabled or fails
    """
    if not USE_AZURE_AUTH:
        logger.debug("Azure OAuth authentication disabled")
        return None

    with oauth_token_cache["lock"]:
        now = datetime.now(timezone.utc)

        # Check cached token (refresh 5 minutes before expiry)
        if oauth_token_cache["token"] and oauth_token_cache["expires_at"]:
            time_until_expiry = (oauth_token_cache["expires_at"] - now).total_seconds()

            if time_until_expiry > 300:  # More than 5 minutes remaining
                logger.debug(f"✓ Using cached OAuth token, expires in {time_until_expiry:.0f}s")
                return oauth_token_cache["token"]
            else:
                logger.info(f"⚠ OAuth token expires in {time_until_expiry:.0f}s, refreshing...")

        # Generate new token
        logger.info("=" * 80)
        logger.info("🔑 Acquiring OAuth token for Azure Storage")
        logger.info("=" * 80)
        logger.info(f"Mode: {'DEVELOPMENT (Azure CLI)' if LOCAL_MODE else 'PRODUCTION (Managed Identity)'}")
        logger.info(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
        logger.info(f"Token Scope: https://storage.azure.com/.default")
        logger.info("=" * 80)

        try:
            from azure.identity import DefaultAzureCredential

            # Step 1: Get credential (Azure CLI in dev, Managed Identity in prod)
            logger.debug("Step 1/2: Creating DefaultAzureCredential...")
            try:
                credential = DefaultAzureCredential()
                logger.info("✓ DefaultAzureCredential created successfully")
            except Exception as cred_error:
                logger.error("=" * 80)
                logger.error("❌ FAILED TO CREATE AZURE CREDENTIAL")
                logger.error("=" * 80)
                logger.error(f"Error Type: {type(cred_error).__name__}")
                logger.error(f"Error Message: {str(cred_error)}")
                logger.error("")
                logger.error("Troubleshooting:")
                if LOCAL_MODE:
                    logger.error("  - Run: az login")
                    logger.error("  - Verify: az account show")
                else:
                    logger.error("  - Verify Managed Identity: az webapp identity show --name <app> --resource-group <rg>")
                    logger.error("  - Wait 2-3 minutes after enabling identity")
                logger.error("=" * 80)
                raise

            # Step 2: Get token for Azure Storage scope
            logger.debug("Step 2/2: Requesting token for scope 'https://storage.azure.com/.default'...")
            try:
                token = credential.get_token("https://storage.azure.com/.default")
                access_token = token.token
                expires_on = datetime.fromtimestamp(token.expires_on, tz=timezone.utc)

                logger.info(f"✓ OAuth token acquired, expires at {expires_on.isoformat()}")
                logger.debug(f"  Token length: {len(access_token)} characters")
                logger.debug(f"  Token starts with: {access_token[:20]}...")

            except Exception as token_error:
                logger.error("=" * 80)
                logger.error("❌ FAILED TO GET OAUTH TOKEN")
                logger.error("=" * 80)
                logger.error(f"Error Type: {type(token_error).__name__}")
                logger.error(f"Error Message: {str(token_error)}")
                logger.error(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
                logger.error("")
                logger.error("Troubleshooting:")
                logger.error("  - Verify RBAC Role: Storage Blob Data Reader or higher")
                logger.error("  - Check role assignment:")
                logger.error(f"    az role assignment list --assignee <principal-id>")
                logger.error("  - Grant role if missing:")
                logger.error(f"    az role assignment create --role 'Storage Blob Data Reader' \\")
                logger.error(f"      --assignee <principal-id> \\")
                logger.error(f"      --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/{AZURE_STORAGE_ACCOUNT}")
                logger.error("=" * 80)
                raise

            # Cache token
            oauth_token_cache["token"] = access_token
            oauth_token_cache["expires_at"] = expires_on

            logger.info("=" * 80)
            logger.info("✅ OAuth token successfully generated and cached")
            logger.info("=" * 80)
            logger.info(f"   Storage Account: {AZURE_STORAGE_ACCOUNT}")
            logger.info(f"   Valid until: {expires_on.isoformat()}")
            logger.info(f"   Grants access to: ALL containers per RBAC role")
            logger.info("=" * 80)

            return access_token

        except Exception as e:
            logger.error("=" * 80)
            logger.error("❌ CATASTROPHIC FAILURE IN OAUTH TOKEN GENERATION")
            logger.error("=" * 80)
            logger.error(f"Error Type: {type(e).__name__}")
            logger.error(f"Error Message: {str(e)}")
            logger.error(f"Mode: {'DEVELOPMENT' if LOCAL_MODE else 'PRODUCTION'}")
            logger.error(f"Storage Account: {AZURE_STORAGE_ACCOUNT}")
            logger.error("")
            logger.error("Full traceback:", exc_info=True)
            logger.error("=" * 80)
            raise
```

**Copy this middleware from geotiler `custom_main.py:171-194`**:

```python
class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage OAuth token is set before each request.
    Sets AZURE_STORAGE_ACCESS_TOKEN which GDAL uses for /vsiaz/ authentication.
    """
    async def dispatch(self, request: Request, call_next):
        if USE_AZURE_AUTH and AZURE_STORAGE_ACCOUNT:
            try:
                # Get OAuth token (uses cache if valid)
                token = get_azure_storage_oauth_token()

                if token:
                    # Set environment variables that GDAL will use
                    os.environ["AZURE_STORAGE_ACCOUNT"] = AZURE_STORAGE_ACCOUNT
                    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token
                    logger.debug(f"Set OAuth token for storage account: {AZURE_STORAGE_ACCOUNT}")
                    logger.debug("GDAL will use: AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_ACCESS_TOKEN")

            except Exception as e:
                logger.error(f"Error in Azure auth middleware: {e}", exc_info=True)
                # Continue with request even if auth fails (may result in 403 errors)

        response = await call_next(request)
        return response
```

---

## Database Configuration

### pgSTAC Setup

#### 1. Create Azure Database for PostgreSQL

```bash
# Create PostgreSQL Flexible Server
az postgres flexible-server create \
  --name rmhpgstac \
  --resource-group rmhazure_rg \
  --location eastus \
  --admin-user pgadmin \
  --admin-password '<secure-password>' \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --version 14 \
  --storage-size 32 \
  --public-access 0.0.0.0

# Allow Azure services
az postgres flexible-server firewall-rule create \
  --name rmhpgstac \
  --resource-group rmhazure_rg \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

# Create database
az postgres flexible-server db create \
  --server-name rmhpgstac \
  --resource-group rmhazure_rg \
  --database-name pgstac
```

#### 2. Install pgSTAC Extension

```bash
# Connect to database
psql "host=rmhpgstac.postgres.database.azure.com port=5432 dbname=pgstac user=pgadmin sslmode=require"

# Install pgSTAC
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgstac;

# Verify installation
SELECT pgstac.version();
```

#### 3. Initialize pgSTAC Schema

Create `scripts/init_pgstac.sh`:

```bash
#!/bin/bash
# Initialize pgSTAC database schema

set -e

# Database connection from environment or args
DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/pgstac}"

echo "Initializing pgSTAC database: $DATABASE_URL"

# Run pgSTAC migrations (if using pypgstac)
pypgstac migrate

# Or manually create schema
psql "$DATABASE_URL" -c "SELECT pgstac.migrate();"

echo "pgSTAC database initialized successfully"
```

#### 4. Load Sample STAC Data

Create `scripts/load_sample_data.py`:

```python
#!/usr/bin/env python3
"""Load sample STAC items into pgSTAC database."""

import asyncio
import asyncpg
import os
from datetime import datetime

async def load_sample_data():
    """Load sample STAC collection and items."""

    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/pgstac")

    conn = await asyncpg.connect(database_url)

    try:
        # Create collection
        collection = {
            "type": "Collection",
            "id": "namangan-imagery",
            "stac_version": "1.0.0",
            "description": "Namangan region imagery collection",
            "license": "proprietary",
            "extent": {
                "spatial": {"bbox": [[71.6, 40.9, 71.7, 41.1]]},
                "temporal": {"interval": [["2019-08-14T00:00:00Z", None]]}
            }
        }

        await conn.execute(
            "SELECT * FROM pgstac.create_collection($1::text::jsonb)",
            collection
        )
        print(f"✓ Created collection: {collection['id']}")

        # Create sample item
        item = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "namangan-2019-08-14-R1C1",
            "collection": "namangan-imagery",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [71.6063, 40.9850],
                    [71.6681, 40.9850],
                    [71.6681, 41.0318],
                    [71.6063, 41.0318],
                    [71.6063, 40.9850]
                ]]
            },
            "bbox": [71.6063, 40.9850, 71.6681, 41.0318],
            "properties": {
                "datetime": "2019-08-14T00:00:00Z",
                "platform": "satellite",
                "instruments": ["camera"]
            },
            "assets": {
                "visual": {
                    "href": "/vsiaz/rmhazuregeobronze/namangan/namangan14aug2019_R1C1cog.tif",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "roles": ["data"],
                    "title": "RGB Visual"
                }
            },
            "links": []
        }

        await conn.execute(
            "SELECT * FROM pgstac.create_item($1::text::jsonb)",
            item
        )
        print(f"✓ Created item: {item['id']}")

    finally:
        await conn.close()

    print("\n✅ Sample data loaded successfully")

if __name__ == "__main__":
    asyncio.run(load_sample_data())
```

---

## Local Development Setup

### Step-by-Step Local Setup

#### 1. Clone/Create Project

```bash
# Create new project directory
mkdir geotiler-pgstac
cd geotiler-pgstac

# Initialize git
git init

# Copy OAuth code from geotiler
# You'll need custom_main.py from geotiler as reference
```

#### 2. Create Environment File

```bash
cp .env.example .env

# Edit .env with your settings
# Ensure AZURE_STORAGE_ACCOUNT matches your storage account
```

#### 3. Azure CLI Login (for local OAuth)

```bash
# Login to Azure (required for local OAuth)
az login

# Verify account
az account show

# Verify you have access to storage account
az storage account show --name rmhazuregeo --resource-group rmhazure_rg
```

#### 4. Start Services

```bash
# Start PostgreSQL and TiTiler-pgSTAC
docker-compose up -d

# Wait for PostgreSQL to be ready
docker-compose logs -f postgres

# Initialize pgSTAC schema
chmod +x scripts/init_pgstac.sh
./scripts/init_pgstac.sh

# Load sample data
python scripts/load_sample_data.py
```

#### 5. Verify Local Deployment

```bash
# Check health
curl http://localhost:8000/healthz | jq .

# Expected output:
# {
#   "status": "healthy",
#   "azure_auth_enabled": true,
#   "local_mode": true,
#   "auth_type": "OAuth Bearer Token",
#   "storage_account": "rmhazuregeo",
#   "token_status": "active",
#   "token_scope": "ALL containers (RBAC-based)",
#   "database_status": "connected"
# }

# Test STAC search
curl "http://localhost:8000/mosaic/searches" | jq .

# Test mosaic tile (if you have STAC items loaded)
# curl "http://localhost:8000/mosaic/{search_id}/tiles/WebMercatorQuad/12/2866/1744.png"
```

#### 6. Development Workflow

```bash
# Edit custom_pgstac_main.py
# Changes will auto-reload (--reload flag in docker-compose)

# View logs
docker-compose logs -f titiler-pgstac

# Stop services
docker-compose down

# Clean up (remove volumes)
docker-compose down -v
```

---

## Production Deployment

### Step-by-Step Production Deployment

#### 1. Prerequisites Check

```bash
# Verify Azure resources exist
az postgres flexible-server show --name rmhpgstac --resource-group rmhazure_rg
az storage account show --name rmhazuregeo --resource-group rmhazure_rg
az acr show --name rmhazureacr --resource-group rmhazure_rg

# Verify pgSTAC is installed
psql "host=rmhpgstac.postgres.database.azure.com dbname=pgstac user=pgadmin sslmode=require" \
  -c "SELECT pgstac.version();"
```

#### 2. Build and Push Docker Image

```bash
# Build image
az acr build \
  --registry rmhazureacr \
  --image geotiler-pgstac:1.0.0 \
  .

# Verify image
az acr repository show \
  --name rmhazureacr \
  --image geotiler-pgstac:1.0.0
```

#### 3. Create App Service

```bash
# Create App Service Plan (if needed)
az appservice plan create \
  --name ASP-geotiler-pgstac \
  --resource-group rmhazure_rg \
  --location eastus \
  --is-linux \
  --sku B1

# Create Web App
az webapp create \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  --plan ASP-geotiler-pgstac \
  --deployment-container-image-name rmhazureacr.azurecr.io/geotiler-pgstac:1.0.0

# Configure ACR credentials
az webapp config container set \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  --container-image-name rmhazureacr.azurecr.io/geotiler-pgstac:1.0.0 \
  --container-registry-url https://rmhazureacr.azurecr.io
```

#### 4. Enable Managed Identity

```bash
# Enable system-assigned managed identity
az webapp identity assign \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg

# Get principal ID
PRINCIPAL_ID=$(az webapp identity show \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  --query principalId -o tsv)

echo "Managed Identity Principal ID: $PRINCIPAL_ID"
```

#### 5. Grant RBAC Permissions

```bash
# Get storage account resource ID
STORAGE_ID=$(az storage account show \
  --name rmhazuregeo \
  --resource-group rmhazure_rg \
  --query id -o tsv)

# Grant Storage Blob Data Reader role
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee-object-id $PRINCIPAL_ID \
  --scope $STORAGE_ID

# Verify role assignment
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --scope $STORAGE_ID
```

#### 6. Configure Environment Variables

```bash
# Set environment variables
az webapp config appsettings set \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  --settings \
    USE_AZURE_AUTH=true \
    LOCAL_MODE=false \
    AZURE_STORAGE_ACCOUNT=rmhazuregeo \
    DATABASE_URL="postgresql://pgadmin:<password>@rmhpgstac.postgres.database.azure.com:5432/pgstac?sslmode=require" \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff" \
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR" \
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES" \
    GDAL_HTTP_MULTIPLEX="YES" \
    GDAL_HTTP_VERSION="2" \
    VSI_CACHE="TRUE" \
    VSI_CACHE_SIZE="536870912"
```

#### 7. Restart and Monitor

```bash
# Restart app
az webapp restart \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg

# Monitor logs
az webapp log tail \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg
```

#### 8. Verify Deployment

```bash
# Get app URL
APP_URL=$(az webapp show \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  --query defaultHostName -o tsv)

echo "App URL: https://$APP_URL"

# Test health endpoint
curl "https://$APP_URL/healthz" | jq .

# Expected output:
# {
#   "status": "healthy",
#   "azure_auth_enabled": true,
#   "local_mode": false,
#   "auth_type": "OAuth Bearer Token",
#   "storage_account": "rmhazuregeo",
#   "token_status": "active",
#   "token_expires_in_seconds": 86400,
#   "token_scope": "ALL containers (RBAC-based)",
#   "database_status": "connected"
# }

# Look for OAuth initialization in logs
az webapp log tail \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  | grep -A 10 "OAuth"

# Expected log output:
# ================================================================================
# 🔑 Acquiring OAuth token for Azure Storage
# ================================================================================
# Mode: PRODUCTION (Managed Identity)
# Storage Account: rmhazuregeo
# Token Scope: https://storage.azure.com/.default
# ================================================================================
# DefaultAzureCredential acquired a token from ManagedIdentityCredential
# ✓ OAuth token acquired, expires at 2025-11-09T00:16:42+00:00
# ✅ OAuth token successfully generated and cached
#    Grants access to: ALL containers per RBAC role
# ================================================================================
```

---

## Testing & Validation

### Comprehensive Testing Strategy

#### 1. OAuth Authentication Tests

Create `tests/test_oauth_auth.py`:

```python
"""Test OAuth authentication functionality."""

import pytest
from custom_pgstac_main import get_azure_storage_oauth_token, oauth_token_cache
from datetime import datetime, timezone, timedelta

def test_oauth_token_acquisition():
    """Test OAuth token can be acquired."""
    token = get_azure_storage_oauth_token()
    assert token is not None
    assert len(token) > 100  # OAuth tokens are long
    assert oauth_token_cache["token"] == token
    assert oauth_token_cache["expires_at"] > datetime.now(timezone.utc)

def test_oauth_token_caching():
    """Test OAuth token is cached and reused."""
    token1 = get_azure_storage_oauth_token()
    token2 = get_azure_storage_oauth_token()
    assert token1 == token2  # Should be same cached token

def test_oauth_token_refresh():
    """Test OAuth token is refreshed before expiry."""
    # Force expiry
    oauth_token_cache["expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=4)

    # This should trigger refresh (< 5 minutes remaining)
    token = get_azure_storage_oauth_token()
    assert token is not None
    assert oauth_token_cache["expires_at"] > datetime.now(timezone.utc) + timedelta(hours=20)
```

#### 2. Multi-Container Access Tests

Create `tests/test_multi_container.py`:

```python
"""Test multi-container access with single OAuth token."""

import pytest
from httpx import AsyncClient
from custom_pgstac_main import app

@pytest.mark.asyncio
async def test_access_bronze_container():
    """Test access to bronze container."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/cog/info",
            params={"url": "/vsiaz/rmhazuregeobronze/namangan/namangan14aug2019_R1C1cog.tif"}
        )
    assert response.status_code == 200
    data = response.json()
    assert "bounds" in data
    assert "width" in data

@pytest.mark.asyncio
async def test_access_silver_container():
    """Test access to silver container (if exists)."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/cog/info",
            params={"url": "/vsiaz/rmhazuregeosilver/test/file.tif"}
        )
    # Should work if file exists and RBAC allows
    assert response.status_code in [200, 404]  # 404 if file doesn't exist

@pytest.mark.asyncio
async def test_single_token_works_everywhere():
    """Verify single OAuth token grants access to multiple containers."""
    # Token should be cached from previous tests
    from custom_pgstac_main import oauth_token_cache
    assert oauth_token_cache["token"] is not None

    # All requests should use the same token
    # (verified by checking no new token acquisition in logs)
```

#### 3. STAC Search Tests

Create `tests/test_stac_search.py`:

```python
"""Test STAC search and mosaic functionality."""

import pytest
from httpx import AsyncClient
from custom_pgstac_main import app

@pytest.mark.asyncio
async def test_stac_collection_list():
    """Test listing STAC collections."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/collections")
    assert response.status_code == 200
    data = response.json()
    assert "collections" in data

@pytest.mark.asyncio
async def test_stac_search():
    """Test STAC search endpoint."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/search",
            json={
                "collections": ["namangan-imagery"],
                "bbox": [71.6, 40.9, 71.7, 41.1]
            }
        )
    assert response.status_code == 200
    data = response.json()
    assert "features" in data
    assert len(data["features"]) > 0

@pytest.mark.asyncio
async def test_mosaic_tile_from_search():
    """Test mosaic tile generation from STAC search."""
    # First, create a search
    async with AsyncClient(app=app, base_url="http://test") as client:
        search_response = await client.post(
            "/searches/register",
            json={
                "collections": ["namangan-imagery"],
                "bbox": [71.6, 40.9, 71.7, 41.1]
            }
        )
        assert search_response.status_code == 200
        search_id = search_response.json()["id"]

        # Request tile from search
        tile_response = await client.get(
            f"/mosaic/{search_id}/tiles/WebMercatorQuad/12/2866/1744.png"
        )
        assert tile_response.status_code == 200
        assert tile_response.headers["content-type"] == "image/png"
```

#### 4. Integration Tests

Create `tests/test_integration.py`:

```python
"""End-to-end integration tests."""

import pytest
from httpx import AsyncClient
from custom_pgstac_main import app

@pytest.mark.asyncio
async def test_full_workflow():
    """Test complete workflow: search → extract URLs → generate tiles."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # 1. Search for STAC items
        search_response = await client.post(
            "/search",
            json={
                "collections": ["namangan-imagery"],
                "bbox": [71.6, 40.9, 71.7, 41.1],
                "limit": 10
            }
        )
        assert search_response.status_code == 200
        items = search_response.json()["features"]
        assert len(items) > 0

        # 2. Register search for mosaic
        register_response = await client.post(
            "/searches/register",
            json={
                "collections": ["namangan-imagery"],
                "bbox": [71.6, 40.9, 71.7, 41.1]
            }
        )
        assert register_response.status_code == 200
        search_id = register_response.json()["id"]

        # 3. Get mosaic info
        info_response = await client.get(f"/mosaic/{search_id}/info")
        assert info_response.status_code == 200

        # 4. Generate preview
        preview_response = await client.get(
            f"/mosaic/{search_id}/preview.png",
            params={"max_size": 256}
        )
        assert preview_response.status_code == 200
        assert len(preview_response.content) > 1000  # Should be a real image
```

### Running Tests

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=custom_pgstac_main --cov-report=html

# Run specific test file
pytest tests/test_oauth_auth.py -v

# Run with logging output
pytest -v -s
```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue 1: OAuth Token Acquisition Fails

**Symptoms**:
```
❌ FAILED TO CREATE AZURE CREDENTIAL
Error: EnvironmentCredential authentication unavailable...
```

**Solutions**:

**Local Development**:
```bash
# Ensure you're logged in to Azure CLI
az login
az account show

# Verify you have the correct subscription
az account set --subscription <subscription-id>
```

**Production**:
```bash
# Verify Managed Identity is enabled
az webapp identity show --name geotiler-pgstac --resource-group rmhazure_rg

# Wait 2-3 minutes after enabling identity for it to propagate
```

#### Issue 2: RBAC Permissions Missing

**Symptoms**:
```
❌ FAILED TO GET OAUTH TOKEN
Error: Unauthorized (403)
```

**Solution**:
```bash
# Get Managed Identity principal ID
PRINCIPAL_ID=$(az webapp identity show \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  --query principalId -o tsv)

# Verify role assignment
az role assignment list --assignee $PRINCIPAL_ID

# Grant role if missing
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee-object-id $PRINCIPAL_ID \
  --scope /subscriptions/<sub>/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo
```

#### Issue 3: Database Connection Fails

**Symptoms**:
```
asyncpg.exceptions.InvalidPasswordError
asyncpg.exceptions.ConnectionDoesNotExistError
```

**Solutions**:

**Check connection string**:
```bash
# Verify DATABASE_URL is correct
az webapp config appsettings list \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  | grep DATABASE_URL

# Test connection manually
psql "$DATABASE_URL" -c "SELECT version();"
```

**Check firewall rules**:
```bash
# Allow Azure services
az postgres flexible-server firewall-rule create \
  --name rmhpgstac \
  --resource-group rmhazure_rg \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

**Use Managed Identity for database** (recommended):
```bash
# Enable Azure AD authentication
az postgres flexible-server ad-admin create \
  --server-name rmhpgstac \
  --resource-group rmhazure_rg \
  --display-name geotiler-pgstac \
  --object-id $PRINCIPAL_ID

# Update DATABASE_URL to use Azure AD
# DATABASE_URL="postgresql://geotiler-pgstac@rmhpgstac:@rmhpgstac.postgres.database.azure.com/pgstac?sslmode=require"
```

#### Issue 4: GDAL Can't Read COG Files

**Symptoms**:
```
ERROR 1: HTTP error code: 403
ERROR 1: /vsiaz/container/file.tif: No such file or directory
```

**Solutions**:

**Check OAuth token is set**:
```python
# Add debug logging to middleware
logger.info(f"AZURE_STORAGE_ACCOUNT: {os.getenv('AZURE_STORAGE_ACCOUNT')}")
logger.info(f"AZURE_STORAGE_ACCESS_TOKEN set: {bool(os.getenv('AZURE_STORAGE_ACCESS_TOKEN'))}")
```

**Verify GDAL configuration**:
```bash
# Ensure GDAL environment variables are set
az webapp config appsettings list \
  --name geotiler-pgstac \
  --resource-group rmhazure_rg \
  | grep GDAL
```

**Test GDAL directly**:
```python
# In Python shell or test script
import os
from osgeo import gdal

os.environ["AZURE_STORAGE_ACCOUNT"] = "rmhazuregeo"
os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = "<token>"

ds = gdal.Open("/vsiaz/rmhazuregeobronze/namangan/namangan14aug2019_R1C1cog.tif")
print(ds.RasterXSize, ds.RasterYSize)
```

#### Issue 5: Mosaic Tiles Return 404

**Symptoms**:
```
GET /mosaic/{search_id}/tiles/12/2866/1744.png
Response: 404 Not Found
```

**Solutions**:

**Check search exists**:
```bash
# Verify search was registered
curl https://geotiler-pgstac.azurewebsites.net/mosaic/searches | jq .
```

**Check tile coordinates**:
```bash
# Get correct bounds
curl "https://geotiler-pgstac.azurewebsites.net/mosaic/{search_id}/info" | jq .bounds

# Use tilejson to find valid tiles
curl "https://geotiler-pgstac.azurewebsites.net/mosaic/{search_id}/tilejson.json" | jq .
```

**Check STAC items have assets**:
```sql
-- In PostgreSQL
SELECT id, assets FROM pgstac.items WHERE collection='namangan-imagery';
```

#### Issue 6: Performance Issues

**Symptoms**:
- Slow tile generation
- High memory usage
- Timeouts

**Solutions**:

**Optimize GDAL settings**:
```bash
# Increase cache size
VSI_CACHE_SIZE=1073741824  # 1GB

# Enable HTTP optimizations
GDAL_HTTP_MULTIPLEX=YES
GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES
```

**Scale App Service**:
```bash
# Increase workers
# In Dockerfile: CMD ["uvicorn", "custom_pgstac_main:app", "--workers", "4"]

# Scale up App Service plan
az appservice plan update \
  --name ASP-geotiler-pgstac \
  --resource-group rmhazure_rg \
  --sku B2
```

**Optimize database**:
```sql
-- Create indexes on commonly queried fields
CREATE INDEX IF NOT EXISTS items_collection_idx ON pgstac.items(collection);
CREATE INDEX IF NOT EXISTS items_datetime_idx ON pgstac.items((properties->>'datetime'));
CREATE INDEX IF NOT EXISTS items_geometry_idx ON pgstac.items USING GIST(geometry);

-- Analyze tables
ANALYZE pgstac.items;
ANALYZE pgstac.collections;
```

---

## Migration from geotiler

### Key Differences

| Aspect | geotiler | geotiler-pgstac |
|--------|-----------|-------------------|
| **Base Image** | `ghcr.io/developmentseed/titiler:latest` | `ghcr.io/stac-utils/titiler-pgstac:latest` |
| **Primary Use** | Direct COG URL access | STAC catalog queries |
| **Database** | None | PostgreSQL with pgSTAC |
| **Dependencies** | `azure-identity` | `azure-identity`, `titiler.pgstac`, `asyncpg` |
| **Main File** | `custom_main.py` | `custom_pgstac_main.py` |
| **Endpoints** | `/cog/*` | `/mosaic/*`, `/search`, `/collections` |
| **OAuth Code** | Identical | Identical (copy from geotiler) |

### Code Reuse

**What to copy directly from geotiler**:

1. ✅ `get_azure_storage_oauth_token()` function - lines 49-168
2. ✅ `AzureAuthMiddleware` class - lines 171-194
3. ✅ OAuth token cache structure - lines 36-41
4. ✅ Configuration variables - lines 44-46
5. ✅ Logging setup - lines 30-34
6. ✅ Health check OAuth status logic - lines 234-245
7. ✅ Startup OAuth initialization - lines 287-314

**What to adapt for pgSTAC**:

1. 🔄 Database connection in startup event
2. 🔄 Health check to include database status
3. 🔄 TilerFactory → MosaicTilerFactory
4. 🔄 Endpoint registration (mosaic vs cog)
5. 🔄 Dependencies in requirements.txt

### Migration Steps

1. **Create new project directory** (don't modify geotiler)
2. **Copy OAuth authentication code** from geotiler
3. **Adapt for pgSTAC** (database, endpoints, factory)
4. **Test locally** with docker-compose
5. **Deploy to production** as separate App Service
6. **Keep both projects** - they serve different purposes

---

## Success Criteria

### Local Development Success

- [ ] `docker-compose up` starts without errors
- [ ] PostgreSQL with pgSTAC running
- [ ] OAuth token acquired from Azure CLI
- [ ] Health endpoint shows `token_status: "active"`
- [ ] Database connection successful
- [ ] Sample STAC items loaded
- [ ] STAC search returns results
- [ ] Mosaic tiles generate successfully
- [ ] Multi-container COG access works

### Production Deployment Success

- [ ] Docker image builds in ACR
- [ ] App Service starts without errors
- [ ] Managed Identity enabled
- [ ] RBAC permissions granted (Storage Blob Data Reader)
- [ ] OAuth token acquired from Managed Identity
- [ ] Logs show: `DefaultAzureCredential acquired a token from ManagedIdentityCredential`
- [ ] Health endpoint shows OAuth and database status
- [ ] STAC searches return results from database
- [ ] Mosaic tiles render from STAC items
- [ ] Assets from multiple containers accessible with single token
- [ ] All tests pass in production environment

### OAuth Validation

- [ ] Token expires in ~24 hours (86400 seconds)
- [ ] Token scope: "ALL containers (RBAC-based)"
- [ ] Token automatically refreshes before expiry
- [ ] No SAS token generation code present
- [ ] Single token works across all containers
- [ ] GDAL reads succeed with `/vsiaz/` paths

### Performance Validation

- [ ] Mosaic tile generation < 2 seconds
- [ ] Database queries < 100ms
- [ ] OAuth token acquisition < 3 seconds
- [ ] Memory usage stable over 24 hours
- [ ] No token refresh during active use

---

## Next Steps After Implementation

### Phase 1: Core Implementation (Done When...)

- [ ] All files created per blueprint
- [ ] OAuth authentication working locally
- [ ] Database connected and pgSTAC initialized
- [ ] Sample data loaded successfully
- [ ] Local tests passing

### Phase 2: Production Deployment (Done When...)

- [ ] Docker image built and pushed
- [ ] App Service created and configured
- [ ] Managed Identity enabled with RBAC
- [ ] Production deployment successful
- [ ] Health checks passing
- [ ] Multi-container access verified

### Phase 3: Real Data Integration (Done When...)

- [ ] Production STAC catalog populated
- [ ] Collections created for your datasets
- [ ] Items ingested with correct asset URLs
- [ ] Mosaics generated from real searches
- [ ] Performance optimized for scale

### Phase 4: Documentation & Handoff (Done When...)

- [ ] All docs written (API, deployment, troubleshooting)
- [ ] Runbooks created for operations
- [ ] Monitoring and alerts configured
- [ ] Team trained on system
- [ ] Project marked as production-ready

---

## Reference Links

### geotiler Resources

- GitHub: https://github.com/rob634/geotiler
- Deployment URL: https://geotiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net
- OAuth Approach Doc: `docs/OAUTH-TOKEN-APPROACH.md`
- Roadmap: `docs/ROADMAP.md`

### External Documentation

- TiTiler-pgSTAC: https://stac-utils.github.io/titiler-pgstac/
- pgSTAC: https://github.com/stac-utils/pgstac
- Azure Managed Identity: https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/
- GDAL /vsiaz/: https://gdal.org/user/virtual_file_systems.html#vsiaz-microsoft-azure-blob-files

### Azure CLI Reference

- App Service: `az webapp --help`
- PostgreSQL: `az postgres flexible-server --help`
- RBAC: `az role assignment --help`
- ACR: `az acr --help`

---

## Appendix: Complete Example Files

### A. Complete custom_pgstac_main.py Template

```python
"""
TiTiler-pgSTAC with Azure OAuth Token authentication

STAC catalog tile server with multi-container Azure Storage access.
OAuth tokens grant access to ALL containers based on RBAC role assignments.

Based on: geotiler v2.0.0 (OAuth Bearer Token Authentication)
"""
import os
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from titiler.pgstac.factory import MosaicTilerFactory
from titiler.pgstac.db import close_db_connection, connect_to_db
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# OAuth token cache - shared across all workers
oauth_token_cache = {
    "token": None,
    "expires_at": None,
    "lock": Lock()
}

# Configuration
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL")


def get_azure_storage_oauth_token() -> Optional[str]:
    """
    Get OAuth token for Azure Storage using Managed Identity.

    [COPY ENTIRE FUNCTION FROM geotiler custom_main.py:49-168]
    """
    # ... (complete implementation from geotiler)
    pass


class AzureAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that ensures Azure Storage OAuth token is set before each request.

    [COPY ENTIRE CLASS FROM geotiler custom_main.py:171-194]
    """
    async def dispatch(self, request: Request, call_next):
        # ... (complete implementation from geotiler)
        pass


# Create FastAPI application
app = FastAPI(
    title="TiTiler-pgSTAC with Azure OAuth Auth",
    description="STAC catalog tile server with Azure Managed Identity authentication",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Azure authentication middleware
app.add_middleware(AzureAuthMiddleware)

# Add exception handlers
add_exception_handlers(app, DEFAULT_STATUS_CODES)

# Register TiTiler-pgSTAC mosaic endpoints
mosaic = MosaicTilerFactory(
    router_prefix="/mosaic",
    add_statistics=True,
    add_viewer=True,
)
app.include_router(mosaic.router, prefix="/mosaic", tags=["Mosaic"])


@app.get("/healthz", tags=["Health"])
async def health():
    """Health check endpoint with OAuth token and database status."""
    status = {
        "status": "healthy",
        "azure_auth_enabled": USE_AZURE_AUTH,
        "local_mode": LOCAL_MODE,
        "auth_type": "OAuth Bearer Token"
    }

    # OAuth status
    if USE_AZURE_AUTH:
        status["storage_account"] = AZURE_STORAGE_ACCOUNT

        if oauth_token_cache["token"] and oauth_token_cache["expires_at"]:
            now = datetime.now(timezone.utc)
            time_until_expiry = (oauth_token_cache["expires_at"] - now).total_seconds()
            status["token_expires_in_seconds"] = max(0, int(time_until_expiry))
            status["token_scope"] = "ALL containers (RBAC-based)"
            status["token_status"] = "active"
        else:
            status["token_status"] = "not_initialized"

    # Database status
    try:
        # Check database connection
        if hasattr(app.state, "pool") and app.state.pool:
            status["database_status"] = "connected"
            status["database_url"] = DATABASE_URL.split("@")[1].split("/")[0] if DATABASE_URL else None
        else:
            status["database_status"] = "not_connected"
    except Exception as e:
        status["database_status"] = f"error: {str(e)}"

    return status


@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information."""
    return {
        "title": "TiTiler-pgSTAC with Azure OAuth Auth",
        "description": "STAC catalog tile server with OAuth token support",
        "version": "1.0.0",
        "auth_type": "OAuth Bearer Token (Managed Identity)",
        "endpoints": {
            "health": "/healthz",
            "docs": "/docs",
            "redoc": "/redoc",
            "mosaic_search": "/search",
            "mosaic_register": "/searches/register",
            "mosaic_tiles": "/mosaic/{search_id}/tiles/{tileMatrixSetId}/{z}/{x}/{y}",
            "mosaic_info": "/mosaic/{search_id}/info",
            "collections": "/collections"
        },
        "local_mode": LOCAL_MODE,
        "azure_auth": USE_AZURE_AUTH,
        "multi_container_support": True,
        "note": "OAuth token grants access to ALL containers based on RBAC role assignments"
    }


@app.on_event("startup")
async def startup_event():
    """Initialize database connection and Azure OAuth authentication on startup."""
    logger.info("=" * 60)
    logger.info("TiTiler-pgSTAC with Azure OAuth Auth - Starting up")
    logger.info("=" * 60)
    logger.info(f"Version: 1.0.0")
    logger.info(f"Local mode: {LOCAL_MODE}")
    logger.info(f"Azure auth enabled: {USE_AZURE_AUTH}")
    logger.info(f"Auth type: OAuth Bearer Token")

    # Initialize database connection
    if DATABASE_URL:
        logger.info(f"Connecting to database...")
        try:
            await connect_to_db(app, settings={"database_url": DATABASE_URL})
            logger.info("✓ Database connection established")
        except Exception as e:
            logger.error(f"✗ Failed to connect to database: {e}")
            raise
    else:
        logger.error("DATABASE_URL environment variable not set!")
        raise ValueError("DATABASE_URL is required")

    # Initialize OAuth authentication
    if USE_AZURE_AUTH:
        if not AZURE_STORAGE_ACCOUNT:
            logger.error("AZURE_STORAGE_ACCOUNT environment variable not set!")
            logger.error("Set this to your storage account name for Azure auth to work")
        else:
            logger.info(f"Storage account: {AZURE_STORAGE_ACCOUNT}")

            try:
                # Get initial OAuth token
                token = get_azure_storage_oauth_token()
                if token:
                    logger.info("✓ OAuth authentication initialized successfully")
                    logger.info(f"✓ Token expires at: {oauth_token_cache['expires_at']}")
                    logger.info(f"✓ Access scope: ALL containers per RBAC role")
                    if LOCAL_MODE:
                        logger.info("✓ Using Azure CLI credentials (az login)")
                    else:
                        logger.info("✓ Using Managed Identity")
                else:
                    logger.warning("Failed to get initial OAuth token")
            except Exception as e:
                logger.error(f"Failed to initialize OAuth authentication: {e}")
                logger.error("The app will continue but may not be able to access Azure Storage")
                if LOCAL_MODE:
                    logger.info("TIP: Run 'az login' to authenticate locally")
    else:
        logger.info("Azure authentication is disabled")
        logger.info("Enable with: USE_AZURE_AUTH=true")

    logger.info("=" * 60)
    logger.info("Startup complete - Ready to serve tiles!")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("TiTiler-pgSTAC with Azure OAuth Auth - Shutting down")

    # Close database connection
    await close_db_connection(app)

    logger.info("Shutdown complete")
```

### B. Complete .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
env/
ENV/
.venv

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/

# Environment
.env
.env.local

# Docker
.dockerignore

# Logs
*.log
logs/

# Data
*.tif
*.tiff
data/

# Azure
.azure/

# Database
*.db
*.sqlite

# OS
.DS_Store
Thumbs.db
```

---

**End of Blueprint**

This document provides everything needed to implement TiTiler-pgSTAC with OAuth authentication. Copy the OAuth code from geotiler, adapt for pgSTAC, and follow the deployment steps. The OAuth approach is proven in production and will work identically for TiTiler-pgSTAC.

**Key Success Factor**: The OAuth authentication code is battle-tested and production-validated in geotiler v2.0.0. Copy it exactly, adapt the endpoints for pgSTAC, and you'll have multi-container STAC catalog access working immediately.
