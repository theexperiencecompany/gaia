"""Unit tests for user API endpoints.

Tests the user endpoints with mocked service layer to verify
routing, status codes, response bodies, auth, and validation.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.config.settings import settings
from app.models.user_models import (
    AuthenticatedUserResponse,
    OnboardingPreferences,
    OnboardingStatusResponse,
    UserDocument,
    UserUpdate,
)
from app.services.onboarding.onboarding_service import get_user_onboarding_status

USER_BASE = "/api/v1/user"

USER_ID = "507f1f77bcf86cd799439011"

FAKE_USER_UPDATE = {
    "user_id": USER_ID,
    "name": "Updated User",
    "email": "test@example.com",
    "picture": None,
}

_MAX_IMAGE_BYTES = 5 * 1024 * 1024


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


def _card_user_doc(**overrides) -> UserDocument:
    base = {
        "id": USER_ID,
        "name": "Alice",
        "onboarding": {
            "house": "phoenix",
            "personality_phrase": "creative",
            "user_bio": "Hello",
            "account_number": 42,
            "member_since": "Jan 01, 2025",
        },
    }
    base.update(overrides)
    return UserDocument.model_validate(base)


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
        assert data["user_id"] == USER_ID
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"
        assert data["auth_provider"] == "workos"
        assert data["timezone"] == "UTC"
        assert data["onboarding"]["completed"] is True
        mock_onboarding.assert_awaited_once_with(USER_ID)

    @patch(
        "app.api.v1.endpoints.user.get_user_onboarding_status",
        new_callable=AsyncMock,
    )
    async def test_get_me_omits_none_fields(self, mock_onboarding: AsyncMock, client: AsyncClient):
        """response_model_exclude_none: absent optional fields stay off the wire."""
        mock_onboarding.return_value = OnboardingStatusResponse(
            completed=False,
            completed_at=None,
            phase="initial",
            preferences=OnboardingPreferences(),
            first_message_conversation_id=None,
        )
        response = await client.get(f"{USER_BASE}/me")
        assert response.status_code == 200
        data = response.json()
        for key in ("impersonated", "bot_authenticated", "dev_bypass", "picture"):
            assert key not in data
        assert "completed_at" not in data["onboarding"]
        assert "first_message_conversation_id" not in data["onboarding"]
        assert data["onboarding"]["phase"] == "initial"

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
        response = await client.patch(
            f"{USER_BASE}/me",
            data={"name": "Updated User"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated User"
        assert data["user_id"] == USER_ID
        assert data["email"] == "test@example.com"
        assert data["picture"] is None
        mock_update.assert_awaited_once_with(
            user_id=USER_ID, name="Updated User", picture_data=None
        )

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_with_picture(self, mock_update: AsyncMock, client: AsyncClient):
        picture_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
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
                    picture_bytes,
                    "image/png",
                )
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["picture"] == "https://img.example.com/a.png"
        mock_update.assert_awaited_once_with(
            user_id=USER_ID, name="Updated User", picture_data=picture_bytes
        )

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_rejects_invalid_content_type(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        response = await client.patch(
            f"{USER_BASE}/me",
            data={"name": "Updated User"},
            files={"picture": ("evil.txt", b"not an image", "text/plain")},
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Invalid file type. Allowed types: image/jpeg, image/png, image/gif, image/webp"
        )
        mock_update.assert_not_awaited()

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_rejects_oversized_picture(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        response = await client.patch(
            f"{USER_BASE}/me",
            data={"name": "Updated User"},
            files={"picture": ("big.png", b"\x00" * (_MAX_IMAGE_BYTES + 1), "image/png")},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "File size too large. Maximum size is 5MB"
        mock_update.assert_not_awaited()

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_without_user_id_returns_400(
        self, mock_update: AsyncMock, client: AsyncClient, test_app
    ):
        with _override_current_user(test_app, {}):
            response = await client.patch(f"{USER_BASE}/me", data={"name": "X"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid user ID"
        mock_update.assert_not_awaited()

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_non_string_user_id_returns_400(
        self, mock_update: AsyncMock, client: AsyncClient, test_app
    ):
        """A truthy non-string user_id is still rejected."""
        with _override_current_user(test_app, {"user_id": 123}):
            response = await client.patch(f"{USER_BASE}/me", data={"name": "X"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid user ID"
        mock_update.assert_not_awaited()

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_empty_picture_is_ignored(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        """A zero-byte upload must be treated as 'no picture'."""
        mock_update.return_value = FAKE_USER_UPDATE
        response = await client.patch(
            f"{USER_BASE}/me",
            data={"name": "Updated User"},
            files={"picture": ("empty.png", b"", "image/png")},
        )
        assert response.status_code == 200
        mock_update.assert_awaited_once_with(
            user_id=USER_ID, name="Updated User", picture_data=None
        )

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_one_byte_picture_is_read(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        """The size check is `> 0`: a 1-byte file is still a real upload."""
        mock_update.return_value = {**FAKE_USER_UPDATE, "picture": "https://img.example.com/1.png"}
        response = await client.patch(
            f"{USER_BASE}/me",
            data={"name": "Updated User"},
            files={"picture": ("one.png", b"\x00", "image/png")},
        )
        assert response.status_code == 200
        mock_update.assert_awaited_once_with(
            user_id=USER_ID, name="Updated User", picture_data=b"\x00"
        )

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_me_exactly_5mb_picture_accepted(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        """The limit is 'greater than 5MB' — exactly 5MB passes."""
        mock_update.return_value = {**FAKE_USER_UPDATE, "picture": "https://img.example.com/5.png"}
        response = await client.patch(
            f"{USER_BASE}/me",
            data={"name": "Updated User"},
            files={"picture": ("big.png", b"\x00" * _MAX_IMAGE_BYTES, "image/png")},
        )
        assert response.status_code == 200
        mock_update.assert_awaited_once()

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
        response = await client.patch(
            f"{USER_BASE}/name",
            data={"name": "Updated User"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated User"
        mock_update.assert_awaited_once_with(user_id=USER_ID, name="Updated User")

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
        assert response.json()["detail"] == "Failed to update name"

    async def test_update_name_missing_field(self, client: AsyncClient):
        response = await client.patch(f"{USER_BASE}/name")
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.user.update_user_profile",
        new_callable=AsyncMock,
    )
    async def test_update_name_non_string_user_id_returns_400(
        self, mock_update: AsyncMock, client: AsyncClient, test_app
    ):
        with _override_current_user(test_app, {"user_id": 123}):
            response = await client.patch(f"{USER_BASE}/name", data={"name": "X"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid user ID"
        mock_update.assert_not_awaited()

    async def test_update_name_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.patch(f"{USER_BASE}/name", data={"name": "X"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /user/timezone
# ---------------------------------------------------------------------------


class TestUpdateTimezone:
    """PATCH /api/v1/user/timezone"""

    @patch("app.api.v1.endpoints.user.user_repository.update", new_callable=AsyncMock)
    async def test_update_timezone_success(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = UserDocument(timezone="America/New_York")
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "America/New_York"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Timezone updated successfully",
            "timezone": "America/New_York",
        }
        mock_update.assert_awaited_once_with(USER_ID, UserUpdate(timezone="America/New_York"))

    @patch("app.api.v1.endpoints.user.user_repository.update", new_callable=AsyncMock)
    async def test_update_timezone_strips_whitespace(
        self, mock_update: AsyncMock, client: AsyncClient
    ):
        mock_update.return_value = UserDocument(timezone="UTC")
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "  UTC  "},
        )
        assert response.status_code == 200
        assert response.json()["timezone"] == "UTC"
        mock_update.assert_awaited_once_with(USER_ID, UserUpdate(timezone="UTC"))

    @patch("app.api.v1.endpoints.user.user_repository.update", new_callable=AsyncMock)
    async def test_update_timezone_utc(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = UserDocument(timezone="UTC")
        response = await client.patch(
            f"{USER_BASE}/timezone",
            data={"timezone": "UTC"},
        )
        assert response.status_code == 200

    async def test_update_timezone_invalid(self, client: AsyncClient):
        with patch(
            "app.api.v1.endpoints.user.user_repository.update", new_callable=AsyncMock
        ) as mock_update:
            response = await client.patch(
                f"{USER_BASE}/timezone",
                data={"timezone": "Invalid/Zone"},
            )

        assert response.status_code == 400
        assert "Invalid timezone" in response.json()["detail"]
        mock_update.assert_not_awaited()

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
        assert response.json()["detail"] == "User not found"

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
        assert response.json()["detail"] == "Failed to update timezone"

    async def test_update_timezone_unauthed(self, unauthed_client: AsyncClient):
        response = await unauthed_client.patch(f"{USER_BASE}/timezone", data={"timezone": "UTC"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /user/holo-card/{card_id}
# ---------------------------------------------------------------------------


class TestGetPublicHoloCard:
    """GET /api/v1/user/holo-card/{card_id}"""

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.user.user_repository.count_created_before",
        new_callable=AsyncMock,
    )
    async def test_holo_card_success(
        self, mock_count: AsyncMock, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = _card_user_doc()
        response = await client.get(f"{USER_BASE}/holo-card/{USER_ID}")
        assert response.status_code == 200
        assert response.json() == {
            "house": "phoenix",
            "personality_phrase": "creative",
            "user_bio": "Hello",
            "account_number": 42,
            "member_since": "Jan 01, 2025",
            "name": "Alice",
            "overlay_color": "rgba(0,0,0,0)",
            "overlay_opacity": 40,
        }
        mock_get.assert_awaited_once_with(USER_ID)
        mock_count.assert_not_awaited()

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.user.user_repository.count_created_before",
        new_callable=AsyncMock,
    )
    async def test_holo_card_backfills_identity_from_created_at(
        self, mock_count: AsyncMock, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = _card_user_doc(
            created_at=datetime(2024, 1, 15, tzinfo=UTC),
            onboarding={"house": "phoenix", "user_bio": "Hello"},
        )
        mock_count.return_value = 7
        response = await client.get(f"{USER_BASE}/holo-card/{USER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["account_number"] == 8
        assert data["member_since"] == "Jan 15, 2024"
        mock_count.assert_awaited_once_with(datetime(2024, 1, 15, tzinfo=UTC))

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    async def test_holo_card_without_created_at_yields_account_one(
        self, mock_get: AsyncMock, client: AsyncClient
    ):
        mock_get.return_value = _card_user_doc(
            created_at=None,
            onboarding={"house": "phoenix"},
        )
        with patch("app.api.v1.endpoints.user.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 8, 10, tzinfo=UTC)
            response = await client.get(f"{USER_BASE}/holo-card/{USER_ID}")

        assert response.status_code == 200
        data = response.json()
        assert data["account_number"] == 1
        assert data["member_since"] == "Aug 10, 2026"

    async def test_holo_card_invalid_id(self, client: AsyncClient):
        with patch(
            "app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock
        ) as mock_get:
            response = await client.get(f"{USER_BASE}/holo-card/not-a-valid-id")

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid card ID"
        mock_get.assert_not_awaited()

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    async def test_holo_card_not_found(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = None
        response = await client.get(f"{USER_BASE}/holo-card/{USER_ID}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Card not found"

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    async def test_holo_card_no_house(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = UserDocument(id=USER_ID, onboarding={})
        response = await client.get(f"{USER_BASE}/holo-card/{USER_ID}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Card not found"

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    @patch(
        "app.api.v1.endpoints.user.user_repository.count_created_before",
        new_callable=AsyncMock,
    )
    async def test_holo_card_partial_stored_identity_still_backfills(
        self, mock_count: AsyncMock, mock_get: AsyncMock, client: AsyncClient
    ):
        """account_number without member_since must still derive both — the
        'or' join in the stored-identity check is load-bearing."""
        mock_get.return_value = _card_user_doc(
            created_at=datetime(2023, 6, 20, tzinfo=UTC),
            onboarding={"house": "phoenix", "account_number": 42},
        )
        mock_count.return_value = 9
        response = await client.get(f"{USER_BASE}/holo-card/{USER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["account_number"] == 10
        assert data["member_since"] == "Jun 20, 2023"
        mock_count.assert_awaited_once_with(datetime(2023, 6, 20, tzinfo=UTC))

    @patch("app.api.v1.endpoints.user.user_repository.get", new_callable=AsyncMock)
    async def test_holo_card_db_error(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.side_effect = Exception("db error")
        response = await client.get(f"{USER_BASE}/holo-card/{USER_ID}")
        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to fetch holo card data"


# ---------------------------------------------------------------------------
# PATCH /user/holo-card/colors
# ---------------------------------------------------------------------------


class TestUpdateHoloCardColors:
    """PATCH /api/v1/user/holo-card/colors"""

    @patch("app.api.v1.endpoints.user.user_repository.set_holo_card_colors", new_callable=AsyncMock)
    async def test_update_colors_success(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.return_value = True
        response = await client.patch(
            f"{USER_BASE}/holo-card/colors",
            data={"overlay_color": "rgba(255,0,0,1)", "overlay_opacity": 50},
        )
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "Holo card colors updated successfully",
            "overlay_color": "rgba(255,0,0,1)",
            "overlay_opacity": 50,
        }
        mock_set.assert_awaited_once_with(USER_ID, "rgba(255,0,0,1)", 50)

    @patch("app.api.v1.endpoints.user.user_repository.set_holo_card_colors", new_callable=AsyncMock)
    async def test_update_colors_user_not_found(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.return_value = False
        response = await client.patch(
            f"{USER_BASE}/holo-card/colors",
            data={"overlay_color": "rgba(0,0,0,1)", "overlay_opacity": 50},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"

    async def test_update_colors_opacity_out_of_range(self, client: AsyncClient):
        for opacity in (-1, 101):
            response = await client.patch(
                f"{USER_BASE}/holo-card/colors",
                data={"overlay_color": "rgba(0,0,0,1)", "overlay_opacity": opacity},
            )
            assert response.status_code == 400
            assert response.json()["detail"] == "Opacity must be between 0 and 100"

    @patch("app.api.v1.endpoints.user.user_repository.set_holo_card_colors", new_callable=AsyncMock)
    async def test_update_colors_opacity_boundaries_accepted(
        self, mock_set: AsyncMock, client: AsyncClient
    ):
        mock_set.return_value = True
        for opacity in (0, 100):
            response = await client.patch(
                f"{USER_BASE}/holo-card/colors",
                data={"overlay_color": "rgba(0,0,0,1)", "overlay_opacity": opacity},
            )
            assert response.status_code == 200
            assert response.json()["overlay_opacity"] == opacity

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
        assert response.json()["detail"] == "Failed to update holo card colors"

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

    @patch("app.api.v1.endpoints.user.track_logout")
    @patch("app.api.v1.endpoints.user.workos")
    async def test_logout_success(
        self, mock_workos: MagicMock, mock_track: MagicMock, client: AsyncClient
    ):
        session = MagicMock()
        session.get_logout_url.return_value = "https://auth.example.com/logout"
        mock_workos.user_management.load_sealed_session.return_value = session
        client.cookies.set("wos_session", "sealed_token")
        response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 200
        assert response.json() == {"logout_url": "https://auth.example.com/logout"}
        mock_workos.user_management.load_sealed_session.assert_called_once_with(
            sealed_session="sealed_token",
            cookie_password=settings.WORKOS_COOKIE_PASSWORD,
        )
        session.get_logout_url.assert_called_once_with()
        mock_track.assert_called_once_with(user_id=USER_ID, email="test@example.com")
        set_cookie = response.headers.get("set-cookie", "").lower()
        assert "wos_session=" in set_cookie
        assert "httponly" in set_cookie
        assert "path=/" in set_cookie

    @patch("app.api.v1.endpoints.user.track_logout")
    @patch("app.api.v1.endpoints.user.workos")
    async def test_logout_analytics_failure_tolerated(
        self, mock_workos: MagicMock, mock_track: MagicMock, client: AsyncClient
    ):
        """A failing analytics call must not block the logout."""
        session = MagicMock()
        session.get_logout_url.return_value = "https://auth.example.com/logout"
        mock_workos.user_management.load_sealed_session.return_value = session
        mock_track.side_effect = RuntimeError("analytics down")
        client.cookies.set("wos_session", "sealed_token")
        response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 200
        assert response.json()["logout_url"] == "https://auth.example.com/logout"

    async def test_logout_no_session_cookie(self, client: AsyncClient):
        response = await client.post(f"{USER_BASE}/logout")
        assert response.status_code == 401
        assert response.json()["detail"] == "No active session"

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
        assert response.json()["detail"] == "Logout failed"
