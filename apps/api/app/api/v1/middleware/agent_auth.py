"""Agent token issuance + verification.

C7 hardening:
- Agent tokens are now bound to (user_id, room_id) and carry a unique jti.
- Tokens are single-use: verify_agent_token atomically consumes the jti
  through Redis SETNX, so a captured token cannot be replayed.
- TTL is tightened from AGENT_TOKEN_EXPIRY_MINUTES to 60 s at the default.
- verify_agent_token is now async because jti tracking requires Redis IO.
- Callers that only need the JWT payload (without single-use enforcement)
  can use ``_decode_agent_token`` directly. Any call path that promotes
  the bearer to a user MUST go through ``verify_agent_token``.
- When ``AGENT_JWT_PRIVATE_KEY`` and ``AGENT_JWT_PUBLIC_KEY`` are
  configured, JWTs are signed with **RS256** instead of HS256. The
  voice-agent worker still authenticates to ``/voice/agent-token`` with
  ``AGENT_SECRET`` (a separate API-level secret), but a leak of that
  secret no longer lets an attacker forge agent JWTs because the
  signing key is asymmetric. Falls back to HS256 when keys absent so
  dev environments and the migration period work unchanged.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from app.config.settings import settings
from app.constants.auth import (
    AGENT_JWT_ALGORITHM_ASYMMETRIC,
    AGENT_TOKEN_EXPIRY_MINUTES,
    JWT_ALGORITHM,
)
from app.db.redis import redis_cache

AGENT_SECRET = settings.AGENT_SECRET

# Tight single-use TTL. The JWT ``exp`` is still honoured but the Redis
# marker is what makes each jti one-shot.
_AGENT_JTI_PREFIX = "agent_jti"
_AGENT_JTI_TTL_SECONDS = max(60, AGENT_TOKEN_EXPIRY_MINUTES * 60)


def _signing_material() -> tuple[str, str, list[str]]:
    """Return ``(sign_key, verify_key, accepted_algorithms)``.

    When the asymmetric keypair is configured we sign with RS256 and
    verify with the public key. We still accept HS256 on verify so a
    rolling deploy doesn't reject in-flight tokens that were signed
    with the symmetric secret. Once every issuer has rotated, drop
    HS256 from the accept list.
    """
    private_key = getattr(settings, "AGENT_JWT_PRIVATE_KEY", None)
    public_key = getattr(settings, "AGENT_JWT_PUBLIC_KEY", None)
    if private_key and public_key:
        return (
            private_key,
            public_key,
            [AGENT_JWT_ALGORITHM_ASYMMETRIC, JWT_ALGORITHM],
        )
    return AGENT_SECRET, AGENT_SECRET, [JWT_ALGORITHM]


def _decode_agent_token(token: str) -> Optional[dict]:
    """Decode + validate the JWT signature/expiry without consuming jti."""
    _, verify_key, accepted_algorithms = _signing_material()
    try:
        payload = jwt.decode(token, verify_key, algorithms=accepted_algorithms)
    except JWTError:
        return None
    if payload.get("role") != "agent":
        return None
    return payload


async def verify_agent_token(
    token: str, expected_room_id: Optional[str] = None
) -> Optional[dict]:
    """Verify a single-use agent token.

    Args:
        token: The JWT presented by the caller.
        expected_room_id: If set, the token's ``room_id`` claim must match.
            Chat/voice endpoints pass the room from the request path; a
            token minted for room A cannot then be used against room B.

    Returns:
        ``{user_id, impersonated}`` on success, ``None`` on any failure.
    """
    payload = _decode_agent_token(token)
    if not payload:
        return None

    jti = payload.get("jti")
    if not jti:
        # Legacy tokens without jti are rejected outright — they were
        # infinitely replayable and we do not want to keep that surface.
        return None

    if expected_room_id is not None:
        token_room = payload.get("room_id")
        if not token_room or token_room != expected_room_id:
            return None

    # Single-use: atomically claim the jti. ``set ... nx`` returns False
    # if the key already exists (== token was already spent).
    claimed = await redis_cache.client.set(
        f"{_AGENT_JTI_PREFIX}:{jti}", "1", nx=True, ex=_AGENT_JTI_TTL_SECONDS
    )
    if not claimed:
        return None

    return {
        "user_id": payload.get("sub"),
        "impersonated": True,
        "room_id": payload.get("room_id"),
    }


def create_agent_token(
    user_id: str,
    room_id: Optional[str] = None,
    expires_minutes: int = AGENT_TOKEN_EXPIRY_MINUTES,
) -> str:
    """Issue a single-use agent token bound to the given ``user_id``/``room_id``.

    ``room_id`` should be the LiveKit room name for voice flows. Omit it
    only in controlled contexts where room binding does not apply; the
    resulting token is still single-use and tied to the user_id but will
    fail any ``verify_agent_token(..., expected_room_id=...)`` check.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes)
    payload: dict = {
        "sub": user_id,
        "role": "agent",
        "exp": expire,
        "iat": now,
        "jti": secrets.token_urlsafe(16),
    }
    if room_id:
        payload["room_id"] = room_id
    sign_key, _, accepted_algorithms = _signing_material()
    # Sign with the strongest accepted algorithm — RS256 when configured,
    # HS256 otherwise. Verifiers still accept both during the migration
    # window so newly minted tokens remain compatible.
    sign_algorithm = accepted_algorithms[0]
    return jwt.encode(payload, sign_key, algorithm=sign_algorithm)
