"""Unit tests for app.utils.auth_utils — WorkOS session authentication."""

import builtins
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.auth_utils import authenticate_workos_session

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_PATCH_SETTINGS = "app.utils.auth_utils.settings"
_PATCH_USERS_COLLECTION = "app.utils.auth_utils.users_collection"
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
    user: Optional[MagicMock] = None,
    reason: Optional[str] = None,
) -> MagicMock:
    """Create a mock authentication response."""
    response = MagicMock()
    response.authenticated = authenticated
    response.user = user
    response.reason = reason
    return response


def _make_refresh_result(
    authenticated: bool = True,
    user: Optional[MagicMock] = None,
    sealed_session: Optional[str] = None,
    reason: Optional[str] = None,
) -> MagicMock:
    """Create a mock refresh result with a controlled __dict__.

    MagicMock stores its attributes in __dict__, so setting mock attributes
    before overriding __dict__ is lost.  Instead we use a SimpleNamespace-like
    approach: build a plain object whose __dict__ contains exactly what the
    production code reads via ``refresh_dict = refresh_result.__dict__``.
    """

    class _RefreshResult:
        pass

    result = _RefreshResult()
    result.authenticated = authenticated  # type: ignore[attr-defined]
    result.user = user  # type: ignore[attr-defined]
    result.sealed_session = sealed_session  # type: ignore[attr-defined]
    result.reason = reason  # type: ignore[attr-defined]
    return result  # type: ignore[return-value]


