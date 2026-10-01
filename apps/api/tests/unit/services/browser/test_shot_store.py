"""A step frame kept in Redis is read back by its run's code, by the process that serves it, until it expires."""

from __future__ import annotations

import fakeredis
import pytest

from app.constants.browser import BROWSER_REPLAY_CODE_TTL_SECONDS
from app.services.browser import shot_store

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
    await shot_store.store_step_screenshot(b"a", "sess-1", 1)

    ttls = {key: await fake_redis.ttl(key) for key in await fake_redis.keys()}

    assert len(ttls) == 3
    assert all(0 < ttl <= BROWSER_REPLAY_CODE_TTL_SECONDS for ttl in ttls.values())


async def test_an_unknown_code_or_a_session_id_opens_nothing(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await shot_store.store_step_screenshot(b"a", "sess-1", 1)

    assert await shot_store.read_step_screenshot("never-minted", 1) is None
    assert await shot_store.read_step_screenshot("sess-1", 1) is None


async def test_a_frame_redis_does_not_take_gets_no_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shot_store.redis_cache, "redis", None)

    assert await shot_store.store_step_screenshot(b"a", "sess-1", 1) is None
