"""Unit tests for the existing-user briefing rollout.

Every seam is faked; provision_existing_user itself runs for real.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.models.user_models import BriefingBootstrap, UserDocument
from app.services.briefing import context, rollout
from app.services.briefing.rollout import provision_existing_user
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingProvisioned
from shared.py.wide_events import log, log_context

USER_ID = "64f1c0ffee0000000000abcd"


class FakeIntegrationRepo:
    def __init__(self, count: int) -> None:
        self.count = count
        self.calls: list[str] = []

    async def count_for_user(self, user_id: str) -> int:
        self.calls.append(user_id)
        return self.count


class FakeUserRepo:
    def __init__(self) -> None:
        self.user: UserDocument | None = UserDocument(id=USER_ID)
        self.lookups: list[str] = []
        self.bootstrap_calls: list[str] = []

    async def get(self, user_id: str) -> UserDocument | None:
        self.lookups.append(user_id)
        return self.user

    async def set_briefing_bootstrap_pending(self, user_id: str) -> None:
        self.bootstrap_calls.append(user_id)


class FakeBriefingRepo:
    def __init__(self) -> None:
        self.briefed = False

    async def has_daily_briefing(self, user_id: str) -> bool:
        assert user_id == USER_ID
        return self.briefed


class Harness:
    def __init__(self) -> None:
        self.briefings = FakeBriefingRepo()
        self.has_goal = True
        self.goal_calls: list[tuple[str, UserDocument]] = []
        self.provisioned: list[str] = []
        self.captured: list[tuple[UserId, Any]] = []
        self.integrations = FakeIntegrationRepo(0)
        self.users = FakeUserRepo()


def _provisioned(held_for_goal: bool) -> list[tuple[UserId, Any]]:
    return [(UserId(USER_ID), BriefingProvisioned(held_for_goal=held_for_goal))]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    h = Harness()

    async def fake_provision(user_id: str) -> list[Any]:
        h.provisioned.append(user_id)
        return []

    async def fake_format_goal_block(user_id: str, user: UserDocument) -> tuple[str, bool]:
        h.goal_calls.append((user_id, user))
        return ("goal block", h.has_goal)

    def fake_capture(user_id: UserId, event: Any) -> None:
        h.captured.append((user_id, event))

    monkeypatch.setattr(rollout, "provision_briefing_workflows", fake_provision)
    monkeypatch.setattr(context, "format_goal_block", fake_format_goal_block)
    monkeypatch.setattr(rollout, "capture", fake_capture)
    monkeypatch.setattr(rollout, "user_integration_repository", h.integrations)
    monkeypatch.setattr(rollout, "user_repository", h.users)
    monkeypatch.setattr(rollout, "briefing_repository", h.briefings)
    return h


@pytest.mark.unit
class TestReRun:
    """A second rollout pass leaves a user's held or briefed state exactly as it was."""

    async def test_a_user_already_held_keeps_their_grace_window(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.users.user = UserDocument(
            id=USER_ID,
            briefing_bootstrap=BriefingBootstrap(
                pending=True, since=datetime(2026, 10, 1, tzinfo=UTC)
            ),
        )

        assert await provision_existing_user(USER_ID) == "already_rolled_out"
        assert harness.users.bootstrap_calls == []
        assert harness.provisioned == [USER_ID]

    async def test_a_user_already_briefed_is_never_held(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.briefings.briefed = True

        assert await provision_existing_user(USER_ID) == "already_rolled_out"
        assert harness.users.bootstrap_calls == []
        assert harness.captured == []


@pytest.mark.unit
class TestUnknownUser:
    async def test_returns_skipped_and_touches_nothing(self, harness: Harness) -> None:
        harness.users.user = None

        assert await provision_existing_user(USER_ID) == "skipped"
        assert harness.provisioned == []
        assert harness.goal_calls == []
        assert harness.users.bootstrap_calls == []
        assert harness.captured == []


@pytest.mark.unit
class TestNormalPath:
    async def test_derivable_goal_provisions_and_reports_normal(self, harness: Harness) -> None:
        harness.has_goal = True

        assert await provision_existing_user(USER_ID) == "normal"
        assert harness.users.lookups == [USER_ID]
        assert harness.provisioned == [USER_ID]
        assert harness.users.bootstrap_calls == []
        assert harness.captured == _provisioned(held_for_goal=False)

    async def test_goal_derivation_reads_the_user_that_was_looked_up(
        self, harness: Harness
    ) -> None:
        await provision_existing_user(USER_ID)

        assert harness.goal_calls == [(USER_ID, harness.users.user)]

    async def test_no_goal_but_busy_account_is_still_normal(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 2

        assert await provision_existing_user(USER_ID) == "normal"
        assert harness.users.bootstrap_calls == []
        assert harness.captured == _provisioned(held_for_goal=False)


@pytest.mark.unit
class TestBootstrapPath:
    async def test_no_goal_and_sparse_account_holds_briefings(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 1

        assert await provision_existing_user(USER_ID) == "bootstrap"
        assert harness.provisioned == [USER_ID]
        assert harness.users.bootstrap_calls == [USER_ID]
        assert harness.captured == _provisioned(held_for_goal=True)

    async def test_zero_integrations_is_sparse(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 0

        assert await provision_existing_user(USER_ID) == "bootstrap"
        assert harness.users.bootstrap_calls == [USER_ID]

    async def test_sparsity_is_measured_for_the_same_user(self, harness: Harness) -> None:
        harness.has_goal = False
        harness.integrations.count = 1

        await provision_existing_user(USER_ID)

        assert harness.integrations.calls == [USER_ID]


@pytest.mark.unit
class TestWideEvent:
    """The rollout runs from a script and a worker.

    Its wide event is therefore the only place an operator can see which user took which
    path.
    """

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
        harness.users.user = None

        async with log_context("briefing_rollout_test"):
            assert await provision_existing_user(USER_ID) == "skipped"
            event = dict(log.get())

        assert event["warnings"] == [{"msg": "briefing_rollout.unknown_user", "user_id": USER_ID}]
