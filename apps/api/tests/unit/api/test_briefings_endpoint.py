"""One brief, opened from the email image, the chat link or the Briefings list; and the brief settings.

The repository is faked; the route, its owner scoping and its analytics run for real.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from pydantic import ValidationError
import pytest

from app.api.v1.endpoints.briefings import (
    get_briefing,
    get_postmarks,
    list_briefings,
    read_briefing_editions,
    read_briefing_schedule,
    update_briefing_editions,
    update_briefing_schedule,
)
from app.config.settings import settings
from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    BriefingFrequency,
    BriefingKind,
    EditionChoice,
    EditionFamily,
)
from app.constants.workflows import WorkflowDelivery
from app.models.brief_document_models import (
    BriefCardRecord,
    BriefingModel,
    EditionImage,
    EditionRender,
)
from app.models.brief_payload_models import BriefingMood, BriefingPayload
from app.models.brief_settings_models import (
    BriefingEditions,
    BriefingEditionsUpdate,
    BriefingSchedule,
    BriefingScheduleUpdate,
)
from app.models.brief_view_models import BriefCard, Postmark, PostmarksResponse
from app.models.briefing_state_models import BriefingStateDocument
from app.models.user_models import UserDocument
from app.services.briefing.view import briefing_card
from app.workers.brief_slots import slot_minute
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingOpened, BriefingPostmarksViewed
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

BASE = "/api/v1/briefings"
MODULE = "app.api.v1.endpoints.briefings"
FAKE_USER_ID = FAKE_USER.user_id


def _brief(*, opened: bool) -> BriefingModel:
    return BriefingModel(
        id="brief_abc123",
        user_id=FAKE_USER.user_id,
        date="2026-10-14",
        kind=BriefingKind.DAILY,
        payload=BriefingPayload(
            kicker="THE MORNING BRIEF",
            template_family=EditionFamily.SWISS,
            date="2026-10-14",
            headline="Two replies need you",
            lede="Priya and Dhruv.",
            mood=BriefingMood.PACKED,
            caption="Onward.",
        ),
        edition=EditionRender(key="k1", fold=0.3),
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
    assert body["card"]["briefing_id"] == "brief_abc123"
    assert body["payload"]["headline"] == "Two replies need you"
    assert body["card"]["edition"]["image_url"].startswith(
        f"{settings.HOST}/api/v1/briefings/editions/k1/png?t="
    )
    get.assert_awaited_once_with("brief_abc123", user_id=FAKE_USER.user_id)
    mark.assert_awaited_once_with(FAKE_USER.user_id, "brief_abc123")
    capture.assert_called_once_with(
        UserId(FAKE_USER.user_id), BriefingOpened(kind=BriefingKind.DAILY)
    )


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


def _record(brief: BriefingModel) -> BriefCardRecord:
    return BriefCardRecord.model_validate(brief, from_attributes=True)


async def test_the_archive_lists_the_users_editions_as_cards_and_tags_the_wide_event() -> None:
    record = _record(_brief(opened=True))
    with patch(
        f"{MODULE}.briefing_repository.list_cards", AsyncMock(return_value=[record])
    ) as list_cards:
        async with captured_wide_event() as event:
            response = await list_briefings(user=FAKE_USER, limit=7)

    assert response.briefings == [await briefing_card(record)]
    assert response.next_cursor is None
    # One past the page, to learn whether another page follows.
    list_cards.assert_awaited_once_with(FAKE_USER.user_id, limit=8, before=None)
    assert event["user"] == {"id": FAKE_USER.user_id}
    assert event["briefing"] == {"operation": "list", "limit": 7}


async def test_the_archive_sends_each_briefs_card_never_its_payload(client: AsyncClient) -> None:
    record = _record(_brief(opened=True))
    with patch(f"{MODULE}.briefing_repository.list_cards", AsyncMock(return_value=[record])):
        response = await client.get(BASE)

    [card] = response.json()["briefings"]
    assert "payload" not in card
    assert (card["briefing_id"], card["headline"]) == ("brief_abc123", "Two replies need you")


def _dated(day: int) -> BriefCardRecord:
    brief = _brief(opened=True)
    return _record(brief.model_copy(update={"id": f"brief_{day}", "date": f"2026-10-{day:02d}"}))


async def test_a_full_page_names_where_the_next_one_starts(client: AsyncClient) -> None:
    briefs = [_dated(14), _dated(13), _dated(12), _dated(11)]
    with patch(f"{MODULE}.briefing_repository.list_cards", AsyncMock(return_value=briefs)):
        response = await client.get(BASE, params={"limit": 3})

    assert response.status_code == 200
    body = response.json()
    assert [b["briefing_id"] for b in body["briefings"]] == ["brief_14", "brief_13", "brief_12"]
    assert body["next_cursor"] == "brief_12"


async def test_a_page_that_takes_the_last_briefs_exactly_names_no_next_one(
    client: AsyncClient,
) -> None:
    briefs = [_dated(14), _dated(13)]
    with patch(f"{MODULE}.briefing_repository.list_cards", AsyncMock(return_value=briefs)):
        response = await client.get(BASE, params={"limit": 2})

    assert response.json()["next_cursor"] is None


async def test_the_archive_reads_thirty_briefs_a_page_unless_asked() -> None:
    with patch(
        f"{MODULE}.briefing_repository.list_cards", AsyncMock(return_value=[])
    ) as list_cards:
        await list_briefings(user=FAKE_USER)

    assert list_cards.await_args.kwargs["limit"] == 31


async def test_the_next_page_is_read_from_after_the_cursors_brief(client: AsyncClient) -> None:
    anchor = _dated(13)
    with (
        patch(f"{MODULE}.briefing_repository.get_card", AsyncMock(return_value=anchor)) as get,
        patch(
            f"{MODULE}.briefing_repository.list_cards", AsyncMock(return_value=[_dated(12)])
        ) as list_cards,
    ):
        response = await client.get(BASE, params={"limit": 2, "before": "brief_13"})

    assert response.status_code == 200
    assert response.json()["next_cursor"] is None
    get.assert_awaited_once_with("brief_13", user_id=FAKE_USER.user_id)
    list_cards.assert_awaited_once_with(FAKE_USER.user_id, limit=3, before=anchor)


async def test_a_cursor_naming_no_brief_of_the_users_is_a_404(client: AsyncClient) -> None:
    with (
        patch(f"{MODULE}.briefing_repository.get_card", AsyncMock(return_value=None)),
        patch(f"{MODULE}.briefing_repository.list_cards", AsyncMock()) as list_cards,
    ):
        response = await client.get(BASE, params={"before": "brief_nope"})

    assert (response.status_code, response.json()["message"]) == (404, "Briefing not found")
    list_cards.assert_not_awaited()


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
        card=BriefCard(
            briefing_id="brief_abc123",
            date="2026-09-01",
            kind=BriefingKind.DAILY,
            headline="Two replies need you",
            edition=EditionImage(image_url="https://cdn.example/edition.png", fold=0.3),
            edition_name="Air Mail",
            stamp_city_name="Tokyo",
            needs_you_count=0,
        ),
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


PAID = "app.services.briefing.schedule.is_paid"
STATE_FOR = "app.db.repositories.briefing_state.briefing_state_repository.state_for"
SYSTEM_WORKFLOWS = "app.services.briefing.schedule.workflow_repository.find_system_workflows"


def _state(**fields: object) -> BriefingStateDocument:
    return BriefingStateDocument.model_validate({"user_id": FAKE_USER_ID, **fields})


class TestBriefingScheduleEndpoints:
    async def test_an_unset_user_reads_daily_at_8(self, client: AsyncClient) -> None:
        daily = MagicMock(system_workflow_key=DAILY_BRIEFING_WORKFLOW_KEY, activated=True)
        daily.trigger_config.next_run = datetime(2026, 10, 15, 2, 30, tzinfo=UTC)
        with (
            patch(PAID, new_callable=AsyncMock, return_value=True),
            patch(SYSTEM_WORKFLOWS, new_callable=AsyncMock, return_value=[daily]),
            patch(
                "app.services.user_service.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(id=FAKE_USER_ID),
            ) as get,
            patch(STATE_FOR, new_callable=AsyncMock, return_value=_state()),
        ):
            response = await client.get(f"{BASE}/schedule")

        get.assert_awaited_once_with(FAKE_USER_ID)
        assert response.status_code == 200
        assert response.json() == {
            "frequency": "daily",
            "hour": 8,
            "paused_for_plan": False,
            "next_daily_brief_at": "2026-10-15T02:30:00Z",
            "has_daily_brief": True,
            "daily_brief_lands_at": f"08:{slot_minute(FAKE_USER_ID):02d}:00",
        }

    async def test_a_free_users_schedule_reads_as_paused_for_the_plan(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(PAID, new_callable=AsyncMock, return_value=False),
            patch(
                "app.services.user_service.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(id=FAKE_USER_ID),
            ),
            patch(STATE_FOR, new_callable=AsyncMock, return_value=_state()),
        ):
            response = await client.get(f"{BASE}/schedule")

        assert response.json() == {
            "frequency": "daily",
            "hour": 8,
            "paused_for_plan": True,
            "next_daily_brief_at": None,
            "has_daily_brief": True,
            "daily_brief_lands_at": f"08:{slot_minute(FAKE_USER_ID):02d}:00",
        }

    async def test_a_missing_user_is_a_404(self, client: AsyncClient) -> None:
        with patch(
            "app.services.user_service.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"{BASE}/schedule")

        assert response.status_code == 404
        assert response.json()["message"] == "User not found"

    async def test_an_update_goes_through_the_one_schedule_setter_and_echoes_it(
        self, client: AsyncClient
    ) -> None:
        wanted = BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=7)
        with (
            patch(PAID, new_callable=AsyncMock, return_value=False),
            patch(f"{MODULE}.set_briefing_schedule", new_callable=AsyncMock) as setter,
            patch(
                "app.services.user_service.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(id=FAKE_USER_ID),
            ),
            patch(STATE_FOR, new_callable=AsyncMock, return_value=_state(schedule=wanted)),
        ):
            response = await client.put(
                f"{BASE}/schedule",
                json={"frequency": "weekdays", "hour": 7},
            )

        assert response.status_code == 200
        assert response.json() == {
            "frequency": "weekdays",
            "hour": 7,
            "paused_for_plan": True,
            "next_daily_brief_at": None,
            "has_daily_brief": True,
            "daily_brief_lands_at": f"08:{slot_minute(FAKE_USER_ID):02d}:00",
        }
        setter.assert_awaited_once_with(
            FAKE_USER_ID,
            BriefingFrequency.WEEKDAYS,
            "settings",
            hour=7,
            workflow_deliveries={},
        )

    async def test_new_deliveries_are_refused_unless_briefs_are_being_turned_off(
        self, client: AsyncClient
    ) -> None:
        with patch(f"{MODULE}.set_briefing_schedule", new_callable=AsyncMock) as setter:
            response = await client.put(
                f"{BASE}/schedule",
                json={"frequency": "daily", "hour": 7, "workflow_deliveries": {"wf-1": "now"}},
            )

        assert response.status_code == 422
        assert "workflow_deliveries is only accepted when frequency is off" in response.text
        setter.assert_not_awaited()

    def test_the_refusal_names_exactly_why_deliveries_were_refused(self) -> None:
        with pytest.raises(ValidationError) as refused:
            BriefingScheduleUpdate(
                frequency=BriefingFrequency.DAILY,
                hour=7,
                workflow_deliveries={"wf-1": WorkflowDelivery.NOW},
            )

        assert [error["msg"] for error in refused.value.errors()] == [
            "Value error, workflow_deliveries is only accepted when frequency is off"
        ]

    @pytest.mark.parametrize(
        "body", [{"frequency": "hourly", "hour": 7}, {"frequency": "daily", "hour": 24}]
    )
    async def test_an_unknown_frequency_or_hour_is_refused_before_anything_is_stored(
        self, client: AsyncClient, body: dict[str, object]
    ) -> None:
        with patch(f"{MODULE}.set_briefing_schedule", new_callable=AsyncMock) as setter:
            response = await client.put(f"{BASE}/schedule", json=body)

        assert response.status_code == 422
        setter.assert_not_awaited()


class TestBriefingEditionsEndpoints:
    async def test_the_stored_choices_are_read_back_for_every_edition(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                STATE_FOR,
                new_callable=AsyncMock,
                return_value=_state(editions={"menu": EditionChoice.OFF}),
            ) as state_for,
        ):
            response = await client.get(f"{BASE}/editions")

        state_for.assert_awaited_once_with(FAKE_USER_ID)
        assert response.status_code == 200
        choices = {e["family"]: e["choice"] for e in response.json()["editions"]}
        assert choices["menu"] == "off"
        assert choices["postal"] == "on"

    async def test_an_update_goes_through_the_one_setter_and_echoes_it(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                f"{MODULE}.set_edition_choices",
                new_callable=AsyncMock,
                return_value=BriefingEditions(editions=[]),
            ) as setter,
        ):
            response = await client.put(
                f"{BASE}/editions",
                json={"choices": {"menu": "off", "swiss": "favourite"}},
            )

        assert response.status_code == 200
        assert response.json() == {"editions": []}
        setter.assert_awaited_once_with(
            FAKE_USER_ID, {"menu": EditionChoice.OFF, "swiss": EditionChoice.FAVOURITE}
        )

    async def test_an_unknown_choice_is_refused_before_anything_is_stored(
        self, client: AsyncClient
    ) -> None:
        with patch(f"{MODULE}.set_edition_choices", new_callable=AsyncMock) as setter:
            response = await client.put(f"{BASE}/editions", json={"choices": {"menu": "hidden"}})

        assert response.status_code == 422
        setter.assert_not_awaited()


@pytest.mark.parametrize(
    ("operation", "call"),
    [
        ("read_briefing_schedule", lambda: read_briefing_schedule(user=FAKE_USER)),
        (
            "update_briefing_schedule",
            lambda: update_briefing_schedule(
                BriefingScheduleUpdate(frequency=BriefingFrequency.DAILY, hour=7), user=FAKE_USER
            ),
        ),
        ("read_briefing_editions", lambda: read_briefing_editions(user=FAKE_USER)),
        (
            "update_briefing_editions",
            lambda: update_briefing_editions(
                BriefingEditionsUpdate(choices={"menu": EditionChoice.OFF}), user=FAKE_USER
            ),
        ),
    ],
)
async def test_each_settings_route_tags_the_wide_event_with_the_user_and_operation(
    operation: str, call: Callable[[], Awaitable[object]]
) -> None:
    with (
        patch(f"{MODULE}.briefing_schedule_state", new_callable=AsyncMock),
        patch(f"{MODULE}.set_briefing_schedule", new_callable=AsyncMock),
        patch(STATE_FOR, new_callable=AsyncMock, return_value=_state()),
        patch(f"{MODULE}.set_edition_choices", new_callable=AsyncMock),
    ):
        async with captured_wide_event() as event:
            await call()

    assert (event["user"], event["operation"]) == ({"id": FAKE_USER_ID}, operation)
