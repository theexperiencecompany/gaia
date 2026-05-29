"""Mutation-verified unit tests for app/config/token_repository.py :: TokenRepository.

The repository is the single gateway for third-party integration OAuth tokens
(Google, Slack, Notion, ...). Every test below imports the real class, mocks only
the I/O boundary (the async DB session via ``get_db_session`` and the outbound
``httpx`` client), and asserts the real behaviour the rest of the app relies on:
the OAuth2Token payloads returned to callers, the exact SQL filters/values issued
to PostgreSQL, the outbound Google refresh request, and every error/early-return
branch.

BEHAVIOR SPEC
=============
UNIT: TokenRepository._init_oauth_clients
EXPECTED: Register a Google OAuth client named "google" with the configured
          client id/secret and openid scopes ONLY when both credentials are set.
MUST-CATCH: register called iff both creds present; the registered name/id/secret/
            scope/prompt are the configured values (not blanked).

UNIT: TokenRepository._get_token_expiration
EXPECTED: Prefer a valid expires_at timestamp; else expires_in seconds from now
          (default 3500); on both invalid, fall back to now+3600s.
MUST-CATCH: expires_at path vs expires_in path; the 3500 default; the 3600 fallback;
            invalid expires_at falls through to expires_in.

UNIT: TokenRepository.store_token
EXPECTED: Insert a new OAuthToken or UPDATE the existing one; preserve a prior
          refresh token when none supplied; return an OAuth2Token carrying the
          stored access/refresh/token_type/expires_at/scope.
MUST-CATCH: new vs update branch (session.add vs UPDATE statement); the UPDATE
            targets the existing row id and writes the new column values; refresh
            token preservation mutates token_data; token_type defaults to "Bearer";
            returned OAuth2Token keys/values.

UNIT: TokenRepository.get_token
EXPECTED: Look up by (user_id, provider); 401 if absent; return OAuth2Token; when
          renew_if_expired and the token is expired, return the refreshed token or
          raise 401 if refresh fails.
MUST-CATCH: the SELECT filters on user_id AND provider; missing -> 401 with provider
            name; expired+renew -> refresh result; refresh failure -> 401; expired
            without renew -> the (expired) token returned unchanged.

UNIT: TokenRepository._refresh_google_token
EXPECTED: POST the refresh-token grant to GOOGLE_TOKEN_URL; on 200 return an
          OAuth2Token with the original refresh token re-injected; else None.
MUST-CATCH: no google client -> None; the posted data (grant_type/client_id/secret/
            refresh_token) and Content-Type header; non-200 -> None; network error
            -> None; refresh token preserved in the returned token.

UNIT: TokenRepository._refresh_provider_token
EXPECTED: Dispatch "google" to _refresh_google_token; anything else -> None.
MUST-CATCH: google dispatched with the refresh token; non-google -> None.

UNIT: TokenRepository.refresh_token
EXPECTED: Load the row; bail (None) if no row or no refresh token; otherwise refresh
          via the provider handler and persist via store_token, returning its result.
MUST-CATCH: no row -> None; no refresh token -> None; provider returns None -> None;
            success persists the refreshed fields and returns the stored token; any
            exception -> None.

UNIT: TokenRepository.revoke_token
EXPECTED: Delete the row and return True; False if absent; False + rollback on error.
MUST-CATCH: success deletes the exact row and commits, returns True; absent -> False;
            delete error -> rollback + False.

UNIT: TokenRepository.get_token_by_auth_token
EXPECTED: Look up by access_token; None if absent; OAuth2Token (token_type "Bearer",
          scopes from record) otherwise; renew-on-expiry like get_token but raising
          401 only when refresh fails.
MUST-CATCH: the SELECT filters on access_token; missing -> None; returned payload
            keys/values; expired+renew -> refreshed token; refresh failure -> 401.

EQUIVALENT MUTANTS (justified survivors): docstring ``str -> ''`` mutations and
``log.*`` message ``str -> ''`` mutations change no observable behaviour and are not
asserted on. Defaulted-empty-string fallbacks (``scope``/``scopes`` default "") that
mutate to "" are byte-identical no-ops.
"""

