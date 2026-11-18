"""The brief schedule resync: only a user whose stored crons are not their slot's moves, and only on --apply."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_settings_models import BriefingSchedule
from app.models.briefing_state_models import BriefingStateDocument
from app.models.user_models import UserDocument
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.briefing.run_times import briefing_cron
from scripts import resync_brief_schedules as resync

pytestmark = pytest.mark.unit

_ON_THE_HOUR = UserDocument(id="64f1c0ffee0000000000aaa1")
_ON_ITS_SLOT = UserDocument(id="64f1c0ffee0000000000aaa2")


def _workflow(key: str, cron: str) -> MagicMock:
    workflow = MagicMock(system_workflow_key=key)
    workflow.trigger_config = TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=cron)
    return workflow


def _briefs(user: UserDocument, *, spread: bool) -> list[MagicMock]:
    return [
        _workflow(key, briefing_cron(key, user, BriefingSchedule()) if spread else "0 8 * * *")
        for key in (DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY)
    ]


@pytest.fixture
def moved() -> Iterator[AsyncMock]:
    users = {u.id: u for u in (_ON_THE_HOUR, _ON_ITS_SLOT)}
    briefs = {
        _ON_THE_HOUR.id: _briefs(_ON_THE_HOUR, spread=False),
        _ON_ITS_SLOT.id: _briefs(_ON_ITS_SLOT, spread=True),
    }
    resync_user = AsyncMock()
    with (
        patch.object(user_repository, "list_all_ids", AsyncMock(return_value=list(users))),
        patch.object(user_repository, "get", AsyncMock(side_effect=users.get)),
        patch.object(
            briefing_state_repository,
            "state_for",
            AsyncMock(side_effect=lambda user_id: BriefingStateDocument(user_id=user_id)),
        ),
        patch.object(
            workflow_repository,
            "find_system_workflows",
            AsyncMock(side_effect=lambda user_id, _keys: briefs[user_id]),
        ),
        patch.object(resync, "resync_briefing_schedules", resync_user),
        patch.object(resync, "register_lazy_providers"),
    ):
        yield resync_user


async def test_a_dry_run_counts_the_users_off_their_slot_and_moves_nothing(
    moved: AsyncMock,
) -> None:
    assert await resync.resync(apply=False) == 1
    moved.assert_not_awaited()


async def test_apply_resyncs_only_the_user_off_their_slot(moved: AsyncMock) -> None:
    assert await resync.resync(apply=True) == 1
    moved.assert_awaited_once_with(_ON_THE_HOUR)
