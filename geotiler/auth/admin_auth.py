"""
Azure AD authentication for admin endpoints.

Validates Bearer tokens from Azure AD to ensure only authorized apps
(like Orchestrator) can call /admin/* endpoints.

Usage:
    from geotiler.auth.admin_auth import require_admin_auth

    @router.post("/admin/something", dependencies=[Depends(require_admin_auth)])
    async def admin_endpoint():
        ...

Configuration:
    GEOTILER_ENABLE_ADMIN_AUTH=true              # Enable auth (default: false for local dev)
    GEOTILER_ADMIN_ALLOWED_APP_IDS=<id1>,<id2>  # Comma-separated MI client IDs
    AZURE_TENANT_ID=<tenant-id>                 # Your Azure AD tenant
"""

import logging
from typing import Optional
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Request, status

from geotiler.config import settings

logger = logging.getLogger(__name__)

# Azure AD OpenID Connect metadata URL template
AZURE_AD_OPENID_CONFIG_URL = (
    "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
)

# Azure AD JWKS (JSON Web Key Set) URL template
AZURE_AD_JWKS_URL = "https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"


@lru_cache(maxsize=1)
def get_jwks_client() -> Optional[PyJWKClient]:
    """
    Get cached JWKS client for Azure AD token validation.

    Returns None if admin auth is not configured.
    """
    if not settings.azure_tenant_id:
        return None

    jwks_url = AZURE_AD_JWKS_URL.format(tenant_id=settings.azure_tenant_id)
    return PyJWKClient(jwks_url, cache_keys=True)


def validate_azure_ad_token(token: str) -> dict:
    """
    Validate an Azure AD JWT token.

    Args:
        token: The JWT token string (without 'Bearer ' prefix)

    Returns:
        Decoded token claims if valid

    Raises:
        HTTPException: If token is invalid, expired, or from wrong issuer/app
    """
    if not settings.azure_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin auth enabled but AZURE_TENANT_ID not configured",
        )

    jwks_client = get_jwks_client()
    if not jwks_client:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize JWKS client",
        )

    try:
        # Get the signing key from Azure AD's JWKS
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Expected issuer for v2.0 tokens
        expected_issuer = f"https://login.microsoftonline.com/{settings.azure_tenant_id}/v2.0"

        # Decode and validate the token
        decoded = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=expected_issuer,
            options={
                # Audience verification is disabled because service-to-service
            # MI tokens use varying audience values (e.g. https://management.azure.com
            # or the app's own ID). Instead, we extract and verify the caller's
            # app/client ID from azp/appid claims against ADMIN_ALLOWED_APP_IDS.
            "verify_aud": False,
                "verify_exp": True,
                "verify_iss": True,
            },
        )

        return decoded

    except jwt.ExpiredSignatureError:
        logger.warning("Admin auth: Token has expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidIssuerError:
        logger.warning("Admin auth: Invalid token issuer")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        logger.warning(f"Admin auth: Token validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_app_id_from_token(claims: dict) -> Optional[str]:
    """
    Extract the application/client ID from token claims.

    Azure AD tokens may have the app ID in different claims depending on the flow:
    - 'azp' (authorized party) - OAuth 2.0 flows
    - 'appid' - v1.0 tokens
    - 'app_id' - some MI tokens
    - 'oid' (object ID) - can be used as fallback for MI

    Returns:
        The app/client ID or None if not found
    """
    # Try different claim names used by Azure AD
    for claim in ["azp", "appid", "app_id"]:
        if claim in claims:
            return claims[claim]

    return None


async def require_admin_auth(request: Request) -> Optional[dict]:
    """
    FastAPI dependency that validates Azure AD tokens for admin endpoints.

    When GEOTILER_ENABLE_ADMIN_AUTH=false, this is a no-op (allows all requests).
    When enabled, validates the Bearer token and checks the caller's app ID.

    Args:
        request: The FastAPI request

    Returns:
        Decoded token claims if auth enabled and valid, None if auth disabled

    Raises:
        HTTPException: 401 if token missing/invalid, 403 if app not authorized
    """
    # If auth is disabled, allow all requests (local dev mode)
    if not settings.enable_admin_auth:
        logger.debug("Admin auth disabled, allowing request")
        return None

    # Check for Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        logger.warning("Admin auth: Missing Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract Bearer token
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("Admin auth: Invalid Authorization header format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]

    # Validate the token
    claims = validate_azure_ad_token(token)

    # Extract and verify the app ID
    app_id = get_app_id_from_token(claims)
    if not app_id:
        logger.warning(f"Admin auth: Could not extract app ID from token. Claims: {list(claims.keys())}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not extract application ID from token",
        )

    # Check if this app is allowed
    allowed_apps = settings.admin_allowed_app_id_list
    if not allowed_apps:
        logger.warning("Admin auth: GEOTILER_ADMIN_ALLOWED_APP_IDS not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin auth enabled but GEOTILER_ADMIN_ALLOWED_APP_IDS not configured",
        )

    if app_id not in allowed_apps:
        logger.warning(f"Admin auth: App {app_id} not in allowed list")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Application {app_id} is not authorized to access admin endpoints",
        )

    logger.info(f"Admin auth: Authorized request from app {app_id}")
    return claims
