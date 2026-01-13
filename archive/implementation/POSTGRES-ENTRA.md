# TiTiler-PgSTAC Authentication Guide
## Azure Managed Identity & Key Vault Patterns for PostgreSQL

---

## Overview

TiTiler-pgstac requires PostgreSQL credentials via environment variables. This guide covers two authentication patterns:

1. **Managed Identity (Recommended for Production)** - Passwordless, sustainable, automatic token rotation
2. **Key Vault (Fallback/Development)** - Password-based, requires manual rotation

---

## Managed Identity Implementation

### Why User-Assigned Managed Identity?

**Advantages over System-Assigned:**
- **Predictable naming** - You control the identity name
- **Lifecycle independence** - Survives web app deletion/recreation
- **Reusability** - Same identity can be used across dev/staging/prod
- **Infrastructure-as-code friendly** - Explicit and easier to manage in Terraform/Bicep

### Step 1: Create User-Assigned Managed Identity

```bash
# Create the managed identity with a clear, descriptive name
az identity create \
  --name titiler-db-access \
  --resource-group <your-resource-group> \
  --location <your-location>

# Capture the client ID (needed for explicit authentication)
CLIENT_ID=$(az identity show \
  --name titiler-db-access \
  --resource-group <your-resource-group> \
  --query clientId -o tsv)

echo "Client ID: $CLIENT_ID"
```

**Naming Convention:**
- Use descriptive names like `titiler-db-access`, `geospatial-api-db`, etc.
- Avoid web app-specific names since the identity should be reusable
- PostgreSQL username will match this identity name

### Step 2: Assign Identity to Web App

```bash
# Assign the user-assigned managed identity to your web app
az webapp identity assign \
  --name geotiler \
  --resource-group <your-resource-group> \
  --identities /subscriptions/<subscription-id>/resourcegroups/<your-resource-group>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/titiler-db-access

# Verify assignment
az webapp identity show \
  --name geotiler \
  --resource-group <your-resource-group>
```

### Step 3: Create PostgreSQL User

Connect to your Azure PostgreSQL Flexible Server as an admin and run:

```sql
-- Enable managed identity authentication (if not already enabled)
SET aad_validate_oids_in_tenant = off;

-- Create the database user matching your managed identity name
SELECT * FROM pgaadauth_create_principal('titiler-db-access', false, false);

-- Grant read-only permissions (recommended for production)
GRANT USAGE ON SCHEMA pgstac TO "titiler-db-access";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "titiler-db-access";
GRANT SELECT ON ALL SEQUENCES IN SCHEMA pgstac TO "titiler-db-access";

-- OR use PgSTAC's built-in read-only role
GRANT pgstac_read TO "titiler-db-access";

-- For future tables (if schema evolves)
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac 
GRANT SELECT ON TABLES TO "titiler-db-access";
```

### Permissions Breakdown

#### Read-Only Access (Production Recommendation)

**What it enables:**
- ✅ Serve tiles from collections: `/collections/{collection_id}/tiles/{z}/{x}/{y}`
- ✅ Serve tiles from items: `/collections/{collection_id}/items/{item_id}/tiles/{z}/{x}/{y}`
- ✅ Get collection info: `/collections/{collection_id}/info`
- ✅ Get item info: `/collections/{collection_id}/items/{item_id}/info`
- ✅ Read pre-registered searches from `pgstac.searches` table
- ✅ Statistics endpoints on collections/items

**What it blocks:**
- ❌ `/searches/register` endpoint (cannot create new search hashes)
- ❌ Writing to `pgstac.searches` table
- ❌ Modifying STAC items or collections

**Why read-only for production:**
1. **Security** - Prevents uncontrolled database writes from public API
2. **Stability** - No risk of database bloat from unlimited search registration
3. **Predictability** - Only serve pre-defined, tested queries
4. **DoS prevention** - Cannot register complex queries that slow the database

#### Write Access (Admin/Internal Only)

If you need the `/register` endpoint for an internal admin API:

```sql
-- Grant write access to searches table
GRANT INSERT, UPDATE ON pgstac.searches TO "titiler-admin-writer";

-- OR use broader PgSTAC role
GRANT pgstac_ingest TO "titiler-admin-writer";
```

