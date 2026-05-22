"""
Blog authentication dependencies using Bearer token.
"""

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import settings

security = HTTPBearer()


async def verify_blog_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """
    Verify the bearer token for blog management operations.

    Uses constant-time comparison to prevent timing attacks against the
    configured BLOG_BEARER_TOKEN.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid authorization code"
        )

    expected_token = settings.BLOG_BEARER_TOKEN

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Blog management token not configured",
        )

    if not secrets.compare_digest(credentials.credentials, expected_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid bearer token")

    return credentials.credentials
