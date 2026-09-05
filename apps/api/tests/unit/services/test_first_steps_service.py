"""Unit tests for the activation checklist.

``mark_step`` is the only writer of ``first_steps.<step>`` and the only emitter
of the ``first_steps_step_done`` event, so both the repository write and the
analytics payload are pinned exactly — including the distinct id, which must
always be GAIA's own user id. ``get_steps`` is the read side: it pre-checks the
steps a long-time user already satisfied before the widget existed, which is
the part that must never over- or under-count. Every repository is faked with
its real signature so a call that drops or reorders an argument fails here
exactly as it would in production; the service itself runs for real.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.models.integration_models import UserIntegrationDocument
from app.models.user_models import UserDocument
from app.services import first_steps_service
from app.services.first_steps_service import (
    ALL_STEPS,
    STEP_CONNECT_INTEGRATION,
    STEP_DISMISSED_ALL,
    STEP_FIRST_APPROVE,
    STEP_LINK_PLATFORM,
    STEP_TELL_GAIA_GOAL,
    get_steps,
    hide_step,
    mark_step,
)

USER_ID = "user-abc"
PROPOSAL_STATUSES = ["proposed", "dismissed", "expired"]


def _user(**fields: Any) -> UserDocument:
    return UserDocument.model_validate({"email": "test@example.com", "id": USER_ID, **fields})


class FakeUserRepo:
    """``user_repository`` narrowed to the first-steps accessors, real
    signatures kept so a dropped or reordered argument raises here."""

    def __init__(self) -> None:
        self.user: UserDocument | None = _user()
        self.first_time = True
        self.calls: list[tuple[str, str]] = []
        self.hidden_calls: list[tuple[str, str]] = []
        self.get_calls: list[str] = []

    async def get(self, user_id: str) -> UserDocument | None:
        self.get_calls.append(user_id)
        return self.user if user_id == USER_ID else None

    async def set_first_step(self, user_id: str, step: str) -> bool:
        self.calls.append((user_id, step))
        return self.first_time

    async def add_hidden_first_step(self, user_id: str, step: str) -> None:
        self.hidden_calls.append((user_id, step))


class FakeTodoRepo:
    def __init__(self) -> None:
        self.has_goal = False
        self.has_history = False
        self.goal_calls: list[str] = []
        self.history_calls: list[tuple[str, list[str]]] = []

    async def has_goal_todo(self, user_id: str) -> bool:
        self.goal_calls.append(user_id)
        return self.has_goal if user_id == USER_ID else False

    async def has_gaia_execution_history(self, user_id: str, *, statuses: list[str]) -> bool:
        self.history_calls.append((user_id, statuses))
        return self.has_history if user_id == USER_ID else False


class FakeIntegrationRepo:
    def __init__(self) -> None:
        self.connected: UserIntegrationDocument | None = None
        self.calls: list[tuple[str, str]] = []

    async def find_connected_excluding(
        self, user_id: str, exclude_integration_id: str
    ) -> UserIntegrationDocument | None:
        self.calls.append((user_id, exclude_integration_id))
        return self.connected if user_id == USER_ID else None


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> FakeUserRepo:
    fake = FakeUserRepo()
    monkeypatch.setattr(first_steps_service, "user_repository", fake)
    return fake


@pytest.fixture
def todos(monkeypatch: pytest.MonkeyPatch) -> FakeTodoRepo:
    fake = FakeTodoRepo()
    monkeypatch.setattr(first_steps_service, "todo_repository", fake)
    return fake


@pytest.fixture
def integrations(monkeypatch: pytest.MonkeyPatch) -> FakeIntegrationRepo:
    fake = FakeIntegrationRepo()
    monkeypatch.setattr(first_steps_service, "user_integration_repository", fake)
    return fake


@pytest.fixture
def tracked(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, Any] | None]]:
    events: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_track(user_id: str, event: str, properties: dict[str, Any] | None = None) -> None:
        events.append((user_id, event, properties))

    monkeypatch.setattr(first_steps_service, "track", fake_track)
    return events


@pytest.mark.unit
class TestMarkStep:
    @pytest.mark.parametrize("step", [*ALL_STEPS, STEP_DISMISSED_ALL])
    async def test_every_valid_step_is_recorded_for_that_user(
        self, repo: FakeUserRepo, tracked: list[Any], step: str
    ) -> None:
        await mark_step(USER_ID, step)

        assert repo.calls == [(USER_ID, step)]

    async def test_an_unknown_step_writes_nothing(
        self, repo: FakeUserRepo, tracked: list[Any]
    ) -> None:
        await mark_step(USER_ID, "not_a_step")

        assert repo.calls == []
        assert tracked == []

    async def test_the_first_completion_emits_the_activation_event(
        self, repo: FakeUserRepo, tracked: list[Any]
    ) -> None:
        await mark_step(USER_ID, STEP_FIRST_APPROVE)

        # distinct_id is GAIA's own user id, never a platform handle — a wrong
        # id here strands the event on a second, anonymous profile.
        assert tracked == [(USER_ID, "first_steps_step_done", {"step": STEP_FIRST_APPROVE})]

    async def test_a_repeat_completion_is_idempotent_and_silent(
        self, repo: FakeUserRepo, tracked: list[Any]
    ) -> None:
        repo.first_time = False

        await mark_step(USER_ID, STEP_LINK_PLATFORM)

        assert repo.calls == [(USER_ID, STEP_LINK_PLATFORM)]
        assert tracked == []


@pytest.mark.unit
class TestHideStep:
    async def test_a_real_row_is_hidden_for_that_user(
        self, repo: FakeUserRepo, tracked: list[Any]
    ) -> None:
        await hide_step(USER_ID, STEP_CONNECT_INTEGRATION)

        assert repo.hidden_calls == [(USER_ID, STEP_CONNECT_INTEGRATION)]

    async def test_a_step_outside_the_checklist_is_never_hidden(
        self, repo: FakeUserRepo, tracked: list[Any]
    ) -> None:
        # dismissed_all is a valid mark_step target but not a checklist ROW,
        # so it must not be storable as a hidden row either.
        await hide_step(USER_ID, STEP_DISMISSED_ALL)
        await hide_step(USER_ID, "not_a_step")

        assert repo.hidden_calls == []


@pytest.mark.unit
class TestGetSteps:
    async def test_a_fresh_account_has_completed_nothing(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        result = await get_steps(USER_ID)

        assert result == {
            "steps": dict.fromkeys(ALL_STEPS),
            "hidden_steps": [],
            "has_had_proposal": False,
            "dismissed": False,
        }
        assert repo.calls == []

    async def test_an_unknown_user_reads_as_a_fresh_account(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        repo.user = None

        result = await get_steps(USER_ID)

        assert result["steps"] == dict.fromkeys(ALL_STEPS)
        assert result["dismissed"] is False

    async def test_an_onboarding_focus_retroactively_completes_the_goal_step(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        repo.user = _user(onboarding={"focus": "ship the launch"})

        result = await get_steps(USER_ID)

        assert repo.get_calls == [USER_ID]
        assert repo.calls == [(USER_ID, STEP_TELL_GAIA_GOAL)]
        marked = result["steps"][STEP_TELL_GAIA_GOAL]
        assert marked is not None
        # Timestamped in UTC, not in whatever zone this process happens to run.
        assert datetime.fromisoformat(marked).utcoffset() == timedelta(0)

    async def test_a_goal_todo_alone_completes_the_goal_step(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        todos.has_goal = True

        result = await get_steps(USER_ID)

        assert todos.goal_calls == [USER_ID]
        assert repo.calls == [(USER_ID, STEP_TELL_GAIA_GOAL)]
        assert result["steps"][STEP_TELL_GAIA_GOAL] is not None

    async def test_a_junk_onboarding_focus_is_not_a_goal(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        repo.user = _user(onboarding={"focus": "n/a"})

        result = await get_steps(USER_ID)

        assert result["steps"][STEP_TELL_GAIA_GOAL] is None
        assert repo.calls == []

    async def test_an_existing_platform_link_retroactively_completes_that_step(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        repo.user = _user(platform_links={"discord": {"id": "d-1"}})

        result = await get_steps(USER_ID)

        assert repo.calls == [(USER_ID, STEP_LINK_PLATFORM)]
        assert result["steps"][STEP_LINK_PLATFORM] is not None

    async def test_a_legacy_non_dict_link_does_not_count(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        # Pre-dict storage kept a bare platform id string; it carries no "id"
        # key, so probing it must be skipped rather than attempted.
        repo.user = _user(platform_links={"discord": "legacy_string", "slack": {}})

        result = await get_steps(USER_ID)

        assert result["steps"][STEP_LINK_PLATFORM] is None
        assert repo.calls == []

    async def test_a_connected_non_gmail_integration_completes_that_step(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        integrations.connected = UserIntegrationDocument(
            user_id=USER_ID, integration_id="notion", status="connected"
        )

        result = await get_steps(USER_ID)

        # Gmail is connected at signup, so it is the one integration excluded
        # from the "connected something real" probe.
        assert integrations.calls == [(USER_ID, "gmail")]
        assert repo.calls == [(USER_ID, STEP_CONNECT_INTEGRATION)]
        assert result["steps"][STEP_CONNECT_INTEGRATION] is not None

    async def test_an_execution_history_unlocks_the_first_approve_row(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        todos.has_history = True

        result = await get_steps(USER_ID)

        # Only todos that entered the approval lifecycle count — queued/running
        # work never needed a tap.
        assert todos.history_calls == [(USER_ID, PROPOSAL_STATUSES)]
        assert result["has_had_proposal"] is True
        assert result["steps"][STEP_FIRST_APPROVE] is None

    async def test_a_recorded_approve_unlocks_the_row_without_any_history(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        repo.user = _user(first_steps={STEP_FIRST_APPROVE: datetime(2026, 6, 1, tzinfo=UTC)})
        todos.has_history = False

        result = await get_steps(USER_ID)

        assert result["has_had_proposal"] is True
        assert result["steps"][STEP_FIRST_APPROVE] == "2026-06-01T00:00:00+00:00"

    async def test_hidden_rows_are_returned_and_filtered_to_real_steps(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        repo.user = _user(
            first_steps={"hidden_steps": [STEP_LINK_PLATFORM, STEP_DISMISSED_ALL, "bogus"]}
        )

        result = await get_steps(USER_ID)

        assert result["hidden_steps"] == [STEP_LINK_PLATFORM]

    async def test_a_dismissed_checklist_reports_dismissed(
        self,
        repo: FakeUserRepo,
        todos: FakeTodoRepo,
        integrations: FakeIntegrationRepo,
        tracked: list[Any],
    ) -> None:
        repo.user = _user(first_steps={STEP_DISMISSED_ALL: datetime(2026, 6, 1, tzinfo=UTC)})

        result = await get_steps(USER_ID)

        assert result["dismissed"] is True
        # dismissed_all is not a checklist row, so it never leaks into steps.
        assert set(result["steps"]) == set(ALL_STEPS)
