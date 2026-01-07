# TiTiler-pgSTAC QA Deployment - December 2025

**Archived**: December 25, 2025
**Original Location**: CLAUDE.md
**Status**: Reference only - contains QA environment specifics

---

## Verified Azure Resources (QA Environment)

| Resource Type | Name | Details |
|---------------|------|---------|
| **Resource Group** | `itses-gddatahub-qa-rg` | Location: **eastus** |
| **Container Registry** | `itsesgddatahubacrqa` | Login: `itsesgddatahubacrqa.azurecr.io` |
| **Storage Account** | `itsesgddataintqastrg` | StorageV2, eastus |
| **PostgreSQL Server** | `itses-gddatahub-pgsqlsvr-qa` | FQDN: `itses-gddatahub-pgsqlsvr-qa.postgres.database.azure.com` |
| **Database** | `geoapp` | pgSTAC schema |
| **User-Assigned MI** | `migeoetldbreaderqa` | ClientId: `7704971b-b7fb-4951-9120-8471281a66fc` |
| **Subscription** | WBG AZ ITSOC QA PDMZ | `f2bde2ed-4d2d-416d-be06-bb76bb62dc85` |

---

## Docker Build via WSL (Corporate Proxy Workaround)

Due to corporate proxy issues, `az acr build` fails. Use local build + push from WSL.

### Prerequisites

1. Configure Docker for insecure registry:
   ```json
   // /etc/docker/daemon.json
   { "insecure-registries": ["itsesgddatahubacrqa.azurecr.io"] }
   ```

2. Set Azure CLI SSL bypass:
   ```bash
   export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1
   ```

### Build & Push

```bash
az acr login --name itsesgddatahubacrqa

docker build --platform linux/amd64 \
  -t itsesgddatahubacrqa.azurecr.io/titiler-pgstac:v1.0.0 \
  -t itsesgddatahubacrqa.azurecr.io/titiler-pgstac:latest \
  -f Dockerfile .

docker push itsesgddatahubacrqa.azurecr.io/titiler-pgstac:latest
```

---

## App Service Setup (Admin Required)

### Create App Service

```bash
az appservice plan create \
  --name titiler-pgstac-plan \
  --resource-group itses-gddatahub-qa-rg \
  --is-linux --sku B2 --location eastus

az webapp create \
  --name titiler-pgstac-qa \
  --resource-group itses-gddatahub-qa-rg \
  --plan titiler-pgstac-plan \
  --deployment-container-image-name itsesgddatahubacrqa.azurecr.io/titiler-pgstac:latest
```

### Assign Managed Identities

```bash
# System-assigned (for storage)
az webapp identity assign --name titiler-pgstac-qa --resource-group itses-gddatahub-qa-rg

# User-assigned (for PostgreSQL)
az webapp identity assign --name titiler-pgstac-qa --resource-group itses-gddatahub-qa-rg \
  --identities /subscriptions/f2bde2ed-4d2d-416d-be06-bb76bb62dc85/resourcegroups/itses-gddatahub-qa-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/migeoetldbreaderqa
```

### Environment Variables

```bash
az webapp config appsettings set \
  --name titiler-pgstac-qa --resource-group itses-gddatahub-qa-rg \
  --settings \
    POSTGRES_AUTH_MODE="managed_identity" \
    POSTGRES_HOST="itses-gddatahub-pgsqlsvr-qa.postgres.database.azure.com" \
    POSTGRES_DB="geoapp" \
    POSTGRES_USER="migeoetldbreaderqa" \
    USE_AZURE_AUTH="true" \
    AZURE_STORAGE_ACCOUNT="itsesgddataintqastrg" \
    LOCAL_MODE="false"
```

---

## PostgreSQL Setup

```sql
SET aad_validate_oids_in_tenant = off;
SELECT * FROM pgaadauth_create_principal('migeoetldbreaderqa', false, false);

GRANT USAGE ON SCHEMA pgstac TO "migeoetldbreaderqa";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "migeoetldbreaderqa";
GRANT INSERT, UPDATE, DELETE ON pgstac.searches TO "migeoetldbreaderqa";
```

---

## Why `az acr build` Failed

Requires `Microsoft.ContainerRegistry/registries/listBuildSourceUploadUrl/action` permission, not included in `AcrPush` role. Use local Docker build as workaround.
