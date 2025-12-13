"""
Blog authentication dependencies using Bearer token.
"""

from typing import Optional
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Initialize the security scheme
security = HTTPBearer()


async def verify_blog_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """
    Verify the bearer token for blog management operations.

    Args:
        credentials: HTTP Authorization credentials with Bearer token

    Returns:
        str: The validated token

    Raises:
        HTTPException: If token is invalid or missing
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid authorization code"
        )

    from app.config.settings import settings

    # Get the expected token from settings
    expected_token = settings.BLOG_BEARER_TOKEN

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Blog management token not configured",
        )

    # Verify the token
    if credentials.credentials != expected_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid bearer token"
        )

    return credentials.credentials


async def get_optional_blog_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Optional[str]:
    """
    Optional bearer token verification for endpoints that can be public or protected.

    Args:
        credentials: Optional HTTP Authorization credentials

    Returns:
        Optional[str]: The token if valid, None if not provided
    """
    if not credentials:
        return None

    try:
        return await verify_blog_token(credentials)
    except HTTPException:
        return None
