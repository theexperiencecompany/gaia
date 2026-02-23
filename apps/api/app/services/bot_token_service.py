"""Bot Session Token Service.

JWT-based session tokens for bot authentication. Prevents user impersonation
by issuing tokens only after legitimate platform messages.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM

# Default bot session token expiry (15 minutes)
BOT_SESSION_TOKEN_EXPIRY_MINUTES = 15


def create_bot_session_token(
    user_id: str,
    platform: str,
    platform_user_id: str,
    expires_minutes: int = BOT_SESSION_TOKEN_EXPIRY_MINUTES,
) -> str:
    """Create JWT session token for bot authentication.

    Args:
        user_id: Internal user ID from database
        platform: Bot platform (discord/slack/telegram)
        platform_user_id: Platform-specific user ID
        expires_minutes: Token expiry time in minutes (default: 15)

    Returns:
        JWT token string

    Example:
        token = create_bot_session_token(
            user_id="user_123",
            platform="discord",
            platform_user_id="123456789",
            expires_minutes=15
        )
    """
    secret = _get_bot_session_secret()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

    payload = {
        "sub": user_id,  # Subject: internal user ID
        "platform": platform,
        "platform_user_id": platform_user_id,
        "role": "bot",  # Identifies this as a bot session token
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_bot_session_token(token: str) -> dict:
    """Verify and decode bot session token.

    Args:
        token: JWT token string

    Returns:
        dict: Decoded payload with user_id, platform, platform_user_id

    Raises:
        JWTError: If token is invalid, expired, or malformed

    Example:
        try:
            payload = verify_bot_session_token(token)
            user_id = payload["user_id"]
            platform = payload["platform"]
        except JWTError:
            # Handle invalid token
            pass
    """
    secret = _get_bot_session_secret()

    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])

        # Verify it's a bot session token
        if payload.get("role") != "bot":
            raise JWTError("Invalid token role")

        return {
            "user_id": payload.get("sub"),
            "platform": payload.get("platform"),
            "platform_user_id": payload.get("platform_user_id"),
        }

    except JWTError as e:
        raise JWTError(f"Token verification failed: {str(e)}") from e


def _get_bot_session_secret() -> str:
    """Get bot session token secret key. Requires dedicated secret.

    Returns:
        Secret key for JWT signing

    Raises:
        ValueError: If BOT_SESSION_TOKEN_SECRET is not configured or too short
    """
    secret = getattr(settings, "BOT_SESSION_TOKEN_SECRET", None)

    if not secret:
        raise ValueError(
            "BOT_SESSION_TOKEN_SECRET is required for JWT signing. "
            "Generate with: openssl rand -hex 32"
        )

    if len(secret) < 32:
        raise ValueError(
            f"BOT_SESSION_TOKEN_SECRET must be at least 32 characters (current: {len(secret)})"
        )

    return secret
