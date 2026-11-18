"""Switching the daily brief off, whatever switches it off, releases what it held."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    HELD_RELEASE_TITLE,
    WEEKLY_DIGEST_WORKFLOW_KEY,
    BriefItemSource,
)
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_models import PendingBriefItemDocument
from app.models.scheduler_models import DeactivationReason
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
    WorkflowStep,
)
from app.services import member_offboarding
from app.services.member_offboarding import stop_acting_for_removed_member
from app.services.notification_service import notification_service
from app.services.platform_link_service import PlatformLinkService
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.service import WorkflowService
from tests.factories import make_user_id

pytestmark = pytest.mark.unit


@dataclass
class _Seams:
    user_id: str
    workflow: WorkflowDocument
    held: list[PendingBriefItemDocument]
    notify: AsyncMock
    consume: AsyncMock


def _brief_workflow(user_id: str, key: str) -> WorkflowDocument:
    return WorkflowDocument(
        id=f"wf-{key}",
        user_id=user_id,
        title="Daily Briefing",
        description="Your morning brief.",
        prompt="Generate the user's daily briefing.",
        delivery=WorkflowDelivery.SILENT,
        is_system_workflow=True,
        system_workflow_key=key,
        activated=True,
        trigger_config=TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 7 * * *"),
        steps=[WorkflowStep(id="s1", title="Brief", category="gaia", description="Brief.")],
    )


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Seams]:
    user_id = make_user_id()
    s = _Seams(
        user_id=user_id,
        workflow=_brief_workflow(user_id, DAILY_BRIEFING_WORKFLOW_KEY),
        held=[
            PendingBriefItemDocument(
                user_id=user_id,
                source=BriefItemSource.WORKFLOW,
                source_id="wf-digest",
                source_title="Digest",
                conversation_id="c1",
                text="Three new leads",
            )
        ],
        notify=AsyncMock(),
        consume=AsyncMock(return_value=1),
    )

    async def get_for_user(workflow_id: str, owner: str) -> WorkflowDocument | None:
        return s.workflow if (workflow_id, owner) == (s.workflow.id, user_id) else None

    async def deactivate(workflow_id: str, owner: str, **_: object) -> WorkflowDocument | None:
        if (workflow_id, owner) != (s.workflow.id, user_id):
            return None
        s.workflow = s.workflow.model_copy(update={"activated": False})
        return s.workflow

    async def held_for(owner: str, **_: object) -> list[PendingBriefItemDocument]:
        return list(s.held) if owner == user_id else []

    monkeypatch.setattr(workflow_repository, "get_for_user", get_for_user)
    monkeypatch.setattr(workflow_repository, "deactivate", deactivate)
    monkeypatch.setattr(pending_brief_items_repository, "list_for_user", held_for)
    monkeypatch.setattr(pending_brief_items_repository, "consume", s.consume)
    monkeypatch.setattr(notification_service, "create_notification", s.notify)
    return s


def _released(seams: _Seams) -> None:
    [request] = [c.args[0] for c in seams.notify.await_args_list]
    assert (request.user_id, request.content.title, request.content.body) == (
        seams.user_id,
        HELD_RELEASE_TITLE,
        "Digest: Three new leads",
    )
    seams.consume.assert_awaited_once_with(seams.user_id, [doc.id for doc in seams.held])


class TestSwitchingTheDailyBriefOff:
    @pytest.mark.regression
    async def test_a_lapsed_plan_releases_what_the_brief_held(self, seams: _Seams) -> None:
        """The unpaid-fire gate pauses the brief through the scheduler; its held results were stranded."""
        await WorkflowScheduler().pause_for_reason(
            seams.workflow, DeactivationReason.SUBSCRIPTION_LAPSED
        )

        assert not seams.workflow.activated
        _released(seams)

    @pytest.mark.regression
    async def test_removing_the_member_releases_what_their_brief_held(
        self, seams: _Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workflow_repository,
            "find_activated_for_user",
            AsyncMock(
                side_effect=lambda owner, **_: [seams.workflow] if owner == seams.user_id else []
            ),
        )
        monkeypatch.setattr(member_offboarding, "revoke_all_links_for_user", AsyncMock())
        monkeypatch.setattr(
            reminder_repository, "find_scheduled_for_user", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            todo_repository, "find_running_tracked_for_user", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(PlatformLinkService, "get_linked_platforms", AsyncMock(return_value={}))

        await stop_acting_for_removed_member(seams.user_id)

        assert not seams.workflow.activated
        _released(seams)

    async def test_switching_the_weekly_digest_off_leaves_the_daily_its_results(
        self, seams: _Seams
    ) -> None:
        seams.workflow = _brief_workflow(seams.user_id, WEEKLY_DIGEST_WORKFLOW_KEY)

        await WorkflowService.deactivate_workflow(
            seams.workflow.id, seams.user_id, reason=DeactivationReason.MEMBER_REMOVED
        )

        seams.notify.assert_not_awaited()
        seams.consume.assert_not_awaited()
