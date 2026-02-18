# Google Cloud Storage Integration — Implementation Plan

**Date:** 2026-02-13
**App Version:** 0.8.13.3
**Status:** Proposal — awaiting review

---

## Goal

Enable TiTiler to serve COG tiles and Zarr data from Google Cloud Storage (GCS) buckets, alongside the existing Azure Blob Storage support.

---

## How It Works Today (Azure)

Understanding the current pattern is key — GCS support should mirror it:

1. **Middleware** (`middleware/azure_auth.py`) runs before every request
2. Calls `get_storage_oauth_token_async()` to get a cached Azure MI token
3. Injects the token into GDAL env vars (`AZURE_STORAGE_ACCESS_TOKEN`)
4. GDAL reads COGs from `/vsiaz/container/path.tif` using that token
5. For Zarr, `adlfs` (fsspec backend) uses the same token via `abfs://` URLs
6. Background task refreshes the token every 45 minutes (1-hour lifetime)

**GCS equivalent:** GDAL reads from `/vsigs/bucket/path.tif`. fsspec dispatches `gs://` URLs to `gcsfs`.

---

## Authentication Approach

### Primary: Service Account Key JSON

A JSON key file for a GCP Service Account. Both GDAL (`/vsigs/`) and gcsfs (`gs://`) read it automatically via `GOOGLE_APPLICATION_CREDENTIALS`. This is the simplest approach that covers both COGs and Zarr.

**How it works:**
1. Create a GCP Service Account with `roles/storage.objectViewer` on the target bucket(s)
2. Generate a JSON key file
3. Store the JSON as an Azure App Setting (or in Key Vault for extra security)
4. At startup, write it to a temp file and set `GOOGLE_APPLICATION_CREDENTIALS`
5. GDAL and gcsfs both pick it up — no per-request token management needed

**GCP setup:**
```bash
# Create service account
gcloud iam service-accounts create gcs-reader \
    --display-name="TiTiler GCS Reader"

# Grant read access to bucket(s)
gcloud storage buckets add-iam-policy-binding gs://your-bucket \
    --role=roles/storage.objectViewer \
    --member="serviceAccount:gcs-reader@your-project.iam.gserviceaccount.com"

# Generate key file
gcloud iam service-accounts keys create gcs-key.json \
    --iam-account=gcs-reader@your-project.iam.gserviceaccount.com
```

**App-side config:**
```bash
ENABLE_GCS=true
GCS_PROJECT_ID=your-gcp-project
GCS_SERVICE_ACCOUNT_KEY='{"type":"service_account","project_id":"...","private_key":"..."}'
```

The app writes the JSON to `/tmp/gcs-credentials.json` at startup and sets `GOOGLE_APPLICATION_CREDENTIALS`. Both GDAL and gcsfs handle token acquisition and refresh internally — the `google-auth` library uses the private key to mint short-lived OAuth2 tokens on demand.

**Key storage options:**

| Method | Security | Complexity |
|--------|----------|------------|
| App Setting (env var) | Moderate — visible to App Service admins | Lowest |
| Key Vault secret | High — audited, RBAC-controlled | Medium |
| Key Vault reference (`@Microsoft.KeyVault(...)`) | High — best of both | Medium |

**Rotation:** GCP allows up to 10 keys per service account. Create a new key, update the App Setting, restart. Delete the old key after confirming the new one works.

---

### Future Option: Workload Identity Federation

If we want to eliminate the stored key entirely, WIF lets Azure MI tokens be exchanged for GCP tokens automatically — no secrets. This mirrors the Azure Blob Storage pattern exactly.

The code changes below are designed to support both approaches. With a service account key, `google.auth.default()` uses the key file. With WIF, the same `google.auth.default()` call reads a credential config file instead — no code changes, just a different file at `GOOGLE_APPLICATION_CREDENTIALS`.

<details>
<summary>WIF setup details (for future reference)</summary>

```bash
# Create Workload Identity Pool
gcloud iam workload-identity-pools create azure-pool \
    --location="global" --display-name="Azure App Service"

# Add Azure AD as OIDC provider
gcloud iam workload-identity-pools providers create-oidc azure-provider \
    --location="global" \
    --workload-identity-pool="azure-pool" \
    --issuer-uri="https://sts.windows.net/{AZURE_TENANT_ID}" \
    --allowed-audiences="{APPLICATION_ID_URI}" \
    --attribute-mapping="google.subject=assertion.sub"

# Grant bucket access
gcloud storage buckets add-iam-policy-binding gs://your-bucket \
    --role=roles/storage.objectViewer \
    --member="principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/azure-pool/subject/{MI_OBJECT_ID}"

# Generate credential config (NOT a secret — only metadata)
gcloud iam workload-identity-pools create-cred-config \
    projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/azure-pool/providers/azure-provider \
    --service-account=gcs-reader@your-project.iam.gserviceaccount.com \
    --azure --app-id-uri {APPLICATION_ID_URI} \
    --output-file=gcp-wif-config.json
```

