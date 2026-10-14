"""One brief, opened from the email image, the chat link or the Briefings list.

The repository is faked; the route, its owner scoping and its analytics run for real.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.api.v1.endpoints.briefings import get_briefing, get_postmarks, list_briefings
from app.models.briefing_models import (
    BriefingModel,
    BriefingPayload,
    Postmark,
    PostmarksResponse,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingOpened, BriefingPostmarksViewed
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

BASE = "/api/v1/briefings"
MODULE = "app.api.v1.endpoints.briefings"


def _brief(*, opened: bool) -> BriefingModel:
    return BriefingModel(
        id="brief_abc123",
        user_id=FAKE_USER.user_id,
        date="2026-10-14",
        kind="daily",
        payload=BriefingPayload(
            kicker="THE MORNING BRIEF",
            date="2026-10-14",
            headline="Two replies need you",
            lede="Priya and Dhruv.",
            mood="packed",
            caption="Onward.",
        ),
        edition_image_url="https://cdn.example/brief.png",
        opened_at=MagicMock() if opened else None,
    )


async def test_opening_a_brief_returns_it_marks_it_opened_and_reports_it_once(
    client: AsyncClient,
) -> None:
    unopened, opened = _brief(opened=False), _brief(opened=True)
    with (
        patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=unopened)) as get,
        patch(f"{MODULE}.briefing_repository.mark_opened", AsyncMock(return_value=opened)) as mark,
        patch(f"{MODULE}.capture") as capture,
    ):
        response = await client.get(f"{BASE}/brief_abc123")

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["edition_image_url"]) == (
        "brief_abc123",
        "https://cdn.example/brief.png",
    )
    get.assert_awaited_once_with("brief_abc123", user_id=FAKE_USER.user_id)
    mark.assert_awaited_once_with(FAKE_USER.user_id, "brief_abc123")
    capture.assert_called_once_with(UserId(FAKE_USER.user_id), BriefingOpened(kind="daily"))


async def test_reopening_a_brief_reports_nothing(client: AsyncClient) -> None:
    with (
        patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=_brief(opened=True))),
        patch(f"{MODULE}.briefing_repository.mark_opened", AsyncMock()) as mark,
        patch(f"{MODULE}.capture") as capture,
    ):
        response = await client.get(f"{BASE}/brief_abc123")

    assert response.status_code == 200
    mark.assert_not_awaited()
    capture.assert_not_called()


async def test_someone_elses_or_a_missing_brief_is_a_404(client: AsyncClient) -> None:
    with patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=None)):
        response = await client.get(f"{BASE}/brief_nope")

    assert (response.status_code, response.json()["message"]) == (404, "Briefing not found")


async def test_opening_a_brief_tags_the_wide_event_with_the_user_and_brief() -> None:
    with patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=_brief(opened=True))):
        async with captured_wide_event() as event:
            await get_briefing("brief_abc123", user=FAKE_USER)

    assert event["user"] == {"id": FAKE_USER.user_id}
    assert event["briefing"] == {"operation": "get", "id": "brief_abc123"}


async def test_the_archive_lists_the_users_briefs_and_tags_the_wide_event() -> None:
    brief = _brief(opened=True)
    with patch(
        f"{MODULE}.briefing_repository.list_recent", AsyncMock(return_value=[brief])
    ) as list_recent:
        async with captured_wide_event() as event:
            response = await list_briefings(user=FAKE_USER, limit=7)

    assert response.briefings == [brief]
    list_recent.assert_awaited_once_with(FAKE_USER.user_id, limit=7)
    assert event["user"] == {"id": FAKE_USER.user_id}
    assert event["briefing"] == {"operation": "list", "limit": 7}


async def test_postmarks_returns_the_collection_and_reports_the_view(
    client: AsyncClient,
) -> None:
    tokyo = Postmark(
        city_slug="tokyo",
        city="Tokyo",
        country="Japan",
        lat=35.68,
        lng=139.69,
        stamp_url="https://cdn.example/tokyo.webp",
        date="2026-09-01",
        briefing_id="brief_abc123",
    )
    collection = PostmarksResponse(total=85, postmarks=[tokyo])
    with (
        patch(f"{MODULE}.collected_postmarks", AsyncMock(return_value=collection)) as collect,
        patch(f"{MODULE}.capture") as capture,
    ):
        response = await client.get(f"{BASE}/postmarks")

    assert response.status_code == 200
    assert PostmarksResponse.model_validate(response.json()) == collection
    collect.assert_awaited_once_with(FAKE_USER.user_id)
    capture.assert_called_once_with(
        UserId(FAKE_USER.user_id), BriefingPostmarksViewed(collected=1, total=85)
    )


async def test_postmarks_tags_the_wide_event_with_the_collected_count() -> None:
    empty = PostmarksResponse(total=85, postmarks=[])
    with (
        patch(f"{MODULE}.collected_postmarks", AsyncMock(return_value=empty)),
        patch(f"{MODULE}.capture"),
    ):
        async with captured_wide_event() as event:
            await get_postmarks(user=FAKE_USER)

    assert event["user"] == {"id": FAKE_USER.user_id}
    assert event["briefing"] == {"operation": "postmarks", "postmarks_collected": 0}
