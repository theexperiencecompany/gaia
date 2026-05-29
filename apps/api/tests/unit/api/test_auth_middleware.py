"""Behaviour spec for the WorkOS auth middleware.

UNIT: app/api/v1/middleware/auth.py :: get_current_user
EXPECTED: Return request.state.user; None when the attribute is absent.
MECHANISM: getattr(request.state, "user", None).
MUST-CATCH:
  - reads the "user" attribute specifically, returns its real value
  - default is None when state has no user attribute

UNIT: app/api/v1/middleware/auth.py :: WorkOSAuthMiddleware.dispatch
EXPECTED: Authenticate each non-excluded request. Excluded paths bypass auth
          entirely. A wos_session cookie (or a "Bearer <tok>" Authorization
          header fallback) is authenticated through _authenticate_session; on
          success request.state.user/.authenticated are set and a refreshed
          session is written back as a wos_session Set-Cookie; on failure
          request.state.auth_failure is "invalid_or_expired_session"; on
          exception the request still proceeds unauthenticated. For agent-only
          paths with no session, a valid agent JWT loads the impersonated user
          from Mongo.
MECHANISM: exclude-path startswith short-circuit; cookie then Bearer-header
          token extraction; _authenticate_session(); state mutation; agent_only
          branch via verify_agent_token + users_collection.find_one; refreshed
          cookie via response.set_cookie(httponly, secure, samesite, max_age).
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - excluded paths skip auth (no _authenticate_session call), arbitrary path
  - the token passed to the WorkOS boundary equals the cookie value
  - the Bearer header fallback strips exactly "Bearer " and keeps the rest,
    including tokens that themselves contain spaces (split maxsplit == 1)
  - a header that is not "Bearer ..." is NOT treated as a session token
  - successful auth sets user + authenticated True; unauth leaves them False/None
  - failed auth sets request.state.auth_failure == "invalid_or_expired_session"
  - an exception in auth is swallowed; request proceeds, unauthenticated
  - refreshed session writes a wos_session cookie with HttpOnly, SameSite=lax,
    Max-Age=604800 and (in non-prod) NO Secure flag
  - no refresh => no Set-Cookie
  - agent path: only triggers when unauthenticated AND path is agent-only AND
    header is Bearer; builds the exact impersonated user dict from the db row
  - agent path with non-ObjectId user_id still queries Mongo by ObjectId
  - invalid agent token / missing db user => unauthenticated
EQUIVALENT MUTANTS (allowed survivors, proven): dispatch docstring str->''
  (first statement Expr(Constant) -> only mutates __doc__, never read at runtime).

UNIT: app/api/v1/middleware/auth.py :: WorkOSAuthMiddleware._authenticate_session
EXPECTED: Delegate to authenticate_workos_session; on a user, stamp
          last_active_at via users_collection.update_one and return
          (user_info, new_session); if that update raises, return
          (None, new_session); if no user, return (None, new_session).
MECHANISM: authenticate_workos_session(); update_one({"email": ...},
          {"$set": {"last_active_at": now}}); try/except -> (None, new_session).
MUST-CATCH:
  - the session token reaches authenticate_workos_session unchanged
  - update_one filter is keyed on the user's email, $set targets last_active_at
  - success returns the real (user_info, new_session) tuple
  - update_one failure => (None, <new_session preserved>)
  - no user => (None, <new_session preserved>)
EQUIVALENT MUTANTS (allowed survivors, proven): _authenticate_session docstring
  str->'' (only mutates __doc__, no runtime effect).
"""

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import FastAPI, Request
import pytest
from starlette.testclient import TestClient

from app.api.v1.middleware.auth import WorkOSAuthMiddleware, get_current_user
from app.config.settings import settings

AUTH_WORKOS = "app.api.v1.middleware.auth.authenticate_workos_session"
VERIFY_AGENT = "app.api.v1.middleware.auth.verify_agent_token"
FIND_ONE = "app.api.v1.middleware.auth.users_collection.find_one"
UPDATE_ONE = "app.api.v1.middleware.auth.users_collection.update_one"
LOG = "app.api.v1.middleware.auth.log"
SETTINGS = "app.api.v1.middleware.auth.settings"

