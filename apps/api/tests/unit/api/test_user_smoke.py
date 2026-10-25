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

from app.models.user_models import (
    UserDocument,
)
from tests.conftest import FAKE_USER


class TestGetMe:
    """GET /api/v1/user/me."""

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get("/api/v1/user/me")
        assert resp.status_code == 401


class TestUpdateName:
    """PATCH /api/v1/user/name."""

    async def test_update_name_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.patch(
            "/api/v1/user/name",
            data={"name": "Hacker"},
        )
        assert resp.status_code == 401


class TestUpdateTimezone:
    """PATCH /api/v1/user/timezone."""

    async def test_valid_timezone(self, client: AsyncClient):
        updated = UserDocument.model_validate(
            {
                "id": FAKE_USER.user_id,
                "email": FAKE_USER.email,
                "timezone": "America/New_York",
            }
        )
        with patch("app.api.v1.endpoints.user.user_repository") as mock_repo:
            mock_repo.update = AsyncMock(return_value=updated)
            resp = await client.patch(
                "/api/v1/user/timezone",
                data={"timezone": "America/New_York"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["timezone"] == "America/New_York"
        # The write must go through the users repository, scoped to the caller.
        mock_repo.update.assert_awaited_once()
        user_id, update = mock_repo.update.await_args.args
        assert user_id == FAKE_USER.user_id
        assert update.timezone == "America/New_York"

    async def test_unknown_user_returns_404(self, client: AsyncClient):
        with patch("app.api.v1.endpoints.user.user_repository") as mock_repo:
            mock_repo.update = AsyncMock(return_value=None)
            resp = await client.patch(
                "/api/v1/user/timezone",
                data={"timezone": "America/New_York"},
            )

        assert resp.status_code == 404

    async def test_invalid_timezone(self, client: AsyncClient):
        resp = await client.patch(
            "/api/v1/user/timezone",
            data={"timezone": "Not/A/Timezone"},
        )
        assert resp.status_code == 400
        assert "Invalid timezone" in resp.json()["message"]


class TestLogout:
    """POST /api/v1/user/logout."""

    async def test_logout_without_session_cookie(self, client: AsyncClient):
        resp = await client.post("/api/v1/user/logout")
        assert resp.status_code == 401
        assert "No active session" in resp.json()["message"]
