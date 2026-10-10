"""Bot Session Token Service.

JWT-based session tokens for bot authentication. Prevents user impersonation
by issuing tokens only after legitimate platform messages.
"""

from datetime import UTC, datetime, timedelta

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
    """Create a signed JWT session token for bot authentication."""
    secret = _get_bot_session_secret()
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)

    payload = {
        "sub": user_id,  # Subject: internal user ID
        "platform": platform,
        "platform_user_id": platform_user_id,
        "role": "bot",  # Identifies this as a bot session token
        "exp": expire,
        "iat": datetime.now(UTC),
    }

    token: str = jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
    return token


def verify_bot_session_token(token: str) -> dict:
    """Decode and verify a bot session token, returning user_id/platform/platform_user_id.

    Raises JWTError if invalid, expired, malformed, or not a bot-role token.
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
        raise JWTError(f"Token verification failed: {e!s}") from e


def _get_bot_session_secret() -> str:
    """Return BOT_SESSION_TOKEN_SECRET, requiring at least 32 characters.

    Raises ValueError if unset or too short.
    """
    secret: str | None = getattr(settings, "BOT_SESSION_TOKEN_SECRET", None)

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
