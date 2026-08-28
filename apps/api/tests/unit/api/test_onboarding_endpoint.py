"""Unit tests for the onboarding API endpoints.

Tests cover:
- POST /api/v1/onboarding           (complete onboarding)
- GET  /api/v1/onboarding/status    (get onboarding status)
- POST /api/v1/onboarding/phase     (update onboarding phase)
- PATCH /api/v1/onboarding/preferences (update preferences)
- GET  /api/v1/onboarding/personalization (get personalization data)
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.models.user_models import (
    OnboardingPreferences,
    OnboardingStatusResponse,
    UserDocument,
)
from app.services.analytics_service import AnalyticsEvents

BASE_URL = "/api/v1/onboarding"
ANALYTICS_PATCH = "app.api.v1.endpoints.onboarding.capture_context_event"
FAKE_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture_context_event for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture_context_event call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


STATUS_URL = f"{BASE_URL}/status"
PHASE_URL = f"{BASE_URL}/phase"
PREFERENCES_URL = f"{BASE_URL}/preferences"
PERSONALIZATION_URL = f"{BASE_URL}/personalization"

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
        "id": "507f1f77bcf86cd799439011",
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


# ---------------------------------------------------------------------------
# POST /onboarding (complete onboarding)
# ---------------------------------------------------------------------------


class TestCompleteOnboarding:
    """Tests for the complete user onboarding endpoint."""

    async def test_complete_onboarding_success(self, client: AsyncClient):
        mock_composio = MagicMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})
        with (
            patch(
                _COMPLETE_ONBOARDING,
                new_callable=AsyncMock,
                return_value={
                    "user_id": "507f1f77bcf86cd799439011",
                    "name": "Test User",
                },
            ),
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


class TestOnboardingAnalytics:
    """Analytics captures on onboarding endpoints."""

    async def test_complete_does_not_capture_completion_it_only_queues(self, client: AsyncClient):
        """Submitting the form QUEUES the pipeline; it does not finish onboarding.

        Capturing here counted the milestone at the wrong moment and counted
        submissions whose pipeline later failed. The worker owns the event and
        fires it once the phase actually reaches PERSONALIZATION_COMPLETE.
        """
        with (
            patch(
                _COMPLETE_ONBOARDING,
                new_callable=AsyncMock,
                return_value={
                    "user_id": "507f1f77bcf86cd799439011",
                    "name": "Test User",
                },
            ),
            patch(
                _REDIS_POOL_MANAGER + ".get_pool",
                new_callable=AsyncMock,
                return_value=AsyncMock(),
            ),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            response = await client.post(BASE_URL, json=_make_onboarding_request())

        assert response.status_code == 200
        captured = [call.args[0] for call in mock_capture.call_args_list]
        assert AnalyticsEvents.ONBOARDING_COMPLETED not in captured

    async def test_update_phase_captures_step_completed(self, client: AsyncClient):
        with (
            patch(_SET_PHASE, new_callable=AsyncMock, return_value=True),
            patch(
                _WEBSOCKET_MANAGER + ".broadcast_to_user",
                new_callable=AsyncMock,
            ),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            response = await client.post(PHASE_URL, json={"phase": "getting_started"})

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.ONBOARDING_STEP_COMPLETED, {"phase": "getting_started"}
        )

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
        assert "Failed to complete onboarding" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /onboarding/status
# ---------------------------------------------------------------------------


def _status(*, completed: bool, phase: str) -> OnboardingStatusResponse:
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
        with patch(_GET_STATUS, new_callable=AsyncMock, return_value=mock_status):
            response = await client.get(STATUS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["completed"] is True
        assert data["phase"] == "completed"

    async def test_get_status_incomplete_user(self, client: AsyncClient):
        mock_status = _status(completed=False, phase="initial")
        with patch(_GET_STATUS, new_callable=AsyncMock, return_value=mock_status):
            response = await client.get(STATUS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["completed"] is False

    async def test_get_status_service_error(self, client: AsyncClient):
        with patch(
            _GET_STATUS,
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            response = await client.get(STATUS_URL)

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /onboarding/phase
# ---------------------------------------------------------------------------


class TestUpdateOnboardingPhase:
    """Tests for the update onboarding phase endpoint."""

    async def test_update_phase_success(self, client: AsyncClient):
        with (
            patch(_SET_PHASE, new_callable=AsyncMock, return_value=True),
            patch(
                _WEBSOCKET_MANAGER + ".broadcast_to_user",
                new_callable=AsyncMock,
            ),
        ):
            response = await client.post(PHASE_URL, json={"phase": "getting_started"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["phase"] == "getting_started"

    async def test_update_phase_user_not_found_returns_404(self, client: AsyncClient):
        with patch(_SET_PHASE, new_callable=AsyncMock, return_value=False):
            response = await client.post(PHASE_URL, json={"phase": "completed"})

        assert response.status_code == 404

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


# ---------------------------------------------------------------------------
# PATCH /onboarding/preferences
# ---------------------------------------------------------------------------


class TestUpdatePreferences:
    """Tests for the update preferences endpoint."""

    async def test_update_preferences_success(self, client: AsyncClient):
        with (
            patch(
                _UPDATE_PREFERENCES,
                new_callable=AsyncMock,
                return_value={"user_id": "507f1f77bcf86cd799439011"},
            ) as mock_update,
            patch("app.api.v1.endpoints.onboarding.schedule_account_sync") as mock_schedule_sync,
        ):
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
        mock_schedule_sync.assert_called_once_with(FAKE_USER_ID)
        assert mock_update.await_count == 1

    async def test_update_preferences_captures_settings_changed(self, client: AsyncClient):
        with (
            patch(
                _UPDATE_PREFERENCES,
                new_callable=AsyncMock,
                return_value={"user_id": "507f1f77bcf86cd799439011"},
            ),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            response = await client.patch(
                PREFERENCES_URL,
                json={"profession": "Engineer", "custom_instructions": "Be concise."},
            )

        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {
                "setting": "onboarding_preferences",
                "fields": ["custom_instructions", "profession"],
                "response_style": None,
                "has_custom_instructions": True,
            },
        )

    async def test_update_preferences_empty_body_allowed(self, client: AsyncClient):
        """Empty optional fields should be accepted."""
        with patch(
            _UPDATE_PREFERENCES,
            new_callable=AsyncMock,
            return_value={"user_id": "507f1f77bcf86cd799439011"},
        ):
            response = await client.patch(PREFERENCES_URL, json={})

        assert response.status_code == 200

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


# ---------------------------------------------------------------------------
# GET /onboarding/personalization
# ---------------------------------------------------------------------------


class TestGetPersonalization:
    """Tests for the get personalization data endpoint."""

    async def test_get_personalization_success(self, client: AsyncClient):
        user_doc = _make_user_doc()
        mock_composio = MagicMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=41),
            patch(_COMPOSIO_SERVICE, return_value=mock_composio),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["house"] == "Bluehaven"
        assert data["personality_phrase"] == "Curious Explorer"
        assert data["has_personalization"] is True

    async def test_get_personalization_user_not_found_returns_404(self, client: AsyncClient):
        with patch(_GET_USER, new_callable=AsyncMock, return_value=None):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 404

    async def test_get_personalization_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _GET_USER,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 500

    async def test_get_personalization_no_phase_defaults(self, client: AsyncClient):
        """User doc with empty onboarding should return default values."""
        user_doc = UserDocument(
            id="507f1f77bcf86cd799439011",
            name="New User",
            onboarding={},
            created_at=None,
        )
        mock_composio = MagicMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})
        with (
            patch(_GET_USER, new_callable=AsyncMock, return_value=user_doc),
            patch(_COUNT_BEFORE, new_callable=AsyncMock, return_value=0),
            patch(_COMPOSIO_SERVICE, return_value=mock_composio),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["has_personalization"] is False
        assert data["house"] == "Bluehaven"
