"""Unit tests for the existing-user briefing rollout.

Every seam (user lookup, workflow provisioning, goal derivation, repositories,
analytics) is faked; ``provision_existing_user`` itself runs for real.
"""

from typing import Any

import pytest
from tests.factories import make_user

from app.services.briefing import context, rollout
from app.services.briefing.rollout import provision_existing_user
from shared.py.wide_events import log, log_context

USER_ID = "user-abc"


class FakeIntegrationRepo:
    def __init__(self, count: int) -> None:
        self.count = count
        self.calls: list[str] = []

    async def count_for_user(self, user_id: str) -> int:
        self.calls.append(user_id)
        return self.count


class FakeTodoRepo:
    def __init__(self, count: int) -> None:
        self.count = count
        self.calls: list[str] = []

    async def count_gaia_assigned(self, user_id: str) -> int:
        self.calls.append(user_id)
        return self.count


class FakeUserRepo:
    def __init__(self) -> None:
        self.bootstrap_calls: list[str] = []

    async def set_briefing_bootstrap_pending(self, user_id: str) -> None:
        self.bootstrap_calls.append(user_id)


class Harness:
    def __init__(self) -> None:
        self.user: dict[str, Any] | None = make_user(user_id=USER_ID)
        self.lookups: list[str] = []
        self.has_goal = True
        self.goal_calls: list[tuple[str, dict[str, Any]]] = []
        self.provisioned: list[str] = []
        self.tracked: list[tuple[str, str, dict[str, Any] | None]] = []
        self.integrations = FakeIntegrationRepo(0)
        self.todos = FakeTodoRepo(0)
        self.users = FakeUserRepo()


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    h = Harness()

    async def fake_get_user_by_id(user_id: str) -> dict[str, Any] | None:
        h.lookups.append(user_id)
        return h.user

    async def fake_provision(user_id: str) -> list[Any]:
        h.provisioned.append(user_id)
        return []

    async def fake_format_goal_block(user_id: str, user: dict[str, Any]) -> tuple[str, bool]:
        h.goal_calls.append((user_id, dict(user)))
        return ("goal block", h.has_goal)

    def fake_track(user_id: str, event: str, properties: dict[str, Any] | None = None) -> None:
        h.tracked.append((user_id, event, properties))

    monkeypatch.setattr(rollout, "get_user_by_id", fake_get_user_by_id)
    monkeypatch.setattr(rollout, "provision_briefing_workflows", fake_provision)
    monkeypatch.setattr(context, "format_goal_block", fake_format_goal_block)
    monkeypatch.setattr(rollout, "track", fake_track)
    monkeypatch.setattr(rollout, "user_integration_repository", h.integrations)
    monkeypatch.setattr(rollout, "todo_repository", h.todos)
    monkeypatch.setattr(rollout, "user_repository", h.users)
    return h


@pytest.mark.unit
class TestUnknownUser:
    async def test_returns_skipped_and_touches_nothing(self, harness: Harness) -> None:
        harness.user = None

        assert await provision_existing_user(USER_ID) == "skipped"
        assert harness.provisioned == []
        assert harness.goal_calls == []
        assert harness.users.bootstrap_calls == []
        assert harness.tracked == []


@pytest.mark.unit
class TestNormalPath:
    async def test_derivable_goal_provisions_and_reports_normal(self, harness: Harness) -> None:
        harness.has_goal = True

        assert await provision_existing_user(USER_ID) == "normal"
        assert harness.lookups == [USER_ID]
        assert harness.provisioned == [USER_ID]
        assert harness.users.bootstrap_calls == []
        assert harness.tracked == [(USER_ID, "briefing_provisioned", {"path": "normal"})]

    async def test_goal_derivation_receives_the_user_id_stamped_on_the_user(
        self, harness: Harness
    ) -> None:
        harness.user = make_user(user_id="stale-id")

        await provision_existing_user(USER_ID)

        assert len(harness.goal_calls) == 1
        called_user_id, called_user = harness.goal_calls[0]
        assert called_user_id == USER_ID
        assert called_user["user_id"] == USER_ID

    async def test_no_goal_but_busy_account_is_still_normal(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 2
        harness.todos.count = 0

        assert await provision_existing_user(USER_ID) == "normal"
        assert harness.users.bootstrap_calls == []
        assert harness.tracked == [(USER_ID, "briefing_provisioned", {"path": "normal"})]

    async def test_no_goal_but_gaia_todos_exist_is_normal(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 0
        harness.todos.count = 1

        assert await provision_existing_user(USER_ID) == "normal"
        assert harness.users.bootstrap_calls == []
        assert harness.tracked == [(USER_ID, "briefing_provisioned", {"path": "normal"})]


@pytest.mark.unit
class TestBootstrapPath:
    async def test_no_goal_and_sparse_account_holds_briefings(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 1
        harness.todos.count = 0

        assert await provision_existing_user(USER_ID) == "bootstrap"
        assert harness.provisioned == [USER_ID]
        assert harness.users.bootstrap_calls == [USER_ID]
        assert harness.tracked == [(USER_ID, "briefing_provisioned", {"path": "bootstrap"})]

    async def test_zero_integrations_and_zero_todos_is_sparse(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 0
        harness.todos.count = 0

        assert await provision_existing_user(USER_ID) == "bootstrap"
        assert harness.users.bootstrap_calls == [USER_ID]

    async def test_sparsity_is_measured_for_the_same_user(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 1
        harness.todos.count = 0

        await provision_existing_user(USER_ID)

        assert harness.integrations.calls == [USER_ID]
        assert harness.todos.calls == [USER_ID]


@pytest.mark.unit
class TestWideEvent:
    """The rollout runs from a script and a worker, so its wide event is the
    only place an operator can see which user took which path."""

    async def test_stamps_the_component_operation_and_user(self, harness: Harness) -> None:
        async with log_context("briefing_rollout_test"):
            await provision_existing_user(USER_ID)
            event = dict(log.get())

        assert event["component"] == "briefing_rollout"
        assert event["operation"] == "provision_existing_user"
        assert event["user_id"] == USER_ID

    async def test_an_unknown_user_is_warned_with_the_id_that_was_missing(
        self, harness: Harness
    ) -> None:
        harness.user = None

        async with log_context("briefing_rollout_test"):
            assert await provision_existing_user(USER_ID) == "skipped"
            event = dict(log.get())

        assert event["warnings"] == [{"msg": "briefing_rollout.unknown_user", "user_id": USER_ID}]
