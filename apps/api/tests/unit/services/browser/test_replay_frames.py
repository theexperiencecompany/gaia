"""Regression: the recap slideshow derived image URLs it never checked existed.

render_replay_page built a step image URL for every step from a count, so any
step whose screenshot upload failed showed a broken image in the shared recap
link. Same root cause as the task-history thumbnails.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.constants.browser import BROWSER_REPLAY_CODE_TTL_SECONDS
from app.db.redis import redis_cache
from app.schemas.browser import ReplayRecord
from app.services.browser import replay as replay_module
from app.services.browser.replay import create_replay_link, render_replay_page, resolve_replay_code
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def link_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.browser.links.settings.BROWSER_LIVE_VIEW_BASE_URL",
        "https://browser.heygaia.io/",
    )


def _code(link: str) -> str:
    return link.rsplit("/replays/", 1)[1]


def test_page_shows_only_the_screenshots_that_uploaded() -> None:
    page = render_replay_page(
        ReplayRecord(session_id="s1", shots=["https://cdn/1.jpg", "https://cdn/3.jpg"])
    )

    assert '["https://cdn/1.jpg", "https://cdn/3.jpg"]' in page
    assert "__URLS__" not in page


def test_closing_script_tags_in_urls_are_escaped_for_safe_embedding() -> None:
    page = render_replay_page(ReplayRecord(session_id="s1", shots=["https://cdn/</script>.jpg"]))

    # The raw closing sequence must never appear inside the inlined <script> block.
    assert "</script>.jpg" not in page
    assert "<\\/script>.jpg" in page


async def test_a_recap_link_opens_the_screenshots_the_run_uploaded_for_a_week(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    link = await create_replay_link("s1", ["https://cdn/1.jpg", "https://cdn/2.jpg"])

    assert link is not None
    # A trailing slash on the base must not survive into a double slash before "replays".
    assert link.startswith("https://browser.heygaia.io/replays/")
    assert await resolve_replay_code(_code(link)) == ReplayRecord(
        session_id="s1", shots=["https://cdn/1.jpg", "https://cdn/2.jpg"]
    )
    ttl = await fake_redis.ttl(f"browser:replay:{_code(link)}")
    assert BROWSER_REPLAY_CODE_TTL_SECONDS - 10 < ttl <= BROWSER_REPLAY_CODE_TTL_SECONDS
    assert await resolve_replay_code("never-minted") is None


async def test_no_recap_link_when_no_screenshot_uploaded(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    assert await create_replay_link("s1", []) is None
    # Nothing to replay means no code should ever be minted.
    assert await fake_redis.keys() == []


async def test_no_recap_link_when_its_code_was_not_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_cache, "redis", None)

    assert await create_replay_link("s1", ["https://cdn/1.jpg"]) is None


async def test_minting_reports_the_session_its_frame_count_and_latency_on_the_wide_event(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter([10.0, 10.75])
    monkeypatch.setattr(replay_module, "perf_counter", lambda: next(clock))

    async with captured_wide_event() as event:
        await create_replay_link("s1", ["https://cdn/1.jpg", "https://cdn/3.jpg"])

    assert event["browser"] == {"session_id": "s1", "replay_shots": 2, "replay_mint_ms": 750}
