"""Unit tests for the nurture skip predicates (app/services/nurture/predicates.py).

Each predicate decides whether a nurture step is skipped for a user. The
predicates are the gate before any nurture email is sent — a regression
here silently stops or spams the sequence, so every branch is pinned.
"""

from unittest.mock import AsyncMock, patch

from app.constants.integrations import GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.user_models import UserDocument
from app.services.nurture.predicates import (
    SKIP_PREDICATES,
    google_suite_connected,
    has_workflow,
    linked_platform,
    onboarding_completed,
    used_chat,
    uses_todos,
)


def _user(user_id: str = "u-1", **overrides) -> UserDocument:
    return UserDocument(id=user_id, email="u@example.com", **overrides)


class TestOnboardingCompleted:
    async def test_true_when_marked_completed(self) -> None:
        assert await onboarding_completed(_user(onboarding={"completed": True})) is True

    async def test_false_when_not_completed(self) -> None:
        assert await onboarding_completed(_user()) is False
        assert await onboarding_completed(_user(onboarding={"completed": False})) is False


class TestUsedChat:
    @patch(
        "app.services.nurture.predicates.conversation_repository.count_non_onboarding",
        new_callable=AsyncMock,
    )
    async def test_true_with_a_real_conversation(self, mock_count) -> None:
        mock_count.return_value = 1
        assert await used_chat(_user()) is True
        mock_count.assert_awaited_once_with("u-1")

    @patch(
        "app.services.nurture.predicates.conversation_repository.count_non_onboarding",
        new_callable=AsyncMock,
    )
    async def test_false_without_conversations(self, mock_count) -> None:
        mock_count.return_value = 0
        assert await used_chat(_user()) is False


class TestGoogleSuiteConnected:
    @patch(
        "app.services.nurture.predicates.check_multiple_integrations_status", new_callable=AsyncMock
    )
    async def test_true_when_both_connected(self, mock_check) -> None:
        mock_check.return_value = {GMAIL_INTEGRATION_ID: True, GOOGLE_CALENDAR_INTEGRATION_ID: True}
        assert await google_suite_connected(_user()) is True

    @patch(
        "app.services.nurture.predicates.check_multiple_integrations_status", new_callable=AsyncMock
    )
    async def test_false_when_only_one_connected(self, mock_check) -> None:
        mock_check.return_value = {
            GMAIL_INTEGRATION_ID: True,
            GOOGLE_CALENDAR_INTEGRATION_ID: False,
        }
        assert await google_suite_connected(_user()) is False


class TestUsesTodos:
    @patch("app.services.nurture.predicates.todo_repository.count_for_user", new_callable=AsyncMock)
    async def test_false_below_threshold(self, mock_count) -> None:
        mock_count.return_value = 4
        assert await uses_todos(_user()) is False

    @patch("app.services.nurture.predicates.todo_repository.count_for_user", new_callable=AsyncMock)
    async def test_true_at_threshold(self, mock_count) -> None:
        mock_count.return_value = 5
        assert await uses_todos(_user()) is True


class TestHasWorkflow:
    @patch(
        "app.services.nurture.predicates.workflow_repository.count_for_user", new_callable=AsyncMock
    )
    async def test_true_with_any_workflow(self, mock_count) -> None:
        mock_count.return_value = 1
        assert await has_workflow(_user()) is True
        mock_count.assert_awaited_once_with("u-1", exclude_todo_workflows=False)

    @patch(
        "app.services.nurture.predicates.workflow_repository.count_for_user", new_callable=AsyncMock
    )
    async def test_false_without_workflows(self, mock_count) -> None:
        mock_count.return_value = 0
        assert await has_workflow(_user()) is False


class TestLinkedPlatform:
    async def test_true_when_any_platform_has_an_id(self) -> None:
        user = _user(platform_links={"whatsapp": {"id": "w-1"}})
        assert await linked_platform(user) is True

    async def test_false_when_links_empty_or_unlinked(self) -> None:
        assert await linked_platform(_user()) is False
        user = _user(platform_links={"whatsapp": {}})
        assert await linked_platform(user) is False


def test_skip_predicates_map_exposes_every_predicate() -> None:
    assert set(SKIP_PREDICATES) == {
        "onboarding_completed",
        "used_chat",
        "google_suite_connected",
        "uses_todos",
        "has_workflow",
        "linked_platform",
    }
    for predicate in SKIP_PREDICATES.values():
        assert callable(predicate)
