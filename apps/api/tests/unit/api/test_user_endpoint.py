"""Unit tests for user API endpoints.

Tests the user endpoints with mocked service layer to verify
routing, status codes, response bodies, auth, and validation.
"""

from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.models.user_models import (
    AuthenticatedUserResponse,
    OnboardingPreferences,
    OnboardingStatusResponse,
    UserDocument,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.onboarding.onboarding_service import get_user_onboarding_status

USER_BASE = "/api/v1/user"

FAKE_USER_UPDATE = {
    "user_id": "507f1f77bcf86cd799439011",
    "name": "Updated User",
    "email": "test@example.com",
    "picture": None,
}


# ---------------------------------------------------------------------------
# GET /user/me
# ---------------------------------------------------------------------------


class TestGetMe:
    """GET /api/v1/user/me"""

    @patch(
        "app.api.v1.endpoints.user.get_user_onboarding_status",
        new_callable=AsyncMock,
    )
    async def test_get_me_success(self, mock_onboarding: AsyncMock, client: AsyncClient):
        # Must be the real return type, not a dict: get_user_onboarding_status was
        # typed to return OnboardingStatusResponse while this mock still handed back
        # the pre-refactor dict, so the endpoint 500'd in production on every page
        # load while this test stayed green.
        mock_onboarding.return_value = OnboardingStatusResponse(
            completed=True,
            completed_at=None,
            phase=None,
            preferences=OnboardingPreferences(),
            first_message_conversation_id=None,
        )
        response = await client.get(f"{USER_BASE}/me")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "User retrieved successfully"
        assert data["user_id"] == "507f1f77bcf86cd799439011"
        assert data["onboarding"]["completed"] is True

    async def test_get_me_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(f"{USER_BASE}/me")
        assert response.status_code == 401

    def test_onboarding_field_type_tracks_the_service_return_type(self) -> None:
        # The 500 above was a *drift* bug: get_user_onboarding_status was retyped to
        # return OnboardingStatusResponse while this field stayed dict[str, Any].
        # test_get_me_success can't catch a repeat on its own — it asserts against a
        # hand-written mock, so correcting the mock is what makes it pass. This
        # compares the declared field against the real annotation, with no mock in
        # between, so retyping the service without updating the response fails here.
        service_returns = get_type_hints(get_user_onboarding_status)["return"]
        field_type = AuthenticatedUserResponse.model_fields["onboarding"].annotation
        assert field_type is service_returns, (
            f"GET /me declares onboarding as {field_type}, but "
            f"get_user_onboarding_status returns {service_returns}"
        )


# ---------------------------------------------------------------------------
# PATCH /user/me
# ---------------------------------------------------------------------------


class TestUpdateMe:
    """PATCH /api/v1/user/me"""

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_name(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = FAKE_USER_UPDATE
        with patch("app.api.v1.endpoints.user.capture_context_event") as mock_capture:
            response = await client.patch(
                f"{USER_BASE}/me",
                data={"name": "Updated User"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated User"
        mock_capture.assert_called_once_with(
            AnalyticsEvents.PROFILE_UPDATED,
            {"changed_field_count": 1, "has_picture_upload": False},
        )

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_with_picture(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = {
            **FAKE_USER_UPDATE,
            "picture": "https://img.example.com/a.png",
        }
        with patch("app.api.v1.endpoints.user.capture_context_event") as mock_capture:
            response = await client.patch(
                f"{USER_BASE}/me",
                data={"name": "Updated User"},
                files={
                    "picture": (
                        "avatar.png",
                        b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
                        "image/png",
                    )
                },
            )
        assert response.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.PROFILE_UPDATED,
            {"changed_field_count": 2, "has_picture_upload": True},
        )

    async def test_update_me_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.patch(f"{USER_BASE}/me", data={"name": "X"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /user/name
# ---------------------------------------------------------------------------


class TestUpdateUserName:
    """PATCH /api/v1/user/name"""

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_name_success(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = FAKE_USER_UPDATE
        with patch("app.api.v1.endpoints.user.capture_context_event") as mock_capture:
            response = await client.patch(
                f"{USER_BASE}/name",
                data={"name": "Updated User"},
            )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated User"
        mock_capture.assert_called_once_with(
            AnalyticsEvents.PROFILE_UPDATED, {"changed_field_count": 1}
        )

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_name_service_error(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.side_effect = Exception("db error")
        response = await client.patch(
            f"{USER_BASE}/name",
            data={"name": "X"},
        )
        assert response.status_code == 500

    async def test_update_name_missing_field(self, client: AsyncClient):
        response = await client.patch(f"{USER_BASE}/name")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /user/timezone
# ---------------------------------------------------------------------------


class TestUpdateTimezone:
    """PATCH /api/v1/user/timezone"""

    @patch("app.api.v1.endpoints.user.user_repository.update", new_callable=AsyncMock)
    async def test_update_timezone_success(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = UserDocument(timezone="America/New_York")
        with patch("app.api.v1.endpoints.user.capture_context_event") as mock_capture:
            response = await client.patch(
                f"{USER_BASE}/timezone",
                data={"timezone": "America/New_York"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["timezone"] == "America/New_York"
        mock_capture.assert_called_once_with(
            AnalyticsEvents.PROFILE_UPDATED, {"changed_field_count": 1}
        )

    @patch("app.api.v1.endpoints.user.user_repository.update", new_callable=AsyncMock)
    async def test_update_timezone_utc(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = UserDocument(timezone="UTC")
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "UTC"},
        )
        assert response.status_code == 200

    async def test_update_timezone_invalid(self, client: AsyncClient):
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "Invalid/Zone"},
        )
        assert response.status_code == 400

    @patch("app.api.v1.endpoints.user.user_repository.update", new_callable=AsyncMock)
    async def test_update_timezone_user_not_found(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = None
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "America/New_York"},
        )
        assert response.status_code == 404

    async def test_update_timezone_missing_field(self, client: AsyncClient):
        response = await client.patch(f"{USER_BASE}/timezone")
        assert response.status_code == 422

    @patch("app.api.v1.endpoints.user.user_repository.update", new_callable=AsyncMock)
    async def test_update_timezone_db_error(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.side_effect = Exception("db error")
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "America/New_York"},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /user/holo-card/{card_id}
# ---------------------------------------------------------------------------


class TestGetPublicHoloCard:
    """GET /api/v1/user/holo-card/{card_id}"""

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    async def test_holo_card_success(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = UserDocument(
            id="507f1f77bcf86cd799439011",
            name="Alice",
            onboarding={
                "house": "phoenix",
                "personality_phrase": "creative",
                "user_bio": "Hello",
                "account_number": 42,
                "member_since": "Jan 01, 2025",
            },
        )
        response = await client.get(f"{USER_BASE}/holo-card/507f1f77bcf86cd799439011")
        assert response.status_code == 200
        data = response.json()
        assert data["house"] == "phoenix"
        assert data["name"] == "Alice"

    async def test_holo_card_invalid_id(self, client: AsyncClient):
        response = await client.get(f"{USER_BASE}/holo-card/not-a-valid-id")
        assert response.status_code == 400

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    async def test_holo_card_not_found(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = None
        response = await client.get(f"{USER_BASE}/holo-card/507f1f77bcf86cd799439011")
        assert response.status_code == 404

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    async def test_holo_card_no_house(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = UserDocument(id="507f1f77bcf86cd799439011", onboarding={})
        response = await client.get(f"{USER_BASE}/holo-card/507f1f77bcf86cd799439011")
        assert response.status_code == 404

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    async def test_holo_card_db_error(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.side_effect = Exception("db error")
        response = await client.get(f"{USER_BASE}/holo-card/507f1f77bcf86cd799439011")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PATCH /user/holo-card/colors
# ---------------------------------------------------------------------------


class TestUpdateHoloCardColors:
    """PATCH /api/v1/user/holo-card/colors"""

    @patch("app.api.v1.endpoints.user.user_repository.set_holo_card_colors", new_callable=AsyncMock)
    async def test_update_colors_success(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.return_value = True
        with patch("app.api.v1.endpoints.user.capture_context_event") as mock_capture:
            response = await client.patch(
                f"{USER_BASE}/holo-card/colors",
                data={"overlay_color": "rgba(255,0,0,1)", "overlay_opacity": 50},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["overlay_opacity"] == 50
        mock_capture.assert_called_once_with(
            AnalyticsEvents.PROFILE_UPDATED, {"changed_field_count": 2}
        )

    @patch("app.api.v1.endpoints.user.user_repository.set_holo_card_colors", new_callable=AsyncMock)
    async def test_update_colors_user_not_found(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.return_value = False
        response = await client.patch(
            f"{USER_BASE}/holo-card/colors",
            data={"overlay_color": "rgba(0,0,0,1)", "overlay_opacity": 50},
        )
        assert response.status_code == 404

    async def test_update_colors_missing_fields(self, client: AsyncClient):
        response = await client.patch(f"{USER_BASE}/holo-card/colors")
        assert response.status_code == 422

    @patch("app.api.v1.endpoints.user.user_repository.set_holo_card_colors", new_callable=AsyncMock)
    async def test_update_colors_db_error(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.side_effect = Exception("db error")
        response = await client.patch(
            f"{USER_BASE}/holo-card/colors",
            data={"overlay_color": "rgba(0,0,0,1)", "overlay_opacity": 50},
        )
        assert response.status_code == 500

    async def test_update_colors_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.patch(
            f"{USER_BASE}/holo-card/colors",
            data={"overlay_color": "rgba(0,0,0,1)", "overlay_opacity": 50},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /user/logout
# ---------------------------------------------------------------------------


class TestLogout:
    """POST /api/v1/user/logout"""

    @patch("app.api.v1.endpoints.user.workos")
    async def test_logout_success(self, mock_workos: MagicMock, client: AsyncClient):
        session = MagicMock()
        session.get_logout_url.return_value = "https://auth.example.com/logout"
        mock_workos.user_management.load_sealed_session.return_value = session
        client.cookies.set("wos_session", "sealed_token")
        with patch("app.api.v1.endpoints.user.track_logout") as mock_track:
            response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 200
        data = response.json()
        assert "logout_url" in data
        mock_track.assert_called_once_with(user_id="507f1f77bcf86cd799439011")

    @patch("app.api.v1.endpoints.user.workos")
    @patch("app.api.v1.endpoints.user.track_logout", side_effect=RuntimeError("ph down"))
    async def test_logout_track_failure_is_logged_not_fatal(
        self, mock_track: MagicMock, mock_workos: MagicMock, client: AsyncClient
    ):
        """A PostHog tracking failure must not break the logout flow — it is
        logged and the redirect still happens."""
        session = MagicMock()
        session.get_logout_url.return_value = "https://auth.example.com/logout"
        mock_workos.user_management.load_sealed_session.return_value = session
        client.cookies.set("wos_session", "sealed_token")
        with patch("app.api.v1.endpoints.user.log") as mock_log:
            response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 200
        assert "logout_url" in response.json()
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs["error_type"] == "RuntimeError"
        assert mock_log.warning.call_args.kwargs["error"] == "ph down"

    async def test_logout_no_session_cookie(self, client: AsyncClient):
        response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 401

    @patch("app.api.v1.endpoints.user.workos")
    async def test_logout_invalid_session(self, mock_workos: MagicMock, client: AsyncClient):
        # The HTTPException(401) is inside a bare except that re-raises as 500
        mock_workos.user_management.load_sealed_session.return_value = None
        client.cookies.set("wos_session", "bad_token")
        response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 500

    @patch("app.api.v1.endpoints.user.workos")
    async def test_logout_exception(self, mock_workos: MagicMock, client: AsyncClient):
        mock_workos.user_management.load_sealed_session.side_effect = Exception("boom")
        client.cookies.set("wos_session", "sealed_token")
        response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 500
