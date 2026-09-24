"""Unit tests for app.utils.auth_utils — WorkOS session authentication."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.config.feature_flags import FeatureFlag
from app.constants.auth import DEV_USER_HEADER
from app.models.first_steps_models import FirstStepsState
from app.models.user_models import OnboardingSubdocument, UserDocument
from app.utils.auth_utils import (
    authenticate_workos_session,
    build_user_context,
    load_user_context,
    resolve_bot_user,
    resolve_dev_bypass_user,
)


def _as_user(db_doc: dict) -> UserDocument:
    data = {k: v for k, v in db_doc.items() if k != "_id"}
    if "_id" in db_doc:
        data["id"] = str(db_doc["_id"])
    return UserDocument.model_validate(data)


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_PATCH_SETTINGS = "app.utils.auth_utils.settings"
_PATCH_USER_REPO = "app.utils.auth_utils.user_repository"
_PATCH_LOG = "app.utils.auth_utils.log"
_PATCH_WORKOS_CLIENT = "app.utils.auth_utils.AsyncWorkOSClient"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workos_user(
    email: str = "alice@example.com",
    first_name: str = "Alice",
    last_name: str = "Smith",
    user_id: str = "workos_user_123",
) -> MagicMock:
    """Create a mock WorkOS user object."""
    user = MagicMock()
    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    user.id = user_id
    return user


def _make_auth_response(
    authenticated: bool = True,
    user: MagicMock | None = None,
    reason: str | None = None,
) -> MagicMock:
    """Create a mock authentication response."""
    response = MagicMock()
    response.authenticated = authenticated
    response.user = user
    response.reason = reason
    return response


def _make_refresh_result(
    authenticated: bool = True,
    user: MagicMock | None = None,
    sealed_session: str | None = None,
    reason: str | None = None,
) -> MagicMock:
    """Create a fake refresh result carrying exactly the attributes the production code reads."""

    class _RefreshResult:
        pass

    result = _RefreshResult()
    result.authenticated = authenticated  # type: ignore[attr-defined]  # fake attaches result fields dynamically
    result.user = user  # type: ignore[attr-defined]  # fake attaches result fields dynamically
    result.sealed_session = sealed_session  # type: ignore[attr-defined]  # fake attaches result fields dynamically
    result.reason = reason  # type: ignore[attr-defined]  # fake attaches result fields dynamically
    return result  # type: ignore[return-value]  # helper is typed MagicMock but returns the richer fake


def _make_session(
    auth_response: MagicMock,
    refresh_result: MagicMock | None = None,
    refresh_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock sealed session object."""
    session = MagicMock()
    session.authenticate.return_value = auth_response
    if refresh_side_effect:
        session.refresh = AsyncMock(side_effect=refresh_side_effect)
    elif refresh_result is not None:
        session.refresh = AsyncMock(return_value=refresh_result)
    else:
        session.refresh = AsyncMock()
    return session


def _make_workos_client(session: MagicMock) -> MagicMock:
    """Create a mock AsyncWorkOSClient."""
    client = MagicMock()
    client.user_management.load_sealed_session = AsyncMock(return_value=session)
    return client


def _db_user_doc(
    email: str = "alice@example.com",
    user_id: str = "64abc123def4567890abcdef",
    name: str = "Alice Smith",
    timezone: str = "America/New_York",
) -> dict[str, Any]:
    """Create a mock MongoDB user document."""
    return {
        "_id": user_id,
        "email": email,
        "name": name,
        "timezone": timezone,
        "picture": "https://example.com/avatar.png",
    }