AGENT_PATH = "/api/v1/chat-stream"
PROTECTED_PATH = "/api/v1/protected"
OBJECT_ID_HEX = "507f1f77bcf86cd799439011"


def _build_app(middleware_kwargs: dict | None = None) -> FastAPI:
    """Minimal app exposing the auth state the middleware writes to request.state."""
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get(PROTECTED_PATH)
    async def protected(request: Request) -> dict:
        return {
            "user": getattr(request.state, "user", None),
            "authenticated": getattr(request.state, "authenticated", False),
            "auth_failure": getattr(request.state, "auth_failure", None),
        }

    @app.post(AGENT_PATH)
    async def chat_stream(request: Request) -> dict:
        return {
            "user": getattr(request.state, "user", None),
            "authenticated": getattr(request.state, "authenticated", False),
        }

    kwargs = middleware_kwargs or {}
    kwargs.setdefault("workos_client", MagicMock())
    app.add_middleware(WorkOSAuthMiddleware, **kwargs)
    return app


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCurrentUser:
    def test_returns_the_user_attribute_value(self) -> None:
        request = MagicMock()
        request.state.user = {"user_id": "u1", "email": "a@b.com"}
        assert get_current_user(request) == {"user_id": "u1", "email": "a@b.com"}

    def test_returns_none_when_user_attribute_absent(self) -> None:
        request = MagicMock()
        request.state = MagicMock(spec=[])  # no 'user' attribute
        assert get_current_user(request) is None


# ---------------------------------------------------------------------------
# dispatch — excluded paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExcludedPaths:
    def test_excluded_path_bypasses_authentication(self) -> None:
        app = _build_app()
        with patch(AUTH_WORKOS, new_callable=AsyncMock) as auth:
            resp = TestClient(app).get("/health", cookies={"wos_session": "tok"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # Excluded path returned before any auth work happened.
        auth.assert_not_called()

    def test_non_excluded_path_is_authenticated(self) -> None:
        # The same cookie on a path NOT in exclude_paths must reach the WorkOS
        # boundary — proves the startswith match is real, not always-true.
        app = _build_app(middleware_kwargs={"exclude_paths": ["/health"]})
        with patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=({}, None)) as auth:
            TestClient(app).get(PROTECTED_PATH, cookies={"wos_session": "tok"})
        auth.assert_awaited_once()


# ---------------------------------------------------------------------------
# dispatch — session authentication (real _authenticate_session, mocked I/O)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionAuth:
    def test_no_session_leaves_request_unauthenticated(self) -> None:
        app = _build_app()
        with patch(AUTH_WORKOS, new_callable=AsyncMock) as auth:
            resp = TestClient(app).get(PROTECTED_PATH)
        data = resp.json()
        assert data["authenticated"] is False
        assert data["user"] is None
        assert data["auth_failure"] is None
        auth.assert_not_called()

    def test_cookie_token_reaches_workos_and_authenticates(self) -> None:
        user_info = {"user_id": "u1", "email": "a@b.com", "name": "Test"}
        app = _build_app()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=(user_info, None)) as auth,
            patch(UPDATE_ONE, new_callable=AsyncMock),
        ):
            resp = TestClient(app).get(PROTECTED_PATH, cookies={"wos_session": "sealed_tok"})
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"] == user_info
        # The exact cookie value is the token handed to WorkOS.
        assert auth.await_args.kwargs["session_token"] == "sealed_tok"  # pragma: allowlist secret

    def test_bearer_header_token_is_stripped_of_prefix_only(self) -> None:
        # Token contains a space; maxsplit==1 must keep "tok with space" intact.
        user_info = {"user_id": "u2", "email": "b@c.com"}
        app = _build_app()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=(user_info, None)) as auth,
            patch(UPDATE_ONE, new_callable=AsyncMock),
        ):
            resp = TestClient(app).get(
                PROTECTED_PATH,
                headers={"Authorization": "Bearer tok with space"},
            )
        assert resp.json()["authenticated"] is True
        assert (
            auth.await_args.kwargs["session_token"] == "tok with space"
        )  # pragma: allowlist secret

    def test_non_bearer_header_is_not_used_as_token(self) -> None:
        app = _build_app()
        with patch(AUTH_WORKOS, new_callable=AsyncMock) as auth:
            resp = TestClient(app).get(
                PROTECTED_PATH,
                headers={"Authorization": "Basic dXNlcjpwYXNz"},
            )
        assert resp.json()["authenticated"] is False
        auth.assert_not_called()

    def test_failed_auth_records_auth_failure_reason(self) -> None:
        app = _build_app()
        with patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=({}, None)):
            resp = TestClient(app).get(PROTECTED_PATH, cookies={"wos_session": "bad_tok"})
        data = resp.json()
        assert data["authenticated"] is False
        assert data["user"] is None
        assert data["auth_failure"] == "invalid_or_expired_session"

    def test_auth_exception_is_swallowed_and_logged(self) -> None:
        app = _build_app()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, side_effect=RuntimeError("WorkOS down")),
            patch(LOG) as log,
        ):
            resp = TestClient(app).get(PROTECTED_PATH, cookies={"wos_session": "tok"})
        data = resp.json()
        assert resp.status_code == 200
        assert data["authenticated"] is False
        # Exception path does NOT set the auth_failure reason (only the else does).
        assert data["auth_failure"] is None
        # The failure is logged as the wide event 'auth_middleware_error' with the
        # exception class name and message attached.
        event_name = log.error.call_args.args[0]
        kwargs = log.error.call_args.kwargs
        assert event_name == "auth_middleware_error"
        assert kwargs["auth_failure"] == "RuntimeError"
        assert kwargs["error"] == "WorkOS down"


