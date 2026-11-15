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
from app.services.briefing.view import briefing_view
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
            template_family="swiss",
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


async def test_the_archive_lists_only_the_users_editions_and_tags_the_wide_event() -> None:
    brief = _brief(opened=True)
    with patch(
        f"{MODULE}.briefing_repository.list_recent", AsyncMock(return_value=[brief])
    ) as list_recent:
        async with captured_wide_event() as event:
            response = await list_briefings(user=FAKE_USER, limit=7)

    assert response.briefings == [briefing_view(brief)]
    assert response.next_cursor is None
    # One past the page, to learn whether another page follows.
    list_recent.assert_awaited_once_with(
        FAKE_USER.user_id, limit=8, editions_only=True, before=None
    )
    assert event["user"] == {"id": FAKE_USER.user_id}
    assert event["briefing"] == {"operation": "list", "limit": 7}


def _dated(day: int) -> BriefingModel:
    brief = _brief(opened=True)
    return brief.model_copy(update={"id": f"brief_{day}", "date": f"2026-10-{day:02d}"})


async def test_a_full_page_names_where_the_next_one_starts(client: AsyncClient) -> None:
    briefs = [_dated(14), _dated(13), _dated(12), _dated(11)]
    with patch(f"{MODULE}.briefing_repository.list_recent", AsyncMock(return_value=briefs)):
        response = await client.get(BASE, params={"limit": 3})

    assert response.status_code == 200
    body = response.json()
    assert [b["id"] for b in body["briefings"]] == ["brief_14", "brief_13", "brief_12"]
    assert body["next_cursor"] == "brief_12"


async def test_a_page_that_takes_the_last_briefs_exactly_names_no_next_one(
    client: AsyncClient,
) -> None:
    briefs = [_dated(14), _dated(13)]
    with patch(f"{MODULE}.briefing_repository.list_recent", AsyncMock(return_value=briefs)):
        response = await client.get(BASE, params={"limit": 2})

    assert response.json()["next_cursor"] is None


async def test_the_archive_reads_thirty_briefs_a_page_unless_asked() -> None:
    with patch(
        f"{MODULE}.briefing_repository.list_recent", AsyncMock(return_value=[])
    ) as list_recent:
        await list_briefings(user=FAKE_USER)

    assert list_recent.await_args.kwargs["limit"] == 31


async def test_the_next_page_is_read_from_after_the_cursors_brief(client: AsyncClient) -> None:
    anchor = _dated(13)
    with (
        patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=anchor)) as get,
        patch(
            f"{MODULE}.briefing_repository.list_recent", AsyncMock(return_value=[_dated(12)])
        ) as list_recent,
    ):
        response = await client.get(BASE, params={"limit": 2, "before": "brief_13"})

    assert response.status_code == 200
    assert response.json()["next_cursor"] is None
    get.assert_awaited_once_with("brief_13", user_id=FAKE_USER.user_id)
    list_recent.assert_awaited_once_with(
        FAKE_USER.user_id, limit=3, editions_only=True, before=anchor
    )


async def test_a_cursor_naming_no_brief_of_the_users_is_a_404(client: AsyncClient) -> None:
    with (
        patch(f"{MODULE}.briefing_repository.get", AsyncMock(return_value=None)),
        patch(f"{MODULE}.briefing_repository.list_recent", AsyncMock()) as list_recent,
    ):
        response = await client.get(BASE, params={"before": "brief_nope"})

    assert (response.status_code, response.json()["message"]) == (404, "Briefing not found")
    list_recent.assert_not_awaited()


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
