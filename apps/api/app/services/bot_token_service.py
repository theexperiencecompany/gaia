"""Bot Session Token Service.

JWT-based session tokens for bot authentication. Prevents user impersonation
by issuing tokens only after legitimate platform messages.
"""

from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM


class BotSessionClaims(BaseModel):
    """The identity claims ``verify_bot_session_token`` decodes from a bot JWT.

    Each is optional: a token missing any of them authenticates nobody.
    """

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None


class _BotTokenPayload(BaseModel):
    """The raw claims of a bot session JWT."""

    model_config = ConfigDict(extra="ignore")

    sub: str | None = None
    role: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None


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


def verify_bot_session_token(token: str) -> BotSessionClaims:
    """Decode and verify a bot session token, returning user_id/platform/platform_user_id.

    Raises InvalidTokenError if invalid, expired, malformed, or not a bot-role token.
    """
    secret = _get_bot_session_secret()

    try:
        payload = _BotTokenPayload.model_validate(
            jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        )

        # Verify it's a bot session token
        if payload.role != "bot":
            raise jwt.InvalidTokenError("Invalid token role")

        return BotSessionClaims(
            user_id=payload.sub,
            platform=payload.platform,
            platform_user_id=payload.platform_user_id,
        )

    except (jwt.PyJWTError, ValidationError) as e:
        raise jwt.InvalidTokenError(f"Token verification failed: {e!s}") from e


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