def _make_session(
    auth_response: MagicMock,
    refresh_result: Optional[MagicMock] = None,
    refresh_side_effect: Optional[Exception] = None,
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
) -> Dict[str, Any]:
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
@pytest.mark.unit
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

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG):
            mock_col.find_one = AsyncMock(return_value=db_doc)

            user_info, new_session = await authenticate_workos_session(
                session_token="sealed_tok", workos_client=client
            )

        assert user_info["auth_provider"] == "workos"
        assert user_info["email"] == "alice@example.com"
        assert user_info["name"] == "Alice Smith"
        assert user_info["user_id"] == str(db_doc["_id"])
        assert new_session is None
        assert "_id" not in user_info

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

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG):
            mock_col.find_one = AsyncMock(return_value=db_doc)

            user_info, _ = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info["auth_provider"] == "workos"
        assert user_info["user_id"] == "aabbccdd11223344"
        assert user_info["email"] == "bob@test.io"
        assert user_info["name"] == "Bob Jones"
        assert user_info["timezone"] == "Europe/London"
        assert user_info["picture"] == "https://example.com/avatar.png"
        assert "_id" not in user_info

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
            patch(_PATCH_USERS_COLLECTION) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass_32chars_long_enough"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.find_one = AsyncMock(return_value=db_doc)

            user_info, new_session = await authenticate_workos_session(
                session_token="old_tok", workos_client=client
            )

        assert user_info["auth_provider"] == "workos"
        assert user_info["email"] == "alice@example.com"
        assert new_session == "new_sealed_session_token"
        assert "_id" not in user_info

    # -- Auth fails, refresh also fails ------------------------------------

    async def test_auth_fails_refresh_not_authenticated(self) -> None:
        """When both authenticate() and refresh() fail, return ({}, None)."""
        auth_response = _make_auth_response(authenticated=False, reason="expired")
        refresh_result = _make_refresh_result(
            authenticated=False, reason="refresh_token_expired"
        )
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG), patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info == {}
        assert new_session is None

    # -- Auth fails, refresh raises exception ------------------------------

    async def test_auth_fails_refresh_raises_exception(self) -> None:
        """When refresh() raises an exception, return ({}, None)."""
        auth_response = _make_auth_response(authenticated=False)
        session = _make_session(
            auth_response, refresh_side_effect=RuntimeError("network error")
        )
        client = _make_workos_client(session)

        with patch(_PATCH_LOG), patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info == {}
        assert new_session is None

    # -- Refresh result has no __dict__ ------------------------------------

    async def test_refresh_result_no_dict_returns_empty(self) -> None:
        """When refresh result has no __dict__ (hasattr returns False), return ({}, None).

        Python objects inherently have __dict__, so we patch builtins.hasattr
        to return False specifically for the refresh_result object.
        """
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = MagicMock()
        refresh_result.authenticated = True

        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        original_hasattr = builtins.hasattr

        def patched_hasattr(obj: Any, name: str) -> bool:
            if obj is refresh_result and name == "__dict__":
                return False
            return original_hasattr(obj, name)

        with (
            patch(_PATCH_LOG) as mock_log,
            patch(_PATCH_SETTINGS) as mock_settings,
            patch.object(builtins, "hasattr", side_effect=patched_hasattr),
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once_with(
            "Refresh result doesn't have expected structure"
        )

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

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once_with("Invalid user data from WorkOS")

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

        assert user_info == {}
        assert new_session == "refreshed_session_tok"
        mock_log.error.assert_any_call(
            "Refresh successful but no user data in refresh result"
        )

    # -- User not found in database ----------------------------------------

    async def test_user_not_found_in_database(self) -> None:
        """When user authenticates but is not in MongoDB, return ({}, new_session)."""
        workos_user = _make_workos_user(email="unknown@example.com")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.find_one = AsyncMock(return_value=None)

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info == {}
        assert new_session is None
        mock_log.warning.assert_called_once()
        assert "unknown@example.com" in mock_log.warning.call_args[0][0]

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
            patch(_PATCH_USERS_COLLECTION) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.find_one = AsyncMock(return_value=None)

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info == {}
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

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once()
        assert "connection refused" in mock_log.error.call_args[0][0]

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

        assert user_info == {}
        assert new_session is None

    # -- Database query exception ------------------------------------------

    async def test_db_exception_returns_empty_with_new_session(self) -> None:
        """When users_collection.find_one raises, return ({}, new_session)."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.find_one = AsyncMock(
                side_effect=Exception("MongoDB connection lost")
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once()
        assert "MongoDB connection lost" in mock_log.error.call_args[0][0]

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
            patch(_PATCH_USERS_COLLECTION) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.find_one = AsyncMock(side_effect=Exception("timeout"))

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info == {}
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
            patch(_PATCH_USERS_COLLECTION) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_WORKOS_CLIENT) as mock_cls,
        ):
            mock_col.find_one = AsyncMock(return_value=db_doc)

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
            patch(_PATCH_USERS_COLLECTION) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_WORKOS_CLIENT, return_value=mock_client) as mock_cls,
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_API_KEY = "sk_test_key"  # pragma: allowlist secret
            mock_settings.WORKOS_CLIENT_ID = "client_id_123"  # pragma: allowlist secret
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.find_one = AsyncMock(return_value=db_doc)

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

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG):
            mock_col.find_one = AsyncMock(return_value=None)

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_col.find_one.assert_awaited_once_with({"email": "query@test.com"})

    # -- user_info merges db data with auth_provider and user_id -----------

    async def test_user_info_includes_all_db_fields(self) -> None:
        """All fields from the db document are merged into user_info (except _id)."""
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
            "preferences": {"theme": "dark"},
        }

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG):
            mock_col.find_one = AsyncMock(return_value=db_doc)

            user_info, _ = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info["custom_field"] == "custom_value"
        assert user_info["preferences"] == {"theme": "dark"}
        assert user_info["user_id"] == "mongo_id_abc"
        assert "_id" not in user_info

    # -- Refresh result __dict__ edge cases --------------------------------

    async def test_refresh_dict_missing_user_key(self) -> None:
        """When refresh __dict__ has no 'user' key, return ({}, new_session)."""
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = MagicMock()
        refresh_result.authenticated = True
        refresh_result.__dict__ = {
            "authenticated": True,
            "sealed_session": "some_session",
        }

        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info == {}
        assert new_session == "some_session"
        mock_log.error.assert_called_once_with(
            "Refresh successful but no user data in refresh result"
        )

    async def test_refresh_dict_missing_sealed_session(self) -> None:
        """When refresh __dict__ has user but no sealed_session, new_session is None."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = MagicMock()
        refresh_result.authenticated = True
        refresh_result.__dict__ = {
            "authenticated": True,
            "user": workos_user,
        }

        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)
        db_doc = _db_user_doc()

        with (
            patch(_PATCH_USERS_COLLECTION) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.find_one = AsyncMock(return_value=db_doc)

            user_info, new_session = await authenticate_workos_session(
                session_token="tok", workos_client=client
            )

        assert user_info["email"] == "alice@example.com"
        assert new_session is None

    # -- Verify logging calls ----------------------------------------------

    async def test_log_set_called_with_auth_context(self) -> None:
        """Verify log.set is called with auth_provider and user_email."""
        workos_user = _make_workos_user(email="logged@example.com")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = _db_user_doc(email="logged@example.com")

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.find_one = AsyncMock(return_value=db_doc)

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_log.set.assert_called_once_with(
            auth_provider="workos", user_email="logged@example.com"
        )

    async def test_refresh_failure_logs_warning_with_reason(self) -> None:
        """When refresh fails, log.warning includes the reason."""
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(
            authenticated=False, reason="session_revoked"
        )
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_log.warning.assert_called_once()
        assert "session_revoked" in mock_log.warning.call_args[0][0]

    async def test_refresh_exception_logs_error(self) -> None:
        """When refresh raises, log.error includes the exception message."""
        auth_response = _make_auth_response(authenticated=False)
        session = _make_session(
            auth_response, refresh_side_effect=ValueError("bad token format")
        )
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            await authenticate_workos_session(session_token="tok", workos_client=client)

        mock_log.error.assert_called_once()
        assert "bad token format" in mock_log.error.call_args[0][0]

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
            patch(_PATCH_USERS_COLLECTION) as mock_col,
            patch(_PATCH_LOG),
            patch(_PATCH_SETTINGS) as mock_settings,
        ):
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "pw_123"  # NOSONAR  # pragma: allowlist secret
            )
            mock_col.find_one = AsyncMock(return_value=db_doc)

            await authenticate_workos_session(
                session_token="my_sealed_token", workos_client=client
            )

        client.user_management.load_sealed_session.assert_awaited_once_with(
            sealed_session="my_sealed_token",
            cookie_password="pw_123",  # pragma: allowlist secret
        )
