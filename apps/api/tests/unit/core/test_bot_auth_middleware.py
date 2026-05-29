"""Tests for BotAuthMiddleware — bot platform authentication.

UNIT: app/core/bot_auth_middleware.py :: BotAuthMiddleware
      (dispatch, _verify_api_key, _authenticate_platform, _authenticate_jwt)

EXPECTED: For every non-excluded, not-already-authenticated request, resolve the
caller from either a JWT Bearer token (fast path) or an X-Bot-API-Key + platform
headers (DB lookup). On success set request.state.user (a fixed-shape dict) and
request.state.authenticated=True so downstream endpoints treat the bot like a web
user. A valid API key alone also marks request.state.bot_api_key_valid/bot_platform/
bot_platform_user_id even when no linked user exists.

MECHANISM:
  dispatch:
    - excluded path (prefix match) OR already-authenticated -> pass straight through,
      no auth work at all.
    - Authorization: "Bearer <tok>" -> token = header[7:]; _authenticate_jwt(token).
      On success set state.user/authenticated and stop. Any exception -> swallow, fall
      through to API-key path.
    - API-key path runs only when not already JWT-authenticated. Requires api_key AND
      _verify_api_key(api_key). With platform AND platform_user_id -> _authenticate_platform;
      on a user, set state.user/authenticated. Always (when key valid) set
      bot_api_key_valid=True, bot_platform, bot_platform_user_id.
  _verify_api_key: returns False if GAIA_BOT_API_KEY unset/missing, else timing-safe equality.
  _authenticate_platform / _authenticate_jwt: cache hit short-circuits the DB; otherwise
    look up by platform id, build a {user_id,email,name,picture,auth_provider,bot_authenticated}
    dict (auth_provider = "bot:<platform>"), write it to cache (10-min TTL), return it.
    JWT path additionally rejects payloads missing any of user_id/platform/platform_user_id,
    a cached user whose user_id != token user_id (cache miss, re-lookup), and a DB _id that
    does not match the token user_id.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - excluded path bypass uses real prefix list; mutating it makes a guarded path run auth
  - already-authenticated short-circuit: NO auth collaborator is invoked  [L60 key]
  - "Bearer " prefix gate: a non-Bearer header must NOT trigger JWT auth   [L67]
  - token is header sliced from index 7 exactly                            [L68]
  - JWT success populates the exact user dict (every field, provider, flag) [L164-170]
  - JWT cache key is exactly "bot_user:<platform>:<platform_user_id>"       [L148]
  - JWT cache-hit (matching user_id) returns cached user, no DB / no set_cache [L151]
  - JWT payload missing any required field -> unauthenticated              [L145 Or]
  - JWT DB user _id != token user_id -> unauthenticated                    [L161]
  - JWT failure (JWTError / generic) is swallowed; request proceeds        [L75]
  - API key + both platform headers authenticates; exact platform dict     [L124-130]
  - platform cache key is exactly "bot_user:<platform>:<platform_user_id>" [L113]
  - API key valid but only one platform header -> NO platform lookup       [L86 And]
  - API key valid, no platform headers -> bot_api_key_valid True, not authed
  - API key valid, unlinked user -> bot_api_key_valid True + platform crumbs set
  - invalid / unconfigured key -> _verify_api_key False, never authed; key
    UNCONFIGURED must not be treated as valid                              [L105]
  - JWT wins when both JWT and API key are present (API-key path skipped)  [L74]

EQUIVALENT MUTANTS (allowed survivors, justified):
  - L91 `authenticated = True` (True->False): this local is the LAST read of
    `authenticated` in the API-key block; nothing downstream reads it again, so flipping
    it cannot change behaviour. The observable state mutation is L90
    `request.state.authenticated = True`, which is covered.
  - L105 `return False` -> `return None`: the sole caller uses the result only in
    `if api_key and self._verify_api_key(api_key)`; None and False are both falsy there,
    so the branch outcome is identical. (The `False -> True` mutant on the same line is
    NOT equivalent and is killed by test_unconfigured_key_is_not_treated_as_valid.)
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from jose import JWTError
import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.constants.cache import TEN_MINUTES_TTL
from app.core.bot_auth_middleware import BotAuthMiddleware

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FAKE_USER_DATA: dict[str, Any] = {
    "_id": "user_abc123",
    "email": "bot@example.com",
    "name": "Bot User",
    "picture": "https://example.com/pic.png",
}

FAKE_JWT_PAYLOAD: dict[str, Any] = {
    "user_id": "user_abc123",
    "platform": "discord",
    "platform_user_id": "disc_999",
}


def _build_app(exclude_paths: list[str] | None = None) -> FastAPI:
    """Minimal FastAPI app wired with the real BotAuthMiddleware.

    The endpoint echoes back the request.state fields the middleware sets, so
    tests assert observable behaviour through the real dispatch path.
    """
    app = FastAPI()
    app.add_middleware(BotAuthMiddleware, exclude_paths=exclude_paths)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/test")
    async def api_test(request: Request) -> dict[str, Any]:
        return {
            "authenticated": getattr(request.state, "authenticated", False),
            "user": getattr(request.state, "user", None),
            "bot_api_key_valid": getattr(request.state, "bot_api_key_valid", False),
            "bot_platform": getattr(request.state, "bot_platform", None),
            "bot_platform_user_id": getattr(request.state, "bot_platform_user_id", None),
        }

    return app


async def _get(app: FastAPI, path: str = "/api/test", **kwargs: Any) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        return await client.get(path, **kwargs)


# ---------------------------------------------------------------------------
# dispatch — excluded paths & already-authenticated short-circuit
# ---------------------------------------------------------------------------


class TestDispatchShortCircuits:
    async def test_excluded_path_bypasses_auth(self) -> None:
        """A path matching the exclude list returns without invoking any auth path."""
        app = _build_app()
        # Health is excluded by default; a Bearer header would otherwise hit JWT auth.
        with patch("app.core.bot_auth_middleware.verify_bot_session_token") as mock_verify:
            resp = await _get(app, "/health", headers={"Authorization": "Bearer would-be-token"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        # Excluded means the JWT collaborator is never touched.
        mock_verify.assert_not_called()

    async def test_non_excluded_path_runs_auth(self) -> None:
        """A path NOT in the exclude list must run the auth logic (anchors the exclude
        check: if the prefix list were mutated to also match /api, JWT auth would not run)."""
        app = _build_app(exclude_paths=["/health"])
        with patch("app.core.bot_auth_middleware.verify_bot_session_token") as mock_verify:
            mock_verify.side_effect = JWTError("nope")
            resp = await _get(app, "/api/test", headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        mock_verify.assert_called_once()

    async def test_custom_exclude_path_bypasses(self) -> None:
        app = _build_app(exclude_paths=["/custom"])

        @app.get("/custom")
        async def custom() -> dict[str, str]:
            return {"ok": "true"}

        with patch("app.core.bot_auth_middleware.verify_bot_session_token") as mock_verify:
            resp = await _get(app, "/custom", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": "true"}
        mock_verify.assert_not_called()

    async def test_already_authenticated_skips_all_auth_work(self) -> None:
        """If an upstream middleware set authenticated=True, BotAuth must do nothing —
        no JWT verify, no API-key handling, state.user preserved untouched."""
        app = FastAPI()

        class PreAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):  # type: ignore[override]
                request.state.authenticated = True
                request.state.user = {"user_id": "pre_auth_user"}
                return await call_next(request)

        # Last added runs first -> PreAuth runs before BotAuth.
        app.add_middleware(BotAuthMiddleware)
        app.add_middleware(PreAuthMiddleware)

        @app.get("/api/test")
        async def endpoint(request: Request) -> dict[str, Any]:
            return {
                "authenticated": request.state.authenticated,
                "user": request.state.user,
                "bot_api_key_valid": getattr(request.state, "bot_api_key_valid", False),
            }

        with (
            patch("app.core.bot_auth_middleware.verify_bot_session_token") as mock_verify,
            patch("app.core.bot_auth_middleware.settings") as mock_settings,
        ):
            mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
            # Send creds that WOULD authenticate if the short-circuit failed.
            resp = await _get(
                app,
                "/api/test",
                headers={
                    "Authorization": "Bearer realtoken",
                    "X-Bot-API-Key": "secret-bot-key",  # pragma: allowlist secret
                    "X-Bot-Platform": "discord",
                    "X-Bot-Platform-User-Id": "disc_1",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        # The pre-existing user is preserved; BotAuth never overwrote it.
        assert data["authenticated"] is True
        assert data["user"] == {"user_id": "pre_auth_user"}
        # Proof BotAuth short-circuited: it never ran JWT verify nor the API-key block.
        mock_verify.assert_not_called()
        assert data["bot_api_key_valid"] is False


# ---------------------------------------------------------------------------
# dispatch — JWT Bearer header handling
# ---------------------------------------------------------------------------


class TestDispatchJWTHeader:
    async def test_non_bearer_authorization_does_not_trigger_jwt(self) -> None:
        """Only an "Bearer " prefix arms JWT auth; a Basic header must be ignored."""
        app = _build_app()
        with patch("app.core.bot_auth_middleware.verify_bot_session_token") as mock_verify:
            resp = await _get(app, headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        mock_verify.assert_not_called()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_token_is_sliced_after_bearer_prefix(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """The exact token (header minus the 7-char "Bearer " prefix) is passed to
        verify_bot_session_token — anchors the [7:] slice offset."""
        app = _build_app()
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        resp = await _get(app, headers={"Authorization": "Bearer abc.def.ghi"})

        assert resp.status_code == 200
        mock_verify.assert_called_once_with("abc.def.ghi")

    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_error_is_swallowed_and_request_proceeds(
        self, mock_verify: MagicMock
    ) -> None:
        """A JWTError from token verification is caught; the request continues
        unauthenticated rather than 500-ing."""
        app = _build_app()
        mock_verify.side_effect = JWTError("expired")
        resp = await _get(app, headers={"Authorization": "Bearer bad"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_generic_exception_in_jwt_is_swallowed(self, mock_verify: MagicMock) -> None:
        """The broad `except (JWTError, Exception)` also swallows non-JWT errors so a
        malformed token never crashes the request."""
        app = _build_app()
        mock_verify.side_effect = RuntimeError("boom")
        resp = await _get(app, headers={"Authorization": "Bearer bad"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


# ---------------------------------------------------------------------------
# _authenticate_jwt — success, caching, and every rejection branch
# ---------------------------------------------------------------------------


class TestAuthenticateJWT:
    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_valid_jwt_builds_full_user_and_caches(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """On a cache miss + matching DB user, the middleware returns the exact user
        dict (all fields, provider, flag), looks the user up by the token's platform id,
        and writes the result to cache under the right key with the 10-min TTL."""
        app = _build_app()
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        resp = await _get(app, headers={"Authorization": "Bearer tok"})

        assert resp.status_code == 200
        user = resp.json()["user"]
        assert resp.json()["authenticated"] is True
        # Exact dict shape — every key must carry the real value, not a defaulted None.
        assert user == {
            "user_id": "user_abc123",
            "email": "bot@example.com",
            "name": "Bot User",
            "picture": "https://example.com/pic.png",
            "auth_provider": "bot:discord",
            "bot_authenticated": True,
        }
        # DB lookup keyed on the token's platform + platform_user_id, not constants.
        mock_platform.assert_awaited_once_with("discord", "disc_999")
        # Cache key + TTL contract.
        mock_get_cache.assert_awaited_once_with("bot_user:discord:disc_999")
        mock_set_cache.assert_awaited_once()
        set_args, set_kwargs = mock_set_cache.await_args
        assert set_args[0] == "bot_user:discord:disc_999"
        assert set_args[1] == user
        assert set_kwargs["ttl"] == TEN_MINUTES_TTL

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_cache_hit_returns_cached_user_without_db(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """A cached user whose user_id matches the token short-circuits: no DB lookup,
        no re-cache, and the cached dict is returned verbatim."""
        app = _build_app()
        cached = {
            "user_id": "user_abc123",
            "email": "cached@example.com",
            "name": "Cached User",
            "picture": None,
            "auth_provider": "bot:discord",
            "bot_authenticated": True,
        }
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = cached

        resp = await _get(app, headers={"Authorization": "Bearer tok"})

        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True
        assert resp.json()["user"] == cached
        mock_platform.assert_not_awaited()
        mock_set_cache.assert_not_awaited()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_cached_user_id_mismatch_falls_through_to_db(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """A cached entry whose user_id does NOT equal the token user_id is treated as a
        miss: the DB is re-queried (here authenticating the correct user)."""
        app = _build_app()
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = {"user_id": "someone_else", "email": "x"}
        mock_platform.return_value = FAKE_USER_DATA

        resp = await _get(app, headers={"Authorization": "Bearer tok"})

        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True
        assert resp.json()["user"]["email"] == "bot@example.com"
        mock_platform.assert_awaited_once_with("discord", "disc_999")

    @pytest.mark.parametrize(
        "payload",
        [
            {"user_id": None, "platform": "discord", "platform_user_id": "disc_999"},
            {"user_id": "u", "platform": None, "platform_user_id": "disc_999"},
            {"user_id": "u", "platform": "discord", "platform_user_id": None},
        ],
    )
    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_payload_missing_any_required_field_rejected(
        self,
        mock_verify: MagicMock,
        mock_get_cache: AsyncMock,
        payload: dict[str, Any],
    ) -> None:
        """Missing user_id OR platform OR platform_user_id -> unauthenticated, and the
        cache is never consulted (the guard returns before the cache read)."""
        app = _build_app()
        mock_verify.return_value = payload
        resp = await _get(app, headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        mock_get_cache.assert_not_awaited()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_unlinked_user_not_authenticated(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """No DB user for the platform id -> unauthenticated."""
        app = _build_app()
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = None
        mock_platform.return_value = None
        resp = await _get(app, headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_db_id_mismatch_rejected(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """If the DB user's _id does not match the token user_id, auth fails and nothing
        is cached (guards against token/DB identity drift)."""
        app = _build_app()
        mock_verify.return_value = {
            "user_id": "different_user_id",
            "platform": "discord",
            "platform_user_id": "disc_999",
        }
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA  # _id = user_abc123

        resp = await _get(app, headers={"Authorization": "Bearer tok"})

        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        mock_set_cache.assert_not_awaited()


# ---------------------------------------------------------------------------
# _verify_api_key + API-key/platform path
# ---------------------------------------------------------------------------


class TestAPIKeyAuth:
    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_valid_key_and_platform_headers_authenticate(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """Valid key + both platform headers -> full platform user dict, state crumbs set,
        DB looked up by the supplied platform/user id, cache written with the right key."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        resp = await _get(
            app,
            headers={
                "X-Bot-API-Key": "secret-bot-key",  # pragma: allowlist secret
                "X-Bot-Platform": "telegram",
                "X-Bot-Platform-User-Id": "tg_123",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"] == {
            "user_id": "user_abc123",
            "email": "bot@example.com",
            "name": "Bot User",
            "picture": "https://example.com/pic.png",
            "auth_provider": "bot:telegram",
            "bot_authenticated": True,
        }
        assert data["bot_api_key_valid"] is True
        assert data["bot_platform"] == "telegram"
        assert data["bot_platform_user_id"] == "tg_123"
        mock_platform.assert_awaited_once_with("telegram", "tg_123")
        mock_get_cache.assert_awaited_once_with("bot_user:telegram:tg_123")
        set_args, set_kwargs = mock_set_cache.await_args
        assert set_args[0] == "bot_user:telegram:tg_123"
        assert set_kwargs["ttl"] == TEN_MINUTES_TTL

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_platform_cache_hit_skips_db(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """A cached platform user (with a user_id) is returned without a DB lookup or
        re-cache."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        cached = {
            "user_id": "user_abc123",
            "email": "c@example.com",
            "name": "C",
            "picture": None,
            "auth_provider": "bot:slack",
            "bot_authenticated": True,
        }
        mock_get_cache.return_value = cached

        resp = await _get(
            app,
            headers={
                "X-Bot-API-Key": "secret-bot-key",  # pragma: allowlist secret
                "X-Bot-Platform": "slack",
                "X-Bot-Platform-User-Id": "slack_456",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True
        assert resp.json()["user"] == cached
        mock_get_cache.assert_awaited_once_with("bot_user:slack:slack_456")
        mock_platform.assert_not_awaited()
        mock_set_cache.assert_not_awaited()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_platform_cache_entry_without_user_id_falls_through(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """A cached entry lacking a user_id is not trusted: the DB is consulted."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_get_cache.return_value = {"email": "stale@example.com"}  # no user_id
        mock_platform.return_value = None

        resp = await _get(
            app,
            headers={
                "X-Bot-API-Key": "secret-bot-key",  # pragma: allowlist secret
                "X-Bot-Platform": "discord",
                "X-Bot-Platform-User-Id": "disc_1",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
        mock_platform.assert_awaited_once_with("discord", "disc_1")

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_valid_key_missing_one_platform_header_skips_lookup(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """Both platform headers are required for the lookup. With only the platform
        present (no user id), the DB is NOT queried, but the key is still recorded."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret

        resp = await _get(
            app,
            headers={
                "X-Bot-API-Key": "secret-bot-key",  # pragma: allowlist secret
                "X-Bot-Platform": "discord",
                # no X-Bot-Platform-User-Id
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is True
        assert data["bot_platform"] == "discord"
        assert data["bot_platform_user_id"] is None
        mock_platform.assert_not_awaited()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_valid_key_no_platform_headers_marks_key_only(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """Valid key, no platform headers: bot_api_key_valid=True (so /bot/chat works for
        unlinked users) but not authenticated and no DB lookup."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret

        resp = await _get(
            app,
            headers={"X-Bot-API-Key": "secret-bot-key"},  # pragma: allowlist secret
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is True
        assert data["bot_platform"] is None
        assert data["bot_platform_user_id"] is None
        mock_platform.assert_not_awaited()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_valid_key_unlinked_user_sets_crumbs_not_authenticated(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """Valid key + headers but user not linked: not authenticated, yet the platform
        crumbs are recorded for downstream handling of unlinked users."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_get_cache.return_value = None
        mock_platform.return_value = None

        resp = await _get(
            app,
            headers={
                "X-Bot-API-Key": "secret-bot-key",  # pragma: allowlist secret
                "X-Bot-Platform": "discord",
                "X-Bot-Platform-User-Id": "unknown_disc",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is True
        assert data["bot_platform"] == "discord"
        assert data["bot_platform_user_id"] == "unknown_disc"

    @patch("app.core.bot_auth_middleware.settings")
    async def test_wrong_key_rejected(self, mock_settings: MagicMock) -> None:
        """A key that does not match the configured one fails timing-safe comparison: not
        authenticated and bot_api_key_valid stays False."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = "correct-key"  # pragma: allowlist secret

        resp = await _get(
            app,
            headers={
                "X-Bot-API-Key": "wrong-key",
                "X-Bot-Platform": "discord",
                "X-Bot-Platform-User-Id": "disc_1",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is False

    @patch("app.core.bot_auth_middleware.settings")
    async def test_unconfigured_key_is_not_treated_as_valid(self, mock_settings: MagicMock) -> None:
        """When GAIA_BOT_API_KEY is unset, _verify_api_key returns False — an attacker's
        key must NOT be accepted (kills the False->True mutant on the unset guard)."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = None

        resp = await _get(
            app,
            headers={
                "X-Bot-API-Key": "any-key",
                "X-Bot-Platform": "discord",
                "X-Bot-Platform-User-Id": "disc_1",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is False

    async def test_settings_missing_attribute_is_not_valid(self) -> None:
        """If settings has no GAIA_BOT_API_KEY attribute at all, getattr defaults to None
        and the key is rejected."""
        app = _build_app()
        with patch("app.core.bot_auth_middleware.settings", new=MagicMock(spec=[])):
            resp = await _get(app, headers={"X-Bot-API-Key": "any-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is False


# ---------------------------------------------------------------------------
# No auth headers / precedence
# ---------------------------------------------------------------------------


class TestNoAuthAndPrecedence:
    async def test_no_auth_headers_unauthenticated(self) -> None:
        app = _build_app()
        resp = await _get(app)
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["user"] is None
        assert data["bot_api_key_valid"] is False

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    @patch("app.core.bot_auth_middleware.settings")
    async def test_jwt_wins_over_api_key_and_skips_api_path(
        self,
        mock_settings: MagicMock,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """When both a valid JWT and a valid API key with a DIFFERENT platform are present,
        JWT auth wins (discord) and the API-key fallback never runs — so bot_platform is
        NOT overwritten with the API-key's slack value. Anchors the `not authenticated`
        gate on the fallback."""
        app = _build_app()
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_verify.return_value = FAKE_JWT_PAYLOAD  # discord
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        resp = await _get(
            app,
            headers={
                "Authorization": "Bearer jwt-token",
                "X-Bot-API-Key": "secret-bot-key",  # pragma: allowlist secret
                "X-Bot-Platform": "slack",
                "X-Bot-Platform-User-Id": "slack_1",
            },
        )

        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["auth_provider"] == "bot:discord"
        # API-key fallback skipped -> no slack crumbs, single DB lookup (the JWT one).
        assert data["bot_platform"] is None
        mock_platform.assert_awaited_once_with("discord", "disc_999")
