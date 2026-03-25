"""Unit tests for OAuth utility functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.utils.oauth_utils import (
    build_google_oauth_url,
    get_tokens_by_user_id,
    upload_user_picture,
)


# ---------------------------------------------------------------------------
# build_google_oauth_url
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildGoogleOAuthUrl:
    """Tests for building Google OAuth authorization URLs."""

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_basic_url_structure(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.GOOGLE_CLIENT_ID = "test_client_id"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"
        mock_token_repo.get_token = AsyncMock(return_value=None)

        url = await build_google_oauth_url(
            user_email="user@example.com",
            state_token="state_123",
            integration_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )

        assert url.startswith("https://accounts.google.com/o/oauth2/auth?")
        assert "client_id=test_client_id" in url
        assert "redirect_uri=http" in url
        assert "state=state_123" in url
        assert "login_hint=user%40example.com" in url

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_includes_base_scopes(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.GOOGLE_CLIENT_ID = "cid"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"
        mock_token_repo.get_token = AsyncMock(return_value=None)

        url = await build_google_oauth_url(
            user_email="u@e.com",
            state_token="s",
            integration_scopes=[],
        )

        # Base scopes: openid, profile, email
        assert "openid" in url
        assert "profile" in url
        assert "email" in url

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_includes_integration_scopes(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.GOOGLE_CLIENT_ID = "cid"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"
        mock_token_repo.get_token = AsyncMock(return_value=None)

        custom_scope = "https://www.googleapis.com/auth/calendar"
        url = await build_google_oauth_url(
            user_email="u@e.com",
            state_token="s",
            integration_scopes=[custom_scope],
        )

        # URL-encoded scope
        assert "googleapis.com" in url

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_merges_existing_scopes_when_user_id_provided(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.GOOGLE_CLIENT_ID = "cid"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"

        mock_token = MagicMock()
        mock_token.get.return_value = "existing_scope_1 existing_scope_2"
        mock_token_repo.get_token = AsyncMock(return_value=mock_token)

        url = await build_google_oauth_url(
            user_email="u@e.com",
            state_token="s",
            integration_scopes=["new_scope"],
            user_id="user_123",
        )

        assert "existing_scope_1" in url
        assert "existing_scope_2" in url
        assert "new_scope" in url

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_deduplicates_scopes(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.GOOGLE_CLIENT_ID = "cid"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"

        mock_token = MagicMock()
        mock_token.get.return_value = "openid email"
        mock_token_repo.get_token = AsyncMock(return_value=mock_token)

        url = await build_google_oauth_url(
            user_email="u@e.com",
            state_token="s",
            integration_scopes=["openid"],
            user_id="user_123",
        )

        # "openid" should appear only once in the scope parameter
        scope_param = [p for p in url.split("&") if p.startswith("scope=")]
        assert len(scope_param) == 1
        scope_value = scope_param[0].replace("scope=", "")
        scopes = scope_value.replace("+", " ").split()
        assert scopes.count("openid") == 1

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_no_user_id_skips_existing_scope_lookup(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.GOOGLE_CLIENT_ID = "cid"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"

        url = await build_google_oauth_url(
            user_email="u@e.com",
            state_token="s",
            integration_scopes=["new_scope"],
            user_id=None,
        )

        mock_token_repo.get_token.assert_not_called()
        assert "new_scope" in url

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_token_lookup_failure_still_produces_url(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.GOOGLE_CLIENT_ID = "cid"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"
        mock_token_repo.get_token = AsyncMock(side_effect=Exception("DB down"))

        url = await build_google_oauth_url(
            user_email="u@e.com",
            state_token="s",
            integration_scopes=["scope_1"],
            user_id="user_123",
        )

        assert url.startswith("https://accounts.google.com/o/oauth2/auth?")
        assert "scope_1" in url

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_token_with_none_scope_field(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        """When token exists but scope is None, .split() on '' produces ['']."""
        mock_settings.GOOGLE_CLIENT_ID = "cid"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"

        mock_token = MagicMock()
        mock_token.get.return_value = None  # scope is None
        mock_token_repo.get_token = AsyncMock(return_value=mock_token)

        url = await build_google_oauth_url(
            user_email="u@e.com",
            state_token="s",
            integration_scopes=["new_scope"],
            user_id="user_123",
        )

        # Should still produce a valid URL despite None scope
        assert url.startswith("https://accounts.google.com/o/oauth2/auth?")

    @patch("app.utils.oauth_utils.settings")
    @patch("app.utils.oauth_utils.token_repository")
    async def test_includes_required_oauth_params(
        self, mock_token_repo: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.GOOGLE_CLIENT_ID = "cid"
        mock_settings.GOOGLE_CALLBACK_URL = "http://localhost/callback"
        mock_token_repo.get_token = AsyncMock(return_value=None)

        url = await build_google_oauth_url(
            user_email="u@e.com",
            state_token="state_val",
            integration_scopes=[],
        )

        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "include_granted_scopes=true" in url


# ---------------------------------------------------------------------------
# upload_user_picture
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadUserPicture:
    """Tests for uploading user profile pictures to Cloudinary."""

    @patch("app.utils.oauth_utils.cloudinary.uploader.upload")
    async def test_success_returns_secure_url(self, mock_upload: MagicMock) -> None:
        mock_upload.return_value = {"secure_url": "https://cdn.example.com/img.png"}

        result = await upload_user_picture(b"fake_image_data", "user_123_pic")
        assert result == "https://cdn.example.com/img.png"

    @patch("app.utils.oauth_utils.cloudinary.uploader.upload")
    async def test_passes_correct_params_to_cloudinary(
        self, mock_upload: MagicMock
    ) -> None:
        mock_upload.return_value = {"secure_url": "https://cdn.example.com/img.png"}

        await upload_user_picture(b"data", "my_public_id")

        call_kwargs = mock_upload.call_args
        assert call_kwargs.kwargs["resource_type"] == "image"
        assert call_kwargs.kwargs["public_id"] == "my_public_id"
        assert call_kwargs.kwargs["overwrite"] is True

    @patch("app.utils.oauth_utils.cloudinary.uploader.upload")
    async def test_raises_500_when_secure_url_missing(
        self, mock_upload: MagicMock
    ) -> None:
        # The inner HTTPException is caught by the outer except block,
        # which re-raises as "Image upload failed".
        mock_upload.return_value = {"public_id": "abc"}  # no secure_url

        with pytest.raises(HTTPException) as exc_info:
            await upload_user_picture(b"data", "pid")
        assert exc_info.value.status_code == 500
        assert "Image upload failed" in exc_info.value.detail

    @patch("app.utils.oauth_utils.cloudinary.uploader.upload")
    async def test_raises_500_when_secure_url_is_none(
        self, mock_upload: MagicMock
    ) -> None:
        mock_upload.return_value = {"secure_url": None}

        with pytest.raises(HTTPException) as exc_info:
            await upload_user_picture(b"data", "pid")
        assert exc_info.value.status_code == 500

    @patch("app.utils.oauth_utils.cloudinary.uploader.upload")
    async def test_raises_500_on_upload_exception(self, mock_upload: MagicMock) -> None:
        mock_upload.side_effect = Exception("Cloudinary timeout")

        with pytest.raises(HTTPException) as exc_info:
            await upload_user_picture(b"data", "pid")
        assert exc_info.value.status_code == 500
        assert "Image upload failed" in exc_info.value.detail

    @patch("app.utils.oauth_utils.cloudinary.uploader.upload")
    async def test_raises_500_on_empty_response(self, mock_upload: MagicMock) -> None:
        mock_upload.return_value = {}

        with pytest.raises(HTTPException) as exc_info:
            await upload_user_picture(b"data", "pid")
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get_tokens_by_user_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetTokensByUserId:
    """Tests for retrieving and refreshing Google OAuth tokens."""

    @patch("app.utils.oauth_utils.token_repository")
    async def test_returns_valid_tokens(self, mock_token_repo: MagicMock) -> None:
        mock_token = MagicMock()
        mock_token.get.side_effect = lambda key, default="": {
            "access_token": "access_tok",
            "refresh_token": "refresh_tok",
        }.get(key, default)
        mock_token.is_expired.return_value = False
        mock_token_repo.get_token = AsyncMock(return_value=mock_token)

        access, refresh, success = await get_tokens_by_user_id("user_1")
        assert access == "access_tok"
        assert refresh == "refresh_tok"
        assert success is True

    @patch("app.utils.oauth_utils.token_repository")
    async def test_returns_empty_when_no_token(
        self, mock_token_repo: MagicMock
    ) -> None:
        mock_token_repo.get_token = AsyncMock(return_value=None)

        access, refresh, success = await get_tokens_by_user_id("user_1")
        assert access == ""
        assert refresh == ""
        assert success is False

    @patch("app.utils.oauth_utils.token_repository")
    async def test_returns_empty_when_no_refresh_token(
        self, mock_token_repo: MagicMock
    ) -> None:
        mock_token = MagicMock()
        mock_token.get.side_effect = lambda key, default="": {
            "access_token": "access_tok",
            "refresh_token": "",
        }.get(key, default)
        mock_token_repo.get_token = AsyncMock(return_value=mock_token)

        access, refresh, success = await get_tokens_by_user_id("user_1")
        assert access == ""
        assert refresh == ""
        assert success is False

    @patch("app.utils.oauth_utils.token_repository")
    async def test_refreshes_expired_token(self, mock_token_repo: MagicMock) -> None:
        mock_token = MagicMock()
        mock_token.get.side_effect = lambda key, default="": {
            "access_token": "old_access",
            "refresh_token": "refresh_tok",
        }.get(key, default)
        mock_token.is_expired.return_value = True
        mock_token_repo.get_token = AsyncMock(return_value=mock_token)

        refreshed_token = MagicMock()
        refreshed_token.get.side_effect = lambda key, default="": {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
        }.get(key, default)
        mock_token_repo.refresh_token = AsyncMock(return_value=refreshed_token)

        access, refresh, success = await get_tokens_by_user_id("user_1")
        assert access == "new_access"
        assert refresh == "new_refresh"
        assert success is True
        mock_token_repo.refresh_token.assert_awaited_once_with("user_1", "google")

    @patch("app.utils.oauth_utils.token_repository")
    async def test_refresh_failure_returns_partial(
        self, mock_token_repo: MagicMock
    ) -> None:
        mock_token = MagicMock()
        mock_token.get.side_effect = lambda key, default="": {
            "access_token": "old_access",
            "refresh_token": "refresh_tok",
        }.get(key, default)
        mock_token.is_expired.return_value = True
        mock_token_repo.get_token = AsyncMock(return_value=mock_token)
        mock_token_repo.refresh_token = AsyncMock(return_value=None)

        access, refresh, success = await get_tokens_by_user_id("user_1")
        assert access == ""
        assert refresh == "refresh_tok"
        assert success is False

    @patch("app.utils.oauth_utils.token_repository")
    async def test_exception_returns_empty(self, mock_token_repo: MagicMock) -> None:
        mock_token_repo.get_token = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        access, refresh, success = await get_tokens_by_user_id("user_1")
        assert access == ""
        assert refresh == ""
        assert success is False

    @patch("app.utils.oauth_utils.token_repository")
    async def test_calls_get_token_with_google_provider(
        self, mock_token_repo: MagicMock
    ) -> None:
        mock_token_repo.get_token = AsyncMock(return_value=None)

        await get_tokens_by_user_id("user_42")

        mock_token_repo.get_token.assert_awaited_once_with("user_42", "google")

    @patch("app.utils.oauth_utils.token_repository")
    async def test_non_expired_token_skips_refresh(
        self, mock_token_repo: MagicMock
    ) -> None:
        mock_token = MagicMock()
        mock_token.get.side_effect = lambda key, default="": {
            "access_token": "valid_access",
            "refresh_token": "valid_refresh",
        }.get(key, default)
        mock_token.is_expired.return_value = False
        mock_token_repo.get_token = AsyncMock(return_value=mock_token)
        mock_token_repo.refresh_token = AsyncMock()

        await get_tokens_by_user_id("user_1")

        mock_token_repo.refresh_token.assert_not_awaited()
