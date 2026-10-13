"""Login-free integration-connect links for bots / non-UI surfaces.

A bot user can't click an in-chat "Connect" card and isn't logged into a
browser. This mints a short, single-use link they can open in any browser to
start the OAuth flow for ONE integration — no GAIA login required, because the
link itself is the credential.

Security properties: a high-entropy opaque code (96-bit, secrets.token_urlsafe)
testable only via the rate-limited connect-link endpoint (no offline oracle);
server-side binding, so nothing sensitive travels in the link; single-use via
atomic GETDEL on first open; a bounded lifetime (CONNECT_LINK_TTL_MINUTES);
and an endpoint that only redirects into OAuth, never returns data.
"""

from __future__ import annotations

import secrets

from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import settings
from app.constants.auth import CONNECT_LINK_CODE_BYTES, CONNECT_LINK_TTL_MINUTES
from app.constants.cache import CONNECT_LINK_PREFIX
from app.db.redis import get_and_delete_cache, set_cache
from shared.py.wide_events import log

CONNECT_LINK_FRONTEND_PATH = "/connect"


def _code_key(code: str) -> str:
    return f"{CONNECT_LINK_PREFIX}:{code}"


class ConnectLinkBinding(BaseModel):
    """Who a connect link signs in, and to what; stored server-side under the link's code."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1)
    integration_id: str = Field(min_length=1)
    # The expired account to sign back in; None starts a new connection.
    account_id: str | None = None


async def build_connect_link_url(
    user_id: str, integration_id: str, account_id: str | None = None
) -> str | None:
    """Mint a single-use connect link pointing at the frontend /connect/<code>.

    Returns None when the binding can't be stored (Redis unavailable/failed) so
    callers degrade to a generic connect prompt instead of handing out a link
    that can't resolve.
    """
    code = secrets.token_urlsafe(CONNECT_LINK_CODE_BYTES)
    binding = ConnectLinkBinding(
        user_id=user_id, integration_id=integration_id, account_id=account_id
    )
    stored = await set_cache(
        _code_key(code), binding, ttl=CONNECT_LINK_TTL_MINUTES * 60, model=ConnectLinkBinding
    )
    if not stored:
        log.warning("connect-link: could not store code (Redis unavailable) — generic prompt")
        return None

    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}{CONNECT_LINK_FRONTEND_PATH}/{code}"


async def resolve_and_consume_connect_code(code: str) -> ConnectLinkBinding | None:
    """Atomically consume a connect code; None for an unknown, expired, or already-used one.

    The code is deleted on first read (GETDEL), enforcing single-use.
    """
    binding = await get_and_delete_cache(_code_key(code), ConnectLinkBinding)
    if binding is None:
        return None
    log.set(auth={"user_id": binding.user_id, "provider": binding.integration_id})
    return binding
