"""Device connect-token minting/verification and refresh-credential hashing.

The daemon presents a short-lived JWT (``aud=device-bridge``) on the WebSocket
upgrade. It obtains that JWT by exchanging a long-lived refresh credential, which
rotates on every exchange. We store only the SHA-256 of the refresh credential.
"""

from datetime import UTC, datetime, timedelta
import hashlib
import secrets

from jose import JWTError, jwt

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM
from app.constants.device_bridge import (
    DEVICE_TOKEN_AUDIENCE,
    DEVICE_TOKEN_EXPIRY_MINUTES,
    REFRESH_TOKEN_BYTES,
)
from app.schemas.device.responses import DeviceTokenClaims

_SECRET = settings.AGENT_SECRET


def hash_refresh_token(token: str) -> str:
    """SHA-256 of a refresh credential — what we persist, never the plaintext."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> str:
    """Mint a fresh opaque refresh credential."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def create_device_token(device_id: str, user_id: str) -> tuple[str, int]:
    """Mint a short-lived device connect JWT. Returns ``(token, expires_in_seconds)``."""
    expires_in = DEVICE_TOKEN_EXPIRY_MINUTES * 60
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "device_id": device_id,
        "aud": DEVICE_TOKEN_AUDIENCE,
        "role": "device",
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, _SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_in


def verify_device_token(token: str) -> DeviceTokenClaims | None:
    """Verify a device connect JWT. Returns ``{user_id, device_id}`` or ``None``.

    The audience check is what stops a chat agent-token or any other HS256 token
    signed with the same secret from authenticating as a device.
    """
    try:
        payload = jwt.decode(
            token,
            _SECRET,
            algorithms=[JWT_ALGORITHM],
            audience=DEVICE_TOKEN_AUDIENCE,
        )
    except JWTError:
        return None
    if payload.get("role") != "device":
        return None
    user_id = payload.get("sub")
    device_id = payload.get("device_id")
    if not user_id or not device_id:
        return None
    return DeviceTokenClaims(user_id=str(user_id), device_id=str(device_id))
