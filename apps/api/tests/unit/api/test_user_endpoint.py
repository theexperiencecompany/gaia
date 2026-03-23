"""Unit tests for user API endpoints.

Tests the user endpoints with mocked service layer to verify
routing, status codes, response bodies, auth, and validation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

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


@pytest.mark.unit
class TestGetMe:
    """GET /api/v1/user/me"""

    @patch(
        "app.api.v1.endpoints.user.get_user_onboarding_status",
        new_callable=AsyncMock,
    )
    async def test_get_me_success(
        self, mock_onboarding: AsyncMock, client: AsyncClient
    ):
        mock_onboarding.return_value = {"completed": True}
        response = await client.get(f"{USER_BASE}/me")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "User retrieved successfully"
        assert data["user_id"] == "507f1f77bcf86cd799439011"
        assert data["onboarding"]["completed"] is True

    async def test_get_me_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.get(f"{USER_BASE}/me")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /user/me
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateMe:
    """PATCH /api/v1/user/me"""

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_name(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = FAKE_USER_UPDATE
        response = await client.patch(
            f"{USER_BASE}/me",
            data={"name": "Updated User"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated User"

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_with_picture(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = {
            **FAKE_USER_UPDATE,
            "picture": "https://img.example.com/a.png",
        }
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

    async def test_update_me_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.patch(f"{USER_BASE}/me", data={"name": "X"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /user/name
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateUserName:
    """PATCH /api/v1/user/name"""

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_name_success(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = FAKE_USER_UPDATE
        response = await client.patch(
            f"{USER_BASE}/name",
            data={"name": "Updated User"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated User"

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_name_service_error(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
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


@pytest.mark.unit
class TestUpdateTimezone:
    """PATCH /api/v1/user/timezone"""

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_update_timezone_success(
        self, mock_users: MagicMock, client: AsyncClient
    ):
        result = MagicMock()
        result.matched_count = 1
        mock_users.update_one = AsyncMock(return_value=result)
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "America/New_York"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["timezone"] == "America/New_York"

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_update_timezone_utc(
        self, mock_users: MagicMock, client: AsyncClient
    ):
        result = MagicMock()
        result.matched_count = 1
        mock_users.update_one = AsyncMock(return_value=result)
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

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_update_timezone_user_not_found(
        self, mock_users: MagicMock, client: AsyncClient
    ):
        result = MagicMock()
        result.matched_count = 0
        mock_users.update_one = AsyncMock(return_value=result)
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "America/New_York"},
        )
        assert response.status_code == 404

    async def test_update_timezone_missing_field(self, client: AsyncClient):
        response = await client.patch(f"{USER_BASE}/timezone")
        assert response.status_code == 422

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_update_timezone_db_error(
        self, mock_users: MagicMock, client: AsyncClient
    ):
        mock_users.update_one = AsyncMock(side_effect=Exception("db error"))
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "America/New_York"},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /user/holo-card/{card_id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPublicHoloCard:
    """GET /api/v1/user/holo-card/{card_id}"""

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_holo_card_success(self, mock_users: MagicMock, client: AsyncClient):
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "name": "Alice",
                "onboarding": {
                    "house": "phoenix",
                    "personality_phrase": "creative",
                    "user_bio": "Hello",
                    "account_number": 42,
                    "member_since": "Jan 01, 2025",
                },
            }
        )
        response = await client.get(f"{USER_BASE}/holo-card/507f1f77bcf86cd799439011")
        assert response.status_code == 200
        data = response.json()
        assert data["house"] == "phoenix"
        assert data["name"] == "Alice"

    async def test_holo_card_invalid_id(self, client: AsyncClient):
        response = await client.get(f"{USER_BASE}/holo-card/not-a-valid-id")
        assert response.status_code == 400

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_holo_card_not_found(
        self, mock_users: MagicMock, client: AsyncClient
    ):
        mock_users.find_one = AsyncMock(return_value=None)
        response = await client.get(f"{USER_BASE}/holo-card/507f1f77bcf86cd799439011")
        assert response.status_code == 404

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_holo_card_no_house(self, mock_users: MagicMock, client: AsyncClient):
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": "507f1f77bcf86cd799439011",
                "onboarding": {},
            }
        )
        response = await client.get(f"{USER_BASE}/holo-card/507f1f77bcf86cd799439011")
        assert response.status_code == 404

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_holo_card_db_error(self, mock_users: MagicMock, client: AsyncClient):
        mock_users.find_one = AsyncMock(side_effect=Exception("db error"))
        response = await client.get(f"{USER_BASE}/holo-card/507f1f77bcf86cd799439011")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PATCH /user/holo-card/colors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateHoloCardColors:
    """PATCH /api/v1/user/holo-card/colors"""

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_update_colors_success(
        self, mock_users: MagicMock, client: AsyncClient
    ):
        result = MagicMock()
        result.matched_count = 1
        mock_users.update_one = AsyncMock(return_value=result)
        response = await client.patch(
            f"{USER_BASE}/holo-card/colors",
            data={"overlay_color": "rgba(255,0,0,1)", "overlay_opacity": 50},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["overlay_opacity"] == 50

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_update_colors_user_not_found(
        self, mock_users: MagicMock, client: AsyncClient
    ):
        result = MagicMock()
        result.matched_count = 0
        mock_users.update_one = AsyncMock(return_value=result)
        response = await client.patch(
            f"{USER_BASE}/holo-card/colors",
            data={"overlay_color": "rgba(0,0,0,1)", "overlay_opacity": 50},
        )
        assert response.status_code == 404

    async def test_update_colors_missing_fields(self, client: AsyncClient):
        response = await client.patch(f"{USER_BASE}/holo-card/colors")
        assert response.status_code == 422

    @patch("app.api.v1.endpoints.user.users_collection")
    async def test_update_colors_db_error(
        self, mock_users: MagicMock, client: AsyncClient
    ):
        mock_users.update_one = AsyncMock(side_effect=Exception("db error"))
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


@pytest.mark.unit
class TestLogout:
    """POST /api/v1/user/logout"""

    @patch("app.api.v1.endpoints.user.workos")
    async def test_logout_success(self, mock_workos: MagicMock, client: AsyncClient):
        session = MagicMock()
        session.get_logout_url.return_value = "https://auth.example.com/logout"
        mock_workos.user_management.load_sealed_session.return_value = session
        response = await client.post(
            f"{USER_BASE}/logout",
            cookies={"wos_session": "sealed_token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "logout_url" in data

    async def test_logout_no_session_cookie(self, client: AsyncClient):
        response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 401

    @patch("app.api.v1.endpoints.user.workos")
    async def test_logout_invalid_session(
        self, mock_workos: MagicMock, client: AsyncClient
    ):
        # The HTTPException(401) is inside a bare except that re-raises as 500
        mock_workos.user_management.load_sealed_session.return_value = None
        response = await client.post(
            f"{USER_BASE}/logout",
            cookies={"wos_session": "bad_token"},
        )
        assert response.status_code == 500

    @patch("app.api.v1.endpoints.user.workos")
    async def test_logout_exception(self, mock_workos: MagicMock, client: AsyncClient):
        mock_workos.user_management.load_sealed_session.side_effect = Exception("boom")
        response = await client.post(
            f"{USER_BASE}/logout",
            cookies={"wos_session": "sealed_token"},
        )
        assert response.status_code == 500
