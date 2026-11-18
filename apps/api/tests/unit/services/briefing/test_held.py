"""Whether a held result waits for the daily brief, and its release when the loop stops carrying it."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.factories import make_user_id
import time_machine

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WINBACK_THRESHOLD,
    BriefingRunOutcome,
    BriefItemSource,
)
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_models import PendingBriefItemDocument
from app.models.briefing_models import BriefingModel, BriefingMood, BriefingPayload
from app.models.user_activity_models import UserActivityDates
from app.models.user_models import BriefingBootstrap, BriefingDormancy, UserDocument
from app.services.briefing import held
from app.services.notification_service import notification_service

_NOW = datetime(2026, 10, 14, 8, tzinfo=UTC)


@dataclass
class _Seams:
    user: UserDocument
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
    monkeypatch.setattr(user_repository, "get", AsyncMock(side_effect=lambda _uid: s.user))
    monkeypatch.setattr(user_repository, "get_activity_dates", activity)
    monkeypatch.setattr(briefing_repository, "list_recent", recent)
    monkeypatch.setattr(
        pending_brief_items_repository,
        "list_for_user",
        AsyncMock(
            return_value=[
                PendingBriefItemDocument(
                    user_id=user_id,
                    source=BriefItemSource.WORKFLOW,
                    source_id="wf_digest",
                    source_title="Digest",
                    conversation_id="c1",
                    text="Three new leads",
                )
            ]
        ),
    )
    monkeypatch.setattr(pending_brief_items_repository, "consume", s.consume)
    monkeypatch.setattr(notification_service, "create_notification", s.notify)
    with time_machine.travel(_NOW, tick=False):
        yield s


def _brief(mood: BriefingMood, sent_at: datetime) -> BriefingModel:
    return BriefingModel(
        user_id="u",
        date=sent_at.date().isoformat(),
        payload=BriefingPayload(
            kicker="K",
            template_family="swiss",
            date=sent_at.date().isoformat(),
            headline="H",
            lede="L",
            mood=mood,
            caption="C",
        ),
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
        seams.user.briefing_dormancy = BriefingDormancy(dormant_since=_NOW - timedelta(days=2))
        seams.last_active_at = _NOW - timedelta(days=5)

        assert not await held.brief_will_carry(seams.user.id)

    async def test_activity_since_dormancy_wakes_the_next_run_so_it_carries(
        self, seams: _Seams
    ) -> None:
        seams.user.briefing_dormancy = BriefingDormancy(dormant_since=_NOW - timedelta(days=2))

        assert await held.brief_will_carry(seams.user.id)

    @pytest.mark.regression
    async def test_a_winback_backing_off_does_not(self, seams: _Seams) -> None:
        seams.last_active_at = _NOW - timedelta(days=30)
        seams.briefs = [
            _brief("winback" if day == 0 else "clear", _NOW - timedelta(days=day + 1))
            for day in range(WINBACK_THRESHOLD)
        ]

        assert not await held.brief_will_carry(seams.user.id)

    @pytest.mark.regression
    async def test_a_first_brief_held_for_a_goal_does_not(self, seams: _Seams) -> None:
        seams.user.briefing_bootstrap = BriefingBootstrap(pending=True, since=_NOW)

        assert not await held.brief_will_carry(seams.user.id)


class TestReleaseAfterDailyRun:
    @pytest.mark.regression
    @pytest.mark.parametrize(
        "outcome", [BriefingRunOutcome.DORMANT, BriefingRunOutcome.WINBACK_BACKOFF]
    )
    async def test_a_run_the_loop_stopped_releases_what_was_held(
        self, seams: _Seams, outcome: BriefingRunOutcome
    ) -> None:
        seams.user.briefing_dormancy = BriefingDormancy(dormant_since=_NOW - timedelta(days=2))
        seams.last_active_at = None

        await held.release_after_daily_run(seams.user.id, outcome)

        seams.notify.assert_awaited_once()
        seams.consume.assert_awaited_once()

    @pytest.mark.regression
    async def test_a_silent_day_releases_what_it_left_held(self, seams: _Seams) -> None:
        await held.release_after_daily_run(seams.user.id, BriefingRunOutcome.SILENT)

        seams.notify.assert_awaited_once()

    async def test_a_sent_brief_on_a_live_loop_leaves_the_rest_for_tomorrow(
        self, seams: _Seams
    ) -> None:
        await held.release_after_daily_run(seams.user.id, BriefingRunOutcome.SENT)

        seams.notify.assert_not_awaited()
        seams.consume.assert_not_awaited()