# ---------------------------------------------------------------------------
# dispatch — refreshed-session cookie
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionRefreshCookie:
    def test_refreshed_session_sets_secure_cookie_attributes(self) -> None:
        user_info = {"user_id": "u1", "email": "a@b.com"}
        app = _build_app()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=(user_info, "refreshed_tok")),
            patch(UPDATE_ONE, new_callable=AsyncMock),
        ):
            resp = TestClient(app).get(PROTECTED_PATH, cookies={"wos_session": "old_tok"})
        set_cookie = resp.headers["set-cookie"]
        assert "wos_session=refreshed_tok" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        # 7 days = 60*60*24*7 seconds.
        assert "Max-Age=604800" in set_cookie
        # ENV is "development" in tests, so the Secure flag must NOT be present.
        assert "Secure" not in set_cookie

    def test_refreshed_cookie_is_secure_in_production(self) -> None:
        # secure=settings.ENV == "production": flipping ENV to production must
        # add the Secure attribute (guards the == "production" comparison).
        user_info = {"user_id": "u1", "email": "a@b.com"}
        app = _build_app()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=(user_info, "refreshed_tok")),
            patch(UPDATE_ONE, new_callable=AsyncMock),
            patch.object(settings, "ENV", "production"),
        ):
            resp = TestClient(app).get(PROTECTED_PATH, cookies={"wos_session": "old_tok"})
        assert "Secure" in resp.headers["set-cookie"]

    def test_no_refresh_means_no_session_cookie(self) -> None:
        user_info = {"user_id": "u1", "email": "a@b.com"}
        app = _build_app()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=(user_info, None)),
            patch(UPDATE_ONE, new_callable=AsyncMock),
        ):
            resp = TestClient(app).get(PROTECTED_PATH, cookies={"wos_session": "tok"})
        assert "set-cookie" not in {k.lower() for k in resp.headers}


