"""Unit tests for the TokenRepository class.

Tests cover:
- Initialization and OAuth client registration
- Token expiration calculation (_get_token_expiration)
- Storing new tokens and updating existing tokens
- Retrieving tokens (by user/provider and by access token)
- Token refresh flow (Google provider dispatch, unsupported providers)
- Token revocation (single provider)
- Edge cases: missing refresh tokens, expired tokens, malformed data
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from authlib.oauth2.rfc6749 import OAuth2Token
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_record(
    *,
    user_id: str = "user_1",
    provider: str = "google",
    access_token: str = "access_123",
    refresh_token: Optional[str] = "refresh_456",
    token_data: Optional[str] = None,
    scopes: Optional[str] = "openid email",
    expires_at: Optional[datetime] = None,
    updated_at: Optional[datetime] = None,
    id: int = 1,
) -> MagicMock:
    """Create a mock OAuthToken database record."""
    record = MagicMock()
    record.id = id
    record.user_id = user_id
    record.provider = provider
    record.access_token = access_token
    record.refresh_token = refresh_token
    record.scopes = scopes
    record.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(hours=1))
    record.updated_at = updated_at or datetime.now(timezone.utc)
    if token_data is None:
        token_data = json.dumps(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "Bearer",
                "scope": scopes or "",
            }
        )
    record.token_data = token_data
    return record


def _make_expired_record(**kwargs: Any) -> MagicMock:
    """Create a mock OAuthToken that is already expired."""
    return _make_token_record(
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        **kwargs,
    )


def _mock_db_session(
    scalar_one_or_none_return: Any = None,
) -> AsyncMock:
    """Build a mock async context manager for get_db_session."""
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_one_or_none_return
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------


class TestTokenRepositoryInit:
    """Tests for __init__ and _init_oauth_clients."""

    @patch("app.config.token_repository.get_db_session")
    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def test_init_registers_google_when_credentials_present(
        self, mock_oauth_cls: MagicMock, mock_settings: MagicMock, _mock_db: MagicMock
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = "client_id"
        mock_settings.GOOGLE_CLIENT_SECRET = "client_secret"  # pragma: allowlist secret
        mock_oauth_instance = MagicMock()
        mock_oauth_cls.return_value = mock_oauth_instance

        repo = TokenRepository()

        mock_oauth_instance.register.assert_called_once()
        call_kwargs = mock_oauth_instance.register.call_args
        assert call_kwargs[1]["name"] == "google"
        assert call_kwargs[1]["client_id"] == "client_id"
        assert (
            call_kwargs[1]["client_secret"]
            == "client_secret"  # pragma: allowlist secret
        )
        assert repo.oauth is mock_oauth_instance

    @patch("app.config.token_repository.get_db_session")
    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def test_init_skips_google_when_credentials_missing(
        self, mock_oauth_cls: MagicMock, mock_settings: MagicMock, _mock_db: MagicMock
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        mock_oauth_instance = MagicMock()
        mock_oauth_cls.return_value = mock_oauth_instance

        TokenRepository()

        mock_oauth_instance.register.assert_not_called()

    @patch("app.config.token_repository.get_db_session")
    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def test_init_skips_google_when_only_client_id_present(
        self, mock_oauth_cls: MagicMock, mock_settings: MagicMock, _mock_db: MagicMock
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = "client_id"
        mock_settings.GOOGLE_CLIENT_SECRET = None
        mock_oauth_instance = MagicMock()
        mock_oauth_cls.return_value = mock_oauth_instance

        TokenRepository()

        mock_oauth_instance.register.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: _get_token_expiration
# ---------------------------------------------------------------------------


class TestGetTokenExpiration:
    """Tests for the _get_token_expiration helper."""

    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def setup_method(
        self,
        method: Any,
        mock_oauth_cls: MagicMock = MagicMock(),
        mock_settings: MagicMock = MagicMock(),
    ) -> None:
        """Create a TokenRepository with mocked dependencies."""
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        self.repo = TokenRepository()

    def test_uses_expires_at_timestamp(self) -> None:
        future_ts = (datetime.now() + timedelta(hours=2)).timestamp()
        result = self.repo._get_token_expiration({"expires_at": future_ts})
        expected = datetime.fromtimestamp(future_ts)
        assert abs((result - expected).total_seconds()) < 1

    def test_uses_expires_at_as_string(self) -> None:
        future_ts = str((datetime.now() + timedelta(hours=2)).timestamp())
        result = self.repo._get_token_expiration({"expires_at": future_ts})
        expected = datetime.fromtimestamp(float(future_ts))
        assert abs((result - expected).total_seconds()) < 1

    def test_falls_back_to_expires_in(self) -> None:
        before = datetime.now()
        result = self.repo._get_token_expiration({"expires_in": 7200})
        after = datetime.now()
        expected_min = before + timedelta(seconds=7200)
        expected_max = after + timedelta(seconds=7200)
        assert expected_min <= result <= expected_max

    def test_default_expires_in_when_missing(self) -> None:
        before = datetime.now()
        result = self.repo._get_token_expiration({})
        after = datetime.now()
        # Default is 3500 seconds
        expected_min = before + timedelta(seconds=3500)
        expected_max = after + timedelta(seconds=3500)
        assert expected_min <= result <= expected_max

    def test_invalid_expires_at_falls_back_to_expires_in(self) -> None:
        before = datetime.now()
        result = self.repo._get_token_expiration(
            {
                "expires_at": "not-a-number",
                "expires_in": 1800,
            }
        )
        after = datetime.now()
        expected_min = before + timedelta(seconds=1800)
        expected_max = after + timedelta(seconds=1800)
        assert expected_min <= result <= expected_max

    def test_invalid_expires_at_and_invalid_expires_in_uses_default(self) -> None:
        before = datetime.now(timezone.utc)
        result = self.repo._get_token_expiration(
            {
                "expires_at": "bad",
                "expires_in": "also-bad",
            }
        )
        # Fallback is 3600 seconds from utcnow
        expected_min = before + timedelta(seconds=3600)
        # Allow some tolerance because the production code may use utc vs local
        assert abs((result - expected_min).total_seconds()) < 5

    def test_overflow_expires_at_falls_back(self) -> None:
        """An extremely large expires_at should trigger OverflowError and fall back."""
        result = self.repo._get_token_expiration(
            {
                "expires_at": 1e20,
                "expires_in": 600,
            }
        )
        # Should fall back to expires_in=600
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: store_token
# ---------------------------------------------------------------------------


class TestStoreToken:
    """Tests for store_token — new and update paths."""

    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def setup_method(
        self,
        method: Any,
        mock_oauth_cls: MagicMock = MagicMock(),
        mock_settings: MagicMock = MagicMock(),
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        self.repo = TokenRepository()

    async def test_store_new_token(self) -> None:
        session = _mock_db_session(scalar_one_or_none_return=None)
        token_data: Dict[str, Any] = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "token_type": "Bearer",
            "scope": "openid email",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.store_token("user_1", "google", token_data)

        assert isinstance(result, OAuth2Token)
        assert result["access_token"] == "new_access"
        assert result["refresh_token"] == "new_refresh"
        assert result["token_type"] == "Bearer"
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    async def test_store_updates_existing_token(self) -> None:
        existing = _make_token_record()
        session = _mock_db_session(scalar_one_or_none_return=existing)
        token_data: Dict[str, Any] = {
            "access_token": "updated_access",
            "refresh_token": "updated_refresh",
            "token_type": "Bearer",
            "scope": "openid email profile",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.store_token("user_1", "google", token_data)

        assert isinstance(result, OAuth2Token)
        assert result["access_token"] == "updated_access"
        # execute called twice: once for SELECT, once for UPDATE
        assert session.execute.await_count == 2
        session.commit.assert_awaited_once()

    async def test_store_preserves_existing_refresh_token_when_missing(self) -> None:
        existing = _make_token_record(refresh_token="old_refresh")
        session = _mock_db_session(scalar_one_or_none_return=existing)
        token_data: Dict[str, Any] = {
            "access_token": "new_access",
            # No refresh_token provided
            "token_type": "Bearer",
            "scope": "openid",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.store_token("user_1", "google", token_data)

        assert result["refresh_token"] == "old_refresh"
        # token_data should have been mutated to include the preserved refresh_token
        assert token_data["refresh_token"] == "old_refresh"

    async def test_store_new_token_without_refresh_token(self) -> None:
        session = _mock_db_session(scalar_one_or_none_return=None)
        token_data: Dict[str, Any] = {
            "access_token": "new_access",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.store_token("user_1", "google", token_data)

        assert result["refresh_token"] is None
        session.add.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: get_token
# ---------------------------------------------------------------------------


class TestGetToken:
    """Tests for get_token — retrieval and refresh-on-expiry."""

    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def setup_method(
        self,
        method: Any,
        mock_oauth_cls: MagicMock = MagicMock(),
        mock_settings: MagicMock = MagicMock(),
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        self.repo = TokenRepository()

    async def test_get_token_success(self) -> None:
        record = _make_token_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.get_token("user_1", "google")

        assert isinstance(result, OAuth2Token)
        assert result["access_token"] == "access_123"
        assert result["refresh_token"] == "refresh_456"

    async def test_get_token_not_found_raises_401(self) -> None:
        session = _mock_db_session(scalar_one_or_none_return=None)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(HTTPException) as exc_info:
                await self.repo.get_token("user_1", "google")

        assert exc_info.value.status_code == 401
        assert "google" in str(exc_info.value.detail)

    async def test_get_token_expired_with_renew_calls_refresh(self) -> None:
        record = _make_expired_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        refreshed_token = OAuth2Token(
            params={
                "access_token": "refreshed_access",
                "refresh_token": "refreshed_refresh",
                "token_type": "Bearer",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).timestamp(),
            }
        )

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(
                self.repo,
                "refresh_token",
                new_callable=AsyncMock,
                return_value=refreshed_token,
            ):
                result = await self.repo.get_token(
                    "user_1", "google", renew_if_expired=True
                )

        assert result["access_token"] == "refreshed_access"

    async def test_get_token_expired_refresh_fails_raises_401(self) -> None:
        record = _make_expired_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(
                self.repo, "refresh_token", new_callable=AsyncMock, return_value=None
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await self.repo.get_token("user_1", "google", renew_if_expired=True)

        assert exc_info.value.status_code == 401
        assert "refresh" in str(exc_info.value.detail).lower()

    async def test_get_token_expired_without_renew_returns_expired_token(self) -> None:
        record = _make_expired_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.get_token(
                "user_1", "google", renew_if_expired=False
            )

        # Should return the token even though it is expired
        assert result["access_token"] == "access_123"

    async def test_get_token_with_no_expires_at_on_record(self) -> None:
        record = _make_token_record(expires_at=None)
        record.expires_at = None
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.get_token("user_1", "google")

        assert result["expires_at"] is None


# ---------------------------------------------------------------------------
# Tests: _refresh_google_token
# ---------------------------------------------------------------------------


class TestRefreshGoogleToken:
    """Tests for the Google-specific token refresh logic."""

    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def setup_method(
        self,
        method: Any,
        mock_oauth_cls: MagicMock = MagicMock(),
        mock_settings: MagicMock = MagicMock(),
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        self.repo = TokenRepository()
        self.mock_settings = mock_settings

    async def test_refresh_google_no_client_returns_none(self) -> None:
        self.repo.oauth = MagicMock()
        self.repo.oauth.google = None

        result = await self.repo._refresh_google_token("refresh_tok")
        assert result is None

    async def test_refresh_google_success(self) -> None:
        mock_client = MagicMock()
        mock_client.client_id = "cid"
        mock_client.client_secret = "csec"  # pragma: allowlist secret
        self.repo.oauth = MagicMock()
        self.repo.oauth.google = mock_client
        self.mock_settings.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

        response_data = {
            "access_token": "new_access",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        with patch("app.config.token_repository.httpx.AsyncClient") as mock_httpx:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo._refresh_google_token("old_refresh")

        assert result is not None
        assert result["access_token"] == "new_access"
        # The refresh token should be preserved in the result
        assert result["refresh_token"] == "old_refresh"

    async def test_refresh_google_http_error(self) -> None:
        mock_client = MagicMock()
        mock_client.client_id = "cid"
        mock_client.client_secret = "csec"  # pragma: allowlist secret
        self.repo.oauth = MagicMock()
        self.repo.oauth.google = mock_client
        self.mock_settings.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("app.config.token_repository.httpx.AsyncClient") as mock_httpx:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(
                return_value=mock_async_client
            )
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo._refresh_google_token("old_refresh")

        assert result is None

    async def test_refresh_google_exception_returns_none(self) -> None:
        mock_client = MagicMock()
        mock_client.client_id = "cid"
        mock_client.client_secret = "csec"  # pragma: allowlist secret
        self.repo.oauth = MagicMock()
        self.repo.oauth.google = mock_client
        self.mock_settings.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

        with patch("app.config.token_repository.httpx.AsyncClient") as mock_httpx:
            mock_httpx.return_value.__aenter__ = AsyncMock(
                side_effect=ConnectionError("timeout")
            )

            result = await self.repo._refresh_google_token("old_refresh")

        assert result is None


# ---------------------------------------------------------------------------
# Tests: _refresh_provider_token
# ---------------------------------------------------------------------------


class TestRefreshProviderToken:
    """Tests for provider dispatch in _refresh_provider_token."""

    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def setup_method(
        self,
        method: Any,
        mock_oauth_cls: MagicMock = MagicMock(),
        mock_settings: MagicMock = MagicMock(),
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        self.repo = TokenRepository()

    async def test_dispatches_google(self) -> None:
        expected = OAuth2Token(params={"access_token": "refreshed"})
        with patch.object(
            self.repo,
            "_refresh_google_token",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            result = await self.repo._refresh_provider_token("google", "refresh_tok")
        assert result is expected

    async def test_unsupported_provider_returns_none(self) -> None:
        result = await self.repo._refresh_provider_token(
            "unsupported_provider", "refresh_tok"
        )
        assert result is None

    async def test_slack_provider_returns_none(self) -> None:
        result = await self.repo._refresh_provider_token("slack", "refresh_tok")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: refresh_token (full flow)
# ---------------------------------------------------------------------------


class TestRefreshToken:
    """Tests for the full refresh_token orchestration."""

    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def setup_method(
        self,
        method: Any,
        mock_oauth_cls: MagicMock = MagicMock(),
        mock_settings: MagicMock = MagicMock(),
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        self.repo = TokenRepository()

    async def test_refresh_no_token_record_returns_none(self) -> None:
        session = _mock_db_session(scalar_one_or_none_return=None)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.refresh_token("user_1", "google")

        assert result is None

    async def test_refresh_no_refresh_token_returns_none(self) -> None:
        record = _make_token_record(refresh_token=None)
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.refresh_token("user_1", "google")

        assert result is None

    async def test_refresh_provider_returns_none_means_failure(self) -> None:
        record = _make_token_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(
                self.repo,
                "_refresh_provider_token",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await self.repo.refresh_token("user_1", "google")

        assert result is None

    async def test_refresh_success_stores_and_returns_token(self) -> None:
        record = _make_token_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        provider_token = MagicMock()
        provider_token.get = lambda key, default=None: {
            "access_token": "new_access",
            "token_type": "Bearer",
            "scope": "openid",
            "expires_in": 3600,
            "expires_at": None,
            "refresh_token": "new_refresh",
        }.get(key, default)

        stored_token = OAuth2Token(
            params={"access_token": "new_access", "refresh_token": "new_refresh"}
        )

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(
                self.repo,
                "_refresh_provider_token",
                new_callable=AsyncMock,
                return_value=provider_token,
            ):
                with patch.object(
                    self.repo,
                    "store_token",
                    new_callable=AsyncMock,
                    return_value=stored_token,
                ):
                    result = await self.repo.refresh_token("user_1", "google")

        assert result is stored_token

    async def test_refresh_exception_returns_none(self) -> None:
        record = _make_token_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(
                self.repo,
                "_refresh_provider_token",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                result = await self.repo.refresh_token("user_1", "google")

        assert result is None


# ---------------------------------------------------------------------------
# Tests: revoke_token
# ---------------------------------------------------------------------------


class TestRevokeToken:
    """Tests for revoking a single provider token."""

    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def setup_method(
        self,
        method: Any,
        mock_oauth_cls: MagicMock = MagicMock(),
        mock_settings: MagicMock = MagicMock(),
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        self.repo = TokenRepository()

    async def test_revoke_success(self) -> None:
        record = _make_token_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.revoke_token("user_1", "google")

        assert result is True
        session.delete.assert_awaited_once_with(record)
        session.commit.assert_awaited_once()

    async def test_revoke_no_token_returns_false(self) -> None:
        session = _mock_db_session(scalar_one_or_none_return=None)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.revoke_token("user_1", "google")

        assert result is False

    async def test_revoke_exception_rolls_back(self) -> None:
        record = _make_token_record()
        session = _mock_db_session(scalar_one_or_none_return=record)
        session.delete = AsyncMock(side_effect=RuntimeError("db error"))

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.revoke_token("user_1", "google")

        assert result is False
        session.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: get_token_by_auth_token
# ---------------------------------------------------------------------------


class TestGetTokenByAuthToken:
    """Tests for access-token-based lookup."""

    @patch("app.config.token_repository.settings")
    @patch("app.config.token_repository.OAuth")
    def setup_method(
        self,
        method: Any,
        mock_oauth_cls: MagicMock = MagicMock(),
        mock_settings: MagicMock = MagicMock(),
    ) -> None:
        from app.config.token_repository import TokenRepository

        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        self.repo = TokenRepository()

    async def test_found_returns_token(self) -> None:
        record = _make_token_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.get_token_by_auth_token("access_123")

        assert result is not None
        assert result["access_token"] == "access_123"

    async def test_not_found_returns_none(self) -> None:
        session = _mock_db_session(scalar_one_or_none_return=None)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.get_token_by_auth_token("nonexistent")

        assert result is None

    async def test_expired_with_renew_calls_refresh(self) -> None:
        record = _make_expired_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        refreshed = OAuth2Token(
            params={
                "access_token": "refreshed",
                "refresh_token": "ref",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).timestamp(),
            }
        )

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(
                self.repo,
                "refresh_token",
                new_callable=AsyncMock,
                return_value=refreshed,
            ):
                result = await self.repo.get_token_by_auth_token(
                    "access_123", renew_if_expired=True
                )

        assert result["access_token"] == "refreshed"  # type: ignore[index]

    async def test_expired_refresh_fails_raises_401(self) -> None:
        record = _make_expired_record()
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch.object(
                self.repo, "refresh_token", new_callable=AsyncMock, return_value=None
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await self.repo.get_token_by_auth_token(
                        "access_123", renew_if_expired=True
                    )

        assert exc_info.value.status_code == 401

    async def test_no_expires_at_on_record(self) -> None:
        record = _make_token_record()
        record.expires_at = None
        session = _mock_db_session(scalar_one_or_none_return=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await self.repo.get_token_by_auth_token("access_123")

        assert result is not None
        assert result["expires_at"] is None
