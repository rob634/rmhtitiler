"""
App role authorization for Easy Auth.

Reads the X-MS-CLIENT-PRINCIPAL header injected by Azure App Service Easy Auth,
extracts app role claims, and provides FastAPI dependencies for role-based gating.

When GEOTILER_ENABLE_ADMIN_AUTH=false (default), all role checks are no-ops.
This allows local development without Easy Auth configured.
"""

import base64
import json
import logging
from typing import Optional

from fastapi import HTTPException, Request

from geotiler.config import settings

logger = logging.getLogger(__name__)


def _get_roles(request: Request) -> list[str]:
    """Extract app roles from the X-MS-CLIENT-PRINCIPAL header."""
    header = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not header:
        return []

    try:
        decoded = json.loads(base64.b64decode(header))
        claims = decoded.get("claims", [])
        return [c["val"] for c in claims if c.get("typ") == "roles"]
    except Exception as e:
        logger.warning(f"Failed to decode X-MS-CLIENT-PRINCIPAL: {e}")
        return []


def require_admin(request: Request) -> Optional[list[str]]:
    """
    FastAPI dependency that requires the Admin app role.

    No-op when GEOTILER_ENABLE_ADMIN_AUTH=false (local dev).
    Returns the user's roles list on success.
    """
    if not settings.enable_admin_auth:
        return []

    roles = _get_roles(request)
    if not roles:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if "Admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin role required")

    return roles
