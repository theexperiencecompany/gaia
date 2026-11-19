"""The scout jobs: a connect's learn of the new integration, and a brief's refresh ahead of its slot."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.scout_models import ScoutOutcome, ScoutResult
from app.models.user_models import UserDocument
from app.utils.occurrence import occurrence_stamp
from app.workers.tasks import scout_tasks
from app.workers.tasks.scout_tasks import learn_scout_task, refresh_scouts_task
from tests.factories import make_user_id
from tests.helpers import captured_wide_event

USER_ID = make_user_id()
USER = UserDocument(id=USER_ID, timezone="UTC")


async def test_the_job_learns_the_connected_integration_for_its_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learn = AsyncMock(
        return_value=ScoutResult(
            integration_id="linear", app="Linear", outcome=ScoutOutcome.LEARNED
        )
    )
    get = AsyncMock(return_value=USER)
    monkeypatch.setattr(user_repository, "get", get)
    monkeypatch.setattr(scout_tasks, "learn_connected_integration", learn)

    async with captured_wide_event() as event:
        assert await learn_scout_task({}, USER_ID, "linear") == "learn_scout linear: learned"

    get.assert_awaited_once_with(USER_ID)
    learn.assert_awaited_once_with(USER, "linear")
    assert (event["user_id"], event["integration_id"]) == (USER_ID, "linear")
    assert event["scouts"] == {"learn_outcome": "learned"}


async def test_an_integration_no_scout_watches_is_reported_not_scouted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(user_repository, "get", AsyncMock(return_value=USER))
    monkeypatch.setattr(scout_tasks, "learn_connected_integration", AsyncMock(return_value=None))

    assert await learn_scout_task({}, USER_ID, "gmail") == "learn_scout gmail: not_scouted"


async def test_a_job_for_an_unknown_user_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user_repository, "get", AsyncMock(return_value=None))

    with pytest.raises(LookupError) as raised:
        await learn_scout_task({}, USER_ID, "linear")

    assert str(raised.value) == f"no user {USER_ID} to scout linear for"


_FIRE = datetime(2026, 11, 18, 7, 12, tzinfo=UTC)


def _brief(*, activated: bool = True, next_run: datetime | None = _FIRE) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=USER_ID, activated=activated, trigger_config=SimpleNamespace(next_run=next_run)
    )


@pytest.fixture
def refresh(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    refreshed = AsyncMock()
    monkeypatch.setattr(user_repository, "get", AsyncMock(return_value=USER))
    monkeypatch.setattr(scout_tasks, "refresh_scouts", refreshed)
    return refreshed


async def test_a_brief_still_armed_for_its_fire_has_its_scouts_refreshed(
    monkeypatch: pytest.MonkeyPatch, refresh: AsyncMock
) -> None:
    workflow = AsyncMock(return_value=_brief())
    user = AsyncMock(return_value=USER)
    monkeypatch.setattr(workflow_repository, "get", workflow)
    monkeypatch.setattr(user_repository, "get", user)

    async with captured_wide_event() as event:
        said = await refresh_scouts_task({}, "wf_1", occurrence_stamp(_FIRE))

    assert said == "refresh_scouts wf_1: kept"
    workflow.assert_awaited_once_with("wf_1")
    user.assert_awaited_once_with(USER_ID)
    refresh.assert_awaited_once_with(USER)
    assert (event["workflow_id"], event["user_id"]) == ("wf_1", USER_ID)
    assert event["scouts"] == {"refresh": "kept"}


@pytest.mark.parametrize(
    ("brief", "said"),
    [
        (None, "no live brief"),
        (_brief(activated=False), "no live brief"),
        (_brief(next_run=None), "no live brief"),
        (_brief(next_run=_FIRE + timedelta(hours=1)), "brief moved"),
    ],
)
async def test_a_refresh_for_a_fire_that_no_longer_stands_refreshes_nothing(
    monkeypatch: pytest.MonkeyPatch, refresh: AsyncMock, brief: SimpleNamespace | None, said: str
) -> None:
    monkeypatch.setattr(workflow_repository, "get", AsyncMock(return_value=brief))

    async with captured_wide_event() as event:
        result = await refresh_scouts_task({}, "wf_1", occurrence_stamp(_FIRE))

    assert result == f"refresh_scouts wf_1: {said}"
    refresh.assert_not_awaited()
    assert event["scouts"] == {"refresh": "stale"}


async def test_a_refresh_for_an_unknown_user_fails_loud(
    monkeypatch: pytest.MonkeyPatch, refresh: AsyncMock
) -> None:
    monkeypatch.setattr(workflow_repository, "get", AsyncMock(return_value=_brief()))
    monkeypatch.setattr(user_repository, "get", AsyncMock(return_value=None))

    with pytest.raises(LookupError, match=f"no user {USER_ID} to refresh scouts for"):
        await refresh_scouts_task({}, "wf_1", occurrence_stamp(_FIRE))
    refresh.assert_not_awaited()
