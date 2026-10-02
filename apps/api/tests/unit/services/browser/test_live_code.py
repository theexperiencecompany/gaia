"""The short live-view capability link: one per handoff, lapsing with its window, revoked on settle."""

import asyncio
import re
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.config.settings import settings
from app.constants.browser import BROWSER_LIVE_CODE_ENTROPY_BYTES
from app.schemas.browser import LiveCodeRecord
from app.services.browser import links, live_code, live_view

_URL_SAFE_RE = re.compile(r"^[A-Za-z0-9_-]+$")

pytestmark = pytest.mark.unit


async def test_a_code_opens_its_session_for_the_handoffs_window_until_revoked(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    code = await live_code.mint_live_code("sess-abc", "user-1", "h1")

    assert await live_code.resolve_live_code(code) == LiveCodeRecord(
        session_id="sess-abc", user_id="user-1", handoff_id="h1"
    )
    assert (
        0
        < await fake_redis.ttl(f"browser:livecode:{code}")
        <= (settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS)
    )

    # The handoff's own pointer to its code lapses with it too.
    assert await fake_redis.ttl("browser:livecode:handoff:h1") > 0

    await live_code.revoke_handoff_live_code("h1")

    assert await live_code.resolve_live_code(code) is None
    # Gone, so a socket it opens from here on closes at once.
    await asyncio.wait_for(live_code.live_code_ended(code), timeout=1)


async def test_a_socket_a_code_opened_ends_when_the_code_lapses(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    code = await live_code.mint_live_code("sess-abc", "user-1", "h1")
    await fake_redis.expire(f"browser:livecode:{code}", 1)

    await asyncio.wait_for(live_code.live_code_ended(code), timeout=3)


async def test_a_live_code_is_a_short_url_safe_slug(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """The code rides a chat link: it carries the configured entropy and nothing longer."""
    code = await live_code.mint_live_code("sess-abc", "user-1", "h1")

    # token_urlsafe base64-encodes the entropy bytes: 4 characters per 3 bytes.
    assert len(code) == -(-BROWSER_LIVE_CODE_ENTROPY_BYTES * 4 // 3)
    assert _URL_SAFE_RE.match(code)


async def test_link_opens_the_web_live_page_whatever_the_socket_vhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mint = AsyncMock(return_value="Xk3p9qR2mN4t")
    monkeypatch.setattr(live_view, "mint_live_code", mint)
    monkeypatch.setattr(live_view.settings, "FRONTEND_URL", "https://heygaia.io")
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io")

    link = await live_view.create_live_view_link("sess-abc", "user-1", "h1")

    # The web app serves the viewer; the vhost only fronts its socket. No
    # session id and no ?t= token in the link: the code is the authority.
    assert link == "https://heygaia.io/live/Xk3p9qR2mN4t"
    mint.assert_awaited_once_with("sess-abc", "user-1", "h1")