**Use cases for write access:**
- Internal admin tools for registering common queries
- Development/testing environments
- Pre-registration service (separate from public API)

---

## Auth Wrapper Implementation

### Managed Identity Pattern

```python
"""
TiTiler-PgSTAC Authentication Wrapper
Supports both Managed Identity (preferred) and Key Vault fallback
"""

import os
from typing import Optional
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
from azure.core.credentials import AccessToken


class TiTilerAuth:
    """
    Manages PostgreSQL authentication for TiTiler-PgSTAC.
    Sets required environment variables before TiTiler modules are imported.
    """
    
    def __init__(
        self,
        postgres_host: str,
        postgres_db: str,
        postgres_user: str,
        postgres_port: str = "5432",
        use_managed_identity: bool = True,
        managed_identity_client_id: Optional[str] = None,
        key_vault_url: Optional[str] = None,
        key_vault_secret_name: Optional[str] = None
    ):
        """
        Initialize TiTiler authentication.
        
        Args:
            postgres_host: PostgreSQL server hostname (e.g., 'myserver.postgres.database.azure.com')
            postgres_db: Database name
            postgres_user: PostgreSQL username (should match managed identity name for MI auth)
            postgres_port: PostgreSQL port (default: 5432)
            use_managed_identity: Use managed identity token instead of password (default: True)
            managed_identity_client_id: Client ID for user-assigned MI (optional, for explicit auth)
            key_vault_url: Azure Key Vault URL for password fallback
            key_vault_secret_name: Secret name in Key Vault containing password
        """
        self.postgres_host = postgres_host
        self.postgres_db = postgres_db
        self.postgres_user = postgres_user
        self.postgres_port = postgres_port
        self.use_managed_identity = use_managed_identity
        self.managed_identity_client_id = managed_identity_client_id
        self.key_vault_url = key_vault_url
        self.key_vault_secret_name = key_vault_secret_name
        
    def _get_managed_identity_token(self) -> str:
        """
        Retrieve PostgreSQL access token using managed identity.
        
        Returns:
            Access token string to use as password
        """
        # Scope for Azure PostgreSQL
        postgres_scope = "https://ossrdbms-aad.database.windows.net/.default"
        
        # Use explicit managed identity if client_id provided
        if self.managed_identity_client_id:
            credential = ManagedIdentityCredential(
                client_id=self.managed_identity_client_id
            )
        else:
            # DefaultAzureCredential will automatically find user-assigned MI
            credential = DefaultAzureCredential()
        
        try:
            token: AccessToken = credential.get_token(postgres_scope)
            return token.token
        except Exception as e:
            raise RuntimeError(f"Failed to acquire managed identity token: {e}")
    
    def _get_key_vault_password(self) -> str:
        """
        Retrieve PostgreSQL password from Azure Key Vault.
        
        Returns:
            Password string from Key Vault
        """
        if not self.key_vault_url or not self.key_vault_secret_name:
            raise ValueError(
                "key_vault_url and key_vault_secret_name required for Key Vault auth"
            )
        
        try:
            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=self.key_vault_url, credential=credential)
            secret = client.get_secret(self.key_vault_secret_name)
            return secret.value
        except Exception as e:
            raise RuntimeError(f"Failed to retrieve Key Vault secret: {e}")
    
    def configure_environment(self) -> None:
        """
        Set environment variables required by TiTiler-PgSTAC.
        Must be called before importing titiler.pgstac modules.
        """
        # Get password/token based on authentication method
        if self.use_managed_identity:
            password = self._get_managed_identity_token()
            print("✓ Using Managed Identity for PostgreSQL authentication")
        else:
            password = self._get_key_vault_password()
            print("⚠ Using Key Vault password for PostgreSQL authentication")
        
        # Set environment variables that TiTiler-PgSTAC expects
        os.environ['POSTGRES_USER'] = self.postgres_user
        os.environ['POSTGRES_PASS'] = password
        os.environ['POSTGRES_DBNAME'] = self.postgres_db
        os.environ['POSTGRES_HOST'] = self.postgres_host
        os.environ['POSTGRES_PORT'] = self.postgres_port
        
        # Alternative: Set DATABASE_URL (TiTiler supports both patterns)
        # database_url = f"postgresql://{self.postgres_user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        # os.environ['DATABASE_URL'] = database_url
        
        print(f"✓ PostgreSQL environment configured for {self.postgres_host}/{self.postgres_db}")


# Example usage in Azure Function or Web App startup
def configure_titiler_auth():
    """
    Configure TiTiler authentication based on environment.
    Call this BEFORE importing any titiler.pgstac modules.
    """
    
    # Configuration from app settings or environment variables
    postgres_host = os.getenv("POSTGRES_HOST", "your-server.postgres.database.azure.com")
    postgres_db = os.getenv("POSTGRES_DB", "your_database")
    postgres_user = os.getenv("POSTGRES_USER", "titiler-db-access")
    
    # Managed Identity settings (preferred)
    use_managed_identity = os.getenv("USE_MANAGED_IDENTITY", "true").lower() == "true"
    managed_identity_client_id = os.getenv("MANAGED_IDENTITY_CLIENT_ID")  # Optional
    
    # Key Vault settings (fallback)
    key_vault_url = os.getenv("KEY_VAULT_URL")
    key_vault_secret_name = os.getenv("POSTGRES_PASSWORD_SECRET_NAME", "postgres-password")
    
    # Initialize and configure
    auth = TiTilerAuth(
        postgres_host=postgres_host,
        postgres_db=postgres_db,
        postgres_user=postgres_user,
        use_managed_identity=use_managed_identity,
        managed_identity_client_id=managed_identity_client_id,
        key_vault_url=key_vault_url,
        key_vault_secret_name=key_vault_secret_name
    )
    
    auth.configure_environment()


# FastAPI application example
if __name__ == "__main__":
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from titiler.pgstac.db import close_db_connection, connect_to_db
    from titiler.pgstac.factory import MosaicTilerFactory
    
    # CRITICAL: Configure auth BEFORE importing titiler modules
    configure_titiler_auth()
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """FastAPI Lifespan - manages database connection pool"""
        await connect_to_db(app)
        yield
        await close_db_connection(app)
    
    app = FastAPI(
        title="World Bank Geospatial API",
        description="Cloud-native STAC tile server",
        lifespan=lifespan
    )
    
    # Add TiTiler-PgSTAC endpoints
    mosaic = MosaicTilerFactory(
        router_prefix="/searches",
        # Exclude /register endpoint for read-only production
    )
    app.include_router(mosaic.router, prefix="/searches", tags=["Mosaic Tiles"])
    
    print("🚀 TiTiler-PgSTAC server ready")
```