With WIF, set `GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-wif-config.json` instead of the service account key. Everything else stays the same.

</details>

---

## Implementation Plan

### What Changes

| Component | Change | Effort |
|-----------|--------|--------|
| `config.py` | Add GCS settings (`ENABLE_GCS`, `GCS_PROJECT_ID`, `GCS_SERVICE_ACCOUNT_KEY`) | Small |
| `auth/gcs.py` | New file — write credentials file at startup, verify auth works | Small |
| `app.py` | Call GCS init in lifespan startup | Small |
| `requirements.txt` | Add `gcsfs`, `google-auth`, `google-cloud-storage` | Small |
| `Dockerfile` | No change (GDAL already has `/vsigs/` compiled in) | None |
| `routers/health.py` | Report GCS status in `/health` | Small |

**No middleware changes needed.** With a service account key, `google-auth` handles token minting internally — GDAL and gcsfs both call `google.auth.default()` which reads the key file and generates short-lived OAuth2 tokens on demand. No background refresh task required either.

### Phase 1: Configuration

Add to `geotiler/config.py`:

```python
# =========================================================================
# Google Cloud Storage
# =========================================================================
enable_gcs: bool = False
"""Enable Google Cloud Storage access via /vsigs/ and gs:// URLs."""

gcs_project_id: str = ""
"""GCP project ID (needed by gcsfs for bucket operations)."""

gcs_service_account_key: str = ""
"""Service account key JSON string. Stored as env var, written to file at startup.
Set via GCS_SERVICE_ACCOUNT_KEY app setting."""
```

### Phase 2: Auth Module

Create `geotiler/auth/gcs.py`:

```python
"""
Google Cloud Storage authentication.

Writes the service account key JSON to a temp file at startup and sets
GOOGLE_APPLICATION_CREDENTIALS. Both GDAL (/vsigs/) and gcsfs (gs://)
use this automatically — google-auth handles token minting and refresh
internally using the private key.
"""

import os
import json
import logging
import tempfile
from pathlib import Path

from geotiler.config import settings

logger = logging.getLogger(__name__)

_credentials_path: str | None = None


def initialize_gcs() -> bool:
    """
    Write service account key to file and set GOOGLE_APPLICATION_CREDENTIALS.

    Called once at startup. Returns True if GCS auth is configured.
    """
    global _credentials_path

    if not settings.enable_gcs:
        return False

    if not settings.gcs_service_account_key:
        logger.warning("ENABLE_GCS=true but GCS_SERVICE_ACCOUNT_KEY is empty")
        return False

    # Validate JSON before writing
    try:
        key_data = json.loads(settings.gcs_service_account_key)
        if key_data.get("type") != "service_account":
            logger.error(f"GCS key JSON 'type' is '{key_data.get('type')}', expected 'service_account'")
            return False
    except json.JSONDecodeError as e:
        logger.error(f"GCS_SERVICE_ACCOUNT_KEY is not valid JSON: {e}")
        return False

    # Write to temp file (survives for container lifetime)
    credentials_dir = Path(tempfile.gettempdir()) / "gcs"
    credentials_dir.mkdir(exist_ok=True)
    credentials_file = credentials_dir / "credentials.json"
    credentials_file.write_text(settings.gcs_service_account_key)
    credentials_file.chmod(0o600)

    _credentials_path = str(credentials_file)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _credentials_path

    # Set project ID for gcsfs
    if settings.gcs_project_id:
        os.environ["GCLOUD_PROJECT"] = settings.gcs_project_id

    client_email = key_data.get("client_email", "unknown")
    project = key_data.get("project_id", "unknown")
    logger.info(f"GCS auth configured: sa={client_email} project={project}")
    return True


def get_gcs_status() -> dict:
    """Return GCS status for /health endpoint."""
    if not settings.enable_gcs:
        return {"status": "disabled"}

    if not _credentials_path:
        return {"status": "unavailable", "error": "Credentials not initialized"}

    return {
        "status": "healthy",
        "credentials_file": _credentials_path,
        "project_id": settings.gcs_project_id or "(not set)",
    }
```

### Phase 3: Startup Integration

Add to `app.py` lifespan, after storage auth init:

