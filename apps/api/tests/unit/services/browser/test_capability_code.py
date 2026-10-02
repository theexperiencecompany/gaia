"""A capability code opens exactly the record it was minted with, for as long as it lives."""

from __future__ import annotations

import re

import fakeredis.aioredis
from pydantic import BaseModel
import pytest

from app.services.browser.capability_code import CapabilityCodes
from app.services.browser.exceptions import BrowserUnavailableError

pytestmark = pytest.mark.unit

_URL_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


class _Grant(BaseModel):
    user_id: str


_CODES = CapabilityCodes("test:grant:", _Grant, entropy_bytes=9)


async def test_a_code_opens_its_record_until_its_time_runs_out(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    code = await _CODES.mint(_Grant(user_id="u1"), ttl=60)

    assert await _CODES.resolve(code) == _Grant(user_id="u1")
    assert 50 < await fake_redis.ttl(f"test:grant:{code}") <= 60
    assert await _CODES.seconds_left(code) == await fake_redis.ttl(f"test:grant:{code}")
    assert await _CODES.resolve("never-minted") is None


async def test_a_revoked_code_opens_nothing(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    code = await _CODES.mint(_Grant(user_id="u1"), ttl=60)

    await _CODES.revoke(code)

    assert await _CODES.resolve(code) is None
    assert await _CODES.seconds_left(code) is None


async def test_a_consumed_code_is_redeemed_once(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    code = await _CODES.mint(_Grant(user_id="u1"), ttl=60)

    assert await _CODES.consume(code) == _Grant(user_id="u1")
    assert await _CODES.consume(code) is None


async def test_every_code_is_a_fresh_url_safe_slug_of_its_entropy(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    codes = {await _CODES.mint(_Grant(user_id="u1"), ttl=60) for _ in range(5)}

    assert len(codes) == 5
    # token_urlsafe base64-encodes the entropy: 4 characters per 3 bytes.
    assert all(len(code) == 12 and _URL_SAFE.match(code) for code in codes)


async def test_a_code_redis_did_not_keep_is_never_handed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.browser.capability_code.redis_cache.redis", None)

    with pytest.raises(BrowserUnavailableError):
        await _CODES.mint(_Grant(user_id="u1"), ttl=60)