### Usage in Azure Function

```python
# __init__.py or function_app.py
import azure.functions as func
from .auth_wrapper import configure_titiler_auth

# Configure before any titiler imports
configure_titiler_auth()

# Now import titiler
from titiler.pgstac.factory import MosaicTilerFactory

# Rest of your Azure Function code
```

---

## Key Vault Pattern (Fallback)

While managed identity is preferred, Key Vault provides a fallback for scenarios where MI isn't available.

### Setup Key Vault Secret

```bash
# Create or update the secret
az keyvault secret set \
  --vault-name <your-vault-name> \
  --name postgres-password \
  --value "<your-postgres-password>"

# Grant your web app access to the Key Vault
az keyvault set-policy \
  --name <your-vault-name> \
  --object-id <web-app-managed-identity-principal-id> \
  --secret-permissions get list
```

### App Settings

```bash
# Configure for Key Vault authentication
az webapp config appsettings set \
  --name geotiler \
  --resource-group <your-rg> \
  --settings \
    USE_MANAGED_IDENTITY="false" \
    KEY_VAULT_URL="https://<your-vault>.vault.azure.net/" \
    POSTGRES_PASSWORD_SECRET_NAME="postgres-password" \
    POSTGRES_HOST="your-server.postgres.database.azure.com" \
    POSTGRES_DB="your_database" \
    POSTGRES_USER="your_db_user"
```

