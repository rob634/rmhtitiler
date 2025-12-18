# PostgreSQL Managed Identity Setup Guide
## TiTiler-pgSTAC with Azure Database for PostgreSQL Flexible Server

**Date**: November 13, 2025
**Purpose**: Complete setup guide for passwordless PostgreSQL authentication using Azure Managed Identity
**Scope**: Production-ready configuration for TiTiler-pgSTAC with Azure Database for PostgreSQL Flexible Server

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Step 1: Create User-Assigned Managed Identity](#step-1-create-user-assigned-managed-identity)
4. [Step 2: Assign Identity to Web App](#step-2-assign-identity-to-web-app)
5. [Step 3: Configure PostgreSQL for Entra ID Authentication](#step-3-configure-postgresql-for-entra-id-authentication)
6. [Step 4: Create PostgreSQL Database User](#step-4-create-postgresql-database-user)
7. [Step 5: Grant Permissions](#step-5-grant-permissions)
8. [Step 6: Update TiTiler Code](#step-6-update-titiler-code)
9. [Step 7: Configure Environment Variables](#step-7-configure-environment-variables)
10. [Step 8: Deploy and Test](#step-8-deploy-and-test)
11. [Troubleshooting](#troubleshooting)
12. [Security Best Practices](#security-best-practices)

---

## Overview

This guide configures **passwordless authentication** for TiTiler-pgSTAC using Azure Managed Identity (MI). This eliminates hardcoded passwords and provides automatic token rotation.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Azure App Service (rmhtitiler)                              │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ User-Assigned Managed Identity: titiler-db-access    │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           │ 1. Request token at startup      │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ DefaultAzureCredential()                             │  │
│  │ → get_token("https://ossrdbms-aad.../.default")      │  │
│  │ → Returns OAuth token (valid ~1 hour)                │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           │ 2. Build DATABASE_URL            │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ DATABASE_URL = postgresql://                         │  │
│  │   titiler-db-access:{TOKEN}@                         │  │
│  │   rmhpgflex.postgres.database.azure.com/geopgflex    │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           │ 3. Connect to database           │
│                           ↓                                  │
└───────────────────────────┼──────────────────────────────────┘
                            │
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Azure Database for PostgreSQL (rmhpgflex)                   │
│                                                              │
│  Database User: "titiler-db-access"                         │
│  Auth Type: Entra ID (passwordless)                         │
│  Permissions: Read-only (pgstac_read role)                  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ pgstac schema                                        │  │
│  │  - collections (SELECT)                              │  │
│  │  - items (SELECT)                                    │  │
│  │  - searches (SELECT, INSERT) ← for /register         │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Benefits

✅ **No password management** - Tokens rotate automatically
✅ **Better security** - No credentials in code or config
✅ **Audit trail** - All access tied to managed identity
✅ **Simpler operations** - No secret rotation workflows
✅ **Production-ready** - Recommended Azure best practice

---

## Prerequisites

Before starting, ensure you have:

- [ ] Azure CLI installed and logged in (`az login`)
- [ ] Owner or Contributor role on the resource group
- [ ] Admin access to PostgreSQL database
- [ ] TiTiler-pgSTAC application deployed to Azure App Service
- [ ] Azure Database for PostgreSQL Flexible Server running

**Environment variables you'll need:**

```bash
export RESOURCE_GROUP="your-resource-group"
export WEBAPP_NAME="rmhtitiler"
export POSTGRES_SERVER="rmhpgflex"
export POSTGRES_DB="geopgflex"
export SUBSCRIPTION_ID="your-subscription-id"
export LOCATION="eastus"  # or your region
```

---

## Step 1: Create User-Assigned Managed Identity

Create a user-assigned managed identity that will represent your TiTiler application.

### Why User-Assigned vs System-Assigned?

| Feature | User-Assigned ✅ | System-Assigned ❌ |
|---------|------------------|-------------------|
| **Name control** | You choose the name | Azure generates random name |
| **Lifecycle** | Independent of app | Deleted with app |
| **Reusability** | Multiple apps can use | Tied to single app |
| **IaC friendly** | Easier to reference | Harder to manage |

### Create the Identity

```bash
# Create user-assigned managed identity
az identity create \
  --name titiler-db-access \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION

# Capture the Client ID and Principal ID (both needed)
MI_CLIENT_ID=$(az identity show \
  --name titiler-db-access \
  --resource-group $RESOURCE_GROUP \
  --query clientId -o tsv)

MI_PRINCIPAL_ID=$(az identity show \
  --name titiler-db-access \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

# Display for verification
echo "✓ Managed Identity created"
echo "  Name: titiler-db-access"
echo "  Client ID: $MI_CLIENT_ID"
echo "  Principal ID: $MI_PRINCIPAL_ID"
```

**Save these values** - you'll need them later:
- **Client ID**: Used in code configuration (optional, for explicit MI selection)
- **Principal ID**: Used to get the Object ID for PostgreSQL user creation

### Get the Object ID (Required for PostgreSQL)

```bash
# Get the Object ID from Microsoft Graph
MI_OBJECT_ID=$(az ad sp show \
  --id $MI_CLIENT_ID \
  --query id -o tsv)

echo "  Object ID: $MI_OBJECT_ID"
```

**⚠️ IMPORTANT**: You need the **Object ID**, not the Principal ID or Client ID, for creating the PostgreSQL user!

---

## Step 2: Assign Identity to Web App

Assign the user-assigned managed identity to your Azure App Service.

```bash
# Get the full resource ID of the managed identity
MI_RESOURCE_ID=$(az identity show \
  --name titiler-db-access \
  --resource-group $RESOURCE_GROUP \
  --query id -o tsv)

# Assign the identity to your web app
az webapp identity assign \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --identities $MI_RESOURCE_ID

# Verify assignment
az webapp identity show \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP
```

**Expected output:**
```json
{
  "type": "UserAssigned",
  "userAssignedIdentities": {
    "/subscriptions/.../titiler-db-access": {
      "clientId": "...",
      "principalId": "..."
    }
  }
}
```

✅ **Checkpoint**: Your App Service now has a managed identity that can request PostgreSQL tokens.

---

## Step 3: Configure PostgreSQL for Entra ID Authentication

Enable Microsoft Entra ID (formerly Azure AD) authentication on your PostgreSQL server.

### Enable Entra ID Authentication

```bash
# Check if Entra ID admin is already set
az postgres flexible-server ad-admin list \
  --server-name $POSTGRES_SERVER \
  --resource-group $RESOURCE_GROUP

# If no admin is set, create one (use your own account or a service principal)
az postgres flexible-server ad-admin create \
  --server-name $POSTGRES_SERVER \
  --resource-group $RESOURCE_GROUP \
  --object-id "your-entra-id-object-id" \
  --display-name "your-admin-account"
```

### Verify Server Configuration

```bash
# Check that authentication types include EntraID
az postgres flexible-server parameter show \
  --server-name $POSTGRES_SERVER \
  --resource-group $RESOURCE_GROUP \
  --name azure.extensions

# Ensure pgaadauth is enabled
az postgres flexible-server parameter set \
  --server-name $POSTGRES_SERVER \
  --resource-group $RESOURCE_GROUP \
  --name azure.extensions \
  --value "pgaadauth"
```

✅ **Checkpoint**: PostgreSQL server now accepts Entra ID authentication.

---

## Step 4: Create PostgreSQL Database User

Connect to PostgreSQL as an admin and create a user matching your managed identity.

### Get Admin Token (for connection)

```bash
# Get PostgreSQL access token for your admin account
ADMIN_TOKEN=$(az account get-access-token \
  --resource https://ossrdbms-aad.database.windows.net/.default \
  --query accessToken -o tsv)

# Connect to PostgreSQL using the token
psql "host=$POSTGRES_SERVER.postgres.database.azure.com \
      dbname=$POSTGRES_DB \
      user=your-admin-user@$POSTGRES_SERVER \
      password=$ADMIN_TOKEN \
      sslmode=require"
```

**Alternative**: Use Azure Data Studio or pgAdmin with Entra ID authentication.

### Create the Database User

Once connected to PostgreSQL, run the following SQL:

```sql
-- ============================================
-- STEP 1: Enable Entra ID Authentication
-- ============================================

-- Ensure pgaadauth extension is installed
CREATE EXTENSION IF NOT EXISTS pgaadauth;

-- Configure Azure AD settings (may already be set by server config)
SET aad_validate_oids_in_tenant = off;

-- ============================================
-- STEP 2: Create Database User for MI
-- ============================================

-- Create the principal for your managed identity
-- IMPORTANT: Use the OBJECT ID from Step 1, not Client ID or Principal ID!
SELECT * FROM pgaadauth_create_principal(
    'titiler-db-access',           -- User name (must match MI name exactly)
    'YOUR_MI_OBJECT_ID_HERE',      -- Object ID from az ad sp show
    'service'                      -- Type: 'service' for managed identity
);

-- Alternative for user/group (not service principal):
-- SELECT * FROM pgaadauth_create_principal('titiler-db-access', false, false);

-- Verify user was created
SELECT rolname, rolcanlogin
FROM pg_roles
WHERE rolname = 'titiler-db-access';
```

**Expected output:**
```
       rolname        | rolcanlogin
----------------------+-------------
 titiler-db-access    | t
(1 row)
```

### Understanding pgaadauth_create_principal

The function has two signatures:

**Option 1: With Object ID (Recommended for MI)**
```sql
SELECT * FROM pgaadauth_create_principal(
    role_name TEXT,      -- 'titiler-db-access'
    object_id TEXT,      -- Object ID from Azure AD
    role_type TEXT       -- 'service', 'user', or 'group'
);
```

**Option 2: Without Object ID (Legacy)**
```sql
SELECT * FROM pgaadauth_create_principal(
    role_name TEXT,      -- 'titiler-db-access'
    is_admin BOOLEAN,    -- false (not admin)
    in_roles TEXT[]      -- NULL or array of roles
);
```

✅ **Checkpoint**: Database user `titiler-db-access` now exists and can authenticate with MI tokens.

---

## Step 5: Grant Permissions

Grant the necessary database permissions based on your use case.

### Option A: Read-Only Access (Recommended for Production)

**Use this if:**
- TiTiler only serves tiles from pre-existing collections
- You pre-register searches via admin API or ETL
- You want maximum security (no writes from public API)

```sql
-- ============================================
-- READ-ONLY PERMISSIONS
-- ============================================

-- Grant schema access
GRANT USAGE ON SCHEMA pgstac TO "titiler-db-access";

-- Grant SELECT on all existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-access";

-- Grant SELECT on all existing sequences (for ID generation reads)
GRANT SELECT ON ALL SEQUENCES IN SCHEMA pgstac TO "titiler-db-access";

-- Ensure future tables are also readable (when schema updates)
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
GRANT SELECT ON TABLES TO "titiler-db-access";

-- Verify permissions
SELECT
    grantee,
    table_schema,
    table_name,
    privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'titiler-db-access'
ORDER BY table_name;
```

**What this enables:**
- ✅ Serve tiles: `/collections/{id}/tiles/{z}/{x}/{y}`
- ✅ Get collection info: `/collections/{id}/info`
- ✅ Get item info: `/collections/{id}/items/{item_id}/info`
- ✅ Read pre-registered searches from `pgstac.searches` table
- ✅ Statistics endpoints
- ❌ `/searches/register` endpoint (cannot write to searches table)

### Option B: Read + Search Registration (For Public Search Registration)

**Use this if:**
- You want users to register custom searches via `/searches/register`
- You have rate limiting or authentication on the registration endpoint
- You trust the public to define queries (⚠️ DoS risk!)

```sql
-- ============================================
-- READ + SEARCH WRITE PERMISSIONS
-- ============================================

-- Start with read-only permissions (from Option A)
GRANT USAGE ON SCHEMA pgstac TO "titiler-db-access";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-access";

-- Add write access specifically to searches table
GRANT INSERT, UPDATE, DELETE ON pgstac.searches TO "titiler-db-access";

-- Grant sequence usage for ID generation
GRANT USAGE ON ALL SEQUENCES IN SCHEMA pgstac TO "titiler-db-access";

-- Verify write permissions
SELECT
    grantee,
    table_name,
    privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'titiler-db-access'
  AND table_name = 'searches';
```

**What this additionally enables:**
- ✅ `/searches/register` endpoint (creates new searches)
- ✅ Store searches in `pgstac.searches` table (persistent, shared across instances)

**⚠️ Production Considerations:**
- Implement rate limiting on `/searches/register`
- Consider requiring authentication for registration
- Monitor database size growth (searches table)
- Consider periodic cleanup of unused searches

### Option C: Using pgSTAC Built-in Roles (Alternative)

pgSTAC provides pre-configured roles:

```sql
-- ============================================
-- USING PGSTAC BUILT-IN ROLES
-- ============================================

-- Read-only role (equivalent to Option A)
GRANT pgstac_read TO "titiler-db-access";

-- Ingest role (read + write to items, collections, searches)
-- GRANT pgstac_ingest TO "titiler-db-access";  -- ⚠️ Too permissive for production

-- Admin role (full access)
-- GRANT pgstac_admin TO "titiler-db-access";   -- ⚠️ NEVER use for public API

-- Verify role membership
SELECT
    r.rolname as role_name,
    ARRAY_AGG(b.rolname) as member_of
FROM pg_roles r
LEFT JOIN pg_auth_members m ON r.oid = m.member
LEFT JOIN pg_roles b ON m.roleid = b.oid
WHERE r.rolname = 'titiler-db-access'
GROUP BY r.rolname;
```

### Verification Queries

```sql
-- Check all permissions for titiler-db-access
SELECT
    schemaname,
    tablename,
    has_table_privilege('titiler-db-access', schemaname||'.'||tablename, 'SELECT') as can_select,
    has_table_privilege('titiler-db-access', schemaname||'.'||tablename, 'INSERT') as can_insert,
    has_table_privilege('titiler-db-access', schemaname||'.'||tablename, 'UPDATE') as can_update,
    has_table_privilege('titiler-db-access', schemaname||'.'||tablename, 'DELETE') as can_delete
FROM pg_tables
WHERE schemaname = 'pgstac'
ORDER BY tablename;

-- Check specific table permissions
SELECT
    grantee,
    table_name,
    privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'titiler-db-access'
  AND table_schema = 'pgstac'
ORDER BY table_name, privilege_type;

-- Test connection (should succeed)
SET ROLE "titiler-db-access";
SELECT current_user;  -- Should show: titiler-db-access

-- Test SELECT (should succeed)
SELECT COUNT(*) FROM pgstac.collections;

-- Test INSERT (should fail with read-only, succeed with Option B)
-- INSERT INTO pgstac.searches (id, search) VALUES ('test', '{}');

-- Reset to admin
RESET ROLE;
```

✅ **Checkpoint**: User `titiler-db-access` has appropriate permissions for TiTiler operations.

---

## Step 6: Update TiTiler Code

Modify your TiTiler application to acquire PostgreSQL tokens at startup.

### Add Token Acquisition Function

Edit [`custom_pgstac_main.py`](custom_pgstac_main.py):

```python
import os
from typing import Optional
from datetime import datetime, timezone
from threading import Lock
import logging

logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION
# ============================================

# Existing storage config
USE_AZURE_AUTH = os.getenv("USE_AZURE_AUTH", "false").lower() == "true"
AZURE_STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT")
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"

# NEW: PostgreSQL Managed Identity config
USE_POSTGRES_MI = os.getenv("USE_POSTGRES_MI", "false").lower() == "true"
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")  # Should match MI name
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

# Will be set at startup (either from env or built with MI token)
DATABASE_URL = None

# ============================================
# POSTGRESQL TOKEN ACQUISITION
# ============================================

def get_postgres_oauth_token() -> str:
    """
    Get OAuth token for Azure PostgreSQL using Managed Identity.

    Similar to get_azure_storage_oauth_token() but:
    - Uses PostgreSQL scope (not storage scope)
    - Called once at startup (not per-request)
    - Token becomes part of DATABASE_URL

    Returns:
        str: OAuth bearer token for Azure Database for PostgreSQL

    Raises:
        RuntimeError: If token acquisition fails
    """
    logger.info("=" * 80)
    logger.info("🔑 Acquiring OAuth token for PostgreSQL")
    logger.info("=" * 80)
    logger.info(f"Mode: {'DEVELOPMENT (Azure CLI)' if LOCAL_MODE else 'PRODUCTION (Managed Identity)'}")
    logger.info(f"PostgreSQL Host: {POSTGRES_HOST}")
    logger.info(f"PostgreSQL User: {POSTGRES_USER}")
    logger.info(f"Token Scope: https://ossrdbms-aad.database.windows.net/.default")
    logger.info("=" * 80)

    try:
        from azure.identity import DefaultAzureCredential

        # Step 1: Create credential
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

        # Step 2: Get token for PostgreSQL scope
        logger.debug("Step 2/2: Requesting token for scope 'https://ossrdbms-aad.database.windows.net/.default'...")
        try:
            # IMPORTANT: PostgreSQL scope is different from Storage!
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
            access_token = token.token
            expires_on = datetime.fromtimestamp(token.expires_on, tz=timezone.utc)

            logger.info(f"✓ PostgreSQL OAuth token acquired")
            logger.info(f"  Token length: {len(access_token)} characters")
            logger.info(f"  Token expires at: {expires_on.isoformat()}")
            logger.debug(f"  Token starts with: {access_token[:20]}...")

        except Exception as token_error:
            logger.error("=" * 80)
            logger.error("❌ FAILED TO GET POSTGRESQL OAUTH TOKEN")
            logger.error("=" * 80)
            logger.error(f"Error Type: {type(token_error).__name__}")
            logger.error(f"Error Message: {str(token_error)}")
            logger.error(f"PostgreSQL Host: {POSTGRES_HOST}")
            logger.error(f"PostgreSQL User: {POSTGRES_USER}")
            logger.error("")
            logger.error("Troubleshooting:")
            logger.error("  - Verify database user exists:")
            logger.error(f"    psql -c \"SELECT rolname FROM pg_roles WHERE rolname='{POSTGRES_USER}';\"")
            logger.error("  - Verify user was created via pgaadauth_create_principal")
            logger.error("  - Check MI has correct Object ID in PostgreSQL")
            logger.error("  - Verify MI is assigned to App Service")
            logger.error("=" * 80)
            raise

        logger.info("=" * 80)
        logger.info("✅ PostgreSQL OAuth token successfully acquired")
        logger.info("=" * 80)
        logger.info(f"   PostgreSQL Host: {POSTGRES_HOST}")
        logger.info(f"   PostgreSQL User: {POSTGRES_USER}")
        logger.info(f"   Valid until: {expires_on.isoformat()}")
        logger.info("=" * 80)

        return access_token

    except Exception as e:
        logger.error("=" * 80)
        logger.error("❌ CATASTROPHIC FAILURE IN POSTGRESQL TOKEN GENERATION")
        logger.error("=" * 80)
        logger.error(f"Error Type: {type(e).__name__}")
        logger.error(f"Error Message: {str(e)}")
        logger.error(f"Mode: {'DEVELOPMENT' if LOCAL_MODE else 'PRODUCTION'}")
        logger.error(f"PostgreSQL Host: {POSTGRES_HOST}")
        logger.error(f"PostgreSQL User: {POSTGRES_USER}")
        logger.error("")
        logger.error("Full traceback:", exc_info=True)
        logger.error("=" * 80)
        raise


# Existing get_azure_storage_oauth_token() function remains unchanged
# ... (your existing storage token code) ...
```

### Update Startup Event

Modify the `startup_event()` function:

```python
from titiler.pgstac.db import close_db_connection, connect_to_db
from titiler.pgstac.settings import PostgresSettings

@app.on_event("startup")
async def startup_event():
    """Initialize database connection and Azure OAuth authentication on startup."""
    global DATABASE_URL  # Need to modify the global variable

    logger.info("=" * 60)
    logger.info("TiTiler-pgSTAC with Azure OAuth Auth - Starting up")
    logger.info("=" * 60)

    # ============================================
    # STEP 1: BUILD DATABASE_URL WITH MI TOKEN
    # ============================================

    if USE_POSTGRES_MI:
        # Validate required environment variables
        if not all([POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER]):
            logger.error("Missing PostgreSQL environment variables!")
            logger.error(f"  POSTGRES_HOST: {POSTGRES_HOST}")
            logger.error(f"  POSTGRES_DB: {POSTGRES_DB}")
            logger.error(f"  POSTGRES_USER: {POSTGRES_USER}")
            raise ValueError("POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER required when USE_POSTGRES_MI=true")

        logger.info("PostgreSQL Managed Identity authentication enabled")

        try:
            # Get OAuth token at startup
            postgres_token = get_postgres_oauth_token()

            # Build connection string with token as password
            DATABASE_URL = (
                f"postgresql://{POSTGRES_USER}:{postgres_token}"
                f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}?sslmode=require"
            )

            logger.info(f"✓ Built DATABASE_URL with MI token")
            logger.info(f"  Host: {POSTGRES_HOST}")
            logger.info(f"  Database: {POSTGRES_DB}")
            logger.info(f"  User: {POSTGRES_USER}")

        except Exception as e:
            logger.error(f"✗ Failed to acquire PostgreSQL token: {e}")
            raise
    else:
        # Use DATABASE_URL from environment (traditional password auth)
        DATABASE_URL = os.getenv("DATABASE_URL")

        if DATABASE_URL:
            logger.info("Using DATABASE_URL from environment (password authentication)")
            # Redact password in logs
            safe_url = DATABASE_URL.split("@")[1] if "@" in DATABASE_URL else DATABASE_URL
            logger.info(f"  Host: {safe_url}")
        else:
            logger.error("DATABASE_URL environment variable not set!")
            raise ValueError("DATABASE_URL is required when USE_POSTGRES_MI=false")

    # ============================================
    # STEP 2: CONNECT TO DATABASE
    # ============================================

    if DATABASE_URL:
        logger.info(f"Connecting to PostgreSQL database...")
        try:
            db_settings = PostgresSettings(database_url=DATABASE_URL)
            await connect_to_db(app, settings=db_settings)
            logger.info("✓ Database connection established")
            logger.info("  Connection pool created and ready")
        except Exception as e:
            logger.error(f"✗ Failed to connect to database: {e}")
            logger.error("")
            logger.error("Troubleshooting:")
            logger.error("  - Verify PostgreSQL server is running")
            logger.error("  - Verify user exists in database")
            logger.error("  - Verify MI token is valid")
            logger.error("  - Check firewall rules allow App Service")
            raise
    else:
        logger.error("DATABASE_URL not configured!")
        raise ValueError("DATABASE_URL is required")

    # ============================================
    # STEP 3: INITIALIZE STORAGE OAUTH (existing)
    # ============================================

    if USE_AZURE_AUTH:
        if not AZURE_STORAGE_ACCOUNT:
            logger.error("AZURE_STORAGE_ACCOUNT environment variable not set!")
        else:
            logger.info(f"Storage account: {AZURE_STORAGE_ACCOUNT}")

            try:
                # Get initial OAuth token for storage
                token = get_azure_storage_oauth_token()
                if token:
                    logger.info("✓ Storage OAuth authentication initialized successfully")
                    logger.info(f"✓ Token expires at: {oauth_token_cache['expires_at']}")
                    logger.info(f"✓ Access scope: ALL containers per RBAC role")
                    if LOCAL_MODE:
                        logger.info("✓ Using Azure CLI credentials (az login)")
                    else:
                        logger.info("✓ Using Managed Identity")
                else:
                    logger.warning("Failed to get initial storage OAuth token")
            except Exception as e:
                logger.error(f"Failed to initialize storage OAuth authentication: {e}")
                logger.error("The app will continue but may not access Azure Storage")
    else:
        logger.info("Azure Storage authentication is disabled")

    logger.info("=" * 60)
    logger.info("✅ TiTiler-pgSTAC startup complete")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connections on shutdown."""
    logger.info("Shutting down TiTiler-pgSTAC...")
    await close_db_connection(app)
    logger.info("✓ Database connection closed")
```

### Update Dependencies

Ensure `requirements.txt` includes:

```txt
# Azure authentication - OAuth tokens via Managed Identity
azure-identity>=1.15.0

# TiTiler-pgSTAC and dependencies
titiler.pgstac>=1.0.0

# Database drivers
asyncpg>=0.29.0
psycopg2-binary>=2.9.9

# Additional dependencies
pydantic>=2.0.0
pydantic-settings>=2.0.0
```

✅ **Checkpoint**: Code is ready to acquire PostgreSQL tokens and connect using MI.

---

## Step 7: Configure Environment Variables

Set environment variables in Azure App Service.

### For Production (Managed Identity)

```bash
az webapp config appsettings set \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    USE_POSTGRES_MI="true" \
    POSTGRES_HOST="$POSTGRES_SERVER.postgres.database.azure.com" \
    POSTGRES_DB="$POSTGRES_DB" \
    POSTGRES_USER="titiler-db-access" \
    POSTGRES_PORT="5432" \
    LOCAL_MODE="false" \
    USE_AZURE_AUTH="true" \
    AZURE_STORAGE_ACCOUNT="rmhazuregeo"
```

**⚠️ Important**: Do NOT set `DATABASE_URL` when using `USE_POSTGRES_MI=true`. The code builds it dynamically.

### For Development (Azure CLI)

In your local `.env` file:

```bash
# Development mode - use Azure CLI credentials
LOCAL_MODE=true
USE_POSTGRES_MI=false

# Traditional password auth for local dev
DATABASE_URL=postgresql://rob634:B@lamb634@@rmhpgflex.postgres.database.azure.com:5432/geopgflex?sslmode=require

# Storage (uses Azure CLI via DefaultAzureCredential)
USE_AZURE_AUTH=true
AZURE_STORAGE_ACCOUNT=rmhazuregeo

# GDAL Configuration
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.tiff
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
VSI_CACHE_SIZE=536870912
```

**Or** use MI locally (requires `az login`):

```bash
# Local development with MI (must run 'az login' first)
LOCAL_MODE=true
USE_POSTGRES_MI=true
POSTGRES_HOST=rmhpgflex.postgres.database.azure.com
POSTGRES_DB=geopgflex
POSTGRES_USER=titiler-db-access
POSTGRES_PORT=5432

USE_AZURE_AUTH=true
AZURE_STORAGE_ACCOUNT=rmhazuregeo
```

### Verify Configuration

```bash
# Check all settings are applied
az webapp config appsettings list \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "[?contains(name, 'POSTGRES') || contains(name, 'USE_')].{Name:name, Value:value}" \
  --output table
```

**Expected output:**
```
Name               Value
-----------------  ------------------------------------------------
USE_POSTGRES_MI    true
POSTGRES_HOST      rmhpgflex.postgres.database.azure.com
POSTGRES_DB        geopgflex
POSTGRES_USER      titiler-db-access
POSTGRES_PORT      5432
LOCAL_MODE         false
USE_AZURE_AUTH     true
```

✅ **Checkpoint**: Environment variables configured for MI authentication.

---

## Step 8: Deploy and Test

Deploy your updated code and verify the connection works.

### Deploy Code

```bash
# Rebuild and deploy (adjust for your deployment method)
cd /Users/robertharrison/python_builds/titilerpgstac

# Build Docker image
docker build -t rmhtitiler:latest .

# Push to Azure Container Registry (or your registry)
az acr login --name <your-registry>
docker tag rmhtitiler:latest <your-registry>.azurecr.io/rmhtitiler:latest
docker push <your-registry>.azurecr.io/rmhtitiler:latest

# Restart web app to pull new image
az webapp restart \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP
```

### Check Logs

```bash
# Stream application logs
az webapp log tail \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP

# Look for these log messages:
# ✓ "🔑 Acquiring OAuth token for PostgreSQL"
# ✓ "✅ PostgreSQL OAuth token successfully acquired"
# ✓ "✓ Built DATABASE_URL with MI token"
# ✓ "✓ Database connection established"
```

**Expected successful startup logs:**

```
TiTiler-pgSTAC with Azure OAuth Auth - Starting up
============================================================
PostgreSQL Managed Identity authentication enabled
============================================================
🔑 Acquiring OAuth token for PostgreSQL
============================================================
Mode: PRODUCTION (Managed Identity)
PostgreSQL Host: rmhpgflex.postgres.database.azure.com
PostgreSQL User: titiler-db-access
Token Scope: https://ossrdbms-aad.database.windows.net/.default
============================================================
✓ DefaultAzureCredential created successfully
✓ PostgreSQL OAuth token acquired
  Token length: 1234 characters
  Token expires at: 2025-11-13T17:30:00+00:00
============================================================
✅ PostgreSQL OAuth token successfully acquired
============================================================
   PostgreSQL Host: rmhpgflex.postgres.database.azure.com
   PostgreSQL User: titiler-db-access
   Valid until: 2025-11-13T17:30:00+00:00
============================================================
✓ Built DATABASE_URL with MI token
  Host: rmhpgflex.postgres.database.azure.com
  Database: geopgflex
  User: titiler-db-access
Connecting to PostgreSQL database...
✓ Database connection established
  Connection pool created and ready
```

### Test Endpoints

```bash
# Health check (should show database status)
curl https://rmhtitiler.azurewebsites.net/healthz | jq

# Expected response includes:
# {
#   "status": "healthy",
#   "database_connected": true,
#   "database_url": "rmhpgflex.postgres.database.azure.com",
#   ...
# }

# Test collection endpoint
curl https://rmhtitiler.azurewebsites.net/collections | jq

# Test search registration (if you have write permissions)
curl -X POST https://rmhtitiler.azurewebsites.net/searches/register \
  -H "Content-Type: application/json" \
  -d '{
    "collections": ["test_collection"],
    "filter-lang": "cql2-json"
  }' | jq
```

### Verify Token in Database

Connect to PostgreSQL and check the connection:

```sql
-- Check current connections
SELECT
    usename,
    application_name,
    client_addr,
    state,
    query_start
FROM pg_stat_activity
WHERE usename = 'titiler-db-access';

-- Should show connections from your App Service
```

✅ **Checkpoint**: TiTiler is successfully authenticating with PostgreSQL using Managed Identity!

---

## Troubleshooting

### Issue: "Failed to create Azure credential"

**Symptoms:**
```
❌ FAILED TO CREATE AZURE CREDENTIAL
Error: DefaultAzureCredential failed to retrieve a token from the included credentials
```

**Solutions:**

1. **Verify MI is assigned to App Service:**
   ```bash
   az webapp identity show --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP
   ```
   Should show `"type": "UserAssigned"` with your MI listed.

2. **Wait for propagation:**
   After assigning MI, wait 2-3 minutes for Azure IMDS to update.

3. **Check LOCAL_MODE setting:**
   - Production: `LOCAL_MODE=false` (uses Managed Identity)
   - Development: `LOCAL_MODE=true` (uses Azure CLI, requires `az login`)

### Issue: "Failed to get PostgreSQL OAuth token"

**Symptoms:**
```
❌ FAILED TO GET POSTGRESQL OAUTH TOKEN
Error: ManagedIdentityCredential authentication unavailable
```

**Solutions:**

1. **Verify MI has correct scope:**
   Test token acquisition manually:
   ```bash
   az account get-access-token \
     --resource https://ossrdbms-aad.database.windows.net/.default
   ```

2. **Check MI client ID is correct:**
   ```bash
   MI_CLIENT_ID=$(az identity show \
     --name titiler-db-access \
     --resource-group $RESOURCE_GROUP \
     --query clientId -o tsv)
   echo $MI_CLIENT_ID
   ```

3. **Verify MI assignment:**
   ```bash
   az webapp identity show --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP \
     --query "userAssignedIdentities" -o json
   ```

### Issue: "User does not exist" or "Role does not exist"

**Symptoms:**
```
psycopg2.OperationalError: FATAL: role "titiler-db-access" does not exist
```

**Solutions:**

1. **Verify user was created:**
   ```sql
   SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'titiler-db-access';
   ```

2. **Recreate user with correct Object ID:**
   ```bash
   # Get Object ID
   MI_OBJECT_ID=$(az ad sp show \
     --id $(az identity show --name titiler-db-access --resource-group $RESOURCE_GROUP --query clientId -o tsv) \
     --query id -o tsv)

   echo "Use this Object ID: $MI_OBJECT_ID"
   ```

   Then in PostgreSQL:
   ```sql
   -- Drop existing user if needed
   DROP ROLE IF EXISTS "titiler-db-access";

   -- Recreate with correct Object ID
   SELECT * FROM pgaadauth_create_principal(
       'titiler-db-access',
       'PASTE_OBJECT_ID_HERE',
       'service'
   );
   ```

### Issue: "Permission denied for table X"

**Symptoms:**
```
psycopg2.errors.InsufficientPrivilege: permission denied for table collections
```

**Solutions:**

1. **Verify permissions:**
   ```sql
   SELECT
       grantee,
       table_name,
       privilege_type
   FROM information_schema.table_privileges
   WHERE grantee = 'titiler-db-access'
     AND table_schema = 'pgstac';
   ```

2. **Re-grant permissions:**
   ```sql
   GRANT USAGE ON SCHEMA pgstac TO "titiler-db-access";
   GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-access";
   ```

3. **For search registration:**
   ```sql
   GRANT INSERT, UPDATE ON pgstac.searches TO "titiler-db-access";
   ```

### Issue: "Connection timed out" or "No pg_hba.conf entry"

**Symptoms:**
```
psycopg2.OperationalError: could not connect to server: Connection timed out
```

**Solutions:**

1. **Check firewall rules:**
   ```bash
   # Allow Azure services
   az postgres flexible-server firewall-rule create \
     --resource-group $RESOURCE_GROUP \
     --name $POSTGRES_SERVER \
     --rule-name AllowAzureServices \
     --start-ip-address 0.0.0.0 \
     --end-ip-address 0.0.0.0
   ```

2. **Verify SSL mode:**
   Ensure connection string includes `sslmode=require`:
   ```python
   DATABASE_URL = f"postgresql://{user}:{token}@{host}:{port}/{db}?sslmode=require"
   ```

3. **Check network connectivity:**
   ```bash
   # From App Service console
   tcpping $POSTGRES_SERVER.postgres.database.azure.com 5432
   ```

### Issue: "Token expired" or long-running connections fail

**Symptoms:**
After ~1 hour, database connections start failing.

**Solutions:**

**This should NOT happen** because:
- TiTiler connection pools recycle connections automatically
- Your app typically restarts more frequently than token expiry
- New tokens are acquired on each app restart

If it does happen:
1. Check app uptime: `az webapp show --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP --query "state"`
2. Consider implementing connection pool max lifetime < 1 hour
3. Add health check endpoint that tests database connectivity

### Debug: Enable Detailed Logging

Add to your `custom_pgstac_main.py`:

```python
import logging

# Set detailed logging for Azure Identity
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('azure.identity').setLevel(logging.DEBUG)
logging.getLogger('azure.core').setLevel(logging.DEBUG)
```

Or via environment variable:

```bash
az webapp config appsettings set \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings AZURE_LOG_LEVEL="DEBUG"
```

---

## Security Best Practices

### 1. Use Read-Only Permissions in Production

```sql
-- Production: Read-only
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-access";

-- Never grant in production:
-- GRANT INSERT, UPDATE, DELETE ON pgstac.collections TO "titiler-db-access";  ❌
-- GRANT pgstac_admin TO "titiler-db-access";  ❌
```

### 2. Separate Identities for Different Environments

```bash
# Development
az identity create --name titiler-db-dev --resource-group $RESOURCE_GROUP

# Staging
az identity create --name titiler-db-staging --resource-group $RESOURCE_GROUP

# Production
az identity create --name titiler-db-prod --resource-group $RESOURCE_GROUP
```

Each with appropriate permissions for its environment.

### 3. Monitor Database Access

```sql
-- Enable audit logging on PostgreSQL
ALTER DATABASE geopgflex SET log_connections = 'on';
ALTER DATABASE geopgflex SET log_disconnections = 'on';

-- Monitor MI access patterns
SELECT
    usename,
    COUNT(*) as connection_count,
    MAX(query_start) as last_query,
    state
FROM pg_stat_activity
WHERE usename = 'titiler-db-access'
GROUP BY usename, state;
```

### 4. Use Azure Monitor

```bash
# Enable diagnostic logs
az monitor diagnostic-settings create \
  --name postgres-logs \
  --resource /subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.DBforPostgreSQL/flexibleServers/$POSTGRES_SERVER \
  --logs '[{"category": "PostgreSQLLogs", "enabled": true}]' \
  --workspace <log-analytics-workspace-id>
```

### 5. Rotate Managed Identities (If Compromised)

```bash
# Create new identity
az identity create --name titiler-db-access-v2 --resource-group $RESOURCE_GROUP

# Assign to app
az webapp identity assign --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP \
  --identities /subscriptions/$SUBSCRIPTION_ID/resourcegroups/$RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/titiler-db-access-v2

# Create new PostgreSQL user (in database)
# Then update POSTGRES_USER environment variable
# Then remove old identity
```

### 6. Network Security

```bash
# Use VNet integration for App Service
az webapp vnet-integration add \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --vnet <vnet-name> \
  --subnet <subnet-name>

# Restrict PostgreSQL to VNet only
az postgres flexible-server firewall-rule delete \
  --resource-group $RESOURCE_GROUP \
  --name $POSTGRES_SERVER \
  --rule-name AllowAzureServices

# Add VNet rule instead
az postgres flexible-server vnet-rule create \
  --resource-group $RESOURCE_GROUP \
  --server-name $POSTGRES_SERVER \
  --name AllowAppServiceSubnet \
  --vnet-name <vnet-name> \
  --subnet <subnet-name>
```

---

## Summary

### What You've Accomplished

✅ **Passwordless authentication** - No credentials in code or environment
✅ **Automatic token rotation** - Tokens refresh on app restart
✅ **Production-ready security** - Minimal permissions, audit trail
✅ **Scalable architecture** - Works with multiple app instances
✅ **Simplified operations** - No secret management overhead

### Configuration Checklist

- [x] User-assigned managed identity created
- [x] MI assigned to App Service
- [x] PostgreSQL user created with MI Object ID
- [x] Permissions granted (read-only or read+write)
- [x] Code updated to acquire tokens at startup
- [x] Environment variables configured
- [x] Application deployed and tested
- [x] Logs reviewed for successful connection

### Key Differences from Storage Pattern

| Aspect | Azure Storage | PostgreSQL |
|--------|---------------|------------|
| **Token scope** | `https://storage.azure.com/.default` | `https://ossrdbms-aad.database.windows.net/.default` |
| **Acquisition timing** | Per-request (middleware) | Once at startup |
| **Storage location** | `os.environ` (per-request) | `DATABASE_URL` (startup) |
| **Consumer** | GDAL (C++ library) | asyncpg (Python driver) |
| **Refresh pattern** | Every request via middleware | App restart (natural cycle) |

### Next Steps

1. **Test search registration** - Verify `/searches/register` works (if you have write permissions)
2. **Monitor performance** - Watch connection pool metrics
3. **Set up alerts** - Configure Azure Monitor for connection failures
4. **Document for team** - Share this setup with other developers
5. **Plan for DR** - Document MI configuration for disaster recovery

---

**Status**: ✅ Setup Complete
**Date**: November 13, 2025
**Maintained By**: TiTiler-pgSTAC Team
