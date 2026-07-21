"""Steel session lifecycle — create, connect-URL resolution, guaranteed release.

The *infrastructure* layer: it knows about Steel (via ``steel-sdk``) and nothing
about Browser-Use or the agent. The session is always released on exit —
success, error, or cancellation — so no browser is ever orphaned. Supports
automatic CAPTCHA solving, persistent profiles (restored auth), and a live-view
URL served from our own domain.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.services.browser.exceptions import BrowserUnavailableError
from shared.py.wide_events import log

if TYPE_CHECKING:
    from steel import AsyncSteel

_SELF_HOST_API_KEY_PLACEHOLDER = "self-hosted"


@dataclass(frozen=True, slots=True)
class SteelBrowserSession:
    session_id: str
    cdp_url: str
    debug_url: str | None
    live_view_url: str | None
    profile_id: str | None


def build_steel_client() -> AsyncSteel:
    """Construct an ``AsyncSteel`` pointed at the configured Steel instance.
    ``steel`` is imported lazily so the module loads without the SDK present."""
    from steel import AsyncSteel  # noqa: PLC0415

    return AsyncSteel(
        base_url=settings.STEEL_API_URL,
        steel_api_key=settings.STEEL_API_KEY or _SELF_HOST_API_KEY_PLACEHOLDER,
    )


def resolve_cdp_url(session_id: str, websocket_url: str) -> str:
    """CDP connect URL Browser-Use attaches to. Defaults to Steel's advertised
    ``websocketUrl``; ``STEEL_CDP_CONNECT_URL`` overrides for split networks."""
    override = settings.STEEL_CDP_CONNECT_URL
    if override:
        return override.format(session_id=session_id) if "{session_id}" in override else override
    return websocket_url


def resolve_live_view_url(session_id: str, session_viewer_url: str | None) -> str | None:
    """Live-view URL for the card. Prefers our own domain
    (``STEEL_LIVE_VIEW_BASE_URL``, e.g. https://browser.heygaia.io) so the link
    never exposes Steel directly; falls back to Steel's ``sessionViewerUrl``."""
    base = settings.STEEL_LIVE_VIEW_BASE_URL
    if base:
        return f"{base.rstrip('/')}/sessions/{session_id}"
    return session_viewer_url


@asynccontextmanager
async def steel_session(
    *,
    profile_id: str | None = None,
    block_ads: bool = True,
) -> AsyncIterator[SteelBrowserSession]:
    """Create a Steel session, yield it, and always release it.

    Raises :class:`BrowserUnavailableError` if Steel cannot create the session.
    ``profile_id`` restores a persisted authenticated context when provided.
    """
    client = build_steel_client()
    ttl_ms = settings.BROWSER_USE_SESSION_TTL_SECONDS * 1000

    # persist_profile makes Steel save the authenticated context back to a
    # profile (creating one and returning its id on first use, reusing the given
    # one otherwise) — without it, ``created.profile_id`` is never populated and
    # "log in once, reuse next time" silently never works.
    create_kwargs: dict = {
        "block_ads": block_ads,
        "api_timeout": ttl_ms,
        "persist_profile": True,
    }
    if settings.BROWSER_USE_SOLVE_CAPTCHA:
        create_kwargs["solve_captcha"] = True
    if profile_id:
        create_kwargs["profile_id"] = profile_id

    try:
        created = await client.sessions.create(**create_kwargs)
    except Exception as exc:  # noqa: BLE001 — translate any SDK/transport failure
        await client.close()
        raise BrowserUnavailableError(
            f"Could not create a Steel browser session at {settings.STEEL_API_URL}: {exc}"
        ) from exc

    session = SteelBrowserSession(
        session_id=created.id,
        cdp_url=resolve_cdp_url(created.id, created.websocket_url),
        debug_url=getattr(created, "debug_url", None),
        live_view_url=resolve_live_view_url(
            created.id, getattr(created, "session_viewer_url", None)
        ),
        profile_id=getattr(created, "profile_id", None) or profile_id,
    )
    log.set(browser={"session_id": session.session_id, "operation": "create"})
    log.info(f"{LogTag.AGENT} Steel session created: {session.session_id}")

    try:
        yield session
    finally:
        try:
            await client.sessions.release(session.session_id)
            log.info(f"{LogTag.AGENT} Steel session released: {session.session_id}")
        except Exception as exc:  # noqa: BLE001 — best-effort teardown
            log.warning(
                f"{LogTag.AGENT} Failed to release Steel session {session.session_id}: {exc}",
                browser={"session_id": session.session_id, "operation": "release_failed"},
            )
        await client.close()
