# Easy Auth — Azure App Service Authentication

**Created**: 24 MAR 2026
**Status**: Implemented and verified

---

## Overview

Azure App Service Easy Auth adds tenant-level authentication at the **platform layer**,
before requests reach the FastAPI application. No application code changes required.

```
Client Request
    │
    ▼
Azure App Service (Easy Auth)
    │
    ├── No token?           → 401 (API) or redirect to login (browser)
    ├── Token, wrong tenant? → 403
    ├── Token, valid tenant?  → Pass through to FastAPI
    │   (injects X-MS-CLIENT-PRINCIPAL headers)
    │
    ▼
FastAPI application (unchanged)
```

---

## What It Enforces

With Easy Auth enabled in "Return 401" mode:

| Caller | Behavior |
|--------|----------|
| Browser (human, no session) | Redirected to Microsoft login → sign in → session cookie → works |
| Browser (human, active session) | Session cookie sent automatically → works |
| API client (no token) | `401 Unauthorized` |
| API client (valid tenant token) | `200` — request forwarded to app |
| API client (wrong tenant token) | `403 Forbidden` |
| Managed Identity (same tenant) | Works if app role assigned (see Future section) |

The only check is **"are you in our Azure AD tenant?"** — any authenticated user in the
tenant can access the API. No group or role checks (see Future section for that).

---

## Components

### 1. App Registration (Entra ID)

An App Registration tells Entra ID that your API exists and defines who can access it.

**Required settings:**

| Setting | Value | Why |
|---------|-------|-----|
| Sign-in audience | Single tenant (`AzureADMyOrg`) | Only your org's users can authenticate |
| Redirect URI | `https://{app-hostname}/.auth/login/aad/callback` | Where Entra sends users after login |
| ID token issuance | Enabled | Required for browser login flow |
| Identifier URI | `api://{app-client-id}` | Unique identifier for token audience |
| Client secret | **None** | Not needed — no confidential client flow |

**The redirect URI** is not a callback you build. The `/.auth/*` endpoints are handled
entirely by the App Service platform layer. Your FastAPI app never sees them:

```
/.auth/login/aad/callback  ← Platform handles OAuth code exchange
/.auth/me                  ← Returns current user info (JSON)
/.auth/login/aad           ← Triggers login manually
/.auth/logout              ← Clears session
```

### 2. API Scope

The app registration needs at least one **OAuth2 permission scope** defined, otherwise
client applications cannot request tokens for it.

Create a delegated permission scope (e.g., `access_as_user`) on the app registration
under **Expose an API**. This scope represents "this client can access the API on behalf
of the signed-in user."

### 3. Pre-Authorized Client Applications

When a client application (like the Azure CLI, a portal, or a React frontend) requests
a token for your API, Entra checks whether that client has **consent** to do so.

In corporate environments, user consent is typically disabled by tenant policy. This
means every client must be either:

- **Pre-authorized** on the app registration (no consent prompt, no admin action needed)
- **Admin-consented** by a tenant administrator

Pre-authorization is the self-service option. On the app registration under
**Expose an API → Authorized client applications**, add each client's app ID and
grant it the `access_as_user` scope.

Common clients to pre-authorize:

| Client | App ID | Purpose |
|--------|--------|---------|
| Azure CLI | `04b07795-8ddb-461a-bbee-02f9e1bf7b46` | Developer CLI access |
| Azure Portal | `c44b4083-3bb0-49c1-b47d-974e53cbdf3c` | Portal-based testing |
| Your frontend app | *(its app ID)* | Web application consuming the API |

### 4. Easy Auth Configuration (App Service)

Easy Auth is configured via the `authsettingsV2` resource on the App Service.

**Key settings:**

```json
{
  "platform": { "enabled": true },
  "globalValidation": {
    "requireAuthentication": true,
    "unauthenticatedClientAction": "Return401"
  },
  "identityProviders": {
    "azureActiveDirectory": {
      "enabled": true,
      "registration": {
        "clientId": "<app-registration-client-id>",
        "openIdIssuer": "https://sts.windows.net/<tenant-id>/v2.0"
      },
      "validation": {
        "allowedAudiences": [
          "api://<app-registration-client-id>",
          "<app-registration-client-id>"
        ]
      }
    }
  },
  "login": {
    "tokenStore": { "enabled": true }
  }
}
```

### Excluded Paths

