"""The learn job a connect enqueues: it scouts the new integration for that user, loudly."""

from unittest.mock import AsyncMock

import pytest

from app.models.scout_models import ScoutOutcome, ScoutResult
from app.models.user_models import UserDocument
from app.workers.tasks import scout_tasks
from app.workers.tasks.scout_tasks import learn_scout_task

USER_ID = "64f1c0ffee0000000000abcd"
USER = UserDocument(id=USER_ID, timezone="UTC")


async def test_the_job_learns_the_connected_integration_for_its_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learn = AsyncMock(
        return_value=ScoutResult(integration_id="linear", outcome=ScoutOutcome.LEARNED)
    )
    monkeypatch.setattr(scout_tasks.user_repository, "get", AsyncMock(return_value=USER))
    monkeypatch.setattr(scout_tasks, "learn_connected_integration", learn)

    assert await learn_scout_task({}, USER_ID, "linear") == "learn_scout linear: learned"
    learn.assert_awaited_once_with(USER, "linear")


async def test_an_integration_no_scout_watches_is_reported_not_scouted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scout_tasks.user_repository, "get", AsyncMock(return_value=USER))
    monkeypatch.setattr(scout_tasks, "learn_connected_integration", AsyncMock(return_value=None))

    assert await learn_scout_task({}, USER_ID, "gmail") == "learn_scout gmail: not_scouted"


async def test_a_job_for_an_unknown_user_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scout_tasks.user_repository, "get", AsyncMock(return_value=None))

    with pytest.raises(LookupError):
        await learn_scout_task({}, USER_ID, "linear")
