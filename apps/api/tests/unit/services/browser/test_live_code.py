"""The short live-view capability link: bare slug behind a vhost, /live/{code} in dev."""

import re
import secrets
from unittest.mock import AsyncMock, call

import pytest

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_LIVE_CODE_KEY_PREFIX,
    BROWSER_LIVE_CODE_TTL_SECONDS,
)
from app.schemas.browser import LiveCodeRecord
from app.services.browser import live_code, live_view

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
async def test_mint_live_code_returns_url_safe_code_of_expected_length(monkeypatch):
    monkeypatch.setattr(live_code.redis_cache, "set", AsyncMock())

    code = await live_code.mint_live_code("sess-abc", "user-1")

    assert _URL_SAFE_RE.match(code)
    assert len(code) == len(secrets.token_urlsafe(BROWSER_LIVE_CODE_ENTROPY_BYTES))


@pytest.mark.unit
async def test_mint_live_code_produces_distinct_codes_across_mints(monkeypatch):
    monkeypatch.setattr(live_code.redis_cache, "set", AsyncMock())

    first = await live_code.mint_live_code("sess-abc", "user-1")
    second = await live_code.mint_live_code("sess-abc", "user-1")

    assert first != second


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
async def test_remaining_seconds_is_zero_once_the_code_is_gone(monkeypatch):
    monkeypatch.setattr(live_code.redis_cache, "ttl_seconds", AsyncMock(return_value=None))

    assert await live_code.live_code_remaining_seconds("abc") == 0.0


@pytest.mark.unit
async def test_link_is_bare_slug_when_a_vhost_is_configured(monkeypatch):
    monkeypatch.setattr(live_view, "mint_live_code", AsyncMock(return_value="Xk3p9qR2mN4t"))
    monkeypatch.setattr(
        live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", "https://browser.heygaia.io"
    )

    link = await live_view.create_live_view_link("sess-abc", "user-1")

    # No /live/ prefix, no session id, no ?t= token — the vhost rewrites /{code}.
    assert link == "https://browser.heygaia.io/Xk3p9qR2mN4t"


@pytest.mark.unit
async def test_link_keeps_live_prefix_without_a_vhost(monkeypatch):
    monkeypatch.setattr(live_view, "mint_live_code", AsyncMock(return_value="Xk3p9qR2mN4t"))
    monkeypatch.setattr(live_view.settings, "BROWSER_LIVE_VIEW_BASE_URL", None)
    monkeypatch.setattr(live_view.settings, "HOST", "http://localhost:8000")

    link = await live_view.create_live_view_link("sess-abc", "user-1")

    # Dev: the app serves /live/{code} directly (no vhost to rewrite the bare slug).
    assert link == "http://localhost:8000/live/Xk3p9qR2mN4t"