Some paths must bypass authentication entirely — e.g., liveness probes called by
the App Service platform (which doesn't send Bearer tokens).

Add `excludedPaths` to the `globalValidation` config:

```json
{
  "globalValidation": {
    "requireAuthentication": true,
    "unauthenticatedClientAction": "Return401",
    "excludedPaths": ["/livez"]
  }
}
```

Excluded paths return responses without any auth check. Keep this list minimal —
only paths that **must** be anonymous (platform probes, ACME challenges, etc.).
A restart is required after changing excluded paths.

**`unauthenticatedClientAction` options:**

| Value | Behavior |
|-------|----------|
| `Return401` | API-friendly — returns 401, client handles auth |
| `RedirectToLoginPage` | Browser-friendly — redirects to Microsoft login |
| `AllowAnonymous` | Passes identity when present, allows anonymous access |

Use `Return401` for APIs. Browser users still get redirected when they visit
`/.auth/login/aad` directly or when the frontend initiates the flow.

---

## How Consumers Authenticate

### Browser (Human User)

No extra work. The browser is redirected to Microsoft login, user signs in with their
org credentials, and a session cookie is set. Subsequent requests include the cookie
automatically. Sessions last 8 hours by default.

### Azure CLI

```bash
# Get a token for the API
TOKEN=$(az account get-access-token \
  --resource "<app-registration-client-id>" \
  --query accessToken -o tsv)

# Use it
curl -H "Authorization: Bearer $TOKEN" https://<app-hostname>/health
```

If this fails with `AADSTS65001` (consent error), the Azure CLI needs to be
pre-authorized on the app registration (see section 3 above), or you need to
re-login to pick up the new authorization:

```bash
az account clear
az login --tenant "<tenant-id>"
```

### Python / Other Languages

```python
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
token = credential.get_token("<app-registration-client-id>/.default")

import requests
response = requests.get(
    "https://<app-hostname>/health",
    headers={"Authorization": f"Bearer {token.token}"}
)
```

### Managed Identity (Service-to-Service)

Another Azure resource (e.g., a Function App, another App Service) can authenticate
using its Managed Identity:

```python
from azure.identity import ManagedIdentityCredential

credential = ManagedIdentityCredential()
token = credential.get_token("<app-registration-client-id>/.default")
```

**Note:** For Managed Identity callers, the token uses the **client credentials flow**
(no user involved). By default this works if the caller is in the same tenant. For
fine-grained control, use app role assignments (see Future section).

---

## Consent Model

Azure AD uses a three-party trust model:

```
Party 1: The API (your app registration)  — "I exist, here's who can access me"
Party 2: The Client (CLI, browser app,    — "I want a token to access the API"
          another service)
Party 3: The User (human signing in)       — "I consent to this client acting on my behalf"
```

**Consent** is the answer to: "Is this client allowed to request tokens for this API?"

| Consent type | Who grants it | Scope | When to use |
|-------------|---------------|-------|-------------|
| User consent | Each user, interactively | That user only | Dev/test (often disabled in corporate) |
| Admin consent | Tenant admin | All users in tenant | Corporate environments |
| Pre-authorization | App registration owner | Specific client, all users | Self-service, no admin needed |

**Corporate environments** typically disable user consent at the tenant level. This
means you need either admin consent or pre-authorization for every client that will
call your API. Pre-authorization is preferred because it doesn't require a support
ticket to the cloud admins.

### What to Request from Cloud Admins

If pre-authorization isn't sufficient (e.g., you need tenant-wide admin consent):

```
Request: Grant admin consent for app registration

App Registration: <display name>
App ID: <client-id>
Tenant: <tenant-id>

What this does: Allows users in our tenant to authenticate against
our geospatial tile server API. No external access — single-tenant only.

Action needed: Entra ID → Enterprise Applications → <app name>
→ Permissions → Grant admin consent
```

---

## Troubleshooting

### `AADSTS65001` — Consent required

The client application hasn't been consented or pre-authorized. Fix by:
1. Pre-authorizing the client on the app registration (Expose an API → Authorized clients)
2. Or requesting admin consent from tenant admins
3. Then clearing local token cache: `az account clear && az login`

### `401` with a valid token

Check the `allowedAudiences` in Easy Auth config. The token's `aud` claim must match
one of the allowed audiences. Common values:
- `api://<client-id>` (when using identifier URI)
- `<client-id>` (when using raw client ID as resource)

### `403` after successful login

The user is authenticated but from the wrong tenant, or the token has an unexpected
issuer. Verify the `openIdIssuer` matches your tenant.

### Browser not redirecting to login

If `unauthenticatedClientAction` is `Return401`, browsers get a raw 401. Either
change to `RedirectToLoginPage` or have your frontend redirect to `/.auth/login/aad`.

### Cached token errors

Azure CLI caches tokens aggressively. If you've changed app registration settings
(added scopes, pre-authorized clients), clear the cache:

```bash
az account clear
az login --tenant "<tenant-id>"
```

---

## App Roles — Two-Role Model

### Design

Two roles, two Entra security groups:

| App Role | Value | Entra Group | Who | Purpose |
|----------|-------|-------------|-----|---------|
| API User | `B2C` | All-users group (everyone in tenant) | All authenticated users | Gate: must have explicit group assignment to access the app |
| Admin | `Admin` | Geo admin group | Platform operators | Gate: admin-only endpoints |

The `B2C` role is not checked in application code — its purpose is to require explicit
group assignment at the **platform layer**. Without it, any tenant user can access the
app. With it, only users in the all-users group (or admin group) can get past Easy Auth.

The `Admin` role is checked in **application code** on specific endpoints.

```
User authenticates
    │
    ├── No app role assigned?  → 403 (Easy Auth rejects — platform layer)
    │
    ├── Has "B2C" role only?   → Normal API access (tiles, STAC, vector, etc.)
    │
    ├── Has "Admin" role?      → Normal API access + admin endpoints
```

A user can have both roles. Admin group members would typically also be in the
all-users group, or you assign both roles to the admin group.

### 1. Define App Roles

On the app registration under **App roles**, create two roles:

| Display Name | Value | Allowed member types |
|-------------|-------|----------------------|
| API User | `B2C` | Users/Groups |
| Admin | `Admin` | Users/Groups |

### 2. Assign Roles to Groups

In Entra ID → Enterprise Applications → your app → Users and groups:

| Group | Role assigned |
|-------|--------------|
| All-users group | `B2C` |
| Geo admin group | `Admin` |

### 3. Require Role Assignment (Platform Layer)

Update the Easy Auth config to require at least one app role. Users without any
role assignment get `403` at the platform layer — the request never reaches FastAPI:

```json
{
  "identityProviders": {
    "azureActiveDirectory": {
      "validation": {
        "defaultAuthorizationPolicy": {
          "allowedPrincipals": {
            "identities": ["*"]
          }
        }
      }
    }
  }
}
```

Alternatively, set **"Assignment required?"** to **Yes** on the Enterprise Application
in the Azure Portal. This achieves the same thing — only users with an app role
assignment can get a token.

### 4. Check Admin Role (Application Layer)

Easy Auth injects the `X-MS-CLIENT-PRINCIPAL` header on every authenticated request.
The application decodes it and checks the `roles` claim:

```
X-MS-CLIENT-PRINCIPAL: <base64-encoded JSON>
```

Decoded:
```json
{
  "claims": [
    { "typ": "roles", "val": "B2C" },
    { "typ": "roles", "val": "Admin" }
  ]
}
```

A FastAPI dependency reads this header and gates admin endpoints:

```python
from fastapi import Depends, HTTPException, Request
import base64, json

def require_admin(request: Request):
    """Dependency that requires the Admin app role."""
    principal = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not principal:
        raise HTTPException(status_code=401, detail="Not authenticated")

    claims = json.loads(base64.b64decode(principal))
    roles = [c["val"] for c in claims.get("claims", []) if c["typ"] == "roles"]

    if "Admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin role required")

# Usage:
@router.post("/admin/refresh-collections", dependencies=[Depends(require_admin)])
async def refresh_collections(): ...
```

### Admin-Gated Endpoints

| Endpoint | Router | Why |
|----------|--------|-----|
| `POST /admin/refresh-collections` | admin.py | Mutates catalog state |
| `GET /vector/diagnostics` | diagnostics.py | Exposes internal schema structure |
| `GET /vector/diagnostics/verbose` | diagnostics.py | Detailed DB state and permissions |
| `GET /vector/diagnostics/table/{name}` | diagnostics.py | Deep table inspection |

All other endpoints (tiles, STAC, vector features, health probes) remain accessible
to any authenticated user with the `B2C` role.

---

## Configuration Reference

### App Registration Settings

| Setting | Location | Value |
|---------|----------|-------|
| Sign-in audience | Authentication | Single tenant |
| Redirect URI | Authentication | `https://{hostname}/.auth/login/aad/callback` |
| ID tokens | Authentication | Enabled |
| Identifier URI | Expose an API | `api://{client-id}` |
| Scope | Expose an API | `access_as_user` (delegated) |
| Pre-authorized clients | Expose an API | Azure CLI, Portal, frontends |
| Client secret | Certificates & secrets | None needed |

### Easy Auth Settings (App Service)

| Setting | Value |
|---------|-------|
| Authentication | Enabled |
| Identity provider | Microsoft Entra ID |
| Client ID | App registration client ID |
| Issuer URL | `https://sts.windows.net/{tenant-id}/v2.0` |
| Allowed audiences | `api://{client-id}`, `{client-id}` |
| Unauthenticated action | Return 401 |
| Token store | Enabled |