# ---------------------------------------------------------------------------
# authenticate_workos_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAuthenticateWorkosSession:
    """Tests for authenticate_workos_session."""

    # -- Successful authentication (auth_response.authenticated=True) ------

    async def test_successful_auth_returns_user_info(self) -> None:
        """When authenticate() succeeds, return user_info dict with no new session token."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = _db_user_doc()

        with patch(_PATCH_USER_REPO) as mock_col, patch(_PATCH_LOG):
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            user_info, new_session = await authenticate_workos_session(
                session_token="sealed_tok", workos_client=client
            )

        assert user_info.auth_provider == "workos"
        assert user_info.email == "alice@example.com"
        assert user_info.name == "Alice Smith"
        assert user_info.user_id == str(db_doc["_id"])
        assert new_session is None

    async def test_successful_auth_user_info_structure(self) -> None:
        """Verify the full structure of user_info: auth_provider, user_id, email, plus db fields."""
        workos_user = _make_workos_user(email="bob@test.io")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = _db_user_doc(
            email="bob@test.io",
            user_id="aabbccdd11223344",
            name="Bob Jones",
            timezone="Europe/London",
        )

        with patch(_PATCH_USER_REPO) as mock_col, patch(_PATCH_LOG):
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            user_info, _ = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info.auth_provider == "workos"
        assert user_info.user_id == "aabbccdd11223344"
        assert user_info.email == "bob@test.io"
        assert user_info.name == "Bob Jones"
        assert user_info.timezone == "Europe/London"
        assert user_info.picture == "https://example.com/avatar.png"

    # -- Auth fails, refresh succeeds --------------------------------------

    async def test_auth_fails_refresh_succeeds(self) -> None:
        """When authenticate() fails but refresh() succeeds, return user_info with new session."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=False, reason="expired")
        refresh_result = _make_refresh_result(
            authenticated=True,
            user=workos_user,
            sealed_session="new_sealed_session_token",
        )
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)
        db_doc = _db_user_doc()

        with (
            patch(_PATCH_USER_REPO) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass_32chars_long_enough"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            user_info, new_session = await authenticate_workos_session(
                session_token="old_tok", workos_client=client
            )

        assert user_info.auth_provider == "workos"
        assert user_info.email == "alice@example.com"
        assert new_session == "new_sealed_session_token"

    # -- Auth fails, refresh also fails ------------------------------------

    async def test_auth_fails_refresh_not_authenticated(self) -> None:
        """When both authenticate() and refresh() fail, return ({}, None)."""
        auth_response = _make_auth_response(authenticated=False, reason="expired")
        refresh_result = _make_refresh_result(authenticated=False, reason="refresh_token_expired")
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG), patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session is None

    # -- Auth fails, refresh raises exception ------------------------------

    async def test_auth_fails_refresh_raises_exception(self) -> None:
        """When refresh() raises an exception, return ({}, None)."""
        auth_response = _make_auth_response(authenticated=False)
        session = _make_session(auth_response, refresh_side_effect=RuntimeError("network error"))
        client = _make_workos_client(session)

        with patch(_PATCH_LOG), patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session is None

    # -- Refresh result has no __dict__ ------------------------------------

    # -- workos_user is None after auth ------------------------------------

    async def test_workos_user_none_after_successful_auth(self) -> None:
        """When auth succeeds but user is None, return ({}, new_session=None)."""
        auth_response = _make_auth_response(authenticated=True, user=None)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log:
            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session is None
        mock_log.error.assert_called_once_with("[AGENT] Invalid user data from WorkOS")

    async def test_workos_user_none_after_refresh(self) -> None:
        """When refresh succeeds but user is None in refresh dict, return ({}, new_session)."""
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(
            authenticated=True,
            user=None,
            sealed_session="refreshed_session_tok",
        )
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session == "refreshed_session_tok"
        mock_log.error.assert_any_call(
            "[AGENT] Refresh successful but no user data in refresh result"
        )

    # -- User not found in database ----------------------------------------

    async def test_user_not_found_in_database(self) -> None:
        """When user authenticates but is not in MongoDB, return ({}, new_session)."""
        workos_user = _make_workos_user(email="unknown@example.com")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_USER_REPO) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.get_by_email = AsyncMock(return_value=None)

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session is None
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs["user_email"] == "unknown@example.com"

    async def test_user_not_found_after_refresh(self) -> None:
        """When user refreshes but is not in MongoDB, return ({}, new_session)."""
        workos_user = _make_workos_user(email="ghost@example.com")
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(
            authenticated=True,
            user=workos_user,
            sealed_session="refreshed_tok",
        )
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with (
            patch(_PATCH_USER_REPO) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.get_by_email = AsyncMock(return_value=None)

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session == "refreshed_tok"

    # -- Overall exception -------------------------------------------------

    async def test_overall_exception_returns_empty(self) -> None:
        """When load_sealed_session raises, return ({}, None)."""
        client = MagicMock()
        client.user_management.load_sealed_session = AsyncMock(
            side_effect=Exception("connection refused")
        )

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session is None
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["error"] == "connection refused"

    async def test_exception_during_session_authenticate(self) -> None:
        """When session.authenticate() raises, caught by outer try/except -> ({}, None)."""
        session = MagicMock()
        session.authenticate.side_effect = RuntimeError("corrupt session")
        client = MagicMock()
        client.user_management.load_sealed_session = AsyncMock(return_value=session)

        with patch(_PATCH_LOG), patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session is None

    # -- Database query exception ------------------------------------------

    async def test_db_exception_returns_empty_with_new_session(self) -> None:
        """When users_collection.find_one raises, return ({}, new_session)."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_USER_REPO) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.get_by_email = AsyncMock(side_effect=Exception("MongoDB connection lost"))

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session is None
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["error"] == "MongoDB connection lost"

    async def test_db_exception_after_refresh_preserves_new_session(self) -> None:
        """When DB query fails after a refresh, return ({}, new_session) preserving the refreshed token."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(
            authenticated=True,
            user=workos_user,
            sealed_session="fresh_tok",
        )
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with (
            patch(_PATCH_USER_REPO) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.get_by_email = AsyncMock(side_effect=Exception("timeout"))

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session == "fresh_tok"

    # -- Provided workos_client vs creating new one ------------------------

    async def test_uses_provided_workos_client(self) -> None:
        """When a workos_client is provided, it is used instead of creating a new one."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = _db_user_doc()

        with (
            patch(_PATCH_USER_REPO) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_WORKOS_CLIENT) as mock_cls,
        ):
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_cls.assert_not_called()
        client.user_management.load_sealed_session.assert_awaited_once()

    async def test_creates_workos_client_when_none_provided(self) -> None:
        """When no workos_client is provided, create one with settings credentials."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        db_doc = _db_user_doc()
        mock_client = _make_workos_client(session)

        with (
            patch(_PATCH_USER_REPO) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_WORKOS_CLIENT, return_value=mock_client) as mock_cls,
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_API_KEY = "sk_test_key"  # pragma: allowlist secret
            mock_settings.WORKOS_CLIENT_ID = "client_id_123"  # pragma: allowlist secret
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            await authenticate_workos_session(session_token="tok", workos_client=None)

        mock_cls.assert_called_once_with(
            api_key="sk_test_key",  # pragma: allowlist secret
            client_id="client_id_123",
        )

    # -- Verify correct MongoDB query --------------------------------------

    async def test_queries_mongodb_with_correct_email(self) -> None:
        """Verify that users_collection.find_one is called with the user's email."""
        workos_user = _make_workos_user(email="query@test.com")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_USER_REPO) as mock_col, patch(_PATCH_LOG):
            mock_col.get_by_email = AsyncMock(return_value=None)

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_col.get_by_email.assert_awaited_once_with("query@test.com")

    # -- user_info merges db data with auth_provider and user_id -----------

    async def test_user_info_carries_the_declared_db_fields_only(self) -> None:
        """An undeclared historical key on the row does not reach user_info (closed model)."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = {
            "_id": "mongo_id_abc",
            "email": "alice@example.com",
            "name": "Alice Smith",
            "timezone": "UTC",
            "picture": None,
            "custom_field": "custom_value",
            "hil_preferences": {"theme": "dark"},
        }

        with patch(_PATCH_USER_REPO) as mock_col, patch(_PATCH_LOG):
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            user_info, _ = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is not None
        assert user_info.hil_preferences == {"theme": "dark"}
        assert user_info.user_id == "mongo_id_abc"
        assert user_info.picture is None
        assert "custom_field" not in user_info.model_dump()

    # -- Refresh result edge cases -----------------------------------------

    async def test_refresh_result_without_a_user(self) -> None:
        """A refresh that authenticated but carries no user yields (None, new_session)."""
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(
            authenticated=True, user=None, sealed_session="some_session"
        )

        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info is None
        assert new_session == "some_session"
        mock_log.error.assert_called_once_with(
            "[AGENT] Refresh successful but no user data in refresh result"
        )

    async def test_refresh_result_without_a_sealed_session(self) -> None:
        """A refresh carrying a user but no sealed_session yields new_session None."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(authenticated=True, user=workos_user)

        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)
        db_doc = _db_user_doc()

        with (
            patch(_PATCH_USER_REPO) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info.email == "alice@example.com"
        assert new_session is None

    # -- Verify logging calls ----------------------------------------------

    async def test_log_set_called_with_auth_context(self) -> None:
        """Verify log.set is called with auth_provider and user_email."""
        workos_user = _make_workos_user(email="logged@example.com")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = _db_user_doc(email="logged@example.com")

        with patch(_PATCH_USER_REPO) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_log.set.assert_called_once_with(
            auth_provider="workos", user_email="logged@example.com"
        )

    async def test_refresh_failure_logs_warning_with_reason(self) -> None:
        """When refresh fails, log.warning includes the reason."""
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(authenticated=False, reason="session_revoked")
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs["reason"] == "session_revoked"

    async def test_refresh_exception_logs_error(self) -> None:
        """When refresh raises, log.error includes the exception message."""
        auth_response = _make_auth_response(authenticated=False)
        session = _make_session(auth_response, refresh_side_effect=ValueError("bad token format"))
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["error"] == "bad token format"
        assert mock_log.error.call_args.kwargs["error_type"] == "ValueError"

    # -- Arguments forwarded correctly -------------------------------------

    async def test_cookie_password_forwarded_to_refresh(self) -> None:
        """Verify that settings.WORKOS_COOKIE_PASSWORD is passed to session.refresh()."""
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(authenticated=False, reason="expired")
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG), patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "my_secret_cookie_pw"  # NOSONAR  # pragma: allowlist secret
            )

            await authenticate_workos_session(session_token="tok", workos_client=client)

        session.refresh.assert_awaited_once_with(
            cookie_password="my_secret_cookie_pw"  # pragma: allowlist secret
        )  # NOSONAR

    async def test_sealed_session_and_cookie_password_forwarded(self) -> None:
        """Verify correct args passed to load_sealed_session."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = _db_user_doc()

        with (
            patch(_PATCH_USER_REPO) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = "pw_123"  # NOSONAR  # pragma: allowlist secret
            mock_col.get_by_email = AsyncMock(return_value=_as_user(db_doc))

            await authenticate_workos_session(session_token="my_sealed_token", workos_client=client)

        client.user_management.load_sealed_session.assert_awaited_once_with(
            sealed_session="my_sealed_token",
            cookie_password="pw_123",  # pragma: allowlist secret
        )


# ---------------------------------------------------------------------------
# build_user_context / resolve_bot_user / load_user_context
# ---------------------------------------------------------------------------


_STAMP = datetime(2024, 5, 1, tzinfo=UTC)

# One distinct non-default sample per declared field type, matched by the
# first type name found in the field's annotation (order matters: the nested
# models are named before the primitives their annotations also mention).
_SAMPLE_BY_TYPE: tuple[tuple[str, object], ...] = (
    ("OnboardingSubdocument", OnboardingSubdocument(focus="ops")),
    ("FirstStepsState", FirstStepsState(collapsed=True, collapsed_at=_STAMP)),
    ("FeatureFlag", {FeatureFlag.BROWSER_OBSCURA: True}),
    ("datetime", _STAMP),
    ("bool", True),
    ("int", 3),
    ("list", ["item"]),
    ("dict", {"k": "v"}),
)


def _sample_values() -> dict[str, object]:
    """Return a non-default value for every declared UserDocument field but id."""
    return {
        name: next(
            (value for type_name, value in _SAMPLE_BY_TYPE if type_name in str(field.annotation)),
            f"{name}-value",
        )
        for name, field in UserDocument.model_fields.items()
        if name != "id"
    }


def _every_field_document() -> tuple[UserDocument, dict[str, object]]:
    """Return a document with a distinct non-default value in every declared field."""
    values = _sample_values()
    return UserDocument(id="64abc123def4567890abcdef", **values), values


class TestBuildUserContext:
    def test_every_document_field_is_copied_verbatim(self) -> None:
        doc, values = _every_field_document()

        user = build_user_context(doc, auth_provider="workos")

        assert user.user_id == "64abc123def4567890abcdef"
        assert user.auth_provider == "workos"
        for name, value in values.items():
            assert getattr(user, name) == value, name

    def test_a_plain_session_sets_no_path_flag(self) -> None:
        doc, _ = _every_field_document()

        user = build_user_context(doc, auth_provider="workos")

        assert (user.impersonated, user.bot_authenticated, user.dev_bypass) == (False, False, False)

    @pytest.mark.parametrize("flag", ["impersonated", "bot_authenticated", "dev_bypass"])
    def test_each_path_flag_is_carried_alone(self, flag: str) -> None:
        doc, _ = _every_field_document()

        user = build_user_context(doc, auth_provider="workos", **{flag: True})

        flags = {
            "impersonated": user.impersonated,
            "bot_authenticated": user.bot_authenticated,
            "dev_bypass": user.dev_bypass,
        }
        assert flags == {name: name == flag for name in flags}


@pytest.mark.asyncio
class TestResolveBotUser:
    async def test_a_linked_account_is_a_bot_authenticated_context(self) -> None:
        doc, _ = _every_field_document()
        with patch(_PATCH_USER_REPO) as repo:
            repo.get_by_platform_id = AsyncMock(return_value=doc)

            user = await resolve_bot_user("telegram", "tg-1")

        repo.get_by_platform_id.assert_awaited_once_with("telegram", "tg-1")
        assert user is not None
        assert user.user_id == doc.id
        assert user.auth_provider == "bot:telegram"
        assert (user.bot_authenticated, user.impersonated, user.dev_bypass) == (True, False, False)

    async def test_an_unlinked_account_is_none(self) -> None:
        with patch(_PATCH_USER_REPO) as repo:
            repo.get_by_platform_id = AsyncMock(return_value=None)

            assert await resolve_bot_user("telegram", "tg-1") is None


@pytest.mark.asyncio
class TestResolveDevBypassUser:
    """Precedence: X-Dev-User header, then the dev_bypass_user cookie, then the configured default."""

    @staticmethod
    async def _resolve(
        headers: dict[str, str], cookies: dict[str, str], default: str | None
    ) -> str:
        doc, _ = _every_field_document()
        raw_headers = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
        if cookies:
            cookie = "; ".join(f"{name}={value}" for name, value in cookies.items())
            raw_headers.append((b"cookie", cookie.encode()))
        connection = Request({"type": "http", "headers": raw_headers})
        with patch(_PATCH_SETTINGS) as mock_settings, patch(_PATCH_USER_REPO) as repo:
            mock_settings.DEV_AUTH_BYPASS_EMAIL = default
            repo.get_by_email = AsyncMock(return_value=doc)

            email, user = await resolve_dev_bypass_user(connection)

        repo.get_by_email.assert_awaited_once_with(email)
        assert user is doc
        return email

    async def test_the_header_outranks_the_cookie_and_the_default(self) -> None:
        email = await self._resolve(
            {DEV_USER_HEADER: "header@example.com"},
            {"dev_bypass_user": "cookie@example.com"},
            "default@example.com",
        )

        assert email == "header@example.com"

    async def test_the_cookie_outranks_the_default(self) -> None:
        email = await self._resolve({}, {"dev_bypass_user": "cookie@example.com"}, "default@e.com")

        assert email == "cookie@example.com"

    async def test_the_configured_default_is_the_last_resort(self) -> None:
        email = await self._resolve({}, {}, "default@example.com")

        assert email == "default@example.com"

    async def test_nothing_configured_resolves_to_the_empty_email(self) -> None:
        assert await self._resolve({}, {}, None) == ""


@pytest.mark.asyncio
class TestLoadUserContext:
    async def test_a_known_user_is_a_context_no_auth_path_produced(self) -> None:
        doc, values = _every_field_document()
        with patch(_PATCH_USER_REPO) as repo:
            repo.get = AsyncMock(return_value=doc)

            user = await load_user_context(doc.id)

        repo.get.assert_awaited_once_with(doc.id)
        assert user is not None
        assert user.user_id == doc.id
        assert user.auth_provider is None
        assert user.timezone == values["timezone"]
        assert (user.impersonated, user.bot_authenticated, user.dev_bypass) == (False, False, False)

    async def test_an_unknown_user_is_none(self) -> None:
        with patch(_PATCH_USER_REPO) as repo:
            repo.get = AsyncMock(return_value=None)

            assert await load_user_context("missing") is None


@pytest.mark.asyncio
class TestAuthenticateWorkosSessionFailureLogs:
    async def test_a_refresh_that_fails_logs_its_reason(self) -> None:
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(authenticated=False, reason="invalid_grant")
        client = _make_workos_client(_make_session(auth_response, refresh_result=refresh_result))

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS):
            result = await authenticate_workos_session(session_token="tok", workos_client=client)

        assert result == (None, None)
        mock_log.warning.assert_called_once_with(
            "[AGENT] Authentication failed even after refresh with reason",
            reason="invalid_grant",
        )

    async def test_a_user_lookup_error_is_logged_and_keeps_the_rotated_session(self) -> None:
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(
            authenticated=True, user=_make_workos_user(), sealed_session="rotated"
        )
        client = _make_workos_client(_make_session(auth_response, refresh_result=refresh_result))

        with patch(_PATCH_USER_REPO) as repo, patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS):
            repo.get_by_email = AsyncMock(side_effect=RuntimeError("mongo down"))

            result = await authenticate_workos_session(session_token="tok", workos_client=client)

        assert result == (None, "rotated")
        mock_log.error.assert_called_once_with(
            "[AGENT] Error processing user data",
            error="mongo down",
            error_type="RuntimeError",
        )

    async def test_a_workos_failure_is_logged_with_its_type(self) -> None:
        client = MagicMock()
        client.user_management.load_sealed_session = AsyncMock(side_effect=ValueError("bad seal"))

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS):
            result = await authenticate_workos_session(session_token="tok", workos_client=client)

        assert result == (None, None)
        mock_log.error.assert_called_once_with(
            "[AGENT] Error in authenticate_workos_session",
            error="bad seal",
            error_type="ValueError",
        )
