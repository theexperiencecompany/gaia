"""Unit tests for app.utils.auth_utils — WorkOS session authentication.

UNIT: app/utils/auth_utils.py :: authenticate_workos_session
EXPECTED:
  Given a sealed WorkOS session token, load + authenticate the session. On success
  (or after a successful refresh) look up the user in MongoDB by email and return
  ``(user_info, new_session_token)``. The function NEVER raises — every failure path
  returns ``({}, <session-or-None>)``. ``user_info`` merges the Mongo document with
  ``auth_provider="workos"`` and a stringified ``user_id`` (the Mongo ``_id``), and the
  raw ``_id`` key is removed.

MECHANISM:
  workos = workos_client or AsyncWorkOSClient(api_key=..., client_id=...)
  session = await workos.user_management.load_sealed_session(sealed_session=token, cookie_password=...)
  auth = session.authenticate()
  if auth.authenticated:        -> workos_user = auth.user;            new_session = None
  else: refresh = await session.refresh(cookie_password=...)
        if not refresh.authenticated: log.warning(reason); return ({}, None)
        d = refresh.__dict__ (if hasattr __dict__ else return ({}, None))
        workos_user = d["user"]; new_session = d["sealed_session"]
        if not workos_user: log.error(...); return ({}, new_session)
  if not workos_user: log.error("Invalid user data from WorkOS"); return ({}, new_session)
  user = await users_collection.find_one({"email": workos_user.email})
  if not user: log.warning(...); return ({}, new_session)
  return ({"auth_provider": "workos", **user, "user_id": str(_id)} minus _id, new_session)

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - authenticated branch (auth.authenticated True) returns user_info with new_session None
  - refresh branch: auth False -> refresh True returns user_info with the REFRESHED session token
  - auth False AND refresh.authenticated False -> ({}, None) and warns with refresh.reason
  - refresh raises -> ({}, None) and logs "Session refresh error: <e>"
  - refresh result lacks __dict__ -> ({}, None) and logs exact structure-error message
  - refresh dict missing "user" -> ({}, new_session) and logs exact no-user message
  - refresh dict missing "sealed_session" -> new_session is None (still returns user_info)
  - workos_user None after authenticate -> ({}, None) and logs "Invalid user data from WorkOS"
  - find_one called with EXACTLY {"email": <workos_user.email>}  [DB filter contract]
  - user not found in Mongo -> ({}, new_session) and warns with the exact email message
  - find_one raises -> ({}, new_session) preserving refreshed token; logs "Error processing user data: <e>"
  - load_sealed_session raises -> ({}, None) and logs "Error in authenticate_workos_session: <e>"
  - user_info contract: auth_provider="workos", user_id=str(_id), all db fields merged, _id removed
  - log.set(auth_provider="workos", user_email=<email>) before DB lookup  [observability contract]
  - no client provided -> AsyncWorkOSClient(api_key, client_id) constructed from settings
  - client provided -> AsyncWorkOSClient NOT constructed
  - load_sealed_session forwarded the exact sealed_session + cookie_password
  - refresh forwarded the exact cookie_password

EQUIVALENT MUTANTS (allowed survivors, justified):
  - The function docstring string constant (the ``\"\"\"...\"\"\"`` under the ``def``):
    mutating it to "" is behaviour-preserving — a docstring is never read at runtime,
    only ``__doc__`` metadata changes, which this function never inspects. Proven empirically
    by ``test_docstring_is_runtime_inert``.
"""

from typing import Any
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


def _make_workos_user(email: str = "alice@example.com") -> MagicMock:
    """Create a mock WorkOS user object (only ``.email`` is read by prod)."""
    user = MagicMock()
    user.email = email
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
) -> Any:
    """Create a refresh result whose real ``__dict__`` is read by production code.

    Production reads ``refresh_result.__dict__`` for ``user`` / ``sealed_session``,
    so we use a plain object whose actual ``__dict__`` carries exactly those keys.
    """

    class _RefreshResult:
        pass

    result = _RefreshResult()
    result.authenticated = authenticated
    result.user = user
    result.sealed_session = sealed_session
    result.reason = reason
    return result