from datetime import UTC, datetime, timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from authlib.oauth2.rfc6749 import OAuth2Token
from fastapi import HTTPException
import pytest
from sqlalchemy.sql import Update

from app.config.token_repository import TokenRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_repo() -> TokenRepository:
    """Construct a TokenRepository with OAuth registration stubbed out.

    Patches ``OAuth`` (so no real client metadata is fetched) and ``settings`` so
    no Google client is registered. The repository under test is real otherwise.
    """
    with (
        patch("app.config.token_repository.OAuth"),
        patch("app.config.token_repository.settings") as mock_settings,
    ):
        mock_settings.GOOGLE_CLIENT_ID = None
        mock_settings.GOOGLE_CLIENT_SECRET = None
        return TokenRepository()


def _make_token_record(
    *,
    user_id: str = "user_1",
    provider: str = "google",
    access_token: str = "access_123",
    refresh_token: str | None = "refresh_456",
    token_data: str | None = None,
    scopes: str | None = "openid email",
    expires_at: datetime | None = None,
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
    record.expires_at = expires_at or (datetime.now(UTC) + timedelta(hours=1))
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
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        **kwargs,
    )


class _CapturingSession:
    """A stand-in async DB session that records every statement it executes.

    The real session forwards a SQLAlchemy ``select``/``update`` statement to
    Postgres; here we capture each statement (so tests can assert the exact filter
    and stored values) and return a result whose ``scalar_one_or_none`` yields the
    configured record.
    """

    def __init__(self, scalar_result: Any = None) -> None:
        self._scalar_result = scalar_result
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.delete = AsyncMock()

    async def execute(self, statement: Any) -> MagicMock:
        self.statements.append(statement)
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._scalar_result
        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _patch_db(session: _CapturingSession) -> Any:
    """Patch get_db_session to yield ``session`` from its async context manager."""
    ctx = patch("app.config.token_repository.get_db_session")
    return ctx, session


def _install_session(mock_get_db: MagicMock, session: _CapturingSession) -> None:
    mock_get_db.return_value.__aenter__ = AsyncMock(return_value=session)
    mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)


def _select_where_sql(statement: Any) -> str:
    """Render a SELECT statement's WHERE clause with literal values."""
    return str(statement.whereclause.compile(compile_kwargs={"literal_binds": True}))


def _update_values(statement: Update) -> dict[str, Any]:
    """Extract the SET column->value parameters from an UPDATE statement."""
    return dict(statement.compile().params)