```python
# Initialize GCS authentication
if settings.enable_gcs:
    from geotiler.auth.gcs import initialize_gcs
    if initialize_gcs():
        logger.info("GCS storage access enabled")
```

### Phase 4: Dependencies

Add to `requirements.txt`:

```
# Google Cloud Storage — /vsigs/ COG access + gs:// Zarr access
google-auth>=2.20.0
gcsfs>=2025.3.0
```

Notes:
- `gcsfs` pulls in `google-cloud-storage` and `fsspec` (already present via `adlfs`)
- `gcsfs` and `adlfs` both depend on `fsspec` — they release in lockstep, so recent versions of both resolve to the same `fsspec`
- No `Dockerfile` changes — the base image (`titiler-pgstac:1.9.0`) ships GDAL 3.9+ with `/vsigs/` compiled in
- `google-auth` handles token minting from the service account key automatically — it generates short-lived OAuth2 tokens on demand, so no background refresh task is needed

### Phase 5: Health Reporting

Add GCS to `/health` response:

```json
{
    "services": {
        "gcs": {
            "status": "healthy",
            "credentials_file": "/tmp/gcs/credentials.json",
            "project_id": "your-gcp-project"
        }
    }
}
```

---

## URL Patterns

Once enabled, users access GCS data via:

### COG Tiles (GDAL /vsigs/)

```
# Get info
GET /cog/info?url=/vsigs/my-bucket/path/to/file.tif

# Get tile
GET /cog/tiles/WebMercatorQuad/10/512/384.png?url=/vsigs/my-bucket/path/to/file.tif

# Interactive viewer
GET /cog/WebMercatorQuad/map.html?url=/vsigs/my-bucket/path/to/file.tif
```

### Zarr/NetCDF (gcsfs)

```
# List variables
GET /xarray/variables?url=gs://my-bucket/path/to/data.zarr

# Get tile
GET /xarray/tiles/WebMercatorQuad/0/0/0@1x.png?url=gs://my-bucket/path/to/data.zarr&variable=temperature&bidx=1
```

Both URL formats work alongside existing Azure URLs (`/vsiaz/...`, `abfs://...`, `https://*.blob.core.windows.net/...`). No changes to the TiTiler routing or tiler factories — the URL prefix tells GDAL/fsspec which backend to use.

---

## Environment Variables Summary

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ENABLE_GCS` | No | `false` | Enable GCS access |
| `GCS_SERVICE_ACCOUNT_KEY` | Yes (when enabled) | `""` | Service account key JSON string |
| `GCS_PROJECT_ID` | For Zarr | `""` | GCP project ID (needed by gcsfs for bucket ops) |

The app writes `GCS_SERVICE_ACCOUNT_KEY` to `/tmp/gcs/credentials.json` at startup and sets `GOOGLE_APPLICATION_CREDENTIALS` automatically. You never set `GOOGLE_APPLICATION_CREDENTIALS` directly.

---

## Cost Considerations

| Factor | Impact |
|--------|--------|
| **Egress (GCS to Azure)** | $0.08–0.12/GB — significant for high-volume tile serving |
| **GCS API requests** | $0.004/10,000 Class B (reads) — negligible |
| **Cross-cloud latency** | 5–50ms per request vs sub-1ms in-region — affects Zarr (many chunk reads) more than COGs |

**Recommendation:** For high-traffic datasets, mirror the data to Azure Blob Storage. Use GCS access for low-frequency reads, development, or data that must stay on GCP.

---

## Scoping Options

Two levels of implementation:

### Standard (COGs + Zarr)
- Add `gcsfs` + `google-auth` to requirements
- Create `auth/gcs.py` — write key file at startup, set `GOOGLE_APPLICATION_CREDENTIALS`
- Add GCS init to app lifespan
- Both `/vsigs/` and `gs://` URLs work
- Health endpoint reports GCS status
- **Effort: ~3 hours**

### Standard + Docs
- Everything above
- Landing pages updated with GCS sample URLs
- WIKI.md updated with GCS URL patterns and examples
- Deployment docs updated with GCS App Settings
- **Effort: ~5 hours**

---

## Open Questions

1. **Which GCS buckets need access?** Determines IAM setup (single bucket vs project-wide).
2. **Is Zarr access needed, or just COGs?** If COGs only, we could skip `gcsfs` and just set `GOOGLE_APPLICATION_CREDENTIALS` with no code changes at all.
3. **Expected read volume?** High egress from GCS ($0.08–0.12/GB) may justify mirroring data to Azure for frequently-accessed datasets.
4. **Key storage preference?** Plain App Setting vs Key Vault reference.
