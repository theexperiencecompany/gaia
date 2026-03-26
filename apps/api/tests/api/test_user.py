"""
Tests for user endpoints (/api/v1/user/*).

Covers:
- GET /me — retrieve authenticated user
- PATCH /me — update profile (name + picture)
- PATCH /name — update name only
- PATCH /timezone — update timezone
- POST /logout — logout (cookie-based)
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from tests.conftest import FAKE_USER


class TestGetMe:
    """GET /api/v1/user/me"""

    async def test_returns_current_user(self, client: AsyncClient):
        with patch(
            "app.api.v1.endpoints.user.get_user_onboarding_status",
            new_callable=AsyncMock,
            return_value={"completed": True, "phase": "done"},
        ):
            resp = await client.get("/api/v1/user/me")

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == FAKE_USER["user_id"]
        assert body["email"] == FAKE_USER["email"]
        assert "onboarding" in body

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get("/api/v1/user/me")
        assert resp.status_code == 401


class TestUpdateName:
    """PATCH /api/v1/user/name"""

    async def test_update_name_success(self, client: AsyncClient):
        mock_result = {**FAKE_USER, "name": "New Name"}
        with patch(
            "app.api.v1.endpoints.user.update_user_profile",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.patch(
                "/api/v1/user/name",
                data={"name": "New Name"},
            )

        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_update_name_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.patch(
            "/api/v1/user/name",
            data={"name": "Hacker"},
        )
        assert resp.status_code == 401


class TestUpdateTimezone:
    """PATCH /api/v1/user/timezone"""

    async def test_valid_timezone(self, client: AsyncClient):
        mock_result = AsyncMock(matched_count=1)
        with patch("app.api.v1.endpoints.user.users_collection") as mock_col:
            mock_col.update_one = AsyncMock(return_value=mock_result)
            resp = await client.patch(
                "/api/v1/user/timezone",
                data={"timezone": "America/New_York"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["timezone"] == "America/New_York"

    async def test_invalid_timezone(self, client: AsyncClient):
        resp = await client.patch(
            "/api/v1/user/timezone",
            data={"timezone": "Not/A/Timezone"},
        )
        assert resp.status_code == 400
        assert "Invalid timezone" in resp.json()["detail"]


class TestLogout:
    """POST /api/v1/user/logout"""

    async def test_logout_without_session_cookie(self, client: AsyncClient):
        resp = await client.post("/api/v1/user/logout")
        assert resp.status_code == 401
        assert "No active session" in resp.json()["detail"]