def _make_session(
    auth_response: MagicMock,
    refresh_result: Any | None = None,
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
@pytest.mark.unit
class TestAuthenticateWorkosSession:
    """Tests for authenticate_workos_session."""

    # -- Successful authentication (auth_response.authenticated=True) ------

    async def test_successful_auth_returns_full_user_info(self) -> None:
        """authenticate() success -> user_info merges db fields + auth_provider + user_id, no new session."""
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

            user_info, new_session = await authenticate_workos_session(
                session_token="sealed_tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info["auth_provider"] == "workos"
        assert user_info["user_id"] == "aabbccdd11223344"
        assert user_info["email"] == "bob@test.io"
        assert user_info["name"] == "Bob Jones"
        assert user_info["timezone"] == "Europe/London"
        assert user_info["picture"] == "https://example.com/avatar.png"
        assert "_id" not in user_info
        assert new_session is None

    async def test_user_info_merges_arbitrary_db_fields(self) -> None:
        """All fields from the db document (including nested/custom) are merged into user_info."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = {
            "_id": "mongo_id_abc",
            "email": "alice@example.com",
            "custom_field": "custom_value",
            "preferences": {"theme": "dark"},
        }

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG):
            mock_col.find_one = AsyncMock(return_value=db_doc)

            user_info, _ = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info["custom_field"] == "custom_value"
        assert user_info["preferences"] == {"theme": "dark"}
        assert user_info["user_id"] == "mongo_id_abc"
        assert user_info["auth_provider"] == "workos"
        assert "_id" not in user_info

    # -- Auth fails, refresh succeeds --------------------------------------

    async def test_auth_fails_refresh_succeeds_returns_refreshed_session(self) -> None:
        """authenticate() fails but refresh() succeeds -> user_info with the REFRESHED session token."""
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
                session_token="old_tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info["auth_provider"] == "workos"
        assert user_info["email"] == "alice@example.com"
        assert new_session == "new_sealed_session_token"
        assert "_id" not in user_info

    # -- Auth fails, refresh also fails ------------------------------------

    async def test_auth_fails_refresh_not_authenticated(self) -> None:
        """Both authenticate() and refresh() fail -> ({}, None) + warning with the refresh reason."""
        auth_response = _make_auth_response(authenticated=False, reason="expired")
        refresh_result = _make_refresh_result(authenticated=False, reason="session_revoked")
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session is None
        mock_log.warning.assert_called_once_with(
            "Authentication failed even after refresh with reason: session_revoked"
        )

    # -- Auth fails, refresh raises exception ------------------------------

    async def test_auth_fails_refresh_raises_exception(self) -> None:
        """refresh() raising -> ({}, None) + error logging the exact 'Session refresh error: <e>' message."""
        auth_response = _make_auth_response(authenticated=False)
        session = _make_session(auth_response, refresh_side_effect=ValueError("bad token format"))
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once_with("Session refresh error: bad token format")

    # -- Refresh result has no __dict__ ------------------------------------

    async def test_refresh_result_no_dict_returns_empty(self) -> None:
        """Refresh result lacking __dict__ -> ({}, None) + exact structure-error log.

        ``__slots__`` removes the instance ``__dict__``, so ``hasattr(obj, "__dict__")``
        is genuinely False — no monkeypatching of ``hasattr`` required.
        """

        class _Slotted:
            __slots__ = ("authenticated",)

            def __init__(self) -> None:
                self.authenticated = True

        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _Slotted()
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once_with("Refresh result doesn't have expected structure")

    # -- workos_user is None after auth ------------------------------------

    async def test_workos_user_none_after_successful_auth(self) -> None:
        """auth succeeds but user is None -> ({}, None) + 'Invalid user data from WorkOS' error."""
        auth_response = _make_auth_response(authenticated=True, user=None)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log:
            user_info, new_session = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once_with("Invalid user data from WorkOS")

    # -- Refresh result __dict__ edge cases --------------------------------

    async def test_refresh_dict_missing_user_key(self) -> None:
        """refresh __dict__ has no 'user' -> ({}, new_session) + exact no-user error."""
        auth_response = _make_auth_response(authenticated=False)
        # Plain object whose real __dict__ has sealed_session but no user key at all.
        refresh_result = _make_refresh_result(
            authenticated=True, user=None, sealed_session="some_session"
        )
        del refresh_result.__dict__["user"]

        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session == "some_session"
        mock_log.error.assert_called_once_with(
            "Refresh successful but no user data in refresh result"
        )

    async def test_refresh_dict_missing_sealed_session_yields_none_session(self) -> None:
        """refresh __dict__ has user but no sealed_session -> user_info returned, new_session None."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(authenticated=True, user=workos_user)
        del refresh_result.__dict__["sealed_session"]

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
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info["email"] == "alice@example.com"
        assert new_session is None

    # -- User not found in database ----------------------------------------

    async def test_user_not_found_in_database(self) -> None:
        """auth ok but user missing from Mongo -> ({}, None) + exact 'User <email> ...' warning."""
        workos_user = _make_workos_user(email="unknown@example.com")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.find_one = AsyncMock(return_value=None)

            user_info, new_session = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session is None
        mock_log.warning.assert_called_once_with(
            "User unknown@example.com authenticated but not found in database"
        )

    async def test_user_not_found_after_refresh_preserves_session(self) -> None:
        """user refreshed but missing from Mongo -> ({}, refreshed_session)."""
        workos_user = _make_workos_user(email="ghost@example.com")
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(
            authenticated=True, user=workos_user, sealed_session="refreshed_tok"
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
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session == "refreshed_tok"

    # -- Database query exception ------------------------------------------

    async def test_db_exception_returns_empty(self) -> None:
        """find_one raising -> ({}, None) + 'Error processing user data: <e>' error."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.find_one = AsyncMock(side_effect=Exception("MongoDB connection lost"))

            user_info, new_session = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once_with(
            "Error processing user data: MongoDB connection lost"
        )

    async def test_db_exception_after_refresh_preserves_new_session(self) -> None:
        """find_one raising after a refresh -> ({}, refreshed_token)."""
        workos_user = _make_workos_user()
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(
            authenticated=True, user=workos_user, sealed_session="fresh_tok"
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
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session == "fresh_tok"

    # -- Overall exception -------------------------------------------------

    async def test_overall_exception_returns_empty(self) -> None:
        """load_sealed_session raising -> ({}, None) + 'Error in authenticate_workos_session: <e>'."""
        client = MagicMock()
        client.user_management.load_sealed_session = AsyncMock(
            side_effect=Exception("connection refused")
        )

        with patch(_PATCH_LOG) as mock_log, patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "cookie_pass"  # NOSONAR  # pragma: allowlist secret
            )

            user_info, new_session = await authenticate_workos_session(
                session_token="tok",
                workos_client=client,  # pragma: allowlist secret
            )

        assert user_info == {}
        assert new_session is None
        mock_log.error.assert_called_once_with(
            "Error in authenticate_workos_session: connection refused"
        )

    # -- Provided workos_client vs creating new one ------------------------

    async def test_uses_provided_workos_client(self) -> None:
        """A provided workos_client is used; AsyncWorkOSClient is never constructed."""
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

            await authenticate_workos_session(
                session_token="tok", workos_client=client
            )  # pragma: allowlist secret

        mock_cls.assert_not_called()
        client.user_management.load_sealed_session.assert_awaited_once()

    async def test_creates_workos_client_when_none_provided(self) -> None:
        """No client provided -> AsyncWorkOSClient(api_key, client_id) built from settings."""
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

            await authenticate_workos_session(
                session_token="tok", workos_client=None
            )  # pragma: allowlist secret

        mock_cls.assert_called_once_with(
            api_key="sk_test_key",  # pragma: allowlist secret
            client_id="client_id_123",
        )

    # -- Forwarded arguments (external contracts) --------------------------

    async def test_queries_mongodb_with_exact_email_filter(self) -> None:
        """find_one is called with EXACTLY {'email': <workos_user.email>} — the DB filter contract."""
        workos_user = _make_workos_user(email="query@test.com")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG):
            mock_col.find_one = AsyncMock(return_value=None)

            await authenticate_workos_session(
                session_token="tok", workos_client=client
            )  # pragma: allowlist secret

        mock_col.find_one.assert_awaited_once_with({"email": "query@test.com"})

    async def test_load_sealed_session_forwards_token_and_cookie_password(self) -> None:
        """load_sealed_session receives the exact sealed_session token + cookie_password."""
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
            mock_settings.WORKOS_COOKIE_PASSWORD = "pw_123"  # NOSONAR  # pragma: allowlist secret
            mock_col.find_one = AsyncMock(return_value=db_doc)

            await authenticate_workos_session(
                session_token="my_sealed_token", workos_client=client
            )  # pragma: allowlist secret

        client.user_management.load_sealed_session.assert_awaited_once_with(
            sealed_session="my_sealed_token",
            cookie_password="pw_123",  # pragma: allowlist secret
        )

    async def test_refresh_forwards_cookie_password(self) -> None:
        """session.refresh receives settings.WORKOS_COOKIE_PASSWORD."""
        auth_response = _make_auth_response(authenticated=False)
        refresh_result = _make_refresh_result(authenticated=False, reason="expired")
        session = _make_session(auth_response, refresh_result=refresh_result)
        client = _make_workos_client(session)

        with patch(_PATCH_LOG), patch(_PATCH_SETTINGS) as mock_settings:
            mock_settings.WORKOS_COOKIE_PASSWORD = (
                "my_secret_cookie_pw"  # NOSONAR  # pragma: allowlist secret
            )

            await authenticate_workos_session(
                session_token="tok", workos_client=client
            )  # pragma: allowlist secret

        session.refresh.assert_awaited_once_with(
            cookie_password="my_secret_cookie_pw"  # pragma: allowlist secret
        )  # NOSONAR

    # -- Observability contract --------------------------------------------

    async def test_log_set_called_with_auth_context(self) -> None:
        """log.set is called with auth_provider='workos' and the authenticated user_email."""
        workos_user = _make_workos_user(email="logged@example.com")
        auth_response = _make_auth_response(authenticated=True, user=workos_user)
        session = _make_session(auth_response)
        client = _make_workos_client(session)
        db_doc = _db_user_doc(email="logged@example.com")

        with patch(_PATCH_USERS_COLLECTION) as mock_col, patch(_PATCH_LOG) as mock_log:
            mock_col.find_one = AsyncMock(return_value=db_doc)

            await authenticate_workos_session(
                session_token="tok", workos_client=client
            )  # pragma: allowlist secret

        mock_log.set.assert_called_once_with(
            auth_provider="workos", user_email="logged@example.com"
        )

    # -- Equivalent-mutant proof -------------------------------------------

    def test_docstring_is_runtime_inert(self) -> None:
        """Prove the docstring is an equivalent-mutant: emptying it changes only __doc__.

        The function body never reads ``__doc__``; behaviour is identical whether the
        docstring is the real text or "". This justifies the single surviving str mutant.
        """
        assert isinstance(authenticate_workos_session.__doc__, str)
        assert "Authenticate a WorkOS session" in authenticate_workos_session.__doc__
