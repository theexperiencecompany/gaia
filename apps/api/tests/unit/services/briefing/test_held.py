"""Whether a held result waits for the daily brief, and its release when the loop stops carrying it."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.factories import make_briefing_payload, make_user_id
import time_machine

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WINBACK_THRESHOLD,
    BriefingRunOutcome,
    BriefItemSource,
)
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_document_models import BriefingModel
from app.models.brief_models import PendingBriefItemDocument
from app.models.brief_payload_models import BriefingMood
from app.models.briefing_state_models import (
    BriefingStateDocument,
    BriefingWindDown,
)
from app.models.notification.notification_models import notification_id
from app.models.user_activity_models import UserActivityDates
from app.models.user_models import UserDocument
from app.services.briefing import held
from app.services.notification_service import notification_service

_NOW = datetime(2026, 10, 14, 8, tzinfo=UTC)


@dataclass
class _Seams:
    user: UserDocument
    state: BriefingStateDocument
    workflow: MagicMock
    last_active_at: datetime | None
    briefs: list[BriefingModel]
    notify: AsyncMock
    consume: AsyncMock


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Seams]:
    user_id = make_user_id()
    s = _Seams(
        user=UserDocument(id=user_id, created_at=_NOW - timedelta(days=60)),
        state=BriefingStateDocument(user_id=user_id),
        workflow=MagicMock(id="wf_daily", activated=True),
        last_active_at=_NOW - timedelta(hours=1),
        briefs=[],
        notify=AsyncMock(),
        consume=AsyncMock(return_value=1),
    )

    async def find_system_workflow(uid: str, key: str) -> MagicMock | None:
        assert (uid, key) == (s.user.id, DAILY_BRIEFING_WORKFLOW_KEY)
        return s.workflow

    async def activity(_uid: str) -> UserActivityDates:
        return UserActivityDates(last_active_at=s.last_active_at)

    async def recent(_uid: str, **_kw: object) -> list[BriefingModel]:
        return s.briefs

    monkeypatch.setattr(workflow_repository, "find_system_workflow", find_system_workflow)
    monkeypatch.setattr(
        user_repository,
        "get",
        AsyncMock(side_effect=lambda uid: s.user if uid == user_id else None),
    )
    monkeypatch.setattr(user_repository, "get_activity_dates", activity)

    async def state_for(uid: str) -> BriefingStateDocument:
        # Anyone else's row is empty: a read for the wrong user finds no hold or dormancy.
        return s.state if uid == s.user.id else BriefingStateDocument(user_id=uid)

    monkeypatch.setattr(briefing_state_repository, "state_for", state_for)
    monkeypatch.setattr(briefing_repository, "list_recent", recent)

    async def list_for_user(uid: str, **_kw: object) -> list[PendingBriefItemDocument]:
        return (
            [
                PendingBriefItemDocument(
                    id="h1",
                    user_id=uid,
                    source=BriefItemSource.WORKFLOW,
                    source_id="wf_digest",
                    source_title="Digest",
                    conversation_id="c1",
                    text="Three new leads\nThe longest is from Acme.",
                )
            ]
            if uid == user_id
            else []
        )

    monkeypatch.setattr(pending_brief_items_repository, "list_for_user", list_for_user)
    monkeypatch.setattr(pending_brief_items_repository, "consume", s.consume)
    monkeypatch.setattr(notification_service, "notify", s.notify)
    with time_machine.travel(_NOW, tick=False):
        yield s


def _brief(mood: BriefingMood, sent_at: datetime) -> BriefingModel:
    return BriefingModel(
        user_id=make_user_id(),
        date=sent_at.date().isoformat(),
        payload=make_briefing_payload(date=sent_at.date().isoformat(), mood=mood),
        created_at=sent_at,
    )


class TestBriefWillCarry:
    async def test_a_switched_on_awake_loop_carries(self, seams: _Seams) -> None:
        assert await held.brief_will_carry(seams.user.id)

    async def test_a_switched_off_daily_brief_does_not(self, seams: _Seams) -> None:
        seams.workflow.activated = False

        assert not await held.brief_will_carry(seams.user.id)

    @pytest.mark.regression
    async def test_a_dormant_loop_does_not(self, seams: _Seams) -> None:
        seams.state.wind_down = BriefingWindDown(wound_down_since=_NOW - timedelta(days=2))
        seams.last_active_at = _NOW - timedelta(days=5)

        assert not await held.brief_will_carry(seams.user.id)

    async def test_activity_since_dormancy_wakes_the_next_run_so_it_carries(
        self, seams: _Seams
    ) -> None:
        seams.state.wind_down = BriefingWindDown(wound_down_since=_NOW - timedelta(days=2))

        assert await held.brief_will_carry(seams.user.id)

    @pytest.mark.regression
    async def test_a_winback_backing_off_does_not(self, seams: _Seams) -> None:
        seams.last_active_at = _NOW - timedelta(days=30)
        seams.briefs = [
            _brief(
                BriefingMood.WINBACK if day == 0 else BriefingMood.CLEAR,
                _NOW - timedelta(days=day + 1),
            )
            for day in range(WINBACK_THRESHOLD)
        ]

        assert not await held.brief_will_carry(seams.user.id)

    async def test_a_workflow_whose_user_is_gone_fails_loud(
        self, seams: _Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(user_repository, "get", AsyncMock(return_value=None))

        with pytest.raises(
            LookupError, match=f"^Daily brief workflow wf_daily belongs to no user {seams.user.id}$"
        ):
            await held.brief_will_carry(seams.user.id)


class TestReleaseAfterDailyRun:
    @pytest.mark.regression
    @pytest.mark.parametrize(
        "outcome", [BriefingRunOutcome.DORMANT, BriefingRunOutcome.WINBACK_BACKOFF]
    )
    async def test_a_run_the_loop_stopped_releases_what_was_held(
        self, seams: _Seams, outcome: BriefingRunOutcome
    ) -> None:
        seams.state.wind_down = BriefingWindDown(wound_down_since=_NOW - timedelta(days=2))
        seams.last_active_at = None

        await held.release_after_daily_run(seams.user.id, outcome)

        seams.notify.assert_awaited_once()
        seams.consume.assert_awaited_once()

    @pytest.mark.regression
    async def test_a_silent_day_releases_what_it_left_held(self, seams: _Seams) -> None:
        await held.release_after_daily_run(seams.user.id, BriefingRunOutcome.SILENT)

        request = seams.notify.await_args.args[0]
        assert (request.user_id, request.content.body) == (
            seams.user.id,
            "Digest: Three new leads",
        )
        seams.consume.assert_awaited_once_with(seams.user.id, ["h1"])

    async def test_a_sent_brief_on_a_live_loop_leaves_the_rest_for_tomorrow(
        self, seams: _Seams
    ) -> None:
        await held.release_after_daily_run(seams.user.id, BriefingRunOutcome.SENT)

        seams.notify.assert_not_awaited()
        seams.consume.assert_not_awaited()


class TestReleaseOnTellMeNow:
    async def test_moving_a_held_workflow_to_now_releases_what_it_held(self, seams: _Seams) -> None:
        await held.release_on_tell_me_now(seams.user.id, ["wf_digest"], WorkflowDelivery.NOW)

        seams.consume.assert_awaited_once_with(seams.user.id, ["h1"])

    async def test_moving_another_workflow_to_now_leaves_this_one_held(self, seams: _Seams) -> None:
        await held.release_on_tell_me_now(seams.user.id, ["wf_other"], WorkflowDelivery.NOW)

        seams.notify.assert_not_awaited()
        seams.consume.assert_not_awaited()


class TestReleaseHeldItems:
    async def test_everything_held_goes_out_oldest_first_as_one_notification_keyed_by_its_items(
        self, seams: _Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def doc(held_id: str, title: str, text: str) -> PendingBriefItemDocument:
            return PendingBriefItemDocument(
                id=held_id,
                user_id=seams.user.id,
                source=BriefItemSource.WORKFLOW,
                source_id=f"wf-{held_id}",
                source_title=title,
                conversation_id=f"c-{held_id}",
                text=text,
            )

        stored = AsyncMock(
            return_value=[doc("h2", "Digest", "Three new leads"), doc("h1", "Invoices", "All paid")]
        )
        monkeypatch.setattr(pending_brief_items_repository, "list_for_user", stored)

        await held.release_held_items(seams.user.id)

        stored.assert_awaited_once_with(seams.user.id, sort=[("created_at", 1)])
        request = seams.notify.await_args.args[0]
        assert request.id == notification_id(seams.user.id, "held_release", "h1,h2")
        assert request.content.body == "Digest: Three new leads\nInvoices: All paid"
        seams.consume.assert_awaited_once_with(seams.user.id, ["h2", "h1"])