# ---------------------------------------------------------------------------
# dispatch — agent-only path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentAuth:
    def test_agent_token_builds_impersonated_user_from_db_row(self) -> None:
        db_row = {
            "_id": OBJECT_ID_HEX,
            "email": "agent@test.com",
            "name": "Agent User",
            "picture": "pic.png",
        }
        app = _build_app()
        with (
            patch(VERIFY_AGENT, return_value={"user_id": OBJECT_ID_HEX, "impersonated": True}),
            patch(FIND_ONE, new_callable=AsyncMock, return_value=db_row),
        ):
            resp = TestClient(app).post(AGENT_PATH, headers={"Authorization": "Bearer agent_jwt"})
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"] == {
            "user_id": OBJECT_ID_HEX,
            "email": "agent@test.com",
            "name": "Agent User",
            "picture": "pic.png",
            "auth_provider": "workos",
            "impersonated": True,
        }

    def test_agent_lookup_converts_string_user_id_to_objectid(self) -> None:
        db_row = {"_id": OBJECT_ID_HEX, "email": "a@t.com", "name": "n", "picture": None}
        app = _build_app()
        with (
            patch(VERIFY_AGENT, return_value={"user_id": OBJECT_ID_HEX, "impersonated": True}),
            patch(FIND_ONE, new_callable=AsyncMock, return_value=db_row) as find_one,
        ):
            TestClient(app).post(AGENT_PATH, headers={"Authorization": "Bearer agent_jwt"})
        # String user_id is converted before the query (not-isinstance branch).
        assert find_one.await_args.args[0] == {"_id": ObjectId(OBJECT_ID_HEX)}

    def test_agent_lookup_uses_existing_objectid_directly(self) -> None:
        # When user_id is already an ObjectId, the conversion branch is skipped
        # and the query uses it as-is.
        oid = ObjectId(OBJECT_ID_HEX)
        db_row = {"_id": OBJECT_ID_HEX, "email": "a@t.com", "name": "n", "picture": None}
        app = _build_app()
        with (
            patch(VERIFY_AGENT, return_value={"user_id": oid, "impersonated": True}),
            patch(FIND_ONE, new_callable=AsyncMock, return_value=db_row) as find_one,
        ):
            resp = TestClient(app).post(AGENT_PATH, headers={"Authorization": "Bearer agent_jwt"})
        assert resp.json()["authenticated"] is True
        assert find_one.await_args.args[0] == {"_id": oid}

    def test_agent_path_requires_bearer_prefix_on_header(self) -> None:
        # On the agent path a non-Bearer Authorization header must not be parsed
        # as an agent token (guards the startswith("Bearer ") check, L137).
        app = _build_app()
        with patch(VERIFY_AGENT) as verify:
            resp = TestClient(app).post(AGENT_PATH, headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.json()["authenticated"] is False
        verify.assert_not_called()

    def test_agent_path_without_authorization_header_is_unauthenticated(self) -> None:
        # No header at all on the agent path: the `auth_header and ...` guard
        # short-circuits (mutating `and`->`or` would dereference None and 500).
        app = _build_app()
        with patch(VERIFY_AGENT) as verify:
            resp = TestClient(app).post(AGENT_PATH)
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        verify.assert_not_called()

    def test_agent_token_split_keeps_spaces_in_token(self) -> None:
        # Agent token containing spaces: split(" ", 1) must keep it intact.
        db_row = {"_id": OBJECT_ID_HEX, "email": "a@t.com", "name": "n", "picture": None}
        app = _build_app()
        with (
            patch(
                VERIFY_AGENT,
                return_value={"user_id": OBJECT_ID_HEX, "impersonated": True},
            ) as verify,
            patch(FIND_ONE, new_callable=AsyncMock, return_value=db_row),
        ):
            TestClient(app).post(AGENT_PATH, headers={"Authorization": "Bearer jwt with spaces"})
        assert verify.call_args.args[0] == "jwt with spaces"

    def test_agent_path_ignored_when_already_authenticated(self) -> None:
        # A valid session on the agent path must NOT trigger the agent branch.
        session_user = {"user_id": "u1", "email": "a@b.com"}
        app = _build_app()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=(session_user, None)),
            patch(UPDATE_ONE, new_callable=AsyncMock),
            patch(VERIFY_AGENT) as verify,
        ):
            resp = TestClient(app).post(
                AGENT_PATH,
                cookies={"wos_session": "good"},
                headers={"Authorization": "Bearer agent_jwt"},
            )
        assert resp.json()["user"] == session_user
        verify.assert_not_called()

    def test_agent_branch_skipped_on_non_agent_path(self) -> None:
        app = _build_app()
        with patch(VERIFY_AGENT) as verify:
            resp = TestClient(app).get(
                PROTECTED_PATH, headers={"Authorization": "Bearer agent_jwt"}
            )
        # /api/v1/protected is not an agent-only path; agent auth never runs.
        verify.assert_not_called()
        assert resp.json()["authenticated"] is False

    def test_invalid_agent_token_stays_unauthenticated(self) -> None:
        app = _build_app()
        with (
            patch(VERIFY_AGENT, return_value=None),
            patch(FIND_ONE, new_callable=AsyncMock) as find_one,
        ):
            resp = TestClient(app).post(AGENT_PATH, headers={"Authorization": "Bearer bad_token"})
        assert resp.json()["authenticated"] is False
        find_one.assert_not_called()

    def test_agent_user_not_in_db_stays_unauthenticated(self) -> None:
        app = _build_app()
        with (
            patch(VERIFY_AGENT, return_value={"user_id": OBJECT_ID_HEX, "impersonated": True}),
            patch(FIND_ONE, new_callable=AsyncMock, return_value=None),
        ):
            resp = TestClient(app).post(AGENT_PATH, headers={"Authorization": "Bearer agent_jwt"})
        assert resp.json()["authenticated"] is False

    def test_agent_invalid_objectid_format_does_not_crash(self) -> None:
        app = _build_app()
        with (
            patch(VERIFY_AGENT, return_value={"user_id": "not-an-objectid", "impersonated": True}),
            patch(FIND_ONE, new_callable=AsyncMock) as find_one,
            patch(LOG) as log,
        ):
            resp = TestClient(app).post(AGENT_PATH, headers={"Authorization": "Bearer agent_jwt"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        # Bad ObjectId => user_data is None, never queried.
        find_one.assert_not_called()
        # The malformed id is logged with its value and the underlying error,
        # separated by " - " (full message contract).
        message = log.error.call_args.args[0]
        assert message.startswith("Invalid user_id format: not-an-objectid - ")


# ---------------------------------------------------------------------------
# _authenticate_session helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuthenticateSession:
    def _middleware(self) -> WorkOSAuthMiddleware:
        return WorkOSAuthMiddleware(app=MagicMock(), workos_client=MagicMock())

    async def test_success_stamps_last_active_and_returns_tuple(self) -> None:
        user_info = {"user_id": "u1", "email": "a@b.com"}
        middleware = self._middleware()
        with (
            patch(
                AUTH_WORKOS, new_callable=AsyncMock, return_value=(user_info, "new_sess")
            ) as auth,
            patch(UPDATE_ONE, new_callable=AsyncMock) as update_one,
        ):
            result_user, result_sess = await middleware._authenticate_session("tok")
        assert result_user == user_info
        assert result_sess == "new_sess"
        assert auth.await_args.kwargs["session_token"] == "tok"  # pragma: allowlist secret
        filter_arg, update_arg = update_one.await_args.args
        assert filter_arg == {"email": "a@b.com"}
        assert set(update_arg["$set"]) == {"last_active_at"}

    async def test_no_user_returns_none_with_new_session_preserved(self) -> None:
        middleware = self._middleware()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=({}, "sess_only")),
            patch(UPDATE_ONE, new_callable=AsyncMock) as update_one,
        ):
            result_user, result_sess = await middleware._authenticate_session("tok")
        assert result_user is None
        assert result_sess == "sess_only"
        update_one.assert_not_called()

    async def test_update_failure_returns_none_user_but_keeps_session(self) -> None:
        user_info = {"user_id": "u1", "email": "a@b.com"}
        middleware = self._middleware()
        with (
            patch(AUTH_WORKOS, new_callable=AsyncMock, return_value=(user_info, "kept_sess")),
            patch(UPDATE_ONE, new_callable=AsyncMock, side_effect=RuntimeError("db err")),
            patch(LOG) as log,
        ):
            result_user, result_sess = await middleware._authenticate_session("tok")
        assert result_user is None
        assert result_sess == "kept_sess"
        # The processing failure is logged.
        message = log.error.call_args.args[0]
        assert message.startswith("Error in middleware additional processing:")
        assert "db err" in message
