"""The activation checklist derives every ``done`` from a real signal at read
time; only the collapse is persisted. Repositories are the seams."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.first_steps_models import FirstStepKey, FirstStepsResponse, FirstStepsState
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents
from app.services.first_steps_service import get_first_steps, set_first_steps_collapsed
from app.utils.errors import AppError

MODULE = "app.services.first_steps_service"
USER_ID = "507f1f77bcf86cd799439011"


def _user(**overrides: object) -> UserDocument:
    return UserDocument.model_validate({"id": USER_ID, "email": "test@example.com", **overrides})


@pytest.fixture
def repos():
    """Every signal false, user present, not collapsed — tests flip one at a time."""
    with (
        patch(f"{MODULE}.user_repository") as users,
        patch(f"{MODULE}.conversation_repository") as conversations,
        patch(f"{MODULE}.get_all_integrations_status", new_callable=AsyncMock) as integrations,
        patch(f"{MODULE}.workflow_repository") as workflows,
        patch(f"{MODULE}.capture_context_event") as capture,
    ):
        users.get = AsyncMock(return_value=_user())
        users.set_first_steps_collapsed = AsyncMock(return_value=True)
        conversations.has_sent_message = AsyncMock(return_value=False)
        integrations.return_value = {"gmail": False, "notion": False}
        workflows.count_for_user = AsyncMock(return_value=0)
        yield {
            "users": users,
            "conversations": conversations,
            "integrations": integrations,
            "workflows": workflows,
            "capture": capture,
        }


def _done(response: FirstStepsResponse) -> dict[FirstStepKey, bool]:
    return {step.key: step.done for step in response.steps}


def _assert_user_not_found(error: AppError) -> None:
    """The 404 every entry point raises, including the id an operator needs."""
    assert error.status_code == 404
    assert error.message == "User not found"
    assert error.why == "no user document matches the authenticated session's id"
    assert error.meta == {"user_id": USER_ID}


@pytest.mark.unit
class TestFirstStepKey:
    def test_members_in_checklist_order(self) -> None:
        assert [key.value for key in FirstStepKey] == [
            "say_hi",
            "connect_integration",
            "link_platform",
            "create_workflow",
        ]


@pytest.mark.unit
class TestGetFirstSteps:
    async def test_fresh_user_has_every_step_open_and_is_expanded(self, repos) -> None:
        result = await get_first_steps(USER_ID)

        assert [step.key for step in result.steps] == list(FirstStepKey)
        assert _done(result) == dict.fromkeys(FirstStepKey, False)
        assert result.collapsed is False
        repos["users"].get.assert_awaited_once_with(USER_ID)

    async def test_say_hi_is_the_sent_message_signal(self, repos) -> None:
        repos["conversations"].has_sent_message.return_value = True

        result = await get_first_steps(USER_ID)

        assert _done(result)[FirstStepKey.SAY_HI] is True
        repos["conversations"].has_sent_message.assert_awaited_once_with(USER_ID)

    async def test_connect_integration_counts_any_connected_integration(self, repos) -> None:
        repos["integrations"].return_value = {"gmail": False, "notion": True}

        result = await get_first_steps(USER_ID)

        assert _done(result)[FirstStepKey.CONNECT_INTEGRATION] is True
        repos["integrations"].assert_awaited_once_with(USER_ID)

    async def test_connect_integration_counts_gmail(self, repos) -> None:
        """Gmail is self-managed, so it only reads as connected through the
        canonical status map — a raw ``user_integrations`` count misses it."""
        repos["integrations"].return_value = {"gmail": True, "notion": False}

        assert _done(await get_first_steps(USER_ID))[FirstStepKey.CONNECT_INTEGRATION] is True

    async def test_link_platform_needs_a_link_with_an_id(self, repos) -> None:
        repos["users"].get.return_value = _user(platform_links={"telegram": {"id": "42"}})

        assert _done(await get_first_steps(USER_ID))[FirstStepKey.LINK_PLATFORM] is True

    async def test_link_platform_ignores_a_link_without_an_id(self, repos) -> None:
        repos["users"].get.return_value = _user(platform_links={"telegram": {"id": ""}})

        assert _done(await get_first_steps(USER_ID))[FirstStepKey.LINK_PLATFORM] is False

    async def test_create_workflow_is_done_at_the_very_first_workflow(self, repos) -> None:
        repos["workflows"].count_for_user.return_value = 1

        assert _done(await get_first_steps(USER_ID))[FirstStepKey.CREATE_WORKFLOW] is True

    async def test_create_workflow_excludes_todo_and_system_workflows(self, repos) -> None:
        repos["workflows"].count_for_user.return_value = 2

        result = await get_first_steps(USER_ID)

        assert _done(result)[FirstStepKey.CREATE_WORKFLOW] is True
        repos["workflows"].count_for_user.assert_awaited_once_with(
            USER_ID, exclude_todo_workflows=True, exclude_system_workflows=True
        )

    async def test_collapsed_is_read_from_the_user_document(self, repos) -> None:
        repos["users"].get.return_value = _user(first_steps=FirstStepsState(collapsed=True))

        assert (await get_first_steps(USER_ID)).collapsed is True

    async def test_missing_user_is_a_404(self, repos) -> None:
        repos["users"].get.return_value = None

        with pytest.raises(AppError) as excinfo:
            await get_first_steps(USER_ID)
        _assert_user_not_found(excinfo.value)


@pytest.mark.unit
class TestSetFirstStepsCollapsed:
    @pytest.mark.parametrize("collapsed", [True, False])
    async def test_persists_either_direction_and_returns_the_checklist(
        self, repos, collapsed: bool
    ) -> None:
        repos["users"].get.return_value = _user(first_steps=FirstStepsState(collapsed=collapsed))
        repos["conversations"].has_sent_message.return_value = True

        result = await set_first_steps_collapsed(USER_ID, collapsed)

        repos["users"].set_first_steps_collapsed.assert_awaited_once_with(USER_ID, collapsed)
        repos["users"].get.assert_awaited_once_with(USER_ID)
        assert result.collapsed is collapsed
        assert _done(result)[FirstStepKey.SAY_HI] is True

    async def test_emits_the_collapse_event_with_counts_only(self, repos) -> None:
        repos["users"].get.return_value = _user(
            first_steps=FirstStepsState(collapsed=True),
            platform_links={"telegram": {"id": "42"}},
        )
        repos["conversations"].has_sent_message.return_value = True

        await set_first_steps_collapsed(USER_ID, True)

        repos["capture"].assert_called_once_with(
            AnalyticsEvents.FIRST_STEPS_COLLAPSED,
            {"collapsed": True, "steps_done": 2, "steps_total": len(FirstStepKey)},
        )

    async def test_missing_user_is_a_404_and_emits_nothing(self, repos) -> None:
        repos["users"].set_first_steps_collapsed.return_value = False

        with pytest.raises(AppError) as excinfo:
            await set_first_steps_collapsed(USER_ID, True)
        _assert_user_not_found(excinfo.value)
        repos["capture"].assert_not_called()
