"""The short live-view capability link: bare slug behind a vhost, /live/{code} in dev."""

import re
from unittest.mock import AsyncMock, call

import pytest

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_LIVE_CODE_KEY_PREFIX,
    BROWSER_LIVE_CODE_TTL_SECONDS,
)
from app.schemas.browser import LiveCodeRecord
from app.services.browser import links, live_code, live_view

_URL_SAFE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@pytest.mark.unit
async def test_mint_live_code_stores_record_under_prefixed_key(monkeypatch):
    set_mock = AsyncMock()
    monkeypatch.setattr(live_code.redis_cache, "set", set_mock)

    code = await live_code.mint_live_code("sess-abc", "user-1")

    set_mock.assert_awaited_once_with(
        BROWSER_LIVE_CODE_KEY_PREFIX + code,
        LiveCodeRecord(session_id="sess-abc", user_id="user-1"),
        ttl=BROWSER_LIVE_CODE_TTL_SECONDS,
        model=LiveCodeRecord,
    )


@pytest.mark.unit
async def test_resolve_live_code_returns_cache_hit(monkeypatch):
    record = LiveCodeRecord(session_id="sess-xyz", user_id="user-2")
    get_mock = AsyncMock(return_value=record)
    monkeypatch.setattr(live_code.redis_cache, "get", get_mock)

    result = await live_code.resolve_live_code("Xk3p9qR2mN4t")

    assert result == record
    get_mock.assert_awaited_once_with(
        BROWSER_LIVE_CODE_KEY_PREFIX + "Xk3p9qR2mN4t", model=LiveCodeRecord
    )
    assert get_mock.await_args == call(
        BROWSER_LIVE_CODE_KEY_PREFIX + "Xk3p9qR2mN4t", model=LiveCodeRecord
    )


@pytest.mark.unit
async def test_resolve_live_code_returns_none_when_cache_misses(monkeypatch):
    monkeypatch.setattr(live_code.redis_cache, "get", AsyncMock(return_value=None))

    result = await live_code.resolve_live_code("unknown-code")

    assert result is None


@pytest.mark.unit
async def test_remaining_seconds_is_the_codes_ttl(monkeypatch):
    ttl = AsyncMock(return_value=120)
    monkeypatch.setattr(live_code.redis_cache, "ttl_seconds", ttl)

    assert await live_code.live_code_remaining_seconds("abc") == 120.0
    ttl.assert_awaited_once_with(f"{BROWSER_LIVE_CODE_KEY_PREFIX}abc")


@pytest.mark.unit
async def test_a_live_code_is_a_short_url_safe_slug(monkeypatch):
    """The code rides a chat link: it carries the configured entropy and nothing longer."""
    monkeypatch.setattr(live_code.redis_cache, "set", AsyncMock())

    code = await live_code.mint_live_code("sess-abc", "user-1")

    # token_urlsafe base64-encodes the entropy bytes: 4 characters per 3 bytes.
    assert len(code) == -(-BROWSER_LIVE_CODE_ENTROPY_BYTES * 4 // 3)
    assert _URL_SAFE_RE.match(code)


@pytest.mark.unit
async def test_a_lapsed_code_has_no_time_left(monkeypatch):
    """No TTL means the key is gone, so the socket bound to it must close at once."""
    monkeypatch.setattr(live_code.redis_cache, "ttl_seconds", AsyncMock(return_value=None))

    assert await live_code.live_code_remaining_seconds("abc") == 0.0


@pytest.mark.unit
async def test_link_keeps_the_live_path_on_a_vhost(monkeypatch):
    monkeypatch.setattr(live_view, "mint_live_code", AsyncMock(return_value="Xk3p9qR2mN4t"))
    monkeypatch.setattr(links.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io")

    link = await live_view.create_live_view_link("sess-abc", "user-1")

    # No session id and no ?t= token; /live/ keeps a bare /{code} off the API root.
    assert link == "https://browser.heygaia.io/live/Xk3p9qR2mN4t"
