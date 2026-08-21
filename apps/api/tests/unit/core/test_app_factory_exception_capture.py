"""PostHog attribution of unhandled exceptions.

``PostHogRequestContextMiddleware`` identifies inside ``with new_context():``
wrapped around ``call_next``. An exception propagating out of it unwinds that
context *before* the handler in ``ServerErrorMiddleware`` runs, so a capture
that relies on the context lands on a fresh anonymous profile — a crash nobody
can trace to the user who hit it. These pin the explicit attribution.

The provider goes through the real ``providers`` registry rather than a patch:
the lookup key ``"posthog"`` is part of what is under test — under any other
key the registry finds nothing and every crash goes uncaptured.
"""

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
import pytest

from app.core.app_factory import create_app


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _cors_only_middleware(app: FastAPI) -> None:
    """The conftest's hermetic stack: no Redis, no WorkOS.

    `create_app()` raw installs Redis-backed middleware, so on a runner without
    Redis a ConnectionError surfaces before the route is reached and the handler
    under test sees the wrong exception entirely.
    """
    app.add_middleware(CORSMiddleware, allow_origins=["*"])


def _hermetic_app() -> FastAPI:
    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch("app.core.app_factory.configure_middleware", _cors_only_middleware),
    ):
        return create_app()


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def _app_with_boom_route(user: dict[str, Any] | None) -> FastAPI:
    """An app whose only route authenticates, then raises.

    The user is set inside the ROUTE, not an outer middleware:
    ``WorkOSAuthMiddleware`` resets ``request.state.user = None`` at the top of
    its dispatch (auth.py:148), so anything seeded outside it is wiped before
    the route runs. Setting it here is also the faithful model — an
    authenticated request that then crashes.
    """
    app = _hermetic_app()

    @app.get("/boom")
    async def _boom(request: Request) -> None:
        if user is not None:
            request.state.user = user
        raise RuntimeError("db down")

    return app


@pytest.mark.asyncio
async def test_unhandled_exception_is_attributed_to_the_authenticated_user(
    posthog_provider: Callable[..., None],
) -> None:
    posthog_client = MagicMock()
    posthog_provider(available=True, client=posthog_client)
    app = _app_with_boom_route({"user_id": "uid1"})

    async with _client(app) as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"error": "internal_server_error"}
    posthog_client.capture_exception.assert_called_once()
    args, kwargs = posthog_client.capture_exception.call_args
    assert isinstance(args[0], RuntimeError)
    assert kwargs["distinct_id"] == "uid1"


@pytest.mark.asyncio
async def test_unauthenticated_crash_is_still_captured_without_an_id(
    posthog_provider: Callable[..., None],
) -> None:
    """An anonymous crash must still reach error tracking — dropping it would
    hide every failure on the public surface."""
    posthog_client = MagicMock()
    posthog_provider(available=True, client=posthog_client)
    app = _app_with_boom_route(None)

    async with _client(app) as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    posthog_client.capture_exception.assert_called_once()
    args, kwargs = posthog_client.capture_exception.call_args
    assert isinstance(args[0], RuntimeError)
    assert "distinct_id" not in kwargs


@pytest.mark.asyncio
async def test_unavailable_posthog_provider_still_returns_the_json_500(
    posthog_provider: Callable[..., None],
) -> None:
    """Apps built without the production lifespan have no usable provider; a
    raising handler would turn the JSON body into a bare Starlette 500."""
    posthog_client = MagicMock()
    posthog_provider(available=False, client=posthog_client)
    app = _app_with_boom_route({"user_id": "uid1"})

    async with _client(app) as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"error": "internal_server_error"}
    posthog_client.capture_exception.assert_not_called()
