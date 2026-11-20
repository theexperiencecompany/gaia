"""Unit tests for the existing-user briefing rollout.

Every seam is faked; provision_existing_user itself runs for real.
"""

from typing import Any

import pytest
from tests.factories import make_user_id
from tests.helpers import captured_wide_event

from app.models.user_models import OnboardingSubdocument, UserDocument
from app.services.briefing import rollout
from app.services.briefing.rollout import provision_existing_user
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingProvisioned

USER_ID = make_user_id()
_ONBOARDED = OnboardingSubdocument(completed=True)


class FakeUserRepo:
    def __init__(self) -> None:
        self.user: UserDocument | None = UserDocument(id=USER_ID, onboarding=_ONBOARDED)
        self.lookups: list[str] = []

    async def get(self, user_id: str) -> UserDocument | None:
        self.lookups.append(user_id)
        return self.user


class FakeBriefingRepo:
    def __init__(self) -> None:
        self.briefed = False

    async def has_daily_briefing(self, user_id: str) -> bool:
        assert user_id == USER_ID
        return self.briefed


class Harness:
    def __init__(self) -> None:
        self.briefings = FakeBriefingRepo()
        self.provisioned: list[str] = []
        self.captured: list[tuple[UserId, Any]] = []
        self.users = FakeUserRepo()


def _provisioned() -> list[tuple[UserId, Any]]:
    return [(UserId(USER_ID), BriefingProvisioned())]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    h = Harness()

    async def fake_provision(user_id: str) -> list[Any]:
        h.provisioned.append(user_id)
        return []

    def fake_capture(user_id: UserId, event: Any) -> None:
        h.captured.append((user_id, event))

    monkeypatch.setattr(rollout, "provision_briefing_workflows", fake_provision)
    monkeypatch.setattr(rollout, "capture", fake_capture)
    monkeypatch.setattr(rollout, "user_repository", h.users)
    monkeypatch.setattr(rollout, "briefing_repository", h.briefings)
    return h


@pytest.mark.unit
class TestReRun:
    async def test_a_user_already_briefed_is_left_as_they_are(self, harness: Harness) -> None:
        harness.briefings.briefed = True

        assert await provision_existing_user(USER_ID) == "already_rolled_out"
        assert harness.provisioned == [USER_ID]
        assert harness.captured == []


@pytest.mark.unit
class TestUnknownUser:
    async def test_returns_skipped_and_touches_nothing(self, harness: Harness) -> None:
        harness.users.user = None

        assert await provision_existing_user(USER_ID) == "skipped"
        assert harness.provisioned == []
        assert harness.captured == []


@pytest.mark.unit
class TestMidOnboarding:
    @pytest.mark.regression
    @pytest.mark.parametrize(
        "onboarding", [None, OnboardingSubdocument(completed=False)], ids=["none", "unfinished"]
    )
    async def test_a_user_still_in_the_wizard_is_left_to_it(
        self, harness: Harness, onboarding: OnboardingSubdocument | None
    ) -> None:
        harness.users.user = UserDocument(id=USER_ID, onboarding=onboarding)

        assert await provision_existing_user(USER_ID) == "mid_onboarding"
        assert harness.provisioned == []
        assert harness.captured == []


@pytest.mark.unit
class TestNormalPath:
    async def test_a_user_with_no_goal_is_provisioned_and_briefed_like_any_other(
        self, harness: Harness
    ) -> None:
        assert await provision_existing_user(USER_ID) == "normal"
        assert harness.users.lookups == [USER_ID]
        assert harness.provisioned == [USER_ID]
        assert harness.captured == _provisioned()


@pytest.mark.unit
class TestWideEvent:
    """The rollout runs from a script and a worker.

    Its wide event is therefore the only place an operator can see which user took which
    path.
    """

    async def test_stamps_the_component_operation_and_user(self, harness: Harness) -> None:
        async with captured_wide_event() as event:
            await provision_existing_user(USER_ID)

        assert event["component"] == "briefing_rollout"
        assert event["operation"] == "provision_existing_user"
        assert event["user_id"] == USER_ID

    async def test_an_unknown_user_is_warned_with_the_id_that_was_missing(
        self, harness: Harness
    ) -> None:
        harness.users.user = None

        async with captured_wide_event() as event:
            assert await provision_existing_user(USER_ID) == "skipped"

        assert event["warnings"] == [{"msg": "briefing_rollout.unknown_user", "user_id": USER_ID}]
