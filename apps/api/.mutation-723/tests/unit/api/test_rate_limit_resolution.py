"""@tiered_rate_limit must enforce regardless of what the auth param is named.

Regression cover for a silent failure: the decorator used to resolve the caller
by looking for a kwarg literally named ``user``, so an endpoint that named it
``current_user``/``user_id``/``_user`` skipped rate limiting entirely — no log,
no error, just unlimited access. These tests drive real routes through the real
``WorkOSAuthMiddleware`` and assert the limiter actually fired.
"""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.core.request_context import set_authenticated_user
from app.decorators import tiered_rate_limit

USER = {"user_id": "u1", "email": "a@b.c"}


def _build_app() -> FastAPI:
    """Routes whose auth parameter is named four different ways."""
    app = FastAPI()

    @app.middleware("http")
    async def fake_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Stands in for WorkOSAuthMiddleware: set request.state.user, then mirror
        # it into the ContextVar before call_next, exactly as the real one does.
        request.state.user = USER
        request.state.authenticated = True
        set_authenticated_user(USER)
        return await call_next(request)

    @app.get("/named-user")
    @tiered_rate_limit("generate_image")
    async def named_user(user: dict = Depends(get_current_user)) -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/named-current-user")
    @tiered_rate_limit("generate_image")
    async def named_current_user(current_user: dict = Depends(get_current_user)) -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/named-underscore-user")
    @tiered_rate_limit("generate_image")
    async def named_underscore_user(_user: dict = Depends(get_current_user)) -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/named-user-id")
    @tiered_rate_limit("generate_image")
    async def named_user_id(user_id: str = Depends(get_user_id)) -> dict[str, str]:
        return {"ok": "1"}

    @app.get("/public")
    @tiered_rate_limit("generate_image")
    async def public_route() -> dict[str, str]:
        return {"ok": "1"}

    return app


@pytest.mark.asyncio
class TestRateLimitParamNameIndependence:
    @pytest.mark.parametrize(
        "path",
        ["/named-user", "/named-current-user", "/named-underscore-user", "/named-user-id"],
    )
    async def test_limiter_fires_regardless_of_param_name(self, path: str) -> None:
        app = _build_app()
        with (
            patch(
                "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
                new_callable=AsyncMock,
            ) as fired,
            patch(
                "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
            ) as sub,
        ):
            sub.return_value.plan_type = None
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(path)

            assert resp.status_code == 200
            assert fired.called, f"rate limit silently skipped for route {path}"
            assert fired.call_args.kwargs["user_id"] == "u1"

    async def test_public_route_without_auth_is_not_limited(self) -> None:
        """A route with nobody authenticated has no one to bill — still skipped."""
        app = FastAPI()

        @app.get("/anon")
        @tiered_rate_limit("generate_image")
        async def anon() -> dict[str, str]:
            return {"ok": "1"}

        set_authenticated_user(None)
        with patch(
            "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
        ) as fired:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/anon")

            assert resp.status_code == 200
            assert not fired.called


def test_no_duplicate_decorator_remains() -> None:
    """The drifted second copy in the middleware module must stay deleted."""
    from app.api.v1.middleware import tiered_rate_limiter as middleware_mod

    assert not hasattr(middleware_mod, "tiered_rate_limit"), (
        "A second tiered_rate_limit implementation reappeared in the middleware "
        "module; endpoints importing it would silently skip rate limiting."
    )


@pytest.mark.asyncio
async def test_route_without_an_auth_dependency_is_still_limited() -> None:
    """Auth comes from the middleware, not the handler's signature.

    ``search_email_endpoint`` takes only ``query: str`` — no auth dependency at
    all — yet it sits behind the global auth middleware and carries a
    ``web_search`` limit. Resolving the caller from the request context (rather
    than the handler's kwargs) is what lets that route be billed.
    """
    app = FastAPI()

    @app.middleware("http")
    async def fake_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.user = USER
        request.state.authenticated = True
        set_authenticated_user(USER)
        return await call_next(request)

    @app.get("/no-auth-param")
    @tiered_rate_limit("web_search")
    async def no_auth_param(query: str) -> dict[str, str]:
        return {"ok": query}

    with (
        patch(
            "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
        ) as fired,
        patch(
            "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
        ) as sub,
    ):
        sub.return_value.plan_type = None
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/no-auth-param", params={"query": "x"})

        assert resp.status_code == 200
        assert fired.called
        assert fired.call_args.kwargs["user_id"] == "u1"
