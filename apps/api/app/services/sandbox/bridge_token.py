"""Sandbox bridge connect-token minting/verification.

Minted at acquire time; the in-sandbox bridge client presents the token on
the /ws/sandbox upgrade and re-dials with a fresh one on every resume (an
E2B pause kills the socket). Mirrors services/device/device_auth.py: a
distinct audience stops cross-replay, and the role claim stops any other
HS256 token signed with the same secret from authenticating as a sandbox.
"""

from datetime import UTC, datetime, timedelta
from typing import TypedDict

from jose import JWTError, jwt

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM
from app.constants.sandbox import SANDBOX_TOKEN_AUDIENCE, SANDBOX_TOKEN_EXPIRY_MINUTES

_SECRET = settings.AGENT_SECRET


class SandboxBridgeClaims(TypedDict):
    """Claims carried by a sandbox bridge JWT."""

    user_id: str
    sandbox_id: str


def mint_sandbox_bridge_token(user_id: str, sandbox_id: str) -> tuple[str, int]:
    """Mint a short-lived sandbox bridge JWT. Returns (token, expires_in_seconds)."""
    expires_in = SANDBOX_TOKEN_EXPIRY_MINUTES * 60
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "sandbox_id": sandbox_id,
        "aud": SANDBOX_TOKEN_AUDIENCE,
        "role": "sandbox",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, _SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_in


def verify_sandbox_bridge_token(token: str) -> SandboxBridgeClaims | None:
    """Verify a sandbox bridge JWT. Returns {user_id, sandbox_id} or None.

    The audience check is what stops a device token, a chat agent-token, or
    any other HS256 token signed with the same secret from authenticating
    as a sandbox.
    """
    try:
        payload = jwt.decode(
            token,
            _SECRET,
            algorithms=[JWT_ALGORITHM],
            audience=SANDBOX_TOKEN_AUDIENCE,
        )
    except JWTError:
        return None
    if payload.get("role") != "sandbox":
        return None
    user_id = payload.get("sub")
    sandbox_id = payload.get("sandbox_id")
    if not user_id or not sandbox_id:
        return None
    return SandboxBridgeClaims(user_id=str(user_id), sandbox_id=str(sandbox_id))
