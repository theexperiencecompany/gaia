"""Login-free integration-connect links for bots / non-UI surfaces.

A bot user can't click an in-chat "Connect" card and isn't logged into a
browser. This mints a short-lived, single-use, scope-limited signed token they
can open in any browser to start the OAuth flow for ONE integration — no GAIA
login required, because the identity travels (signed) in the link.

Security properties:
- **Signed** (HS256, shared agent/bot secret) → unforgeable.
- **Role-scoped** (``integration_connect``) → cannot act as a session / agent /
  bot token; those verifiers reject this role and vice-versa.
- **Single integration** → bound to one ``integration_id``.
- **Single-use** → the ``jti`` is consumed atomically in Redis on first use.
- **Bounded lifetime** → ``CONNECT_LINK_TTL_HOURS``.
- The endpoint it points at only redirects into OAuth; it never returns data.

Minting is a pure local sign (no I/O), so it is cheap to do on every prompt.
The only Redis write happens once, when the link is actually opened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets

from jose import JWTError, jwt

from app.config.settings import settings
from app.constants.auth import CONNECT_LINK_ROLE, CONNECT_LINK_TTL_HOURS, JWT_ALGORITHM
from app.constants.cache import CONNECT_LINK_USED_PREFIX
from app.db.redis import redis_cache
from app.helpers.mcp_helpers import get_api_base_url
from shared.py.wide_events import log

CONNECT_LINK_PATH = "/api/v1/integrations/connect-link"


def create_connect_link_token(user_id: str, integration_id: str) -> str:
    """Sign a single-use, connect-scoped token for ``(user_id, integration_id)``."""
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "integration_id": integration_id,
        "role": CONNECT_LINK_ROLE,
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(hours=CONNECT_LINK_TTL_HOURS),
    }
    return jwt.encode(payload, settings.AGENT_SECRET, algorithm=JWT_ALGORITHM)


def build_connect_link_url(user_id: str, integration_id: str) -> str | None:
    """Full login-free connect URL to hand to a bot / non-UI user.

    Returns ``None`` when no signing secret is configured (dev/misconfig) so
    callers degrade to the generic integrations page instead of crashing.
    ``AGENT_SECRET`` is required in production, so this only no-ops in dev.
    """
    if not settings.AGENT_SECRET:
        log.warning("connect-link: AGENT_SECRET unset — falling back to generic connect prompt")
        return None
    token = create_connect_link_token(user_id, integration_id)
    return f"{get_api_base_url()}{CONNECT_LINK_PATH}?t={token}"


async def verify_and_consume_connect_link_token(token: str) -> tuple[str, str] | None:
    """Verify (signature, role, expiry) and atomically consume the token.

    Returns ``(user_id, integration_id)`` on the first valid use, else ``None``.
    Single-use is enforced with an atomic Redis ``SET NX`` on the token's
    ``jti``; the marker's TTL is the token's own remaining lifetime.
    """
    try:
        payload = jwt.decode(token, settings.AGENT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        log.warning(f"connect-link token rejected (invalid/expired): {e}")
        return None

    if payload.get("role") != CONNECT_LINK_ROLE:
        log.warning("connect-link token rejected: wrong role")
        return None

    user_id = payload.get("sub")
    integration_id = payload.get("integration_id")
    jti = payload.get("jti")
    if not (user_id and integration_id and jti):
        log.warning("connect-link token rejected: missing claims")
        return None

    remaining = int(payload.get("exp", 0) - datetime.now(UTC).timestamp())
    if remaining <= 0:
        return None

    first_use = await redis_cache.client.set(
        f"{CONNECT_LINK_USED_PREFIX}:{jti}", "1", nx=True, ex=remaining
    )
    if not first_use:
        log.warning("connect-link token rejected: already used")
        return None

    log.set(auth={"user_id": str(user_id), "provider": str(integration_id)})
    return str(user_id), str(integration_id)
