"""A step frame kept in Redis is read back by its run's code, by the process that serves it, until it expires."""

from __future__ import annotations

import secrets

import fakeredis
import pytest

from app.constants.browser import (
    BROWSER_LIVE_CODE_ENTROPY_BYTES,
    BROWSER_REPLAY_CODE_TTL_SECONDS,
    BROWSER_SHOT_CODE_KEY_PREFIX,
)
from app.services.browser import shot_store
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def link_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.browser.links.settings.BROWSER_LIVE_VIEW_BASE_URL", "https://browser.test"
    )


def _code(url: str) -> str:
    return url.split("/shots/")[1].split("/")[0]


async def test_a_stored_frame_is_read_back_by_its_runs_code_and_index(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    url = await shot_store.store_step_screenshot(b"\xff\xd8jpeg-one", "sess-1", 2)

    assert url is not None
    assert url.startswith("https://browser.test/shots/")
    assert url.endswith("/2.jpg")
    assert "sess-1" not in url
    assert await shot_store.read_step_screenshot(_code(url), 2) == b"\xff\xd8jpeg-one"
    assert await shot_store.read_step_screenshot(_code(url), 3) is None


async def test_every_step_of_a_run_shares_one_code_and_another_run_gets_its_own(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    first = [await shot_store.store_step_screenshot(b"a", "sess-1", i) for i in (1, 2)]
    other = await shot_store.store_step_screenshot(b"b", "sess-2", 1)

    assert first[0] is not None and first[1] is not None and other is not None
    assert _code(first[0]) == _code(first[1]) != _code(other)
    assert await shot_store.read_step_screenshot(_code(other), 1) == b"b"


async def test_a_frame_and_its_code_expire_with_the_recap(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    url = await shot_store.store_step_screenshot(b"a", "sess-1", 1)

    ttls = {key: await fake_redis.ttl(key) for key in await fake_redis.keys()}

    assert len(ttls) == 3
    assert all(
        BROWSER_REPLAY_CODE_TTL_SECONDS - 60 < ttl <= BROWSER_REPLAY_CODE_TTL_SECONDS
        for ttl in ttls.values()
    )
    # One code as short as a live view's, the same capability size.
    assert url is not None
    assert len(_code(url)) == len(secrets.token_urlsafe(BROWSER_LIVE_CODE_ENTROPY_BYTES))


async def test_reading_a_frame_leaves_its_run_on_the_event(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    url = await shot_store.store_step_screenshot(b"12345", "sess-9", 1)
    assert url is not None

    async with captured_wide_event() as read:
        await shot_store.read_step_screenshot(_code(url), 1)

    assert read["browser"] == {"session_id": "sess-9"}


async def test_an_unknown_code_or_a_session_id_opens_nothing(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await shot_store.store_step_screenshot(b"a", "sess-1", 1)

    assert await shot_store.read_step_screenshot("never-minted", 1) is None
    assert await shot_store.read_step_screenshot("sess-1", 1) is None


async def test_a_frame_redis_does_not_take_gets_no_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shot_store.redis_cache, "redis", None)

    assert await shot_store.store_step_screenshot(b"a", "sess-1", 1) is None


async def test_a_frame_whose_code_redis_does_not_keep_gets_no_url(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    setex = fake_redis.setex

    async def _refuse_codes(name: str, time: int, value: str) -> object:
        if name.startswith(BROWSER_SHOT_CODE_KEY_PREFIX):
            raise ConnectionError("redis went away")
        return await setex(name, time, value)

    monkeypatch.setattr(fake_redis, "setex", _refuse_codes)

    assert await shot_store.store_step_screenshot(b"a", "sess-1", 1) is None
