"""PostHog attribution of unhandled exceptions.

``PostHogRequestContextMiddleware`` identifies inside ``with new_context():``
wrapped around ``call_next``. An exception propagating out of it unwinds that
context *before* the handler in ``ServerErrorMiddleware`` runs, so a capture
that relies on the context lands on a fresh anonymous profile — a crash nobody
can trace to the user who hit it. These pin the explicit attribution.
"""

from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
import pytest
from pytest_mock import MockerFixture

from app.core.app_factory import create_app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def _app_with_boom_route(mocker: MockerFixture, user: dict[str, Any] | None) -> FastAPI:
    """An app whose only route authenticates, then raises.

    The user is set inside the ROUTE, not an outer middleware:
    ``WorkOSAuthMiddleware`` resets ``request.state.user = None`` at the top of
    its dispatch (auth.py:148), so anything seeded outside it is wiped before
    the route runs. Setting it here is also the faithful model — an
    authenticated request that then crashes.
    """
    mocker.patch("app.core.app_factory.providers.is_available", return_value=True)
    app = create_app()

    @app.get("/boom")
    async def _boom(request: Request) -> None:
        if user is not None:
            request.state.user = user
        raise RuntimeError("db down")

    return app


@pytest.mark.asyncio
async def test_unhandled_exception_is_attributed_to_the_authenticated_user(
    mocker: MockerFixture,
) -> None:
    posthog_client = MagicMock()
    mocker.patch("app.core.app_factory.providers.get", return_value=posthog_client)
    app = _app_with_boom_route(mocker, {"user_id": "uid1"})

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
    mocker: MockerFixture,
) -> None:
    """An anonymous crash must still reach error tracking — dropping it would
    hide every failure on the public surface."""
    posthog_client = MagicMock()
    mocker.patch("app.core.app_factory.providers.get", return_value=posthog_client)
    app = _app_with_boom_route(mocker, None)

    async with _client(app) as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    posthog_client.capture_exception.assert_called_once()
    assert "distinct_id" not in posthog_client.capture_exception.call_args.kwargs


@pytest.mark.asyncio
async def test_missing_posthog_provider_still_returns_the_json_500(
    mocker: MockerFixture,
) -> None:
    """Apps built without the production lifespan have no provider; a raising
    handler would turn the JSON body into a bare Starlette 500."""
    mocker.patch("app.core.app_factory.providers.is_available", return_value=False)
    app = create_app()

    @app.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("db down")

    async with _client(app) as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"error": "internal_server_error"}
