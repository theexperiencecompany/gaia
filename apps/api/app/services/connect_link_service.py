"""Login-free integration-connect links for bots / non-UI surfaces.

A bot user can't click an in-chat "Connect" card and isn't logged into a
browser. This mints a short, single-use link they can open in any browser to
start the OAuth flow for ONE integration — no GAIA login required, because the
link itself is the credential.

Security properties:
- **High-entropy opaque code** (96-bit, ``secrets.token_urlsafe``) → unguessable;
  the only way to test a code is an online request to the (rate-limited)
  connect-link endpoint — there is no offline oracle.
- **Server-side binding** → the code maps to one ``(user_id, integration_id)``
  in Redis; nothing sensitive travels in the link.
- **Single-use** → consumed atomically with ``GETDEL`` on first open, so a
  second open (or a brute-force hit racing a real user) gets nothing.
- **Bounded lifetime** → ``CONNECT_LINK_TTL_MINUTES``.
- The endpoint it points at only redirects into OAuth; it never returns data.
"""

from __future__ import annotations

import secrets

from app.config.settings import settings
from app.constants.auth import CONNECT_LINK_CODE_BYTES, CONNECT_LINK_TTL_MINUTES
from app.constants.cache import CONNECT_LINK_PREFIX
from app.db.redis import get_and_delete_cache, set_cache
from shared.py.wide_events import log

CONNECT_LINK_FRONTEND_PATH = "/connect"


def _code_key(code: str) -> str:
    return f"{CONNECT_LINK_PREFIX}:{code}"


async def build_connect_link_url(user_id: str, integration_id: str) -> str | None:
    """Mint a single-use connect link pointing at the frontend ``/connect/<code>``.

    Stores the ``(user_id, integration_id)`` binding in Redis under a fresh
    high-entropy code and returns the frontend URL. Returns ``None`` when the
    binding can't be stored (Redis unavailable/failed) so callers degrade to a
    generic connect prompt instead of handing out a link that can't resolve.
    """
    code = secrets.token_urlsafe(CONNECT_LINK_CODE_BYTES)
    stored = await set_cache(
        _code_key(code),
        {"user_id": user_id, "integration_id": integration_id},
        ttl=CONNECT_LINK_TTL_MINUTES * 60,
    )
    if not stored:
        log.warning("connect-link: could not store code (Redis unavailable) — generic prompt")
        return None

    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}{CONNECT_LINK_FRONTEND_PATH}/{code}"


async def resolve_and_consume_connect_code(code: str) -> tuple[str, str] | None:
    """Atomically consume a connect code, returning ``(user_id, integration_id)``.

    The code is deleted on first read (``GETDEL``), enforcing single-use. Returns
    ``None`` for an unknown, expired, or already-consumed code.
    """
    data = await get_and_delete_cache(_code_key(code))
    if not isinstance(data, dict):
        return None

    user_id = data.get("user_id")
    integration_id = data.get("integration_id")
    if not (user_id and integration_id):
        return None

    log.set(auth={"user_id": str(user_id), "provider": str(integration_id)})
    return str(user_id), str(integration_id)