def _update_where_sql(statement: Update) -> str:
    """Render an UPDATE statement's WHERE clause with literal values."""
    return str(statement.whereclause.compile(compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# _init_oauth_clients
# ---------------------------------------------------------------------------


class TestInitOAuthClients:
    def test_registers_google_with_configured_credentials(self) -> None:
        with (
            patch("app.config.token_repository.OAuth") as mock_oauth_cls,
            patch("app.config.token_repository.settings") as mock_settings,
        ):
            mock_settings.GOOGLE_CLIENT_ID = "the-client-id"
            mock_settings.GOOGLE_CLIENT_SECRET = "the-secret"  # pragma: allowlist secret
            instance = MagicMock()
            mock_oauth_cls.return_value = instance

            repo = TokenRepository()

        assert repo.oauth is instance
        instance.register.assert_called_once()
        kwargs = instance.register.call_args.kwargs
        assert kwargs["name"] == "google"
        assert kwargs["client_id"] == "the-client-id"
        assert kwargs["client_secret"] == "the-secret"  # pragma: allowlist secret
        assert (
            kwargs["server_metadata_url"]
            == "https://accounts.google.com/.well-known/openid-configuration"
        )
        assert kwargs["client_kwargs"]["scope"] == "openid email profile"
        assert kwargs["client_kwargs"]["prompt"] == "select_account"

    def test_skips_registration_when_both_credentials_missing(self) -> None:
        with (
            patch("app.config.token_repository.OAuth") as mock_oauth_cls,
            patch("app.config.token_repository.settings") as mock_settings,
        ):
            mock_settings.GOOGLE_CLIENT_ID = None
            mock_settings.GOOGLE_CLIENT_SECRET = None
            instance = MagicMock()
            mock_oauth_cls.return_value = instance

            TokenRepository()

        instance.register.assert_not_called()

    def test_skips_registration_when_secret_missing(self) -> None:
        with (
            patch("app.config.token_repository.OAuth") as mock_oauth_cls,
            patch("app.config.token_repository.settings") as mock_settings,
        ):
            mock_settings.GOOGLE_CLIENT_ID = "the-client-id"
            mock_settings.GOOGLE_CLIENT_SECRET = None
            instance = MagicMock()
            mock_oauth_cls.return_value = instance

            TokenRepository()

        instance.register.assert_not_called()


# ---------------------------------------------------------------------------
# _get_token_expiration
# ---------------------------------------------------------------------------


class TestGetTokenExpiration:
    def setup_method(self, _method: Any) -> None:
        self.repo = _build_repo()

    def test_uses_expires_at_when_valid(self) -> None:
        future_ts = (datetime.now() + timedelta(hours=2)).timestamp()
        result = self.repo._get_token_expiration({"expires_at": future_ts, "expires_in": 60})
        expected = datetime.fromtimestamp(future_ts)
        # Must use expires_at (2h out), not expires_in (60s out).
        assert abs((result - expected).total_seconds()) < 1
        assert result > datetime.now() + timedelta(hours=1)

    def test_accepts_expires_at_as_numeric_string(self) -> None:
        future_ts = str((datetime.now() + timedelta(hours=2)).timestamp())
        result = self.repo._get_token_expiration({"expires_at": future_ts})
        expected = datetime.fromtimestamp(float(future_ts))
        assert abs((result - expected).total_seconds()) < 1

    def test_falls_back_to_expires_in(self) -> None:
        before = datetime.now()
        result = self.repo._get_token_expiration({"expires_in": 7200})
        after = datetime.now()
        assert before + timedelta(seconds=7200) <= result <= after + timedelta(seconds=7200)

    def test_default_expires_in_is_3500_seconds(self) -> None:
        before = datetime.now()
        result = self.repo._get_token_expiration({})
        after = datetime.now()
        assert before + timedelta(seconds=3500) <= result <= after + timedelta(seconds=3500)
        # Distinguish the real default (3500) from neighbouring values.
        assert result < before + timedelta(seconds=3501)

    def test_invalid_expires_at_falls_through_to_expires_in(self) -> None:
        before = datetime.now()
        result = self.repo._get_token_expiration({"expires_at": "not-a-number", "expires_in": 1800})
        after = datetime.now()
        assert before + timedelta(seconds=1800) <= result <= after + timedelta(seconds=1800)

    def test_both_invalid_uses_3600_default(self) -> None:
        before = datetime.now(UTC)
        result = self.repo._get_token_expiration({"expires_at": "bad", "expires_in": "also-bad"})
        after = datetime.now(UTC)
        # Fallback is exactly now(UTC)+3600s.
        assert before + timedelta(seconds=3600) <= result <= after + timedelta(seconds=3600)
        assert result < before + timedelta(seconds=3601)


# ---------------------------------------------------------------------------
# store_token
# ---------------------------------------------------------------------------


class TestStoreToken:
    def setup_method(self, _method: Any) -> None:
        self.repo = _build_repo()

    async def test_new_token_inserts_row_and_returns_payload(self) -> None:
        session = _CapturingSession(scalar_result=None)
        # Distinct token_type/scope (not the defaults) so the dict lookups must use
        # the real keys, not the "Bearer"/"" fallbacks.
        token_data: dict[str, Any] = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "token_type": "MAC",
            "scope": "openid email",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.store_token("user_1", "google", token_data)

        # Insert path: a new OAuthToken row was added with the right columns.
        assert len(session.added) == 1
        new_row = session.added[0]
        assert new_row.user_id == "user_1"
        assert new_row.provider == "google"
        assert new_row.access_token == "new_access"
        assert new_row.refresh_token == "new_refresh"
        assert new_row.scopes == "openid email"
        session.commit.assert_awaited_once()

        # Only the SELECT lookup ran (no UPDATE).
        assert len(session.statements) == 1
        where_sql = _select_where_sql(session.statements[0])
        assert "user_id = 'user_1'" in where_sql
        assert "provider = 'google'" in where_sql

        # Returned OAuth2Token carries the stored data, reading the real dict keys.
        assert isinstance(result, OAuth2Token)
        assert result["access_token"] == "new_access"
        assert result["refresh_token"] == "new_refresh"
        assert result["token_type"] == "MAC"
        assert result["scope"] == "openid email"
        assert result["expires_at"] is not None

    async def test_token_type_defaults_to_bearer_when_absent(self) -> None:
        session = _CapturingSession(scalar_result=None)
        token_data: dict[str, Any] = {
            "access_token": "acc",
            "refresh_token": "ref",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.store_token("user_1", "google", token_data)

        assert result["token_type"] == "Bearer"

    async def test_existing_token_issues_update_with_new_values(self) -> None:
        existing = _make_token_record(id=42, refresh_token="old_refresh")
        session = _CapturingSession(scalar_result=existing)
        token_data: dict[str, Any] = {
            "access_token": "updated_access",
            "refresh_token": "updated_refresh",
            "token_type": "Bearer",
            "scope": "openid email profile",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.store_token("user_1", "google", token_data)

        # SELECT then UPDATE.
        assert len(session.statements) == 2
        assert session.added == []
        update_stmt = session.statements[1]
        assert isinstance(update_stmt, Update)
        # The UPDATE targets the existing row (id == 42), not some other row.
        assert "id = 42" in _update_where_sql(update_stmt)
        values = _update_values(update_stmt)
        assert values["access_token"] == "updated_access"
        assert values["refresh_token"] == "updated_refresh"
        assert values["scopes"] == "openid email profile"
        session.commit.assert_awaited_once()

        assert result["access_token"] == "updated_access"

    async def test_preserves_existing_refresh_token_when_none_supplied(self) -> None:
        existing = _make_token_record(refresh_token="old_refresh")
        session = _CapturingSession(scalar_result=existing)
        token_data: dict[str, Any] = {
            "access_token": "new_access",
            "token_type": "Bearer",
            "scope": "openid",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.store_token("user_1", "google", token_data)

        # The preserved refresh token is written to the UPDATE and the input dict.
        update_stmt = session.statements[1]
        assert _update_values(update_stmt)["refresh_token"] == "old_refresh"
        assert token_data["refresh_token"] == "old_refresh"
        assert result["refresh_token"] == "old_refresh"

    async def test_new_token_without_refresh_token_stores_none(self) -> None:
        session = _CapturingSession(scalar_result=None)
        token_data: dict[str, Any] = {
            "access_token": "new_access",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.store_token("user_1", "google", token_data)

        assert result["refresh_token"] is None
        assert session.added[0].refresh_token is None


# ---------------------------------------------------------------------------
# get_token
# ---------------------------------------------------------------------------


class TestGetToken:
    def setup_method(self, _method: Any) -> None:
        self.repo = _build_repo()

    async def test_returns_token_and_filters_by_user_and_provider(self) -> None:
        # The token_type/scope are read from the record's JSON blob; use distinct
        # values (not the "Bearer"/"" defaults) so the JSON lookup keys matter.
        token_json = json.dumps({"token_type": "MAC", "scope": "drive.read"})
        record = _make_token_record(token_data=token_json)
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.get_token("user_1", "google")

        where_sql = _select_where_sql(session.statements[0])
        assert "user_id = 'user_1'" in where_sql
        assert "provider = 'google'" in where_sql
        assert isinstance(result, OAuth2Token)
        assert result["access_token"] == "access_123"
        assert result["refresh_token"] == "refresh_456"
        assert result["token_type"] == "MAC"
        assert result["scope"] == "drive.read"

    async def test_missing_token_raises_401_naming_provider(self) -> None:
        session = _CapturingSession(scalar_result=None)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with pytest.raises(HTTPException) as exc:
                await self.repo.get_token("user_1", "notion")

        assert exc.value.status_code == 401
        assert exc.value.detail == "No notion token found for this user"

    async def test_token_type_defaults_to_bearer_when_json_lacks_it(self) -> None:
        # The stored JSON has no token_type -> the "Bearer" default is used.
        token_json = json.dumps({"scope": "openid"})
        record = _make_token_record(token_data=token_json)
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.get_token("user_1", "google")

        assert result["token_type"] == "Bearer"

    async def test_expired_with_renew_returns_refreshed_token(self) -> None:
        record = _make_expired_record()
        session = _CapturingSession(scalar_result=record)
        refreshed = OAuth2Token(
            params={
                "access_token": "refreshed_access",
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
            }
        )

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(
                self.repo, "refresh_token", new_callable=AsyncMock, return_value=refreshed
            ) as mock_refresh:
                result = await self.repo.get_token("user_1", "google", renew_if_expired=True)

        mock_refresh.assert_awaited_once_with("user_1", "google")
        assert result["access_token"] == "refreshed_access"

    async def test_expired_with_renew_raises_401_when_refresh_fails(self) -> None:
        record = _make_expired_record()
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(
                self.repo, "refresh_token", new_callable=AsyncMock, return_value=None
            ):
                with pytest.raises(HTTPException) as exc:
                    await self.repo.get_token("user_1", "google", renew_if_expired=True)

        assert exc.value.status_code == 401
        assert exc.value.detail == "Failed to refresh google token"

    async def test_expired_defaults_to_no_renew_and_returns_expired_token(self) -> None:
        # renew_if_expired is omitted: it must default to False, so even an expired
        # token is returned untouched without attempting a refresh.
        record = _make_expired_record()
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(self.repo, "refresh_token", new_callable=AsyncMock) as mock_refresh:
                result = await self.repo.get_token("user_1", "google")

        # No refresh attempted; the expired token is handed back as-is.
        mock_refresh.assert_not_awaited()
        assert result["access_token"] == "access_123"
        assert result.is_expired() is True

    async def test_record_without_expiry_yields_none_expires_at(self) -> None:
        record = _make_token_record()
        record.expires_at = None
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.get_token("user_1", "google")

        assert result["expires_at"] is None


# ---------------------------------------------------------------------------
# _refresh_google_token
# ---------------------------------------------------------------------------


class TestRefreshGoogleToken:
    def setup_method(self, _method: Any) -> None:
        self.repo = _build_repo()

    def _attach_google_client(self) -> None:
        client = MagicMock()
        client.client_id = "cid"
        client.client_secret = "csec"  # pragma: allowlist secret
        self.repo.oauth = MagicMock()
        self.repo.oauth.google = client

    async def test_no_google_client_returns_none(self) -> None:
        self.repo.oauth = MagicMock()
        self.repo.oauth.google = None

        result = await self.repo._refresh_google_token("refresh_tok")
        assert result is None

    async def test_success_posts_refresh_grant_and_preserves_refresh_token(self) -> None:
        self._attach_google_client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "access_token": "new_access",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=response)

        with (
            patch("app.config.token_repository.httpx.AsyncClient") as mock_httpx,
            patch("app.config.token_repository.settings") as mock_settings,
        ):
            mock_settings.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=http_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await self.repo._refresh_google_token("old_refresh")

        # The outbound request is the OAuth2 refresh-token grant.
        http_client.post.assert_awaited_once()
        url = http_client.post.call_args.args[0]
        kwargs = http_client.post.call_args.kwargs
        assert url == "https://oauth2.googleapis.com/token"
        assert kwargs["data"] == {
            "client_id": "cid",
            "client_secret": "csec",  # pragma: allowlist secret
            "refresh_token": "old_refresh",
            "grant_type": "refresh_token",
        }
        assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

        assert result is not None
        assert result["access_token"] == "new_access"
        # Google omits the refresh token in refresh responses; it is re-injected.
        assert result["refresh_token"] == "old_refresh"

    async def test_non_200_response_returns_none(self) -> None:
        self._attach_google_client()
        response = MagicMock()
        response.status_code = 400
        response.text = "Bad Request"
        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=response)

        with (
            patch("app.config.token_repository.httpx.AsyncClient") as mock_httpx,
            patch("app.config.token_repository.settings") as mock_settings,
        ):
            mock_settings.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=http_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await self.repo._refresh_google_token("old_refresh")

        assert result is None

    async def test_network_error_returns_none(self) -> None:
        self._attach_google_client()

        with (
            patch("app.config.token_repository.httpx.AsyncClient") as mock_httpx,
            patch("app.config.token_repository.settings") as mock_settings,
        ):
            mock_settings.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
            mock_httpx.return_value.__aenter__ = AsyncMock(side_effect=ConnectionError("boom"))
            result = await self.repo._refresh_google_token("old_refresh")

        assert result is None


# ---------------------------------------------------------------------------
# _refresh_provider_token
# ---------------------------------------------------------------------------


class TestRefreshProviderToken:
    def setup_method(self, _method: Any) -> None:
        self.repo = _build_repo()

    async def test_google_dispatches_to_google_handler(self) -> None:
        expected = OAuth2Token(params={"access_token": "refreshed"})
        with patch.object(
            self.repo, "_refresh_google_token", new_callable=AsyncMock, return_value=expected
        ) as mock_google:
            result = await self.repo._refresh_provider_token("google", "refresh_tok")

        mock_google.assert_awaited_once_with("refresh_tok")
        assert result is expected

    async def test_unsupported_provider_returns_none_without_dispatch(self) -> None:
        with patch.object(
            self.repo, "_refresh_google_token", new_callable=AsyncMock
        ) as mock_google:
            result = await self.repo._refresh_provider_token("slack", "refresh_tok")

        mock_google.assert_not_awaited()
        assert result is None


# ---------------------------------------------------------------------------
# refresh_token
# ---------------------------------------------------------------------------


class TestRefreshToken:
    def setup_method(self, _method: Any) -> None:
        self.repo = _build_repo()

    async def test_no_token_record_returns_none(self) -> None:
        session = _CapturingSession(scalar_result=None)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.refresh_token("user_1", "google")

        assert result is None

    async def test_missing_refresh_token_returns_none(self) -> None:
        record = _make_token_record(refresh_token=None)
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(
                self.repo, "_refresh_provider_token", new_callable=AsyncMock
            ) as mock_provider:
                result = await self.repo.refresh_token("user_1", "google")

        # Bails before attempting a provider refresh.
        mock_provider.assert_not_awaited()
        assert result is None

    async def test_provider_returns_none_means_failure(self) -> None:
        record = _make_token_record()
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(
                self.repo, "_refresh_provider_token", new_callable=AsyncMock, return_value=None
            ):
                result = await self.repo.refresh_token("user_1", "google")

        assert result is None

    async def test_success_maps_provider_fields_and_returns_stored(self) -> None:
        record = _make_token_record(refresh_token="db_refresh", scopes="db_scope")
        session = _CapturingSession(scalar_result=record)
        # Provider returns distinct values for every field so the token_dict mapping
        # must read the real provider keys (not blanked lookup keys / DB fallbacks).
        provider_token = OAuth2Token(
            params={
                "access_token": "new_access",
                "token_type": "MAC",
                "scope": "new_scope",
                "expires_in": 999,
                "expires_at": 1893456000,
                "refresh_token": "provider_refresh",
            }
        )
        stored = OAuth2Token(
            params={"access_token": "new_access", "refresh_token": "provider_refresh"}
        )

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with (
                patch.object(
                    self.repo,
                    "_refresh_provider_token",
                    new_callable=AsyncMock,
                    return_value=provider_token,
                ) as mock_provider,
                patch.object(
                    self.repo, "store_token", new_callable=AsyncMock, return_value=stored
                ) as mock_store,
            ):
                result = await self.repo.refresh_token("user_1", "google")

        # The row was looked up by user + provider.
        assert "user_id = 'user_1'" in _select_where_sql(session.statements[0])
        assert "provider = 'google'" in _select_where_sql(session.statements[0])

        mock_provider.assert_awaited_once_with("google", "db_refresh")
        # Every field is taken from the provider response under its real key.
        stored_args = mock_store.call_args.args
        assert stored_args[0] == "user_1"
        assert stored_args[1] == "google"
        token_dict = stored_args[2]
        assert token_dict["access_token"] == "new_access"
        assert token_dict["token_type"] == "MAC"
        assert token_dict["scope"] == "new_scope"
        assert token_dict["expires_in"] == 999
        assert token_dict["expires_at"] == 1893456000
        assert token_dict["refresh_token"] == "provider_refresh"
        assert result is stored

    async def test_success_falls_back_to_defaults_when_provider_omits_fields(self) -> None:
        # The provider response carries only an access token: scope/refresh_token
        # fall back to the DB record, and token_type falls back to "Bearer".
        record = _make_token_record(refresh_token="db_refresh", scopes="db_scope")
        session = _CapturingSession(scalar_result=record)
        provider_token = OAuth2Token(params={"access_token": "new_access"})
        stored = OAuth2Token(params={"access_token": "new_access"})

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with (
                patch.object(
                    self.repo,
                    "_refresh_provider_token",
                    new_callable=AsyncMock,
                    return_value=provider_token,
                ),
                patch.object(
                    self.repo, "store_token", new_callable=AsyncMock, return_value=stored
                ) as mock_store,
            ):
                await self.repo.refresh_token("user_1", "google")

        token_dict = mock_store.call_args.args[2]
        assert token_dict["token_type"] == "Bearer"
        assert token_dict["scope"] == "db_scope"
        assert token_dict["refresh_token"] == "db_refresh"

    async def test_exception_during_refresh_returns_none(self) -> None:
        record = _make_token_record()
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(
                self.repo,
                "_refresh_provider_token",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                result = await self.repo.refresh_token("user_1", "google")

        assert result is None


# ---------------------------------------------------------------------------
# revoke_token
# ---------------------------------------------------------------------------


class TestRevokeToken:
    def setup_method(self, _method: Any) -> None:
        self.repo = _build_repo()

    async def test_success_deletes_row_and_returns_true(self) -> None:
        record = _make_token_record()
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.revoke_token("user_1", "google")

        assert result is True
        # The row deleted is the one matching user + provider.
        where_sql = _select_where_sql(session.statements[0])
        assert "user_id = 'user_1'" in where_sql
        assert "provider = 'google'" in where_sql
        session.delete.assert_awaited_once_with(record)
        session.commit.assert_awaited_once()

    async def test_missing_token_returns_false_without_delete(self) -> None:
        session = _CapturingSession(scalar_result=None)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.revoke_token("user_1", "google")

        assert result is False
        session.delete.assert_not_awaited()

    async def test_delete_error_rolls_back_and_returns_false(self) -> None:
        record = _make_token_record()
        session = _CapturingSession(scalar_result=record)
        session.delete = AsyncMock(side_effect=RuntimeError("db error"))

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.revoke_token("user_1", "google")

        assert result is False
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_token_by_auth_token
# ---------------------------------------------------------------------------


class TestGetTokenByAuthToken:
    def setup_method(self, _method: Any) -> None:
        self.repo = _build_repo()

    async def test_found_returns_token_filtered_by_access_token(self) -> None:
        record = _make_token_record(
            access_token="access_123", refresh_token="refresh_789", scopes="openid email"
        )
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.get_token_by_auth_token("access_123")

        where_sql = _select_where_sql(session.statements[0])
        assert "access_token = 'access_123'" in where_sql
        assert result is not None
        assert result["access_token"] == "access_123"
        assert result["refresh_token"] == "refresh_789"
        # token_type is hard-coded "Bearer" here; scope comes straight off the record.
        assert result["token_type"] == "Bearer"
        assert result["scope"] == "openid email"

    async def test_renew_requested_but_token_valid_returns_token_without_refresh(
        self,
    ) -> None:
        # renew_if_expired is True but the token is still valid -> the AND short
        # circuits, no refresh is attempted, the existing token is returned.
        record = _make_token_record(access_token="access_123")
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(self.repo, "refresh_token", new_callable=AsyncMock) as mock_refresh:
                result = await self.repo.get_token_by_auth_token(
                    "access_123", renew_if_expired=True
                )

        mock_refresh.assert_not_awaited()
        assert result["access_token"] == "access_123"  # type: ignore[index]

    async def test_not_found_returns_none(self) -> None:
        session = _CapturingSession(scalar_result=None)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.get_token_by_auth_token("nonexistent")

        assert result is None

    async def test_expired_with_renew_returns_refreshed_token(self) -> None:
        record = _make_expired_record(user_id="owner_9", provider="google")
        session = _CapturingSession(scalar_result=record)
        refreshed = OAuth2Token(
            params={
                "access_token": "refreshed",
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
            }
        )

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(
                self.repo, "refresh_token", new_callable=AsyncMock, return_value=refreshed
            ) as mock_refresh:
                result = await self.repo.get_token_by_auth_token(
                    "access_123", renew_if_expired=True
                )

        # Refresh is keyed by the record's owner + provider, not the access token.
        mock_refresh.assert_awaited_once_with("owner_9", "google")
        assert result["access_token"] == "refreshed"  # type: ignore[index]

    async def test_expired_with_renew_raises_401_when_refresh_fails(self) -> None:
        record = _make_expired_record(provider="notion")
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(
                self.repo, "refresh_token", new_callable=AsyncMock, return_value=None
            ):
                with pytest.raises(HTTPException) as exc:
                    await self.repo.get_token_by_auth_token("access_123", renew_if_expired=True)

        assert exc.value.status_code == 401
        assert exc.value.detail == "Failed to refresh notion token"

    async def test_expired_defaults_to_no_renew(self) -> None:
        # renew_if_expired omitted -> defaults to False; the expired token is
        # returned without attempting a refresh.
        record = _make_expired_record(access_token="access_123")
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            with patch.object(self.repo, "refresh_token", new_callable=AsyncMock) as mock_refresh:
                result = await self.repo.get_token_by_auth_token("access_123")

        mock_refresh.assert_not_awaited()
        assert result["access_token"] == "access_123"  # type: ignore[index]

    async def test_record_without_expiry_yields_none_expires_at(self) -> None:
        record = _make_token_record()
        record.expires_at = None
        session = _CapturingSession(scalar_result=record)

        with patch("app.config.token_repository.get_db_session") as mock_get_db:
            _install_session(mock_get_db, session)
            result = await self.repo.get_token_by_auth_token("access_123")

        assert result is not None
        assert result["expires_at"] is None
