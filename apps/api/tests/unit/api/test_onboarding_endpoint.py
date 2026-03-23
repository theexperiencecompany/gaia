"""Unit tests for the onboarding API endpoints.

Tests cover:
- POST /api/v1/onboarding           (complete onboarding)
- GET  /api/v1/onboarding/status    (get onboarding status)
- POST /api/v1/onboarding/phase     (update onboarding phase)
- PATCH /api/v1/onboarding/preferences (update preferences)
- GET  /api/v1/onboarding/personalization (get personalization data)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

BASE_URL = "/api/v1/onboarding"
STATUS_URL = f"{BASE_URL}/status"
PHASE_URL = f"{BASE_URL}/phase"
PREFERENCES_URL = f"{BASE_URL}/preferences"
PERSONALIZATION_URL = f"{BASE_URL}/personalization"

# Patch targets
_COMPLETE_ONBOARDING = "app.api.v1.endpoints.onboarding.complete_onboarding"
_GET_STATUS = "app.api.v1.endpoints.onboarding.get_user_onboarding_status"
_USERS_COLLECTION = "app.api.v1.endpoints.onboarding.users_collection"
_WORKFLOWS_COLLECTION = "app.api.v1.endpoints.onboarding.workflows_collection"
_UPDATE_PREFERENCES = "app.api.v1.endpoints.onboarding.update_onboarding_preferences"
_COMPOSIO_SERVICE = "app.api.v1.endpoints.onboarding.get_composio_service"
_WEBSOCKET_MANAGER = "app.api.v1.endpoints.onboarding.websocket_manager"
_QUEUE_PERSONALIZATION = "app.api.v1.endpoints.onboarding.queue_personalization"


def _make_onboarding_request(**overrides) -> dict:
    base = {
        "name": "Test User",
        "profession": "Developer",
        "timezone": "UTC",
    }
    base.update(overrides)
    return base


def _make_user_doc(**overrides) -> dict:
    from bson import ObjectId

    base = {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
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
    return base


# ---------------------------------------------------------------------------
# POST /onboarding (complete onboarding)
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
                _USERS_COLLECTION + ".find_one",
                new_callable=AsyncMock,
                return_value={"email_memory_processed": False},
            ),
            patch(_QUEUE_PERSONALIZATION, new_callable=AsyncMock),
        ):
            response = await client.post(BASE_URL, json=_make_onboarding_request())

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Onboarding completed successfully"

    async def test_complete_onboarding_missing_name_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            BASE_URL,
            json={"profession": "Developer"},
        )
        assert response.status_code == 422

    async def test_complete_onboarding_missing_profession_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            BASE_URL,
            json={"name": "Test User"},
        )
        assert response.status_code == 422

    async def test_complete_onboarding_empty_name_returns_422(
        self, client: AsyncClient
    ):
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

    async def test_complete_onboarding_service_error_returns_500(
        self, client: AsyncClient
    ):
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


@pytest.mark.unit
class TestGetOnboardingStatus:
    """Tests for the get onboarding status endpoint."""

    async def test_get_status_returns_200(self, client: AsyncClient):
        mock_status = {"is_complete": True, "phase": "completed"}
        with patch(_GET_STATUS, new_callable=AsyncMock, return_value=mock_status):
            response = await client.get(STATUS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["is_complete"] is True

    async def test_get_status_incomplete_user(self, client: AsyncClient):
        mock_status = {"is_complete": False, "phase": "initial"}
        with patch(_GET_STATUS, new_callable=AsyncMock, return_value=mock_status):
            response = await client.get(STATUS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["is_complete"] is False

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


@pytest.mark.unit
class TestUpdateOnboardingPhase:
    """Tests for the update onboarding phase endpoint."""

    async def test_update_phase_success(self, client: AsyncClient):
        mock_result = MagicMock(modified_count=1)
        with (
            patch(
                _USERS_COLLECTION + ".update_one",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
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
        mock_result = MagicMock(modified_count=0)
        with patch(
            _USERS_COLLECTION + ".update_one",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
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
            _USERS_COLLECTION + ".update_one",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.post(PHASE_URL, json={"phase": "completed"})

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PATCH /onboarding/preferences
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdatePreferences:
    """Tests for the update preferences endpoint."""

    async def test_update_preferences_success(self, client: AsyncClient):
        with patch(
            _UPDATE_PREFERENCES,
            new_callable=AsyncMock,
            return_value={"user_id": "507f1f77bcf86cd799439011"},
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

    async def test_update_preferences_service_error_returns_500(
        self, client: AsyncClient
    ):
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


@pytest.mark.unit
class TestGetPersonalization:
    """Tests for the get personalization data endpoint."""

    async def test_get_personalization_success(self, client: AsyncClient):
        user_doc = _make_user_doc()
        mock_composio = MagicMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})
        with (
            patch(
                _USERS_COLLECTION + ".find_one",
                new_callable=AsyncMock,
                return_value=user_doc,
            ),
            patch(
                _USERS_COLLECTION + ".count_documents",
                new_callable=AsyncMock,
                return_value=41,
            ),
            patch(_COMPOSIO_SERVICE, return_value=mock_composio),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["house"] == "Bluehaven"
        assert data["personality_phrase"] == "Curious Explorer"
        assert data["has_personalization"] is True

    async def test_get_personalization_user_not_found_returns_404(
        self, client: AsyncClient
    ):
        with patch(
            _USERS_COLLECTION + ".find_one",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 404

    async def test_get_personalization_service_error_returns_500(
        self, client: AsyncClient
    ):
        with patch(
            _USERS_COLLECTION + ".find_one",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 500

    async def test_get_personalization_no_phase_defaults(self, client: AsyncClient):
        """User doc with empty onboarding should return default values."""
        from bson import ObjectId

        user_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "name": "New User",
            "onboarding": {},
            "created_at": None,
        }
        mock_composio = MagicMock()
        mock_composio.check_connection_status = AsyncMock(return_value={"gmail": False})
        with (
            patch(
                _USERS_COLLECTION + ".find_one",
                new_callable=AsyncMock,
                return_value=user_doc,
            ),
            patch(
                _USERS_COLLECTION + ".count_documents",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(_COMPOSIO_SERVICE, return_value=mock_composio),
        ):
            response = await client.get(PERSONALIZATION_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["has_personalization"] is False
        assert data["house"] == "Bluehaven"
