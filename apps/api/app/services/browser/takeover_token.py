"""Short-lived signed tokens that let a bot user open a browser live view.

A takeover token authorizes one user to watch (and, during a handoff, drive) one
browser session over the live-view WebSocket without a web login; it is embedded
in the link a bot delivers to that user's own channel. Same JWT shape as
bot_token_service (jose HS256, dedicated secret, role claim, 15-min exp); the
secret never overlaps with the bot-session secret so a leak is contained.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time
from typing import TypedDict

from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM

_TAKEOVER_ROLE = "browser_takeover"
_TAKEOVER_TOKEN_EXPIRY_MINUTES = 15
_MIN_SECRET_LENGTH = 32


class TakeoverTokenClaims(TypedDict):
    """The verified claims of a takeover token — always signature-checked."""

    session_id: str
    user_id: str
    # Verified expiry timestamp (seconds since epoch) so a connection's remaining
    # lifetime is always read from a validated claim, never an unverified parse.
    exp: float


def create_takeover_token(session_id: str, user_id: str) -> str:
    """Mint a 15-minute token binding user_id to one browser session_id."""
    secret = _get_takeover_secret()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "session_id": session_id,
        "role": _TAKEOVER_ROLE,
        "exp": now + timedelta(minutes=_TAKEOVER_TOKEN_EXPIRY_MINUTES),
        "iat": now,
    }
    token: str = jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
    return token


_MISSING_CLAIMS_MESSAGE = "Takeover token missing session_id, subject, or expiry"


class _TakeoverPayload(BaseModel):
    """The decoded token as jose hands it back, before the claims are checked."""

    model_config = ConfigDict(extra="ignore", strict=True)

    role: str | None = None
    session_id: str | None = None
    sub: str | None = None
    exp: float | None = None


def verify_takeover_token(token: str) -> TakeoverTokenClaims:
    """Decode and validate a takeover token, returning {session_id, user_id, exp}.

    exp is the verified expiry timestamp (seconds since epoch) so the caller
    can bound a connection's lifetime without ever reading an *unverified* claim.
    Raises :class:jose.JWTError if the signature, role, expiry, or required
    claims are invalid — the caller rejects the connection on any failure.
    """
    secret = _get_takeover_secret()
    try:
        # NOSONAR python:S5659 — false positive: the signature IS verified. jose
        # verifies whenever a key and an algorithm allow-list are supplied, and both
        # are here; there is no verify_signature=False anywhere in this module.
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])  # NOSONAR python:S5659
    except JWTError as exc:
        raise JWTError(f"Takeover token verification failed: {exc!s}") from exc

    try:
        claims = _TakeoverPayload.model_validate(payload)
    except ValidationError as exc:
        raise JWTError(_MISSING_CLAIMS_MESSAGE) from exc
    if claims.role != _TAKEOVER_ROLE:
        raise JWTError("Invalid token role")
    if claims.session_id is None or claims.sub is None or claims.exp is None:
        raise JWTError(_MISSING_CLAIMS_MESSAGE)

    return {"session_id": claims.session_id, "user_id": claims.sub, "exp": claims.exp}


def takeover_token_ttl_seconds(claims: TakeoverTokenClaims) -> float:
    """Return seconds until an already-verified token expires (0 or less once past).

    Bounds the live-view WebSocket to the token's lifetime. claims must come
    from verify_takeover_token; no unverified claim is ever trusted here.
    """
    return claims["exp"] - time.time()


def _get_takeover_secret() -> str:
    """Return the dedicated HS256 secret for takeover tokens (>= 32 chars, or raise)."""
    secret: str | None = settings.BROWSER_TAKEOVER_TOKEN_SECRET

    if not secret:
        raise ValueError(
            "BROWSER_TAKEOVER_TOKEN_SECRET is required for browser takeover token signing. "
            "Generate with: openssl rand -hex 32"
        )

    if len(secret) < _MIN_SECRET_LENGTH:
        raise ValueError(
            f"BROWSER_TAKEOVER_TOKEN_SECRET must be at least {_MIN_SECRET_LENGTH} characters "
            f"(current: {len(secret)})"
        )

    return secret
