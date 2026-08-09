"""Unit tests for the onboarding API endpoints.

Tests cover:
- POST /api/v1/onboarding            (complete onboarding)
- POST /api/v1/onboarding/integrations (submit selected integrations)
- POST /api/v1/onboarding/clarify-questions (no-Gmail follow-up questions)
- POST /api/v1/onboarding/reset      (reset onboarding)
- GET  /api/v1/onboarding/status     (get onboarding status)
- POST /api/v1/onboarding/phase      (update onboarding phase)
- PATCH /api/v1/onboarding/preferences (update preferences)
- GET  /api/v1/onboarding/personalization (get personalization data)
- POST /api/v1/onboarding/writing-style (save edited writing style summary)
- POST /api/v1/onboarding/writing-style/regenerate-example
- POST /api/v1/onboarding/social-profiles

Plus direct unit tests for the module-level helpers the personalization
endpoint delegates to (_resolve_account_identity, _resolve_display_bio,
_load_suggested_workflows, _build_writing_style, _load_onboarding_todos).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import BackgroundTasks
from httpx import AsyncClient

from app.api.v1.endpoints.onboarding import (
    _BIO_PROCESSING_MESSAGE,
    _build_writing_style,
    _load_onboarding_todos,
    _load_suggested_workflows,
    _normalize_example_blocks,
    _resolve_account_identity,
    _resolve_display_bio,
)
from app.constants.todos import ONBOARDING_TODO_LIMIT
from app.models.onboarding_models import (
    ClarifyQuestion,
    OnboardingResetCounts,
    PersonalizationTodo,
    PersonalizationWorkflow,
    SocialProfile,
    WritingStyleExampleBlocks,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import (
    BioStatus,
    OnboardingIntegrationsStatus,
    OnboardingPhase,
    OnboardingPreferences,
    OnboardingStatusResponse,
    UserDocument,
)
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument, WorkflowStep

BASE_URL = "/api/v1/onboarding"
STATUS_URL = f"{BASE_URL}/status"
PHASE_URL = f"{BASE_URL}/phase"
PREFERENCES_URL = f"{BASE_URL}/preferences"
PERSONALIZATION_URL = f"{BASE_URL}/personalization"
INTEGRATIONS_URL = f"{BASE_URL}/integrations"
CLARIFY_URL = f"{BASE_URL}/clarify-questions"
RESET_URL = f"{BASE_URL}/reset"
WRITING_STYLE_URL = f"{BASE_URL}/writing-style"
REGENERATE_EXAMPLE_URL = f"{BASE_URL}/writing-style/regenerate-example"
SOCIAL_PROFILES_URL = f"{BASE_URL}/social-profiles"

# Patch targets
_COMPLETE_ONBOARDING = "app.api.v1.endpoints.onboarding.complete_onboarding"
_GET_STATUS = "app.api.v1.endpoints.onboarding.get_user_onboarding_status"
_REPO = "app.api.v1.endpoints.onboarding.user_repository"
_GET_USER = _REPO + ".get"
_SET_PHASE = _REPO + ".set_onboarding_phase"
_COUNT_BEFORE = _REPO + ".count_created_before"
_UPDATE_PREFERENCES = "app.api.v1.endpoints.onboarding.update_onboarding_preferences"
_COMPOSIO_SERVICE = "app.api.v1.endpoints.onboarding.get_composio_service"
_WEBSOCKET_MANAGER = "app.api.v1.endpoints.onboarding.websocket_manager"
_REDIS_POOL_MANAGER = "app.utils.redis_utils.RedisPoolManager"
_SUBMIT_INTEGRATIONS = "app.api.v1.endpoints.onboarding.submit_onboarding_integrations"
_GENERATE_CLARIFY = "app.api.v1.endpoints.onboarding.generate_clarify_questions"
_RESET_ONBOARDING = "app.api.v1.endpoints.onboarding.reset_onboarding"
_WORKFLOW_REPO = "app.api.v1.endpoints.onboarding.workflow_repository"
_TODO_REPO = "app.api.v1.endpoints.onboarding.todo_repository"
_SAVE_EDITED_SUMMARY = "app.api.v1.endpoints.onboarding.save_user_edited_summary"
_REGENERATE_EXAMPLE = "app.api.v1.endpoints.onboarding.regenerate_example_for_style"
_SAVE_GENERATED_EXAMPLE = "app.api.v1.endpoints.onboarding.save_generated_example"
_SAVE_CONFIRMED_PROFILES = "app.api.v1.endpoints.onboarding.save_confirmed_profiles"

USER_ID = "507f1f77bcf86cd799439011"


def _make_onboarding_request(**overrides) -> dict:
    base = {
        "name": "Test User",
        "profession": "Developer",
        "timezone": "UTC",
    }
    base.update(overrides)
    return base


def _make_user_doc(**overrides) -> UserDocument:
    base = {
        "id": USER_ID,
        "name": "Test User",
        "onboarding": {
            "phase": "personalization_complete",
            "house": "Bluehaven",
            "personality_phrase": "Curious Explorer",
            "user_bio": "A bio about the user.",
            "bio_status": "completed",
            "suggested_workflows": [],
            "overlay_color": "rgba(0,0,0,0)",
            "overlay_opacity": 40,
            "account_number": 42,
            "member_since": "Jan 01, 2025",
        },
        "created_at": None,
    }
    base.update(overrides)
    return UserDocument.model_validate(base)


def _make_workflow(workflow_id: str, title: str, description: str) -> WorkflowDocument:
    return WorkflowDocument(
        id=workflow_id,
        user_id=USER_ID,
        title=title,
        description=description,
        steps=[WorkflowStep(title="Step one", description="Do the thing")],
        trigger_config=TriggerConfig(type=TriggerType.MANUAL),
    )


def _make_todo(todo_id: str, title: str | None, *, source_email: str | None = None) -> TodoDocument:
    return TodoDocument(
        id=todo_id,
        user_id=USER_ID,
        title=title or "",
        description="A generated task",
        source_email=source_email,
    )


@contextmanager
def _override_current_user(test_app, user: dict) -> Iterator[None]:
    """Swap the get_current_user override for one test, restoring the default."""
    from app.api.v1.dependencies.oauth_dependencies import get_current_user

    original = test_app.dependency_overrides.get(get_current_user)
    test_app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        if original is None:
            test_app.dependency_overrides.pop(get_current_user, None)
        else:
            test_app.dependency_overrides[get_current_user] = original


def _mock_composio(gmail: bool) -> MagicMock:
    mock_composio = MagicMock()
    mock_composio.check_connection_status = AsyncMock(return_value={"gmail": gmail})
    return mock_composio


# ---------------------------------------------------------------------------
# POST /onboarding (complete onboarding)
# ---------------------------------------------------------------------------


class TestCompleteOnboarding:
    """Tests for the complete user onboarding endpoint."""

    async def test_complete_onboarding_success(self, client: AsyncClient, test_app):
        mock_composio = _mock_composio(gmail=False)
        with (
            patch(
                _COMPLETE_ONBOARDING,
                new_callable=AsyncMock,
                return_value={
                    "user_id": USER_ID,
                    "name": "Test User",
                },
            ) as mock_complete,
            patch(_COMPOSIO_SERVICE, return_value=mock_composio),
            patch(
                _GET_USER,
                new_callable=AsyncMock,
                return_value=UserDocument(email_memory_processed=False),
            ),
            patch(
                _REDIS_POOL_MANAGER + ".get_pool",
                new_callable=AsyncMock,
                return_value=AsyncMock(),
            ),
        ):
            response = await client.post(BASE_URL, json=_make_onboarding_request())

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Onboarding completed successfully"
        assert data["user"] == {"user_id": USER_ID, "name": "Test User"}
        mock_complete.assert_awaited_once()
        args, _kwargs = mock_complete.await_args
        assert args[0] == USER_ID
        assert args[1].name == "Test User"
        assert args[1].profession == "Developer"
        assert args[1].timezone == "UTC"
        assert isinstance(args[2], BackgroundTasks)

    async def test_complete_onboarding_invalid_timezone_returns_422(self, client: AsyncClient):
        response = await client.post(
            BASE_URL,
            json=_make_onboarding_request(timezone="Not/AZone"),
        )
        assert response.status_code == 422

    async def test_complete_onboarding_missing_name_returns_422(self, client: AsyncClient):
        response = await client.post(
            BASE_URL,
            json={"profession": "Developer"},
        )
        assert response.status_code == 422

    async def test_complete_onboarding_missing_profession_returns_422(self, client: AsyncClient):
        response = await client.post(
            BASE_URL,
            json={"name": "Test User"},
        )
        assert response.status_code == 422

    async def test_complete_onboarding_empty_name_returns_422(self, client: AsyncClient):
        response = await client.post(
            BASE_URL,
            json={"name": "", "profession": "Developer"},
        )
        assert response.status_code == 422

    async def test_complete_onboarding_invalid_name_characters_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            BASE_URL,
            json={"name": "Test123!", "profession": "Developer"},
        )
        assert response.status_code == 422

    async def test_complete_onboarding_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _COMPLETE_ONBOARDING,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB failure"),
        ):
            response = await client.post(BASE_URL, json=_make_onboarding_request())

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to complete onboarding"

    async def test_complete_onboarding_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.post(BASE_URL, json=_make_onboarding_request())
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /onboarding/integrations
# ---------------------------------------------------------------------------


class TestSubmitIntegrations:
    """POST /api/v1/onboarding/integrations — split-mode workflow deferral."""

    async def test_submit_integrations_success(self, client: AsyncClient):
        with patch(
            _SUBMIT_INTEGRATIONS,
            new_callable=AsyncMock,
            return_value=OnboardingIntegrationsStatus.QUEUED,
        ) as mock_submit:
            response = await client.post(
                INTEGRATIONS_URL, json={"selected_integrations": ["gmail", "slack"]}
            )

        assert response.status_code == 200
        assert response.json() == {"success": True, "status": "queued"}
        mock_submit.assert_awaited_once_with(USER_ID, ["gmail", "slack"])

    async def test_submit_integrations_empty_selection_allowed(self, client: AsyncClient):
        with patch(
            _SUBMIT_INTEGRATIONS,
            new_callable=AsyncMock,
            return_value=OnboardingIntegrationsStatus.QUEUED,
        ) as mock_submit:
            response = await client.post(INTEGRATIONS_URL, json={"selected_integrations": []})

        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        mock_submit.assert_awaited_once_with(USER_ID, [])

    async def test_submit_integrations_dedupes_selection(self, client: AsyncClient):
        with patch(
            _SUBMIT_INTEGRATIONS,
            new_callable=AsyncMock,
            return_value=OnboardingIntegrationsStatus.ALREADY_RUNNING,
        ) as mock_submit:
            response = await client.post(
                INTEGRATIONS_URL,
                json={"selected_integrations": ["gmail", "gmail", "slack", "slack"]},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "already_running"
        mock_submit.assert_awaited_once_with(USER_ID, ["gmail", "slack"])

    async def test_submit_integrations_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _SUBMIT_INTEGRATIONS,
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            response = await client.post(
                INTEGRATIONS_URL, json={"selected_integrations": ["gmail"]}
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to submit integrations"

    async def test_submit_integrations_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.post(
            INTEGRATIONS_URL, json={"selected_integrations": ["gmail"]}
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /onboarding/clarify-questions
# ---------------------------------------------------------------------------


def _make_questions() -> list[ClarifyQuestion]:
    return [
        ClarifyQuestion(
            id="scope",
            kind="scope",
            question="What should GAIA focus on?",
            options=["Work", "Personal"],
        )
    ]


class TestGetClarifyQuestions:
    """POST /api/v1/onboarding/clarify-questions — no-Gmail follow-up."""

    async def test_clarify_questions_success(self, client: AsyncClient):
        with patch(
            _GENERATE_CLARIFY,
            new_callable=AsyncMock,
            return_value=_make_questions(),
        ) as mock_generate:
            response = await client.post(
                CLARIFY_URL,
                json={"name": "Ada", "profession": "Engineer", "focus": "calendar"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["questions"][0]["id"] == "scope"
        assert data["questions"][0]["question"] == "What should GAIA focus on?"
        mock_generate.assert_awaited_once_with("Ada", "Engineer", "calendar", user_id=USER_ID)

    async def test_clarify_questions_empty_fields_fall_back(self, client: AsyncClient):
        """Blank name/profession fall back to 'there'/'professional'; focus is kept."""
        with patch(
            _GENERATE_CLARIFY,
            new_callable=AsyncMock,
            return_value=_make_questions(),
        ) as mock_generate:
            response = await client.post(
                CLARIFY_URL, json={"name": " ", "profession": "  ", "focus": "inbox"}
            )

        assert response.status_code == 200
        mock_generate.assert_awaited_once_with("there", "professional", "inbox", user_id=USER_ID)

    async def test_clarify_questions_missing_focus_returns_400(self, client: AsyncClient):
        with patch(
            _GENERATE_CLARIFY,
            new_callable=AsyncMock,
            return_value=_make_questions(),
        ) as mock_generate:
            response = await client.post(
                CLARIFY_URL, json={"name": "Ada", "profession": "Engineer", "focus": ""}
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Focus is required"
        mock_generate.assert_not_awaited()

    async def test_clarify_questions_missing_fields_returns_422(self, client: AsyncClient):
        response = await client.post(CLARIFY_URL, json={"name": "Ada"})
        assert response.status_code == 422

    async def test_clarify_questions_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.post(
            CLARIFY_URL, json={"name": "Ada", "profession": "Engineer", "focus": "x"}
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /onboarding/reset
# ---------------------------------------------------------------------------


class TestResetOnboarding:
    """POST /api/v1/onboarding/reset — full reset to rerun the flow."""

    async def test_reset_success(self, client: AsyncClient):
        counts = OnboardingResetCounts(
            workflows_deleted=3,
            todos_deleted=5,
            conversation_deleted=1,
            demo_conversations_deleted=0,
            integrations_disconnected=2,
            memories_cleared=4,
        )
        with patch(_RESET_ONBOARDING, new_callable=AsyncMock, return_value=counts) as mock_reset:
            response = await client.post(RESET_URL)

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "workflows_deleted": 3,
            "todos_deleted": 5,
            "conversation_deleted": 1,
            "demo_conversations_deleted": 0,
            "integrations_disconnected": 2,
            "memories_cleared": 4,
        }
        mock_reset.assert_awaited_once_with(USER_ID)

    async def test_reset_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _RESET_ONBOARDING,
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            response = await client.post(RESET_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to reset onboarding"

    async def test_reset_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.post(RESET_URL)
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /onboarding/status
# ---------------------------------------------------------------------------


def _status(*, completed: bool, phase: str | None) -> OnboardingStatusResponse:
    return OnboardingStatusResponse(
        completed=completed,
        completed_at=None,
        phase=phase,
        preferences=OnboardingPreferences(),
        first_message_conversation_id=None,
    )


class TestGetOnboardingStatus:
    """Tests for the get onboarding status endpoint."""

    # BUG: the handler logged `status.get("is_complete")`, a key the service has
    # never returned — the completion flag was always logged as False. The wire
    # field is `completed`, which is what mobile reads.
    async def test_get_status_returns_200(self, client: AsyncClient):
        mock_status = _status(completed=True, phase="completed")
        with patch(_GET_STATUS, new_callable=AsyncMock, return_value=mock_status) as mock_get:
            response = await client.get(STATUS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data == {
            "completed": True,
            "completed_at": None,
            "phase": "completed",
            "preferences": {
                "profession": None,
                "response_style": None,
                "custom_instructions": None,
            },
            "first_message_conversation_id": None,
        }
        mock_get.assert_awaited_once_with(USER_ID)

    async def test_get_status_incomplete_user(self, client: AsyncClient):
        mock_status = _status(completed=False, phase="initial")
        with patch(_GET_STATUS, new_callable=AsyncMock, return_value=mock_status):
            response = await client.get(STATUS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["completed"] is False
        assert data["phase"] == "initial"

    async def test_get_status_service_error(self, client: AsyncClient):
        with patch(
            _GET_STATUS,
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            response = await client.get(STATUS_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to get onboarding status"

    async def test_get_status_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(STATUS_URL)
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /onboarding/phase
# ---------------------------------------------------------------------------


class TestUpdateOnboardingPhase:
    """Tests for the update onboarding phase endpoint."""

    async def test_update_phase_success(self, client: AsyncClient):
        with (
            patch(_SET_PHASE, new_callable=AsyncMock, return_value=True) as mock_set,
            patch(
                _WEBSOCKET_MANAGER + ".broadcast_to_user",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            response = await client.post(PHASE_URL, json={"phase": "getting_started"})

        assert response.status_code == 200
        data = response.json()
        assert data == {
            "success": True,
            "phase": "getting_started",
            "message": "Onboarding phase updated to getting_started",
        }
        mock_set.assert_awaited_once_with(USER_ID, OnboardingPhase.GETTING_STARTED)
        mock_broadcast.assert_awaited_once_with(
            user_id=USER_ID,
            message={
                "type": "onboarding_phase_update",
                "data": {"phase": "getting_started"},
            },
        )

    async def test_update_phase_websocket_failure_still_succeeds(self, client: AsyncClient):
        with (
            patch(_SET_PHASE, new_callable=AsyncMock, return_value=True),
            patch(
                _WEBSOCKET_MANAGER + ".broadcast_to_user",
                new_callable=AsyncMock,
                side_effect=RuntimeError("ws down"),
            ),
        ):
            response = await client.post(PHASE_URL, json={"phase": "completed"})

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["phase"] == "completed"

    async def test_update_phase_user_not_found_returns_404(self, client: AsyncClient):
        with patch(_SET_PHASE, new_callable=AsyncMock, return_value=False):
            response = await client.post(PHASE_URL, json={"phase": "completed"})

        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"

    async def test_update_phase_missing_user_id_returns_400(self, client: AsyncClient, test_app):
        with (
            _override_current_user(test_app, {}),
            patch(_SET_PHASE, new_callable=AsyncMock) as mock_set,
        ):
            response = await client.post(PHASE_URL, json={"phase": "completed"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid user_id"
        mock_set.assert_not_awaited()

    async def test_update_phase_non_string_user_id_returns_400(self, client: AsyncClient, test_app):
        """A truthy non-string user_id is still rejected."""
        with (
            _override_current_user(test_app, {"user_id": 123}),
            patch(_SET_PHASE, new_callable=AsyncMock) as mock_set,
        ):
            response = await client.post(PHASE_URL, json={"phase": "completed"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid user_id"
        mock_set.assert_not_awaited()

    async def test_update_phase_invalid_phase_returns_422(self, client: AsyncClient):
        response = await client.post(PHASE_URL, json={"phase": "nonexistent_phase"})
        assert response.status_code == 422

    async def test_update_phase_missing_body_returns_422(self, client: AsyncClient):
        response = await client.post(PHASE_URL, json={})
        assert response.status_code == 422

    async def test_update_phase_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _SET_PHASE,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(PHASE_URL, json={"phase": "completed"})

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to update onboarding phase"

    async def test_update_phase_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.post(PHASE_URL, json={"phase": "completed"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /onboarding/preferences
# ---------------------------------------------------------------------------


class TestUpdatePreferences:
    """Tests for the update preferences endpoint."""

    async def test_update_preferences_success(self, client: AsyncClient):
        with patch(
            _UPDATE_PREFERENCES,
            new_callable=AsyncMock,
            return_value={"user_id": USER_ID},
        ) as mock_update:
            response = await client.patch(
                PREFERENCES_URL,
                json={
                    "profession": "Engineer",
                    "response_style": "brief",
                    "custom_instructions": "Be concise.",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Preferences updated successfully"
        assert data["user"] == {"user_id": USER_ID}
        mock_update.assert_awaited_once()
        args, _kwargs = mock_update.await_args
        assert args[0] == USER_ID
        assert args[1] == OnboardingPreferences(
            profession="Engineer",
            response_style="brief",
            custom_instructions="Be concise.",
        )

    async def test_update_preferences_empty_body_allowed(self, client: AsyncClient):
        """Empty optional fields should be accepted."""
        with patch(
            _UPDATE_PREFERENCES,
            new_callable=AsyncMock,
            return_value={"user_id": USER_ID},
        ) as mock_update:
            response = await client.patch(PREFERENCES_URL, json={})

        assert response.status_code == 200
        args, _kwargs = mock_update.await_args
        assert args[1] == OnboardingPreferences()

    async def test_update_preferences_empty_response_style_normalized_to_none(
        self, client: AsyncClient
    ):
        """Empty response_style is normalized to None by the model."""
        with patch(
            _UPDATE_PREFERENCES,
            new_callable=AsyncMock,
            return_value={"user_id": USER_ID},
        ) as mock_update:
            response = await client.patch(PREFERENCES_URL, json={"response_style": ""})

        assert response.status_code == 200
        args, _kwargs = mock_update.await_args
        assert args[1] == OnboardingPreferences(response_style=None)

    async def test_update_preferences_custom_response_style_passes_through(
        self, client: AsyncClient
    ):
        """Non-empty custom response styles are allowed by the model."""
        with patch(
            _UPDATE_PREFERENCES,
            new_callable=AsyncMock,
            return_value={"user_id": USER_ID},
        ) as mock_update:
            response = await client.patch(PREFERENCES_URL, json={"response_style": "shouty"})

        assert response.status_code == 200
        args, _kwargs = mock_update.await_args
        assert args[1] == OnboardingPreferences(response_style="shouty")

    async def test_update_preferences_custom_instructions_too_long_returns_422(
        self, client: AsyncClient
    ):
        response = await client.patch(
            PREFERENCES_URL,
            json={"custom_instructions": "a" * 501},
        )
        assert response.status_code == 422

    async def test_update_preferences_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _UPDATE_PREFERENCES,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.patch(
                PREFERENCES_URL,
                json={"profession": "Engineer"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to update preferences"

    async def test_update_preferences_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.patch(PREFERENCES_URL, json={"profession": "Engineer"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /onboarding/personalization
# ---------------------------------------------------------------------------


def _full_personalization_doc(**overrides) -> UserDocument:
    base = {
        "id": USER_ID,
        "name": "Test User",
        "onboarding": {
            "phase": "personalization_complete",
            # Deliberately not the default ("Bluehaven"): the defaults-test pins
            # the fallback path, so a mutation to the .get() key or default here
            # must change the observed payload.
            "house": "mistgrove",
            "personality_phrase": "Curious Explorer",
            "user_bio": "A bio about the user.",
            "bio_status": "completed",
            "account_number": 42,
            "member_since": "Jan 01, 2025",
            "overlay_color": "rgba(10,20,30,0.5)",
            "overlay_opacity": 60,
            "suggested_workflows": ["wf_2", "wf_1"],
            "first_message_conversation_id": "conv_123",
            "first_message": "Welcome to GAIA!",
            "writing_style": {
                "summary": "Short and punchy.",
                "user_edited_summary": "Edited summary.",
                "example": {
                    "greeting": "Hey!",
                    "body": ["Body paragraph."],
                    "signoff": "Best,",
                    "name": "Alex",
                },
            },
            "social_profiles": [
                {"platform": "github", "url": "https://github.com/alex"},
                {"platform": "x", "url": "https://x.com/alex"},
            ],
            "triage_summary": {
                "total_scanned": 12,
                "total_unread": 3,
                "summary": "Mostly newsletters.",
                "patterns": ["newsletters"],
                "important_emails": [
                    {"sender": "boss@corp.com", "subject": "Launch", "why_important": "Deadline"}
                ],
            },
        },
        "created_at": None,
    }
    base.update(overrides)
    return UserDocument.model_validate(base)


class TestGetPersonalization:
    """Tests for the get personalization data endpoint."""

    async def test_get_personalization_full_payload(self, client: AsyncClient):
        user_doc = _full_personalization_doc()
        workflows = [
            _make_workflow("wf_1", "Morning Briefing", "A daily digest"),
            _make_workflow("wf_2", "Focus Time", "Block deep work"),
        ]
        todos = [_make_todo("td_1", "Reply to Sarah", source_email="sarah@x.com")]
        mock_composio = _mock_composio(gmail=False)
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(
                _WORKFLOW_REPO + ".find_by_ids",
                new_callable=AsyncMock,
                return_value=workflows,
            ) as mock_workflows,
            patch(
                _TODO_REPO + ".list_onboarding_todos",
                new_callable=AsyncMock,
                return_value=todos,
            ) as mock_todos,
            patch(_COMPOSIO_SERVICE, return_value=mock_composio),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["phase"] == "personalization_complete"
        assert data["has_personalization"] is True
        assert data["house"] == "mistgrove"
        assert data["personality_phrase"] == "Curious Explorer"
        assert data["user_bio"] == "A bio about the user."
        assert data["account_number"] == 42
        assert data["member_since"] == "Jan 01, 2025"
        assert data["overlay_color"] == "rgba(10,20,30,0.5)"
        assert data["overlay_opacity"] == 60
        assert data["name"] == "Test User"
        assert data["holo_card_id"] == USER_ID
        assert data["first_message_conversation_id"] == "conv_123"
        assert data["first_message"] == "Welcome to GAIA!"
        # Suggested workflows render in the stored order, not find_by_ids' order.
        assert [wf["id"] for wf in data["suggested_workflows"]] == ["wf_2", "wf_1"]
        assert data["suggested_workflows"][0] == {
            "id": "wf_2",
            "title": "Focus Time",
            "description": "Block deep work",
            "steps": [
                {
                    "id": "",
                    "title": "Step one",
                    "category": "general",
                    "description": "Do the thing",
                }
            ],
        }
        assert data["writing_style"] == {
            "style_summary": "Edited summary.",
            "example": {
                "greeting": "Hey!",
                "body": ["Body paragraph."],
                "signoff": "Best,",
                "name": "Alex",
            },
        }
        assert data["social_profiles"] == [
            {"platform": "github", "url": "https://github.com/alex"},
            {"platform": "x", "url": "https://x.com/alex"},
        ]
        assert data["triage_summary"] == {
            "total_scanned": 12,
            "total_unread": 3,
            "summary": "Mostly newsletters.",
            "patterns": ["newsletters"],
            "important_emails": [
                {"sender": "boss@corp.com", "subject": "Launch", "why_important": "Deadline"}
            ],
        }
        assert data["onboarding_todos"] == [
            {
                "id": "td_1",
                "title": "Reply to Sarah",
                "description": "A generated task",
                "source_email": "sarah@x.com",
            }
        ]
        mock_workflows.assert_awaited_once_with(["wf_2", "wf_1"])
        mock_todos.assert_awaited_once_with(USER_ID, limit=ONBOARDING_TODO_LIMIT)
        mock_composio.check_connection_status.assert_not_awaited()

    async def test_get_personalization_user_not_found_returns_404(self, client: AsyncClient):
        with patch(_GET_USER, new_callable=AsyncMock, return_value=None):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"

    async def test_get_personalization_missing_user_id_returns_400(
        self, client: AsyncClient, test_app
    ):
        with (
            _override_current_user(test_app, {}),
            patch(_GET_USER, new_callable=AsyncMock) as mock_get,
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid user_id"
        mock_get.assert_not_awaited()

    async def test_get_personalization_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _GET_USER,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to fetch personalization data"

    async def test_get_personalization_no_phase_defaults(self, client: AsyncClient):
        """User doc with empty onboarding should return default values."""
        user_doc = UserDocument(
            id=USER_ID,
            name="New User",
            onboarding={},
            created_at=None,
        )
        mock_composio = _mock_composio(gmail=False)
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(_COUNT_BEFORE, new_callable=AsyncMock) as mock_count,
            patch(
                _TODO_REPO + ".list_onboarding_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(_COMPOSIO_SERVICE, return_value=mock_composio),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["phase"] == "initial"
        assert data["has_personalization"] is False
        assert data["house"] == "Bluehaven"
        assert data["personality_phrase"] == "Curious Adventurer"
        assert data["user_bio"] == "Setting up your profile..."
        assert data["overlay_color"] == "rgba(0,0,0,0)"
        assert data["overlay_opacity"] == 40
        assert data["suggested_workflows"] == []
        assert data["name"] == "New User"
        assert data["holo_card_id"] == USER_ID
        assert data["first_message_conversation_id"] is None
        assert data["first_message"] is None
        assert data["writing_style"] is None
        assert data["social_profiles"] is None
        assert data["triage_summary"] is None
        assert data["onboarding_todos"] is None
        mock_count.assert_not_awaited()
        mock_composio.check_connection_status.assert_awaited_once_with(["gmail"], USER_ID)

    async def test_get_personalization_backfills_account_identity(self, client: AsyncClient):
        """No stored account_number/member_since -> derived from created_at."""
        user_doc = _full_personalization_doc(
            created_at=datetime(2024, 5, 17, tzinfo=UTC),
            onboarding={
                "phase": "personalization_complete",
                "house": "Bluehaven",
                "bio_status": "completed",
                "user_bio": "Bio",
            },
        )
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=7) as mock_count,
            patch(_COMPOSIO_SERVICE, return_value=_mock_composio(gmail=False)),
            patch(
                _TODO_REPO + ".list_onboarding_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["account_number"] == 8
        assert data["member_since"] == "May 17, 2024"
        mock_count.assert_awaited_once_with(datetime(2024, 5, 17, tzinfo=UTC))

    async def test_get_personalization_pending_bio_with_gmail_connected(self, client: AsyncClient):
        """Pending bio + a Gmail connection promises the processing message."""
        user_doc = _full_personalization_doc(
            onboarding={
                "phase": "personalization_pending",
                "bio_status": "pending",
                "house": "Bluehaven",
            }
        )
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=0),
            patch(_COMPOSIO_SERVICE, return_value=_mock_composio(gmail=True)),
            patch(
                _TODO_REPO + ".list_onboarding_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        assert response.json()["user_bio"] == _BIO_PROCESSING_MESSAGE

    async def test_get_personalization_todos_failure_is_soft(self, client: AsyncClient):
        """Todo fetch failure yields onboarding_todos None, not a 500."""
        user_doc = _full_personalization_doc()
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=0),
            patch(_COMPOSIO_SERVICE, return_value=_mock_composio(gmail=False)),
            patch(
                _TODO_REPO + ".list_onboarding_todos",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        assert response.json()["onboarding_todos"] is None

    async def test_get_personalization_name_falls_back_to_user(self, client: AsyncClient):
        """A doc with no name renders the default 'User' label."""
        user_doc = _full_personalization_doc(name=None)
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=0),
            patch(_COMPOSIO_SERVICE, return_value=_mock_composio(gmail=False)),
            patch(
                _TODO_REPO + ".list_onboarding_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        assert response.json()["name"] == "User"

    async def test_get_personalization_partial_social_profiles_default_empty(
        self, client: AsyncClient
    ):
        """Profiles missing platform or url render with empty-string defaults."""
        user_doc = _full_personalization_doc(
            onboarding={
                "phase": "personalization_complete",
                "house": "mistgrove",
                "bio_status": "completed",
                "social_profiles": [{"platform": "github"}, {"url": "https://x.com/alex"}],
            }
        )
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=0),
            patch(_COMPOSIO_SERVICE, return_value=_mock_composio(gmail=False)),
            patch(
                _TODO_REPO + ".list_onboarding_todos",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        assert response.json()["social_profiles"] == [
            {"platform": "github", "url": ""},
            {"platform": "", "url": "https://x.com/alex"},
        ]

    async def test_get_personalization_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(PERSONALIZATION_URL)
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /onboarding/writing-style
# ---------------------------------------------------------------------------


class TestSaveWritingStyle:
    """POST /api/v1/onboarding/writing-style — save the edited summary."""

    async def test_save_writing_style_success(self, client: AsyncClient):
        with patch(
            _SAVE_EDITED_SUMMARY,
            new_callable=AsyncMock,
        ) as mock_save:
            response = await client.post(
                WRITING_STYLE_URL, json={"edited_summary": "  My edited summary.  "}
            )

        assert response.status_code == 200
        assert response.json() == {"success": True}
        mock_save.assert_awaited_once_with(USER_ID, "My edited summary.")

    async def test_save_writing_style_empty_summary_allowed(self, client: AsyncClient):
        with patch(_SAVE_EDITED_SUMMARY, new_callable=AsyncMock) as mock_save:
            response = await client.post(WRITING_STYLE_URL, json={"edited_summary": "   "})

        assert response.status_code == 200
        mock_save.assert_awaited_once_with(USER_ID, "")

    async def test_save_writing_style_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _SAVE_EDITED_SUMMARY,
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            response = await client.post(WRITING_STYLE_URL, json={"edited_summary": "x"})

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to save writing style"

    async def test_save_writing_style_missing_field_returns_422(self, client: AsyncClient):
        response = await client.post(WRITING_STYLE_URL, json={})
        assert response.status_code == 422

    async def test_save_writing_style_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.post(WRITING_STYLE_URL, json={"edited_summary": "x"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /onboarding/writing-style/regenerate-example
# ---------------------------------------------------------------------------


class TestRegenerateWritingStyleExample:
    """POST /api/v1/onboarding/writing-style/regenerate-example."""

    def _example(self) -> WritingStyleExampleBlocks:
        return WritingStyleExampleBlocks(
            greeting="Hi,",
            body=["Paragraph one.", "Paragraph two."],
            signoff="Cheers,",
            name="Ada",
        )

    async def test_regenerate_example_success(self, client: AsyncClient):
        with (
            patch(
                _REGENERATE_EXAMPLE,
                new_callable=AsyncMock,
                return_value=self._example(),
            ) as mock_regenerate,
            patch(
                _SAVE_GENERATED_EXAMPLE,
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            response = await client.post(
                REGENERATE_EXAMPLE_URL,
                json={"edited_summary": "  Punchy and short.  ", "profession": "Engineer"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "example": {
                "greeting": "Hi,",
                "body": ["Paragraph one.", "Paragraph two."],
                "signoff": "Cheers,",
                "name": "Ada",
            }
        }
        mock_regenerate.assert_awaited_once_with(
            summary="Punchy and short.", user_id=USER_ID, profession="Engineer"
        )
        mock_save.assert_awaited_once_with(USER_ID, self._example())

    async def test_regenerate_example_empty_result_skips_save(self, client: AsyncClient):
        with (
            patch(
                _REGENERATE_EXAMPLE,
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_regenerate,
            patch(
                _SAVE_GENERATED_EXAMPLE,
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            response = await client.post(
                REGENERATE_EXAMPLE_URL,
                json={"edited_summary": "No style yet"},
            )

        assert response.status_code == 200
        assert response.json() == {"example": None}
        mock_regenerate.assert_awaited_once_with(
            summary="No style yet", user_id=USER_ID, profession=""
        )
        mock_save.assert_not_awaited()

    async def test_regenerate_example_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _REGENERATE_EXAMPLE,
            new_callable=AsyncMock,
            side_effect=RuntimeError("llm down"),
        ):
            response = await client.post(REGENERATE_EXAMPLE_URL, json={"edited_summary": "x"})

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to regenerate writing style example"

    async def test_regenerate_example_missing_field_returns_422(self, client: AsyncClient):
        response = await client.post(REGENERATE_EXAMPLE_URL, json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /onboarding/social-profiles
# ---------------------------------------------------------------------------


class TestConfirmSocialProfiles:
    """POST /api/v1/onboarding/social-profiles — save confirmed profiles."""

    async def test_confirm_social_profiles_success(self, client: AsyncClient):
        with patch(
            _SAVE_CONFIRMED_PROFILES,
            new_callable=AsyncMock,
        ) as mock_save:
            response = await client.post(
                SOCIAL_PROFILES_URL,
                json={
                    "profiles": [
                        {"platform": "github", "url": "https://github.com/alex"},
                        {"platform": "x", "url": "https://x.com/alex"},
                    ]
                },
            )

        assert response.status_code == 200
        assert response.json() == {"success": True, "saved": 2}
        mock_save.assert_awaited_once_with(
            USER_ID,
            [
                SocialProfile(platform="github", url="https://github.com/alex"),
                SocialProfile(platform="x", url="https://x.com/alex"),
            ],
        )

    async def test_confirm_social_profiles_empty_list(self, client: AsyncClient):
        with patch(_SAVE_CONFIRMED_PROFILES, new_callable=AsyncMock) as mock_save:
            response = await client.post(SOCIAL_PROFILES_URL, json={"profiles": []})

        assert response.status_code == 200
        assert response.json() == {"success": True, "saved": 0}
        mock_save.assert_awaited_once_with(USER_ID, [])

    async def test_confirm_social_profiles_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _SAVE_CONFIRMED_PROFILES,
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            response = await client.post(
                SOCIAL_PROFILES_URL, json={"profiles": [{"platform": "x", "url": "u"}]}
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to save social profiles"

    async def test_confirm_social_profiles_missing_field_returns_422(self, client: AsyncClient):
        response = await client.post(SOCIAL_PROFILES_URL, json={})
        assert response.status_code == 422

    async def test_confirm_social_profiles_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.post(SOCIAL_PROFILES_URL, json={"profiles": []})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestNormalizeExampleBlocks:
    """_normalize_example_blocks: persisted example -> renderable blocks or None."""

    def test_dict_example_maps_all_fields(self) -> None:
        blocks = _normalize_example_blocks(
            {
                "greeting": "Hey!",
                "body": ["P1", "  ", "P2"],
                "signoff": "Best,",
                "name": "Alex",
            }
        )
        assert blocks == WritingStyleExampleBlocks(
            greeting="Hey!", body=["P1", "P2"], signoff="Best,", name="Alex"
        )

    def test_dict_example_missing_body_returns_none(self) -> None:
        assert _normalize_example_blocks({"greeting": "Hey!"}) is None

    def test_dict_example_whitespace_only_body_returns_none(self) -> None:
        assert _normalize_example_blocks({"body": ["   ", ""]}) is None

    def test_dict_example_coerces_non_string_body(self) -> None:
        blocks = _normalize_example_blocks({"body": [123, "real"]})
        assert blocks is not None
        assert blocks.body == ["123", "real"]

    def test_string_example_becomes_single_paragraph(self) -> None:
        blocks = _normalize_example_blocks("  Legacy example  ")
        assert blocks == WritingStyleExampleBlocks(body=["Legacy example"])

    def test_blank_string_returns_none(self) -> None:
        assert _normalize_example_blocks("   ") is None

    def test_none_returns_none(self) -> None:
        assert _normalize_example_blocks(None) is None

    def test_non_dict_object_returns_none(self) -> None:
        assert _normalize_example_blocks(object()) is None


class TestBuildWritingStyle:
    """_build_writing_style: only surface a style with a usable summary."""

    def test_none_returns_none(self) -> None:
        assert _build_writing_style(None) is None

    def test_empty_dict_returns_none(self) -> None:
        assert _build_writing_style({}) is None

    def test_whitespace_only_summary_returns_none(self) -> None:
        assert _build_writing_style({"summary": "   "}) is None

    def test_prefers_user_edited_summary(self) -> None:
        style = _build_writing_style({"summary": "Original", "user_edited_summary": "Edited"})
        assert style is not None
        assert style.style_summary == "Edited"

    def test_falls_back_to_summary(self) -> None:
        style = _build_writing_style({"summary": "Original"})
        assert style is not None
        assert style.style_summary == "Original"

    def test_no_example_yields_none_example(self) -> None:
        style = _build_writing_style({"summary": "S"})
        assert style is not None
        assert style.example is None

    def test_normalizes_example_blocks(self) -> None:
        style = _build_writing_style({"summary": "S", "example": {"greeting": "Hi", "body": ["P"]}})
        assert style is not None
        assert style.example == WritingStyleExampleBlocks(greeting="Hi", body=["P"])


class TestResolveAccountIdentity:
    """_resolve_account_identity: stored identity wins; else derive from created_at."""

    async def test_stored_identity_used_without_repo_call(self) -> None:
        user_doc = UserDocument(id=USER_ID, created_at=None)
        with patch(_COUNT_BEFORE, new_callable=AsyncMock) as mock_count:
            result = await _resolve_account_identity(
                user_doc, {"account_number": 42, "member_since": "Jan 01, 2025"}
            )

        assert result == (42, "Jan 01, 2025")
        mock_count.assert_not_awaited()

    async def test_partial_stored_identity_is_not_trusted(self) -> None:
        """Only one of account_number/member_since present must still derive
        both — the 'and' join is load-bearing."""
        created_at = datetime(2023, 11, 2, tzinfo=UTC)
        user_doc = UserDocument(id=USER_ID, created_at=created_at)
        with patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=4) as mock_count:
            result = await _resolve_account_identity(user_doc, {"account_number": 42})

        assert result == (5, "Nov 02, 2023")
        mock_count.assert_awaited_once_with(created_at)

    async def test_no_created_at_yields_account_one_and_today(self) -> None:
        user_doc = UserDocument(id=USER_ID, created_at=None)
        with (
            patch("app.api.v1.endpoints.onboarding.datetime") as mock_datetime,
            patch(_COUNT_BEFORE, new_callable=AsyncMock) as mock_count,
        ):
            mock_datetime.now.return_value = datetime(2026, 8, 10, tzinfo=UTC)
            result = await _resolve_account_identity(user_doc, {})

        assert result == (1, "Aug 10, 2026")
        mock_datetime.now.assert_called_once_with(UTC)
        mock_count.assert_not_awaited()

    async def test_derives_from_created_at(self) -> None:
        created_at = datetime(2024, 3, 4, tzinfo=UTC)
        user_doc = UserDocument(id=USER_ID, created_at=created_at)
        with patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=99) as mock_count:
            result = await _resolve_account_identity(user_doc, {})

        assert result == (100, "Mar 04, 2024")
        mock_count.assert_awaited_once_with(created_at)


class TestResolveDisplayBio:
    """_resolve_display_bio: processing/pending/complete bio resolution."""

    async def test_processing_returns_processing_message(self) -> None:
        with patch(_COMPOSIO_SERVICE) as mock_service:
            bio = await _resolve_display_bio({"bio_status": "processing"}, USER_ID)

        assert bio == _BIO_PROCESSING_MESSAGE
        mock_service.assert_not_called()

    async def test_processing_enum_returns_processing_message(self) -> None:
        with patch(_COMPOSIO_SERVICE) as mock_service:
            bio = await _resolve_display_bio({"bio_status": BioStatus.PROCESSING}, USER_ID)

        assert bio == _BIO_PROCESSING_MESSAGE
        mock_service.assert_not_called()

    async def test_completed_returns_stored_bio(self) -> None:
        with patch(_COMPOSIO_SERVICE) as mock_service:
            bio = await _resolve_display_bio(
                {"bio_status": "completed", "user_bio": "A bio."}, USER_ID
            )

        assert bio == "A bio."
        mock_service.assert_not_called()

    async def test_no_gmail_status_returns_stored_bio(self) -> None:
        with patch(_COMPOSIO_SERVICE) as mock_service:
            bio = await _resolve_display_bio(
                {"bio_status": "no_gmail", "user_bio": "Filler bio."}, USER_ID
            )

        assert bio == "Filler bio."
        mock_service.assert_not_called()

    async def test_completed_without_stored_bio_returns_empty_string(self) -> None:
        """A completed status with no user_bio must render an empty bio, not a
        default that hides the mutation of the .get() fallback."""
        with patch(_COMPOSIO_SERVICE) as mock_service:
            bio = await _resolve_display_bio({"bio_status": "completed"}, USER_ID)

        assert bio == ""
        mock_service.assert_not_called()

    async def test_default_pending_without_gmail_returns_setup_message(self) -> None:
        mock_composio = _mock_composio(gmail=False)
        with patch(_COMPOSIO_SERVICE, return_value=mock_composio):
            bio = await _resolve_display_bio({}, USER_ID)

        assert bio == "Setting up your profile..."
        mock_composio.check_connection_status.assert_awaited_once_with(["gmail"], USER_ID)

    async def test_pending_with_gmail_returns_processing_message(self) -> None:
        mock_composio = _mock_composio(gmail=True)
        with patch(_COMPOSIO_SERVICE, return_value=mock_composio):
            bio = await _resolve_display_bio({"bio_status": BioStatus.PENDING}, USER_ID)

        assert bio == _BIO_PROCESSING_MESSAGE
        mock_composio.check_connection_status.assert_awaited_once_with(["gmail"], USER_ID)

    async def test_pending_with_empty_connection_status_returns_setup_message(self) -> None:
        """A connection status missing the 'gmail' key must fall back to the
        setup message — the .get() default is load-bearing."""
        mock_composio = MagicMock()
        mock_composio.check_connection_status = AsyncMock(return_value={})
        with patch(_COMPOSIO_SERVICE, return_value=mock_composio):
            bio = await _resolve_display_bio({"bio_status": "pending"}, USER_ID)

        assert bio == "Setting up your profile..."
        mock_composio.check_connection_status.assert_awaited_once_with(["gmail"], USER_ID)


class TestLoadSuggestedWorkflows:
    """_load_suggested_workflows: stored-order projection with soft failure."""

    async def test_empty_ids_returns_empty_without_repo_call(self) -> None:
        with patch(_WORKFLOW_REPO + ".find_by_ids", new_callable=AsyncMock) as mock_find:
            result = await _load_suggested_workflows([])

        assert result == []
        mock_find.assert_not_awaited()

    async def test_returns_workflows_in_stored_order(self) -> None:
        wf_1 = _make_workflow("wf_1", "One", "First")
        wf_2 = _make_workflow("wf_2", "Two", "Second")
        with patch(
            _WORKFLOW_REPO + ".find_by_ids",
            new_callable=AsyncMock,
            return_value=[wf_1, wf_2],
        ) as mock_find:
            result = await _load_suggested_workflows(["wf_2", "wf_1"])

        assert result == [
            PersonalizationWorkflow(
                id="wf_2",
                title="Two",
                description="Second",
                steps=wf_2.steps,
            ),
            PersonalizationWorkflow(
                id="wf_1",
                title="One",
                description="First",
                steps=wf_1.steps,
            ),
        ]
        mock_find.assert_awaited_once_with(["wf_2", "wf_1"])

    async def test_missing_ids_are_skipped(self) -> None:
        with patch(
            _WORKFLOW_REPO + ".find_by_ids",
            new_callable=AsyncMock,
            return_value=[_make_workflow("wf_1", "One", "First")],
        ):
            result = await _load_suggested_workflows(["wf_1", "missing"])

        assert [wf.id for wf in result] == ["wf_1"]

    async def test_repo_error_soft_fails_to_empty(self) -> None:
        with patch(
            _WORKFLOW_REPO + ".find_by_ids",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            result = await _load_suggested_workflows(["wf_1"])

        assert result == []


class TestLoadOnboardingTodos:
    """_load_onboarding_todos: projection with soft failure."""

    async def test_maps_todo_fields(self) -> None:
        todos = [
            TodoDocument(
                id="td_1",
                user_id=USER_ID,
                title="Reply",
                description="Short reply",
                source_email="sarah@x.com",
            ),
        ]
        titleless = TodoDocument(id="td_2", user_id=USER_ID, title="unused")
        # The model requires a title string, but legacy rows can still carry a
        # null — the projection must degrade to "" exactly like it did before
        # the document was typed. Attribute assignment skips validation.
        titleless.title = None
        todos.append(titleless)
        with patch(
            _TODO_REPO + ".list_onboarding_todos",
            new_callable=AsyncMock,
            return_value=todos,
        ) as mock_list:
            result = await _load_onboarding_todos(USER_ID)

        assert result == [
            PersonalizationTodo(
                id="td_1", title="Reply", description="Short reply", source_email="sarah@x.com"
            ),
            PersonalizationTodo(id="td_2", title="", description=None, source_email=None),
        ]
        mock_list.assert_awaited_once_with(USER_ID, limit=ONBOARDING_TODO_LIMIT)

    async def test_repo_error_soft_fails_to_empty(self) -> None:
        with patch(
            _TODO_REPO + ".list_onboarding_todos",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            result = await _load_onboarding_todos(USER_ID)

        assert result == []