### Why Key Vault is Less Sustainable

**Drawbacks:**
- Requires password rotation management
- Password stored (even if encrypted)
- More steps for credential lifecycle
- Requires Key Vault access policies
- Additional cost for Key Vault operations

**Use cases:**
- Legacy systems not supporting managed identity
- Local development (though connection strings work too)
- Multi-cloud scenarios

---

## Production Configuration Summary

### Recommended: Managed Identity (Read-Only)

```bash
# App Settings for production
az webapp config appsettings set \
  --name geotiler \
  --resource-group <your-rg> \
  --settings \
    USE_MANAGED_IDENTITY="true" \
    MANAGED_IDENTITY_CLIENT_ID="<client-id-of-titiler-db-access>" \
    POSTGRES_HOST="your-server.postgres.database.azure.com" \
    POSTGRES_DB="your_database" \
    POSTGRES_USER="titiler-db-access" \
    POSTGRES_PORT="5432"
```

### PostgreSQL User Configuration

```sql
-- Production: Read-only access
SELECT * FROM pgaadauth_create_principal('titiler-db-access', false, false);
GRANT pgstac_read TO "titiler-db-access";
```

### What You Get

✅ **Passwordless authentication** - No secrets to manage  
✅ **Automatic token rotation** - Tokens refresh automatically  
✅ **Read-only safety** - Cannot modify database via public API  
✅ **Sustainable** - No manual credential management  
✅ **Auditable** - All access tied to managed identity  

---

## Migration Path

### Phase 1: Proof of Concept (Now)
- Use Key Vault or connection string
- Get it working with ITSDA
- Prove the cloud-native stack

### Phase 2: Production Hardening (Integration Sprint)
- Create user-assigned managed identity
- Set up read-only PostgreSQL user
- Deploy with managed identity auth
- Document in DDH handoff

### Phase 3: Scale & Optimize (When They Ask for Fine-Tuning)
- Add read replicas if needed
- Consider search registration service (separate from public API)
- Implement caching strategies
- Monitor query performance

---

## Troubleshooting

### "Could not connect to server"

```python
# Verify token acquisition works
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
print(f"Token acquired: {token.token[:20]}...")
```

### "User does not exist"

```sql
-- Verify the PostgreSQL user was created
SELECT rolname FROM pg_roles WHERE rolname = 'titiler-db-access';

-- Check permissions
SELECT grantee, privilege_type 
FROM information_schema.role_table_grants 
WHERE grantee = 'titiler-db-access';
```

### "Permission denied"

You likely need write access but only have read. Either:
1. Grant write permissions (not recommended for production)
2. Don't use the `/register` endpoint (recommended)

### Token Refresh in Long-Running Connections

Managed identity tokens expire (~1 hour). For long-running connection pools:

```python
# TiTiler-PgSTAC handles this automatically via psycopg connection pools
# Connections are recreated with fresh tokens as needed
# No additional code required
```

---

## Security Best Practices

1. **Use user-assigned managed identity** for predictability and reusability
2. **Grant minimum permissions** (read-only for public APIs)
3. **Separate write operations** into admin-only services
4. **Monitor access patterns** via PostgreSQL logs
5. **Rotate identities** if compromised (easier than password rotation)
6. **Document identity assignments** in infrastructure-as-code

---

## Next Steps

- [ ] Create user-assigned managed identity: `titiler-db-access`
- [ ] Assign identity to `geotiler` web app
- [ ] Create read-only PostgreSQL user matching identity name
- [ ] Add auth wrapper to TiTiler startup code
- [ ] Configure app settings for managed identity
- [ ] Test tile serving endpoints
- [ ] Document for ITSDA handoff
- [ ] Show Dany and Dimitar it works 🎉

---

*"Get it working first. Optimize for scale when ITSDA is actually complaining about performance, not when they're still asking if you can make it work at all."*

**Current stage:** "When will there be a REST API?"  
**Not yet at:** "How do we fine-tune query patterns for 500M STAC items?"

Ship the MVP. Make it pretty for Spring Meetings. Worry about `/register` endpoint governance later.